# coverage.md — fidelity & coverage for vibe-tla

A reviewer's first two questions about any model are *"does it faithfully mirror the real
code?"* and *"how much of the code/behavior did it actually cover?"*. This file defines the
report that answers them — produced by the `coverage` command and carried in every level's
`05_output.md`. Keep the three notions below separate; they are measured differently and
oversold differently.

## Table of Contents

- The three notions, kept separate (fidelity · code coverage · model coverage)
- Reading TLC's action-coverage block
- The `## Fidelity & coverage` block in `05_output.md`
- How to read it / what to fix

---

## The three notions, kept separate

### 1. Fidelity (asserted — a structured self-report from the model)

How faithfully the spec mirrors the code. This is partly modeler-asserted, so be honest
that it is a *structured self-report*: the `var ↔ code` map and `01_reasoning.md` are the
evidence a reviewer actually checks. Report:

- **Transitions modeled vs UNCLEAR/TODO.** Count the transitions you modeled, each with a
  verified `file:line`, against the ones marked `UNCLEAR`/`TODO` because you could not
  pin them in source. `12 transitions, all cited file:line; 1 UNCLEAR` is honest; a model
  with many `UNCLEAR` is low fidelity, not done.
- **Abstractions taken**, lifted from `01_reasoning.md`, each with a one-line soundness
  argument (why collapsing/bounding/omitting that detail cannot hide the bug class under
  test). An abstraction without a soundness note is a hole.
- **Map completeness.** Does the `var ↔ code` map cover *every* variable and *every*
  action? A variable or action with no code anchor is an un-grounded part of the spec —
  name it.

Fidelity is asserted; the map + `01_reasoning.md` are where a skeptic verifies the
assertion. Point at them.

### 2. Code coverage (asserted — with a stated denominator)

Which functions/branches of the component the model represents, **over a named
denominator**. State the denominator explicitly — *"the 6 state-machine transitions of the
write path"*, *"the 4 branches of the read-member selector"* — then give an honest fraction
over it (`modeled 5 of 6`). Never a bare percentage with no denominator: `83%` of *what?*

This is **design-surface coverage, not line coverage of an executed binary** — say so
plainly so it is not mistaken for the latter. You are claiming "the model represents these
named branches of the source", not "this fraction of lines ran". If the model only covers
part of the surface, that is fine — **scope the claim to what is covered** rather than
inflating the denominator to look complete.

### 3. Model coverage (automatic — from TLC `-coverage`)

Did TLC actually exercise every action in the spec? An action that **never fired** is
**dead spec** — usually a guard that never holds, i.e. a real modeling bug that can make a
PASS meaningless. This one is not asserted: TLC measures it. `scripts/coverage.sh` runs the
check and the `coverage` command surfaces it; the rule for reading the raw output is below.

---

## Reading TLC's action-coverage block

`run_tlc.sh ... --coverage` (i.e. TLC `-coverage 1`) prints an action-coverage block.
Captured from a real 2-action toy spec with one deliberately-dead action
(`Dead == FALSE /\ x' = x`), verified empirically:

```
The coverage statistics at ... (see https://explain.tlapl.us/module-coverage-statistics ...)
<x line 3, col 10 to line 3, col 10 of module L0_Demo>: 2
<Init line 4, col 1 to line 4, col 4 of module L0_Demo>: 1:1
  line 4, col 9 to line 4, col 13 of module L0_Demo: 1
<Up line 5, col 1 to line 5, col 2 of module L0_Demo>: 2:2
  line 5, col 9 to line 5, col 13 of module L0_Demo: 2
<Down line 6, col 1 to line 6, col 4 of module L0_Demo>: 0:2
  line 6, col 9 to line 6, col 13 of module L0_Demo: 2
<Dead line 7, col 1 to line 7, col 4 of module L0_Demo>: 0:0
  line 7, col 18 to line 7, col 23 of module L0_Demo: 0
<TypeOK line 10, col 1 to line 10, col 6 of module L0_Demo>
  line 10, col 11 to line 10, col 20 of module L0_Demo: 3
```

**How to read a line.** A top-level `<NAME line ... of module M>: A:B` is an **action**.
The two numbers are `distinct:generated` — `A` = distinct states *first found* via this
action, `B` = total states it *generated*.

**The dead-spec rule (B is what matters, not A):**

- **`B == 0`** — `Dead: 0:0` above — the action was **never enabled** in any reachable
  state. Dead spec: a guard that never holds. **Flag it.** In practice TLC emits a `0:0`
  line for an unenabled named disjunct of `Next` (as the empirical capture shows), so a
  never-fired action surfaces *as a `0:0` line* — which is exactly the case the tooling
  catches.
- **`Down: 0:2`** (`A == 0`, `B == 2`) is **not** dead — it fired twice but only reached
  already-seen states. **Do not flag `A == 0`; flag `B == 0`.**
- Lines that are operators/invariants (`TypeOK` above — note it has **no** `:A:B`) and
  indented sub-expression lines (no `<...>` wrapper, a single trailing number) are **not**
  actions. Ignore them for the dead check.

`scripts/coverage.sh` automates exactly this parse — it runs TLC with `--coverage`, extracts
the top-level `<...>: A:B` action lines, and flags every one with `B == 0`, exiting
non-zero if any are dead. (It flags the `0:0` lines TLC prints; it does **not** read the
`.tla` to diff against the spec's declared actions, so an action that produced *no*
coverage line at all would not be flagged — but since an unenabled disjunct yields a `0:0`
line, that realistic case is covered.) The `coverage` command surfaces those flags. When
you write or trust the parser, reproduce the toy spec above with a deliberately-FALSE guard
and confirm it reports `0:0`.

---

## The `## Fidelity & coverage` block in `05_output.md`

Every level's `05_output.md` carries this block, three bullet lines, matching exactly what
`scripts/new_level.sh` stubs:

```
## Fidelity & coverage  (see references/coverage.md)
- Fidelity: <K> transitions modeled, all cited file:line; <U> UNCLEAR/TODO; abstractions listed in 01_reasoning.md
- Code coverage: modeled <m> of <n> relevant functions/branches in <source root> (denominator stated)
- Model coverage: TLC --coverage — <all actions fired | actions with 0 coverage: …>
```

- **Fidelity** — the transition count, how many are `UNCLEAR`/`TODO`, and a pointer to
  the abstractions in `01_reasoning.md`. Confirm the `var ↔ code` map covers every variable
  and action.
- **Code coverage** — the honest fraction `m`/`n` over a **named** denominator and source
  root. Design-surface, not line coverage.
- **Model coverage** — `all actions fired`, or the names of any action with zero coverage
  (`B == 0`), straight from the TLC block.

Keep the wording identical to the stub so the report is uniform across levels. **Freeze
rule:** while a level is still open, this block is written as part of `05_output.md`. Once
the level is **closed** (`05` frozen — see `methodology.md` §schema), the `coverage`
command must **not** edit `05` in place; it writes the refreshed block to `06_notes.md`
(or a separate coverage report) and notes any delta against the frozen `05`. To change a
frozen `05` itself, bump the spec (`*_v2`) and re-close.

---

## How to read it / what to fix

- **A zero-coverage action (`B == 0`)** is a **model bug**, not a curiosity — an action
  that never fires means a guard never holds, and a PASS that skipped it proves less than
  it claims. **Fix it before trusting the verdict**: correct the guard, the `Init`, or the
  constants until the action fires (or delete it if it is genuinely unreachable and
  document why).
- **Many `UNCLEAR`/`TODO`** means **low fidelity** — you modeled behavior you did not pin
  in source. Read more of the code and either anchor those transitions to a `file:line` or
  state plainly that they are out of scope.
- **Low code coverage** is fine *if scoped honestly*: either **model more** of the named
  surface, or **scope the claim** to the branches you actually cover. What is never
  acceptable is reporting a small covered slice as if it were the whole component.
