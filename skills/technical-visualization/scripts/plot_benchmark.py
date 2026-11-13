#!/usr/bin/env python3
"""Plot explicitly identified benchmark run summaries; never infer percentiles."""
from __future__ import annotations
from collections import defaultdict
import math

from plot_common import (COLORS, STYLES, MARKERS, DataError, apply_style, cli, decorate,
                         export_bundle, finite_number, integer, load_config, load_plotting_deps,
                         nonempty, read_csv)


def run(args):
    """Render benchmark CSV to editable figures and an auditable replay bundle."""
    np, _, plt, _ = load_plotting_deps()
    config = load_config(args.config, {'metric', 'unit', 'x_label', 'statistic', 'interval', 'independent_runs', 'seed', 'bootstrap_samples', 'y_scale'})
    for key in ('metric', 'unit', 'x_label'):
        config[key] = nonempty(config.get(key), key)
    config.setdefault('statistic', 'median')
    config.setdefault('interval', 'range')
    config.setdefault('independent_runs', False)
    config.setdefault('y_scale', 'linear')
    config['seed'] = integer(config.get('seed', 0), 'seed', 0, 2**32 - 1)
    config['bootstrap_samples'] = integer(config.get('bootstrap_samples', 2000), 'bootstrap_samples', 1000, 100000)
    if config['statistic'] not in ('mean', 'median'):
        raise DataError('statistic must be mean or median')
    if config['interval'] not in ('range', 'none', 'bootstrap95'):
        raise DataError('interval must be range, none, or bootstrap95')
    if not isinstance(config['independent_runs'], bool):
        raise DataError('independent_runs must be true or false')
    if config['interval'] == 'bootstrap95' and not config['independent_runs']:
        raise DataError('bootstrap95 requires independent_runs=true and defensible independent run sampling')
    if config['y_scale'] not in ('linear', 'log'):
        raise DataError('y_scale must be linear or log')
    groups = defaultdict(list)
    seen = set()
    for line, row in read_csv(args.input, ['series', 'x', 'run', 'value']):
        x = finite_number(row['x'], f'row {line} x')
        value = finite_number(row['value'], f'row {line} value')
        if value < 0:
            raise DataError('benchmark values must be nonnegative; use a custom signed-metric plot if needed')
        if config['y_scale'] == 'log' and value <= 0:
            raise DataError('log scale requires strictly positive values')
        key = (row['series'], x, row['run'])
        if key in seen:
            raise DataError(f'duplicate series/x/run at row {line}: {key}')
        seen.add(key)
        groups[(row['series'], x)].append(value)
    names = sorted({name for name, _ in groups})
    if len(names) > len(COLORS):
        raise DataError('more than seven series: split into panels before using this template')
    center_fn = np.mean if config['statistic'] == 'mean' else np.median
    rng = np.random.default_rng(config['seed'])
    summaries = []
    notes = []
    for (name, x), values in sorted(groups.items()):
        array = np.asarray(values, dtype=float)
        with np.errstate(over='ignore', invalid='ignore'):
            center = float(center_fn(array))
        if not math.isfinite(center):
            raise DataError('summary overflowed; rescale the metric with documented units before plotting')
        if config['interval'] == 'range':
            lower, upper = float(np.min(array)), float(np.max(array))
        elif config['interval'] == 'bootstrap95':
            if len(array) < 2:
                raise DataError('bootstrap95 requires at least two independent runs in every series/x group')
            if len(array) < 10:
                notes.append(f'{name}, x={x:g}: only {len(array)} runs; bootstrap coverage can be unstable')
            # Chunk resampling to avoid an allocation proportional to B * all runs.
            estimates = []
            for start in range(0, config['bootstrap_samples'], 100):
                batch_size = min(100, config['bootstrap_samples'] - start)
                samples = rng.choice(array, size=(batch_size, len(array)), replace=True)
                estimates.extend(center_fn(samples, axis=1))
            lower, upper = map(float, np.quantile(estimates, [0.025, 0.975], method='linear'))
            if not math.isfinite(lower) or not math.isfinite(upper):
                raise DataError('bootstrap summary overflowed; rescale the metric with documented units')
        else:
            lower = upper = float('nan')
        summaries.append({'series': name, 'x': x, 'n': len(values), 'center': center, 'lower': lower, 'upper': upper, 'statistic': config['statistic'], 'interval': config['interval'], 'unit': config['unit']})
    if any(row['n'] == 1 for row in summaries):
        notes.append('At least one group has one run; its range carries no replication evidence.')
    apply_style(config)
    fig, ax = plt.subplots(figsize=(config['width'], config['height']), layout='constrained')
    for index, name in enumerate(names):
        selected = [row for row in summaries if row['series'] == name]
        x = np.array([row['x'] for row in selected])
        centers = np.array([row['center'] for row in selected])
        for row in selected:
            points = groups[(name, row['x'])]
            ax.scatter([row['x']] * len(points), points, color=COLORS[index], alpha=0.35, s=18, marker=MARKERS[index], zorder=2)
        ax.plot(x, centers, label=name, color=COLORS[index], linestyle=STYLES[index % len(STYLES)], marker=MARKERS[index], linewidth=1.7, zorder=3)
        if config['interval'] != 'none':
            ax.vlines(x, [row['lower'] for row in selected], [row['upper'] for row in selected], color=COLORS[index], alpha=0.8, linewidth=1.3, zorder=2)
    ax.set_xlabel(config['x_label'])
    coordinates = sorted({row['x'] for row in summaries})
    if len(coordinates) <= 12:
        ax.set_xticks(coordinates)
    ax.set_ylabel(f'{config["metric"]} ({config["unit"]})')
    ax.set_yscale(config['y_scale'])
    if config['y_scale'] == 'linear':
        ax.set_ylim(bottom=0)
    ax.legend(frameon=False)
    interval_text = {'range': 'min–max range; not a confidence interval', 'none': 'no interval', 'bootstrap95': '95% percentile bootstrap CI across independent runs'}[config['interval']]
    decorate(fig, config, f'{config["statistic"].capitalize()} across runs • {interval_text}')
    synthetic = 'SYNTHETIC EXAMPLE — not measured performance.\n' if config['data_kind'] == 'synthetic' else ''
    caption = synthetic + f'{config["title"]}. {config["metric"]} in {config["unit"]} by {config["x_label"]}. Faint points are individual run summaries; lines show the {config["statistic"]}. Vertical extents show {interval_text}. Sample counts per series/x are in derived.csv.\nSource: {config["source"]}\nEach run is one supplied measurement unit, not automatically an independent replicate. No latency percentile is calculated from run summaries. No hypothesis test or causal attribution is performed.'
    if config['interval'] == 'bootstrap95':
        caption += f' Bootstrap seed={config["seed"]}, resamples={config["bootstrap_samples"]}; independence was declared by the user and is not verified by this script.'
    if notes:
        caption += '\nReview: ' + ' '.join(notes)
    export_bundle(args, config, 'benchmark', fig, summaries, ['series', 'x', 'n', 'center', 'lower', 'upper', 'statistic', 'interval', 'unit'], caption, notes, [])


if __name__ == '__main__':
    cli(run)
