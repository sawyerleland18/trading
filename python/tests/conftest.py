"""Shared pytest fixtures — synthetic OHLCV data so tests never hit the network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_synthetic_ohlcv(n: int = 800, seed: int = 7, drift: float = 0.0004, vol: float = 0.015) -> pd.DataFrame:
    """Deterministic synthetic daily OHLCV: a geometric random walk with drift.

    Good enough to exercise every code path (indicators, scoring, backtest
    loop) without requiring network access to yfinance.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-02", periods=n)
    log_returns = rng.normal(drift, vol, size=n)
    close = 100 * np.exp(np.cumsum(log_returns))

    daily_range = np.abs(rng.normal(0, vol * 0.6, size=n)) * close
    high = close + daily_range * rng.uniform(0.3, 1.0, size=n)
    low = close - daily_range * rng.uniform(0.3, 1.0, size=n)
    open_ = low + (high - low) * rng.uniform(0.0, 1.0, size=n)
    volume = rng.integers(1_000_000, 5_000_000, size=n).astype(float)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df.index.name = "date"
    # guard against any inverted high/low from the random construction above
    df["high"] = df[["high", "low", "open", "close"]].max(axis=1)
    df["low"] = df[["high", "low", "open", "close"]].min(axis=1)
    return df


@pytest.fixture
def ohlcv():
    return make_synthetic_ohlcv()


@pytest.fixture
def trending_ohlcv():
    """Strong, low-noise uptrend — should reliably produce long signals."""
    return make_synthetic_ohlcv(n=600, seed=3, drift=0.0025, vol=0.006)
