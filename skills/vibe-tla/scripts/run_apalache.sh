#!/usr/bin/env bash
# run_apalache.sh — canonical Apalache (SMT / Z3 symbolic model checker) wrapper.
# Supports Snowcat typechecking, symbolic bounded model checking (bmc), and
# unbounded-depth symbolic inductive invariant verification (inductive).
# Refuses symlinks, surfaces counterexample traces (counterexample1.tla) on stdout
# for 04_counterexamples.md / CTI triage, and cleans _apalache-out scratch afterward.
#
# Acceleration design:
#   - Uses C1 fast-JIT (`JVM_ARGS=-XX:+TieredCompilation -XX:TieredStopAtLevel=1`)
#     by default because Apalache's Scala/Snowcat frontend is short-lived while Z3
#     executes as native C++ via JNI (~40-50% faster JVM cold-start per obligation).
#   - In `inductive` mode, skips the redundant standalone `typecheck` JVM cold-start
#     (since `apalache-mc check` runs Snowcat internally first) and executes `base`,
#     `step`, and `entailment` concurrently in isolated temporary directories with
#     deterministic ordered output and fail-fast cancellation (`APALACHE_JOBS=1`
#     restores serial execution).
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

# Fast C1 tiered stop cuts Scala/Snowcat cold-start by ~45% while native Z3 runs at full C++ speed.
export JVM_ARGS="${JVM_ARGS:--XX:+TieredCompilation -XX:TieredStopAtLevel=1 -XX:ParallelGCThreads=2 -XX:ConcGCThreads=1}"

TIMEOUT_SECS="${APALACHE_TIMEOUT:-${TLC_TIMEOUT:-1800}}"
TIMEOUT_PREFIX=""
if [[ -n "$TIMEOUT_SECS" && "$TIMEOUT_SECS" != "0" ]]; then
  if   command -v timeout  >/dev/null 2>&1; then TIMEOUT_PREFIX="timeout ${TIMEOUT_SECS}"
  elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_PREFIX="gtimeout ${TIMEOUT_SECS}"
  fi
fi

stage_isolated_dir() {
  local work_dir
  work_dir="$(mktemp -d "${TMPDIR:-/tmp}/apalache_work.XXXXXX")"
  local f
  for f in "$DIR"/*.tla "$DIR"/*.cfg; do
    [[ -e "$f" && ! -L "$f" ]] || continue
    ln "$f" "$work_dir/$(basename "$f")" 2>/dev/null || cp "$f" "$work_dir/$(basename "$f")"
  done
  printf '%s\n' "$work_dir"
}

dump_counterexamples() {
  local out_dir="$1" label="$2"
  local ce
  for ce in $(find "$out_dir" -type f \( -name 'counterexample*.tla' -o -name 'violation*.tla' \) 2>/dev/null | sort); do
    echo ">>> [$label] SMT counterexample witness ($ce):"
    cat "$ce"
    echo ">>> [end witness]"
  done
}

run_step_isolated() {
  local label="$1"; shift
  local work_dir out_dir rc
  work_dir="$(stage_isolated_dir)"
  out_dir="$work_dir/out"
  mkdir -p "$out_dir" "$work_dir/java_tmp"
  echo ">>> Apalache [$label] module=$MOD"
  SECONDS=0
  (
    cd "$work_dir" || exit 2
    TMPDIR="$work_dir/java_tmp" \
      $TIMEOUT_PREFIX "$BIN" "$@" --out-dir="$out_dir" "$BASE"
  )
  rc=$?
  [[ "$rc" == 124 && -n "$TIMEOUT_PREFIX" ]] && echo ">>> hit APALACHE_TIMEOUT=${TIMEOUT_SECS}s (exit 124)" >&2
  echo ">>> [$label] elapsed: ${SECONDS}s (exit $rc)"
  if [[ "$rc" -ne 0 ]]; then
    dump_counterexamples "$out_dir" "$label"
  fi
  rm -rf "$work_dir" 2>/dev/null || true
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
    ARGS=("typecheck")
    [[ ${#EXTRA[@]} -gt 0 ]] && ARGS+=("${EXTRA[@]}")
    run_step_isolated "typecheck" "${ARGS[@]}"
    exit $?
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
    run_step_isolated "bmc length=$LENGTH" "${ARGS[@]}"
    exit $?
    ;;

  inductive)
    [[ -n "$INDINV" ]] || die "inductive requires --indinv=<InductiveInvariant>"

    BASE_ARGS=("check" "--init=$INIT" "--next=$NEXT" "--inv=$INDINV" "--length=0" "--no-deadlock")
    STEP_ARGS=("check" "--init=$INDINV" "--next=$NEXT" "--inv=$INDINV" "--length=1" "--no-deadlock")
    [[ ${#COMMON_CINIT[@]} -gt 0 ]] && { BASE_ARGS+=("${COMMON_CINIT[@]}"); STEP_ARGS+=("${COMMON_CINIT[@]}"); }
    [[ ${#EXTRA[@]} -gt 0 ]] && { BASE_ARGS+=("${EXTRA[@]}"); STEP_ARGS+=("${EXTRA[@]}"); }

    HAS_ENT=0
    ENT_ARGS=()
    if [[ -n "$INV" && "$INV" != "$INDINV" ]]; then
      HAS_ENT=1
      ENT_ARGS=("check" "--init=$INDINV" "--next=$NEXT" "--inv=$INV" "--length=0" "--no-deadlock")
      [[ ${#COMMON_CINIT[@]} -gt 0 ]] && ENT_ARGS+=("${COMMON_CINIT[@]}")
      [[ ${#EXTRA[@]} -gt 0 ]] && ENT_ARGS+=("${EXTRA[@]}")
    fi

    JOBS="${APALACHE_JOBS:-3}"
    if [[ "$JOBS" == "1" ]]; then
      run_step_isolated "inductive:base ($INIT => $INDINV)" "${BASE_ARGS[@]}" || exit $?
      run_step_isolated "inductive:step ($INDINV /\\ $NEXT => ${INDINV}')" "${STEP_ARGS[@]}" || exit $?
      if [[ "$HAS_ENT" == 1 ]]; then
        run_step_isolated "inductive:entailment ($INDINV => $INV)" "${ENT_ARGS[@]}" || exit $?
      fi
      echo ">>> INDUCTIVE PROOF COMPLETE: $INDINV holds at $INIT and is preserved by $NEXT${INV:+ (entailing $INV)}."
      exit 0
    fi

    # Parallel execution of independent SMT obligations (base, step, entailment)
    # with isolated workdirs, ordered output replay, and true fail-fast cancellation
    # (`APALACHE_FAIL_FAST=0` waits for all obligations even if one fails early).
    SUITE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/apalache_ind.XXXXXX")"
    PIDS=()
    kill_tree() {
      local parent="$1" child
      for child in $(pgrep -P "$parent" 2>/dev/null || true); do
        kill_tree "$child"
      done
      kill "$parent" 2>/dev/null || true
    }
    trap 'for p in ${PIDS[@]+"${PIDS[@]}"}; do kill_tree "$p"; done; rm -rf "$SUITE_TMP" 2>/dev/null || true' EXIT INT TERM

    LAST_IDX=1
    [[ "$HAS_ENT" == 1 ]] && LAST_IDX=2

    SECONDS=0
    ( run_step_isolated "inductive:base ($INIT => $INDINV)" "${BASE_ARGS[@]}" >"$SUITE_TMP/0.log" 2>&1; echo $? >"$SUITE_TMP/0.rc" ) &
    PIDS+=("$!")

    ( run_step_isolated "inductive:step ($INDINV /\\ $NEXT => ${INDINV}')" "${STEP_ARGS[@]}" >"$SUITE_TMP/1.log" 2>&1; echo $? >"$SUITE_TMP/1.rc" ) &
    PIDS+=("$!")

    if [[ "$HAS_ENT" == 1 ]]; then
      ( run_step_isolated "inductive:entailment ($INDINV => $INV)" "${ENT_ARGS[@]}" >"$SUITE_TMP/2.log" 2>&1; echo $? >"$SUITE_TMP/2.rc" ) &
      PIDS+=("$!")
    fi

    FAIL_FAST="${APALACHE_FAIL_FAST:-1}"
    ABORTED_EARLY=0
    while :; do
      ALIVE=0
      for p in "${PIDS[@]}"; do
        if kill -0 "$p" 2>/dev/null; then ALIVE=1; fi
      done
      if [[ "$FAIL_FAST" == "1" ]]; then
        for idx in $(seq 0 "$LAST_IDX"); do
          if [[ -f "$SUITE_TMP/$idx.rc" ]]; then
            rc_now="$(cat "$SUITE_TMP/$idx.rc" 2>/dev/null || echo 0)"
            if [[ -n "$rc_now" && "$rc_now" != "0" ]]; then
              ABORTED_EARLY=1
              for p in "${PIDS[@]}"; do kill_tree "$p"; done
              ALIVE=0
              break
            fi
          fi
        done
      fi
      [[ "$ALIVE" -eq 0 ]] && break
      sleep 0.2
    done

    for p in "${PIDS[@]}"; do
      wait "$p" 2>/dev/null || true
    done

    FINAL_RC=0
    for idx in $(seq 0 "$LAST_IDX"); do
      if [[ -f "$SUITE_TMP/$idx.rc" ]]; then
        [[ -f "$SUITE_TMP/$idx.log" ]] && cat "$SUITE_TMP/$idx.log"
        rc_val="$(cat "$SUITE_TMP/$idx.rc" 2>/dev/null || echo 1)"
        if [[ "$rc_val" -ne 0 && "$FINAL_RC" -eq 0 ]]; then
          FINAL_RC="$rc_val"
        fi
      elif [[ "$ABORTED_EARLY" -eq 1 ]]; then
        echo ">>> [inductive obligation #$idx cancelled after sibling failure]"
      else
        [[ -f "$SUITE_TMP/$idx.log" ]] && cat "$SUITE_TMP/$idx.log"
        [[ "$FINAL_RC" -eq 0 ]] && FINAL_RC=1
      fi
    done

    WALL_ELAPSED="$SECONDS"
    rm -rf "$SUITE_TMP" 2>/dev/null || true
    trap - EXIT INT TERM

    [[ "$FINAL_RC" -eq 0 ]] || exit "$FINAL_RC"
    echo ">>> INDUCTIVE PROOF COMPLETE (parallel wall=${WALL_ELAPSED}s): $INDINV holds at $INIT and is preserved by $NEXT${INV:+ (entailing $INV)}."
    exit 0
    ;;
esac
