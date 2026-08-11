from confluence.signals import ConfluenceParams, add_htf_filter, compute_confluence


def test_compute_confluence_adds_expected_columns(ohlcv):
    out = compute_confluence(ohlcv)
    expected = {
        "trend_pts", "momentum_pts", "volume_pts", "vola_pts", "bb_pts",
        "net_score", "regime", "long_signal", "short_signal",
        "exit_long_signal", "exit_short_signal",
    }
    assert expected.issubset(out.columns)


def test_net_score_bounded(ohlcv):
    out = compute_confluence(ohlcv)
    valid = out["net_score"].dropna()
    assert (valid >= -100).all() and (valid <= 100).all()


def test_component_scores_within_declared_weights(ohlcv):
    out = compute_confluence(ohlcv)
    assert out["trend_pts"].abs().max() <= 25
    assert out["momentum_pts"].abs().max() <= 25
    assert out["volume_pts"].abs().max() <= 20
    assert out["vola_pts"].abs().max() <= 15
    assert out["bb_pts"].abs().max() <= 15


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


def test_add_htf_filter_columns(ohlcv):
    out = add_htf_filter(ohlcv, rule="W")
    assert "htf_bullish" in out.columns and "htf_bearish" in out.columns
    # a bar can't be both bullish and bearish at once
    assert not (out["htf_bullish"] & out["htf_bearish"]).any()
