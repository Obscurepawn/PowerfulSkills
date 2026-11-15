# performance.md — accelerating TLC & Apalache verification without losing soundness

Naive model checking wastes hours on three completely different bottlenecks: **redundant
state-graph branches** (dead registers, write-only trace logs), **AST interpreter overhead**
(multi-limb arithmetic, nested set comprehensions, `-coverage 1` AST dumps), and **poor
batch scheduling** (stranding multi-worker scaling runs at the tail or paying single-worker
coverage overhead on every scaling `.cfg`).

This playbook stacks **three sound acceleration layers** that routinely turn multi-hour or
paused verification runs into sub-minute checks while keeping `.tla` specs code-faithful
and preserving 100% action-coverage gates.

> **Non-negotiable bar:** Acceleration must **never** weaken an invariant, drop a reachable
> fault/interleaving, or shrink a domain below the threshold required to trigger the bug
> class under test (`methodology.md` §7, `symbolic.md`). Every reduction below is an exact
> bisimulation, an exact operator equivalence, or an execution-engine optimization.

---

## Table of Contents

- §1 The 60-second bottleneck triage rule (never wait blindly for `TLC_TIMEOUT`)
- §2 Layer 1 — Spec-level canonicalization & bisimulation quotients (`8x–50x` fewer states)
- §3 Layer 2 — Dual-engine authoring, `QF_LIA` & `@TLAPlusOperator` bytecode (`10x–15x` faster eval)
- §4 Layer 3 — JVM tiers, `OffHeapDiskFPSet`, coverage deduplication & LPT scheduling

---

## 1. The 60-second bottleneck triage rule

Never launch a TLC or Apalache run and wait 30 minutes (`TLC_TIMEOUT=1800`) to discover
that it stalled. Inspect the first `Progress(d)` lines within **30–60 seconds** and route by
the observed signature:

| Early symptom (`30–60s`) | True bottleneck | Immediate action |
|---|---|---|
| **Low per-worker rate** (`< 100,000 states/min` per worker) on `< 500k` states | **AST interpreter hotspot**: nested `SUBSET`/`CHOOSE`, recursive sequence folds, or tuple/limb math evaluated per state | Simplify operator algebra, memoize constant sets, emit a zero-spec-churn `@TLAPlusOperator` override (§3.3), or move wide arithmetic to Apalache `QF_LIA` (§3.2) |
| **High rate** (`> 1,000,000 states/min`) with `states left on queue` doubling each depth (`> 2M` distinct states and climbing) | **Combinatorial state explosion**: dead registers, history ghost variables, or wide numeric Cartesian products | 1. Zero dead registers (`ClearDeadSlots`, §2.1)<br>2. Add congruent `VIEW` (§2.2) or `SYMMETRY`<br>3. Switch wide/unbounded domains to Skolem + Apalache `bmc`/`inductive` (`symbolic.md`) |
| **TLC SANY / runtime 32-bit error** (`TLC can't handle a number this big` or integer overflow) on a dual-engine spec | **32-bit `IntValue` / `Integer.parseInt` limit** on 64-bit/128-bit constants | Express constants via `<= 10^9` factors (`60 * 1000000000`) and gate runtime caps behind `IF BoundedMode THEN ...` (§3.1) |
| **Apalache stalls inside Z3** (`> 60s` on one step/VC) | **Non-linear arithmetic (`QF_NIA`)**, unbounded `Seq(T)` theory, or monolithic unsplit `IndInv` | Cross-multiply constant ratios into `QF_LIA`, replace `Seq(T)` with fixed-slot symbolic witness + `capacity \in Int`, and split `IndInv` into top-level conjuncts (§3.2) |
| **Multi-cfg / full-workspace suite crawls** even though individual primary `.cfg`s take `< 10s` | **Serial execution, `-coverage 1` dumps, or single-worker coverage on heavy scaling `.cfg`s** | Run via `scripts/run_suite.sh` (Core-budgeted LPT + Coverage-Basis Deduplication + `OffHeapDiskFPSet`, §4) |

---

## 2. Layer 1 — Spec-level canonicalization & bisimulation quotients

### 2.1 Dead-register canonicalization (`ClearDeadSlots` — often `10x–45x` fewer states)
Explicit-state BFS treats two states as distinct whenever *any* state variable differs —
even if that variable is logically dead in the current mode or queue length! Common traps:
- A bounded buffer reaches `buf_len' = 0`, but `buf_head` / `buf_tail` retain whatever
  payload IDs the previous cycle wrote ($|D|^2$ phantom copies of the empty state).
- A state machine leaves `"Reconciling"` for `"Ready"`, leaving stale `reconcile_target` or
  `last_delta` values behind.

**Rule:** Whenever a transition empties a container or exits a phase, reset inactive slots
to a single canonical value (`0` or `"None"`) inside the transition helper:

```tla
ClearInactiveBuf(len_next, h_next, t_next) ==
    /\ buf_len'  = len_next
    /\ buf_head' = IF len_next >= 1 THEN h_next ELSE 0
    /\ buf_tail' = IF len_next >= 2 THEN t_next ELSE 0
```

This is an **exact reachable-state canonicalization**: it never alters any enabled guard,
safety invariant, or action coverage count (`B > 0`), and works identically in both TLC and
Apalache.

### 2.2 Congruent `VIEW` bisimulation quotients (`5x–10x` state reduction on scaling runs)
Many `L0` specs record append-only ghost histories (`emitted_events`, `audit_log`),
monotonic generation counters (`published_gen`), or diagnostic error strings (`last_error`)
for trace readability, even though neither `Next` guards nor `INVARIANT`s depend on the
entire history.

Defining a state projection `VIEW ModelView` instructs TLC's fingerprint set (`FPSet`) to
hash `ModelView` instead of `vars`. For **safety** (`INVARIANT`) checking, `VIEW ModelView`
is **100% sound (exact bisimulation quotient)** iff all three conditions hold
(document them in `01_reasoning.md`):

1. **Invariant Determination:** Every checked `INVARIANT` depends only on components
   retained (or summarized as an exact boolean/tag observation `Obs`) in `ModelView`:
   $\text{ModelView}(s_1) = \text{ModelView}(s_2) \implies (\text{Inv}(s_1) \iff \text{Inv}(s_2))$.
2. **Transition Congruence:** Every action guard and post-state projection of `Next` depends
   only on components retained in `ModelView` (projected-away fields are strictly write-only
   sinks or functionally determined).
3. **No Liveness Collapse:** Do **not** attach a lossy `VIEW` when checking temporal
   liveness (`PROPERTY` with `<>` / `~>`), because collapsing distinct progress steps into
   identical `ModelView` fingerprints creates artificial stuttering cycles.

**Preserving frozen specs:** When `02_models/<Mod>.tla` is already closed/frozen or locked
by SHA-256 evidence manifests, never edit the committed `.tla` just to add a scaling `VIEW`.
Either:
- pass `--view ModelView --view-def 'ModelView == <<core_state, Obs>>'` to
  `scripts/run_tlc.sh` (injected only inside an isolated `/tmp` workdir), or
- annotate a scaling `.cfg` with `\* @vibe-view: ModelView` so `scripts/run_suite.sh`
  applies `VIEW ModelView` on coverage-free multi-worker scaling runs while keeping primary
  `-coverage` runs unprojected.

---

## 3. Layer 2 — Dual-engine authoring, `QF_LIA` & `@TLAPlusOperator` bytecode

### 3.1 Single-spec dual-engine pattern (`BoundedMode`) & TLC SANY 32-bit guards
Instead of maintaining separate finite (`L1_Foo.tla`) and symbolic (`L1_Foo_Sym.tla`) files
that can drift apart, parameterize one module with `CONSTANT BoundedMode` (`\* @type: Bool;`):
- **TLC vacuous-pass & topology check (`.cfg` sets `BoundedMode = TRUE`):** binds inputs to
  tight finite sets (`0..2`) so `scripts/coverage.sh` proves every action fires (`B > 0`) in
  seconds.
- **Apalache full-domain / unbounded proof (`ConstInit` sets `BoundedMode = FALSE`):** binds
  timestamps, sequence IDs, and capacities over `Int` + linear inequalities (`0 .. 2^64 - 1`).

**Two mandatory TLC `2.19` 32-bit guards in dual-engine files:**
1. **No raw decimal literal `> 2147483647` anywhere in the `.tla` file.** TLC's SANY parser
   calls Java's signed 32-bit `Integer.parseInt` on *every* lexical number token at parse
   time — **even inside `ELSE` branches that are dead when `BoundedMode = TRUE`!** Writing
   `60000000000` aborts SANY with `Error: TLC can't handle a number this big`. Always factor
   wide constants through arithmetic on `<= 10^9` literals:
   ```tla
   NS_PER_SEC == 1000000000
   WINDOW_60S_NS == 60 * NS_PER_SEC           \* SANY-safe & folded by Apalache into BigInt!
   U64_MOD == 4294967296 -> WRONG! Use:
   TWO_16 == 65536
   TWO_32 == TWO_16 * TWO_16
   U64_MAX == (TWO_32 * TWO_32) - 1
   ```
2. **Gate runtime evaluation of wide upper bounds.** TLC's runtime `IntValue` is also 32-bit
   signed. Wrap `U64_MAX` / `U128_MAX` behind `BoundedMode` in any operator TLC evaluates:
   ```tla
   \* @type: () => Int;
   EffMaxId == IF BoundedMode THEN 4 ELSE U64_MAX
   ```

### 3.2 Keeping Apalache / Z3 in fast `QF_LIA` (`< 15s` inductive proofs)
1. **Cross-multiply constant ratios instead of dividing:** Encode `(used * 100) / cap >= 80`
   (or fixed-point widening checks) as `used * 5 >= cap * 4` over mathematical `Int` — pure
   `QF_LIA`, zero division, exact equivalence for `cap > 0`.
2. **Explicit C/Rust signed division toward zero:** TLA+ `\div` floors toward $-\infty$
   (`(-3) \div 2 = -2`), whereas C/Rust `/` truncates toward `0` (`-3 / 2 = -1`). Model
   signed midpoint/step division with a positive divisor `d > 0` via:
   ```tla
   TruncDivPos(num, d) == IF num >= 0 THEN num \div d ELSE -((-num) \div d)
   ```
3. **Bounded-slot symbolic witness instead of unbounded `Seq(T)`:** Unbounded `Seq(T)`
   forces expensive SMT sequence/array unrolling. Replace variable-length queues with a
   2-slot symbolic head/tail witness `(buf_len, head, tail)` + symbolic
   `cfg_capacity \in Int` (`cfg_capacity >= 1`) + `ClearInactiveBuf` (§2.1).
4. **Top-level conjunctive `IndInv` for VC splitting:** Write
   `IndInv == TypeOK /\ Lemma1 /\ Lemma2 /\ Safety` as a flat top-level conjunction so
   Apalache splits `IndInv'` into small independent Z3 queries, and rely on
   `scripts/run_apalache.sh inductive`'s **parallel fail-fast execution** (`base`, `step`,
   and `entailment` run concurrently; if `base` or `entailment` fails in `2s` during CTI
   tuning, sibling obligations are cancelled immediately).

### 3.3 Zero-spec-churn `@TLAPlusOperator` JVM overrides (`10x–15x` TLC throughput)
When an explicit `L0` model must enumerate millions of states over multi-limb fixed-point
words, bitwise tables, or deterministic replay loops and crawls at `< 100k states/min`,
replace the hot pure operator(s) in JVM bytecode via TLC's `@TLAPlusOperator` mechanism —
**without changing a single byte of the `.tla` or `.cfg` file**.

- **Works even on JRE-only hosts without `javac`:** `scripts/tlc_bytecode.py` provides a
  zero-dependency Python 3 Java `49.0` classfile assembler (`ClassFileBuilder`, `CodeAsm`,
  and `write_tlc_overrides_registry` emitting `tlc2/overrides/TLCOverrides.class`). If
  `javac` is installed, `python3 scripts/tlc_bytecode.py compile --jar "$TLA_TOOLS_JAR" ...`
  compiles `.java` overrides directly.
- **Drop-in discovery:** Place compiled classes under `$WORKSPACE/tools/overrides/` (or pass
  `--classpath <dir>` to `run_tlc.sh` / `run_suite.sh`). Both scripts prepend it before
  `tla2tools.jar` automatically.
- **Mandatory Differential Equivalence Gate:** Before trusting any `@TLAPlusOperator`
  override on a large `.cfg`, run a small `.cfg` with `--det` **without** the override and
  **with** the override, and record in `03_run_log.md` that both runs produced **identical
  `states generated` and `distinct states found`**.

---

## 4. Layer 3 — JVM tiers, `OffHeapDiskFPSet`, coverage deduplication & LPT scheduling

Single-command verification of multi-config levels or entire workspaces should use
`scripts/run_suite.sh <level-or-workspace-dir>` instead of ad-hoc serial loops:

1. **`-coverage 60` instead of `-coverage 1`:** TLC `2.19`'s `-coverage 1` walks and prints
   full AST `CostModelNode` trees every 60 seconds, serializing workers and bloating logs.
   `-coverage 60` (`run_tlc.sh --coverage` default) suppresses periodic AST dumps while
   still printing the exact final `<Action ...>: distinct:generated` block at completion,
   scaling cleanly to `2–4` workers on `50k–2M`-state configs.
2. **Workload-tiered JVM flags:**
   - **Small (`< 25k` states, 1 worker):** `-XX:+TieredCompilation -XX:TieredStopAtLevel=1`
     (`run_tlc.sh --fast-jit`) cuts JVM JIT warmup overhead by ~45%.
   - **Scaling (`>= 500k–2M+` states, multi-worker):** C2 aggressive inlining
     (`-XX:MaxInlineLevel=24 -XX:FreqInlineSize=512`) + off-heap fingerprint table
     (`-Dtlc2.tool.fp.FPSet.impl=tlc2.tool.fp.OffHeapDiskFPSet -XX:MaxDirectMemorySize=...`),
     eliminating GC pauses on large fingerprint sets while budgeting `Xmx + DirectMemory`
     against host `MemAvailable`.
3. **Coverage-Basis Deduplication (with automatic sound failsafe):** When a `.tla` module
   has both fast primary/scenario `.cfg`s (`< 2M` states) and heavy multi-million-state
   scaling `.cfg`s, `run_suite.sh` runs the `< 2M`-state `.cfg`s with `-coverage 60` and
   runs the `>= 2M`-state scaling `.cfg`s **coverage-free** across `4–12` workers with
   `OffHeapDiskFPSet`. Once all `.cfg`s complete, if `100%` of module actions already fired
   (`generated > 0`), dead-spec freedom is proven without paying single-threaded AST
   coverage overhead on `50M+` states; if any action still has `generated == 0`,
   `run_suite.sh` automatically re-runs the scaling `.cfg`(s) with `-coverage 60`.
4. **Core-Budgeted LPT (Longest-Processing-Time) Scheduling:** `run_suite.sh` estimates
   per-cfg state counts from `03_run_log.md` / `*.log` history and reserves multi-core slots
   for the heaviest scaling tasks at $t = 0$, packing 1-core tasks around them so multi-core
   machines stay saturated end-to-end without tail stalls or RAM thrashing.
