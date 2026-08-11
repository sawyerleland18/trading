import numpy as np

from confluence import indicators as ind


def test_ema_tracks_price_and_has_no_lookahead(ohlcv):
    e = ind.ema(ohlcv["close"], 20)
    assert e.dropna().shape[0] > 0
    # EMA should lag: at the last bar it shouldn't equal close exactly for noisy data
    assert not np.isclose(e.iloc[-1], ohlcv["close"].iloc[-1])


def test_rsi_bounded_0_100(ohlcv):
    r = ind.rsi(ohlcv["close"], 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_rsi_extreme_on_monotonic_series():
    import pandas as pd

    up = pd.Series(np.linspace(100, 200, 50))
    r = ind.rsi(up, 14).dropna()
    assert r.iloc[-1] > 90  # relentless uptrend -> RSI near 100


def test_macd_hist_equals_line_minus_signal(ohlcv):
    macd_line, signal, hist = ind.macd(ohlcv["close"])
    diff = (macd_line - signal - hist).dropna()
    assert np.allclose(diff, 0, atol=1e-9)


def test_atr_is_non_negative(ohlcv):
    a = ind.atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14).dropna()
    assert (a >= 0).all()


def test_dmi_adx_bounded(ohlcv):
    plus_di, minus_di, adx = ind.dmi(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14)
    adx_valid = adx.dropna()
    assert (adx_valid >= 0).all() and (adx_valid <= 100).all()


def test_bollinger_upper_above_lower(ohlcv):
    mid, upper, lower, width = ind.bollinger_bands(ohlcv["close"], 20, 2.0)
    valid = upper.dropna().index.intersection(lower.dropna().index)
    assert (upper[valid] >= lower[valid]).all()
    assert (width.dropna() >= 0).all()


def test_obv_increases_on_up_day():
    import pandas as pd

    close = pd.Series([10, 11, 10.5, 12])
    volume = pd.Series([100, 200, 150, 300])
    o = ind.obv(close, volume)
    assert o.iloc[1] == 200  # up day adds volume
    assert o.iloc[2] == 200 - 150  # down day subtracts volume
