#!/usr/bin/env bash
# coverage.sh — run TLC action coverage for a level's spec and report a per-action
# table, flagging dead actions (a guard that never holds / an action never enabled).
# Usage:
#   coverage.sh <Module.tla> [Module.cfg] [--all-cfgs] [--det]
#     --all-cfgs   run coverage for every *.cfg sitting next to the module and
#                  summarize each (instead of a single cfg)
#     --det        pass --det to run_tlc.sh (-workers 1) so the per-action counts
#                  are deterministic / citable run-to-run
#
# CAVEAT (violating cfgs): TLC halts at the first violation, so on a violating cfg
# the coverage block spans only the explored PREFIX.  A 'B == 0' action there may be
# halt-truncation rather than a never-true guard — the table warns; re-check any
# dead flag against a non-violating cfg before trusting it.
#
# It does NOT re-implement the java invocation or jar resolution — it delegates to the
# sibling scripts/run_tlc.sh (the single source of truth), captures its output, and
# parses the TLC '-coverage' action block.  Reading that block:
#   - a top-level '<NAME line ... of module M>: A:B' line is an ACTION; A:B is
#     'distinct:generated' — A = states first found via this action, B = states it
#     generated.  B == 0 (e.g. ': 0:0', or an action TLC never reports) means the action
#     was NEVER ENABLED in any reachable state => DEAD spec, flag it.  A == 0 with B > 0
#     (e.g. ': 0:3') only means it reached already-seen states — that is NOT dead.
#   - lines without the ': A:B' suffix (operators/invariants like TypeOK) and indented
#     sub-expression lines are NOT actions — ignore them for the dead check.
# Exit non-zero if any dead action is found, so '/vibe-tla coverage' and CI can detect a
# broken model; exit 0 if all actions fired (or if TLC produced no coverage block — warn).
#
# POSIX-bash, macOS bash 3.2 compatible (no associative arrays).
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

# ---------------------------------------------------------------------------
# run_one <cfg-basename>
#   Runs coverage for one cfg via run_tlc.sh, parses the action block, prints a
#   table, and sets DEAD_COUNT / TOTAL_ACTIONS for the caller.  Returns:
#     0 = all actions fired      1 = at least one dead action
#     2 = run failed             3 = ran but no coverage block (warn)
# ---------------------------------------------------------------------------
run_one() {
  cfg="$1"
  TRUNC=0
  echo "=== coverage: $MOD  (cfg=$cfg) ==="
  if [[ "$DET" == 1 ]]; then
    out="$(bash "$RUN_TLC" "$DIR/$BASE" "$DIR/$cfg" --coverage --det 2>&1)"
  else
    out="$(bash "$RUN_TLC" "$DIR/$BASE" "$DIR/$cfg" --coverage 2>&1)"
  fi
  rc=$?
  if [[ $rc -ne 0 ]]; then
    # TLC may exit non-zero on an invariant violation yet STILL emit a coverage block;
    # only bail if there is genuinely nothing to parse.
    if ! printf '%s\n' "$out" | grep -q "coverage statistics at"; then
      echo "  TLC run failed (exit $rc) and produced no coverage block. Tail:"
      printf '%s\n' "$out" | tail -8 | sed 's/^/    /'
      return 2
    fi
    echo "  (note: TLC exited $rc — e.g. a property violation — coverage block still present)"
    echo "  (coverage spans only the prefix explored before the halt — see CAUTION below if anything is flagged DEAD)"
    TRUNC=1
  fi

  # Slice from the coverage banner to end of output, then keep only the top-level
  # action headers: lines that start with '<' AND end with ': <digits>:<digits>'.
  # That suffix is what distinguishes an ACTION from an operator/invariant header
  # (e.g. '<TypeOK ...>' has no ': A:B') and from indented sub-expression lines.
  block="$(printf '%s\n' "$out" | awk '/coverage statistics at/{f=1} f')"
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

  TOTAL_ACTIONS=0
  DEAD_COUNT=0
  # Read line by line (bash 3.2: no mapfile / no assoc arrays).
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    # name = token right after '<', up to the first space.
    name="${line#<}"
    name="${name%%[[:space:]]*}"
    # A:B = the field after the final ': '.
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

# ---------------------------------------------------------------------------
# Drive one cfg, or every cfg next to the module.
# ---------------------------------------------------------------------------
overall=0      # 0 = clean, 1 = dead found somewhere, 2 = a run failed
any_warn=0

drive() {
  cfg="$1"
  run_one "$cfg"
  r=$?
  case "$r" in
    0) : ;;
    1) overall=1 ;;
    2) [[ "$overall" -lt 2 ]] && overall=2 ;;
    3) any_warn=1 ;;
  esac
  echo
}

if [[ "$ALL_CFGS" == 1 ]]; then
  cfgs=""
  for f in "$DIR"/*.cfg; do
    [[ -e "$f" ]] || continue
    cfgs="$cfgs $(basename "$f")"
  done
  [[ -n "$cfgs" ]] || die "no *.cfg found next to module: $DIR"
  echo "### --all-cfgs: coverage for every cfg next to $MOD"
  echo
  for c in $cfgs; do
    drive "$c"
  done
else
  if [[ -n "$CFG" ]]; then cfg="$(basename "$CFG")"; else cfg="$MOD.cfg"; fi
  [[ -e "$DIR/$cfg" ]] || die "config not found next to module: $DIR/$cfg"
  drive "$cfg"
fi

# Exit policy: dead action(s) anywhere => non-zero (CI / 'coverage' fails the model).
# A failed run is the worst outcome; a warn-only (no coverage block) stays exit 0.
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
