import numpy as np
import pytest

from confluence.backtest import run_backtest, trades_to_frame
from confluence.metrics import summarize
from confluence.signals import ConfluenceParams, compute_breadth


def test_run_backtest_returns_full_length_equity_curve(ohlcv):
    equity, trades = run_backtest(ohlcv)
    assert len(equity) == len(ohlcv)
    assert equity.index.equals(ohlcv.index)


def test_equity_curve_has_no_nans_or_non_positive_after_warmup(ohlcv):
    equity, _ = run_backtest(ohlcv)
    warm = equity.iloc[210:]  # past the 200-EMA warmup window
    assert not warm.isna().any()
    assert (warm > 0).all()


def test_trades_have_consistent_pnl_sign(trending_ohlcv):
    _, trades = run_backtest(trending_ohlcv)
    trade_df = trades_to_frame(trades)
    if len(trade_df):
        for _, row in trade_df.iterrows():
            expected_sign = np.sign(
                (row["exit_price"] - row["entry_price"]) if row["side"] == "long"
                else (row["entry_price"] - row["exit_price"])
            )
            assert np.sign(row["pnl"]) == expected_sign or row["pnl"] == 0


def test_summarize_runs_on_backtest_output(ohlcv):
    equity, trades = run_backtest(ohlcv)
    trade_df = trades_to_frame(trades)
    summary = summarize(equity, trade_df["pnl_pct"])
    assert set(["cagr_pct", "max_drawdown_pct", "sharpe", "num_trades", "win_rate_pct"]).issubset(summary)
    assert summary["max_drawdown_pct"] <= 0


def test_no_short_trades_when_disabled(ohlcv):
    _, trades = run_backtest(ohlcv, allow_short=False)
    assert all(t.side == "long" for t in trades)


def test_no_long_trades_when_disabled(ohlcv):
    _, trades = run_backtest(ohlcv, allow_long=False)
    assert all(t.side == "short" for t in trades)


def test_custom_params_change_trade_count(ohlcv):
    loose = ConfluenceParams(buy_threshold=10, sell_threshold=-10)
    strict = ConfluenceParams(buy_threshold=80, sell_threshold=-80)
    _, loose_trades = run_backtest(ohlcv, params=loose)
    _, strict_trades = run_backtest(ohlcv, params=strict)
    assert len(loose_trades) >= len(strict_trades)


def test_regime_filter_blocks_entries_against_the_long_term_trend(trending_ohlcv):
    # trending_ohlcv has a strong positive drift, so after the 200-SMA/
    # momentum warmup period the long-term regime should read bullish for
    # most of the series — the filter should veto (or at least sharply cut)
    # new shorts relative to running with it off.
    from confluence.signals import compute_confluence

    _, unfiltered_trades = run_backtest(trending_ohlcv, use_regime_filter=False)
    _, filtered_trades = run_backtest(trending_ohlcv, use_regime_filter=True)

    computed = compute_confluence(trending_ohlcv)
    bullish_share = computed["regime_bullish"].dropna().mean()
    assert bullish_share > 0.5  # sanity check on the fixture's own drift

    unfiltered_shorts = sum(1 for t in unfiltered_trades if t.side == "short")
    filtered_shorts = sum(1 for t in filtered_trades if t.side == "short")
    assert filtered_shorts <= unfiltered_shorts

    # Every trade that *does* enter under the filter must agree with the
    # long-term regime reading at its own entry bar.
    for t in filtered_trades:
        bullish_at_entry = computed.loc[t.entry_date, "regime_bullish"]
        assert bullish_at_entry if t.side == "long" else not bullish_at_entry


def test_chop_filter_only_enters_when_trending(ohlcv):
    from confluence.signals import compute_confluence

    _, unfiltered_trades = run_backtest(ohlcv, use_chop_filter=False)
    _, filtered_trades = run_backtest(ohlcv, use_chop_filter=True)

    assert len(filtered_trades) <= len(unfiltered_trades)

    computed = compute_confluence(ohlcv)
    for t in filtered_trades:
        assert computed.loc[t.entry_date, "trending"]


def test_stop_and_target_stay_fixed_for_the_life_of_a_trade(trending_ohlcv):
    """Regression test: stop/target must be locked to the ATR *at entry*, not
    recomputed from each bar's live ATR while the position is held — matches
    the Pine script, which assigns longSL/longTP with `:=` exactly once, in
    the entry block."""
    _, trades = run_backtest(trending_ohlcv, params=ConfluenceParams(atr_mult_sl=1.5, atr_mult_tp=3.0))
    assert len(trades) >= 1
    for t in trades:
        assert t.entry_atr > 0
        if t.exit_reason == "take_profit":
            expected = t.entry_price + t.entry_atr * 3.0 if t.side == "long" else t.entry_price - t.entry_atr * 3.0
            assert t.exit_price == expected
        elif t.exit_reason == "stop_loss":
            expected = t.entry_price - t.entry_atr * 1.5 if t.side == "long" else t.entry_price + t.entry_atr * 1.5
            assert t.exit_price == expected


def test_slippage_worsens_entry_fills(trending_ohlcv):
    # Entries happen on the signal bar regardless of slippage (slippage only
    # changes the *fill price*, not the entry decision or its timing), so
    # trade-for-trade comparison by entry_date is safe here.
    _, clean_trades = run_backtest(trending_ohlcv, slippage_pct=0.0)
    _, slipped_trades = run_backtest(trending_ohlcv, slippage_pct=0.5)

    assert len(slipped_trades) == len(clean_trades)  # same signals, only fills differ
    clean_by_date = {t.entry_date: t for t in clean_trades}
    for slipped_t in slipped_trades:
        clean_t = clean_by_date[slipped_t.entry_date]
        if slipped_t.side == "long":
            assert slipped_t.entry_price >= clean_t.entry_price  # paid more to get in
        else:
            assert slipped_t.entry_price <= clean_t.entry_price  # received less to get in


def test_zero_slippage_is_a_true_no_op(trending_ohlcv):
    equity_a, trades_a = run_backtest(trending_ohlcv, slippage_pct=0.0)
    equity_b, trades_b = run_backtest(trending_ohlcv)  # default
    assert equity_a.equals(equity_b)
    assert [t.entry_price for t in trades_a] == [t.entry_price for t in trades_b]


def test_breadth_filter_requires_breadth_argument(ohlcv):
    with pytest.raises(ValueError):
        run_backtest(ohlcv, use_breadth_filter=True)


def test_breadth_filter_blocks_entries_against_reference_ticker_trend(ohlcv, trending_ohlcv):
    # Use trending_ohlcv (strong positive drift) as a stand-in "SPY" breadth
    # reference and ohlcv (the plain fixture) as the traded ticker - two
    # genuinely independent series, so this isn't just checking a ticker
    # against its own regime (that's the separate regime-filter test).
    breadth = compute_breadth(trending_ohlcv, sma_len=50)
    bullish_share = breadth["breadth_bullish"].dropna().mean()
    assert bullish_share > 0.5  # sanity check on the fixture's own drift

    _, unfiltered_trades = run_backtest(ohlcv, use_breadth_filter=False)
    _, filtered_trades = run_backtest(ohlcv, breadth=breadth, use_breadth_filter=True)

    assert len(filtered_trades) <= len(unfiltered_trades)
    for t in filtered_trades:
        aligned = breadth.reindex([t.entry_date], method="ffill").iloc[0]
        assert aligned["breadth_bullish"] if t.side == "long" else aligned["breadth_bearish"]


def test_strength_sizing_scales_first_trade_qty_by_conviction(trending_ohlcv):
    # Compare the very first trade only - before any cash divergence has had
    # a chance to accumulate between the two runs, both start from the same
    # initial_capital, so qty should differ by *exactly* the |net_score|/100
    # ratio at that entry bar (risk_dist from ATR is identical either way,
    # unaffected by sizing).
    from confluence.signals import compute_confluence

    _, flat_trades = run_backtest(trending_ohlcv, use_strength_sizing=False)
    _, scaled_trades = run_backtest(trending_ohlcv, use_strength_sizing=True)
    assert flat_trades and scaled_trades
    assert flat_trades[0].entry_date == scaled_trades[0].entry_date  # same signal timing

    computed = compute_confluence(trending_ohlcv)
    entry_score = computed.loc[flat_trades[0].entry_date, "net_score"]
    expected_mult = abs(entry_score) / 100.0
    assert scaled_trades[0].qty == pytest.approx(flat_trades[0].qty * expected_mult)


def test_strength_sizing_never_exceeds_flat_sizing(trending_ohlcv):
    # |net_score| is always <= 100, so the strength-scaled multiplier is
    # always <= 1.0 - scaled qty should never exceed flat-sizing qty, for
    # every trade the two runs have in common by entry date.
    _, flat_trades = run_backtest(trending_ohlcv, use_strength_sizing=False)
    _, scaled_trades = run_backtest(trending_ohlcv, use_strength_sizing=True)
    flat_by_date = {t.entry_date: t for t in flat_trades}
    for scaled_t in scaled_trades:
        if scaled_t.entry_date in flat_by_date:
            assert scaled_t.qty <= flat_by_date[scaled_t.entry_date].qty + 1e-9


def test_strength_sizing_off_is_a_true_no_op(trending_ohlcv):
    equity_a, trades_a = run_backtest(trending_ohlcv, use_strength_sizing=False)
    equity_b, trades_b = run_backtest(trending_ohlcv)  # default
    assert equity_a.equals(equity_b)
    assert [t.qty for t in trades_a] == [t.qty for t in trades_b]
