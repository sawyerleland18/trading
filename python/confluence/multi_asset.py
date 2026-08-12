"""Run the confluence strategy across a whole watchlist and aggregate results.

This is what substantiates "backed up with tons of data": rather than
trusting one backtest on one ticker, run the identical rule set across
dozens/hundreds of symbols and multiple years, then look at the
distribution of outcomes. A strategy that only works on one stock in one
period is probably overfit or lucky.
"""
from __future__ import annotations

import pandas as pd

from .backtest import run_backtest, trades_to_frame
from .data import load_ohlcv
from .metrics import summarize
from .signals import ConfluenceParams, compute_breadth


def run_watchlist(
    tickers: list[str],
    start: str = "2015-01-01",
    end: str | None = None,
    params: ConfluenceParams | None = None,
    initial_capital: float = 10_000.0,
    use_htf_filter: bool = False,
    use_regime_filter: bool = False,
    use_chop_filter: bool = False,
    slippage_pct: float = 0.0,
    use_breadth_filter: bool = False,
    breadth_ticker: str = "SPY",
    verbose: bool = True,
) -> pd.DataFrame:
    """Backtest every ticker in `tickers` and return a summary DataFrame, one row per ticker.

    Tickers that fail to download or have insufficient history are skipped
    with a warning printed to stdout (not raised), so one bad symbol doesn't
    kill a large batch run.

    use_breadth_filter loads `breadth_ticker` (SPY by default) once and
    reuses the same computed breadth regime for every ticker in the
    watchlist, rather than re-fetching/re-computing it per ticker.
    """
    p = params or ConfluenceParams()
    breadth = None
    if use_breadth_filter:
        breadth_df = load_ohlcv(breadth_ticker, start=start, end=end)
        breadth = compute_breadth(breadth_df, sma_len=p.lt_sma_len)

    rows = []
    for ticker in tickers:
        try:
            df = load_ohlcv(ticker, start=start, end=end)
            if len(df) < 250:
                if verbose:
                    print(f"[skip] {ticker}: only {len(df)} bars of history (<250)")
                continue
            equity, trades = run_backtest(
                df, params=params, initial_capital=initial_capital,
                use_htf_filter=use_htf_filter, use_regime_filter=use_regime_filter,
                use_chop_filter=use_chop_filter, slippage_pct=slippage_pct,
                breadth=breadth, use_breadth_filter=use_breadth_filter,
            )
            trade_df = trades_to_frame(trades)
            summary = summarize(equity, trade_df["pnl_pct"] if len(trade_df) else pd.Series(dtype=float))
            summary["ticker"] = ticker
            rows.append(summary)
            if verbose:
                print(
                    f"[ok] {ticker}: CAGR={summary['cagr_pct']:.1f}% "
                    f"MaxDD={summary['max_drawdown_pct']:.1f}% "
                    f"WinRate={summary['win_rate_pct']:.0f}% "
                    f"Trades={summary['num_trades']}"
                )
        except Exception as exc:  # noqa: BLE001 - batch run must not die on one bad symbol
            if verbose:
                print(f"[error] {ticker}: {exc}")
            continue

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows).set_index("ticker")
    cols = [
        "cagr_pct",
        "max_drawdown_pct",
        "sharpe",
        "sortino",
        "num_trades",
        "win_rate_pct",
        "profit_factor",
        "avg_trade_pnl_pct",
        "total_return_pct",
        "start",
        "end",
    ]
    return result[cols].sort_values("sharpe", ascending=False)


def aggregate_stats(summary_df: pd.DataFrame) -> dict:
    """Cross-sectional stats across the whole watchlist run (robustness check)."""
    if summary_df.empty:
        return {}
    return {
        "n_tickers": int(len(summary_df)),
        "median_cagr_pct": float(summary_df["cagr_pct"].median()),
        "median_sharpe": float(summary_df["sharpe"].median()),
        "median_max_drawdown_pct": float(summary_df["max_drawdown_pct"].median()),
        "median_win_rate_pct": float(summary_df["win_rate_pct"].median()),
        "pct_tickers_profitable": float((summary_df["total_return_pct"] > 0).mean() * 100),
        "total_trades": int(summary_df["num_trades"].sum()),
    }
