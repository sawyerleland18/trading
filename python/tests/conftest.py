"""Shared pytest fixtures — synthetic OHLCV data so tests never hit the network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_synthetic_ohlcv(
    n: int = 800,
    seed: int = 7,
    drift: float = 0.0004,
    vol: float = 0.015,
    cycle_amp: float = 0.0,
    cycle_period: int = 40,
) -> pd.DataFrame:
    """Deterministic synthetic daily OHLCV: a geometric random walk with drift,
    optionally with a sinusoidal cyclical component layered on top.

    The cyclical component (`cycle_amp` > 0) produces repeated pullback/rally
    swings on top of the drift, which is what actually generates EMA
    crossover events — a pure monotonic drift never crosses back over its
    own EMAs after the initial warmup, which isn't representative of real
    price action. Good enough to exercise every code path (indicators,
    scoring, backtest loop) without requiring network access to yfinance.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-02", periods=n)
    t = np.arange(n)
    cyclical = cycle_amp * np.sin(2 * np.pi * t / cycle_period)
    cyclical_returns = np.diff(np.concatenate([[0.0], cyclical]))
    log_returns = rng.normal(drift, vol, size=n) + cyclical_returns
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
    """Net uptrend with cyclical pullback/rally swings — reliably produces
    both real EMA crossover events and an overall positive score bias,
    unlike a pure monotonic drift (which never re-crosses its own EMAs)."""
    return make_synthetic_ohlcv(n=800, seed=11, drift=0.0006, vol=0.012, cycle_amp=0.02, cycle_period=40)
