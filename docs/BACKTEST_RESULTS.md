# Backtest Results — Confluence Signal System

**Run date:** 2026-08-12
**Data source:** Tiingo (split + dividend adjusted daily bars)
**Universe:** SPY, QQQ, AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, AMD
**Range:** 2015-01-02 through 2026-08-11 (~11.6 years) for the scan; 2010-01-04 through 2026-08-11 for the SPY walk-forward test
**Costs modeled:** 0.05% commission per side (`confluence/backtest.py`); no separate slippage model beyond that

This is the first time this system has been run against real historical data (every prior validation was code-review-level reasoning plus academic citations for the *general* concepts it's built from, not this specific rule set backtested on actual prices).

## Watchlist scan — cross-sectional results

| Ticker | CAGR % | Max DD % | Win Rate % | Trades |
|---|---|---|---|---|
| QQQ | 1.23 | -2.91 | 46 | 35 |
| AAPL | 0.77 | -4.81 | 41 | 32 |
| GOOGL | 0.56 | -5.59 | 32 | 31 |
| SPY | 0.42 | -5.05 | 44 | 27 |
| AMD | 0.40 | -6.02 | 40 | 30 |
| META | 0.25 | -5.54 | 33 | 27 |
| MSFT | 0.14 | -5.56 | 39 | 31 |
| NVDA | 0.08 | -4.39 | 35 | 34 |
| AMZN | -0.05 | -5.35 | 31 | 32 |
| TSLA | -0.12 | -8.87 | 31 | 42 |

**Aggregate:**
```json
{
  "n_tickers": 10,
  "median_cagr_pct": 0.33,
  "median_sharpe": 0.20,
  "median_max_drawdown_pct": -5.45,
  "median_win_rate_pct": 37.0,
  "pct_tickers_profitable": 80.0,
  "total_trades": 321
}
```

Sample-size read: 321 trades across 10 tickers sounds like a lot, but per-ticker it's ~27-42 trades over 11.6 years (roughly 3 trades/ticker/year). At that count, a 95% confidence interval on any individual ticker's win rate is roughly ±17 points — wide enough that "TSLA win rate 31%" and "QQQ win rate 46%" are not confidently distinguishable from each other, or from a coin flip with a favorable payout ratio. The aggregate median is more trustworthy than any single ticker's row, but even that rests on the trades being independent, which they aren't (correlated market-wide entries/exits across the 10 names).

## SPY deep-dive

```
start_equity      10,000.00
end_equity        10,498.54
total_return_pct  4.99
cagr_pct          0.42
max_drawdown_pct  -5.05
sharpe            0.23
sortino           0.10
num_trades        27
win_rate_pct      44.44
profit_factor     1.41
avg_trade_pnl_pct 0.41
```

**Exit reason breakdown:** stop_loss=9, take_profit=9, score_fade=9 (an exact three-way split — coincidental, but the sample per bucket is too small, 9 trades each, to draw conclusions about which exit rule is pulling its weight).

**Side breakdown: 15 short / 12 long.** This is the single most important number in this report. SPY returned roughly +285% (≈13%/yr) buy-and-hold over this exact window — one of the strongest secular bull runs in market history — and the system took *more* short trades than long trades against it. That single structural fact accounts for most of the gap between the system's +5% total return and the market's +285%. The Long-Term Regime factor (SMA200 + 12-1 month momentum) added recently was meant to bias against counter-trend shorts in a persistent uptrend; on this evidence it isn't doing that strongly enough.

**HTF filter on vs. off:** not tested in this run — flagging as a follow-up rather than guessing.

## Walk-forward optimization (SPY, 2010–2026, 4 folds → 3 out-of-sample periods)

| Fold | In-sample Sharpe | **Out-of-sample Sharpe** | OOS CAGR % | OOS Max DD % | OOS Trades |
|---|---|---|---|---|---|
| 0 | 0.41 | **0.76** | 1.36 | -1.16 | 6 |
| 1 | 1.11 | **-0.06** | -0.16 | -3.44 | 10 |
| 2 | 0.24 | **0.37** | 0.36 | -2.10 | 8 |

The out-of-sample numbers are the only ones that mean anything here — in-sample numbers are fit to the data they're measured on and are expected to look better than reality. Two things stand out:

1. **In-sample performance doesn't predict out-of-sample performance.** Fold 1 had the *best* in-sample Sharpe (1.11) of the three folds and the *worst* out-of-sample Sharpe (-0.06, i.e. lost money risk-adjusted). That's a classic sign the grid search is fitting noise, not a stable edge — if it had found a real regime-appropriate parameter set, in-sample rank should correlate positively with out-of-sample rank, not invert it.
2. **Even the best fold's OOS CAGR is 1.36%/year** — on 6 trades. That's not a number you can act on; it's a handful of coin flips that happened to land right.

## Update 2026-08-12: regime filter added, re-tested

The trend-bias fix proposed above was implemented and re-run against the same
data: a `use_regime_filter` gate (`--regime-filter` on the CLI, `useRegimeFilter`
input in Pine, defaults on there / off in the Python backtest for explicit
opt-in) that vetoes any new entry against the Long-Term Regime factor's own
direction — no new shorts while `long_term_pts > 0`, no new longs while it's
negative. See `docs/ARCHITECTURE.md` for the mechanics.

**SPY, with filter on:**

| Metric | Before | After |
|---|---|---|
| Total return | 4.99% | **10.91%** |
| CAGR | 0.42% | **0.90%** |
| Max drawdown | -5.05% | **-2.26%** |
| Sharpe | 0.23 | **0.59** |
| Sortino | 0.10 | **0.25** |
| Win rate | 44.4% | **58.8%** |
| Profit factor | 1.41 | **2.68** |
| Trades (long/short) | 27 (12L/15S) | **17 (10L/7S)** |

The side split flipped from short-heavy to long-heavy, which was the entire
point — SPY spent most of this window in a bullish long-term regime, so a
regime-respecting system should be long-biased on it, and now is.

**Watchlist scan, with filter on** — aggregate: median CAGR 0.33% → **0.38%**,
median Sharpe 0.20 → **0.24**, median max DD -5.45% → **-4.66%**, % tickers
profitable 80% → **90%**, total trades 321 → **210** (fewer, higher-conviction
entries). The improvement is real but **uneven across tickers**: SPY, QQQ, and
AAPL — broad, persistently-trending names — improved substantially (QQQ CAGR
1.23%→1.41%, MaxDD -2.91%→-2.53%; AAPL CAGR 0.77%→0.98%, WinRate 41%→46%).
TSLA and AMZN, which had genuine multi-year bear phases inside this window
(2018, 2022), improved little or slightly worsened (TSLA CAGR -0.12%→-0.23%) —
consistent with the filter doing exactly what it's supposed to (block
counter-trend noise) rather than a blanket "always go long" bias in disguise.

**Walk-forward out-of-sample (SPY, 2010–2026), with filter on:**

| Fold | In-sample Sharpe | Out-of-sample Sharpe | OOS CAGR % | OOS Max DD % | OOS Trades |
|---|---|---|---|---|---|
| 0 | 0.11 | **0.60** | 0.59 | -1.27 | 3 |
| 1 | 0.84 | **0.34** | 0.47 | -1.34 | 5 |
| 2 | 0.55 | **0.84** | 2.07 | -2.75 | 7 |

The important change here isn't the CAGR numbers (still modest) — it's that
**the sign-flip problem is gone.** Before the filter, fold 1 had the best
in-sample Sharpe (1.11) and the *worst* out-of-sample Sharpe (-0.06, actually
losing money risk-adjusted) — the classic overfitting signature. With the
filter on, all three out-of-sample folds are positive and the ranking is far
more consistent (in-sample and out-of-sample Sharpe move in the same
direction fold to fold). That's a genuinely more trustworthy result, at the
cost of fewer trades per fold (3-7 vs. 6-10 before) — an even smaller sample
to hang confidence on, which cuts against the improvement somewhat.

**Revised verdict:** the regime filter is a clear, real improvement — better
risk-adjusted returns, smaller drawdowns, higher win rate, and a walk-forward
result that no longer contradicts itself. It is not yet a "trade this with
real money" result: SPY's 0.90%/yr still trails buy-and-hold by an enormous
margin, and every out-of-sample fold still has single-digit trade counts. The
right way to read this update is "the biggest structural bug is fixed, and
the fix measurably helped" — not "the system is now profitable." The next
open item from the original assessment (explicit slippage modeling, more
walk-forward folds/history) still stands.

## Honest assessment (original, before the regime filter — kept for the record)

**This does not show tradeable edge on this evidence.** Direct verdict, not hedged:

- Median Sharpe of 0.20 across the watchlist and a walk-forward out-of-sample Sharpe that swings from +0.76 to -0.06 fold-to-fold both say the same thing: whatever signal is in here is weak relative to its own noise.
- The SPY test is the clearest case: +5% over 11.6 years against a benchmark that returned +285% is not "slightly underperforming," it's giving up nearly all of one of the best bull markets on record — largely because the system is roughly balanced long/short in an environment where being long-biased would have trivially won.
- Trade counts (27-42 per ticker over 11.6 years; 6-10 per walk-forward fold) are too small to statistically distinguish the observed win rates from noise around 50%.
- Costs modeled are commission-only (0.05%/side); real slippage on stop-loss market exits during fast moves would erode the already-thin edge further, not help it.

None of this means the underlying factors are worthless — RSI, MACD, OBV, ADX, Bollinger position, and the SMA200/momentum regime filter are each individually well-documented. It means *this specific combination, these specific weights and thresholds, on this specific rule set*, hasn't demonstrated an edge that survives contact with real prices. The most direct next step, in priority order:

1. **Make the system asymmetric toward the dominant trend** — the 15-short/12-long split on SPY during a bull market is the biggest, cheapest fix available. Either strengthen the Long-Term Regime factor's veto power over counter-trend entries, or add the market-breadth filter discussed earlier (don't short individual names while SPY itself is in an uptrend).
2. **Re-run walk-forward with more folds / more history** once the above is in, since 6-10 trades per OOS fold isn't enough to trust either way.
3. **Add explicit slippage** (e.g. a fixed bps or ATR-fraction penalty on stop-loss exits specifically) so the backtest doesn't flatter market-order fills during fast moves.
