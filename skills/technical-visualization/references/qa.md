# Visual design and QA

An automatic pass describes the checks that ran. Delivery also requires an actual visual inspection and an evidence review. A polished chart can still be calculated incorrectly.

## Before rendering

Check units, numeric ranges, unique observation keys, missingness, sorted dates, sample definitions, comparability, and transformation assumptions. Recompute at least one nontrivial derived value by an independent route: for example, a paired speedup denominator or the first negative-return drawdown. Check extrema and counts against the input. Record exclusions instead of hiding them.

For benchmarks, capture hardware/software versions, workload, warm-up, measurement boundaries, repetitions, and correctness checks. For quant research, capture return convention, calendar, fees/slippage, baseline, split boundaries, and point-in-time availability. For diagrams, reconcile each node and edge with code/configuration or its explicit proposal status.

## Design at the destination size

The helpers use readable sans-serif text and color/line/marker redundancy. Use 9–11 pt as a starting point for document figures and larger text for slides. The audit's default 8 pt floor is a warning threshold, not a journal rule. If the document shrinks an 8-inch figure to 4 inches, the effective font size halves: regenerate at the intended size or inspect the scaled result.

Use a subdued grid, light background, few colors, and a stable palette across panels. Sequential heatmaps represent magnitude; diverging maps require a meaningful center such as zero. Avoid rainbow maps and color as the sole discriminator. Confirm grayscale readability. A screenshot of the figure can expose balance and labeling problems, but SVG/PDF and the source remain the editable masters.

Use zero for bars encoding magnitude. A nonzero line/scatter axis can reveal small variation when its range is visible and appropriate. Use logs only on valid positive quantities; state the base and units. Show missing observations as gaps. Avoid dual axes unless the mapping is necessary and explicit. Do not smooth away spikes or drawdowns. Share limits for panels intended to be compared.

## Automatic artifact checks

Run the bundled auditor after the final export:

```bash
python scripts/audit_bundle.py /path/to/result --json /path/to/result/qa-auto.json --strict
```

| Check | What it establishes | What remains manual |
|---|---|---|
| Manifest, confined paths, SHA-256 | Listed files exist, remain within the portable bundle, and match recorded bytes | Whether the original source is authentic or complete |
| SVG parse, viewBox, live text, raster warning | Basic validity and presence of editable labels | Correct font appearance, all mark editability, clipping and layering |
| PDF text extraction via PyMuPDF | Actual exported font sizes, page-edge text bounds, possible line-box overlap | Text/line/arrow collisions, visual salience, font licensing |
| Layout manifest from the renderer | Declared axes share requested edges within 1.5 pt; plot rectangles do not overlap | Whether groups are complete and comparable, intentional insets |
| Synthetic/proposed SVG label | Label text exists outside definitions and obvious hidden elements | Actual visibility after CSS/transforms, legibility and consistency in every view/caption |
| PNG signature, required formats, source presence | Expected artifact types are present | Image legibility and semantic fidelity |

Text bounding boxes can overlap without visible glyph collision, especially in math or rotated labels. Record a warning's exact text and why it is acceptable after inspecting that location. Do not weaken thresholds globally to hide a real defect. The auditor does not infer architecture routing collisions or all alignment groups. Plot bundles require a layout file; missing PDF inspection libraries produce a warning. SVG visibility checks cover obvious hidden attributes and inline styles, not complete CSS or transform evaluation.

`automatic_status` is `pass`, `review`, or `fail`; `human_review` remains `required`. Exit 0 means no failures (warnings may exist without `--strict`), exit 1 means failures, and strict exit 2 means warnings. Repeated audits need a new JSON filename. Rendering and auditing do not run network calls or silently alter input data.

## Human review and caption

Inspect the final PDF and PNG at destination size. Check whole-figure balance, each panel's labels/units, legend identity, line/arrow crossings, clipping, font glyphs, axis scales, time extent, uncertainty definition, and reading order. For architecture, trace one real request/event through the diagram and check the failure path relevant to the question. For data plots, reconcile several visible marks with exported derived values.

Write the result and limitations in `qa-notes.md`, using the bundled template. A caption identifies what was measured or proposed, the comparison and period/workload, sample unit/count, transformations, interval meaning, and important conditions. For an exploratory figure, describe the observed pattern without upgrading it into a confirmed effect. Keep a manual decision separate from automatic JSON so the machine result is not rewritten as a pass.

After any change to data, labels, dimensions, fonts, axes, or assembly, regenerate and rerun the affected checks. If a visual preview cannot be inspected, deliver it as unreviewed and name the outstanding check rather than claiming completion of visual QA.
