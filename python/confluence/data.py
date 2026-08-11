"""Historical OHLCV data loading with local caching.

Uses yfinance (no API key required) as the default source. Data is cached
to python/data_cache/ as parquet so repeated backtests/optimizations don't
re-download. Swap in another data source later (a broker API, a paid
vendor, crypto exchange via ccxt, etc.) by adding a new function with the
same return contract: a DataFrame indexed by tz-naive datetime with lower
case columns open, high, low, close, volume.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"


def _cache_path(ticker: str, interval: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_ticker = ticker.replace("/", "-").replace("^", "")
    return CACHE_DIR / f"{safe_ticker}_{interval}.parquet"


def load_ohlcv(
    ticker: str,
    start: str = "2015-01-01",
    end: str | None = None,
    interval: str = "1d",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch OHLCV history for `ticker` via yfinance, normalized to lower-case columns.

    Raises RuntimeError with a clear message if yfinance isn't installed or
    the network/download fails — callers (CLI, tests) should surface that
    directly instead of guessing why an empty frame came back.
    """
    cache_file = _cache_path(ticker, interval)
    if use_cache and not force_refresh and cache_file.exists():
        df = pd.read_parquet(cache_file)
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        return df

    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "yfinance is required for live data downloads. Install it with "
            "`pip install -r python/requirements.txt`."
        ) from exc

    raw = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
    if raw.empty:
        raise RuntimeError(f"No data returned for ticker '{ticker}' (interval={interval}).")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [str(c).lower() for c in raw.columns]
    raw.index.name = "date"

    if use_cache:
        raw.to_parquet(cache_file)

    return raw


def load_watchlist(path: str) -> list[str]:
    """Read a newline-separated ticker list, ignoring blanks and #comments."""
    tickers = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tickers.append(line.upper())
    return tickers
