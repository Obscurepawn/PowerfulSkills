# authoring.md — writing a code-faithful TLA+ spec that runs clean

This is the practical how-to for turning a code path into a checkable spec. The
standards behind it are in `methodology.md`; the triage rules are in `lessons.md`.

## Table of Contents

- §1 Before you write any TLA+
- §2 The `var ↔ code` map — always at the top of the `.tla`
- §3 Style conventions
- §4 Fault injection patterns (only design-tolerated faults)
- §5 Sizing the config
- §6 Iterate to "runs clean in TLC"
- §7 Common pitfalls

## 1. Before you write any TLA+

1. **Read the code path end to end** and list the transitions. For each, note the
   `file:line`. If you can't cite it, you can't model it (`methodology.md` §4).
2. **Establish denotations.** For every value you'll model (a counter, a watermark, a
   status, a flag), write down what it *means* per its producer — progress vs boundary,
   terminal vs non-terminal, which set a threshold counts (`lessons.md` R1.1/R3).
3. **Derive the real concurrency.** Who runs these transitions, on what threads/workers/
   fibers, dispatched by what key? Is shared state sharded, and is the shard key the same
   as the dispatch key? The model's interleavings must match the runtime's, not the
   source file's apparent ones (`lessons.md` R2/R5). Freeze this in `PLAN.md`/
   `01_reasoning.md` and treat any frozen assumption as a debt to re-derive later.
4. **Pick the mode** (transcription vs faithful fault injection) and the **property**
   (the developer expectation) — `methodology.md` §3.

## 2. The `var ↔ code` map — always at the top of the `.tla`

Open every module with a comment block mapping each variable and each key action to a
code identifier and what it denotes. A reviewer must be able to read the spec with the
source open beside it. Example shape (generic):

```
\* ============================ var <-> code map ============================
\* CONSTANTS
\*   Nodes        - the replica set            (config.h:NUM_REPLICAS)
\*   W, R         - write/read quorum sizes     (config.h:42-43)   [read from THIS code]
\* VARIABLES
\*   ack[n]       - per-node ack state          (ack_tracker.cc:120)  {none,ok,fail}
\*                  DENOTES: terminal once set; consumed by decide_quorum (…:378)
\*   committed    - highest committed index      (commit_log.cc:88)
\*                  DENOTES: content boundary (no data above it), NOT a progress lag
\* ACTIONS
\*   AckOk(n)     - a node replies ok            (writer.cc:201-214)
\*   Crash(n)     - tolerated fault: crash-stop  (design: comment writer.cc:55)
\* FAULTS MODELED: crash-stop, message reorder.  NOT modeled: Byzantine (design = fail-stop).
\* =========================================================================
```

Do not invent constants from another project. If it's a quorum system, read *this*
code's N/W/R; if it's a cache, read *this* code's level count and capacity. Anything you
cannot verify is marked `UNCLEAR` in the map, not guessed.

## 3. Style conventions

- **PlusCal-free, action-style.** Define `Init`, named action operators, and
  `Next == \E ... : Action`, then `Spec == Init /\ [][Next]_vars` (add fairness for
  liveness: `WF_vars(...)` / `SF_vars(...)`). Action style keeps the `var ↔ code` mapping
  one-to-one and the trace readable.
- **Basename = MODULE name.** The file `L2_Foo.tla` must declare `MODULE L2_Foo`. TLC
  errors otherwise. The spec and its configs live together in the level's `02_models/`
  folder as real files; run TLC on `02_models/L2_Foo.tla` directly (no symlinks).
- **Properties express developer expectations**, not folklore: read-your-write,
  success-implies-durable, monotonicity, exactly-once / no-duplicate, no-lost-update,
  mutual exclusion, termination/liveness. State each as an invariant (`INVARIANT`) or a
  temporal property (`PROPERTY`) in the cfg.
- **Encode the witness** for any staleness/loss property (`lessons.md` R1.2): the
  violating state must carry data that is actually wrong/missing, not just a label.

## 4. Fault injection patterns (only design-tolerated faults)

Model each tolerated fault as an explicit action, named for what it is, gated so it stays
inside the failure model:

- **crash-stop:** `Crash(n) == alive[n] /\ alive' = [alive EXCEPT ![n]=FALSE] /\ …`
- **crash-restart with partial durable state:** restore only what the design says is
  durable; lose the rest.
- **message loss/reorder/duplication:** model the network as a *bag/set* of in-flight
  messages; deliver any, drop any, deliver twice — bounded by the protocol.
- **slow/lagging replica:** allow a node to withhold progress arbitrarily long (no
  fairness on its catch-up) while others proceed.
- **partition:** partition the node set; allow healing.

Bound fault counts only as far as the design tolerates (e.g. at most `N−W` crashed). Name
variants `*_Crash`, `*_LossReorder`, `*_UnderQuorum`. Reserve `*_Unsafe` for
guard-demonstration models that deliberately remove a guard to prove it is load-bearing —
never a real finding (`methodology.md` §3.2).

## 5. Sizing the config

- Keep the **primary cfg small** — target a few minutes in TLC. Use the smallest sizes
  that still exercise the concern (often N=3, indices ≤ a handful, 1–2 in-flight ops).
- Put **scaling rounds** in `02_models/` as separate `*.cfg` files (larger N / longer
  index ranges) and run them when the primary passes; document them in `03_run_log.md`.
- Use **symmetry sets** (`SYMMETRY` over a permutation set of interchangeable nodes/keys)
  to cut the state space — but only over genuinely interchangeable values.
- If a level genuinely explodes, document the wall and either bound the concern more
  tightly *without dropping it*, or note Apalache (symbolic) as an alternative.

## 6. Iterate to "runs clean in TLC"

A model that doesn't run is not evidence. Expect to loop:

1. **Parse errors** — usually a missing `EXTENDS Naturals/Integers/Sequences/FiniteSets/
   TLC`, an undefined operator, or a `==` vs `=` slip. Fix and re-run.
2. **`Attempted to … ` runtime errors** — a value used outside its domain, a record field
   that doesn't exist, division by zero, an unbounded set. Constrain the domain or guard
   the action.
3. **State constraint** — if the state space is unbounded (e.g. an ever-growing sequence),
   add a `CONSTRAINT` bounding indices/lengths so TLC terminates; note the bound.
4. **Deadlock reported but expected** — if termination is legitimate, set the cfg to allow
   it or add a stutter/`Done` action; if it's a real "stuck" state, that may be your
   finding.
5. **Invariant violated** — stop and triage with `lessons.md` *before* calling it a bug.

Re-run a violating cfg with `-workers 1` for deterministic state counts and trace depth;
those are the numbers you cite. Use `scripts/run_tlc.sh` for the canonical invocation and
automatic scratch cleanup.

## 7. Common pitfalls

- **Looser-than-code model** (the #1 false-positive source): you dropped a guard the code
  has. Before reporting, re-read the code for every fallback/serialization/ordering the
  model assumed away (`lessons.md` R1.3, the common shape).
- **Modeling the source file's threads, not the runtime's** (`lessons.md` R2/R5).
- **An invariant over a misread denotation** (`lessons.md` R1.1) — the classic
  "watermark below need ⇒ stale" error when the watermark is a content boundary.
- **Unbounded constants** making TLC never finish — always bound and document.
- **Citing numbers from a `-workers auto` run** — fine for the verdict, but for the
  reproducible counts/depth, use `-workers 1`.
