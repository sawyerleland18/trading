import numpy as np
import pandas as pd
import pytest

from confluence.backtest import run_backtest, trades_to_frame
from confluence.metrics import summarize
from confluence.portfolio import _trailing_correlation, run_portfolio_backtest
from confluence.signals import ConfluenceParams
from tests.conftest import make_synthetic_ohlcv


def test_single_ticker_portfolio_matches_single_asset_backtest(trending_ohlcv):
    # With only one ticker in the book, sizing off "total account equity"
    # (portfolio.py) reduces to sizing off "cash when flat" (backtest.py) -
    # the two engines should agree almost exactly. This is the key
    # consistency check that the shared-capital machinery doesn't silently
    # change behavior in the trivial single-asset case.
    equity_single, trades_single = run_backtest(trending_ohlcv, initial_capital=10_000.0)
    trade_df_single = trades_to_frame(trades_single)

    equity_port, trades_port = run_portfolio_backtest({"X": trending_ohlcv}, initial_capital=10_000.0)

    assert len(trades_port) == len(trade_df_single)
    assert equity_port.iloc[-1] == pytest.approx(equity_single.iloc[-1], rel=1e-6)
    for (_, row_p), (_, row_s) in zip(trades_port.iterrows(), trade_df_single.iterrows()):
        assert row_p["entry_date"] == row_s["entry_date"]
        assert row_p["qty"] == pytest.approx(row_s["qty"], rel=1e-6)


def test_summarize_runs_on_portfolio_output(trending_ohlcv):
    equity, trades_df = run_portfolio_backtest({"X": trending_ohlcv})
    summary = summarize(equity, trades_df["pnl_pct"] if len(trades_df) else pd.Series(dtype=float))
    assert set(["cagr_pct", "max_drawdown_pct", "sharpe", "num_trades"]).issubset(summary)


def test_shared_capital_constrains_simultaneous_entries():
    # Two tickers with IDENTICAL price action fire identical signals on
    # identical days - with real shared capital, the combined notional of
    # whatever opens on the very first entry day cannot exceed what was
    # actually in the account, even though each ticker's own signal would
    # "want" a full-size position as if it had the whole account to itself.
    df = make_synthetic_ohlcv(n=500, seed=11, drift=0.0006, vol=0.012, cycle_amp=0.02, cycle_period=40)
    price_data = {"A": df, "B": df.copy()}
    initial_capital = 10_000.0
    equity, trades_df = run_portfolio_backtest(price_data, initial_capital=initial_capital)

    assert len(trades_df) > 0
    first_day = trades_df["entry_date"].min()
    same_day = trades_df[trades_df["entry_date"] == first_day]
    total_notional = (same_day["qty"] * same_day["entry_price"]).sum()
    assert total_notional <= initial_capital * 1.001


def test_max_concurrent_positions_cap_is_respected():
    # Four differently-seeded trending tickers so entries land on different,
    # overlapping days. With max_concurrent_positions=1, no two trades'
    # [entry_date, exit_date) windows may overlap, regardless of ticker.
    price_data = {
        f"T{i}": make_synthetic_ohlcv(n=500, seed=seed, drift=0.0006, vol=0.012, cycle_amp=0.02, cycle_period=40)
        for i, seed in enumerate([11, 23, 37, 41])
    }
    _, trades_df = run_portfolio_backtest(price_data, max_concurrent_positions=1)
    assert len(trades_df) > 1  # otherwise this test can't actually check overlap

    intervals = []
    for _, row in trades_df.sort_values("entry_date").iterrows():
        end = row["exit_date"] if pd.notna(row["exit_date"]) else pd.Timestamp.max
        intervals.append((row["entry_date"], end))

    for i in range(len(intervals) - 1):
        # Sorted by entry_date, so the next entry must be at/after the
        # current interval's exit for there to be no overlap.
        assert intervals[i + 1][0] >= intervals[i][1]


def test_correlation_aware_sizing_shrinks_the_second_correlated_entry():
    # Two IDENTICAL tickers. Note risk-based position sizing here is
    # proportional to equity regardless of its absolute size (risk_dollars =
    # equity * risk_per_trade_pct%, qty = risk_dollars / (atr * atr_mult_sl))
    # - so scaling initial_capital up alone never "escapes" the shared-cash
    # constraint (a full-size position's notional is a roughly constant
    # *fraction* of equity, whatever that equity is). To isolate the
    # correlation-aware shrink from that separate capital-constraint effect
    # (covered by the dedicated test above), risk_per_trade_pct is turned
    # down here so a single position's notional is a small enough slice of
    # equity that two of them comfortably fit in cash.
    df = make_synthetic_ohlcv(n=500, seed=11, drift=0.0006, vol=0.012, cycle_amp=0.02, cycle_period=40)
    price_data = {"A": df, "B": df.copy()}
    params = ConfluenceParams(risk_per_trade_pct=0.1)
    capital = 100_000.0
    corr_floor = 0.3

    _, trades_flat = run_portfolio_backtest(
        price_data, params=params, initial_capital=capital, correlation_aware=False,
    )
    _, trades_corr = run_portfolio_backtest(
        price_data, params=params, initial_capital=capital, correlation_aware=True, corr_penalty_floor=corr_floor,
    )
    assert len(trades_flat) > 0 and len(trades_corr) > 0

    first_day = trades_flat["entry_date"].min()
    same_day_flat = trades_flat[trades_flat["entry_date"] == first_day].sort_values("ticker")
    same_day_corr = trades_corr[trades_corr["entry_date"] == first_day].sort_values("ticker")
    assert len(same_day_flat) == 2 and len(same_day_corr) == 2

    # First-opened ticker (alphabetically A, opened while the book was still
    # empty) should be sized identically either way - nothing to correlate
    # against yet.
    a_flat = same_day_flat[same_day_flat["ticker"] == "A"].iloc[0]
    a_corr = same_day_corr[same_day_corr["ticker"] == "A"].iloc[0]
    assert a_corr["qty"] == pytest.approx(a_flat["qty"], rel=1e-6)

    # Second-opened ticker (B, opened while A was already held) should be
    # shrunk to ~corr_penalty_floor of the uncorrelated-sizing qty.
    b_flat = same_day_flat[same_day_flat["ticker"] == "B"].iloc[0]
    b_corr = same_day_corr[same_day_corr["ticker"] == "B"].iloc[0]
    assert b_corr["qty"] == pytest.approx(b_flat["qty"] * corr_floor, rel=1e-2)


def test_trailing_correlation_uses_no_future_data():
    # Two series that move in lockstep before `as_of` and then diverge
    # completely after it - the computed correlation must reflect only the
    # pre-as_of window (~1.0), proving no lookahead into the post-as_of split.
    dates = pd.bdate_range("2020-01-01", periods=200)
    rng = np.random.default_rng(3)
    shared = rng.normal(0.0005, 0.01, size=200)
    as_of = dates[150]

    r1 = shared.copy()
    r2 = shared.copy()
    # after as_of, make them perfectly anti-correlated instead
    tail = rng.normal(0.0005, 0.01, size=50)
    r1[150:] = tail
    r2[150:] = -tail

    returns = {
        "A": pd.Series(r1, index=dates),
        "B": pd.Series(r2, index=dates),
    }
    corr = _trailing_correlation(returns, "A", "B", as_of, lookback=60)
    assert corr > 0.9  # only the lockstep pre-as_of window should be visible


def test_correlation_returns_zero_with_insufficient_overlap():
    dates = pd.bdate_range("2020-01-01", periods=10)
    returns = {
        "A": pd.Series(np.linspace(0, 1, 10), index=dates),
        "B": pd.Series(np.linspace(1, 0, 10), index=dates),
    }
    corr = _trailing_correlation(returns, "A", "B", dates[-1], lookback=60)
    assert corr == 0.0
