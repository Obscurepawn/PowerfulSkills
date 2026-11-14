# PowerfulSkills

Production-minded Agent Skills for software engineering, formal verification, reproducible visualization, and technical writing. Built on the open `SKILL.md` packaging convention for Claude Code, Codex, Google Antigravity, Gemini CLI, and compatible coding agents.

## Quick Start

Requires Git, Python 3.9+, and a POSIX-compatible `bash` shell. Individual skills declare optional runtime tools (such as Java 17+ for TLA+ model checking or `matplotlib`/`graphviz` for figure rendering) only when those workflows run.

Clone the repository, install all skills into `~/.agents/skills/` (or `$CODEX_HOME/skills/` if `CODEX_HOME` is set), and verify the installed hashes:

```bash
git clone https://github.com/Obscurepawn/PowerfulSkills.git
cd PowerfulSkills
python3 scripts/install_skills.py
python3 scripts/install_skills.py --check
```

Expected output:

```text
[clear-answer-writing] installed: /home/<user>/.agents/skills/clear-answer-writing
[personal-project-engineering] installed: /home/<user>/.agents/skills/personal-project-engineering
[technical-visualization] installed: /home/<user>/.agents/skills/technical-visualization
[vibe-tla] installed: /home/<user>/.agents/skills/vibe-tla
```

Target a specific agent client, repository-local skill directory, or single skill with `--dest-root` and `--skill`. Existing installations are never overwritten unless `--force` is passed (which performs an atomic staging swap and strips development `tests/` directories):

```bash
# Install or update a single skill for Claude Code, Antigravity, or an embedded repo
python3 scripts/install_skills.py --dest-root ~/.claude/skills --skill vibe-tla --force
python3 scripts/install_skills.py --dest-root ~/.gemini/config/skills --skill vibe-tla --force
python3 scripts/install_skills.py --dest-root /path/to/repo/.agents/skills --skill vibe-tla
```

## Included Skills

| Skill | Domain | Core Mechanism & Tooling |
| --- | --- | --- |
| [`vibe-tla`](skills/vibe-tla/SKILL.md) | Code-faithful formal verification | `file:line`-anchored TLA+ specs, explicit-state BFS via **TLC**, symbolic SMT / inductive invariants via **Apalache + Z3**, adversarial bug triage, and drift detection. |
| [`technical-visualization`](skills/technical-visualization/SKILL.md) | Engineering & quantitative graphics | Editable SVG/PDF architecture diagrams (`dot`), bootstrap CI benchmark plots, equity/drawdown/rolling-Sharpe charts, SHA-256 provenance manifests, and `audit_bundle.py`. |
| [`personal-project-engineering`](skills/personal-project-engineering/SKILL.md) | Spec-driven project engineering | Structured `README.md`, feature specs, cross-client `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` authoring, and mechanical Markdown/link/script auditing (`audit_project_docs.py`). |
| [`clear-answer-writing`](skills/clear-answer-writing/SKILL.md) | Technical writing & de-AI editing | Precision technical prose, translation, and long-form editing without defensive boilerplate or meta-narration, backed by `ai_style_check.py`. |

**`vibe-tla` — Code-Faithful Formal Verification.** Hunts concurrency, durability, replication, recovery, and ordering bugs directly from production source code without requiring you to write TLA+ by hand. Every modeled state variable and action maps to a verified `file:line` (`var ↔ code` header), and `scripts/anchors.sh` hashes cited lines so `/vibe-tla sync` and CI catch code drift. Uses **TLC** (`tla2tools.jar`) for explicit-state breadth-first search and action-coverage checks (`--coverage`), and escalates to **symbolic reasoning** ([`references/symbolic.md`](skills/vibe-tla/references/symbolic.md)) — Skolem witness projection plus **Apalache/Z3** bounded model checking (`bmc`) and Counterexample-to-Induction (`inductive`) proofs — when 64-bit bit-fields, byte-budget watermarks, or unbounded counters cause Cartesian-product state explosion. `/vibe-tla check` emits *candidates* only; `/vibe-tla review` runs an adversarial refutation checklist (`R1–R5`) before confirming any bug, and `/vibe-tla fix` mechanically re-verifies patches via a `*_v2` spec. Requires Java 17+. Docs: [User Manual (EN)](docs/vibe-tla/MANUAL.md) · [使用手册（中文）](docs/vibe-tla/MANUAL.zh-CN.md) · [Toolchain Setup](skills/vibe-tla/references/tlc-setup.md).

**`technical-visualization` — Reproducible Engineering & Quantitative Graphics.** Generates publication-grade figures where every visual claim is backed by input data, deterministic replay commands, and automated integrity checks. Covers system architecture and trust-boundary diagrams (`scripts/render_architecture.py` via Graphviz `dot`), systems benchmarks with deterministic bootstrap confidence intervals (`scripts/plot_benchmark.py`), and aligned quantitative return/drawdown/rolling-Sharpe panels (`scripts/plot_quant.py`). Every run emits editable vector SVG/PDF, raster preview, `MANIFEST.json` with SHA-256 digests, and `REPRODUCE.txt`, verified by `scripts/audit_bundle.py`. Synthetic fixtures are labeled explicitly and statistical claims stay strictly within input evidence. Docs: [Installation & Usage Guide](docs/technical-visualization/INSTALL.md) · [Data Contracts](skills/technical-visualization/references/data-contracts.md).

**`personal-project-engineering` — Spec-Driven Project Engineering.** Keeps documentation, agent instructions, and implementation synchronized across personal and small-team repositories. Provides patterns and starter templates for `README.md`, functional specifications, and concise cross-client `AGENTS.md` files (with `CLAUDE.md` / `GEMINI.md` compatibility), paired with `scripts/audit_project_docs.py` to catch broken relative Markdown links, missing `#anchor` headings, unreplaced `{{...}}` placeholders, and undefined `npm run` scripts in `package.json`.

**`clear-answer-writing` — Clear Technical Writing & De-AI Editing.** Guides technical explanations, articles, design docs, reports, translations, and summaries toward direct, high-density prose while preserving factual scope, conditions, and author voice. Load the full skill (plus [`references/long-form.md`](skills/clear-answer-writing/references/long-form.md) and `scripts/ai_style_check.py`) when drafting or editing substantial prose; copy [`assets/AGENTS-snippet.md`](skills/clear-answer-writing/assets/AGENTS-snippet.md) into global `AGENTS.md` if you want concise everyday Q&A without loading the full skill on every turn.

## Repository Layout

```text
PowerfulSkills/
├── docs/                                # Human-facing manuals and installation guides
│   ├── technical-visualization/INSTALL.md
│   └── vibe-tla/{MANUAL.md,MANUAL.zh-CN.md}
├── scripts/
│   └── install_skills.py                # Atomic installer & SHA-256 verifier (excludes tests/)
└── skills/                              # Self-contained Agent Skill packages
    ├── clear-answer-writing/            # SKILL.md, references/, assets/, scripts/, tests/
    ├── personal-project-engineering/    # SKILL.md, references/, assets/, scripts/, tests/
    ├── technical-visualization/         # SKILL.md, references/, assets/, scripts/, tests/
    └── vibe-tla/                        # SKILL.md, references/, scripts/, tests/
```

Runtime references, templates, and helper scripts stay inside each `skills/<name>/` package for progressive disclosure; long-form user manuals live under `docs/` and unit tests under `skills/<name>/tests/` so installed skill directories remain lean.

## Development & Verification

Run the unit test suites and repository-wide documentation audit from the repository root:

```bash
python3 -m unittest discover -s skills/clear-answer-writing/tests -v
python3 -m unittest discover -s skills/personal-project-engineering/tests -v
python3 -m unittest discover -s skills/vibe-tla/tests -v
python3 -m unittest discover -s skills/technical-visualization/tests -v

python3 skills/personal-project-engineering/scripts/audit_project_docs.py . \
  README.md docs/*/*.md skills/*/SKILL.md skills/*/references/*.md skills/*/assets/*.md
```

*(Note: `technical-visualization` plotting tests execute in full when `matplotlib`, `numpy`, and Graphviz `dot` are installed in the active Python environment, and skip plotting-only cases cleanly otherwise.)*

## Contributing & Maintenance

1. Place new or updated skills under `skills/<skill-name>/` with valid YAML frontmatter (`name` matching the directory name and a concise `description` under 1,024 characters).
2. Put user-facing manuals in `docs/<skill-name>/` and automated regression tests in `skills/<skill-name>/tests/`.
3. Never commit credentials, local runtime caches (`__pycache__/`, `_apalache-out/`, `states/`), or private data from target repositories.
4. Update the table in this `README.md` and confirm `audit_project_docs.py` reports zero issues before pushing.

## Provenance & License Notice

This repository curates and maintains Agent Skills for day-to-day engineering and writing workflows. Inclusion in this repository does not imply that every skill was originally authored solely by the repository maintainer, nor does this repository grant additional licenses over third-party material; refer to individual skill directories where specific provenance applies.
