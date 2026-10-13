#!/usr/bin/env bash
# new_level.sh — scaffold a level directory with the standard layout.  Usage:
#   new_level.sh <level-dir> <ModuleName>
#   e.g. new_level.sh foo_models/cache/L2_Evict L2_Evict
# Never clobbers an existing file; safe to re-run.  The spec and ALL its configs
# live in a real 02_models/ subfolder (no symlinks); module basename == .tla name
# (TLC requirement) and must be a TLA identifier.
set -euo pipefail
die(){ echo "new_level.sh: $*" >&2; exit 2; }

[[ $# -ge 2 ]] || die "usage: new_level.sh <level-dir> <ModuleName>"
DIR="$1"; MOD="$2"
case "$MOD" in
  [A-Za-z]*) : ;;
  *) die "module name must start with a letter: $MOD" ;;
esac
echo "$MOD" | grep -qE '^[A-Za-z][A-Za-z0-9_]*$' || die "module name must be a TLA identifier (letters/digits/_): $MOD"

mkdir -p "$DIR/02_models"
cd "$DIR"

w(){ # w <file>  (reads heredoc on stdin) — write only if absent
  local f="$1"
  if [[ -e "$f" ]]; then echo "  skip (exists): $f"; cat >/dev/null; else cat > "$f"; echo "  wrote: $f"; fi
}

w "00_input.md" <<EOF
# 00_input — $MOD  (FROZEN at close)

## Inputs from the previous level
- <invariants/contracts lifted from L(n-1)/05_output.md>

## New code references modeled at this level
- <file:line> — <what it is>

## Supplied context and its verification status
- <claim from the user's context> — VERIFIED at <file:line> | UNCLEAR | owner-fact (keeps any finding CANDIDATE)
EOF

w "01_reasoning.md" <<EOF
# 01_reasoning — $MOD

## The one concern this level adds
<the single new source of complexity vs L(n-1)>

## Mode
<faithful transcription | faithful fault injection — and why this matches the code>
- Faults modeled (if any): <name> — tolerated because <design statement + file:line>

## Concrete vs abstracted
| Modeled concretely | Abstracted (and why sound) |
|---|---|
| <…> | <…> |

## Concurrency derived from the runtime (not the source file)
<who runs these transitions, on what workers, dispatched by what key; is shared state
sharded, and is the shard key the dispatch key?  (lessons R2/R5)>
EOF

w "02_models/$MOD.tla" <<EOF
---------------------------- MODULE $MOD ----------------------------
EXTENDS Naturals, Sequences, FiniteSets, TLC

\* ============================ var <-> code map ============================
\* CONSTANTS
\*   <Name>   - <meaning>                 (<file:line>)   [read from THIS code]
\* VARIABLES
\*   <var>    - <meaning>                 (<file:line>)
\*              DENOTES: <progress marker | content boundary | terminal status | ...>
\* ACTIONS
\*   <Action> - <what it does>            (<file:line>)
\* FAULTS MODELED: <none | crash-stop | loss/reorder | ...>   NOT modeled: <...> (design)
\* =========================================================================

\* CONSTANTS  \* <uncomment and declare model constants here, e.g. CONSTANT N>

VARIABLE x  \* <your state — rename / add variables and keep vars in sync>
vars == << x >>

Init == x = 0                 \* <initial state predicate>
Next == UNCHANGED x           \* <replace with: \E ... : Action1 \/ Action2 \/ ...>

Spec == Init /\ [][Next]_vars \* add WF_vars(...)/SF_vars(...) for liveness

\* ---- Properties (developer expectations) ----
TypeOK == x \in {0}           \* <your type invariant; encode a SEMANTIC WITNESS for staleness/loss>
\* <Invariant> == ...        (a violated invariant is the finding; witness the bad data)
======================================================================
EOF

w "02_models/$MOD.cfg" <<EOF
\* primary config for $MOD — sized for a few minutes in TLC
SPECIFICATION Spec
INVARIANT TypeOK
\* INVARIANT <YourInvariant>
\* PROPERTY  <YourLivenessProperty>
\* CONSTANTS <Name> = <value>
\* SYMMETRY  <permutations of interchangeable values>
\* CONSTRAINT <bound any unbounded value so TLC terminates>
EOF

echo "  (scaling/scenario configs also go in 02_models/, e.g. 02_models/${MOD}_large.cfg)"

w "03_run_log.md" <<EOF
# 03_run_log — $MOD

Invocation (via scripts/run_tlc.sh — runs the real module-named .tla, no symlinks):
\`\`\`
run_tlc.sh 02_models/$MOD.tla                 # primary cfg (defaults to 02_models/$MOD.cfg)
run_tlc.sh 02_models/$MOD.tla 02_models/${MOD}_large.cfg   # a scaling cfg
run_tlc.sh 02_models/$MOD.tla --det           # deterministic counts for a violation
run_tlc.sh 02_models/$MOD.tla --coverage      # action-coverage (zero-coverage = dead spec)
\`\`\`

| cfg | distinct states | generated | depth | time | result |
|---|---|---|---|---|---|
| $MOD.cfg | | | | | |

## TLC action coverage (--coverage)
<paste the per-action counts; flag any action with 0 — it never fired (dead spec / unmet guard)>

## Wall-clock runtime
- primary (deterministic, run_tlc.sh --det): <real>s
- whole level: <real>s
EOF

w "04_counterexamples.md" <<EOF
# 04_counterexamples — $MOD  (only if a property was violated)

> STATUS: N/A — no violation recorded yet. If this level closes PASS, replace the
> sections below with an explicit "no property violated at this level" note; fill
> them in only from a real TLC trace.

## Trace (from the actual TLC output, --det)
| step | <var> | <var> | action |
|---|---|---|---|
| 1 | | | Init |

## What it shows
<the behavior, in one or two sentences>

## Root cause (verified, not assumed)
<code snippet + file:line that produces the behavior>

## Triage  (run the lessons.md checklist first)
- Denotation / witness / omitted-guard / concurrency-topology checks: <result>
- Classification: PASS | candidate | confirmed | refuted | safe-by-design
- One precise owner question (if candidate): <question>
EOF

w "05_output.md" <<EOF
# 05_output — $MOD  (FROZEN at close)

## What this level proved
<the property, under what model/faults, with the TLC verdict>

## Finding
<none | candidate(<open precondition>) | confirmed | refuted(<why>) | safe-by-design>

## Fidelity & coverage  (see references/coverage.md)
- Fidelity: <K> transitions modeled, all cited file:line; <U> UNCLEAR/TODO; abstractions listed in 01_reasoning.md
- Code coverage: modeled <m> of <n> relevant functions/branches in <source root> (denominator stated)
- Model coverage: TLC --coverage — <all actions fired | actions with 0 coverage: …>

## Exports to the next level
- <invariant/contract the next level may assume by name>
EOF

w "06_notes.md" <<EOF
# 06_notes — $MOD

<snippets ready to lift into a write-up / bug report: the one-paragraph result,
the key trace, the suggested fix.>
EOF

echo "Scaffolded level: $DIR  (module $MOD, spec under 02_models/)"
