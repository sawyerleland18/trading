"""Historical OHLCV data loading with local caching.

Uses yfinance (no API key required) as the default source. In network
environments where Yahoo Finance blocks datacenter/cloud IPs (a very
common problem for yfinance on cloud servers), an API-key-based source
can be used instead, checked in this priority order:

  1. TIINGO_API_KEY  — free tier includes full daily history, already
     split+dividend adjusted. Preferred when available.
  2. ALPHAVANTAGE_API_KEY — free tier only returns ~100 recent daily bars
     (their full-history endpoint is now premium-only), so this is mostly
     useful for short lookbacks, not multi-year backtests. Raw prices are
     back-adjusted for splits here, but not dividends.

Data is cached to python/data_cache/ as parquet so repeated
backtests/optimizations don't re-download. Swap in another data source
later (a broker API, a paid vendor, crypto exchange via ccxt, etc.) by
adding a new function with the same return contract: a DataFrame indexed
by tz-naive datetime with lower case columns open, high, low, close, volume.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
TIINGO_BASE_URL = "https://api.tiingo.com/tiingo/daily"


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
    """Fetch OHLCV history for `ticker`, normalized to lower-case columns.

    Source is chosen by which API key is set in the environment — see the
    module docstring for priority order — falling back to yfinance if
    neither is set. Raises RuntimeError with a clear message if the source
    isn't installed/configured or the download fails — callers (CLI, tests)
    should surface that directly instead of guessing why an empty frame
    came back.
    """
    cache_file = _cache_path(ticker, interval)
    if use_cache and not force_refresh and cache_file.exists():
        df = pd.read_parquet(cache_file)
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        return df

    # Always download the ticker's full available history and cache that —
    # a single API call regardless of the requested start/end — then filter
    # locally. This matters most for the API-key sources, where free-tier
    # requests are rate-limited, so a narrower `start` shouldn't cost an
    # extra call.
    tiingo_key = os.environ.get("TIINGO_API_KEY")
    av_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if tiingo_key:
        full = _load_tiingo(ticker, tiingo_key, interval=interval)
    elif av_key:
        full = _load_alpha_vantage(ticker, av_key, interval=interval)
    else:
        full = _load_yfinance(ticker, start=None, end=None, interval=interval)

    if use_cache:
        full.to_parquet(cache_file)

    df = full
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def _load_yfinance(ticker: str, start: str | None, end: str | None, interval: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "yfinance is required for live data downloads. Install it with "
            "`pip install -r python/requirements.txt`."
        ) from exc

    if start is None and end is None:
        # yf.download defaults to only 1mo of history when no start/end is
        # given — request the full available range explicitly instead.
        raw = yf.download(ticker, period="max", interval=interval, progress=False, auto_adjust=True)
    else:
        raw = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True)
    if raw.empty:
        raise RuntimeError(f"No data returned for ticker '{ticker}' (interval={interval}).")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [str(c).lower() for c in raw.columns]
    raw.index.name = "date"
    return raw


def _load_tiingo(ticker: str, api_key: str, interval: str) -> pd.DataFrame:
    """Fetch daily OHLCV from Tiingo, using their already split+dividend
    adjusted columns (adjOpen/adjHigh/adjLow/adjClose/adjVolume) — same
    adjustment convention as yfinance's auto_adjust=True."""
    import requests

    if interval != "1d":
        raise RuntimeError("Tiingo source currently only supports interval='1d'.")

    url = f"{TIINGO_BASE_URL}/{ticker}/prices"
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
    for attempt in range(3):
        resp = requests.get(url, params={"format": "json"}, headers=headers, timeout=30)
        if resp.status_code == 429:
            if attempt < 2:
                time.sleep(15)
                continue
            raise RuntimeError(f"Tiingo rate-limited the request for '{ticker}' after retries.")
        if resp.status_code == 404:
            raise RuntimeError(f"Tiingo has no data for ticker '{ticker}' (404).")
        resp.raise_for_status()
        records = resp.json()
        break

    if not records:
        raise RuntimeError(f"No data returned for ticker '{ticker}' from Tiingo.")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.set_index("date").sort_index()
    df = df.rename(columns={
        "adjOpen": "open", "adjHigh": "high", "adjLow": "low",
        "adjClose": "close", "adjVolume": "volume",
    })
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _alpha_vantage_get(params: dict, api_key: str, ticker: str) -> dict:
    import requests

    params = {**params, "apikey": api_key}
    for attempt in range(3):
        resp = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if "Note" in payload or "Information" in payload:
            # Free-tier rate limit hit (5/min or daily cap) — back off and retry once or twice.
            if attempt < 2:
                time.sleep(15)
                continue
            raise RuntimeError(
                f"Alpha Vantage rate-limited the request for '{ticker}': "
                f"{payload.get('Note') or payload.get('Information')}"
            )
        if "Error Message" in payload:
            raise RuntimeError(f"Alpha Vantage error for '{ticker}': {payload['Error Message']}")
        return payload
    raise RuntimeError(f"Alpha Vantage: no usable response for '{ticker}' after retries.")


def _load_alpha_vantage(ticker: str, api_key: str, interval: str) -> pd.DataFrame:
    """Fetch daily OHLCV from Alpha Vantage's free TIME_SERIES_DAILY endpoint and
    back-adjust for stock splits (that endpoint returns raw as-traded prices, so
    without this a split shows up as a fake multi-day price cliff).

    Note: this does NOT adjust for dividends (the free tier's dividend/split-
    adjusted endpoint is now premium-only), so total-return figures (CAGR) will
    be very slightly understated relative to a fully adjusted series — the gap
    is roughly the ticker's dividend yield times the years backtested.
    """
    if interval != "1d":
        raise RuntimeError("Alpha Vantage source currently only supports interval='1d'.")

    payload = _alpha_vantage_get(
        {"function": "TIME_SERIES_DAILY", "symbol": ticker, "outputsize": "full"}, api_key, ticker
    )
    series = payload.get("Time Series (Daily)")
    if not series:
        raise RuntimeError(f"No data returned for ticker '{ticker}' from Alpha Vantage.")

    df = pd.DataFrame.from_dict(series, orient="index")
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    df = df.rename(columns={
        "1. open": "open", "2. high": "high", "3. low": "low",
        "4. close": "close", "5. volume": "volume",
    }).astype(float)
    df = df.sort_index()

    splits_payload = _alpha_vantage_get({"function": "SPLITS", "symbol": ticker}, api_key, ticker)
    splits = splits_payload.get("data", [])
    df = _apply_split_adjustment(df, splits)
    return df


def _apply_split_adjustment(df: pd.DataFrame, splits: list[dict]) -> pd.DataFrame:
    """Back-adjust raw OHLCV for a list of {"effective_date", "split_factor"} events,
    same convention as yfinance's auto_adjust: prices before the split are divided
    by the factor, volume is multiplied by it."""
    events = []
    for s in splits:
        try:
            factor = float(s["split_factor"])
        except (KeyError, ValueError, TypeError):
            continue
        if factor and factor != 1.0:
            events.append((pd.Timestamp(s["effective_date"]), factor))
    # Apply most-recent split first so earlier periods correctly accumulate
    # the product of every split that happened after them.
    for effective_date, factor in sorted(events, key=lambda e: e[0], reverse=True):
        mask = df.index < effective_date
        df.loc[mask, ["open", "high", "low", "close"]] /= factor
        df.loc[mask, "volume"] *= factor
    return df


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
