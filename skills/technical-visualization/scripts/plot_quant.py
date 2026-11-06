#!/usr/bin/env python3
"""Plot aligned periodic simple returns without filling or silently dropping data."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
import math
import re

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
from plot_common import (COLORS, STYLES, DataError, apply_style, cli, decorate, export_bundle,
                         finite_number, integer, load_config, nonempty, read_csv)


def run(args):
    """Render return CSV to NAV/drawdown and optional descriptive rolling Sharpe."""
    config = load_config(args.config, {'return_basis', 'frequency', 'cost_note', 'rolling_window', 'periods_per_year', 'risk_free_per_period'})
    for key in ('return_basis', 'frequency', 'cost_note'):
        config[key] = nonempty(config.get(key), key)
    if config['return_basis'] not in {'net', 'gross'}:
        raise DataError('return_basis must be net or gross')
    rolling_keys = {'rolling_window', 'periods_per_year', 'risk_free_per_period'}
    provided = rolling_keys & set(config)
    rolling = bool(provided)
    if rolling and provided != rolling_keys:
        raise DataError('rolling Sharpe requires rolling_window, periods_per_year, and risk_free_per_period together')
    if rolling:
        config['rolling_window'] = integer(config['rolling_window'], 'rolling_window', 2, 100000)
        config['periods_per_year'] = finite_number(config['periods_per_year'], 'periods_per_year')
        config['risk_free_per_period'] = finite_number(config['risk_free_per_period'], 'risk_free_per_period')
        if config['periods_per_year'] <= 0:
            raise DataError('periods_per_year must be positive')
        if config['risk_free_per_period'] <= -1:
            raise DataError('risk_free_per_period must exceed -1')
    series = defaultdict(list)
    for line, row in read_csv(args.input, ['date', 'series', 'return']):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['date']):
            raise DataError(f'row {line} date must be YYYY-MM-DD')
        try:
            timestamp = date.fromisoformat(row['date'])
        except ValueError as exc:
            raise DataError(f'row {line}: invalid date') from exc
        value = finite_number(row['return'], f'row {line} return')
        if value <= -1:
            raise DataError('simple return must exceed -1; total-loss and post-default paths need an explicit separate model')
        if series[row['series']] and timestamp <= series[row['series']][-1][0]:
            raise DataError(f'{row["series"]}: dates must be unique and strictly increasing; no implicit sorting')
        series[row['series']].append((timestamp, value))
    names = sorted(series)
    if len(names) > len(COLORS):
        raise DataError('more than seven series: split into panels before using this template')
    dates = [day for day, _ in series[names[0]]]
    for name in names:
        if [day for day, _ in series[name]] != dates:
            raise DataError('all series must have identical dates; align explicitly and document exclusions before plotting')
    if rolling and config['rolling_window'] > len(dates):
        raise DataError('rolling_window exceeds the number of observations; no full window exists')
    rows = []
    prepared = {}
    notes = ['Equal periods and the stated calendar/frequency are user assertions; the script does not infer a trading calendar.']
    for name in names:
        returns = np.array([value for _, value in series[name]], dtype=float)
        with np.errstate(over='ignore', invalid='ignore'):
            nav = np.cumprod(1 + returns)
        if not np.all(np.isfinite(nav)) or np.any(nav <= 0):
            raise DataError(f'{name}: cumulative NAV overflowed or underflowed; inspect input scales')
        peaks = np.maximum.accumulate(np.r_[1.0, nav])[1:]
        drawdown = nav / peaks - 1
        sharpe = np.full(len(returns), np.nan)
        if rolling:
            window = config['rolling_window']
            for end in range(window - 1, len(returns)):
                excess = returns[end + 1 - window:end + 1] - config['risk_free_per_period']
                # Equal represented values have exactly zero spread; a mean rounded
                # away from that value must not manufacture a tiny denominator.
                deviation = 0.0 if np.all(excess == excess[0]) else float(np.std(excess, ddof=1))
                if deviation > 0 and math.isfinite(deviation):
                    value = math.sqrt(config['periods_per_year']) * float(np.mean(excess)) / deviation
                    if math.isfinite(value):
                        sharpe[end] = value
            if np.isnan(sharpe[window - 1:]).any():
                notes.append(f'{name}: zero-volatility or nonfinite rolling Sharpe is blank, not zero.')
        prepared[name] = (nav, drawdown, sharpe)
        for index, timestamp in enumerate(dates):
            rows.append({'date': timestamp.isoformat(), 'series': name, 'return': float(returns[index]), 'nav': float(nav[index]), 'drawdown': float(drawdown[index]), 'rolling_sharpe': float(sharpe[index])})
    apply_style(config)
    panel_count = 3 if rolling else 2
    fig, axes = plt.subplots(panel_count, 1, figsize=(config['width'], config['height']), sharex=True, layout='constrained')
    for index, name in enumerate(names):
        for ax, values in zip(axes, prepared[name][:panel_count]):
            ax.plot(dates, values, label=name, color=COLORS[index], linestyle=STYLES[index % len(STYLES)], linewidth=1.6)
    axes[0].set_ylabel('Wealth (start = 1)')
    axes[0].axhline(1, color='#666666', linewidth=0.7, linestyle=':')
    axes[0].legend(frameon=False, ncol=min(3, len(names)))
    axes[1].set_ylabel('Drawdown')
    axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    axes[1].set_ylim(top=0)
    if rolling:
        axes[2].set_ylabel(f'{config["rolling_window"]}-period\nSharpe')
        axes[2].axhline(0, color='#666666', linewidth=0.7)
    axes[-1].set_xlabel('Period end date')
    decorate(fig, config, f'{config["return_basis"].capitalize()} simple returns • {config["frequency"]} • drawdown from initial wealth included')
    synthetic = 'SYNTHETIC EXAMPLE — not a historical backtest or investment result.\n' if config['data_kind'] == 'synthetic' else ''
    caption = synthetic + f'{config["title"]}. {len(dates)} aligned periods, {dates[0]} to {dates[-1]}; {config["frequency"]}, {config["return_basis"]} decimal simple returns. Wealth starts at 1 before the first return. NAV is the cumulative product of (1 + return); drawdown is NAV / running maximum including initial wealth 1, minus 1. There is no implicit sorting, filling, date intersection, resampling, or fee adjustment.\nSource: {config["source"]}\nCost treatment: {config["cost_note"]}'
    if rolling:
        caption += f'\nRolling Sharpe uses {config["rolling_window"]} observations, full windows only: sqrt({config["periods_per_year"]:g}) × mean(return − {config["risk_free_per_period"]:g}) / sample standard deviation (ddof=1) of those excess returns. Risk-free rate is per input period; frequency is supplied, not inferred. Zero-volatility windows are blank. The square-root annualization assumes suitably comparable periods and does not adjust for serial dependence. It is descriptive, with no confidence interval or significance test.'
    caption += '\nReview: ' + ' '.join(notes)
    caption += '\nThese plots do not establish causality, out-of-sample robustness, or future returns. Research controls, parameter search, costs, and source validity require separate review.'
    groups = [{'axis': 'x', 'panels': [chr(ord('a') + index) for index in range(panel_count)]}]
    export_bundle(args, config, 'quant', fig, rows, ['date', 'series', 'return', 'nav', 'drawdown', 'rolling_sharpe'], caption, notes, groups)


if __name__ == '__main__':
    cli(run)
