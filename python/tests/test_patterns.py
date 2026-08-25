import numpy as np
import pandas as pd

from confluence.patterns import detect_chart_patterns, find_pivots


def _flat_ohlcv(close: np.ndarray) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=len(close))
    return pd.DataFrame(
        {"open": close, "high": close + 0.3, "low": close - 0.3, "close": close,
         "volume": np.full(len(close), 1_000_000.0)},
        index=dates,
    )


def _double_top_series() -> pd.DataFrame:
    n = 60
    close = np.full(n, 100.0)
    close[0:11] = np.linspace(100, 110, 11)
    close[10:21] = np.linspace(110, 100, 11)
    close[20:31] = np.linspace(100, 109, 11)   # second peak within 3% tolerance of 110
    close[30:41] = np.linspace(109, 95, 11)    # breaks below the ~100 trough
    close[40:] = 95.0
    return _flat_ohlcv(close)


def _double_bottom_series() -> pd.DataFrame:
    n = 60
    close = np.full(n, 100.0)
    close[0:11] = np.linspace(100, 90, 11)
    close[10:21] = np.linspace(90, 100, 11)
    close[20:31] = np.linspace(100, 91, 11)    # second trough within tolerance of 90
    close[30:41] = np.linspace(91, 105, 11)    # breaks above the ~100 peak
    close[40:] = 105.0
    return _flat_ohlcv(close)


def _head_shoulders_series() -> pd.DataFrame:
    n = 90
    close = np.full(n, 100.0)
    close[0:10] = np.linspace(100, 108, 10)    # left shoulder
    close[9:20] = np.linspace(108, 100, 11)    # trough 1
    close[19:30] = np.linspace(100, 116, 11)   # head (clearly higher)
    close[29:40] = np.linspace(116, 100, 11)   # trough 2
    close[39:50] = np.linspace(100, 107, 11)   # right shoulder (comparable to left)
    close[49:60] = np.linspace(107, 90, 11)    # breaks below the neckline
    close[60:] = 90.0
    return _flat_ohlcv(close)


def _pure_uptrend_series(n: int = 300, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.008, n)))
    return _flat_ohlcv(close)


def test_find_pivots_marks_local_extrema():
    df = _double_top_series()
    pivot_high, pivot_low = find_pivots(df, left=3, right=3)
    assert pivot_high.any() and pivot_low.any()
    # every marked pivot high really is the max of its own left/right window
    high = df["high"].to_numpy()
    for i in np.where(pivot_high.to_numpy())[0]:
        window = high[max(0, i - 3): i + 4]
        assert high[i] == window.max()


def test_double_top_detected_exactly_once_no_other_patterns():
    df = _double_top_series()
    result = detect_chart_patterns(df, left=3, right=3, tolerance_pct=0.03, trough_depth_pct=0.02, breakout_window=15)
    assert result["double_top_confirmed"].sum() == 1
    assert result["double_bottom_confirmed"].sum() == 0
    assert result["head_shoulders_confirmed"].sum() == 0
    assert result["inverse_head_shoulders_confirmed"].sum() == 0


def test_double_bottom_detected_exactly_once_no_other_patterns():
    df = _double_bottom_series()
    result = detect_chart_patterns(df, left=3, right=3, tolerance_pct=0.03, trough_depth_pct=0.02, breakout_window=15)
    assert result["double_bottom_confirmed"].sum() == 1
    assert result["double_top_confirmed"].sum() == 0
    assert result["head_shoulders_confirmed"].sum() == 0
    assert result["inverse_head_shoulders_confirmed"].sum() == 0


def test_head_and_shoulders_detected_exactly_once():
    df = _head_shoulders_series()
    result = detect_chart_patterns(df, left=3, right=3, tolerance_pct=0.03, trough_depth_pct=0.02, breakout_window=15)
    assert result["head_shoulders_confirmed"].sum() == 1
    assert result["inverse_head_shoulders_confirmed"].sum() == 0


def test_pattern_confirms_after_the_completing_pivot_is_knowable():
    # No lookahead: the confirmation bar must be at or after the second
    # peak's own bar plus `right` (when that pivot first becomes knowable).
    df = _double_top_series()
    right = 3
    result = detect_chart_patterns(df, left=3, right=right, tolerance_pct=0.03, trough_depth_pct=0.02, breakout_window=15)
    confirmed_positions = np.where(result["double_top_confirmed"].to_numpy())[0]
    assert len(confirmed_positions) == 1
    # second peak is at index 30 (see _double_top_series) - not knowable before index 30+right
    assert confirmed_positions[0] >= 30 + right


def test_no_patterns_fire_on_flat_line():
    close = np.full(100, 50.0)
    df = _flat_ohlcv(close)
    result = detect_chart_patterns(df)
    assert result.to_numpy().sum() == 0


def test_pure_trend_does_not_produce_a_firehose_of_false_positives():
    # Real signal, not zero, but bounded - random walk data will occasionally
    # form shapes that pass the geometric tolerance checks by chance, and
    # that's expected. What would be a red flag is every bar firing.
    df = _pure_uptrend_series()
    result = detect_chart_patterns(df)
    total = int(result.to_numpy().sum())
    assert total < len(df) * 0.1
