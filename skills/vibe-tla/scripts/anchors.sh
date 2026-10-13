#!/usr/bin/env bash
# anchors.sh — EXPERIMENTAL, best-effort drift detector for cited code anchors.
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
#   anchors.sh update <workspace-dir>   # (re)baseline: write each level's anchors.lock
#   anchors.sh check  <workspace-dir>   # re-read anchors; exit 1 + list drift if any changed
#
# Anchor forms scanned (PATH is a source path resolved against REPO_ROOT):
#   PATH:LINE        e.g. src/foo/bar.cc:42
#   PATH:START-END   e.g. src/foo/bar.cc:42-48
#
# CAVEATS (this is best-effort):
#   - It hashes the text AT a line number, so inserting/deleting lines ABOVE an
#     anchor shifts content into it and reads as drift even when the cited code
#     is untouched (a line-shift false positive).  That is intentional for a
#     tripwire: it errs toward flagging.  `sync` confirms or dismisses.
#   - It cannot see semantic drift that leaves the cited line byte-identical.
#   - PATHs that don't resolve under REPO_ROOT are WARNED, not failed (generic
#     repos vary; prefer repo-relative paths so anchors resolve).
#
# macOS bash 3.2 compatible; self-locating.
set -uo pipefail

PROG="anchors.sh"
warn(){ echo "$PROG: $*" >&2; }
die(){ echo "$PROG: $*" >&2; exit 2; }

usage(){
  cat >&2 <<EOF
usage: $PROG <update|check> <workspace-dir>
  update   (re)baseline — write 02_models/anchors.lock for every modeled level
  check    re-read cited lines; exit 1 and list drift if any cited line changed
EOF
  exit 2
}

# ---- sha helper: prefer shasum, fall back to sha256sum ----
if command -v shasum >/dev/null 2>&1; then
  SHA(){ shasum -a 256 | awk '{print $1}'; }
elif command -v sha256sum >/dev/null 2>&1; then
  SHA(){ sha256sum | awk '{print $1}'; }
else
  die "need 'shasum -a 256' or 'sha256sum' on PATH"
fi

[[ $# -ge 2 ]] || usage
CMD="$1"; WS="$2"
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

# ---- extract the cited text for one anchor ----
# Args: <abs-source-file> <start-line> <end-line>.  Echoes the joined text of
# lines [start..end]; non-zero if the range is out of the file's bounds.
slice(){
  local f="$1" a="$2" b="$3"
  awk -v a="$a" -v b="$b" '
    NR>=a && NR<=b { print; seen++ }
    END { if (seen != (b - a + 1)) exit 3 }
  ' "$f"
}

# ---- parse anchors out of a doc and emit "path<TAB>start<TAB>end" lines ----
# Scans for tokens PATH:LINE or PATH:START-END where PATH looks like a source
# path (contains a '/' or a dotted extension) — deliberately loose; unresolved
# paths are handled later as warnings, not parse failures.
extract_anchors(){
  local f="$1"
  # Pull candidate tokens, then validate shape.  grep -oE keeps this bash-3.2 safe.
  grep -oE '[A-Za-z0-9._/-]+:[0-9]+(-[0-9]+)?' "$f" 2>/dev/null | while IFS= read -r tok; do
    local loc path rng a b
    loc="${tok##*:}"          # LINE or START-END
    path="${tok%:*}"          # everything before the last ':'
    # Require something that looks like a file path, not a bare word:line.
    case "$path" in
      */*) : ;;                              # has a directory separator
      *.*) : ;;                              # or a dotted filename (foo.cc)
      *) continue ;;
    esac
    case "$loc" in
      *-*) a="${loc%-*}"; b="${loc#*-}" ;;
      *)   a="$loc"; b="$loc" ;;
    esac
    # numeric + ordered
    [[ "$a" =~ ^[0-9]+$ && "$b" =~ ^[0-9]+$ ]] || continue
    [[ "$a" -ge 1 && "$b" -ge "$a" ]] || continue
    printf '%s\t%s\t%s\n' "$path" "$a" "$b"
  done
}

# ---- resolve a cited path against REPO_ROOT ----
# Echoes the repo-relative path on success.  A path that does not exist as cited
# is retried as a SUFFIX match under REPO_ROOT (levels sometimes cite
# `stats.c:10` for `src/stats.c:10`); it resolves only if exactly one file
# matches — an ambiguous suffix stays unresolved (return 2; cite repo-relative
# paths to avoid this), a missing one returns 1.
resolve_path(){
  local path="$1" matches n
  if [[ -f "$REPO_ROOT/$path" ]]; then printf '%s\n' "$path"; return 0; fi
  matches="$(find "$REPO_ROOT" -type f -path "*/$path" -not -path '*/.git/*' 2>/dev/null)"
  [[ -n "$matches" ]] || return 1
  n="$(printf '%s\n' "$matches" | grep -c . || true)"
  [[ "$n" -eq 1 ]] || return 2
  printf '%s\n' "${matches#$REPO_ROOT/}"
}

# ---- find every modeled level: a dir matching <ws>/*_models/*/L*/ with 02_models ----
find_levels(){
  # -path glob keeps us to the documented layout; print the level dir once.
  find "$WS_ABS" -type d -name '02_models' -path '*_models/*/L*/02_models' 2>/dev/null \
    | while IFS= read -r m; do dirname "$m"; done | sort -u
}

LEVELS="$(find_levels)"
if [[ -z "$LEVELS" ]]; then
  echo "$PROG: no modeled levels under $WS_ABS (looked for */*_models/*/L*/02_models)"
  echo "nothing to check"
  exit 0
fi

# ---- per-level: gather unique (path,line,sha) anchor rows from tla + 00_input.md ----
# Emits, on stdout, deduped TSV rows: path<TAB>line<TAB>sha — one row per *cited
# line* (ranges expand to individual lines, so each line is tracked on its own,
# and a line cited from several docs collapses to one row).  Warnings for
# unresolved / out-of-range anchors go to stderr; the caller tallies from the rows.
compute_level_rows(){
  local level="$1"
  local sources=()
  # the spec(s) and the input doc carry the anchors
  local t
  for t in "$level"/02_models/*.tla; do [[ -e "$t" ]] && sources+=("$t"); done
  [[ -e "$level/00_input.md" ]] && sources+=("$level/00_input.md")
  [[ ${#sources[@]} -gt 0 ]] || return 0

  # collect, dedup anchors across this level's docs
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
  } | sort -t"$(printf '\t')" -u   # one row per distinct (path,line,sha)
}

# =====================================================================
# UPDATE
# =====================================================================
if [[ "$CMD" == "update" ]]; then
  WROTE=0; TRACKED=0
  while IFS= read -r level; do
    [[ -n "$level" ]] || continue
    rows="$(compute_level_rows "$level")"
    lock="$level/02_models/anchors.lock"
    if [[ -z "$rows" ]]; then
      # no resolvable anchors at this level — remove a stale lock so check is honest
      [[ -f "$lock" ]] && rm -f "$lock"
      echo "  -  ${level#$WS_ABS/}: no resolvable anchors (no lock written)"
      continue
    fi
    {
      echo "# anchors.lock — written by anchors.sh update on $(date '+%Y-%m-%dT%H:%M:%S')"
      echo "# path<TAB>line<TAB>sha256(of that line's current text)  — re-read with 'anchors.sh check'"
      printf '%s\n' "$rows"
    } > "$lock"
    n="$(printf '%s\n' "$rows" | grep -c . || true)"
    echo "  ok ${level#$WS_ABS/}: $n line anchor(s) -> ${lock#$WS_ABS/}"
    WROTE=$((WROTE+1)); TRACKED=$((TRACKED+n))
  done <<EOF
$LEVELS
EOF
  echo "$PROG update: baselined $WROTE level(s); $TRACKED line(s) tracked (unresolved/out-of-range anchors warned above, not failed)"
  exit 0
fi

# =====================================================================
# CHECK
# =====================================================================
# Re-read each locked anchor in the CURRENT source; report any whose sha changed.
CHANGED=0
CHECKED=0
LOCKS=0
MISSING_LOCK=0

while IFS= read -r level; do
  [[ -n "$level" ]] || continue
  lock="$level/02_models/anchors.lock"
  rel="${level#$WS_ABS/}"
  if [[ ! -f "$lock" ]]; then
    # A level with anchors but no lock => not baselined.  Note it, don't fail.
    if [[ -n "$(compute_level_rows "$level" 2>/dev/null)" ]]; then
      warn "no anchors.lock for $rel — run 'anchors.sh update' to baseline it"
      MISSING_LOCK=$((MISSING_LOCK+1))
    fi
    continue
  fi
  LOCKS=$((LOCKS+1))
  while IFS=$'\t' read -r path line oldsha; do
    case "$path" in '#'*|'') continue ;; esac     # skip header / blanks
    [[ -n "$line" && -n "$oldsha" ]] || continue
    absf="$REPO_ROOT/$path"
    CHECKED=$((CHECKED+1))
    if [[ ! -f "$absf" ]]; then
      warn "unresolved anchor: $path (no longer under REPO_ROOT) [$rel]"
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
