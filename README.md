# Confluence Signal System

An ongoing, collaborative trading-signals project. A rule-based, explainable
multi-factor engine tells you when to buy and sell — it lives as a
TradingView indicator/strategy **and** a Python backtesting suite that
validates the exact same logic against years of historical data across
many tickers, so the signal isn't just "looks good on one chart."

This is meant to be iterated on over time — see [`docs/ROADMAP.md`](docs/ROADMAP.md)
for what's built and what's planned next.

## How it works

Every bar gets a **net confluence score from -100 (max bearish) to +100
(max bullish)**, built from six independently-weighted, fully explainable
factor groups:

| Factor | Weight | Signal |
|---|---|---|
| Trend (EMA 20/50/200 stack) | ±20 | price/EMA alignment |
| Momentum (RSI + MACD) | ±20 | level, slope, crossover |
| Volume (OBV + relative volume) | ±15 | accumulation/distribution confirmation |
| Volatility regime (ADX/DMI) | ±10 | only rewards trend signals when the market is actually trending |
| Mean-reversion (Bollinger + RSI) | ±10 | breakout or contrarian bounce at the extremes |
| **Long-Term Regime** (SMA200 timing + 12-1mo momentum) | **±25** | the single largest-weighted factor, built from two of the most heavily-published, out-of-sample-replicated rules in empirical finance rather than a discretionary indicator — see below |

The BUY/SELL trigger fires on the exact bar an EMA crossover happens (so the
label lands right on the candle you'd expect it on), gated by the
confluence score already agreeing with that direction. Positions exit on
an ATR-based stop-loss/take-profit or when the score fades back toward
neutral. Full math and rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### The evidence behind the Long-Term Regime factor

Rather than adding a seventh discretionary indicator, the strongest factor
in this model is built from results that have been tested across a century
or more of real market data:

- **200-day SMA trend timing** — Faber (2007/2013), tested back to 1901
  across five asset classes; cuts drawdown roughly in half vs. buy-and-hold.
- **12-1 month time-series momentum** — Jegadeesh & Titman (1993);
  Moskowitz, Ooi & Pedersen (2012) across 58 futures markets over 25+
  years; replicated across 8 markets by Asness, Moskowitz & Pedersen (2013)
  and across **212 years** of data by Geczy & Samonov (2016).

Full citations and the "why the biggest weight" rationale are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository layout

```
pine/confluence_signals.pine   TradingView Pine Script v5 strategy
python/confluence/             Python mirror: indicators, scoring, backtesting, CLI
python/tests/                  pytest suite (synthetic data, no network needed)
config/                        shared default parameters + example watchlist
docs/                          architecture + roadmap
```

## 1. Using it on TradingView

1. Open TradingView → **Pine Editor** → New blank script → paste in the
   contents of [`pine/confluence_signals.pine`](pine/confluence_signals.pine).
2. Click **Add to Chart**. Because it's written as a `strategy()`, the
   **Strategy Tester** tab immediately shows equity curve, win rate,
   profit factor, drawdown, etc. for whatever chart/timeframe you're on.
3. Open the **Settings** (gear icon) to tune thresholds, EMA lengths,
   risk-per-trade, or turn the higher-timeframe filter on/off — every
   input is grouped and labeled.
4. **Alerts**: right-click the chart → *Add Alert* → condition
   "Confluence Signal System — Buy/Sell Engine" → choose the "CSS Buy
   Signal" / "CSS Sell Signal" alertcondition, or use "Any alert() function
   call" to receive the dynamic JSON-ish message (ticker, score, price) —
   useful if you want to wire this into a webhook bot later (see Roadmap
   Phase 3).

## 2. Backtesting with Python

The Python package reimplements the identical rules so you can test years
of data across a whole watchlist, not just eyeball one TradingView chart.

```bash
cd python
pip install -r requirements.txt
pytest                     # run the test suite first — synthetic data, no internet needed

# Backtest one ticker
python -m confluence.cli backtest --ticker AAPL --start 2015-01-01

# Backtest a whole watchlist and see aggregate, cross-sectional stats
cp ../config/watchlist.example.txt ../config/watchlist.txt   # edit freely, gitignored
python -m confluence.cli scan --watchlist ../config/watchlist.txt --start 2015-01-01

# Walk-forward parameter optimization (out-of-sample, not naive in-sample fitting)
python -m confluence.cli optimize --ticker SPY --start 2010-01-01
```

> Live data pulls need outbound internet access to Yahoo Finance
> (`yfinance`). If you're running this inside a locked-down sandbox whose
> network proxy blocks that host, run the data commands from a normal
> machine instead — the logic itself is fully covered by the offline
> synthetic-data test suite.

Downloaded price history is cached locally to `python/data_cache/`
(gitignored) so repeated runs don't re-download.

## Contributing / iterating together

This project is designed to be worked on incrementally across sessions.
Before changing the scoring rules:

1. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the current
   weight breakdown and design rationale.
2. Change the rule in **both** `pine/confluence_signals.pine` and
   `python/confluence/signals.py` — they're meant to mirror each other
   exactly.
3. Run `pytest` in `python/` — it checks score bounds and structural
   invariants that catch most mirror-drift bugs.
4. Check [`docs/ROADMAP.md`](docs/ROADMAP.md) for what's already planned
   next (sentiment data, portfolio-level risk, automation, ML-learned
   weights, ...) before starting something new.

## Disclaimer

This is a research/education tool, not financial advice. Backtested
performance does not guarantee future results. Nothing here should be
mistaken for a signal to risk money you can't afford to lose — always
paper-trade and validate independently before using real capital.
