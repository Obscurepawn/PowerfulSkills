# methodology.md — the binding standards for vibe-tla

These are the standards that make a model worth trusting. They are project-agnostic:
nothing here names a repo, a module, or a constant. Read this before authoring any
spec. If a request conflicts with these rules, say so — do not silently lower the bar.

> A model is only as valuable as its **fidelity to the code** and the **integrity of
> its claims**. When in doubt, read the source, state the uncertainty, keep the bar high.

---

## Table of Contents

- §1 The goal
- §2 The ladder method — why levels, not one mega-spec
- §3 Two valid modes — pick the one that matches the code
- §4 Code-faithfulness — the rules a reviewer checks first
- §5 The standard level layout
- §6 Classification vocabulary
- §7 Reproducibility & honesty
- §8 Definition of done

## 1. The goal

Produce **mechanically-verified evidence (TLA+ / TLC)** about a real subsystem: either a
**finding** (a code path can violate a property a developer expects) or a **validated
contract** (under the system's own fault model, the property holds). Both are valuable;
a clean run under a faithful fault model is a genuine correctness result, not a
disappointment. What is *not* acceptable is a model whose verdict is an artifact of an
unfaithful abstraction, or a finding reported as a bug before its preconditions are
discharged.

---

## 2. The ladder method — why levels, not one mega-spec

Verify a subsystem as a **ladder** of levels `L0 → Ln`, each adding exactly one concern,
each independently model-checked. This beats one monolithic spec for five reasons:

1. **Tractable.** Each level fits in TLC's budget (target a few minutes per primary cfg).
2. **Independent invariants.** A counterexample at one level is interpretable without
   unpacking the whole stack.
3. **Refinement story.** Higher levels refine lower ones — you can claim compositional
   verification, not one giant proof.
4. **Stop-anywhere shippable.** If L4 explodes, L0–L3 are still real results.
5. **Audit trail.** Each level carries its own inputs/reasoning/spec/run/output, so the
   write-up drafts itself from the directory.

L0 pins the lowest-level primitive's exact contract (often a single state machine or
counting rule, in isolation). Each higher level lifts the lower level's invariants and
adds one new source of complexity: more concurrency, shared state, faults, lifecycle,
multi-instance composition. Name a level `L{n}_{slug}` where the slug names the concern.

A ladder starts as a single `PLAN.md` (charter + the verified concurrency model + the
level plan), frozen when L0 begins; further design goes into each level's
`01_reasoning.md`. Add a `ROADMAP.md` status table and a `TODO.md` action digest at L0 —
the latter is the single place a user reads to see what's open and what to run next for
this component, without opening each level folder (`workspace.md`).

---

## 3. Two valid modes — pick the one that matches the code {#modes}

There are **two first-class bug-hunting modes**. Choosing the wrong one wastes the run.

### 3.1 Faithful transcription (zero fault injection)
Replicate the code exactly and let TLC report whether the *unmodified* logic violates a
developer expectation. This is right for **control-flow / state-machine** logic where the
bug, if any, is an interleaving of ordinary steps. A violation here is a **candidate real
bug**.

> Caveat learned the hard way: if the model is a *looser* abstraction than the code — it
> omits a guard the code already has (a fallback path, a monotone setter, a dispatch
> affinity, a gate's true operand set) — TLC reports violations that are **artifacts of
> the model**, not the system. Such "findings" must be refuted by reading the code; the
> lesson is the model was under-faithful, not that a bug exists. See `lessons.md`.

### 3.2 Faithful fault injection (required for fault-tolerant code)
For **quorum, replication, durability, recovery, GC/truncation, reconfiguration** code,
the no-fault mode is **structurally unable to find bugs**: a W-of-N quorum exists only to
tolerate a down node, a lost/reordered message, a slow replica, a crash mid-operation.
Run such code with all nodes up and no loss and it is trivially correct — you removed the
entire regime it was written to survive. So you **must** inject the faults the system
*claims to tolerate*. The discipline is **faithfulness to the failure model**, not
absence of faults:

- Inject only faults the code is designed to survive (crash-stop, message
  loss/reorder/duplication, partition, slow/lagging replica, crash-restart with partial
  durable state). Document each injected fault and the design statement that says it is
  tolerated (a code comment, a config bound, an owner-confirmable contract).
- **Do not** inject faults the system does not claim to tolerate (e.g. Byzantine
  corruption under a fail-stop design), and do not blur a tolerated-fault model with an
  arbitrary-chaos model.
- A property violation under a tolerated fault is a **candidate real bug**, reported
  exactly like a transcription finding. A *clean* run under the full tolerated-fault set
  is a **genuine correctness result**.

Name fault variants clearly (`*_Crash`, `*_LossReorder`, `*_UnderQuorum`, …) and state in
the `var ↔ code` map which faults are modeled and why each is in the design's failure
model. Use `*_Unsafe` **only** for deliberate guard-demonstration models (showing a
lemma's hypothesis is load-bearing); those are **never** presented as a real finding.
Keep *tolerated-fault → candidate bug* and *removed-guard → demonstration* clearly
separate.

---

## 4. Code-faithfulness — the rules a reviewer checks first

- **Every modeled transition cites a verified `file:line`.** If you have not read the
  code, you may not model it. Unverified behavior is `TODO`/`UNCLEAR` — never guessed.
- **No assumptions about behavior.** If unsure, find the truth in the source.
- **`var ↔ code` mapping is required** at the top of every `.tla`: every variable and key
  action maps to a code identifier (`file:line`), so a reviewer can read the spec with
  the source open beside it. For each watermark/counter, record what it **denotes** per
  its producer (a progress marker vs a content boundary — `lessons.md` R1.1).
- **The model's concurrency must be the runtime's concurrency**, not the source file's
  apparent one — derived from the dispatch/ownership/sharding topology (`lessons.md` R5).

---

## 5. The standard level layout {#schema}

Every level directory `L{n}_{slug}/` contains six numbered markdown files plus one
numbered models folder, written in this order:

```
L{n}_{slug}/
├── 00_input.md           # inputs from L(n-1) + new code refs + supplied context
│                         #   with its verification status        (FROZEN at close)
├── 01_reasoning.md       # what is concrete vs abstracted, and why each abstraction is sound
├── 02_models/            # the spec + ALL its configs — real files, NO symlinks
│   ├── L{n}_{Module}.tla #   the spec; basename MUST equal the MODULE name
│   ├── L{n}_{Module}.cfg #   primary config
│   └── *.cfg             #   one extra cfg per scaling round / scenario
├── 03_run_log.md         # exact commands, per-cfg states/depth/time/result, coverage, wall-clock
├── 04_counterexamples.md # required iff a property is violated — from the real trace
├── 05_output.md          # what this level proved + fidelity/coverage + exports (FROZEN at close)
└── 06_notes.md           # optional: snippets ready to lift into a write-up/report
```

- The numbering forces order: you cannot write `03` without the spec, nor `05` without
  `03`. The spec and its configs live **together in `02_models/` as real files — no
  symlinks** — so the layout is self-explanatory: open the folder and you see exactly
  what was checked. The `.tla` keeps its module-named basename (TLC requires the basename
  to equal the `MODULE` name); run TLC on it directly via
  `scripts/run_tlc.sh 02_models/L{n}_{Module}.tla`.
- **`00` and `05` are frozen** at close. To change a lower claim, add a bumped spec
  (`02_models/L{n}_{Module}_v2.tla`) and re-run — never edit a frozen file in place. This
  protects the audit trail. (One carve-out: the **fidelity & coverage block** is written
  into `05_output.md` *while the level is still open*, as part of closing it. Once `05` is
  frozen, the `coverage` command must not touch it — it writes a refreshed report to
  `06_notes.md` and notes the delta. See `coverage.md`.)
- `04_counterexamples.md` is **required** on any violation. Match this depth: full trace
  table with all variables, "What it shows", "Root cause (verified, not assumed)" with
  code snippets + `file:line`, and "Triage" ending in one precise owner question.
- `05_output.md` carries the **fidelity & coverage** block (see `coverage.md`): how much
  of the code path is modeled, and TLC action coverage (a zero-coverage action is dead
  spec).

Scaffold the skeleton with `scripts/new_level.sh`.

---

## 6. Classification vocabulary {#classification}

Classify every result as exactly one of:

- **PASS** — the modeled logic validated the property under the faithful model.
- **candidate** — a real code path violates a developer expectation, *pending one
  precisely-stated, owner-confirmable fact*. The fact's answer is the finding; CANDIDATE
  means strength is exactly "pending that answer", not "probably a bug".
- **confirmed** — the precondition has been discharged (from source, or by the owner).
  Never upgrade candidate→confirmed without that evidence.
- **refuted** — the violation was an artifact (under-faithful model) or is unreachable by
  design/deployment. Keep the demonstrating config as a tripwire (`lessons.md` R4.3).
- **safe-by-design** — the code admits the behavior but the design tolerates it; the
  property as stated was wrong, not the code.
- **retired** — the neutral **closed** state: a finding that has reached a terminal
  resolution and is no longer open. A `confirmed` bug becomes `retired` once `fix` applies
  the change and the *validation re-check* passes (`retired: fixed`); a `refuted` or
  `safe-by-design` finding is retired by that ruling. Not every finding is *fixed* — but
  every resolved one is *retired*, with the reason recorded. See the development-cycle loop
  in SKILL.md (`check → review → fix`).

Read `lessons.md` before classifying anything. The triage checklist there is binding — it
is also the procedure the `review` command runs adversarially to separate true positives
from false positives / model artifacts / hallucinations.

---

## 7. Reproducibility & honesty

- Every claimed result is reproducible from the committed `.tla` + `.cfg` by re-running
  TLC. If you cite a number, you ran it.
- For a violating run, re-run with `-workers 1` and record those deterministic counts.
  The reproducible facts are the verdict and the violation depth.
- Report TLC outcomes faithfully: real state counts, the real trace, and whether each cfg
  was actually run vs only provided. If something failed or was skipped, say so.
- Don't shrink a model just to finish faster if that drops the concern under test.
  Document state-space walls explicitly; never let truncation read as "covered
  everything".

---

## 8. Definition of done (check before declaring a level complete)

- [ ] Every modeled transition cites a verified `file:line`; nothing guessed.
- [ ] `var ↔ code` map present at the top of the `.tla`, with denotations for watermarks.
- [ ] Mode chosen correctly (transcription vs faithful fault injection) and justified.
- [ ] TLC actually run; `03_run_log.md` has real per-cfg state counts + time + verdict.
- [ ] Any violation has `04_counterexamples.md` from the real trace, at the schema depth,
      ending in an actionable owner question.
- [ ] Finding classified honestly (PASS / candidate / confirmed / refuted / safe).
- [ ] A bug report + suggested fix exists for any finding — concrete, code-anchored.
- [ ] Long-term memory updated and self-consistent (`MEMORY.md`, ladder `ROADMAP.md`,
      ladder `TODO.md`, `LESSONS.md` on any refutation) so a later run can resume.
- [ ] TLC scratch artifacts cleaned up.
