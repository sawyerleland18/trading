from confluence.signals import ConfluenceParams, add_htf_filter, compute_breadth, compute_confluence


def test_compute_confluence_adds_expected_columns(ohlcv):
    out = compute_confluence(ohlcv)
    expected = {
        "trend_pts", "momentum_pts", "volume_pts", "vola_pts", "bb_pts", "long_term_pts",
        "net_score", "regime", "long_signal", "short_signal",
        "exit_long_signal", "exit_short_signal", "regime_bullish", "regime_bearish",
    }
    assert expected.issubset(out.columns)


def test_regime_bullish_bearish_are_mutually_exclusive(ohlcv):
    out = compute_confluence(ohlcv)
    valid = out.dropna(subset=["long_term_pts"])
    # long_term_pts is a sum of +-12 and +-13, so it's never exactly 0 —
    # every bar is either bullish or bearish, never both or neither.
    assert (valid["regime_bullish"] != valid["regime_bearish"]).all()
    assert (valid["regime_bullish"] == (valid["long_term_pts"] > 0)).all()


def test_trending_column_matches_adx_threshold(ohlcv):
    p = ConfluenceParams()
    out = compute_confluence(ohlcv, p)
    valid = out.dropna(subset=["adx"])
    assert (valid["trending"] == (valid["adx"] > p.adx_thresh)).all()


def test_net_score_bounded(ohlcv):
    out = compute_confluence(ohlcv)
    valid = out["net_score"].dropna()
    assert (valid >= -100).all() and (valid <= 100).all()


def test_component_scores_within_declared_weights(ohlcv):
    out = compute_confluence(ohlcv)
    assert out["trend_pts"].abs().max() <= 20
    assert out["momentum_pts"].abs().max() <= 20
    assert out["volume_pts"].abs().max() <= 15
    assert out["vola_pts"].abs().max() <= 10
    assert out["bb_pts"].abs().max() <= 10
    assert out["long_term_pts"].abs().max() <= 25


def test_component_weights_sum_to_100():
    """The declared per-factor weight caps must sum to exactly the net_score range."""
    caps = {"trend": 20, "momentum": 20, "volume": 15, "vola": 10, "bb": 10, "long_term": 25}
    assert sum(caps.values()) == 100


def test_regime_matches_thresholds(ohlcv):
    p = ConfluenceParams()
    out = compute_confluence(ohlcv, p)
    strong_buy = out[out["regime"] == "STRONG_BUY"]
    assert (strong_buy["net_score"] >= p.strong_buy_level).all()
    strong_sell = out[out["regime"] == "STRONG_SELL"]
    assert (strong_sell["net_score"] <= p.strong_sell_level).all()


def test_uptrend_biases_score_positive(trending_ohlcv):
    out = compute_confluence(trending_ohlcv)
    tail = out["net_score"].dropna().iloc[-100:]
    assert tail.mean() > 0
    assert out["long_signal"].sum() >= 1


def test_long_term_regime_positive_in_sustained_uptrend(trending_ohlcv):
    """The SMA200-timing + 12-1mo momentum factor should lean bullish once
    a sustained uptrend has had enough history to clear both lookbacks."""
    out = compute_confluence(trending_ohlcv)
    tail = out["long_term_pts"].dropna().iloc[-100:]
    assert tail.mean() > 0
    assert out["ts_momentum"].dropna().iloc[-100:].gt(0).mean() > 0.5


def test_ema_cross_columns_exist_and_are_mutually_exclusive(ohlcv):
    out = compute_confluence(ohlcv)
    assert {"ema_cross_up", "ema_cross_down"}.issubset(out.columns)
    assert not (out["ema_cross_up"] & out["ema_cross_down"]).any()


def test_ema_cross_confluence_signals_only_fire_on_the_crossover_bar(trending_ohlcv):
    p = ConfluenceParams(trigger_mode="ema_cross_confluence")
    out = compute_confluence(trending_ohlcv, p)
    assert out["long_signal"].sum() >= 1
    # every long signal must land exactly on an ema_cross_up bar
    assert (out.loc[out["long_signal"], "ema_cross_up"]).all()


def test_score_threshold_trigger_mode_ignores_ema_crossovers(trending_ohlcv):
    p = ConfluenceParams(trigger_mode="score_threshold_cross")
    out = compute_confluence(trending_ohlcv, p)
    prev_score = out["net_score"].shift(1)
    expected = (prev_score <= p.buy_threshold) & (out["net_score"] > p.buy_threshold)
    assert (out["long_signal"] == expected.fillna(False)).all()


def test_add_htf_filter_columns(ohlcv):
    out = add_htf_filter(ohlcv, rule="W")
    assert "htf_bullish" in out.columns and "htf_bearish" in out.columns
    # a bar can't be both bullish and bearish at once
    assert not (out["htf_bullish"] & out["htf_bearish"]).any()


def test_compute_breadth_matches_close_vs_sma(ohlcv):
    breadth = compute_breadth(ohlcv, sma_len=50)
    assert {"breadth_bullish", "breadth_bearish"}.issubset(breadth.columns)
    sma = ohlcv["close"].rolling(50).mean()
    valid = sma.dropna().index
    assert (breadth.loc[valid, "breadth_bullish"] == (ohlcv.loc[valid, "close"] > sma.loc[valid])).all()
    # mutually exclusive wherever the SMA is defined
    assert not (breadth.loc[valid, "breadth_bullish"] & breadth.loc[valid, "breadth_bearish"]).any()
