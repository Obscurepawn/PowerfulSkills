# commands.md — the full per-command procedures for vibe-tla

`SKILL.md` routes each `/vibe-tla <command>` to a section here. **Read the section for the
command you are running before executing it** — SKILL.md carries only short summaries; the
step-by-step procedure lives here. Cross-references: binding standards in `methodology.md`,
refutation case law in `lessons.md`, the workspace + memory layout (and the two install
shapes / scope rule) in `workspace.md`, fidelity/coverage in `coverage.md`.

## Table of Contents

- init — set up the workspace + TLC toolchain (once per repo)
- check — discover: model a component and surface candidate bugs
- sync — detect whether the code drifted out from under a model
- resume — finish an interrupted run
- advance — continue a ladder's next planned level(s)
- status — the verification ledger
- coverage — fidelity + TLC action coverage
- effort — how exhaustively to explore
- review — the true-positive gate (dev-cycle)
- fix — apply the change + validation re-check (dev-cycle)

---

## init — `/vibe-tla init [repo-url]`

Goal: make the repo ready to verify, **once**, and write down everything later runs need
so they never re-derive it. Idempotent — if `$WORKSPACE` already exists, treat this as a
refresh: re-verify the toolchain, re-scan architecture if asked, and update, don't
clobber, the memory files.

1. **Determine the repo and create the workspace** (per the scope rule in SKILL.md /
   `workspace.md`).
   - **Embedded install** ⇒ `<repo-root>` = the project owning this skill's `.claude/`
     (installed in `<repo>/.claude/skills/` ⇒ workspace at `<repo>/tla/`, never the parent
     that holds sibling repos). `REPO_MODE=embedded`.
   - **Standalone install** ⇒ get the target repo from the `init` argument if given
     (`/vibe-tla init <repo-url-or-path> [--branch B]`), otherwise **ask the user for the
     code repo URL** (an HTTPS git URL such as `https://code.example.org/team/Repo`). Then
     run `REPO_ROOT="$(scripts/get_repo.sh use <url-or-path> [--branch B])"` — it clones a
     URL into `${VIBE_TLA_HOME:-$HOME/.vibe-tla}/repos/<name>` (or ff-pulls an existing
     clone), uses a local git path in place, records the active pointer, and prints the
     resolved `<repo-root>`. Set `REPO_MODE=remote` for a URL (`REPO_URL=<url>`) or `local`
     for a path.

   **State the resolved `<repo-root>` and `$WORKSPACE` before creating anything**, so a
   wrong scope is caught immediately. Then create `$WORKSPACE/` (= `<repo-root>/tla`) with
   the skeleton from `workspace.md`. Everything this skill writes lives under `$WORKSPACE`;
   it never scans outside `<repo-root>`.

2. **Install / locate the TLC toolchain.** Run
   `REPO_MODE=$REPO_MODE REPO_URL=$REPO_URL scripts/install_tlc.sh "$WORKSPACE"` (the
   `REPO_*` vars are recorded in `config.env`; omit them for a plain embedded install and
   they default to `embedded`). It locates an existing `tla2tools.jar` (env `TLA_TOOLS_JAR`,
   a VSCode TLA+ extension, a system install) or downloads a pinned release into
   `$WORKSPACE/tools/`, verifies it with a smoke spec, and records everything in
   `$WORKSPACE/config.env`. If `java` is missing, tell the user how to install a JRE (17+)
   and stop — TLC needs it. See `tlc-setup.md` if the script can't resolve a jar.

3. **Gather the architecture context** (this is what makes later specs faithful instead
   of guessed). In order of preference:
   - read architecture docs already in the repo (`README`, `docs/`, `ARCHITECTURE.md`,
     design docs, `*.md` near the code) — grep for them;
   - ask the user for pointers: which subsystems matter, where the interesting
     concurrency / durability / quorum / recovery / ordering code lives, any design docs
     or a doc URL (use `WebFetch` if a link is given);
   - infer the source layout: languages, build system, where modules live, the
     runtime/concurrency model (threads? async tasks? a run-to-completion reactor?
     sharded workers?). The **dispatch/ownership topology matters** — later bug triage
     depends on knowing the *runtime's* concurrency, not the source file's apparent one
     (see `lessons.md` R5).

   Use `AskUserQuestion` for the few high-leverage unknowns; don't interrogate.

4. **Write the long-term memory.** Synthesize the above into the workspace memory files
   (full spec in `workspace.md`):
   - `$WORKSPACE/PROFILE.md` — the repo binding: source roots and exclusions, build/run
     model, subsystem map, the concurrency/fault model as understood so far, the TLC jar
     path, and model-size defaults *discovered from this code* (do not import constants
     from any other project — e.g. if it's a quorum system, read its own N/W/R).
   - `$WORKSPACE/LESSONS.md` — seed it by copying this skill's `lessons.md` so the case law
     travels with the repo; it grows with this repo's own refutations.
   - `$WORKSPACE/MEMORY.md` — the running index of everything modeled (starts empty).
   - `$WORKSPACE/ROADMAP.md` — the ladder map / backlog, seeded with the first few
     high-value components identified in step 3 (per `workspace.md`; step 5 names them to
     the user anyway).

5. **Report.** State where the workspace is, that TLC verifies (show the smoke result),
   the subsystem map you captured, and the two or three components that look most worth
   modeling first — and that the user runs `check` to model one.

---

## check — `/vibe-tla check <keywords> [context] [goal] [--ask]`

`<keywords>`: what to model — exact component / class / feature / folder names, **or a
fuzzy, broad description of an area** ("the replication path", "whatever manages page
eviction"). Ambiguous input is expected and fine: step 2 resolves it to a concrete
component and announces the pick — the user does not need to know the code layout.
`[context]`: free-text background — what it does, suspected invariant, related findings, a
team-confirmed fact. `[goal]`: what to verify or hunt for (the developer expectation or the
suspected race). `--ask`: let the user pick the target interactively instead of
auto-resolving an ambiguous `<keywords>`.
**Context is a hint, not evidence** — verify every claim in it against the source before
modeling it; anything you can't verify is marked `UNCLEAR` in the spec, and a fact only the
team/owner can confirm keeps any finding at *candidate*.

This command runs the **entire loop to completion by itself** ("run-until-complete") — do
not stop half-way to ask for permission to continue. The one stop-and-ask check — `init`
was never run — is resolved **up front, before the loop starts**. An ambiguous or fuzzy
`<keywords>` is **not** a reason to stop: resolve it autonomously in step 2
(survey → rank → announce → proceed). Ask only when resolution genuinely fails — nothing in
the repo matches, or the top candidates would produce materially different work and neither
`[context]`, `[goal]`, nor the roadmap breaks the tie — or when the user passed `--ask`.
Once the loop is running, only an **interruption** (not a question) ends it early.
If the loop is interrupted before the level closes (context runs out, a tool fails, the run
is killed), **leave a `## STAGED` note in `MEMORY.md`** carrying the level dir, reached step,
effort, and next step (format in `workspace.md`), so `/vibe-tla resume` can finish it without
restarting. Honor the resolved **effort** level (§effort): it sets the model sizes, how many
cfgs you run, and how hard you push TLC.

1. **Load memory and standards.** Read `$WORKSPACE/PROFILE.md`, `MEMORY.md`, `ROADMAP.md`,
   and `$WORKSPACE/LESSONS.md`; read this skill's `methodology.md` and `lessons.md`. Check
   `MEMORY.md` for any staged/in-progress work on these keywords and resume it rather than
   restarting.

2. **Resolve the target, then map it to a ladder + level.** `<keywords>` need not name a
   component exactly — resolve whatever was given:
   - **Survey.** Grep the source roots from `PROFILE.md` for every plausible match — the
     literal keywords, their synonyms, and the domain nouns in a fuzzy description; cross-check
     the subsystem map in `PROFILE.md` and existing ladders in `MEMORY.md`/`ROADMAP.md`.
   - **Rank.** Score candidates by match strength; relevance to this skill's concerns
     (concurrency / durability / ordering / recovery — a flush path outranks a config parser);
     fit with `[context]` and `[goal]`; and roadmap priority (an existing ladder's next level
     or a backlog item beats starting cold).
   - **Pick and announce.** One clear winner → proceed. Several plausible → take the top one,
     state the interpretation in one line ("reading `<keywords>` as `<component>` because …"),
     list the runner-ups, and append them to `$WORKSPACE/ROADMAP.md` as backlog so the
     alternatives aren't lost — then proceed without blocking on a question. Record the
     resolution (given keywords → chosen component, and why) in the level's `00_input.md`.
   - **Ask only if resolution fails** (nothing matches, or a genuine no-tiebreaker fork per
     the preamble) or `--ask` was passed — this is the up-front check; once resolved, the
     loop runs to completion.

   Grep the source roots from `PROFILE.md` for the resolved
   component; note its owning subsystem. Find or create the owning **ladder** (a sequence of
   levels L0→Ln, each adding one concern):
   - existing ladder → the work is its next level `L{n+1}_{slug}`, or a `*_v2` revision if
     it reopens a closed claim; read the previous level's `05_output.md` first;
   - no ladder → start one: create `$WORKSPACE/<component>_models/<ladder>/` with a `PLAN.md`
     (charter + the verified concurrency model + the level plan), a `ROADMAP.md` status
     table, a `TODO.md` action digest (the ladder's single-place "what to do next" —
     `workspace.md`), and a scoped note pinning the source root + exclusions you verified.
   State the chosen ladder + level and why before writing files.

3. **Plan the level.** Pick the **mode** (`methodology.md` §modes): *faithful transcription*
   (zero fault injection) for control-flow / state-machine logic, or *faithful fault
   injection* for quorum / replication / durability / recovery / GC code — injecting **only**
   the faults that code is designed to tolerate, each with the design statement that says so.
   Pick the **property** that expresses the goal as a developer expectation (read-your-write,
   success-implies-durable, monotonicity, exactly-once, termination, no-lost-update…).

4. **Read the production source first.** Every transition you model must cite a verified
   `file:line` you actually read — nothing guessed. Enumerate the API caller's obligations
   too; they may live **outside the named component** — in another module of *this* repo —
   so search the rest of `<repo-root>` (and any additional source roots `PROFILE.md` lists),
   not just the component folder (`lessons.md` R1.3). Build the `var ↔ code` map as you read.

5. **Author the level artifacts** in order, using the standard level layout (`methodology.md`
   §schema; scaffold with `scripts/new_level.sh <level-dir> <Module>`). The spec and its
   configs go in the level's `02_models/` folder as **real files (no symlinks)**; the `.tla`
   basename must equal the module name; PlusCal-free action style; the `var ↔ code` map at
   the top; properties express the goal. Size the model by **effort**: at `low`, the primary
   `.cfg` only at the smallest sizes that still exercise the concern; at `high`, add scaling
   cfgs (larger N / longer ranges) and extra scenario cfgs in `02_models/`, and consider more
   fault variants. See `authoring.md`.

6. **Run TLC until the spec is runnable.** Invoke via
   `scripts/run_tlc.sh 02_models/L{n}_{Module}.tla [cfg]` (it runs the real module-named
   `.tla`, never a symlink). Iterate on parse/semantic errors until it runs clean — a model
   that doesn't run is not evidence. Run every cfg you commit; for a violating run, re-run
   with `--det` (`-workers 1`) for deterministic counts; run once with `--coverage` — at
   **every** effort level, the extra run is cheap — and confirm **every action fired** (a
   zero-coverage action is dead spec — a guard that never holds, often a real modeling bug).
   On a **violating** cfg, TLC halts at the violation, so coverage spans only the explored
   prefix — a zero-coverage action there may be halt-truncation, not dead spec; confirm it
   against a non-violating cfg before treating it as dead. Record the exact commands, per-cfg
   state counts / depth / time / result, the coverage summary, and the wall-clock runtime in
   `03_run_log.md`. Clean scratch after (`scripts/run_tlc.sh` does this).

7. **Triage any violation — `lessons.md` is binding.** Before classifying, run the checklist:
   establish what each value **denotes** per its producer (R1.1); a staleness claim needs a
   **data witness in the gap**, not a version-label difference (R1.2); check whether the
   model omitted a guard the code has (an under-faithful model produces artifacts, not bugs —
   the common shape); confirm the model's concurrency is the *runtime's* concurrency (R5).
   This is an initial **screen**: rule out obvious model artifacts (→ **PASS**) and record
   anything that survives as a **candidate**. `check` does **not** self-declare `confirmed` —
   a fresh adversarial pass does that. Hand each candidate to `/vibe-tla review`.

8. **Write the human-readable output.** If violated, write `04_counterexamples.md` from the
   **actual TLC trace** (full trace table, "What it shows", "Root cause (verified, not
   assumed)" with code snippets + `file:line`, and a "Triage" ending in one precise question
   for the owner). Always write `05_output.md` (what this level proved + the **fidelity &
   coverage block** per `coverage.md` + what it exports to the next level) and, when there is
   a finding, a **candidate bug report in the level's `06_notes.md`** (root cause + a
   suggested fix) — concrete, code-anchored, minimal — for `review` to vet and `fix` to
   close.

9. **Update long-term memory.** Add/refresh the entry in `$WORKSPACE/MEMORY.md` (ladder,
   level, mode, verdict, finding, the file:line anchors the model depends on — `sync` needs
   these); update the ladder `ROADMAP.md`, the ladder **`TODO.md`** (move this level into
   Open/Closed and drop it from Planned — the single-place digest so a user needn't open each
   level folder), and `$WORKSPACE/ROADMAP.md`; append any new refutation rule to
   `$WORKSPACE/LESSONS.md`. **Baseline the drift tripwire**: run `scripts/anchors.sh update`
   so the level's `02_models/anchors.lock` records the cited lines — `sync` and CI check
   against it (`ci-integration.md`). If the loop is interrupted, leave a staged-state note in
   `MEMORY.md` so the next `check` resumes.

10. **Report** honestly: ladder/level chosen, mode used, TLC verdicts with real numbers,
    finding classification, the bug report + fix (if any), and what memory was updated.

---

## sync — `/vibe-tla sync <keywords>`

Goal: cheaply answer "has the code drifted out from under an existing model?" without
re-doing everything. In **remote** mode (`REPO_MODE=remote` in `config.env`), first run
`scripts/get_repo.sh refresh` so you re-anchor against current upstream code; in
embedded/local mode the working tree is already current.

1. **Find the model(s).** Load `$WORKSPACE/MEMORY.md`; locate the ladder/level(s) matching
   `<keywords>` and the `file:line` anchors each level's `var ↔ code` map and `00_input.md`
   recorded.

2. **Re-anchor against current code.** Cheap first pass: `scripts/anchors.sh check` flags
   byte-level changes at every locked cited line (it errs toward flagging — line shifts read
   as drift; and it warns about anchors it cannot resolve, which still need the manual pass).
   Then, for each recorded anchor — prioritizing what the tripwire flagged — read the current
   source at that location and compare against what the model captured: did the cited code
   move, change a guard/branch, add a state, change an ordering, or alter the
   concurrency/ownership topology? Use the repo's history if available (e.g. `git log`/
   `git blame` on the cited files since the level closed). For a level retired via `fix`, the
   live model is the latest `*_v2` bump — the original spec *intentionally* still models the
   pre-fix code (historical evidence); re-anchor against the `*_v2`, don't "repair" v1.

3. **Decide and act.**
   - **Material drift** (an anchor the model depends on changed in a way that could change
     the property) → say so concretely (which anchor, old vs new), then **run the `check`
     loop** to revise the model as a `*_v2` bump, and update memory.
   - **No material drift** → report "model still faithful — no re-run needed", listing the
     anchors you checked and their current state as the evidence. Do not re-run TLC for its
     own sake.

4. **Record** the sync outcome (date, anchors checked, verdict) in `$WORKSPACE/MEMORY.md`,
   and update the ladder **`TODO.md`** — add a drifted level to the "Watch — may have
   drifted" section (or clear it once re-synced/revised) — so the next sync starts from a
   known baseline. Re-baseline the tripwire (`scripts/anchors.sh update`) after a `*_v2`
   revision, or after confirming no-drift on a level that had no `anchors.lock` yet.

---

## resume — `/vibe-tla resume [keywords]`

Goal: finish a `check` run that was interrupted before the level closed — the
"run-until-complete" guarantee made restartable across sessions.

1. **Find the staged work.** Read `$WORKSPACE/MEMORY.md` and locate the `## STAGED` entries.
   If `[keywords]` are given, pick the matching one; else if exactly one staged entry exists,
   take it; else list them and ask which to resume. **If there are no `## STAGED` entries at
   all, stop** — nothing was interrupted. Do **not** invent or run new levels to "continue
   the ladder"; say that nothing is staged and point the user to `/vibe-tla advance` (which
   runs the next *planned* level(s)). `resume` finishes *interrupted* work; `advance`
   continues a ladder that closed cleanly — never conflate the two.

2. **Reload context.** Read that entry's "Done so far" and "Next step", the partial artifacts
   already on disk under the level directory (the `02_models/` spec, any `03_run_log.md`), the
   standards (`methodology.md`, `lessons.md`), and `$WORKSPACE/PROFILE.md`.

3. **Continue the Check loop from the recorded step** — not from the beginning. Pick up at the
   next unfinished step (finish the spec, get TLC clean, triage, write output, update memory)
   and carry it to completion under the run's effort level.

4. **Close out.** When the level closes, **remove the `## STAGED` note** and write the normal
   level entry (this also updates the ladder `TODO.md` via the Check loop's memory step).
   Report what was resumed and the outcome. If it stalls again, re-stage with an updated "Next
   step" so a later `resume` continues.

---

## advance — `/vibe-tla advance [ladder] [--to Ln | --count N]`

Goal: continue a ladder that closed cleanly by running its **next planned level(s)**. This is
the "continue the ladder" intent — kept distinct from `resume` (which only finishes an
*interrupted* run) and from a fresh `check` (which models a component you name). Use it when
L0 (or L{k}) is closed and the `PLAN.md` has more rungs.

1. **Pick the ladder and the next level(s).** From `[ladder]` keywords (or the one ladder
   obviously in progress), read its `PLAN.md` (the level plan) and `ROADMAP.md` (which levels
   are closed). The next target is the lowest planned level not yet built.

2. **Announce before running.** State up front which levels you are about to run and why (e.g.
   "L0 closed; PLAN lists L1–L3; running L1, then L2, then L3"). Never silently reinterpret
   intent — if there is no ladder with planned-but-unbuilt levels, say so and ask what to
   model rather than inventing levels.

3. **Run each next level as a full `check` level**, in order, lifting the previous level's
   `05_output.md` exports — the same loop as Check (map → read source → author → run TLC until
   clean → triage → write output → update memory, which moves each rung from Planned to
   Open/Closed in the ladder `TODO.md`). Stop at the plan's end, after `--count N` levels, or
   at `--to Ln`, honoring the resolved **effort**.

4. **Report** each level's verdict. A finding at one rung is recorded and the ladder
   continues, unless the next rung's premise depends on the unresolved result — then pause
   and report rather than build on a shaky contract.

---

## status — `/vibe-tla status [keywords]`

Goal: show the verification ledger at a glance. Read-only — no TLC run.

1. Run `scripts/status.sh "$WORKSPACE" [keywords]` to render the raw ledger from `MEMORY.md`
   (closed levels with their verdicts/findings, `## STAGED` in-progress work, and counts) and
   the `ROADMAP.md` backlog.

2. Present it readably and add the interpretation raw counts can't: the **open candidates**
   (each pending one owner fact — name what it needs), anything **STAGED** (suggest `resume`),
   models **not synced recently** or whose code may have drifted (suggest `sync`), and the
   **next** backlog item worth a `check`. For per-component detail, point the user to each
   ladder's **`TODO.md`** (the single-place action digest).

3. Do not modify anything; `status` only reports.

---

## coverage — `/vibe-tla coverage [keywords]`

Goal: a readable **fidelity + coverage** report for one or more modeled levels — how much of
the code the model covers, and whether the model itself is fully exercised. See `coverage.md`
for the definitions and the report format.

1. **Select levels.** From `MEMORY.md`, take the level(s) matching `[keywords]` (or the whole
   workspace if none).

2. **Model coverage (automatic).** For each, run
   `scripts/coverage.sh 02_models/L{n}_{Module}.tla [cfg]` — it runs TLC with `--coverage` and
   reports each action's hit count, flagging **zero-coverage actions** (dead spec). At `high`
   effort, also run the scaling cfgs.

3. **Fidelity & code coverage (from the model).** From each level's `var ↔ code` map and
   `01_reasoning.md`, summarize: transitions modeled vs marked `UNCLEAR`/`TODO`; which
   functions/branches of the component are modeled vs the stated denominator; and the
   abstractions taken with their soundness notes.

4. **Report** the combined picture per level plus a workspace roll-up. For an **open** level,
   write the fidelity & coverage block into its `05_output.md`; for a **closed** (frozen)
   level, write the refreshed block to `06_notes.md` and note the delta — never edit a frozen
   `05` (`methodology.md` §schema). Flag any zero-coverage action as a model bug to fix before
   trusting the verdict.

---

## effort — `/vibe-tla effort <high|low|medium>`

Effort controls how exhaustively `check` and `coverage` explore. It is a single workspace
setting plus a per-run override.

- `/vibe-tla effort high|low|medium` records `VIBE_TLA_EFFORT` in `$WORKSPACE/config.env` as
  the default (set the key if present, append it if not). `medium` — or unsetting the key —
  restores the built-in default.
- Any run may override inline: `/vibe-tla check <keywords> --effort high`.
- If neither is set, effort is `medium`.

What each level changes — apply with judgment; never drop the concern under test just to
finish faster, and never let truncation read as "covered everything":

| | **low** — quick pass, simpler components | **medium** — the default | **high** — explore more, load-bearing ones |
|---|---|---|---|
| Model sizes | smallest that still exercises the concern | modest sizes | larger N / longer index & value ranges |
| Configs | primary cfg only | primary cfg | primary + scaling rounds + extra scenario cfgs in `02_models/` |
| Faults (injection mode) | one or two core tolerated faults | the core tolerated faults | the full tolerated-fault set + combinations |
| TLC | primary run + `--det` on any violation + `--coverage` once | the same | the same, plus a longer time budget and deeper/scaling runs |
| Properties | the core developer expectation | the core expectation | core + secondary invariants and liveness |

---

## review — `/vibe-tla review [finding]`

The **true-positive gate** of the development cycle (`check → review → fix`): independently
try to *refute* a candidate — the mirror of `check`, which tries to *find* one. A candidate
that survives refutation is a true positive; one that does not is a false positive / model
artifact / hallucination. A *fresh* adversarial pass is what catches these — do not trust the
agent that found the bug to also clear it.

Target `[finding]` (id / ladder-level / keywords), or no arg = every open `candidate` in
`MEMORY.md`. For each:

1. **Reproduce, don't recall.** Re-run TLC on the *committed* spec and confirm the
   counterexample and its state counts are real (a hallucinated trace fails here).
2. **Run the checklist adversarially** (`lessons.md` R1–R5): denotation, semantic witness,
   omitted guard / looser-than-code, caller obligations across the repo, concurrency topology,
   designed-regime / domain bound. When subagents are available, **spawn an independent
   reviewer agent instructed to break the finding**; else review it yourself, in good faith
   trying to refute.
3. **Rule.** Survives → **confirmed** (true positive). Falls to any check → **retired:
   refuted** (say which rule refuted it). Hinges on one owner-only fact → keep **candidate**
   and name the fact; a later `/vibe-tla review <finding> "<owner answer>"` finalizes it.
4. **Record (don't touch the frozen `05`):** append a dated `Reviewed: <verdict> — <why>` line
   to `04_counterexamples.md`'s Triage; update the `- Finding:` line + heading verdict in
   `MEMORY.md`, the ladder `ROADMAP.md`, the ladder **`TODO.md`** (a confirmed finding
   stays Open with "do `fix`"; a still-candidate one stays Open with the owner-answer command
   as its next action; a refuted one moves to Closed), **and `$WORKSPACE/ROADMAP.md`** (the
   workspace backlog mirrors finding state — leaving it stale misleads the next `check`);
   append a one-line verdict update to the `06_notes.md` bug report so its headline can't be
   read as still-candidate; on a refutation append the new rule to `$WORKSPACE/LESSONS.md`
   (the case law grows). Report each verdict.

---

## fix — `/vibe-tla fix <finding>`

Close a **confirmed** finding: apply the change **and** prove it worked — the validation
re-check is part of `fix`, not a separate step (a fix is not done until it is mechanically
verified).

1. **Resolve the finding, then derive the change.** Resolve `<finding>` (an id like
   FINDING-001, a ladder/level, or keywords) via the `- Finding:` lines in
   `$WORKSPACE/MEMORY.md` to exactly one **confirmed** open finding — if none or several
   match, list what exists and stop. Then, from its `04_counterexamples.md` (root cause +
   suggested fix, with `file:line`) and `05_output.md`, write the minimal, code-faithful
   change. Usually a code change in the repo; if the defect is in the *model* (e.g. a dead
   action, an under-faithful spec), fix the spec instead.
2. **Apply it to the working tree** at the cited `file:line`, matching surrounding style. In
   embedded/local mode this edits the repo; in remote mode it edits the clone under
   `${VIBE_TLA_HOME:-$HOME/.vibe-tla}/repos/`. Show the diff (`git diff`); **do not
   commit/push** unless the user asks (those are outward-facing).
3. **Validation re-check.** Model the *fixed* code: add a bumped spec
   `02_models/L{n}_{Module}_v2.tla` (or a new level) transcribing the guard/ordering the fix
   added, citing the new `file:line` — never edit the frozen original spec / `00` / `05`.
   Re-run TLC (`scripts/run_tlc.sh`) and **append the v2 runs (commands + numbers) to the
   level's `03_run_log.md`** — the run ledger is append-only, not frozen; every run the level
   ever made belongs there. Property now **holds** (counterexample gone) → the finding is
   **retired: fixed (validated)**. Still fails → the fix is incomplete; report the surviving
   trace and loop back.
4. **Record.** Set `- Finding: retired(fixed, validated by L{n}_{Module}_v2)` and `- Fix:` in
   `MEMORY.md`, the ladder `ROADMAP.md`, the ladder **`TODO.md`** (move the finding from
   Open to Closed), **and `$WORKSPACE/ROADMAP.md`**; write a short retirement note (what
   changed, the before/after TLC numbers) to `06_notes.md`. Add a `TODO.md` Watch note that
   the frozen v1 spec now *intentionally* models the pre-fix code (historical evidence — the
   `*_v2` is the live model `sync` re-anchors against), and re-baseline the tripwire
   (`scripts/anchors.sh update`) so the lock tracks the v2 anchors. The cycle then **loops
   back to `check`** for the next round (or `advance` for the next planned rung).
