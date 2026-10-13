#!/usr/bin/env bash
# run_tlc.sh — canonical TLC invocation for a level.  Runs the module-named .tla
# (refuses symlinks), times the run, and cleans scratch afterward.  Usage:
#   run_tlc.sh <Module.tla> [Module.cfg] [--det] [--coverage[=N]] [-- <extra tlc args>]
#     --det          deterministic run (-workers 1) for citable state counts / trace depth
#     --coverage[=N] enable TLC action coverage (-coverage N, default N=1); a 0-coverage
#                    action is dead spec (a guard that never holds / an action never enabled)
# Resolves the toolchain from the nearest config.env (walk up from the .tla dir),
# or env VIBE_TLA_CONFIG, or env TLA_TOOLS_JAR.
set -uo pipefail
die(){ echo "run_tlc.sh: $*" >&2; exit 2; }

[[ $# -ge 1 ]] || die "usage: run_tlc.sh <Module.tla> [Module.cfg] [--det] [extra tlc args...]"
TLA="$1"; shift
[[ -f "$TLA" ]] || die "no such file: $TLA"
case "$TLA" in *.tla) : ;; *) die "first arg must be the module-named .tla";; esac
[[ -L "$TLA" ]] && die "refusing symlink '$TLA' — invoke TLC through the real module-named .tla (TLC errors when module name != filename)"

CFG=""
if [[ $# -ge 1 && "${1:-}" == *.cfg ]]; then CFG="$1"; shift; fi

DET=0; COVERAGE=0; COVN=1; EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --det)        DET=1 ;;
    --coverage)   COVERAGE=1 ;;
    --coverage=*) COVERAGE=1; COVN="${1#*=}" ;;
    --)           shift; while [[ $# -gt 0 ]]; do EXTRA+=("$1"); shift; done; break ;;
    *)            EXTRA+=("$1") ;;
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

WORKERS="${TLC_WORKERS:-auto}"
[[ "$DET" == 1 ]] && WORKERS=1

echo ">>> TLC module=$MOD cfg=$CFG workers=$WORKERS"
echo ">>> jar=$JAR"
echo ">>> dir=$DIR"
cd "$DIR" || die "cannot cd into $DIR"

# Optional wall-clock bound: TLC_TIMEOUT>0 wraps the run in timeout/gtimeout when available.
TIMEOUT_PREFIX=""
if [[ -n "${TLC_TIMEOUT:-}" && "${TLC_TIMEOUT:-0}" != "0" ]]; then
  if   command -v timeout  >/dev/null 2>&1; then TIMEOUT_PREFIX="timeout ${TLC_TIMEOUT}"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_PREFIX="gtimeout ${TLC_TIMEOUT}"
  else echo ">>> note: TLC_TIMEOUT=${TLC_TIMEOUT}s set but no timeout/gtimeout binary — running unbounded" >&2; fi
fi

SECONDS=0
$TIMEOUT_PREFIX java -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers "$WORKERS" -config "$CFG" "$BASE" ${EXTRA[@]+"${EXTRA[@]}"}
STATUS=$?
[[ "$STATUS" == 124 && -n "$TIMEOUT_PREFIX" ]] && echo ">>> hit TLC_TIMEOUT=${TLC_TIMEOUT}s (killed at the wall-clock bound; exit 124)" >&2
echo ">>> elapsed: ${SECONDS}s (exit $STATUS)"

# Scratch cleanup — keep the committed spec/cfg + the markdown record only.
rm -rf "$DIR/states" 2>/dev/null || true
find "$DIR" -maxdepth 1 \( -name '*.out' -o -name '*_TTrace_*' -o -name '*_trace_*.tlc' -o -name 'MC_*' \) -delete 2>/dev/null || true

exit $STATUS
