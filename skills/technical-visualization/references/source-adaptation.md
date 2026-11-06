# Source basis and adaptation decisions

This skill adapts workflow and quality-control ideas from [Yuan1z0825/nature-skills](https://github.com/Yuan1z0825/nature-skills), inspected at commit `d774add241c65e89ed17a4da573b472b0972fd42` (commit date: 2026-11-04). It is a standalone engineering and quantitative-visualization skill, with no runtime dependency on that repository.

## Structure inspected

The snapshot contains 24 top-level `skills/*/SKILL.md` packages. `nature-figure` declares version `2.8.0` in its manifest. Its entrypoint routes tasks into local core instructions, backend fragments, on-demand references, reusable scripts, tests, evaluations, and assets. `nature-shared` supplies prose and journal references to other skills. This adaptation keeps the useful entrypoint/references/scripts/assets separation and makes its resources self-contained; it does not require copying all upstream packages or their routing manifests.

- [Figure entrypoint](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/SKILL.md)
- [Figure manifest](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/manifest.yaml)
- [Shared-reference entrypoint](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-shared/SKILL.md)

## Workflow carried forward

| Inspected source | Adaptation for this skill |
|---|---|
| [Figure contract](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/references/figure-contract.md) | Start with the reader's question, available evidence, units, comparison, output size, and intended use. A hypothesis can guide a chart; a conclusion is written only after checking the data. |
| [Multi-panel evidence architecture](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/references/multipanel-evidence-architecture.md) | Give panels distinct jobs. A performance report can pair latency distribution with workload scaling; a strategy report can pair wealth with drawdown. Add a panel when it changes interpretation, not merely because another metric exists. |
| [Vector schematic workflow](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/references/vector-schematic-workflow.md) | Map boxes and arrows to code, configuration, or an explicitly proposed design. Preserve live vector text and editable source, and distinguish synchronous calls, asynchronous events, storage, and trust boundaries. |
| [Asset adaptation](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/references/asset-adaptation.md) | Inspect field meaning before reusing a chart. Preserve raw inputs; record exclusions and transformations; guard logs, ratios, date order, duplicates, and nonfinite values. Demo data stays visibly separate from empirical findings. |
| [QA contract](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/references/qa-contract.md) | Run input and calculation checks, inspect exported artifacts, then review each panel and the whole figure at its intended size. Fresh checks follow layout changes. Automated preflight does not establish statistical validity or complete visual quality. |
| [Statistics entrypoint](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-statistics/SKILL.md) | Define the measurement, independent unit, and claimed inference separately. Distinguish request samples from independent benchmark runs and chronological observations from independent market experiments. Name uncertainty methods and assumptions. |
| [Writing stance](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-writing/static/core/stance.md) | Captions and accompanying prose use the supplied evidence, stable terminology, and bounded claims. Missing sample sizes, intervals, test results, costs, or deployment guarantees remain missing. |

Engineering-specific additions include workload and hardware context, warm-up and measurement boundaries, comparable baseline conditions, latency percentiles, correctness checks, and explicit failure paths in diagrams. Quantitative-research additions include return conventions, net/gross costs, calendar alignment, drawdown from initial capital, training/validation/test boundaries, look-ahead and survivorship bias, dependent observations, and multiple strategy selection. These additions are this skill's adaptation, not claims that the upstream repository already implements them.

## Deliberate changes

Use readable document or slide dimensions instead of importing Nature's column widths and tiny production typography. Respect an existing plotting workflow; use the bundled Python workflow when none is established. Do not impose the upstream first-use Python/R preference question or persist global preferences. Ask only for a missing fact that changes data meaning or the requested deliverable; continue independent work while it is unresolved.

Do not use image generation to draw measured values, uncertainty bands, network topology claimed to reflect implementation, or trading results. Data charts come from explicit inputs and transformations. Architecture illustrations retain semantic source. No journal-acceptance, publication-quality score, or visual-quality score substitutes for concrete checks.

One upstream rule is intentionally rejected: [the consistency sweep](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-shared/core/consistency-sweep.md) treats overlapping error bars as grounds for saying results are statistically indistinguishable. Overlap alone does not decide a comparison. Inference depends on what the bars mean, the sampling design, covariance, and an appropriate contrast. A nonsignificant test also does not establish equivalence. This skill retains numeric and terminology consistency checks without that shortcut.

The upstream privacy rule is adapted to the requested reproducibility goal: include portable relative input identifiers, checksums, and regeneration instructions; exclude credentials and unrelated private paths. Delivering an audit trail does not require embedding sensitive local directory names in figures.

## Attribution and reuse boundary

The inspected root [LICENSE](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/LICENSE) contains Apache License 2.0. The upstream [figures4papers notice](https://github.com/Yuan1z0825/nature-skills/blob/d774add241c65e89ed17a4da573b472b0972fd42/skills/nature-figure/assets/figures4papers/THIRD_PARTY_NOTICES.md) separately flags third-party scripts and images without an explicit upstream license; its reference to a root MIT license does not match the inspected root file. This package does not redistribute that asset collection, upstream figure images, or upstream implementation scripts. The links above credit the workflow sources actually inspected. If upstream code or assets are imported in a later revision, review the applicable file-level terms and preserve their required notices then.
