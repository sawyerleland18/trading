"""Pure pandas/numpy technical indicator implementations.

No dependency on TA-Lib or the `ta` package (both have finicky install
requirements) — every indicator here is implemented from its textbook
formula so behaviour is fully understood and easy to keep in sync with
the Pine Script mirror.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential moving average, seeded like TradingView's ta.ema (RMA-style seed)."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average (used internally by RSI/ADX/ATR), matches ta.rma."""
    alpha = 1.0 / length
    return series.ewm(alpha=alpha, adjust=False, min_periods=length).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    return rma(true_range(high, low, close), length)


def dmi(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    """Directional Movement Index -> (+DI, -DI, ADX)."""
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    tr_rma = rma(true_range(high, low, close), length)
    plus_di = 100 * rma(plus_dm, length) / tr_rma.replace(0.0, np.nan)
    minus_di = 100 * rma(minus_dm, length) / tr_rma.replace(0.0, np.nan)

    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)) * 100
    adx = rma(dx.fillna(0.0), length)
    return plus_di, minus_di, adx


def bollinger_bands(close: pd.Series, length: int = 20, mult: float = 2.0):
    mid = sma(close, length)
    dev = close.rolling(length, min_periods=length).std(ddof=0)
    upper = mid + mult * dev
    lower = mid - mult * dev
    width = (upper - lower) / mid
    return mid, upper, lower, width


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).fillna(0.0).cumsum()
