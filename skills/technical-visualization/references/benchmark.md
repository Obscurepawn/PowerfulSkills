# Benchmark and performance figures

Use a chart to answer a concrete workload question: latency at a stated load, throughput as concurrency changes, memory growth, or performance across input sizes. Record the code revision, hardware, operating system, compiler/runtime and flags, workload/data size, timer, warm-up, measurement duration, repetitions, and correctness check. Keep failed runs and exclusions in the provenance record. Compare implementations under equivalent conditions; state what changed.

## Input and calculation contract

The bundled benchmark helper accepts CSV columns `series,x,run,value`. `series` names the implementation or condition; `x` is a finite numeric workload coordinate; `run` identifies one run within that series and coordinate; `value` is one finite, nonnegative measurement. Each `(series,x,run)` key is unique. Put one metric and one unit in a file. Labels or units in numeric cells are invalid. A row is a run-level observation, not automatically an independent experiment.

The JSON configuration requires `title`, `source`, `data_kind` (`observed` or `synthetic`), `metric`, `unit`, and `x_label`. `source` identifies the input's provenance; `synthetic` visibly marks demonstration data. Optional presentation fields are `width`, `height` (inches), `font_size` (points), and an installed `font_family` with the required glyphs.

| Setting | Meaning |
|---|---|
| `statistic` | `median` (default) or `mean`, computed within each `(series,x)` group |
| `interval` | `range` (default: observed minimum–maximum), `none`, or `bootstrap95` |
| `independent_runs` | Defaults to `false`; `bootstrap95` requires an explicit `true` supported by the experimental design |
| `seed`, `bootstrap_samples` | Defaults `0`, `2000`; controls reproducible resampling, not data generation |
| `y_scale` | `linear` (default) or `log`; log needs strictly positive observations |

The range describes observed spread and is not a confidence interval. Bootstrap bands are pointwise percentile intervals for the chosen group statistic, formed by sampling run values with replacement. They are not simultaneous bands, tests of differences, or predictions of future requests. The helper's minimum input requirements do not establish adequate power or stable tail estimates. Document the sample count and inspect the individual runs. [SciPy's bootstrap documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) distinguishes percentile and other intervals and explains paired resampling; the bundled helper is a small percentile implementation, not SciPy's BCa procedure.

## Measurement and chart selection

Repeated iterations inside one warmed process can share cache, scheduler, or thermal state. Separate those measurements from genuinely independent repetitions. Randomized/interleaved execution order can reduce time drift; preserve raw repetitions alongside summaries. Distinguish CPU time from elapsed time and document whether initialization is timed. [Google Benchmark's guide](https://google.github.io/benchmark/user_guide.html) documents warm-up, repetitions, random interleaving, and timer choices.

| Question | Display and required adaptation |
|---|---|
| How does a metric scale? | Use the bundled run-summary line chart, retain observed x positions, and show spread when supported. A connecting line is not a fitted scaling law. |
| What happens in the latency tail? | Write an ECDF, complementary CDF, or percentile plot from request-level samples or compatible histograms. Report requests, errors/timeouts, load-generation model, and measurement bounds. |
| What changed for matched workloads? | Plot within-pair differences or ratios from matched runs. The bundled independent group bands do not calculate paired contrasts. |
| Where does execution time go? | Use profiler-derived stacks or a component breakdown with consistent time denominators; distinguish inclusive and exclusive time. |
| How costly are cache misses? | Plot a specified counter/rate, with numerator, denominator, hardware event, and multiplexing details. Misses per instruction and misses per cache reference answer different questions. |

Never average per-run or per-host percentiles and label the result a pooled percentile. Compute pooled quantiles from the underlying observations or compatible weighted histograms, or explicitly label a summary of run-level quantiles. A tail estimate with few observations beyond its threshold deserves visible uncertainty, not extra decimal places.

A load generator that pauses while the service stalls can omit waiting requests. Record scheduled versus achieved load and the treatment of coordinated omission. [HdrHistogram's source documentation](https://github.com/HdrHistogram/HdrHistogram/blob/master/src/main/java/org/HdrHistogram/AbstractHistogram.java) explains correction using an expected sampling interval and warns against applying both correction paths to the same data. Keep corrected and recorded distributions distinguishable; the bundled helper does not perform that correction.

Use zero baselines for bars, identify log scales, and label lower/higher-is-better where ambiguity matters. For a speedup, define the reference and ratio direction; preserve paired workload matching and report the absolute baseline. Report a measured difference within the tested workload and hardware scope. Error-bar overlap does not establish equivalence or decide statistical significance.
