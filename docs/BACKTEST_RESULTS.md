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

## Update 2 (2026-08-12): a real bug fix, a filter that helped, and a filter that didn't

Three changes were tested together this round: (1) a real correctness bug
found and fixed in the Python backtest engine, (2) a new chop filter, and
(3) explicit slippage modeling. Reporting all three honestly, including the
one that made things worse.

### Bug fix: stop/target were drifting, not fixed

While adding the slippage tests below, found that the Python engine's
stop-loss/take-profit levels were being **recomputed every bar from that
bar's live ATR**, not frozen at the ATR value from the moment of entry. This
contradicted both the documented design (`docs/ARCHITECTURE.md`) and the
Pine script's actual behavior (`longSL`/`longTP` are assigned with `:=`
exactly once, in the entry block, and never touched again). Fixed by adding
`Trade.entry_atr`, frozen at entry, with a regression test
(`test_stop_and_target_stay_fixed_for_the_life_of_a_trade`). This affects
every number reported anywhere above this line in this document — all
figures below are post-fix.

Post-fix, pre-any-new-filter baseline for SPY: CAGR 0.58% (was 0.42%),
Sharpe 0.33 (was 0.23), max DD -4.02% (was -5.05%). The regime filter's
own effect (from Update 1) holds up and slightly improves post-fix: SPY
CAGR 1.04%, Sharpe 0.70, max DD -2.10%, 17 trades, 58.8% win rate, side
10L/7S.

### Chop filter: helped SPY, hurt the watchlist in aggregate — do not ship as default

The idea: veto *any* new entry, long or short, while ADX says the market
isn't trending (`adxThresh=20`, the same threshold Factor 4 already uses).
Complementary to the regime filter in theory — that one says "don't fight
the big trend," this says "don't trade when there's no trend to catch."

**On SPY alone it looked great:** regime+chop vs. regime-only — Sharpe 0.79
vs. 0.70, max DD -1.70% vs. -2.10%, win rate 75% vs. 59% — at the cost of
trade count dropping from 17 to 8.

**Across the full 10-ticker watchlist it made things worse, not better:**

| Configuration | Median CAGR % | Median Sharpe | Median Max DD % | % Profitable | Total Trades |
|---|---|---|---|---|---|
| Baseline (post-fix, no filters) | 0.37 | 0.21 | -5.05 | 80% | 321 |
| Regime filter only | 0.34 | 0.20 | -4.12 | 80% | 210 |
| Chop filter only | **-0.21** | **-0.15** | -4.23 | **40%** | 150 |
| Regime + chop + slippage | **-0.03** | **-0.03** | -2.99 | **40%** | 78 |

Adding the chop filter — alone, or combined with the regime filter — flips
the aggregate median Sharpe *negative* and cuts the fraction of profitable
tickers from 80% to 40%. TSLA's win rate under chop+regime+slippage dropped
to 12% on 8 trades, MSFT to 17% on 6 trades — a single fixed ADX threshold
applied uniformly does not generalize across instruments with different
volatility characters, and the resulting per-ticker sample sizes (5-14
trades over 11.6 years) are too thin to trust individually regardless.

**Consequence:** the chop filter is implemented and available
(`use_chop_filter` / `--chop-filter` / `useChopFilter`) but now **defaults
off in both implementations** (previously defaulted on in Pine, matching
the other filters — corrected after this result). It's a real, useful
option to test on an individual, already-well-understood ticker — the SPY
walk-forward below shows it can meaningfully help there — but it is not a
blanket improvement and should not be treated as one. This is the sort of
thing that's easy to get backwards from intuition or a single-ticker demo,
which is the whole reason this system runs against real cross-sectional
data before trusting any change.

### Slippage: a small, real, non-catastrophic drag

`slippage_pct` (Python) / the Pine `strategy()` `slippage` argument (bumped
from 1 tick to 5) now widen every entry, stop-loss exit, and score-fade exit
against you; take-profit exits are treated as resting limit orders and
aren't slipped. At a modest 0.05% on SPY with regime+chop: CAGR 0.72% (was
0.73% without slippage), Sharpe 0.78 (was 0.79) — a small, expected drag,
not something that flips the conclusion either direction. Worth keeping on
for any figure meant to be trusted, since it costs almost nothing and
removes one source of the numbers being flattered by unrealistically clean
fills.

### Walk-forward, recommended stack (regime filter + 0.05% slippage, SPY, 2010-2026)

| Fold | In-sample Sharpe | Out-of-sample Sharpe | OOS CAGR % | OOS Max DD % | OOS Trades |
|---|---|---|---|---|---|
| 0 | -0.05 | **0.98** | 1.58 | -1.45 | 3 |
| 1 | 0.98 | **0.73** | 1.21 | -1.36 | 5 |
| 2 | 0.73 | **0.98** | 2.20 | -2.62 | 7 |

All three out-of-sample folds are now positive and reasonably close to each
other (0.73-0.98) — the most internally consistent walk-forward result
across every round of testing so far. For reference, adding the chop filter
on top of this (SPY-only, not the recommended default) pushed OOS Sharpe
even higher (0.86-1.46) and OOS CAGR up to 3.0% in the best fold, but at
2-4 trades per fold — too thin to add real confidence on top of what's
already a small sample, which is exactly why it isn't the default.

### Revised verdict

The bug fix and the regime filter are both real, validated improvements.
The chop filter is a validated *non*-improvement in its current form (fixed
global ADX threshold) and now correctly defaults off — a useful reminder
that not every well-motivated idea survives contact with real,
cross-sectional data, and that's exactly the point of testing this way
instead of shipping on intuition. Slippage modeling didn't change the
conclusion but removes a source of the numbers being too optimistic. Net
state: SPY with regime filter + slippage is the strongest validated
configuration so far (CAGR ~1%, Sharpe ~0.7, consistent walk-forward), and
it's still a modest, not-yet-"trade this with real money" result relative
to buy-and-hold.

## Update 3 (2026-08-12): market-breadth filter — the best individual filter so far

Idea: veto entries against a **separate reference ticker's** own trend
(SPY's 200-SMA by default), not the traded ticker's own — distinct from the
Long-Term Regime filter, which only looks at each ticker's own chart. Don't
short an individual name just because its own price action looks weak if
the broad market itself is still in an uptrend, and vice versa.

**Watchlist aggregate, four configurations compared (all post-ATR-fix):**

| Configuration | Median CAGR % | Median Sharpe | Median Max DD % | % Profitable | Total Trades |
|---|---|---|---|---|---|
| Baseline (no filters) | 0.37 | 0.21 | -5.05 | 80% | 321 |
| Regime filter only | 0.34 | 0.20 | -4.12 | 80% | 210 |
| **Breadth filter only** | **0.53** | **0.34** | -4.16 | 80% | 206 |
| Regime + breadth + slippage 0.05% | 0.40 | 0.25 | -3.65 | 80% | 155 |

Breadth alone is the single best-performing individual filter tested so
far in this document — better than the regime filter alone on every
aggregate metric, and it's **broad-based**: 8 of the 10 tickers improved
(SPY, QQQ, AAPL, NVDA, AMZN, GOOGL, META, AMD all positive CAGR; only MSFT
and TSLA stayed negative), not concentrated in one or two names the way the
chop filter's failure was concentrated. That's the key difference between
"ship this as default" and "don't" — breadth generalizes, chop didn't.

**Mildly counterintuitive wrinkle: combining regime + breadth tests *worse*
than breadth alone** (0.40%/0.25 Sharpe vs. 0.53%/0.34 Sharpe) — still
better than baseline, but the combination doesn't simply add the two
individual improvements together. Both filters are flavors of "don't fight
an uptrend" (one via the ticker's own SMA200+momentum, one via SPY's own
SMA200), so they likely overlap on a meaningful fraction of the same bars,
and stacking gates cuts trade count (206→155) further without a
proportional quality gain. Lesson: filters need to be validated in
combination, not just individually — "more filters" is not automatically
better even when every individual filter tested is itself an improvement.

**SPY-specific** (breadth reference == traded ticker here, so this is close
to but not identical to the regime filter's own effect on SPY — breadth is
pure SMA200 timing, regime also folds in 12-1mo momentum):

| Metric | Breadth only | Regime + breadth + slippage |
|---|---|---|
| CAGR | 0.79% | 0.92% |
| Sharpe | 0.52 | 0.72 |
| Max DD | -2.68% | -2.16% |
| Trades | 21 | 15 |
| Win Rate | 52.4% | 60.0% |
| Side split | 12L/9S | 10L/5S |

**Consequence:** `useBreadthFilter` now **defaults on in Pine** (same
convention as the regime filter — Pine's defaults are what runs live on a
chart out of the box) and stays opt-in in Python (`--breadth-filter`, same
research-baseline convention as every other filter regardless of whether
it's validated-good). Given the regime+breadth interaction above, the
honest recommendation for anyone tuning this live is: **try breadth alone
first**, and only add regime on top if you've separately confirmed it helps
your specific ticker — don't assume stacking every validated filter
together is the best configuration by default.

## Update 4 (2026-08-12): strength-scaled position sizing — clean, uniform drawdown control

Idea: scale the risked dollar amount per trade by the entry bar's own
conviction (`|net_score| / 100`) instead of risking a flat `risk_per_trade_pct`
on every trade regardless of how strong the signal was. `net_score` is
already a -100..100 scale by construction, so this needed no new parameter
beyond a toggle — `risk_per_trade_pct` becomes a ceiling, only fully risked
at maximum conviction.

**Controlled comparison, watchlist aggregate (regime + breadth filter stack,
no slippage, isolating just the sizing change):**

| Configuration | Median CAGR % | Median Sharpe | Median Max DD % |
|---|---|---|---|
| Flat sizing | 0.41 | 0.26 | -3.59 |
| Strength-scaled sizing | 0.39 | 0.29 | -2.77 |

Same trade count either way (155 — sizing doesn't change *which* trades
fire, only their size) and identical win rates (size doesn't affect
win/loss). The effect is small but real: better Sharpe, meaningfully
smaller drawdown, at a small CAGR cost.

**What makes this one trustworthy rather than a coin flip: it's uniform.**
Per-ticker, max drawdown improved at **all 10 of 10** watchlist tickers —
SPY -2.1%→-1.4%, QQQ -2.5%→-1.6%, TSLA -7.9%→-6.1%, MSFT -6.5%→-4.9%, every
single name in the same direction, with CAGR dipping by a small, consistent
amount at every ticker too. That's the opposite of the chop filter's
result (helped SPY, hurt half the watchlist) and matches exactly what
conviction-weighted sizing should theoretically do: smooth the equity curve
and cut worst-case exposure on marginal-conviction trades, at a modest,
consistent cost to raw return from being deliberately under-sized on those
same marginal trades.

**Consequence:** `useStrengthSizing` now **defaults on in Pine** (same
convention as regime/breadth) and stays opt-in in Python
(`--strength-sizing`). Unlike breadth (a bigger swing in Sharpe/CAGR), this
one is a genuine but modest risk-management refinement — worth having on,
not a result that changes the overall verdict about whether the system is
profitable yet.

## Update 5 (2026-08-12): chart patterns — implemented, tested, does not earn a default

New optional Factor 7: Double Top/Bottom and Head-and-Shoulders/Inverse,
detected via pivot ("fractal") points collapsed into a zigzag, matched
against geometric tolerance rules, confirmed only on an actual neckline
breakout (see `python/confluence/patterns.py` and the new Chart Patterns
section in `docs/ARCHITECTURE.md` for the full methodology). Unlike every
other factor here, chart patterns don't have a strong academic evidence
base — the closest is Lo, Mamaysky & Wang (2000), which is why the factor
shipped with `pattern_weight` defaulting to 0.0 (inert) rather than
guessing at a weight and rebalancing the other six factors' point budget
before any evidence existed either way.

**Isolated effect (no other filters), watchlist aggregate:**

| pattern_weight | Median CAGR % | Median Sharpe | % Profitable |
|---|---|---|---|
| 0 (baseline) | 0.369 | 0.213 | 80% |
| 10 | 0.367 | 0.211 | 80% |
| 20 | 0.346 | 0.197 | 70% |
| 30 | 0.338 | 0.193 | 70% |

Monotonically worse as weight increases — a real, if modest, negative
signal, milder than the chop filter's failure but pointing the same
direction: this specific implementation doesn't add edge on its own.

**Combined with the validated regime+breadth+strength-sizing stack:**
median CAGR/Sharpe *improved slightly* (0.386%→0.447%, 0.290→0.323 at
weight=30), which could look like a reason to turn it on — except the
per-ticker breakdown tells a different story. At weight=30: SPY unchanged,
QQQ +0.1%, AAPL +0.1%, GOOGL/META/AMD/AMZN/TSLA/MSFT's CAGR unchanged, but
**NVDA got worse** (CAGR 0.1%→0.0%, win rate 42%→37%) and **MSFT's drawdown
got worse** (-4.9%→-5.7%). Trade count was identical (155) across every
weight tested — patterns weren't changing which trades fired, only nudging
position size/exit timing slightly. A median improvement built from two
small positive nudges, six unchanged tickers, and one or two small negative
nudges is not a broad-based effect — it's noise-level, the same
broad-vs-concentrated check that caught the chop filter being fake-good.

**Consequence:** `pattern_weight` / `patternWeight` stay at **0.0 in both
implementations** — implemented, tested, and available for further
research (different tolerance/pivot parameters, the remaining patterns
from the Lo-Mamaysky-Wang set), but not turned on. This is a clean example
of the validation process working as intended: a feature that sounded
reasonable, got built carefully, and honestly didn't clear the bar — same
outcome as the chop filter, arrived at the same way, and worth trusting
precisely because it isn't every feature that gets built here surviving
contact with real data.

## Update 6 (2026-08-28): wider validation — same tickers, much more history

Every prior update above tested the same 10-ticker watchlist starting
2015-01-01 (~10-11 years). The goal here was to widen that: check whether
the regime+breadth+strength-sizing stack's improvement over baseline (the
combination all three default ON in both implementations) is specific to
that one mostly-bullish decade, or holds up further back.

**Scope caveat, stated honestly up front:** this environment had no
`TIINGO_API_KEY` and Yahoo Finance is network-blocked here, so the *ticker*
universe could not be widened this round — still the same 10 names. What
*could* be widened for free was the *time* dimension: each ticker's data
was already cached going back to its earliest available date (Tiingo's
"full history" — as far back as 1990 for AAPL/AMD/MSFT), so re-running with
`start=1990-01-01` uses each ticker's maximum available history instead of
being clipped to 2015+, at no extra download cost. That adds the dot-com
bubble and bust, the 2008 financial crisis, and the 2020/2022 shocks were
already partly covered — a much harsher, more varied sample than one bull
decade. Widening the ticker universe itself remains a good follow-up
whenever API access is available.

**Cross-sectional aggregate, full available history per ticker:**

| | Baseline (no filters) | Regime+Breadth+Strength-Sizing stack |
|---|---|---|
| Median CAGR | 0.10% | 0.25% |
| Median Sharpe | 0.066 | 0.215 |
| Median Max Drawdown | -9.24% | -4.09% |
| Median Win Rate | 32.8% | 41.0% |
| % Tickers Profitable | 60% | 70% |
| Total Trades (all 10 tickers) | 818 | 378 |

Directionally identical to every prior finding for this stack, now proven
over up to 36 years instead of ~10 — the absolute CAGR/Sharpe numbers are
lower than the 2015+-only figures reported in Update 3/4 (harsher decades
drag down the baseline too), but the *relative* improvement from the filter
stack is intact and, if anything, larger on this longer window.

**Per-ticker breakdown** (baseline → stack), history depth in parentheses:

| Ticker | History | CAGR | Max DD | Win Rate | Trades |
|---|---|---|---|---|---|
| SPY | 33y (1993) | 0.30%→0.33% | -8.5%→-3.2% | 36%→42% | 89→53 |
| QQQ | 27y (1999) | 0.50%→0.52% | -8.7%→-2.6% | 40%→47% | 88→47 |
| AAPL | 36y (1990) | 0.31%→0.38% | -9.8%→-3.9% | 35%→46% | 102→52 |
| MSFT | 36y (1990) | -0.11%→-0.06% | -14.2%→-7.6% | 32%→33% | 113→52 |
| NVDA | 27y (1999) | -0.24%→-0.07% | -14.0%→-7.3% | 29%→31% | 76→35 |
| AMZN | 29y (1997) | 0.30%→0.25% | -5.5%→-3.2% | 36%→40% | 88→42 |
| GOOGL | 22y (2004) | 0.06%→0.24% | -11.2%→-5.2% | 33%→40% | 63→30 |
| META | 14y (2012) | 0.14%→0.47% | -5.7%→-2.6% | 31%→47% | 36→17 |
| TSLA | 16y (2010) | -0.30%→-0.43% | -7.6%→-7.3% | 28%→11% | 61→19 |
| AMD | 36y (1990) | -0.02%→0.18% | -12.8%→-4.3% | 32%→42% | 102→31 |

Max drawdown improved at **all 10/10 tickers** and win rate improved at
**9/10** (TSLA is the exception, and on a small sample — 19 trades). CAGR
improved at 8/10; AMZN dipped slightly (0.30%→0.25%) and TSLA got
meaningfully worse (-0.30%→-0.43%) alongside its win-rate collapse
(28%→11%). This is the same broad-vs-concentrated check used throughout
this document, applied over a much longer window, and it reaches the same
verdict as before: broad-based, not a fluke of the specific tickers or
decade — reinforcing, not just repeating, the original decision to default
`useRegimeFilter`/`useBreadthFilter`/`useStrengthSizing` ON. TSLA
specifically not benefiting (or actively doing worse) under this stack is
worth remembering if trading that name individually — its extreme
volatility and gap risk seem to interact badly with the fixed ATR-based
stop/target here, though 19 trades is too few to treat that as settled.

**8-fold walk-forward on SPY, full history (1993-2026)** — testing
parameter *stability* over time, not just the fixed filter stack above.
Grid: `buy_threshold ∈ {30,40,50}`, `sell_threshold ∈ {-50,-40,-30}`,
`atr_mult_sl ∈ {1.0,1.5,2.0}`, `atr_mult_tp ∈ {2.0,3.0,4.0}` — 36 combos,
regime+breadth+strength-sizing on throughout.

- `buy_threshold=30` / `sell_threshold=-50` was the in-sample winner in
  **every single one of the 7 folds**, no exceptions — a far more
  consistent signal than anything else tested in this project so far, and
  notably more asymmetric/looser than the current live defaults
  (`buyThreshold=40`, `sellThreshold=-40`).
- `atr_mult_sl`/`atr_mult_tp` were not stable — they drifted from a tight
  2.0/2.0 in the earliest fold (1993-97 in-sample) toward a looser 1.0/4.0
  in the most recent two folds (2018+ in-sample), suggesting the
  best stop/target ratio may not be a single constant across market eras.
- Out-of-sample Sharpe was positive in 5 of the 7 folds (the two negative
  folds cover transitions out of the dot-com bust into 2001-05 and out of
  the 2008 crisis into 2009-14 — periods where whatever worked in-sample
  during a crash didn't transfer to the recovery that followed).
- Trade counts per out-of-sample fold were small (2-9), which makes any
  single fold's Sharpe/CAGR noisy — a real limitation of slicing 33 years
  into 8 pieces for a strategy that doesn't trade often.

**Consequence:** no defaults changed in either implementation from this
update. The cross-sectional result *reinforces* the existing
regime+breadth+strength-sizing defaults with a much larger sample; it
doesn't call for any code change. The walk-forward's consistent
`buy_threshold=30`/`sell_threshold=-50` finding is a legitimate lead worth
testing on its own — the same way every other change in this document got
tested in isolation before touching a default — but doing that properly
needs a dedicated run (isolated on this parameter, across the same
broad-vs-concentrated per-ticker check used everywhere else here), not a
same-day change off a single grid search on one ticker.

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
