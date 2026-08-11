import numpy as np

from confluence.backtest import run_backtest, trades_to_frame
from confluence.metrics import summarize
from confluence.signals import ConfluenceParams


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
