#!/usr/bin/env bash
# anchors.sh — deterministic source-anchor drift detector for modeled levels.
#
# A modeled level claims fidelity by citing source `file:line` anchors in its
# var<->code map (02_models/*.tla) and its 00_input.md.  This script records the
# *exact text* at each cited line (as a sha256) into a per-level lock file, then
# later re-reads those lines and flags any whose text changed.  It is the
# deterministic, no-LLM tripwire that CI Tier 1 uses to decide when a model may
# have drifted out from under the code (the LLM `sync` command does the real
# semantic re-anchoring; this just narrows when that's worth running).
#
# Usage (the stable contract references/ci-integration.md depends on):
#   anchors.sh update <workspace-dir> [filter ...]   # (re)baseline anchors.lock
#   anchors.sh check  <workspace-dir> [filter ...]   # exit 1 + list drift if changed
#
# Anchor forms scanned (PATH is a source path resolved against REPO_ROOT):
#   PATH:LINE        e.g. src/foo/bar.cc:42
#   PATH:START-END   e.g. src/foo/bar.cc:42-48
#
# Acceleration design:
#   - Uses a single-process Python 3 engine when python3 is available:
#       1. Single pruned REPO_ROOT walk (skipping .git, target, node_modules, etc.)
#          to build an O(1) suffix-resolution index instead of per-anchor `find`.
#       2. In-memory file line + SHA-256 memoization across all levels instead of
#          spawning `awk` + `shasum` per cited line (~250,000 subprocesses saved).
#       3. Parallel level evaluation via ThreadPoolExecutor with deterministic
#          sorted output and idempotent `update` (leaves existing anchors.lock
#          untouched when its sorted `(path, line, sha)` rows are unchanged).
#   - Falls back cleanly to POSIX/macOS bash 3.2 (`sha256sum` preferred over Perl
#     `shasum`) when python3 is unavailable.
set -uo pipefail

PROG="anchors.sh"
warn(){ echo "$PROG: $*" >&2; }
die(){ echo "$PROG: $*" >&2; exit 2; }

usage(){
  cat >&2 <<EOF
usage: $PROG <update|check> <workspace-dir> [filter ...]
  update   (re)baseline — write 02_models/anchors.lock for every modeled level
  check    re-read cited lines; exit 1 and list drift if any cited line changed
EOF
  exit 2
}

[[ $# -ge 2 ]] || usage
CMD="$1"; WS="$2"; shift 2
FILTERS=("$@")
case "$CMD" in update|check) : ;; *) usage ;; esac
[[ -d "$WS" ]] || die "no such workspace dir: $WS"
WS_ABS="$(cd "$WS" && pwd)"

# ---- REPO_ROOT comes from the workspace config.env (written by install_tlc.sh) ----
CONFIG="$WS_ABS/config.env"
[[ -f "$CONFIG" ]] || die "no config.env in workspace ($CONFIG) — run '/vibe-tla init' first"
# shellcheck disable=SC1090
source "$CONFIG" 2>/dev/null || true
REPO_ROOT="${REPO_ROOT:-}"
[[ -n "$REPO_ROOT" && -d "$REPO_ROOT" ]] || die "REPO_ROOT not set/usable in $CONFIG"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  exec python3 - "$PROG" "$CMD" "$WS_ABS" "$REPO_ROOT" ${FILTERS[@]+"${FILTERS[@]}"} <<'PY'
import concurrent.futures
import datetime as dt
import hashlib
import os
import re
import sys
from pathlib import Path

prog = sys.argv[1]
cmd = sys.argv[2]
ws_abs = Path(sys.argv[3])
repo_root = Path(sys.argv[4])
filters = sys.argv[5:]

TOKEN_RE = re.compile(r"[A-Za-z0-9._/-]+:[0-9]+(?:-[0-9]+)?")
REV_RE = re.compile(r"^(.*)_v([0-9]+)$")
PRUNE_DIRS = {
    ".git",
    "target",
    "node_modules",
    ".build",
    "dist",
    "vendor",
    ".tools",
    "_apalache-out",
    ".venv",
    "__pycache__",
}


def warn(msg: str) -> None:
    print(f"{prog}: {msg}", file=sys.stderr)


def find_levels() -> list[Path]:
    levels: set[Path] = set()
    for top in sorted(ws_abs.iterdir()):
        if not top.is_dir() or not top.name.endswith("_models"):
            continue
        for fam in sorted(top.iterdir()):
            if not fam.is_dir():
                continue
            for lvl in sorted(fam.iterdir()):
                if lvl.is_dir() and lvl.name.startswith("L") and (lvl / "02_models").is_dir():
                    rel = str(lvl.relative_to(ws_abs))
                    if not filters or any(flt in rel for flt in filters):
                        levels.add(lvl)
    return sorted(levels)


levels = find_levels()
if not levels:
    print(f"{prog}: no modeled levels under {ws_abs} (looked for */*_models/*/L*/02_models)")
    print("nothing to check")
    sys.exit(0)

# Lazy-built suffix index over REPO_ROOT (constructed at most once across all levels).
_suffix_lock = __import__("threading").Lock()
_all_repo_files: list[str] | None = None
_basename_map: dict[str, list[str]] | None = None


def ensure_repo_index() -> tuple[list[str], dict[str, list[str]]]:
    global _all_repo_files, _basename_map
    if _all_repo_files is not None and _basename_map is not None:
        return _all_repo_files, _basename_map
    with _suffix_lock:
        if _all_repo_files is None or _basename_map is None:
            files: list[str] = []
            bmap: dict[str, list[str]] = {}
            root_str = str(repo_root)
            for dirpath, dirnames, filenames in os.walk(root_str):
                dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
                rel_dir = os.path.relpath(dirpath, root_str)
                prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
                for fn in filenames:
                    rel_f = prefix + fn
                    files.append(rel_f)
                    bmap.setdefault(fn, []).append(rel_f)
            _all_repo_files = files
            _basename_map = bmap
    return _all_repo_files, _basename_map


# Thread-safe cache of split raw lines + per-line SHA-256 hex digests.
_file_lock = __import__("threading").Lock()
_file_lines: dict[str, list[bytes] | None] = {}
_line_shas: dict[tuple[str, int], str] = {}


def get_file_lines(rel_path: str) -> list[bytes] | None:
    if rel_path in _file_lines:
        return _file_lines[rel_path]
    abs_p = repo_root / rel_path
    try:
        raw = abs_p.read_bytes()
    except OSError:
        with _file_lock:
            _file_lines[rel_path] = None
        return None
    if not raw:
        lines: list[bytes] = []
    else:
        parts = raw.split(b"\n")
        if raw.endswith(b"\n"):
            parts.pop()
        lines = parts
    with _file_lock:
        _file_lines.setdefault(rel_path, lines)
        return _file_lines[rel_path]


def get_line_sha(rel_path: str, line_no: int) -> str | None:
    key = (rel_path, line_no)
    cached = _line_shas.get(key)
    if cached is not None:
        return cached
    lines = get_file_lines(rel_path)
    if lines is None or line_no < 1 or line_no > len(lines):
        return None
    digest = hashlib.sha256(lines[line_no - 1]).hexdigest()
    _line_shas[key] = digest
    return digest


def resolve_path(cited: str) -> tuple[int, str]:
    direct = repo_root / cited
    if direct.is_file():
        return (0, cited)
    _, bmap = ensure_repo_index()
    base = cited.rsplit("/", 1)[-1]
    cands = bmap.get(base, [])
    needle = "/" + cited.lstrip("/")
    matches = [f for f in cands if f == cited or f.endswith(needle)]
    if not matches:
        return (1, "")
    if len(matches) > 1:
        return (2, "")
    return (0, matches[0])


def extract_anchors(doc_path: Path) -> set[tuple[str, int, int]]:
    out: set[tuple[str, int, int]] = set()
    try:
        txt = doc_path.read_text(errors="replace")
    except OSError:
        return out
    for tok in TOKEN_RE.findall(txt):
        path, loc = tok.rsplit(":", 1)
        if "/" not in path and "." not in path:
            continue
        if "-" in loc:
            a_s, b_s = loc.split("-", 1)
        else:
            a_s = b_s = loc
        if not (a_s.isdigit() and b_s.isdigit()):
            continue
        a, b = int(a_s), int(b_s)
        if a >= 1 and b >= a:
            out.add((path, a, b))
    return out


def compute_level_rows(level: Path) -> tuple[list[str], list[str]]:
    rel_lvl = str(level.relative_to(ws_abs))
    warnings: list[str] = []
    best_ver: dict[str, int] = {}
    best_path: dict[str, Path] = {}
    has_revision = False

    for t in sorted((level / "02_models").glob("*.tla")):
        if not t.is_file():
            continue
        base = t.stem
        if base.endswith("_Unsafe"):
            continue
        m = REV_RE.match(base)
        if m:
            stem, ver = m.group(1), int(m.group(2))
            has_revision = True
        else:
            stem, ver = base, 1
        if stem not in best_ver or ver > best_ver[stem]:
            best_ver[stem] = ver
            best_path[stem] = t

    sources: list[Path] = [best_path[s] for s in sorted(best_path)]
    input_md = level / "00_input.md"
    if not has_revision and input_md.exists():
        sources.append(input_md)
    if not sources:
        return ([], warnings)

    anchors: set[tuple[str, int, int]] = set()
    for src in sources:
        anchors.update(extract_anchors(src))
    if not anchors:
        return ([], warnings)

    rows_set: set[str] = set()
    for cited_path, a, b in sorted(anchors):
        rc, resolved = resolve_path(cited_path)
        if rc == 0:
            if resolved != cited_path:
                warnings.append(
                    f"anchor {cited_path} resolved by suffix to {resolved} [level: {rel_lvl}] — prefer repo-relative citations"
                )
        elif rc == 2:
            warnings.append(
                f"ambiguous anchor: {cited_path} matches several files under REPO_ROOT — cite it repo-relative [level: {rel_lvl}]"
            )
            continue
        else:
            warnings.append(
                f"unresolved anchor: {cited_path} (not under REPO_ROOT) [level: {rel_lvl}]"
            )
            continue

        lines = get_file_lines(resolved)
        n_lines = 0 if lines is None else len(lines)
        for ln in range(a, b + 1):
            if ln <= n_lines:
                sha = get_line_sha(resolved, ln)
                if sha is not None:
                    rows_set.add(f"{resolved}\t{ln}\t{sha}")
                    continue
            warnings.append(
                f"out-of-range anchor: {resolved}:{ln} (file has fewer lines) [level: {rel_lvl}]"
            )

    # Sort identically to LC_ALL/bytewise TSV sort used by anchors.lock
    return (sorted(rows_set), warnings)


max_workers = min(16, max(1, os.cpu_count() or 4), len(levels))

if cmd == "update":
    wrote = 0
    tracked = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        computed = list(pool.map(compute_level_rows, levels))

    for level, (rows, warnings) in zip(levels, computed):
        for w in warnings:
            warn(w)
        rel_lvl = str(level.relative_to(ws_abs))
        lock = level / "02_models" / "anchors.lock"
        rel_lock = str(lock.relative_to(ws_abs))
        if not rows:
            if lock.is_file():
                lock.unlink()
            print(f"  -  {rel_lvl}: no resolvable anchors (no lock written)")
            continue

        # Preserve existing anchors.lock byte-for-byte when sorted anchor rows match,
        # avoiding spurious timestamp-only diffs across untouched levels.
        existing_rows: list[str] | None = None
        if lock.is_file():
            try:
                existing_rows = [
                    ln for ln in lock.read_text(errors="replace").splitlines()
                    if ln and not ln.startswith("#")
                ]
            except OSError:
                existing_rows = None

        if existing_rows != rows:
            stamp = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            header = (
                f"# anchors.lock — written by anchors.sh update on {stamp}\n"
                "# path<TAB>line<TAB>sha256(of that line's current text)  — re-read with 'anchors.sh check'\n"
            )
            lock.write_text(header + "\n".join(rows) + "\n")

        n = len(rows)
        print(f"  ok {rel_lvl}: {n} line anchor(s) -> {rel_lock}")
        wrote += 1
        tracked += n

    print(
        f"{prog} update: baselined {wrote} level(s); {tracked} line(s) tracked "
        "(unresolved/out-of-range anchors warned above, not failed)"
    )
    sys.exit(0)


def check_one_level(level: Path) -> tuple[bool, int, int, list[str], list[str]]:
    lock = level / "02_models" / "anchors.lock"
    rel_lvl = str(level.relative_to(ws_abs))
    if not lock.is_file():
        rows, _ = compute_level_rows(level)
        warns = []
        if rows:
            warns.append(f"no anchors.lock for {rel_lvl} — run 'anchors.sh update' to baseline it")
        return (False, 0, 0, [], warns)

    checked = 0
    changed = 0
    drifts: list[str] = []
    for raw_ln in lock.read_text(errors="replace").splitlines():
        if not raw_ln or raw_ln.startswith("#"):
            continue
        parts = raw_ln.split("\t")
        if len(parts) < 3:
            continue
        path, line_s, oldsha = parts[0], parts[1], parts[2]
        if not line_s or not oldsha or not line_s.isdigit():
            continue
        ln = int(line_s)
        checked += 1
        lines = get_file_lines(path)
        if lines is None:
            drifts.append(f"DRIFT  {path}:{ln}   [{rel_lvl}]  (file no longer exists)")
            changed += 1
            continue
        if ln < 1 or ln > len(lines):
            drifts.append(f"DRIFT  {path}:{ln}   [{rel_lvl}]  (line no longer exists)")
            changed += 1
            continue
        newsha = get_line_sha(path, ln)
        if newsha != oldsha:
            drifts.append(f"DRIFT  {path}:{ln}   [{rel_lvl}]")
            changed += 1
    return (True, checked, changed, drifts, [])


with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
    results = list(pool.map(check_one_level, levels))

locks = 0
missing_lock = 0
checked_total = 0
changed_total = 0

for has_lock, checked, changed, drifts, warns in results:
    for w in warns:
        warn(w)
        missing_lock += 1
    if not has_lock:
        continue
    locks += 1
    checked_total += checked
    changed_total += changed
    for d in drifts:
        print(d)

if locks == 0:
    print(f"{prog} check: no anchors.lock found — run 'anchors.sh update' first")
    if missing_lock > 0:
        print(f"  ({missing_lock} level(s) have anchors but no lock)")
    print("nothing to check")
    sys.exit(0)

print(f"{prog} check: {checked_total} anchor line(s) across {locks} lock(s); {changed_total} changed")
if changed_total > 0:
    print("code drifted from the model at the lines above — run '/vibe-tla sync <keywords>' to re-anchor")
    sys.exit(1)
print("no drift — cited lines unchanged since baseline")
sys.exit(0)
PY
fi

# ---- Pure-shell fallback when python3 is unavailable (prefer C sha256sum over Perl shasum) ----
if command -v sha256sum >/dev/null 2>&1; then
  SHA(){ sha256sum | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  SHA(){ shasum -a 256 | awk '{print $1}'; }
else
  die "need 'sha256sum' or 'shasum -a 256' on PATH"
fi

slice(){
  local f="$1" a="$2" b="$3"
  awk -v a="$a" -v b="$b" '
    NR>=a && NR<=b { print; seen++ }
    END { if (seen != (b - a + 1)) exit 3 }
  ' "$f"
}

extract_anchors(){
  local f="$1"
  grep -oE '[A-Za-z0-9._/-]+:[0-9]+(-[0-9]+)?' "$f" 2>/dev/null | while IFS= read -r tok; do
    local loc path a b
    loc="${tok##*:}"
    path="${tok%:*}"
    case "$path" in
      */*|*.*) : ;;
      *) continue ;;
    esac
    case "$loc" in
      *-*) a="${loc%-*}"; b="${loc#*-}" ;;
      *)   a="$loc"; b="$loc" ;;
    esac
    [[ "$a" =~ ^[0-9]+$ && "$b" =~ ^[0-9]+$ ]] || continue
    [[ "$a" -ge 1 && "$b" -ge "$a" ]] || continue
    printf '%s\t%s\t%s\n' "$path" "$a" "$b"
  done
}

resolve_path(){
  local path="$1" matches n
  if [[ -f "$REPO_ROOT/$path" ]]; then printf '%s\n' "$path"; return 0; fi
  matches="$(find "$REPO_ROOT" \( -name .git -o -name target -o -name node_modules -o -name .build -o -name dist -o -name vendor \) -prune -o -type f -path "*/$path" -print 2>/dev/null)"
  [[ -n "$matches" ]] || return 1
  n="$(printf '%s\n' "$matches" | grep -c . || true)"
  [[ "$n" -eq 1 ]] || return 2
  printf '%s\n' "${matches#$REPO_ROOT/}"
}

find_levels(){
  find "$WS_ABS" -type d -name '02_models' -path '*_models/*/L*/02_models' 2>/dev/null \
    | while IFS= read -r m; do dirname "$m"; done | sort -u
}

LEVELS="$(find_levels)"
if [[ -z "$LEVELS" ]]; then
  echo "$PROG: no modeled levels under $WS_ABS (looked for */*_models/*/L*/02_models)"
  echo "nothing to check"
  exit 0
fi

compute_level_rows(){
  local level="$1"
  local sources=() has_revision=0 tag t
  local live_tlas
  live_tlas="$(
    for t in "$level"/02_models/*.tla; do
      [[ -e "$t" ]] && printf '%s\n' "$t"
    done | awk '
      {
        path = $0
        base = path; sub(/^.*\//, "", base); sub(/\.tla$/, "", base)
        if (base ~ /_Unsafe$/) next
        ver = 1; stem = base
        if (match(base, /_v[0-9]+$/)) {
          ver = substr(base, RSTART + 2) + 0
          stem = substr(base, 1, RSTART - 1)
          rev = 1
        }
        if (!(stem in best_ver) || ver > best_ver[stem]) {
          best_ver[stem] = ver
          best_path[stem] = path
        }
      }
      END {
        for (s in best_path) print (rev ? "R\t" : "B\t") best_path[s]
      }
    ' | sort
  )"
  if [[ -n "$live_tlas" ]]; then
    while IFS=$'\t' read -r tag t; do
      [[ -n "$t" ]] || continue
      [[ "$tag" == "R" ]] && has_revision=1
      sources+=("$t")
    done <<EOF
$live_tlas
EOF
  fi
  if [[ "$has_revision" -eq 0 && -e "$level/00_input.md" ]]; then
    sources+=("$level/00_input.md")
  fi
  [[ ${#sources[@]} -gt 0 ]] || return 0

  local anchors
  anchors="$(
    for t in "${sources[@]}"; do extract_anchors "$t"; done | sort -u
  )"
  [[ -n "$anchors" ]] || return 0

  local path a b absf ln text sha rel rc
  {
    while IFS=$'\t' read -r path a b; do
      [[ -n "$path" ]] || continue
      if rel="$(resolve_path "$path")"; then
        if [[ "$rel" != "$path" ]]; then
          warn "anchor $path resolved by suffix to $rel [level: ${level#$WS_ABS/}] — prefer repo-relative citations"
          path="$rel"
        fi
      else
        rc=$?
        if [[ "$rc" -eq 2 ]]; then
          warn "ambiguous anchor: $path matches several files under REPO_ROOT — cite it repo-relative [level: ${level#$WS_ABS/}]"
        else
          warn "unresolved anchor: $path (not under REPO_ROOT) [level: ${level#$WS_ABS/}]"
        fi
        continue
      fi
      absf="$REPO_ROOT/$path"
      ln="$a"
      while [[ "$ln" -le "$b" ]]; do
        if text="$(slice "$absf" "$ln" "$ln")"; then
          sha="$(printf '%s' "$text" | SHA)"
          printf '%s\t%s\t%s\n' "$path" "$ln" "$sha"
        else
          warn "out-of-range anchor: $path:$ln (file has fewer lines) [level: ${level#$WS_ABS/}]"
        fi
        ln=$((ln+1))
      done
    done <<EOF
$anchors
EOF
  } | sort -t"$(printf '\t')" -u
}

if [[ "$CMD" == "update" ]]; then
  WROTE=0; TRACKED=0
  while IFS= read -r level; do
    [[ -n "$level" ]] || continue
    rows="$(compute_level_rows "$level")"
    lock="$level/02_models/anchors.lock"
    if [[ -z "$rows" ]]; then
      [[ -f "$lock" ]] && rm -f "$lock"
      echo "  -  ${level#$WS_ABS/}: no resolvable anchors (no lock written)"
      continue
    fi
    if [[ ! -f "$lock" ]] || [[ "$(grep -v '^#' "$lock" | grep -v '^$')" != "$rows" ]]; then
      {
        echo "# anchors.lock — written by anchors.sh update on $(date '+%Y-%m-%dT%H:%M:%S')"
        echo "# path<TAB>line<TAB>sha256(of that line's current text)  — re-read with 'anchors.sh check'"
        printf '%s\n' "$rows"
      } > "$lock"
    fi
    n="$(printf '%s\n' "$rows" | grep -c . || true)"
    echo "  ok ${level#$WS_ABS/}: $n line anchor(s) -> ${lock#$WS_ABS/}"
    WROTE=$((WROTE+1)); TRACKED=$((TRACKED+n))
  done <<EOF
$LEVELS
EOF
  echo "$PROG update: baselined $WROTE level(s); $TRACKED line(s) tracked (unresolved/out-of-range anchors warned above, not failed)"
  exit 0
fi

CHANGED=0; CHECKED=0; LOCKS=0; MISSING_LOCK=0
while IFS= read -r level; do
  [[ -n "$level" ]] || continue
  lock="$level/02_models/anchors.lock"
  rel="${level#$WS_ABS/}"
  if [[ ! -f "$lock" ]]; then
    if [[ -n "$(compute_level_rows "$level" 2>/dev/null)" ]]; then
      warn "no anchors.lock for $rel — run 'anchors.sh update' to baseline it"
      MISSING_LOCK=$((MISSING_LOCK+1))
    fi
    continue
  fi
  LOCKS=$((LOCKS+1))
  while IFS=$'\t' read -r path line oldsha; do
    case "$path" in '#'*|'') continue ;; esac
    [[ -n "$line" && -n "$oldsha" ]] || continue
    absf="$REPO_ROOT/$path"
    CHECKED=$((CHECKED+1))
    if [[ ! -f "$absf" ]]; then
      echo "DRIFT  $path:$line   [$rel]  (file no longer exists)"
      CHANGED=$((CHANGED+1))
      continue
    fi
    if newtext="$(slice "$absf" "$line" "$line")"; then
      newsha="$(printf '%s' "$newtext" | SHA)"
      if [[ "$newsha" != "$oldsha" ]]; then
        echo "DRIFT  $path:$line   [$rel]"
        CHANGED=$((CHANGED+1))
      fi
    else
      echo "DRIFT  $path:$line   [$rel]  (line no longer exists)"
      CHANGED=$((CHANGED+1))
    fi
  done < "$lock"
done <<EOF
$LEVELS
EOF

if [[ "$LOCKS" -eq 0 ]]; then
  echo "$PROG check: no anchors.lock found — run 'anchors.sh update' first"
  [[ "$MISSING_LOCK" -gt 0 ]] && echo "  ($MISSING_LOCK level(s) have anchors but no lock)"
  echo "nothing to check"
  exit 0
fi

echo "$PROG check: $CHECKED anchor line(s) across $LOCKS lock(s); $CHANGED changed"
if [[ "$CHANGED" -gt 0 ]]; then
  echo "code drifted from the model at the lines above — run '/vibe-tla sync <keywords>' to re-anchor"
  exit 1
fi
echo "no drift — cited lines unchanged since baseline"
exit 0
