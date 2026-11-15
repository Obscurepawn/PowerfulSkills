# symbolic.md — breaking Cartesian-product state explosion with symbolic reasoning

Explicit-state enumeration (TLC BFS) visits concrete states one by one. When a component's
state space is a wide Cartesian product $|S| = \prod_i |D_i|$ — 64-bit packed keys, byte
budgets, watermarks/LSNs/epochs, parameterized quorum bounds, or unbounded retry/counter
horizons — naive enumeration either times out (`TLC_TIMEOUT`) or tempts the modeler into
shrinking constants so aggressively that real boundary bugs disappear.

**Binding rule:** Never shrink a domain below the threshold needed to trigger the bug class
under test (e.g., testing a 24-bit truncation mask on `0..3`, or a hysteresis gap on `0..1`)
and call the resulting TLC run a `PASS`. When Cartesian explosion blocks faithful
enumeration, switch to **mechanically-checked symbolic reasoning**:

1. **Pre-solver symbolic factorization** (§2) — collapse redundant dimensions in TLA+ with
   explicit soundness proofs in `01_reasoning.md`.
2. **Mode S1: Symbolic Bounded Model Checking (`bmc`)** (§3) — unroll $k$ transitions into
   quantifier-free SMT constraints solved by Z3 via Apalache (`scripts/run_apalache.sh bmc`),
   covering full 64-bit / unbounded integer domains without enumerating tuples.
3. **Mode S2: Symbolic Inductive Invariants (`inductive` + CTI loop)** (§4) — prove safety
   for **all** trace depths ($\forall k \ge 0$) in two SMT queries (`length=0` base +
   `length=1` inductive step) via LLM invariant synthesis and mechanical Z3 refutation.

> **No paper proofs.** "Symbolic reasoning" in vibe-tla means **LLM symbolic/inductive
> formulation + mechanical SMT discharge** — never an unchecked prose argument.

---

## Table of Contents

- §1 Diagnosing the explosion — pick the right weapon
- §2 Pre-solver symbolic factorization (LLM reduction prompt)
- §3 Mode S1 — Symbolic Bounded Model Checking (Apalache / Z3)
- §4 Mode S2 — Symbolic Inductive Invariants & the CTI loop
- §5 Vacuous-pass protection, audit logging, and offline fallback

---

## 1. Diagnosing the explosion — pick the right weapon

Before changing solvers or shrinking `.cfg` numbers, classify *why* $|S|$ exploded:

| Explosion source | Example in production code | Wrong reaction | Right weapon |
|---|---|---|---|
| **Interchangeable IDs** ($N!$ permutations of identical workers/keys) | 4 identical worker threads or cache keys | Drop concurrency to 1 thread | Keep TLC; add `SYMMETRY` or string tags (§2.3) |
| **Wide data / bit-field / arithmetic Cartesian product** ($D_1 \times \dots \times D_m \gg 10^7$) | 64-bit key packing `(spc, db, rel, fork)`, `512 MiB` global vs per-conn byte budgets, watermark/lease arithmetic | Shrink `dbNode` to `0..2` (hides 24-bit alias!) | **Mode S1: Symbolic BMC** (`run_apalache.sh bmc`) over `Int` inequalities (§3) |
| **Multi-key / multi-shard map product** ($|V|^{|K|}$) | `map[key]` across thousands of pages/segments coupled only through a shared counter or LRU cap | Model 1 key with no background contention | **Skolem Witness Projection** (§2.1): 1–2 tracked symbolic keys + symbolic environment summary |
| **Unbounded / deep step horizon** ($k \to \infty$) | Monotone LSN/epoch/term counters, sliding windows, retry loops that fail only after high drift | Cap counter at `CONSTRAINT x <= 3` and claim unbounded safety | **Mode S2: Symbolic Inductive Invariant** (`run_apalache.sh inductive`, §4) |
| **Deep liveness lasso** (`<>` / `~>` under `WF`/`SF`) | Multi-hop wake-up stall over large queues | Drop fairness or truncate mid-flight | Factorize data (§2) so small TLC proves liveness; optionally hunt deeper traces with `run_tlc.sh ... -- -simulate num=50000,depth=100` (hunt-only, never exhaustive `PASS`) |

---

## 2. Pre-solver symbolic factorization (LLM reduction prompt)

Even an SMT solver slows down if you encode concrete maps over millions of keys. Apply these
three reductions *first* when authoring the spec, and record each one's soundness argument
in `01_reasoning.md`:

### 2.1 Skolem witness projection (distinguished element + symbolic environment)
When a property quantifies universally over keys/pages/requests ($\forall k \in \text{Keys}: P(k)$,
or $\forall k_1 \neq k_2: \text{Enc}(k_1) \neq \text{Enc}(k_2)$):

- Replace the full table `[Keys -> State]` ($|\text{State}|^{|\text{Keys}|}$) with **1
  symbolic tracked witness `k_star`** (for single-key safety/staleness) or **2 distinct
  symbolic witnesses `k1 /= k2`** (for collision, aliasing, or cross-key interference).
- If other keys affect `k_star` only through shared aggregates (e.g., `global_out_bytes`,
  `shard_lock`, `evictable_count`), model the rest of the universe as a **symbolic
  environment summary** (`env_bytes \in Int`, `env_bytes >= 0`) with transitions that can
  nondeterministically add/release valid environment contributions within code-verified
  bounds.
- **Soundness note (`01_reasoning.md`):** because `k_star` is unconstrained (arbitrary) and
  `env_*` over-approximates all reachable schedules of non-tracked keys, a `PASS` holds for
  every key, while any counterexample must still be checked for environment realizability
  during `lessons.md` triage.

### 2.2 Relational parameterization (`ConstInit`)
Instead of checking one hard-coded tuple (`N=3, W=2, R=2` or `LOW=384, HIGH=512`), declare
symbolic `CONSTANTS` and constrain only their **code-verified algebraic relationship** in a
`ConstInit` predicate (`--cinit=ConstInit`):

```tla
CONSTANTS
    \* @type: Int;
    LOW_WM,
    \* @type: Int;
    HIGH_WM,
    \* @type: Int;
    MAX_FRAME

ConstInit ==
    /\ LOW_WM \in Int /\ HIGH_WM \in Int /\ MAX_FRAME \in Int
    /\ 0 < LOW_WM
    /\ LOW_WM < HIGH_WM
    /\ 0 < MAX_FRAME /\ MAX_FRAME <= HIGH_WM
```

One symbolic run now checks **every** valid configuration satisfying `ConstInit` at once —
and if the property fails only when `HIGH_WM - LOW_WM < MAX_FRAME`, Z3 synthesizes the exact
violating threshold relation as a concrete witness!

### 2.3 Uninterpreted / string tags for non-arithmetic IDs
If node, worker, or shard identifiers are only compared with `=` and `/=` (never `<`, `+`,
`%`), represent them as strings (`{"n1", "n2", "n3"}`, type `Str`) rather than integers.
Apalache translates `Str` constants into SMT equality logic without integer arithmetic
overhead.

### 2.4 Bounded-slot symbolic queues & dead-register canonicalization
Avoid unbounded `Seq(T)` variables when modeling FIFO buffers, replay queues, or rings:
SMT sequence/array theory unrolling slows Z3 dramatically, and leftover payload values in
popped slots explode the finite TLC coverage twin. Instead:
- Model a **2-slot symbolic witness `(buf_len, buf_head, buf_tail)`** coupled with a
  symbolic capacity `cfg_capacity \in Int /\ cfg_capacity >= 1` (allowing arbitrary gap/fill
  arrivals up to `cfg_capacity`).
- Canonicalize inactive slots on every transition (`buf_head' = IF len' >= 1 THEN h ELSE 0`,
  `buf_tail' = IF len' >= 2 THEN t ELSE 0`) — cuts the `BoundedMode = TRUE` TLC coverage
  run by `> 40x` (`references/performance.md` §2.1).

---

## 3. Mode S1 — Symbolic Bounded Model Checking (Apalache / Z3)

Ensure Apalache is installed in the workspace (`scripts/install_apalache.sh "$WORKSPACE"` —
downloads a pinned release once and records `APALACHE_BIN` in `config.env`), then invoke
via `scripts/run_apalache.sh`.

### 3.1 Snowcat `@type:` annotations (dual-engine friendly)
Apalache's Snowcat typechecker requires strict static types inside TLA+ comments
(`\* @type: ...;` or `(* @type: ... *)`). **TLC ignores comments completely**, so `@type:`
annotations never break `run_tlc.sh`.

```tla
VARIABLES
    \* @type: Int;
    globalOut,
    \* @type: Str -> Int;
    connOut,
    \* @type: Set({seq: Int, bytes: Int});
    completions

\* @type: (Str, Int) => Bool;
QueueFrame(c, sz) == ...
```

> **SANY attachment rule (Apalache 0.63+):** Always place `@type:` **after** the
> `CONSTANTS` / `VARIABLES` keyword, immediately above each identifier (or inline as
> `VARIABLE (* @type: Int; *) x`) — **never** above the `VARIABLE` keyword itself, where
> SANY attaches the comment to the preceding declaration and Snowcat reports
> `Expected a type annotation for VARIABLE x`!

Core Snowcat type forms:
- Primitives: `Int`, `Bool`, `Str`
- Collections: `Set(T)`, `Seq(T)`, `S -> T` (functions), `[f1: T1, f2: T2]` or `{f1: T1, f2: T2}` (records), `<<T1, T2>>` / `Tuple(T1, T2)` (heterogeneous tuples)
- Annotate every `CONSTANT`, `VARIABLE`, empty literal (`\* @type: Set(Int); Empty == {}`), and polymorphic helper; always run `scripts/run_apalache.sh typecheck 02_models/<Mod>.tla` first.

### 3.2 Five compiler-critical Apalache rules (read before writing symbolic TLA+)

1. **NEVER write `x \in 0..16777215` in Apalache.** In Apalache, `a..b` constructs an
   explicit finite set of `b - a + 1` elements in memory — wide ranges blow up RAM before
   Z3 ever runs! Always bind wide symbolic integers over `Int` with linear inequalities:
   ```tla
   \* In ConstInit / Init / IndInv:
   /\ dbNode \in Int /\ 0 <= dbNode /\ dbNode < 16777216

   \* In Next (nondeterministic input choice):
   /\ \E sz \in Int:
        /\ 1 <= sz /\ sz <= MAX_FRAME
        /\ globalOut' = globalOut + sz
   ```
   *(Small ranges like `0..3` for replica counts are fine; wide data ranges must use `\in Int` + inequalities.)*

2. **Model fixed-width C/Rust integer overflow & bit-packing explicitly.** TLA+ and SMT `Int`
   are mathematical integers — they **never** overflow or wrap. If production code uses
   `uint32_t`/`uint64_t` bit shifts, masks (`& 0xFFFFFF`), or modular wraparound, encode the
   exact modulo/division (`x % 16777216`, `x \div 16777216`) and input width bounds
   (`0 <= x /\ x < 2^64`), citing the C/Rust type declaration at `file:line`.
   - **Signed division/modulo trap:** TLA+ `\div` and `%` use floor/Euclidean semantics
     (`(-100) \div 3 = -34`), whereas C/Rust `/` and `%` truncate toward zero (`-33`), and
     Apalache/TLC differ when divisor `b < 0`. Keep divisors strictly positive (`b > 0`) and
     handle negative dividends explicitly if the code is signed.

3. **Stay in Linear Integer Arithmetic (`QF_LIA`) whenever possible.** Multiplying by a
   known constant (`16777216 * spc + db`, `2 * quorum > N`) is linear and Z3 solves it in
   milliseconds. Multiplying, dividing, or taking modulo by **two symbolic variables**
   (`x * y`, `x % y`) enters non-linear arithmetic (`QF_NIA`) and can stall the solver.
   Cross-multiply constant percentage/ratio thresholds instead of dividing: e.g. write
   `used * 5 >= cap * 4` rather than `(used * 100) \div cap >= 80`.

4. **No heterogeneous record unions.** Snowcat rejects unions of records with different
   field sets (e.g. `[type: {"1a"}, bal: Int] \union [type: {"1b"}, bal: Int, val: Int]`).
   Instead, model disjoint message/event channels as a **record of typed sets**:
   ```tla
   \* @type: {m1a: Set({bal: Int}), m1b: Set({bal: Int, val: Int})};
   VARIABLE msgs
   ```

5. **Parenthesize `SUBSET` and `DOMAIN`.** Apalache 0.63+ aligns with `tla2tools` operator
   precedence: write `(SUBSET S) \cup T` and `(DOMAIN f) .. n`, never bare `SUBSET S \cup T`.

6. **Single-spec `BoundedMode` & TLC 32-bit SANY guards (`references/performance.md` §3.1).**
   Prefer a single module parameterized by `CONSTANT BoundedMode` (`\* @type: Bool;`) so
   TLC checks `BoundedMode = TRUE` (`--coverage`) and Apalache checks `BoundedMode = FALSE`
   without maintaining two drifting `.tla` files. Because TLC's SANY parser runs signed
   32-bit `Integer.parseInt` on **every decimal literal in the file** (even inside dead
   `ELSE` branches!) and TLC's runtime `IntValue` is 32-bit:
   - **Never** write a decimal token `> 2147483647` (e.g. `60000000000` or `4294967296`);
     build wide constants from `<= 10^9` factors (`60 * 1000000000`, `TWO_32 * TWO_32`).
   - Gate runtime evaluation of `U64_MAX`/`U128_MAX` behind
     `EffMax == IF BoundedMode THEN SmallCap ELSE U64_MAX`.

### 3.3 Running Symbolic BMC
```sh
scripts/run_apalache.sh typecheck 02_models/L1_KeySym.tla
scripts/run_apalache.sh bmc 02_models/L1_KeySym.tla \
    --cinit=ConstInit --init=Init --inv=KeyInjective --length=0 --no-deadlock
# Or multi-step protocol unrolling up to depth K:
scripts/run_apalache.sh bmc 02_models/L1_BudgetSym.tla \
    --cinit=ConstInit --init=Init --inv=BudgetCoherent --length=12
```
- `--length=0` checks `ConstInit /\ Init => Inv` over the entire symbolic Cartesian product
  of initial inputs (ideal for encoders, bit-packing, static routing/quorum algebra).
- `--length=K` checks all execution paths up to `K` steps over full symbolic domains.

---

## 4. Mode S2 — Symbolic Inductive Invariants & the CTI loop

Symbolic BMC up to `--length=K` still bounds step depth. When bugs could hide behind
arbitrary counter drift, unbounded retries, or long-lived epochs, prove safety for **all
depths $\forall k \ge 0$** by synthesizing an **Inductive Invariant (`IndInv`)** and
discharging all three obligations mechanically via `scripts/run_apalache.sh inductive`:

1. **Base case (`k = 0`):** $\text{Init} \implies \text{IndInv}$
   (`apalache-mc check --init=Init --inv=IndInv --length=0`)
2. **Inductive step (`k = 1`):** $\text{IndInv} \land \text{Next} \implies \text{IndInv}'$
   (`apalache-mc check --init=IndInv --inv=IndInv --length=1 --no-deadlock`)
3. **Property entailment (`k = 0`):** $\text{IndInv} \implies \text{Safety}$
   (`apalache-mc check --init=IndInv --inv=Safety --length=0`)

```sh
scripts/run_apalache.sh inductive 02_models/L2_WatermarkSym.tla \
    --cinit=ConstInit --init=Init --indinv=IndInv --inv=NoLostWrite
```

### The Counterexample-to-Induction (CTI) Prompt Loop

A raw target property `Safety` is almost never inductive on its own (`IndInv_0 == TypeOK /\ Safety`
usually fails the Inductive Step from an unreachable pre-state `State 0`). Drive the
**CTI strengthening loop** systematically:

1. **Seed:** Start with `IndInv == TypeOK /\ Safety` (where `TypeOK` constrains every
   variable's symbolic domain, e.g. `lsn \in Int /\ lsn >= 0`, never finite `0..3` ranges).
2. **Run `inductive`:**
   - If **Base** fails → either `Safety` already fails at `Init` (real candidate!), or a
     strengthening lemma you added is false at startup (fix your lemma).
   - If **Step** fails → `run_apalache.sh` prints the 2-state SMT witness (`State 0` $\to$
     `State 1`) where `State 0` satisfies `IndInv` and one `Next` transition reaches
     `State 1` violating `IndInv`.
3. **Triage `State 0` (Reachable Bug vs. Unreachable CTI Artifact):**
   - Ask: *Can production execution actually reach `State 0` from `Init`?*
   - Check with bounded `bmc` (`--init=Init --inv=Safety --length=10`) and by reading the
     code transitions that write `State 0`'s variables.
   - **Reachable `State 0`:** Stop strengthening! Reconstruct a concrete trace from `Init`
     to `State 1` via `bmc`, screen with `lessons.md` R1–R5, and report as **candidate**.
   - **Unreachable `State 0` (garden-of-Eden state):** `State 0` violates an auxiliary
     coupling invariant that the code maintains (for example, `globalOut = 0` while
     `connOut["c1"] = 500`, or `committed > durable_wal` without crash).
4. **Strengthen with a code-anchored lemma:**
   - Verify in production source (`file:line`) that the coupling actually holds across every
     code path.
   - Add it as a named, commented top-level conjunct (`Lemma_GlobalAccounting` citing
     `file:line`) to `IndInv` (flat top-level conjunctions let Apalache split `IndInv'` into
     fast independent `QF_LIA` VCs), and re-run `scripts/run_apalache.sh inductive` (which
     checks `base`, `step`, and `entailment` concurrently and fails fast in seconds if a
     candidate lemma breaks `base` or `entailment`).
   - Repeat until Base, Step, and Entailment all report `NoError`.

> **Anti-cheat guardrail:** Never strengthen `IndInv` (or `ConstInit`) with a predicate that
> excludes reachable caller inputs or tolerated faults unless you verify it in-tree
> (`file:line`). If induction only succeeds under an external caller/deployment bound you
> cannot prove from code, record the result as **candidate** (or conditional contract) per
> `lessons.md` R1.3 / R4.1 — never an unconditional `PASS`.

---

## 5. Vacuous-pass protection, audit logging, and offline fallback

### 5.1 Guarding against vacuous symbolic PASS (mandatory)
Apalache checks SMT satisfiability (`Init /\ Next /\ ~Inv`); it does **not** emit TLC's
per-action `-coverage` table. If a typo makes an action guard identically `FALSE`, both
`bmc` and `inductive` pass **vacuously** for that action! Prevent dead-spec blind spots via
one of two checks:

- **Preferred (dual-engine twin):** Run `scripts/coverage.sh` with TLC on a small concrete
  `.cfg` of the same module (or its finite twin `L{n}_{Mod}.tla` alongside
  `L{n}_{Mod}_Sym.tla`) to confirm every action fires (`B > 0`), **then** run Apalache for
  the full symbolic domain / inductive proof.
- **Pure-symbolic witness check:** For any action `Act` that only fires above wide numeric
  thresholds (unreachable in small TLC), run a negated witness query
  `CanFire_Act == ~ActionFiredFlag` (or check a 1-step witness) in Apalache to confirm Z3
  finds `Error` (meaning `Act` is satisfiable!), then remove the temporary negated invariant.

### 5.2 Recording symbolic runs (`03_run_log.md`, `05_output.md`, `MEMORY.md`)
- In `01_reasoning.md`: explain *why* explicit enumeration exploded, which §2 reductions
  were applied, and (for Mode S2) list every strengthening lemma in `IndInv` with its
  `file:line` justification.
- In `03_run_log.md`: record the exact `run_apalache.sh` commands, mode (`bmc --length=K`
  or `inductive`), Z3 verdict (`NoError` / `Error`), wall-clock seconds, and the vacuous-pass
  coverage check.
- In `05_output.md` & `MEMORY.md`: state the verification scope honestly:
  - `PASS (symbolic BMC, length=K, full 64-bit domain)` — proves no bug within $\le K$ steps
    across the entire symbolic input/parameter space.
  - `PASS (symbolic inductive, unbounded depth & domain)` — proves the invariant for all
    reachable depths $\forall k \ge 0$ under the modeled transitions.

### 5.3 When Apalache is unavailable (air-gapped / restricted host)
If `install_apalache.sh` cannot download `apalache.tgz` and no local binary exists:
1. Apply **§2.1 Skolem witness projection** and **§2.3 string tags** first — many "exploded"
   models collapse from $10^{12}$ states to $< 10^5$ states in plain TLC once concrete maps
   over all keys are projected to 1–2 witness keys + an environment counter!
2. Pair exhaustive small-domain TLC with **TLC simulation mode** for deeper bug hunting:
   `scripts/run_tlc.sh 02_models/L{n}_{Mod}.tla 02_models/L{n}_{Mod}_sim.cfg -- -simulate num=50000,depth=100`
   (report simulation runs as incomplete search, never as an exhaustive `PASS`).
3. Document the exact unverified numeric/depth wall in `05_output.md` and give the user the
   manual `apalache.tgz` placement command printed by `install_apalache.sh`.
