#!/usr/bin/env bash
# run_tlc.sh — canonical TLC invocation for a level.  Runs the module-named .tla
# (refuses symlinks), isolates per-run metadir and java.io.tmpdir so concurrent
# invocations on sibling .cfg files never collide, times the run, and cleans up.
# Usage:
#   run_tlc.sh <Module.tla> [Module.cfg] [--det] [--coverage[=N]] [--fast-jit]
#              [--classpath <cp>] [--view <Ident>] [--view-def '<Ident> == ...']
#              [-- <extra tlc args>]
#     --det          deterministic run (-workers 1) for citable state counts / trace depth
#     --coverage[=N] enable TLC action coverage (-coverage N, default N=60 so final
#                    coverage is emitted without 1-minute AST cost-tree dumps)
#     --fast-jit     force C1 fast-JIT (-XX:TieredStopAtLevel=1) for <25k-state runs
#     --classpath CP prepend directory/jar of @TLAPlusOperator overrides before tla2tools.jar
#     --view IDENT   inject `VIEW IDENT` into an isolated scratch copy (leaves 02_models/ untouched)
#     --view-def DEF inject operator definition `DEF` before `====` in the scratch copy
# Resolves the toolchain from the nearest config.env (walk up from the .tla dir),
# or env VIBE_TLA_CONFIG, or env TLA_TOOLS_JAR.
set -uo pipefail
die(){ echo "run_tlc.sh: $*" >&2; exit 2; }

[[ $# -ge 1 ]] || die "usage: run_tlc.sh <Module.tla> [Module.cfg] [--det] [--coverage] [--fast-jit] [--classpath CP] [--view IDENT] [-- extra tlc args...]"
TLA="$1"; shift
[[ -f "$TLA" ]] || die "no such file: $TLA"
case "$TLA" in *.tla) : ;; *) die "first arg must be the module-named .tla";; esac
[[ -L "$TLA" ]] && die "refusing symlink '$TLA' — invoke TLC through the real module-named .tla (TLC errors when module name != filename)"

CFG=""
if [[ $# -ge 1 && "${1:-}" == *.cfg ]]; then CFG="$1"; shift; fi

DET=0; COVERAGE=0; COVN=60; FAST_JIT="${TLC_FAST_JIT:-0}"
EXTRA_CP="${TLC_CLASSPATH:-}"; VIEW_IDENT=""; VIEW_DEF=""
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --det)          DET=1 ;;
    --coverage)     COVERAGE=1 ;;
    --coverage=*)   COVERAGE=1; COVN="${1#*=}" ;;
    --fast-jit)     FAST_JIT=1 ;;
    --classpath=*)  EXTRA_CP="${1#*=}" ;;
    --classpath)    shift; EXTRA_CP="${1:-}" ;;
    --view=*)       VIEW_IDENT="${1#*=}" ;;
    --view)         shift; VIEW_IDENT="${1:-}" ;;
    --view-def=*)   VIEW_DEF="${1#*=}" ;;
    --view-def)     shift; VIEW_DEF="${1:-}" ;;
    --)             shift; while [[ $# -gt 0 ]]; do EXTRA+=("$1"); shift; done; break ;;
    *)              EXTRA+=("$1") ;;
  esac
  shift
done
[[ "$COVERAGE" == 1 ]] && EXTRA+=("-coverage" "$COVN")

DIR="$(cd "$(dirname "$TLA")" && pwd)"
BASE="$(basename "$TLA")"
MOD="${BASE%.tla}"
if [[ -n "$CFG" ]]; then CFG="$(basename "$CFG")"; else CFG="$MOD.cfg"; fi
[[ -e "$DIR/$CFG" ]] || die "config not found next to module: $DIR/$CFG"

# Locate config.env.
CONFIG=""
if [[ -n "${VIBE_TLA_CONFIG:-}" && -f "${VIBE_TLA_CONFIG:-}" ]]; then
  CONFIG="$VIBE_TLA_CONFIG"
else
  d="$DIR"
  while [[ "$d" != "/" && -n "$d" ]]; do
    if [[ -f "$d/config.env" ]]; then CONFIG="$d/config.env"; break; fi
    d="$(dirname "$d")"
  done
fi
# shellcheck disable=SC1090
[[ -n "$CONFIG" ]] && source "$CONFIG" 2>/dev/null || true

JAR="${TLA_TOOLS_JAR:-}"
[[ -n "$JAR" && -f "$JAR" ]] || die "TLA_TOOLS_JAR not set/found — run '/vibe-tla init' first (config.env: ${CONFIG:-none})"

# Auto-discover <workspace>/tools/overrides when EXTRA_CP wasn't explicitly set.
if [[ -z "$EXTRA_CP" && -n "$CONFIG" ]]; then
  WS_OVR="$(dirname "$CONFIG")/tools/overrides"
  if [[ -d "$WS_OVR" ]] && [[ -n "$(ls -A "$WS_OVR" 2>/dev/null || true)" ]]; then
    EXTRA_CP="$WS_OVR"
  fi
fi

CP_ARG="$JAR"
if [[ -n "$EXTRA_CP" ]]; then
  CP_ARG="${EXTRA_CP}:${JAR}"
fi

WORKERS="${TLC_WORKERS:-auto}"
# Note: TLC 2.19 `-coverage 1` dumps AST CostModelNode trees every minute, whereas
# `--coverage` (`-coverage 60`) suppresses intermediate dumps and scales cleanly to
# 2..4 workers (`TLC_WORKERS=2..4`) on medium state spaces (50k-2M states). Default
# to 1 worker when `--coverage` is requested unless `TLC_WORKERS` was set.
if [[ "$DET" == 1 ]] || { [[ "$COVERAGE" == 1 ]] && [[ -z "${TLC_WORKERS:-}" ]]; }; then
  WORKERS=1
fi

JVM_FLAGS=("-XX:+UseParallelGC")
if [[ -n "${TLC_MAX_HEAP:-}" ]]; then
  JVM_FLAGS+=("-Xmx${TLC_MAX_HEAP}")
fi
if [[ "$WORKERS" == "1" ]]; then
  JVM_FLAGS+=("-XX:ParallelGCThreads=2" "-XX:ConcGCThreads=1")
else
  JVM_FLAGS+=("-XX:ParallelGCThreads=4" "-XX:ConcGCThreads=2" "-XX:MaxInlineLevel=24" "-XX:FreqInlineSize=512")
fi
if [[ "$FAST_JIT" == "1" ]]; then
  JVM_FLAGS+=("-XX:+TieredCompilation" "-XX:TieredStopAtLevel=1")
fi
if [[ "$WORKERS" != "1" ]] && { [[ "$COVERAGE" == 0 ]] || [[ "${TLC_OFFHEAP_COVERAGE:-0}" == "1" ]]; }; then
  OFFHEAP="${TLC_OFFHEAP_MEM:-2g}"
  JVM_FLAGS+=("-XX:MaxDirectMemorySize=$OFFHEAP" "-Dtlc2.tool.fp.FPSet.impl=tlc2.tool.fp.OffHeapDiskFPSet")
fi

RUN_SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/tlc_run.XXXXXX")"
WORK_DIR="$RUN_SCRATCH/work"
mkdir -p "$WORK_DIR" "$RUN_SCRATCH/states" "$RUN_SCRATCH/java"
trap 'rm -rf "$RUN_SCRATCH" 2>/dev/null || true' EXIT INT TERM

# Stage real files into isolated $WORK_DIR so concurrent sibling runs never race on
# 02_models/ cleanup and scratch VIEW injections never touch committed files.
for f in "$DIR"/*.tla "$DIR"/*.cfg; do
  [[ -e "$f" && ! -L "$f" ]] || continue
  if [[ -n "$VIEW_IDENT" || -n "$VIEW_DEF" ]]; then
    cp "$f" "$WORK_DIR/$(basename "$f")"
  else
    ln "$f" "$WORK_DIR/$(basename "$f")" 2>/dev/null || cp "$f" "$WORK_DIR/$(basename "$f")"
  fi
done

if [[ -n "$VIEW_DEF" ]]; then
  python3 - "$WORK_DIR/$BASE" "$VIEW_DEF" <<'PY' || die "failed to inject --view-def"
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
defn = sys.argv[2].rstrip() + "\n"
txt = p.read_text(errors="replace")
new_txt, n = re.subn(r"^====+", lambda m: defn + m.group(0), txt, count=1, flags=re.M)
if n != 1:
    raise SystemExit("no ==== module terminator found")
p.write_text(new_txt)
PY
fi

if [[ -n "$VIEW_IDENT" ]]; then
  if ! grep -qE '^[[:space:]]*VIEW\b' "$WORK_DIR/$CFG"; then
    printf '\nVIEW %s\n' "$VIEW_IDENT" >> "$WORK_DIR/$CFG"
  fi
fi

echo ">>> TLC module=$MOD cfg=$CFG workers=$WORKERS${VIEW_IDENT:+ view=$VIEW_IDENT}${EXTRA_CP:+ overrides=$EXTRA_CP}"
echo ">>> jar=$JAR"
echo ">>> dir=$DIR"
cd "$WORK_DIR" || die "cannot cd into $WORK_DIR"

TIMEOUT_PREFIX=""
if [[ -n "${TLC_TIMEOUT:-}" && "${TLC_TIMEOUT:-0}" != "0" ]]; then
  if   command -v timeout  >/dev/null 2>&1; then TIMEOUT_PREFIX="timeout ${TLC_TIMEOUT}"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_PREFIX="gtimeout ${TLC_TIMEOUT}"
  else echo ">>> note: TLC_TIMEOUT=${TLC_TIMEOUT}s set but no timeout/gtimeout binary — running unbounded" >&2; fi
fi

SECONDS=0
$TIMEOUT_PREFIX java "-Djava.io.tmpdir=$RUN_SCRATCH/java" "${JVM_FLAGS[@]}" -cp "$CP_ARG" tlc2.TLC \
  -checkpoint 0 -metadir "$RUN_SCRATCH/states" -workers "$WORKERS" -config "$CFG" "$BASE" ${EXTRA[@]+"${EXTRA[@]}"}
STATUS=$?
[[ "$STATUS" == 124 && -n "$TIMEOUT_PREFIX" ]] && echo ">>> hit TLC_TIMEOUT=${TLC_TIMEOUT}s (killed at the wall-clock bound; exit 124)" >&2
echo ">>> elapsed: ${SECONDS}s (exit $STATUS)"

# Clean isolated scratch + any legacy trace artifacts sitting in $DIR.
rm -rf "$RUN_SCRATCH" 2>/dev/null || true
trap - EXIT INT TERM

exit $STATUS
