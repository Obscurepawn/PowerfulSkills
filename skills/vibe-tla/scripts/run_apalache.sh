#!/usr/bin/env bash
# run_apalache.sh — canonical Apalache (SMT / Z3 symbolic model checker) wrapper.
# Supports Snowcat typechecking, symbolic bounded model checking (bmc), and
# unbounded-depth symbolic inductive invariant verification (inductive).
# Refuses symlinks, surfaces counterexample traces (counterexample1.tla) on stdout
# for 04_counterexamples.md / CTI triage, and cleans _apalache-out scratch afterward.
#
# Usage:
#   run_apalache.sh typecheck <Module.tla> [-- <extra args>]
#   run_apalache.sh bmc       <Module.tla> --inv=<Inv> [--length=10] [--init=Init]
#                             [--next=Next] [--cinit=ConstInit] [--config=Mod.cfg]
#                             [--no-deadlock] [-- <extra args>]
#   run_apalache.sh inductive <Module.tla> --indinv=<IndInv> [--inv=<Safety>]
#                             [--init=Init] [--next=Next] [--cinit=ConstInit]
#                             [-- <extra args>]
set -uo pipefail
die(){ echo "run_apalache.sh: $*" >&2; exit 2; }

[[ $# -ge 2 ]] || die "usage: run_apalache.sh <typecheck|bmc|inductive> <Module.tla> [options]"
MODE="$1"; TLA="$2"; shift 2
case "$MODE" in typecheck|bmc|inductive) : ;; *) die "mode must be typecheck, bmc, or inductive (got: $MODE)" ;; esac
[[ -f "$TLA" ]] || die "no such file: $TLA"
case "$TLA" in *.tla) : ;; *) die "second arg must be the module-named .tla" ;; esac
[[ -L "$TLA" ]] && die "refusing symlink '$TLA' — invoke through the real module-named .tla"

DIR="$(cd "$(dirname "$TLA")" && pwd)"
BASE="$(basename "$TLA")"
MOD="${BASE%.tla}"

INV=""
INDINV=""
INIT="Init"
NEXT="Next"
CINIT=""
CFG=""
LENGTH="10"
NO_DEADLOCK=0
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --inv=*)        INV="${1#*=}" ;;
    --inv)          shift; INV="${1:-}" ;;
    --indinv=*)     INDINV="${1#*=}" ;;
    --indinv)       shift; INDINV="${1:-}" ;;
    --init=*)       INIT="${1#*=}" ;;
    --init)         shift; INIT="${1:-}" ;;
    --next=*)       NEXT="${1#*=}" ;;
    --next)         shift; NEXT="${1:-}" ;;
    --cinit=*)      CINIT="${1#*=}" ;;
    --cinit)        shift; CINIT="${1:-}" ;;
    --config=*)     CFG="${1#*=}" ;;
    --config)       shift; CFG="${1:-}" ;;
    --length=*)     LENGTH="${1#*=}" ;;
    --length)       shift; LENGTH="${1:-}" ;;
    --no-deadlock)  NO_DEADLOCK=1 ;;
    --)             shift; while [[ $# -gt 0 ]]; do EXTRA+=("$1"); shift; done; break ;;
    *)              EXTRA+=("$1") ;;
  esac
  shift
done

# Locate config.env walking upward from the .tla directory.
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

BIN="${APALACHE_BIN:-}"
if [[ -z "$BIN" || ! -x "$BIN" ]]; then
  BIN="$(command -v apalache-mc 2>/dev/null || true)"
fi
if [[ -z "$BIN" || ! -x "$BIN" ]]; then
  WS_HINT="${CONFIG%/config.env}"
  [[ "$WS_HINT" == "$CONFIG" || -z "$WS_HINT" ]] && WS_HINT="<workspace>"
  die "APALACHE_BIN not set/found — run 'scripts/install_apalache.sh $WS_HINT' first"
fi

TIMEOUT_SECS="${APALACHE_TIMEOUT:-${TLC_TIMEOUT:-1800}}"
TIMEOUT_PREFIX=""
if [[ -n "$TIMEOUT_SECS" && "$TIMEOUT_SECS" != "0" ]]; then
  if   command -v timeout  >/dev/null 2>&1; then TIMEOUT_PREFIX="timeout ${TIMEOUT_SECS}"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_PREFIX="gtimeout ${TIMEOUT_SECS}"
  fi
fi

cd "$DIR" || die "cannot cd into $DIR"

cleanup_scratch() {
  local out_dir="$1"
  rm -rf "$out_dir" "$DIR/_apalache-out" 2>/dev/null || true
  rm -f "$DIR/detailed.log" 2>/dev/null || true
}

dump_counterexamples() {
  local out_dir="$1" label="$2"
  local ce
  for ce in $(find "$out_dir" -type f -name 'counterexample1.tla' 2>/dev/null | sort); do
    echo ">>> [$label] SMT counterexample witness ($ce):"
    cat "$ce"
    echo ">>> [end witness]"
  done
}

run_step() {
  local label="$1"; shift
  local out_dir
  out_dir="$(mktemp -d "$DIR/.apalache_tmp.XXXXXX")"
  echo ">>> Apalache [$label] module=$MOD"
  SECONDS=0
  $TIMEOUT_PREFIX "$BIN" "$@" --out-dir="$out_dir" "$BASE"
  local rc=$?
  [[ "$rc" == 124 && -n "$TIMEOUT_PREFIX" ]] && echo ">>> hit APALACHE_TIMEOUT=${TIMEOUT_SECS}s (exit 124)" >&2
  echo ">>> [$label] elapsed: ${SECONDS}s (exit $rc)"
  if [[ "$rc" -ne 0 ]]; then
    dump_counterexamples "$out_dir" "$label"
  fi
  cleanup_scratch "$out_dir"
  return $rc
}

COMMON_CINIT=()
[[ -n "$CINIT" ]] && COMMON_CINIT+=("--cinit=$CINIT")
if [[ -n "$CFG" ]]; then
  CFG_BASE="$(basename "$CFG")"
  [[ -e "$DIR/$CFG_BASE" ]] || die "config not found next to module: $DIR/$CFG_BASE"
  COMMON_CINIT+=("--config=$CFG_BASE")
fi

case "$MODE" in
  typecheck)
    OUT_TMP="$(mktemp -d "$DIR/.apalache_tmp.XXXXXX")"
    echo ">>> Apalache [typecheck] module=$MOD"
    SECONDS=0
    $TIMEOUT_PREFIX "$BIN" typecheck --out-dir="$OUT_TMP" ${EXTRA[@]+"${EXTRA[@]}"} "$BASE"
    RC=$?
    echo ">>> [typecheck] elapsed: ${SECONDS}s (exit $RC)"
    cleanup_scratch "$OUT_TMP"
    exit $RC
    ;;

  bmc)
    [[ -n "$INV" || -n "$CFG" ]] || die "bmc requires --inv=<Invariant> (or --config=<Mod.cfg>)"
    ARGS=("check")
    [[ ${#COMMON_CINIT[@]} -gt 0 ]] && ARGS+=("${COMMON_CINIT[@]}")
    [[ -n "$INIT" && -z "$CFG" ]] && ARGS+=("--init=$INIT")
    [[ -n "$NEXT" && -z "$CFG" ]] && ARGS+=("--next=$NEXT")
    [[ -n "$INV" ]] && ARGS+=("--inv=$INV")
    ARGS+=("--length=$LENGTH")
    [[ "$NO_DEADLOCK" == 1 ]] && ARGS+=("--no-deadlock")
    [[ ${#EXTRA[@]} -gt 0 ]] && ARGS+=("${EXTRA[@]}")
    run_step "bmc length=$LENGTH" "${ARGS[@]}"
    exit $?
    ;;

  inductive)
    [[ -n "$INDINV" ]] || die "inductive requires --indinv=<InductiveInvariant>"
    # 0. Snowcat static typecheck first so type errors fail fast.
    OUT_TMP="$(mktemp -d "$DIR/.apalache_tmp.XXXXXX")"
    echo ">>> Apalache [inductive:typecheck] module=$MOD"
    $TIMEOUT_PREFIX "$BIN" typecheck --out-dir="$OUT_TMP" "$BASE"
    RC=$?
    cleanup_scratch "$OUT_TMP"
    [[ "$RC" -eq 0 ]] || exit $RC

    # 1. Base case: Init => IndInv  (length=0)
    BASE_ARGS=("check" "--init=$INIT" "--next=$NEXT" "--inv=$INDINV" "--length=0" "--no-deadlock")
    [[ ${#COMMON_CINIT[@]} -gt 0 ]] && BASE_ARGS+=("${COMMON_CINIT[@]}")
    [[ ${#EXTRA[@]} -gt 0 ]] && BASE_ARGS+=("${EXTRA[@]}")
    run_step "inductive:base ($INIT => $INDINV)" "${BASE_ARGS[@]}" || exit $?

    # 2. Inductive step: IndInv /\ Next => IndInv'  (length=1)
    STEP_ARGS=("check" "--init=$INDINV" "--next=$NEXT" "--inv=$INDINV" "--length=1" "--no-deadlock")
    [[ ${#COMMON_CINIT[@]} -gt 0 ]] && STEP_ARGS+=("${COMMON_CINIT[@]}")
    [[ ${#EXTRA[@]} -gt 0 ]] && STEP_ARGS+=("${EXTRA[@]}")
    run_step "inductive:step ($INDINV /\\ $NEXT => ${INDINV}')" "${STEP_ARGS[@]}" || exit $?

    # 3. Property entailment (when target Safety != IndInv): IndInv => Safety  (length=0)
    if [[ -n "$INV" && "$INV" != "$INDINV" ]]; then
      ENT_ARGS=("check" "--init=$INDINV" "--next=$NEXT" "--inv=$INV" "--length=0" "--no-deadlock")
      [[ ${#COMMON_CINIT[@]} -gt 0 ]] && ENT_ARGS+=("${COMMON_CINIT[@]}")
      [[ ${#EXTRA[@]} -gt 0 ]] && ENT_ARGS+=("${EXTRA[@]}")
      run_step "inductive:entailment ($INDINV => $INV)" "${ENT_ARGS[@]}" || exit $?
    fi
    echo ">>> INDUCTIVE PROOF COMPLETE: $INDINV holds at $INIT and is preserved by $NEXT${INV:+ (entailing $INV)}."
    exit 0
    ;;
esac
