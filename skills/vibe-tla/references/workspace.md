# workspace.md — the per-repo workspace and the long-term memory

Everything vibe-tla produces for a repo lives under a single workspace folder,
`<repo-root>/tla` by default (the name is the `WORKSPACE_DIR` setting in `config.env` —
change it once and it's honored everywhere). This folder **is** the skill's long-term
memory: it is what lets a `check` run days later resume where the last one stopped, and what
`sync` reads to decide whether a model has gone stale. Commit it to the repo so the memory
travels with the code (or `.gitignore` it if the user prefers — ask at `init`; in a
non-interactive run don't ask: leave the workspace untracked and note the open choice in the
init report). The skill
stays **within `<repo-root>`** — it never reads or writes a sibling repo.

`<repo-root>` depends on the **install shape** (SKILL.md fixes the exact rule):

- **Embedded** — the skill is installed at `<repo>/.claude/skills/vibe-tla/`, so
  `<repo-root>` is the project that owns that `.claude/` (workspace at `<repo>/tla/`), never
  the working directory or a parent that just holds sibling repos. The workspace lives
  inside the repo you already have.
- **Standalone** — the skill lives in a user-global / agent skill library with no owning
  project. `init` asks for a repo **URL** (or local path) and `scripts/get_repo.sh` clones
  it into `${VIBE_TLA_HOME:-$HOME/.vibe-tla}/repos/<name>` (`REPO_MODE=remote`); that clone
  is `<repo-root>`, and the workspace is `<clone>/tla`, so the memory persists next to the
  code across sessions. The active clone is recorded in the pointer
  `${VIBE_TLA_HOME:-$HOME/.vibe-tla}/active.env` so later commands find it, and `sync`/
  `check` `git pull` the clone (`get_repo.sh refresh`) before reading code. A local path
  given to `init` is used in place (`REPO_MODE=local`).

## Table of Contents

- Layout
- The memory files — what each holds and who writes it
- How the commands use the workspace

## Layout

```
<repo-root>/tla/                      # = $WORKSPACE  (WORKSPACE_DIR, default "tla")
├── PROFILE.md                        # the repo binding (the durable "what is this repo")
├── MEMORY.md                         # running index of everything modeled (the working memory)
├── LESSONS.md                        # case law, seeded from the skill, grown per-repo
├── ROADMAP.md                        # ladder map + backlog (what to model next)
├── config.env                        # machine settings: jar path, repo root, TLC defaults
├── tools/
│   └── tla2tools.jar                 # the TLC jar (if downloaded here; else config.env points out)
└── <component>_models/               # ladders grouped by the component/subsystem they model
    └── <ladder>/
        ├── PLAN.md                   # charter: verified concurrency model + level plan (frozen at L0)
        ├── ROADMAP.md                # this ladder's status table + findings (the record)
        ├── TODO.md                   # single-place action digest: what's open + the next command
        └── L{n}_{slug}/              # one directory per level — the standard level layout
            ├── 00_input.md
            ├── 01_reasoning.md
            ├── 02_models/            # the spec + ALL its configs — real files, no symlinks
            │   ├── L{n}_{Module}.tla #   basename == MODULE name
            │   ├── L{n}_{Module}.cfg #   primary config
            │   └── *.cfg             #   scaling / scenario configs
            ├── 03_run_log.md
            ├── 04_counterexamples.md
            ├── 05_output.md
            └── 06_notes.md
```

Group ladders by the component they model (`<component>_models/`) so one repo can host
many independent ladders without collision. Never put a level directory at the repo root
or at `$WORKSPACE` root.

## The memory files — what each holds and who writes it

### `PROFILE.md` — the durable repo binding (`init` writes; `check`/`sync` read)
The answer to "what is this repo and how do I model it faithfully", captured once and
refined as understanding grows. Sections:

- **Mission** — one line: what we're verifying about this repo and why.
- **Source roots & exclusions** — the directories to read for each subsystem, and any
  trees to ignore (legacy/vendored). `check` greps these to find a component.
- **Build & runtime model** — languages, build system, and crucially the
  **concurrency/dispatch topology** (threads / async tasks / run-to-completion reactor /
  sharded workers; the dispatch and shard keys). This is what later triage leans on
  (`lessons.md` R2/R5).
- **Subsystem map** — the components worth modeling and where their interesting
  concurrency / durability / quorum / recovery / ordering code lives.
- **Fault model** — for fault-tolerant code, what faults the design claims to tolerate
  (read from the code/comments/design docs of *this* repo — never imported from another).
- **Model-size defaults** — sizes discovered from *this* code (e.g. its own N/W/R, its
  own level/capacity constants), not borrowed constants.
- **Toolchain** — the `tla2tools.jar` path and any TLC quirks for this machine.

### `MEMORY.md` — the working index (`check` appends; `sync` updates)
One entry per modeled level, plus a staged-state note for any interrupted run. Each entry
records enough for `sync` to re-anchor and for the next `check` to resume:

```
## <component> / <ladder> / L{n}_{slug}    — <verdict>  (<date>)
- Mode: transcription | fault-injection (<faults>)
- Property: <the developer expectation checked>
- Code anchors the model depends on:
    - <file:line> — <what it is> — <denotation>
    - <file:line> — ...
- TLC: <distinct states> / <depth> / <result> (cfg: <name>)
- Finding: <none | candidate(<open precondition>) | confirmed | refuted(<why>) | safe-by-design | retired(<reason>)>
- Reviewed: <date → verdict, when /vibe-tla review vetted the candidate> (optional)
- Fix: <none | applied at <file:line> via /vibe-tla fix, validated by L{n}_{Module}_v2> (optional)
- Bug report: <link to 04_counterexamples.md / 05_output.md> (if any)
- Last synced: <date or "never">
```

The `- Finding:` field tracks the development-cycle state: `candidate` (from `check`) →
`confirmed` (from `review`) → `retired(fixed, …)` (from `fix`); or `review` closes it as
`retired`/`refuted`/`safe-by-design`. The heading `<verdict>` **mirrors the `- Finding:`
classification word** — `PASS` (or `validated contract`) when Finding is `none`, else
`candidate` / `confirmed` / `refuted` / `safe-by-design` / `retired`. Keep the two in
agreement; `- Finding:` is the canonical source (it
carries the precondition/why), and `status.sh` buckets from it, falling back to the
heading. A heading verdict that disagrees with Finding is a defect to reconcile, not a
second opinion.

A `## STAGED` note exists for any `check` run interrupted before the level closed; it
carries everything `resume` needs to continue **without re-deriving the ladder/level**:

```
## STAGED — <component>/<keywords>            (in progress, <date>)
- Level dir: <$WORKSPACE-relative path to the L{n}_{slug}/ directory the partial work is in>
- Ladder/level: <ladder> / L{n}_{slug}
- Effort: <low | medium | high>   (the resolved effort the interrupted run used)
- Reached step: <the Check step number to resume at, e.g. "6 — TLC not yet clean">
- Done so far: <e.g. source read, var↔code map drafted, spec at 02_models/L1_Foo.tla>
- Next step: <e.g. fix TLC parse error in AckOk, then run primary cfg>
```

### `LESSONS.md` — the case law (`init` seeds; `check` grows)
Seeded by copying the skill's `references/lessons.md` so the transferable rules (R1–R5)
travel with the repo. Append this repo's own refutations as they happen — each as a named
rule with the mistake, the fact that corrected it, and the generalized lesson. Read it
before classifying any violation.

### `ROADMAP.md` — what to model next (`init` seeds; `check`/`sync` update)
The ladder map across the repo and the ordered backlog. `init` proposes the first few
high-value components; each `check` ticks one off and may add follow-ups.

### `<ladder>/TODO.md` — the per-component action digest (every state-changing command maintains it)
Each ladder carries a **`TODO.md`** at its root — the single place a user reads to see
*what is open and what to run next* for that component, **without opening each
`L{n}_{slug}/` folder**. It is the forward-looking companion to the ladder's `ROADMAP.md`
(the backward-looking status record). Every command that changes a level or a finding
rewrites it — `check` and `advance` (open/planned levels), `review` and `fix` (finding
state), `sync` (drift), and `resume` (when it closes the interrupted level via the Check
loop) — so it never goes stale. `MEMORY.md` and the level folders stay canonical;
`TODO.md` is a derived digest. Empty sections read `(none)`. Template:

```
# TODO — <ladder>

Actionable digest for this ladder (the subsystem it models). Auto-maintained by
check / advance / review / fix / sync / resume; per-level detail lives in the L{n}_{slug}/
folders, findings are canonical in ../../MEMORY.md. Last updated: <date>.

## Next action
- <the single most useful next command, e.g. /vibe-tla review L1_evict — 1 candidate to vet>

## Open — needs action
| Level     | Finding (one line)        | State     | Do next                   |
|-----------|---------------------------|-----------|---------------------------|
| L1_evict  | eviction can race GC      | candidate | /vibe-tla review L1_evict |
| L2_write  | lost update under crash   | confirmed | /vibe-tla fix L2_write    |

## Planned — not built yet
| Level        | Concern                | Do next          |
|--------------|------------------------|------------------|
| L3_lifecycle | open/close/drop races  | /vibe-tla advance |

## Watch — may have drifted
| Level    | Signal                  | Do next                 |
|----------|-------------------------|-------------------------|
| L0_base  | anchor task.cc:88 moved | /vibe-tla sync L0_base  |

## Closed — for reference
| Level    | Outcome                    | When       |
|----------|----------------------------|------------|
| L0_base  | PASS (validated contract)  | 2026-06-28 |
| L1_evict | retired: fixed             | 2026-06-30 |
```

## How the commands use the workspace

- **`init`** creates the skeleton, resolves the toolchain into `config.env`, and writes
  `PROFILE.md` + seeds `LESSONS.md`/`MEMORY.md`/`ROADMAP.md`.
- **`check`** reads `PROFILE.md` + `MEMORY.md` + `LESSONS.md` (and resumes any STAGED
  entry for the keywords), writes a level under `<component>_models/`, then updates
  `MEMORY.md`, the ladder `ROADMAP.md`, the repo `ROADMAP.md`, and `LESSONS.md` on any
  refutation.
- **`sync`** reads `MEMORY.md` to find the model's code anchors, re-reads those
  `file:line`s in the current source (with repo history if available), and either reports
  "still faithful" or triggers `check` for a `*_v2` revision — recording the sync outcome
  back into `MEMORY.md`.
- **`advance`** reads a ladder's `PLAN.md` + `ROADMAP.md` and runs its next planned
  level(s) as full `check` levels (distinct from `resume`, which only finishes an
  interrupted run).
- **The development-cycle loop** (`check → review → fix`): `review` vets a `candidate` in
  `MEMORY.md` → `confirmed` or `retired(refuted)`, updating `MEMORY.md` / the ladder
  `ROADMAP.md` / `LESSONS.md`; `fix` applies the code (or spec) change, re-checks it with a
  `*_v2` spec, and records `retired(fixed, …)` + `- Fix:` in `MEMORY.md` and a note in
  `06_notes.md`. The loop then returns to `check` for the next round.
