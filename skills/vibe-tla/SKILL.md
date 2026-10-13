---
name: vibe-tla
description: >-
  Find real concurrency, durability, and ordering bugs in a codebase by writing
  code-faithful TLA+ specifications, model-checking them with TLC, and reporting each
  violation as a fix-ready bug report. Self-contained and project-agnostic: it keeps its
  own per-repo workspace and long-term memory, so it works on any repository with no
  external setup. Use it whenever the user wants to formally verify, model-check, or
  TLA+/TLC a subsystem; hunt for races, lost updates, deadlocks, stale reads, broken
  invariants, or quorum, replication, and recovery bugs; or reason about whether an
  interleaving can violate a property. Commands: init sets up the workspace and TLC
  toolchain; check runs the full learn-spec-check-triage-report loop on a component (named
  exactly or described fuzzily — it resolves an ambiguous target itself); sync
  detects model drift; resume finishes an interrupted run; status shows the ledger;
  coverage reports fidelity and TLC coverage; effort tunes how exhaustively to explore.
  Prefer this skill whenever the user mentions TLA+, TLC, model checking, or formal
  verification.
---

# vibe-tla — code-faithful TLA+ bug-hunting for any repo

You produce **mechanically-checked, code-faithful evidence**: TLA+ specs whose every
modeled transition is anchored to a real `file:line`, checked with TLC, and documented
so a skeptical reviewer can read the spec with the source open beside it. A TLC
violation becomes a bug report only after it survives a refutation checklist; honesty
about *candidate* vs *confirmed* is the whole point.

This skill is **standalone and project-agnostic**. It carries no paths, no module
names, no quorum constants for any particular codebase. Everything specific to the repo
you are working on lives in a **per-repo workspace** that `init` creates and that
`check`/`sync` read and grow as long-term memory. Nothing here depends on the repo you
test it against.

## How this skill is organized (read on demand)

`SKILL.md` (this file) is the dispatcher and command summaries. The **full step-by-step
procedure for each command lives in `references/commands.md`** — read the section for the
command you're running before executing it. Deeper standards live in the other references,
relative to this skill's directory — read the one you need, when you need it:

- `references/commands.md` — **the exact procedure for every command** (`init`, `check`,
  `sync`, `resume`, `advance`, `status`, `coverage`, `effort`, `review`, `fix`).
- `references/methodology.md` — **the binding standards**: the ladder method, the two
  verification modes, the standard level layout, the classification vocabulary, and the
  definition of done. Read before authoring any spec.
- `references/lessons.md` — **the case law**: generalized, repo-agnostic rules (R1–R5)
  distilled from real verification mistakes — denotation-before-invariant,
  staleness-needs-a-witness, model-the-runtime's-concurrency, the-answer-is-the-finding,
  model-the-designed-regime. **Read before classifying any violation.**
- `references/authoring.md` — how to write a faithful spec: the `var ↔ code` map, action
  style, fault-injection patterns, TLA+ idioms, and how to iterate to "runs clean in TLC".
- `references/tlc-setup.md` — the TLC toolchain, the canonical invocation, determinism,
  config keys, and scratch cleanup.
- `references/workspace.md` — the per-repo workspace layout, the memory files, and the two
  install shapes / scope rule in full.
- `references/coverage.md` — **fidelity & coverage**: how to measure how faithfully a spec
  mirrors the code and read TLC's action coverage.
- `references/ci-integration.md` — **experimental**: wiring `sync` into CI so a PR touching
  modeled code flags model drift.

Bundled scripts (in `scripts/`, self-locating) do the repetitive mechanical work so you
don't reinvent it each run: `install_tlc.sh`, `run_tlc.sh`, `new_level.sh`, `status.sh`,
`coverage.sh`, `anchors.sh`, and `get_repo.sh` (clone/track the target repo in a standalone
install). Prefer them over hand-rolled equivalents.

## Command dispatch

The user invokes `/vibe-tla <command> [args]`. The first whitespace-delimited token is the
command; route it to its procedure in `references/commands.md`:

- `init` · `check` · `sync` · `resume` · `advance` · `status` · `coverage` · `effort`, and
  the dev-cycle `review` · `fix` — each has a summary under **Commands** below and a full
  step-by-step section in `references/commands.md`.
- anything else, or empty → print the one-line usage for every command and stop.

**Scope — resolve `<repo-root>` before anything else** (full rule + the two install shapes:
`references/workspace.md`):

1. If the target workspace's `config.env` records `REPO_ROOT` from a prior `init`, honor it.
   (In a standalone install you *locate* that workspace via step 3's `active.env` first;
   `config.env` then confirms the resolution — the steps are precedence, not lookup order.)
2. **Embedded install** (skill at `<repo>/.claude/skills/vibe-tla/`) ⇒ `<repo-root>` = the
   project that owns that `.claude/` — the install location (follow the symlink's *logical*
   path, not its target), never the working directory or a sibling-holding parent.
3. **Standalone install** (user-global / agent skill store, no owning project) ⇒ `<repo-root>`
   = the active clone in `${VIBE_TLA_HOME:-$HOME/.vibe-tla}/active.env`
   (`scripts/get_repo.sh active`); if none is recorded, tell the user to run
   `/vibe-tla init <repo-url>` first — do not fall back to the working directory.

`$WORKSPACE` = `<repo-root>/tla`. Everything the skill reads, writes, and greps stays
**inside `<repo-root>`** — never a sibling or a parent. In remote mode (`REPO_MODE=remote`),
`check` and `sync` first `scripts/get_repo.sh refresh` to read current upstream code.

**Effort** for a run: an explicit `--effort high|low|medium` wins; else `VIBE_TLA_EFFORT` in
`config.env` (set by `/vibe-tla effort`); else `medium`. It scales how exhaustively `check`
and `coverage` explore.

## Commands — summaries (full step-by-step in `references/commands.md`)

**Before running a command, read its section in `references/commands.md`** — that file holds
the exact procedure; the summaries below are orientation. Every command operates strictly
inside `<repo-root>` and keeps the workspace memory consistent (`references/workspace.md`).

- **`init [repo-url]`** — set the repo up to verify, once. Resolve `<repo-root>` (embedded:
  the owning project; standalone: clone the URL — or use a local path in place — via
  `get_repo.sh`), create `$WORKSPACE`,
  install the TLC toolchain (`install_tlc.sh`), learn the architecture, and write the memory
  files (`PROFILE`/`MEMORY`/`LESSONS`/`ROADMAP`). Idempotent.
- **`check <keywords> [context] [goal] [--ask]`** — the **discover** step. `<keywords>` may be
  exact names or a fuzzy area description — `check` resolves an ambiguous target itself
  (survey → rank → announce its pick; runner-ups go to the roadmap backlog), asking only when
  nothing matches or `--ask` forces the interactive choice. Then map to a ladder/level, read
  the source, author a code-faithful spec, run TLC to a clean run, triage.
  **Run-until-complete** (stage on interrupt, `resume` later); emits **candidates** only — it
  never self-declares `confirmed`. Context is a hint, not evidence.
- **`sync <keywords>`** — cheaply detect whether the code drifted out from under a model
  (re-anchor cited `file:line`s). Revise as a `*_v2` bump on material drift; else "still
  faithful". Refreshes the clone first in remote mode.
- **`resume [keywords]`** — finish an interrupted `check` from its `## STAGED` note. If nothing
  is staged, stop and point to `advance` — never invent levels.
- **`advance [ladder] [--to Ln | --count N]`** — continue a clean ladder by running its next
  *planned* level(s). Announce which levels before running; distinct from `resume`.
- **`status [keywords]`** — the read-only ledger (`status.sh`) + interpretation (open
  candidates, staged, drift, next backlog item). Points to each ladder's `TODO.md`.
- **`coverage [keywords]`** — a fidelity + TLC action-coverage report (`coverage.sh`); flags
  zero-coverage (dead-spec) actions.
- **`effort <high|low|medium>`** — set how exhaustively `check`/`coverage` explore (workspace
  default in `config.env`; per-run `--effort` override).

## The development-cycle loop — `review` → `fix`

`check` discovers **candidates**; these two commands drive each to a resolved end and
re-verify any fix, closing **check → review → fix → (loop back to check)**. Full steps in
`references/commands.md`.

```
check <component>   → candidate(s)
review [<finding>]  → confirmed  |  retired: refuted      (the true-positive gate)
fix <finding>       → retired: fixed                      (change + validation re-check)
check ...           → next round  (or `advance` for the next ladder rung)
```

`retired` is the neutral **closed** state: not every finding is *fixed* (some are refuted or
safe-by-design), but every resolved one is *retired*, and the reason is recorded.

- **`review [finding]`** — the true-positive gate: independently try to *refute* a candidate
  (run the `lessons.md` R1–R5 checklist adversarially; spawn a fresh reviewer agent when
  available). Survives → **confirmed**; else → **retired: refuted**; hinges on one owner fact
  → stays **candidate**. Don't trust the agent that found the bug to also clear it.
- **`fix <finding>`** — apply the minimal code (or spec) change **and** prove it: model the
  fixed code as a `*_v2` spec and re-run TLC → **retired: fixed**. Show the diff; don't
  commit/push without asking.

## The bar (non-negotiable, every command)

- **Code-faithful, no assumptions.** Every modeled transition cites a verified `file:line`.
  "I think it probably…" is a defect — read the source. Unverified behavior is
  `TODO`/`UNCLEAR`, never invented.
- **`var ↔ code` map** at the top of every `.tla`.
- **Two valid modes**, picked to match the code (transcription vs faithful fault injection);
  fault injection models only design-tolerated faults, each documented.
- **Honest findings.** PASS / candidate / confirmed / refuted / safe-by-design / retired. A
  candidate stays a candidate until its one open precondition is discharged (by `review`).
- **Reproducible.** Every number you cite, you ran. Counterexamples come from the real trace,
  not memory.
- **Memory is the product too.** The workspace is long-term memory — keep it consistent so
  the next run, days later, picks up where this one left off.

Full standards, schema, and definition-of-done: `references/methodology.md`. Full command
procedures: `references/commands.md`.
