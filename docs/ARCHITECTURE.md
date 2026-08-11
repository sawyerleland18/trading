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
bullish confluence, negative means bearish. It's a sum of five independent
factor groups, each capped at a fixed weight so no single indicator can
dominate the signal.

| Factor group | Weight | What it measures | Bullish condition |
|---|---|---|---|
| **Trend** | ±25 | EMA stack (20/50/200) + price position | price above EMA20, EMA20 > EMA50, EMA50 > EMA200, price above EMA200 |
| **Momentum** | ±25 | RSI level/slope + MACD | RSI > 50 and rising, MACD line above signal, MACD histogram rising |
| **Volume** | ±20 | OBV trend + relative volume | OBV rising over N bars; a volume spike (> SMA × multiplier) confirms candle direction |
| **Volatility regime** | ±15 | ADX / DMI | only rewards trend-following signals when ADX shows the market is actually trending; contributes 0 in chop |
| **Mean-reversion** | ±15 | Bollinger Bands + RSI extremes | a volatility-expanding breakout beyond the bands, or a contrarian bounce setup at an extreme with RSI confirmation |

Each factor is scored with simple, explainable boolean rules — deliberately
not a black box. You can read `signals.py::compute_confluence` top to
bottom and know exactly why the score is what it is on any given bar.

### Signal generation

- **Long entry**: net score crosses **above** `buy_threshold` (default 40).
- **Short entry**: net score crosses **below** `sell_threshold` (default -40).
- **Exit**: whichever comes first — ATR-based stop-loss, ATR-based
  take-profit, or the score "fading" back through `exit_long_score` /
  `exit_short_score` (default ±10), which closes the trade early if the
  original thesis is no longer supported.
- **Regime label**: `STRONG_BUY` / `BUY` / `NEUTRAL` / `SELL` / `STRONG_SELL`
  based on where the score sits relative to the strong/normal thresholds —
  shown on the TradingView dashboard table.

### Multi-timeframe filter

Both implementations optionally require the higher-timeframe trend (EMA
fast vs. EMA slow on a higher timeframe) to agree with the trade direction
before entering — filters out counter-trend noise. Pine uses
`request.security(..., lookahead=barmerge.lookahead_off)`; Python
approximates it with a resample + one-bar-shift (`signals.add_htf_filter`)
so it can never see a still-forming higher-timeframe candle.

### Risk management

Both implementations size positions by **volatility risk**, not a fixed
dollar/share amount: `qty = (equity * risk_per_trade_pct) / (ATR * atr_mult_sl)`.
That means every trade risks roughly the same fraction of the account
regardless of how volatile the instrument is.

Stop-loss and take-profit are **locked in at the moment of entry** (ATR at
that bar × the configured multipliers) and held fixed for the life of the
trade in both implementations — they do not recalculate every bar. Default
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
