# ci-integration.md — wiring `sync` into CI (experimental, opt-in)

## Table of Contents

- [Why this exists](#why)
- [Tier 1 — deterministic drift check, no LLM (recommended start)](#tier1)
- [Tier 2 — LLM in CI, full semantic sync (experimental)](#tier2)
- [What you have to do](#checklist)
- [Limitations](#limits)

This is an **experimental, opt-in** recipe. It does not change how the skill works; it
runs the `sync` idea on every pull request so a change that touches modeled code can no
longer silently drift away from its TLA+ model. Pick **one** tier — start with Tier 1.

## Why this exists {#why}

A model is only evidence while the code it cites still says what the `var ↔ code` map
recorded. When someone edits a cited `file:line` — moves a guard, reorders two steps,
changes a branch — the model can go stale unnoticed and a closed level quietly stops
being true. `sync` answers "did the code drift out from under a model?"; CI's job is to
*remind you to run `sync`* at the moment drift is introduced, while the author still has
the change in their head. Nothing here re-derives a verdict on its own — it surfaces
drift; a human (or Tier 2) does the semantic re-anchoring.

---

## Tier 1 — deterministic drift check, no LLM (recommended start) {#tier1}

Pure git/text. No API key, no model, no money — safe to turn on for everyone. It leans on
`scripts/anchors.sh`, which has two subcommands:

- `anchors.sh update <workspace>` — walks every modeled level, records each cited
  `file:line` anchor plus a content hash of those lines into a **per-level**
  `<level>/02_models/anchors.lock` (one lock file per modeled level, under the workspace).
  Run it once locally after a level closes (or after an intentional `sync`) to baseline.
- `anchors.sh check <workspace>` — re-reads those exact lines and exits **non-zero** if
  any anchored content changed since the lock was written, naming what moved.

The check is deterministic: same lock + same tree → same answer. If it reports drift the
job fails (or comments) and tells the author to run `/vibe-tla sync <component>` locally,
which does the real re-anchoring and re-baselines the lock.

### GitHub Actions — `.github/workflows/vibe-tla-sync.yml`

```yaml
name: vibe-tla sync check
on:
  pull_request:
    # optional: only run when code or models actually change
    paths:
      - "src/**"
      - "tla/**"
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }    # anchors.sh may consult git history
      # Java + TLC are only needed if you also want CI to *run* TLC; for the drift
      # check alone, anchors.sh is pure text — drop these two steps.
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: "17" }
      - run: ./vibe-tla/scripts/install_tlc.sh tla    # adjust to where scripts/ live
      - name: Check for model drift
        run: |
          ./vibe-tla/scripts/anchors.sh check tla || {
            echo "::error::A TLA+ model may have drifted. Run '/vibe-tla sync <component>' locally and commit the refreshed tla/."
            exit 1
          }
```

### A local pre-push hook — `.git/hooks/pre-push`

Catch drift before it ever reaches CI. Make the file executable (`chmod +x`):

```sh
#!/bin/sh
# Block a push if a modeled anchor changed without a matching sync.
WORKSPACE=tla
if [ -d "$WORKSPACE" ] && [ -x vibe-tla/scripts/anchors.sh ]; then
  if ! vibe-tla/scripts/anchors.sh check "$WORKSPACE"; then
    echo
    echo "vibe-tla: a cited code anchor changed — a TLA+ model may be stale."
    echo "  run:  /vibe-tla sync <component>   then commit the refreshed $WORKSPACE/"
    echo "  (to push anyway: git push --no-verify)"
    exit 1
  fi
fi
exit 0
```

Hooks are per-clone and not committed — share the script in the repo (e.g.
`scripts/hooks/pre-push`) and have contributors symlink or `core.hooksPath` to it.

### GitLab CI — `.gitlab-ci.yml`

```yaml
vibe-tla-sync:
  stage: test
  image: alpine/git
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - sh vibe-tla/scripts/anchors.sh check tla
      || { echo "Model drift: run '/vibe-tla sync <component>' locally and commit tla/."; exit 1; }
```

---

## Tier 2 — LLM in CI, full semantic sync (truly experimental, costs money) {#tier2}

Tier 1 only knows that *cited lines changed* — it can't tell a cosmetic rename from a
guard that inverts the property. Tier 2 runs the skill's `sync` for real inside the job:
it re-reads the code around each anchor, decides whether the drift is **material** (could
change the property), and if so posts a PR comment or opens an issue with the specifics.
Be honest about the cost before enabling it:

- **Needs `ANTHROPIC_API_KEY`** (a repo/org secret). The job calls a paid model.
- **Costs money per run** — a semantic sync reads source and reasons, so it is not free
  on every push. Budget accordingly.
- **Non-deterministic** — unlike Tier 1, two runs can word the outcome differently and may
  occasionally disagree at the margin. Treat its comment as advice, not a hard gate.
- **Run it sparingly.** Gate it on a label (e.g. `vibe-tla-sync`) or a nightly schedule,
  **not** every push. Let Tier 1 be the always-on gate and Tier 2 the on-demand deep check.

### Sketch — GitHub Actions (adapt to your Claude Code CLI version)

```yaml
name: vibe-tla semantic sync
on:
  pull_request:
    types: [labeled]          # runs only when the 'vibe-tla-sync' label is added
  schedule:
    - cron: "0 6 * * 1"        # or weekly, instead of per-PR
jobs:
  semantic-sync:
    if: github.event.label.name == 'vibe-tla-sync' || github.event_name == 'schedule'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write     # to post the comment
      issues: write            # if you open an issue instead
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: "17" }
      - run: npm i -g @anthropic-ai/claude-code   # adapt to your install method
      - name: Run semantic sync
        env: { ANTHROPIC_API_KEY: "${{ secrets.ANTHROPIC_API_KEY }}" }
        run: |
          # Flags vary by CLI version — check `claude --help`. Intent: run the skill's
          # sync headless on the components this PR touched.
          claude -p "/vibe-tla sync $(git diff --name-only origin/${{ github.base_ref }}... \
                     | sed 's#/[^/]*$##' | sort -u | tr '\n' ' ')" \
                 --output-format text > sync-report.txt || true
      - name: Post result as a PR comment
        if: github.event_name == 'pull_request'
        env: { GH_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }
        run: gh pr comment "${{ github.event.number }}" --body-file sync-report.txt
```

Don't treat the exact `claude` flags as guaranteed — the headless interface changes; read
your CLI's `--help` and adjust `-p`/`--output-format` (and how you scope which components
to sync) to match. The durable part is the recipe: check out, give it the API key, run
`/vibe-tla sync <touched components>` headless, surface the report.

---

## What you have to do {#checklist}

- [ ] **Commit the workspace** — `tla/` including every level's `02_models/anchors.lock`.
      Those per-level locks are the baseline CI compares against; without them committed,
      `anchors.sh check` has nothing to check.
- [ ] **Add the workflow file** for your CI (`.github/workflows/vibe-tla-sync.yml`, or the
      GitLab snippet), and optionally the local `pre-push` hook.
- [ ] **Decide Tier 1 vs Tier 2.** Tier 1 is the safe default; add Tier 2 only if you want
      semantic judgment in CI and accept the cost.
- [ ] **For Tier 2 only:** add the `ANTHROPIC_API_KEY` secret and gate the job on a label
      or schedule.

---

## Limitations {#limits}

- **Tier 1 detects only that *cited* lines changed.** A behavior-changing edit far from
  any anchor won't trip it; conversely a pure line **shift** (inserting code above an
  anchor, reformatting) moves a cited line and causes a **false positive** even though the
  modeled logic is unchanged. Treat a Tier-1 failure as "go look", not "definitely wrong".
- **Re-baseline after an intentional sync.** Once `/vibe-tla sync <component>` has
  confirmed (or revised) the model, run `scripts/anchors.sh update tla` and commit the
  refreshed `anchors.lock` — otherwise CI keeps flagging the same already-handled drift.
- **Neither tier re-runs the proof on its own.** Drift detection is not verification;
  closing the loop still means a `check`/`sync` that reads the code and (re-)runs TLC. CI
  tells you *when* to do that, not that the property still holds.
