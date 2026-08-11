# Roadmap

This is a living project. Rough phases, roughly in order — pick whichever
sounds most useful next time we sit down to work on it.

## Phase 1 — Foundation (done)

- [x] Multi-factor confluence scoring model (Trend / Momentum / Volume /
      Volatility regime / Mean-reversion), explainable and weight-capped.
- [x] TradingView Pine Script v5 strategy: chart overlay, score dashboard
      table, buy/sell markers, ATR stop/target, `alertcondition()` +
      dynamic `alert()` for webhook bots, native Strategy Tester support.
- [x] Python mirror with the identical rule set, for real historical
      backtesting outside TradingView.
- [x] Backtest engine with ATR-based volatility risk sizing.
- [x] Multi-asset / watchlist runner + cross-sectional aggregate stats.
- [x] Walk-forward grid-search optimizer (avoids naive in-sample overfitting).
- [x] Test suite on synthetic data (no network dependency).

## Phase 2 — More data, sharper signal

- [ ] Add a real sync check: a small script that parses both files' default
      values and fails CI if they drift.
- [ ] Expand the data layer beyond yfinance: crypto via `ccxt`, intraday
      bars, fundamentals (P/E, earnings dates) to gate entries around
      earnings volatility.
- [ ] Sentiment/news factor: headline sentiment score as a 6th weighted
      factor group (e.g. via a news API + simple sentiment classifier).
- [ ] Sector/market regime filter: don't go long individual names when
      SPY/QQQ itself is in a confirmed downtrend (market breadth filter).
- [ ] Replace the fixed rule weights with a learned model (logistic
      regression / gradient boosting) trained to predict forward N-day
      returns from the same feature set — compare against the hand-tuned
      score as a baseline, don't just swap it in blindly.

## Phase 3 — Automation

- [ ] Turn the Pine `alert()` JSON payload into a real webhook receiver
      (small server) that logs signals to a database for a persistent
      track record.
- [ ] Paper-trading connector (Alpaca or similar) driven by the Python
      backtest engine's live-signal mode, so the exact backtested logic
      can generate real paper orders.
- [ ] Telegram/Discord bot that posts buy/sell signals with the dashboard
      breakdown (mirrors the TradingView table) as they fire.

## Phase 4 — Portfolio-level risk

- [ ] Position correlation / sector exposure caps across concurrently open
      trades (currently each ticker is backtested independently).
- [ ] Portfolio-level equity curve and drawdown across the whole watchlist
      running simultaneously, with capital allocation between signals.
- [ ] Kelly-criterion or volatility-parity position sizing as an
      alternative to the current fixed risk-per-trade sizing.

## Notes for future sessions

- The synthetic-data test suite in `python/tests/` is the fast feedback
  loop — run `pytest` after any change to `signals.py` or `backtest.py`
  before touching real data.
- Live data pulls (`yfinance`) need outbound internet access to Yahoo
  Finance; some sandboxed/managed environments block this by default —
  test data commands from a machine with normal internet access if a
  managed session's proxy rejects the connection.
- `python/data_cache/` is gitignored on purpose — it's a local cache, not
  something to check in.
