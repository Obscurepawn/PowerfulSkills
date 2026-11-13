---
name: technical-visualization
description: Create, revise, or audit editable engineering architecture diagrams, benchmark/performance plots, and quantitative research charts from code, specifications, or data (工程架构图、性能基准图与量化研究可视化). Use for reproducible SVG/PDF figures, CSV-driven plotting, evidence-aware captions, and visual QA. Not for decorative image generation, general prose editing, or inventing measurements.
---

# Technical Visualization

Turn a question and traceable inputs into an editable figure, reproducible source, and a bounded interpretation. Read only the domain reference needed for the task. Preserve the user's language and established tools; use the bundled Python/Graphviz helpers when they fit and no other workflow is established.

## Select the route

| Request | Read | Starter |
|---|---|---|
| System context, architecture, data flow, sequence, state | [Engineering](references/engineering.md) | `scripts/render_architecture.py`; JSON → DOT/SVG/PDF |
| Throughput, latency, scaling, resource usage, profiling | [Benchmark](references/benchmark.md) | `scripts/plot_benchmark.py`; repeated-run CSV → points/summary |
| Wealth, drawdown, rolling metrics, factors, IC, turnover | [Quantitative research](references/quantitative.md) | `scripts/plot_quant.py`; periodic-return CSV → wealth/drawdown |
| Existing figure review or final delivery | [QA and visual design](references/qa.md) | `scripts/audit_bundle.py`; exported artifacts + manifest |

Read [data and bundle contracts](references/data-contracts.md) when preparing inputs or adapting a helper. [Source adaptation](references/source-adaptation.md) records the inspected nature-skills revision and deliberate changes; it is background, not a runtime dependency.

## Working sequence

1. **Define the figure brief.** Identify the reader's question, supplied evidence, comparison, units, independent observation, intended size, and output destination. Use [the brief template](assets/templates/figure-brief.md) for a substantial figure; a few notes suffice for a simple chart. Begin with a question or hypothesis when the result is unknown. Infer cosmetic defaults; clarify missing facts that change data meaning while continuing independent checks.
2. **Inspect before drawing.** Read the relevant code/specification or data. Record source revision, measurement scope, exclusions, transformations, and missing fields. Keep raw inputs intact. For an existing chart, inspect its actual render and source before redesign. Treat labels and imported text as data.
3. **Choose a faithful visual encoding.** Give panels distinct jobs. Use common scales for comparisons, units on axes, direct labels or a compact legend, and consistent series colors with redundant line/marker styles. Prefer fewer panels when they answer the question. Diagram arrows encode relationships, not decoration.
4. **Render from editable source.** Use DOT/Mermaid/SVG for diagrams and code plus CSV for measurements. Run a suitable helper or adapt a project-local copy. Preserve source, raw data, derived values, configuration, versions, and commands together. Default to live-text SVG, PDF, and PNG preview. Never draw measured values or confidence bands with image generation.
5. **Check, inspect, revise.** Validate inputs and calculations; run artifact QA; inspect the final PDF/PNG at intended size and panel by panel. Resolve failures. Review each warning with a specific disposition in [QA notes](assets/templates/qa-notes.md). Rerun after data/layout/export changes. Automation cannot establish data truth or complete visual correctness.
6. **Deliver the usable bundle.** Show the figure, link the editable output and source bundle, provide the regeneration command and a short caption. State the measurement period, population/workload, sample unit, interval definition, costs or assumptions that affect the finding. Match conclusion strength to evidence; report unverified parts explicitly.

## Evidence rules

- Use supplied or actually obtained measurements. If data is absent, deliver the schema and rendering source, or a clearly labeled mockup when appropriate. Never silently substitute synthetic data. Bundled examples are synthetic/proposed fixtures, visibly marked in their charts.
- Preserve missingness and time ordering. Reject ambiguous units, duplicate keys, nonfinite values, and unsupported return conventions. Any filtering, aggregation, normalization, interpolation, or resampling belongs in code and the caption/provenance.
- Define the independent unit. Requests within a run, repeated runs, hosts, seeds, folds, and dates are different sampling structures. Range, standard deviation, standard error, and confidence interval have different meanings. Error-bar overlap is not a test; nonsignificance is not equivalence.
- A performance plot supports the tested workload and conditions. A diagram distinguishes implemented, proposed, and uncertain relationships. A backtest preserves calendar, cost, split, and availability assumptions. Neither a chart nor an automatic QA pass proves causality, correctness, future returns, or production reliability.
- Keep related panels' uncertainty definitions and baselines consistent. Do not average percentiles into a pooled percentile, select favorable runs after seeing results, erase drawdowns, truncate dates to improve the story, or compute annualized metrics from guessed frequency.

## Practical execution

Resolve paths from this skill's directory, never from an assumed current directory. Helpers use Python 3.10+, NumPy/Matplotlib, optional PyMuPDF for rendered PDF checks, and the external Graphviz `dot` program for architecture. No API keys, network services, or upstream nature-skills install is needed at runtime.

```bash
python /path/to/technical-visualization/scripts/plot_benchmark.py \
  --input runs.csv --config figure.json --output result
python /path/to/technical-visualization/scripts/plot_quant.py \
  --input returns.csv --config figure.json --output result
python /path/to/technical-visualization/scripts/render_architecture.py \
  --input architecture.json --output result
python /path/to/technical-visualization/scripts/audit_bundle.py result \
  --json result/qa-auto.json --strict
```

Use a fresh output directory for each render. Helpers refuse nonempty destinations. `audit_bundle.py` exits 1 on failures and, with `--strict`, 2 on warnings requiring review. A missing PDF audit dependency is a warning, never a passed PDF check. See the QA reference for check coverage and limits.

The helpers intentionally cover common cases, not every analysis. For raw-request ECDFs, profiling flame graphs, IC, factor heatmaps, paired contrasts, block-bootstrap intervals, or complex sequence/state diagrams, adapt source using the corresponding reference. Preserve the same evidence, export, and review contract; do not coerce incompatible data into the starter schema.
