#!/usr/bin/env bash
# coverage.sh — run TLC action coverage for a level's spec and report a per-action
# table, flagging dead actions (a guard that never holds / an action never enabled).
# Usage:
#   coverage.sh <Module.tla> [Module.cfg] [--all-cfgs] [--det]
#     --all-cfgs   run coverage for every *.cfg sitting next to the module in parallel
#                  and summarize each in deterministic order
#     --det        pass --det to run_tlc.sh (-workers 1) so the per-action counts
#                  are deterministic / citable run-to-run
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_TLC="$SELF_DIR/run_tlc.sh"

die(){ echo "coverage.sh: $*" >&2; exit 2; }

[[ $# -ge 1 ]] || die "usage: coverage.sh <Module.tla> [Module.cfg] [--all-cfgs]"
[[ -x "$RUN_TLC" || -f "$RUN_TLC" ]] || die "sibling not found: $RUN_TLC"

TLA="$1"; shift
[[ -f "$TLA" ]] || die "no such file: $TLA"
case "$TLA" in *.tla) : ;; *) die "first arg must be the module-named .tla";; esac

CFG=""
ALL_CFGS=0
DET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all-cfgs) ALL_CFGS=1 ;;
    --det)      DET=1 ;;
    *.cfg)      CFG="$1" ;;
    *)          die "unexpected argument: $1 (want [Module.cfg] [--all-cfgs] [--det])" ;;
  esac
  shift
done

DIR="$(cd "$(dirname "$TLA")" && pwd)"
BASE="$(basename "$TLA")"
MOD="${BASE%.tla}"

run_one() {
  local cfg="$1"
  local TRUNC=0 out rc block actions line name ab dist gen status
  echo "=== coverage: $MOD  (cfg=$cfg) ==="
  if [[ "$DET" == 1 ]]; then
    out="$(bash "$RUN_TLC" "$DIR/$BASE" "$DIR/$cfg" --coverage=60 --det 2>&1)"
  else
    out="$(bash "$RUN_TLC" "$DIR/$BASE" "$DIR/$cfg" --coverage=60 2>&1)"
  fi
  rc=$?
  if [[ $rc -ne 0 ]]; then
    if ! printf '%s\n' "$out" | grep -q "coverage statistics at"; then
      echo "  TLC run failed (exit $rc) and produced no coverage block. Tail:"
      printf '%s\n' "$out" | tail -8 | sed 's/^/    /'
      return 2
    fi
    echo "  (note: TLC exited $rc — e.g. a property violation — coverage block still present)"
    echo "  (coverage spans only the prefix explored before the halt — see CAUTION below if anything is flagged DEAD)"
    TRUNC=1
  fi

  # Extract ONLY the final `coverage statistics at` block so intermediate periodic
  # dumps never duplicate `<Action ...>: d:g` rows.
  block="$(printf '%s\n' "$out" | awk '/coverage statistics at/{buf=""; f=1} f{buf = buf $0 "\n"} END{printf "%s", buf}')"
  if [[ -z "$block" ]]; then
    echo "  WARNING: no TLC coverage block found (did the run enable -coverage?)."
    echo "  Treating as inconclusive — not flagging dead actions."
    return 3
  fi

  actions="$(printf '%s\n' "$block" \
    | grep -E '^<[^>]+>: [0-9]+:[0-9]+[[:space:]]*$' || true)"

  if [[ -z "$actions" ]]; then
    echo "  WARNING: coverage block present but no action lines parsed."
    echo "  (Spec may have only operators/invariants, or TLC's format changed.)"
    return 3
  fi

  printf '  %-28s %10s %10s  %s\n' "ACTION" "distinct" "generated" "status"
  printf '  %-28s %10s %10s  %s\n' "------" "--------" "---------" "------"

  local TOTAL_ACTIONS=0
  local DEAD_COUNT=0
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    name="${line#<}"
    name="${name%%[[:space:]]*}"
    ab="${line##*: }"
    dist="${ab%%:*}"
    gen="${ab##*:}"
    TOTAL_ACTIONS=$((TOTAL_ACTIONS + 1))
    if [[ "$gen" == "0" ]]; then
      status="DEAD (never enabled)"
      DEAD_COUNT=$((DEAD_COUNT + 1))
    else
      status="OK"
    fi
    printf '  %-28s %10s %10s  %s\n' "$name" "$dist" "$gen" "$status"
  done <<EOF
$actions
EOF

  echo "  ----"
  if [[ "$DEAD_COUNT" -gt 0 ]]; then
    echo "  $DEAD_COUNT of $TOTAL_ACTIONS action(s) DEAD (generated 0 states — never enabled)."
    if [[ "$TRUNC" == 1 ]]; then
      echo "  CAUTION: this run halted early (violation), so a DEAD flag above may be"
      echo "  halt-truncation, not a never-true guard — re-check it against a non-violating cfg."
    fi
    return 1
  fi
  if [[ "$TRUNC" == 1 ]]; then
    echo "  all $TOTAL_ACTIONS action(s) fired (within the prefix explored before the halt)."
  else
    echo "  all $TOTAL_ACTIONS action(s) fired."
  fi
  return 0
}

overall=0
any_warn=0

fold_rc() {
  case "$1" in
    0) : ;;
    1) [[ "$overall" -lt 1 ]] && overall=1 ;;
    2) [[ "$overall" -lt 2 ]] && overall=2 ;;
    3) any_warn=1 ;;
  esac
}

if [[ "$ALL_CFGS" == 1 ]]; then
  CFG_LIST=()
  for f in "$DIR"/*.cfg; do
    [[ -e "$f" ]] || continue
    CFG_LIST+=("$(basename "$f")")
  done
  [[ ${#CFG_LIST[@]} -gt 0 ]] || die "no *.cfg found next to module: $DIR"
  echo "### --all-cfgs: parallel coverage for every cfg next to $MOD"
  echo

  COV_TMP="$(mktemp -d "${TMPDIR:-/tmp}/tlc_cov.XXXXXX")"
  PIDS=()
  trap 'for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null || true; done; rm -rf "$COV_TMP" 2>/dev/null || true' EXIT INT TERM

  idx=0
  for c in "${CFG_LIST[@]}"; do
    (
      run_one "$c" >"$COV_TMP/$idx.out" 2>&1
      echo $? >"$COV_TMP/$idx.rc"
    ) &
    PIDS+=("$!")
    idx=$((idx + 1))
  done

  for p in "${PIDS[@]}"; do
    wait "$p" 2>/dev/null || true
  done

  idx=0
  for _ in "${CFG_LIST[@]}"; do
    [[ -f "$COV_TMP/$idx.out" ]] && cat "$COV_TMP/$idx.out"
    echo
    r="$(cat "$COV_TMP/$idx.rc" 2>/dev/null || echo 2)"
    fold_rc "$r"
    idx=$((idx + 1))
  done

  rm -rf "$COV_TMP" 2>/dev/null || true
  trap - EXIT INT TERM
else
  if [[ -n "$CFG" ]]; then cfg="$(basename "$CFG")"; else cfg="$MOD.cfg"; fi
  [[ -e "$DIR/$cfg" ]] || die "config not found next to module: $DIR/$cfg"
  run_one "$cfg"
  fold_rc "$?"
  echo
fi

case "$overall" in
  2) echo "RESULT: a TLC run failed — see above."; exit 3 ;;
  1) echo "RESULT: dead action(s) found — fix the model (a never-enabled action is usually a guard that never holds)."; exit 1 ;;
  0)
    if [[ "$any_warn" == 1 ]]; then
      echo "RESULT: no dead actions detected, but at least one run produced no parseable coverage block (warned above)."
    else
      echo "RESULT: all actions fired in every cfg checked."
    fi
    exit 0
    ;;
esac
