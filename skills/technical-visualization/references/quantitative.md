# Quantitative research charts

Begin with the data-generating and evaluation process: instrument universe, date range, calendar/timezone, sampling frequency, price adjustments, currency, signal availability, rebalance timing, portfolio construction, and return convention. Separate exploratory selection from held-out evaluation. A chart can describe supplied returns without certifying the backtest that produced them.

## Input and calculation contract

The bundled helper accepts CSV columns `date,series,return`. Dates use ISO `YYYY-MM-DD`; require one value per series/date, chronological order within each series, and the same date grid across series. `return` is a finite decimal simple return: `0.01` means 1%. It must be greater than `-1`. Convert prices or log returns explicitly before using this helper; log returns convert with `expm1`. Total loss, negative wealth, cash-flow-adjusted performance, and irregular intraday events need a separate implementation.

The JSON configuration requires `title`, `source`, `data_kind` (`observed` or `synthetic`), `return_basis` (`net` or `gross`), `frequency` (descriptive text), and `cost_note`. Optional presentation fields are `width`, `height` (inches), `font_size` (points), and an installed `font_family` with the required glyphs. `cost_note` states which fees, slippage, market impact, borrowing, financing, and taxes are included or absent; it does not cause the helper to deduct costs. A common `return_basis` applies to the input bundle, so do not mix net strategy returns with gross benchmark returns under one label.

Wealth starts at `W0 = 1`; each period computes `Wt = W(t-1) × (1 + rt)`. Drawdown is `Wt / max(W0,…,Wt) − 1`, including the starting capital in the high-water mark. Thus a first-period loss is immediately a drawdown. Preserve that convention when editing the source. External deposits and withdrawals are not returns.

For optional rolling statistics, supply `rolling_window`, `periods_per_year`, and `risk_free_per_period` together. The window counts observations. `risk_free_per_period` is a constant decimal simple return for the same period, not an annual rate. With `et = rt − rf`, the displayed annualized rolling Sharpe is `sqrt(periods_per_year) × mean(e) / sample_std(e)`, using `ddof=1`; incomplete windows and zero-variance windows are undefined. A changing risk-free curve requires a source edit and date alignment. Label this as a descriptive square-root-time annualization. Serial dependence can invalidate that scaling and alter inference, as discussed in [Lo, The Statistics of Sharpe Ratios (author's abstract)](https://alo.mit.edu/publications/page/18/).

## Checks before interpretation

- Preserve the source calendar. Missing values are neither zero return nor permission to forward-fill. Resolve unequal dates through an explicit, documented data preparation decision before plotting; report counts and the resulting comparison period.
- Verify point-in-time availability, corporate actions, delistings, and historical universe membership. Features, normalizers, and hyperparameters use training information only. Show training, validation, and test boundaries; overlapping label horizons can require purging or a gap.
- Record how many strategies, parameters, and windows were tried. A selected winner's curve is an exploratory result until independently evaluated. Name transaction-cost and capacity assumptions in the caption or adjacent notes.
- Assess serial dependence and regime changes before confidence intervals. [NIST's autocorrelation reference](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35c.htm) describes lag dependence and assumes equally spaced observations. Calendar gaps need interpretation before applying it.

The bundled helper computes wealth, drawdown, and optional rolling summaries. It does not generate trades, repair market data, test alpha, estimate factor models, perform resampling, or establish causality. Ordinary independent resampling loses time dependence; block or model-based approaches require design and parameter choices. [Berkowitz and Kilian's time-series bootstrap paper](https://www.federalreserve.gov/pubs/feds/1996/199645/199645pap.pdf) explains those issues, including the role of block length.

## Extend the source for other questions

| Chart | Data and definition to retain |
|---|---|
| Rolling out-of-sample comparison | Fit on each historical training window, select on validation only, then concatenate nonoverlapping test returns in time order; show boundary dates and costs. |
| Information coefficient (IC) | Align signal at decision time with the stated future-return horizon. Compute Pearson or Spearman correlation separately within each date's eligible cross-section; define tie handling (such as average ranks), universe size, and missingness. Report undefined constant cross-sections; overlapping horizons affect inference. |
| Factor exposure | State whether exposure means holdings-based loading or regression beta; retain factor definitions, units, estimation window, and uncertainty. A heatmap alone cannot establish neutralization. |
| Turnover and cost sensitivity | Define one-way or two-way turnover and the treatment of drift, cash, shorts, and rebalance weights. Derive cost scenarios from explicit assumptions and label them as scenarios. |
| Parameter or regime heatmap | Retain all searched settings, common color limits, observations per cell, selection criteria, and held-out performance. |

Keep labels and precision consistent with the data. Describe observed historical results and their evaluation scope; a smooth wealth curve or high rolling Sharpe does not establish a repeatable future return.
