"""Confluence Signal System — Python mirror of the TradingView Pine Script.

This package reimplements the exact same rule-based multi-factor scoring
model as pine/confluence_signals.pine so it can be backtested against
years of historical data across many tickers, something TradingView's
own Strategy Tester cannot easily do in bulk.

Modules:
    indicators   - low-level technical indicator math (EMA, RSI, MACD, ATR, ADX, BB, OBV)
    signals      - the confluence scoring model (mirrors the Pine script 1:1)
    data         - historical OHLCV data loading (yfinance) with local caching
    backtest     - vectorized single-asset backtest engine with ATR risk sizing
    metrics      - performance metrics (CAGR, Sharpe, Sortino, drawdown, ...)
    multi_asset  - run the strategy across a whole watchlist and aggregate results
    optimize     - grid-search parameter optimization with walk-forward split
"""

__version__ = "0.1.0"
