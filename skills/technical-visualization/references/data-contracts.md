# Inputs and portable bundles

The included helpers deliberately accept narrow schemas. Copy an example and replace both its values and provenance with the real input. Selecting `observed` is a declaration by the caller, not an automatic authentication check. Keep unrelated metadata in the figure brief; unknown JSON keys are rejected to catch misspelled options.

## CSV and JSON conventions

Use UTF-8 CSV, with the exact header order shown below, ordinary comma delimiters, and quoted fields when needed. No blank cells, NaN, infinity, duplicate observation keys, or extra columns are accepted. Dates are ISO `YYYY-MM-DD`. Plot JSON requires a nonempty `title`, `source`, and `data_kind` (`observed` or `synthetic`). Duplicate JSON keys are rejected.

Shared plot options:

| Key | Default | Meaning |
|---|---|---|
| `width`, `height` | 8, 5 | Inches; width 4–24, height 3–24 |
| `font_size` | 10 | Points, 8–24; check final destination size |
| `font_family` | `DejaVu Sans` | Installed font; unavailable fonts or missing glyphs fail the render |

Both plot starters accept up to seven series; use facets or a custom figure for more. PNG is rendered at 180 dpi; SVG/PDF are the masters. Values and source stay independent of visual configuration.

### Benchmark

```csv
series,x,run,value
```

`series` names the system/condition; numeric `x` is concurrency, problem size, or another explicitly labeled independent variable. Each `(series,x,run)` occurs once. `value` is a finite nonnegative run-level measurement in one unit. For a per-run p99, label the metric accordingly; summary lines then summarize per-run p99 values, never a pooled request percentile.

Required additional JSON keys are `metric`, `unit`, and `x_label`. Optional keys: `statistic` (`median` default or `mean`), `interval` (`range` default, `none`, `bootstrap95`), `independent_runs` (false default), `seed` (0), `bootstrap_samples` (2000), and `y_scale` (`linear` default or `log`). Bootstrap requires `independent_runs: true` and at least two runs in each group; small samples trigger a review warning. It uses a seeded percentile bootstrap of the selected center. A declaration of independence does not make runs independent.

Run-level points, summary lines, and vertical range/interval extents are exported. `derived.csv` includes `series,x,n,center,lower,upper,statistic,interval,unit`. With no interval, lower/upper fields are blank. Counts, matching workloads, and uncertainty interpretation belong in the caption.

### Quantitative returns

```csv
date,series,return
```

`return` is the decimal simple return over the period ending on `date` (0.01 means 1%). Each series has strictly increasing unique dates, and comparison series have identical dates. This helper requires returns greater than -1 and positive finite compounded wealth. Total-loss, negative-equity, log-return, price, intraday timestamp, irregular-frequency, cash-flow, and multi-currency inputs require an explicit preprocessing/model extension.

Required additional JSON keys are `return_basis` (`net` or `gross`), `frequency` (descriptive text), and `cost_note`. Optional `rolling_window`, `periods_per_year`, and `risk_free_per_period` are supplied together. The risk-free value is a constant decimal rate per input period; a varying risk-free series needs a code extension. The script does not deduct costs or infer market holidays, annualization, or train/test boundaries.

`derived.csv` contains `date,series,return,nav,drawdown,rolling_sharpe`. Rolling warm-up and undefined zero-variance windows are blank. The quantitative reference gives formulas and inference limits. A user assertion about equal periods is recorded as a warning for review.

### Architecture

See the exact JSON schema and examples in [engineering.md](engineering.md). `data_kind` also accepts `proposed`. Observed nodes and edges require nonempty evidence references; the script validates their presence, not the truth of a deployment claim. The output includes editable DOT as well as live-text SVG and PDF. Graphviz controls layout, so inspect arrow routing and text after rendering.

## Reproduction and manifests

Each render creates a new self-contained directory:

```text
result/
  inputs/                 copied source CSV/config or architecture JSON
  code/                   exact renderer and shared helpers
  manifest.json           hashes, parameters, environment, replay command
  figure.svg/pdf/png      or architecture.svg/pdf/png
  caption.txt
  derived.csv             numeric plots
  layout.json             measured plot rectangles in points
  requirements-lock.txt   installed plotting dependency versions
  REPRODUCE.txt           exact replay instructions
  architecture.dot        architecture only
```

Manifest schema version 1 has `kind`, `data_kind`, `inputs`, `outputs`, `parameters`, `environment`, `command`, `warnings`, and `checks`. File entries have portable relative `path` and SHA-256; inputs also have `role`. Run the command from the bundle directory and change its output argument if that directory already exists. The auditor never executes a manifest command. Review a received bundle's code before running it.

Plots record Python, OS, package versions, requested font and font-file hash. Graphviz bundles record Python, OS, Graphviz version, and requested font. Fonts are not redistributed. Same data/code should reproduce the calculations; byte-identical rendering additionally depends on matching renderer, libraries, fonts and platform. Graphviz's PDF backend can embed a creation timestamp, so compare rendered pages and extracted text when only that metadata differs. No claim of cross-platform byte identity is made.

`qa-auto.json`, `qa-notes.md`, and the figure brief may be added alongside the bundle after rendering. They are intentionally separate from the producer's original hashes. Hashes detect changed listed files; they do not provide a digital signature or certify a source. If the source is confidential, keep the bundle local and prepare a separately reviewed distribution copy.
