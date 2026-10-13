# Vibe-TLA — User Manual

*Find real concurrency, durability, and ordering bugs in your codebase with TLA+ — without
writing TLA+ yourself.*

> 中文版：[MANUAL.zh-CN.md](MANUAL.zh-CN.md)

Vibe-TLA is a skill for Claude Code. You point it at a component; it reads the production
source, writes a **code-faithful TLA+ spec** (every modeled transition anchored to a real
`file:line`), model-checks it with TLC, and reports each violation as a fix-ready bug
report — or certifies the property as a **validated contract** when nothing breaks. It keeps
a per-repo workspace as long-term memory, so a hunt you start today can be resumed, extended,
or re-verified weeks later.

The whole skill is one loop (a *ladder* is how one component's verification is split into
small levels L0→Ln, each adding one concern — more in §2):

```
check <component>   → candidate(s)
review [<finding>]  → confirmed  |  retired: refuted      (the true-positive gate)
fix <finding>       → retired: fixed                      (change + validation re-check)
check ...           → next round  (or `advance` for the next ladder rung)
```

Two honesty rules drive everything, and they are why the output is trustworthy:

1. **`check` never declares a bug.** It emits *candidates*. A separate adversarial pass
   (`review`) tries to *refute* each candidate against a case-law checklist; only survivors
   become *confirmed*.
2. **A finding that hinges on a fact only the code owner knows stays a candidate** — with
   that fact posed as one precise question. The owner's answer flips it to confirmed *or*
   refuted. Either way you learned something mechanically checked.

---

## 0. Where commands are typed

vibe-tla is a **Claude Code skill**: you type `/vibe-tla <command>` at the prompt of a
Claude Code session (CLI or desktop app). To install it, put the skill folder where Claude
Code finds skills — either

```bash
# embedded: travels with one repo
cp -r vibe-tla  <your-repo>/.claude/skills/vibe-tla
# or standalone: available in every session
cp -r vibe-tla  ~/.claude/skills/vibe-tla
```

then open a session (`cd <your-repo> && claude` for the embedded shape) and type the
commands below in the chat.

## 1. Setup — once per repo

**Prerequisites:** Claude Code (above) and a Java runtime (17+). That's it — `init` finds
or downloads the TLC model checker (`tla2tools.jar`) itself and verifies it with a smoke
spec.

```
You:    /vibe-tla init

Claude: Resolved <repo-root> = /Users/you/Workspace/pagestore  (embedded install)
        $WORKSPACE = <repo-root>/tla
        ✓ TLC toolchain: tla2tools.jar (VSCode TLA+ extension) — smoke spec passed
        ✓ PROFILE.md — C++ / sharded bg-workers; subsystem map: delta_db, hot_page_mgr, …
        ✓ LESSONS.md seeded (case law R1–R5), MEMORY.md / ROADMAP.md created
        Worth modeling first:
          1. hot_page_mgr — multi-level LRU with cascading eviction (shared, locked)
          2. …
        Run `/vibe-tla check <component>` to model one.
```

Two install shapes:

- **Embedded** — skill at `<repo>/.claude/skills/vibe-tla/`; the workspace is `<repo>/tla/`.
  Commit `tla/` so the memory travels with the code (init asks once).
- **Standalone** — skill in your user-global skill library; give init the repo:
  `/vibe-tla init <repo-url-or-path> [--branch B]`. It clones under `~/.vibe-tla/repos/` and
  `sync`/`check` pull before reading code.

The workspace **is** the product alongside the findings — `PROFILE.md` (how to model this
repo faithfully), `MEMORY.md` (the ledger of everything modeled), `LESSONS.md` (case law that
grows with every refutation), `ROADMAP.md` (what to model next), and one folder per modeled
component.

**Quickstart, in order:**

1. `/vibe-tla init`
2. Pick a component — from the "worth modeling first" list `init` prints, or your own worry.
3. `/vibe-tla check "<component>" "<what you know about it>" "<what should always hold>"`
4. Read the verdict in the chat, and the bug report (if any) in
   `tla/<component>_models/<ladder>/L0_*/04_counterexamples.md`.
5. For each candidate: get the owner's answer to its one open question, then
   `/vibe-tla review <finding> "<answer>"`.

Expect a `check` to take a while: TLC itself usually finishes in seconds, but the
read-the-source → author-the-spec → triage loop around it is many minutes of agent work.

## 2. Your first hunt — `check`

```
/vibe-tla check <keywords> [context] [goal]
```

Give it three things:

| Arg | What it is | Example |
|---|---|---|
| `<keywords>` | component / class / folder to model — or a rough description of an area, if you don't know the code layout | `"lst_server flush backpressure"` · `"whatever manages page eviction"` |
| `[context]` | background you happen to know — a design fact, a suspicion, a team answer | `"responses flushed via a ready queue; 512 MiB global output budget"` |
| `[goal]` | the developer expectation to verify | `"every accepted request is eventually answered"` |

You don't need the exact component name. Given something vague, `check` surveys the repo,
picks the best-matching component, announces its interpretation in one line ("reading
`<keywords>` as X because …"), files the runner-ups in the roadmap backlog, and proceeds.
It stops to ask only when nothing matches — or pass `--ask` to pick the target yourself.

Context is a **hint, not evidence** — the skill verifies every claim in it against the
source before modeling it. `check` then runs the whole loop unattended: read the code →
author the spec (with a `var ↔ code` map so a reviewer can read it with the source open
beside it) → run TLC (iterating only until the *spec* runs without tooling errors —
property violations are kept and triaged, never massaged away) → screen any violation
against the case law → write the report → update the ledger. If the session dies mid-run,
`/vibe-tla resume` picks up where it stopped.

Everything lands in one level folder you can audit file by file:

```
tla/<component>_models/<ladder>/L{n}_{slug}/
├── 00_input.md            # what was asked + the code facts gathered
├── 01_reasoning.md        # modeling decisions, abstractions, their soundness
├── 02_models/             # the spec + every config (a .cfg instantiates the spec at
│                          #   concrete sizes — e.g. 2 cache levels vs 3 — so one spec
│                          #   is checked under several regimes)
├── 03_run_log.md          # exact TLC commands, state counts, wall-clock
├── 04_counterexamples.md  # the violation trace + root cause + triage  ← the bug report
├── 05_output.md           # what this level proved; fidelity & coverage
└── 06_notes.md
```

Big components are verified as a **ladder** of levels (L0 → Ln), each adding one concern —
so every level stays within TLC's budget and every verdict is independently auditable.
`/vibe-tla advance` runs the next planned rung; `/vibe-tla status` shows the ledger.

## 3. What a run can conclude

| Verdict | Meaning |
|---|---|
| **PASS / validated contract** | Property holds over the whole state space *of the model at the sizes checked* (the configs record exactly which bounds), under the code's own fault model. A real correctness result, not a disappointment. |
| **candidate** | TLC violation that survived initial screening; usually pinned on one precisely-stated open precondition. Run `review`. |
| **confirmed** | Candidate survived an independent adversarial refutation pass (and any owner fact is discharged). A true positive. |
| **retired: refuted / safe-by-design** | The adversarial pass (or an owner answer) killed it. Recorded, and the *reason* becomes new case law in `LESSONS.md`. |
| **retired: fixed** | Fix applied **and** mechanically re-verified — a `*_v2` spec of the fixed code re-runs clean. |

**How to read a TLC result line** like `AllAnswered violated — 1,391 gen / 457 distinct /
depth 17 — 0.8 s`: *generated* = states TLC produced, *distinct* = unique states actually
explored (the size of the search), *depth* = the longest step sequence. A **safety**
invariant says "nothing bad ever happens" (checked in every state); a **liveness** property
(`<>` reads "eventually") says "something good eventually happens" — its counterexample is
a run that loops forever without the good thing (a *lasso*, i.e. a permanent stall).

---

## Three real case studies

*These cases are real: they come from the bytendb verification program
(`tla_research/`, `pagestore_models/`) whose artifacts and hard-won lessons vibe-tla was
distilled from. The specs, TLC numbers, counterexample traces, and team answers below are
quoted verbatim from the program's committed artifacts; the `/vibe-tla` transcripts show how
you drive the same hunt with the skill today.*

### Case 1 — A production stall, end to end: find → confirm → fix → retire (BUG-006)

**Component:** `pgxn/neon/lst_server.c` — a multi-threaded Unix-socket server that flushes
responses via a ready queue, under a per-connection output budget and a 512 MiB *global*
output budget.

#### Find

```
You: /vibe-tla check "lst_server response flush backpressure" \
       "completions flushed via a ready queue; per-conn output budget plus a \
        512 MiB global output budget (lst_server.c:48)" \
       "every accepted request is eventually answered — no permanent stall"
```

The skill transcribes the code faithfully (zero fault injection — if this breaks, it breaks
under ordinary scheduling) and checks the liveness property
`AllAnswered == <>(Len(sent) = NFRAMES)`. Real TLC results from the run log:

```
hunt_global:      Error: Temporal property AllAnswered was violated.   1,391 gen / 457 distinct / depth 17   0.8 s
perconn_control:  Model checking completed. No error has been found.     249 gen /  86 distinct / depth 14   0.4 s
```

The per-connection-budget twin is safe (the control config passes); the **global**-budget
path stalls. The counterexample's decisive step, verbatim from `04_counterexamples.md`:

> | 9 | `DrainCompletions` — … `queue_output_frame` sees `over_global_limit` (:3986-3988) →
> refuses, `pause_read(GLOBAL)` (:4001), returns BACKPRESSURE → rc==1 → **re-store completion
> (:4157), `pause_read(OUTPUT)` (:4158), break (:4159)**. Nothing sent; **no ready-queue push;
> `outQ` still 0 ⇒ EPOLLOUT not armed** |
>
> In the terminal state: `comp={0,1}` (two responses fully computed and stored), `ready=F`,
> `outQ=0`, `deferred=T`, `pause={PIPE}`, `sent=<<>>` — three requests accepted, zero
> answered, **forever**.

The root cause, straight from the source the spec cites (`lst_server.c:4154-4166`):

```c
rc = lst_conn_send_one_response(conn, target_seq, resp);
if (rc == 1)
{
    (void) lst_conn_store_completion(conn, target_seq, resp);
    lst_conn_pause_read(conn, LST_PAUSE_OUTPUT_BUDGET);
    break;                       /* <-- no push_once, no signal, no epoll change */
}
```

A completion refused by the global budget is re-stored with **no wake-up edge left** — and
the wedge outlives the overload that caused it. `check` classifies this a **candidate** with
one open precondition: *can `lst_global_out_bytes` exceed 512 MiB in production?*

#### Confirm

```
You: /vibe-tla review L1_backpressure "owner: yes — >512 MiB globally queued is
      production-reachable; wake-up-edge audit checked, there is no other resume path"

Claude: Reproduced the trace on the committed spec (457 distinct states — real).
        Checklist R1–R5 adversarially re-run: behavior witness present (computed-but-never-
        delivered responses), every wake-up edge enumerated, precondition now discharged.
        CONFIRMED — true positive. Suggested fix shape (~5 lines): push the ready queue +
        signal the eventfd in the rc==1 path.  → /vibe-tla fix L1_backpressure
```

#### Fix and retire (here: a team fix, retired via `sync`)

Here the team shipped the fix themselves (MR !357: a recovery edge
`lst_conn_schedule_ready_completion_if_unblocked`, a 512/384 MiB hysteresis, a close-time
budget release — matching the proposed shape). When the fix lands, `sync` notices the model
is stale and the re-check retires the bug *mechanically*, not by vibes:

```
You: /vibe-tla sync lst_server

Claude: Material drift at 3 anchors: new lst_server.c:2664-2691
        (schedule_ready_completion_if_unblocked, invoked at :2951), hysteresis :48-49,
        close-time release :1879 → re-modeling the fixed code…

        Post-fix model (N=2 conns, the REAL shared global counter):
          PASS — AllAnswered HOLDS.  3,383 generated / 702 distinct / depth 17.  0.8 s.
          All safety invariants hold, incl. GlobalAccountingExact (globalOut = Σ outQ[c]).
        Removed-guard demos prove both fix halves load-bearing:
          RECOVERY_EDGE=FALSE  → the wedge re-derives itself (AllAnswered violated, 736 distinct)
          RELEASE_ON_CLOSE=FALSE → counter leaks; a survivor still stalls (1,132 distinct)
        Model revised as a *_v2 bump; ledger updated — BUG-006 fixed, mechanically validated.
```

From the retirement write-up: *"The single call at `lst_server.c:2951`
(`schedule_ready_completion_if_unblocked`) is the entire difference."* That's the full
arc the skill is built around: **model-found liveness bug → fix → mechanical retirement** —
and the removed-guard demos stay in the workspace as regression tripwires.

Had the team not shipped it, `/vibe-tla fix L1_backpressure` closes the loop from your
side: it applies the proposed patch to your working tree, shows the diff (it never commits
or pushes without asking), and runs the same `*_v2` re-check itself.

### Case 2 — Masked today, live in the design (BUG-010)

**Component:** PageStore's `MultiLevelLRU` hot-page cache
(`hot_page_mgr/multi_level_lru.cc`). This case is why `review` reads *design docs*, not
just code.

```
You: /vibe-tla check "hot_page_mgr multi-level LRU cascading eviction" \
       "server-side hot page cache; deployed with 2 levels today" \
       "a page is never resident in two LRU levels at once; counters stay coherent"
```

Real results: on the **deployed** configuration the property holds; one level wider, it
doesn't.

```
production_2tier.cfg   (2 levels)  No error — all invariants hold      5,725 gen /  63 distinct / depth 8
three_tier_demo.cfg    (3 levels)  UniqueLocation VIOLATED at depth 4  3,594 gen /  35 distinct
```

The defect is a *stale-read-then-act* (`04_counterexamples.md`):

```c
auto old_level = get_page_heat_level_unlocked(seg_id, page_no);    // :231  captured ONCE
bool ready = cascading_demote(target_level);                       // :244  may move (seg,page)!
levels_[old_level].remove_page(seg_id, page_no);                   // :254  stale level → no-op
levels_[target_level].insert_page(seg_id, page_no, current_clock); // :258  second copy
```

The cascade can demote *the very page being marked*; the stale-level removal no-ops and the
insert leaves the page in **two levels** — corrupting `is_page_hot`, `get_page_heat_level`,
`unmark_page_hot`, and double-counting `size()`.

**The trap — and the lesson the skill now enforces.** An early triage *refuted* this on an
"in-tree, closed" bound: the production constructor only builds ≤ 2 levels
(`page_engine.cc:1851-1858`), and with 2 levels the trace is unreachable. Then the owner
shared the design doc:

```
You: /vibe-tla review L0_cache_integrity "owner design doc: DBEngine defines FIVE cached
      heat tiers (page_cache_level_t cache_level_1..5); HotPageMgr is designed to run one
      LRU level per tier — the level count is moving 2 → 5"

Claude: The "≤ 2 levels" bound is OPEN, not closed — the design is moving it (case law R4.4).
        Re-checking under the DESIGNED regime: five_level_stable.cfg — 5 levels, every page
        pinned to a FIXED heat (no heat change at all)…
        UniqueLocation VIOLATED at depth 4  (140 distinct; ≈28 s, -workers auto).
        Ordinary demote-then-remark traffic duplicates a page. Candidate STANDS —
        one open precondition: is the multi-level (≥3) HotPageMgr the target deployment?
```

The five-level counterexample is the ordinary life of a cache — no corner case needed:

```
Access(3)  heat 2  →   L0:{}    L1:{}    L2:{3}        3 at its heat
Access(8)  heat 2  →   L0:{}    L1:{3}   L2:{8}        3 demoted below its heat
Access(3)  heat 2  →   L0:{3}◀  L1:{8}   L2:{3}◀   ← 3 duplicated (L0 and L2)
```

The team confirmed the multi-level design is the target ⇒ **CONFIRMED** (2026-06-30) — a
*shift-left* catch: **masked in today's 2-level binary, live under the designed 5-level
cache**, found before the rollout ever shipped. The proposed fix is one line (re-read
`old_level` after `cascading_demote`); as of this writing it is pending, and the planned
retirement is mechanical — re-run `five_level_stable.cfg` on the patched flow and watch
`UniqueLocation` hold. The near-miss became permanent case law (`LESSONS.md`): *R4.4 — "closed" means the
design isn't moving the bound either; R4.5 — model the designed regime, not only the
deployed one.* Every future `review` on every repo runs that checklist.

### Case 3 — When the refutation *is* the win (BUG-007/008/009)

Not every violation is a bug — and vibe-tla is built so that a refuted candidate still
pays: it upgrades a PASS into a **validated contract** and leaves tripwires behind.

**Component:** the PG-on-dbstore page-identity encoder `GetSpaceNo`
(`pgxn/neon/ondbstore/ondbstore_key.h:51`) — packs `(db, rel, fork)` into 64 bits,
**dropping `spcNode` and truncating `dbNode` to 24 bits**.

```
You: /vibe-tla check "GetSpaceNo ondbstore_key segment key encoding" \
       "" "distinct PG page identities (spc,db,rel,fork) never collide in the encoded key"
```

TLC as an exhaustive bit-level checker — every ordered key pair is an initial state:

```
canonical.cfg          KeyInjective + 4 more PASS over 20,736 pairs        0.7 s
tablespace_alias.cfg   KeyInjective VIOLATED  (spcNode dropped)            0.3 s
dbnode_alias.cfg       KeyInjective VIOLATED  (dbNode & 0xFFFFFF aliases)  0.3 s
```

The model is **not** looser than the code — the encoder genuinely drops and truncates. So
per case law R1.4, these are two **candidates** (BUG-007/008, "high *if reachable*"), each
pinned to one precise owner question: *are user tablespaces forbidden? is `dbNode < 2²⁴`
guaranteed?* The witness for BUG-007 is one line:

```
k1 = [spc |-> 0, db |-> 0, rel |-> 0, fork |-> 0]
k2 = [spc |-> 1, db |-> 0, rel |-> 0, fork |-> 0]     Enc(k1) = Enc(k2), yet k1 ≠ k2
```

The team answered both questions in a single sentence:

```
You: /vibe-tla review segment_mapping "团队: 这个是设计背景，就是不需要 spcNode，
      且 dbNode 只要 24bit"   (intended design — spcNode need not be encoded;
                               dbNode only needs 24 bits)

Claude: Both excluded inputs are unreachable BY DESIGN →
        BUG-007, BUG-008: retired — REFUTED (safe by design).
        The canonical PASS is hereby promoted: the encoding is now a VALIDATED CONTRACT
        over the team-confirmed production domain — its two domain bounds are confirmed
        facts, no longer open assumptions.
        The violating configs are RETAINED as bound demonstrations — tripwires showing
        exactly what breaks if the design ever admits user tablespaces or dbNode ≥ 2²⁴.
        Case law applied: R4.1–R4.3 ("the answer is the finding" cuts toward refuted too).
```

The R4 rules were distilled from this very case — they now ship in the skill's seed
`LESSONS.md`, so every future repo starts with them.

The same discipline works when the bound is a **deployment** fact rather than a design one:
BUG-009 (same day; a flow-control cap floor that could breach the memory budget iff
`min_cap > mem_hard_cap`) was refuted in one line — production VM sizes pin
`mem_hard_cap` at 1 GiB, making the breach unreachable — leaving a hardening note (assert
the bound in code) as defense in depth.

**Scoreboard logic:** 0 bugs here — and three mechanically-backed results anyway: a
validated encoding contract, two regression tripwires, and new case law. Symmetric honesty
is the feature: the owner's answer flips a candidate to confirmed *or* refuted; your prior
doesn't.

---

## 4. Day-2 operations

**`/vibe-tla status [keywords]`** — the ledger at a glance: closed levels with verdicts,
open candidates (and the one fact each is waiting on), staged work, drift warnings, next
backlog item. Each ladder also keeps a `TODO.md` — the single-place "what's open and what
command to run next" digest.

**`/vibe-tla sync <keywords>`** — "has the code drifted out from under my model?" It
re-reads every `file:line` anchor the model recorded. No material drift → *"model still
faithful — no re-run needed"*, with the anchors as evidence. Material drift → it tells you
which anchor changed, old vs new, and revises the model as a `*_v2` bump (that's how the
Case 1 retirement started). `references/ci-integration.md` shows how to wire this into CI
so a PR touching modeled code flags drift automatically.

**`/vibe-tla resume [keywords]`** vs **`/vibe-tla advance [ladder]`** — `resume` finishes a
run that was *interrupted* (it continues from the `## STAGED` note in `MEMORY.md`);
`advance` runs the next *planned* level of a ladder that closed cleanly. Never the same
thing.

**`/vibe-tla coverage [keywords]`** — two numbers a skeptical reviewer asks for: how much
of the *code* the model covers (transitions modeled vs marked `UNCLEAR`), and whether the
*model* is fully exercised (TLC action coverage — a zero-coverage action is dead spec, a
guard that never fires, often a real modeling bug).

**`/vibe-tla effort <high|low|medium>`** — how exhaustively `check` explores (model sizes,
number of configs, fault variants, TLC time budget). Set a workspace default, or override
per run: `check <keywords> --effort high`. Use `high` for load-bearing subsystems.

## 5. Command reference

| Command | What it does |
|---|---|
| `init [repo-url]` | One-time setup: workspace, TLC toolchain, architecture profile, memory files |
| `check <keywords> [context] [goal] [--ask]` | The full discover loop: read code → spec → TLC → triage → report. Keywords may be fuzzy — it resolves the target itself (`--ask` to choose yourself). Emits **candidates** |
| `review [finding]` | Adversarial true-positive gate → confirmed / retired: refuted. Add `"<owner answer>"` to discharge a precondition |
| `fix <finding>` | Apply the minimal change to your working tree (shows the diff; never commits/pushes without asking) **and** prove it: `*_v2` spec re-runs clean → retired: fixed |
| `sync <keywords>` | Re-anchor a model against current code; revise on material drift |
| `resume [keywords]` | Finish an interrupted `check` from its staged note |
| `advance [ladder] [--to Ln \| --count N]` | Run the ladder's next planned level(s) |
| `status [keywords]` | The read-only ledger + what to do next |
| `coverage [keywords]` | Fidelity + TLC action-coverage report |
| `effort <high\|low\|medium>` | Default exploration depth (per-run override: `--effort`) |

## 6. Getting good results — five habits

1. **Give `check` a real goal.** "every accepted request is eventually answered" beats
   "check for bugs" — the property is what TLC checks. State the developer expectation.
2. **Pass context, but expect it to be verified.** Design facts, suspicions, and team
   answers all help; the skill treats them as hints and re-derives them from source.
   Anything unverifiable is marked `UNCLEAR`, and owner-only facts keep findings at
   candidate.
3. **Treat a candidate's owner question as the deliverable.** It's one precise question
   with a concrete witness (Case 3's was answered in one sentence). Take it to the owner,
   then `review <finding> "<answer>"` — either outcome is a result.
4. **Share design docs when you have them.** Case 2's bug was invisible in the deployed
   config and confirmed only because the designed regime got modeled. What the code does
   today is not the whole domain.
5. **Keep the workspace.** Commit `tla/`. The specs are regression tripwires, `MEMORY.md`
   is the audit trail, `LESSONS.md` makes every refutation permanent, and `sync` keeps all
   of it honest as the code moves.

*Deep dives: `references/commands.md` (exact per-command procedure), `methodology.md` (the
ladder method, transcription vs fault-injection modes, definition of done), `lessons.md`
(the full R1–R5 case law), `authoring.md`, `coverage.md`, `tlc-setup.md`,
`ci-integration.md`.*
