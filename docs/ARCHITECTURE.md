# Architecture

## Goal

One rule set, two implementations that must stay in lockstep:

1. **`pine/confluence_signals.pine`** — runs live on TradingView, draws the
   chart, fires alerts, and (because it's written as a `strategy()`) gives
   you TradingView's built-in Strategy Tester report for free.
2. **`python/confluence/`** — the same rules reimplemented in pandas/numpy,
   so the strategy can be backtested across years of history and hundreds
   of tickers at once — something TradingView's UI doesn't do well.

Neither is the "real" one. They're a mirror pair. When we tune a weight or
add a rule, we change it in both places (see the sync note at the bottom).

## The scoring model

Every bar produces a **net score from -100 to +100**: positive means
bullish confluence, negative means bearish. It's a sum of six independent
factor groups, each capped at a fixed weight so no single indicator can
dominate the signal.

| Factor group | Weight | What it measures | Bullish condition |
|---|---|---|---|
| **Trend** | ±20 | EMA stack (20/50/200) + price position | price above EMA20, EMA20 > EMA50, EMA50 > EMA200, price above EMA200 |
| **Momentum** | ±20 | RSI level/slope + MACD | RSI > 50 and rising, MACD line above signal, MACD histogram rising |
| **Volume** | ±15 | OBV trend + relative volume | OBV rising over N bars; a volume spike (> SMA × multiplier) confirms candle direction |
| **Volatility regime** | ±10 | ADX / DMI | only rewards trend-following signals when ADX shows the market is actually trending; contributes 0 in chop |
| **Mean-reversion** | ±10 | Bollinger Bands + RSI extremes | a volatility-expanding breakout beyond the bands, or a contrarian bounce setup at an extreme with RSI confirmation |
| **Long-Term Regime** | ±25 | 200-day SMA timing + 12-1 month time-series momentum | price above its long-term SMA, and trailing 12-month return (skipping the most recent month) is positive |

Each factor is scored with simple, explainable boolean rules — deliberately
not a black box. You can read `signals.py::compute_confluence` top to
bottom and know exactly why the score is what it is on any given bar.

### Why Long-Term Regime carries the biggest weight

The first five factor groups are standard discretionary technical analysis
rules — useful, but their evidence is mostly "traders have used this for
decades," not controlled out-of-sample studies. The Long-Term Regime factor
is different: it's built from two of the most heavily-published,
independently-replicated results in empirical asset pricing, and it
carries the single largest weight (±25) on purpose.

1. **200-day SMA trend timing.** Mebane Faber, *"A Quantitative Approach to
   Tactical Asset Allocation"* (2007, updated 2013) — a simple rule (hold
   when price is above its 10-month/~200-day SMA, otherwise hold cash)
   tested back to **1901** across five asset classes (US equities, foreign
   equities, bonds, commodities, REITs) and found to cut max drawdown
   roughly in half versus buy-and-hold with comparable or better returns.
   It's one of the most replicated trend-timing results in the tactical
   asset allocation literature.
2. **12-1 month time-series momentum.** Jegadeesh & Titman (1993) first
   documented that assets with strong trailing returns tend to keep
   outperforming over the next 3-12 months. Moskowitz, Ooi & Pedersen,
   *"Time Series Momentum"* (Journal of Financial Economics, 2012) found
   the same effect testing 58 liquid futures markets (equity indices,
   currencies, commodities, bonds) across 25+ years. Asness, Moskowitz &
   Pedersen, *"Value and Momentum Everywhere"* (2013) replicated it across
   8 different markets and asset classes going back decades, and Geczy &
   Samonov, *"Two Centuries of Momentum"* (2016) found it holding across
   **212 years** of data. The "12-1" construction (12-month lookback,
   skipping the most recent month) is the standard form used in the
   literature specifically because it avoids the well-documented
   short-term reversal effect contaminating the signal.

Everything else in this model is a discretionary confirmation layer around
that long-term evidence base, not a replacement for it.

### Signal generation

Entries are gated by a **trigger mode** (`trigger_mode` in Python /
`Trigger Mode` input in Pine), so the BUY/SELL event lines up with what's
visually obvious on the chart instead of firing on an invisible score
threshold cross:

- **`ema_cross_confluence` (default)** — a BUY/SELL fires on the exact bar
  the chosen EMA pair crosses (`ema_cross_pair`: fast/mid by default,
  fast/slow, or mid/slow), *gated* by the net score already agreeing with
  that direction (`net_score >= ema_confirm_score` for longs, `<=
  -ema_confirm_score` for shorts; default confirm level ±15). This is what
  draws the BUY/SELL label directly on the candle where the crossover
  happens on the TradingView chart.
- **`score_threshold_cross`** — the older behavior: fires purely when the
  net score itself crosses above `buy_threshold` (default 40) / below
  `sell_threshold` (default -40), ignoring EMA crossovers entirely. Useful
  if you want signals driven by the full multi-factor score rather than
  tied to a specific EMA event.

- **Exit**: whichever comes first — ATR-based stop-loss, ATR-based
  take-profit, or the score "fading" back through `exit_long_score` /
  `exit_short_score` (default ±10), which closes the trade early if the
  original thesis is no longer supported.
- **Regime label**: `STRONG_BUY` / `BUY` / `NEUTRAL` / `SELL` / `STRONG_SELL`
  based on where the score sits relative to the strong/normal thresholds —
  shown on the TradingView dashboard table. This label reflects the score
  at all times and is independent of which trigger mode is active.

### Candle BUY/SELL % popup (Pine-only, display feature)

A label pops up directly on the candle the moment `net_score` crosses
±`popupThreshold` (default 50%), reading e.g. `BUY 62%` or `SELL 58%` — a
heads-up independent of whether the strategy's own gated trade trigger
(above) actually fires on that bar. Uses `ta.crossover`/`ta.crossunder`
against the threshold, so it fires once per crossing event rather than
re-labeling every bar the score stays past the level. Also backs an
`alertcondition()` pair ("CSS Score Crossed Bullish/Bearish Threshold") so
it can drive a TradingView alert, separate from the trade-entry alerts.
Toggle: `showPopupAlert` input; threshold: `popupThreshold` input (both in
the "Candle BUY/SELL % Popup" group). Pine-only — like the dashboard table
and signal button, there's no Python equivalent since the Python side has
no chart to draw on; `net_score` crossing the same threshold is trivially
derivable from `compute_confluence()`'s output if a Python consumer needs it.

### Manual trade planner (Pine-only, display feature)

Pine has no click-to-query interactivity — a script can't react to "the user
clicked this specific bar." The closest, more useful equivalent: a panel
(bottom-right table, "IF YOU ENTER NOW") that's **always live** rather than
click-triggered — it continuously shows what stop-loss, take-profit,
suggested position size, dollar risk, and reward:risk ratio would be *if you
entered long or short on the current bar right now*, using the exact same
ATR-based formulas as the strategy's own real entries
(`plannerLongSL`/`plannerLongTP`/`plannerShortSL`/`plannerShortTP`, computed
from the current bar's `close`/`atrVal`, not tied to whether `longCondition`/
`shortCondition` actually fired). Also plots small circle markers at the
hypothetical stop/target levels on the current bar, but only while flat
(`strategy.position_size == 0`) — an actual open position already draws its
real stop/target as solid lines via `slPlotSeries`/`tpPlotSeries`, so this
only shows when there's nothing to conflict with. Toggle: `showTradePlanner`
input ("Manual Trade Planner" group). Pine-only, same reasoning as the
dashboard table and signal button.

### Alert payloads (Pine-only)

Every `alert()` call (entries, exits-via-score-fade, and the candle popup
above) sends a JSON payload, not free text, built by `f_entryAlertJson()`
and `f_scoreAlertJson()` — meant to be parsed directly by a webhook receiver
(3Commas, Alertatron, a custom bot) rather than regexed out of a sentence.
Entry payloads: `{"strategy","ticker","event":"entry","action":"buy"|"sell","price","stop","target","qty","score","time"}`.
Score-popup payloads: `{"strategy","ticker","event":"score_alert","direction":"bullish"|"bearish","score","threshold","price","time"}`.
The on-chart labels are unaffected — still human-readable text; only the
`alert()` payload format changed. Note this only covers signal-generation
events (entries, popups) — stop-loss/take-profit *fills* don't have an
alert payload yet, since firing precisely on an order fill (as opposed to
when the script evaluates a signal) needs `alert_message` on
`strategy.exit()` rather than a plain `alert()` call; a natural follow-up
if full automation coverage (including exits) is needed later.

### Multi-timeframe filter

Both implementations optionally require the higher-timeframe trend (EMA
fast vs. EMA slow on a higher timeframe) to agree with the trade direction
before entering — filters out counter-trend noise. Pine uses
`request.security(..., lookahead=barmerge.lookahead_off)`; Python
approximates it with a resample + one-bar-shift (`signals.add_htf_filter`)
so it can never see a still-forming higher-timeframe candle.

### Long-term regime filter

Both implementations can optionally veto *new* entries that go against the
Long-Term Regime factor's own direction — no new shorts while `long_term_pts
> 0` (price above its 200-SMA and/or positive 12-1mo momentum dominating),
no new longs while `long_term_pts < 0`. This exists because that factor is
only one of six additive inputs to `net_score`, so a strong bearish reading
from the other five could still trigger a short even while the long-term
regime itself was bullish. Real-data backtesting (`docs/BACKTEST_RESULTS.md`)
showed exactly that: SPY took 15 short trades against 12 longs through an
11-year bull market. Toggle: `useRegimeFilter` input (Pine, defaults on) /
`use_regime_filter` param to `run_backtest()` (Python, defaults off — opt
in via `--regime-filter` on the CLI) / `regime_bullish` & `regime_bearish`
columns from `compute_confluence()`.

### Chop filter

Both implementations can optionally veto *any* new entry — long or short —
while ADX says the market isn't trending (`adx <= adx_thresh`, the same
threshold Factor 4 uses). This is a complementary filter to the Long-Term
Regime one above: that one says "don't fight the big trend," this one says
"don't trade when there's no trend to catch at all." Toggle: `useChopFilter`
input (Pine) / `use_chop_filter` param to `run_backtest()` (Python — opt in
via `--chop-filter` on the CLI) / `trending` column from
`compute_confluence()`. **Defaults off in both implementations** — real-data
testing found it helped SPY specifically but made the cross-sectional
watchlist aggregate worse (see docs/BACKTEST_RESULTS.md); not a blanket win
with the single fixed `adxThresh` used here.

### Market breadth filter

Distinct from the Long-Term Regime filter above, which only looks at the
*traded* ticker's own 200-SMA trend: this optionally vetoes new entries
against a **separate reference ticker's** own 200-SMA trend (SPY by default)
— don't short an individual name just because its own chart looks weak if
the broad market itself is still in an uptrend, and vice versa for longs
against a weak broad market. Same underlying rule as the regime filter
(Faber SMA timing), just applied to a different series.

Toggle: `useBreadthFilter` input + `breadthSymbol` input (Pine, symbol
defaults to SPY) / `use_breadth_filter` + `breadth` params to
`run_backtest()` (Python — opt in via `--breadth-filter` and
`--breadth-ticker` on the CLI; `breadth` is the output of
`signals.compute_breadth()` run once on the reference ticker's OHLCV and
passed in, rather than every call re-fetching/re-computing it — matters for
`multi_asset.run_watchlist()`, which loads and computes the reference
ticker's breadth exactly once and reuses it across every ticker in the
watchlist). Pine fetches the reference ticker's close and 200-SMA via
`request.security(breadthSymbol, timeframe.period, ...)` — same timeframe as
the chart, just a different symbol, with `lookahead=barmerge.lookahead_off`
for the usual no-repaint guarantee.

**Defaults on in Pine, off in Python** (same convention as the regime
filter — Pine's defaults are what should run live on a chart out of the
box; Python's default to a clean, opt-in baseline for research runs via
`--breadth-filter`/`--regime-filter`/etc., regardless of whether a filter
is validated-good). Unlike the chop filter, this one earned its default:
real-data testing across the 10-ticker watchlist found it broad-based (8/10
tickers improved, not concentrated in one or two names) and the
single best-performing individual filter tested so far — median CAGR
0.37%→0.53%, median Sharpe 0.21→0.34, vs. no filters at all, actually
outperforming the regime filter alone on this watchlist. See
`docs/BACKTEST_RESULTS.md` for the full comparison, including the mildly
counterintuitive finding that regime+breadth *combined* tested slightly
worse in aggregate than breadth alone — evidence the two filters overlap
somewhat (both are flavors of "don't fight an uptrend") and stacking gates
isn't simply additive; each addition and combination needs its own check,
not an assumption that more filters is always better.

### Slippage

Both implementations can model adverse fills, not just commission. In the
Python engine, `slippage_pct` widens every market-style fill against you —
new entries, stop-loss exits, and score-fade exits — by that percentage;
take-profit exits are treated as resting limit orders and aren't slipped,
which is standard backtesting convention. Pine has no percentage-slippage
option, so it uses the built-in `slippage` argument to `strategy()` (in
ticks, applied automatically to every fill) — not directly comparable to the
Python percentage since tick value differs per instrument, but the same
purpose. Both default to a small-but-nonzero amount of protection now (Pine:
5 ticks; Python CLI: opt in via `--slippage <pct>`) after real-data testing
showed the strategy's edge is thin enough that unrealistically clean fills
were flattering the numbers.

### Risk management

Both implementations size positions by **volatility risk**, not a fixed
dollar/share amount: `qty = (equity * risk_per_trade_pct) / (ATR * atr_mult_sl)`.
That means every trade risks roughly the same fraction of the account
regardless of how volatile the instrument is.

Stop-loss and take-profit are **locked in at the moment of entry** (ATR at
that bar × the configured multipliers) and held fixed for the life of the
trade in both implementations — they do not recalculate every bar. (This was
the stated design from the start and always true of the Pine script, but the
Python engine had a bug — fixed 2026-08-12 — where it recomputed stop/target
from each *current* bar's live ATR instead of the frozen entry-bar ATR;
`Trade.entry_atr` now enforces the freeze, with a regression test.) Default
multipliers are 1.5×ATR stop / 3×ATR target, a 2:1 reward-to-risk ratio, so
the strategy only needs to win roughly 1 in 3 trades to break even before
costs. Tighten/widen via the `atr_mult_sl` / `atr_mult_tp` inputs (Pine) or
`ConfluenceParams.atr_mult_sl` / `atr_mult_tp` (Python) — keep the ratio
between them in mind, since that ratio, not just the win rate, is what
determines whether the strategy is profitable overall.

On the Pine chart, every BUY/SELL signal draws a label with the exact
entry, stop-loss, and take-profit prices, and the current trade's stop/target
levels are plotted as live horizontal lines on the candles (and echoed in
the dashboard table) for as long as the position stays open.

## Repository layout

```
pine/
  confluence_signals.pine   # TradingView strategy script (paste into Pine Editor)
python/
  confluence/
    indicators.py    # EMA, RSI, MACD, ATR, ADX/DMI, Bollinger, OBV — from formulas, no TA-Lib dependency
    signals.py        # ConfluenceParams + compute_confluence() + add_htf_filter()
    data.py            # yfinance loader with local parquet caching
    backtest.py        # event-driven single-asset backtest engine (ATR stop/target, risk sizing)
    metrics.py          # CAGR, Sharpe, Sortino, max drawdown, win rate, profit factor
    multi_asset.py       # run the strategy across a whole watchlist, aggregate cross-sectional stats
    optimize.py            # grid search + walk-forward validation
    cli.py                   # `python -m confluence.cli {backtest,scan,optimize}`
  tests/                       # pytest suite, runs entirely on synthetic data (no network needed)
config/
  default.yaml                  # canonical parameter defaults (documentation source of truth)
  watchlist.example.txt          # sample ticker list for `scan`
docs/
  ARCHITECTURE.md (this file)
  ROADMAP.md                        # phased plan for where this goes next
```

## Keeping Pine and Python in sync

There is currently no automated sync between the two files — that's a
deliberate, tracked simplification (see Roadmap). When changing a rule or
weight:

1. Edit `pine/confluence_signals.pine`.
2. Make the identical change in `python/confluence/signals.py`.
3. Update the weight table above and `config/default.yaml` if a default
   changed.
4. Run `pytest` in `python/` — the test suite checks score bounds and
   structural invariants, which will catch most mirror-drift mistakes
   (e.g. a factor exceeding its declared weight cap).
