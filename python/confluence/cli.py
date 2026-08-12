"""Command-line entry point.

Examples
--------
    python -m confluence.cli backtest --ticker AAPL --start 2015-01-01
    python -m confluence.cli scan --watchlist config/watchlist.txt --start 2018-01-01
    python -m confluence.cli optimize --ticker SPY --start 2015-01-01
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from .backtest import run_backtest, trades_to_frame
from .data import load_ohlcv, load_watchlist
from .metrics import summarize
from .multi_asset import aggregate_stats, run_watchlist
from .optimize import walk_forward
from .signals import ConfluenceParams, compute_breadth


def _load_breadth(args) -> pd.DataFrame | None:
    if not args.breadth_filter:
        return None
    breadth_df = load_ohlcv(args.breadth_ticker, start=args.start, end=args.end)
    return compute_breadth(breadth_df, sma_len=ConfluenceParams().lt_sma_len)


def _print_summary(title: str, summary: dict) -> None:
    print(f"\n=== {title} ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k:22s} {v:,.2f}")
        else:
            print(f"  {k:22s} {v}")


def cmd_backtest(args: argparse.Namespace) -> None:
    df = load_ohlcv(args.ticker, start=args.start, end=args.end, force_refresh=args.refresh)
    params = ConfluenceParams()
    breadth = _load_breadth(args)
    equity, trades = run_backtest(
        df, params=params, initial_capital=args.capital,
        use_htf_filter=args.htf, use_regime_filter=args.regime_filter,
        use_chop_filter=args.chop_filter, slippage_pct=args.slippage,
        breadth=breadth, use_breadth_filter=args.breadth_filter,
    )
    trade_df = trades_to_frame(trades)
    summary = summarize(equity, trade_df["pnl_pct"] if len(trade_df) else pd.Series(dtype=float))
    _print_summary(f"Backtest: {args.ticker}", summary)
    if args.out:
        trade_df.to_csv(args.out, index=False)
        print(f"\nSaved {len(trade_df)} trades to {args.out}")


def cmd_scan(args: argparse.Namespace) -> None:
    tickers = load_watchlist(args.watchlist)
    result = run_watchlist(
        tickers, start=args.start, end=args.end,
        use_htf_filter=args.htf, use_regime_filter=args.regime_filter,
        use_chop_filter=args.chop_filter, slippage_pct=args.slippage,
        use_breadth_filter=args.breadth_filter, breadth_ticker=args.breadth_ticker,
    )
    if result.empty:
        print("No results.")
        return
    pd.set_option("display.width", 160)
    print(result)
    print("\n=== Aggregate (cross-sectional) ===")
    print(json.dumps(aggregate_stats(result), indent=2, default=str))
    if args.out:
        result.to_csv(args.out)
        print(f"\nSaved summary to {args.out}")


def cmd_optimize(args: argparse.Namespace) -> None:
    df = load_ohlcv(args.ticker, start=args.start, end=args.end, force_refresh=args.refresh)
    grid = {
        "buy_threshold": [30, 40, 50],
        "sell_threshold": [-50, -40, -30],
        "atr_mult_sl": [1.0, 1.5, 2.0],
        "atr_mult_tp": [2.0, 3.0, 4.0],
    }
    breadth = _load_breadth(args)
    folds, best_params = walk_forward(
        df, grid, n_folds=args.folds, use_regime_filter=args.regime_filter,
        use_chop_filter=args.chop_filter, slippage_pct=args.slippage,
        breadth=breadth, use_breadth_filter=args.breadth_filter,
    )
    pd.set_option("display.width", 200)
    print(folds)
    print("\nFinal recommended params (from last fold's best in-sample fit):")
    print(best_params)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confluence", description="Confluence Signal System CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="Backtest a single ticker")
    bt.add_argument("--ticker", required=True)
    bt.add_argument("--start", default="2015-01-01")
    bt.add_argument("--end", default=None)
    bt.add_argument("--capital", type=float, default=10_000.0)
    bt.add_argument("--htf", action="store_true", help="Enable higher-timeframe trend filter")
    bt.add_argument(
        "--regime-filter", action="store_true",
        help="Veto counter-trend entries against the Long-Term Regime factor (SMA200 + 12-1mo momentum)",
    )
    bt.add_argument(
        "--chop-filter", action="store_true",
        help="Veto any new entry while ADX says the market isn't trending",
    )
    bt.add_argument(
        "--slippage", type=float, default=0.0,
        help="Adverse slippage %% applied to entries, stop-loss exits, and score-fade exits (default 0)",
    )
    bt.add_argument(
        "--breadth-filter", action="store_true",
        help="Veto entries against a market-breadth reference ticker's own 200-SMA trend (default SPY)",
    )
    bt.add_argument("--breadth-ticker", default="SPY", help="Market-breadth reference ticker (default SPY)")
    bt.add_argument("--refresh", action="store_true", help="Bypass cache and re-download")
    bt.add_argument("--out", default=None, help="CSV path to save the trade log")
    bt.set_defaults(func=cmd_backtest)

    scan = sub.add_parser("scan", help="Backtest a whole watchlist and aggregate results")
    scan.add_argument("--watchlist", required=True, help="Path to a newline-separated ticker file")
    scan.add_argument("--start", default="2015-01-01")
    scan.add_argument("--end", default=None)
    scan.add_argument("--htf", action="store_true")
    scan.add_argument(
        "--regime-filter", action="store_true",
        help="Veto counter-trend entries against the Long-Term Regime factor (SMA200 + 12-1mo momentum)",
    )
    scan.add_argument(
        "--chop-filter", action="store_true",
        help="Veto any new entry while ADX says the market isn't trending",
    )
    scan.add_argument(
        "--slippage", type=float, default=0.0,
        help="Adverse slippage %% applied to entries, stop-loss exits, and score-fade exits (default 0)",
    )
    scan.add_argument(
        "--breadth-filter", action="store_true",
        help="Veto entries against a market-breadth reference ticker's own 200-SMA trend (default SPY)",
    )
    scan.add_argument("--breadth-ticker", default="SPY", help="Market-breadth reference ticker (default SPY)")
    scan.add_argument("--out", default=None, help="CSV path to save the summary table")
    scan.set_defaults(func=cmd_scan)

    opt = sub.add_parser("optimize", help="Walk-forward grid-search parameter optimization")
    opt.add_argument("--ticker", required=True)
    opt.add_argument("--start", default="2010-01-01")
    opt.add_argument("--end", default=None)
    opt.add_argument("--folds", type=int, default=4)
    opt.add_argument(
        "--regime-filter", action="store_true",
        help="Veto counter-trend entries against the Long-Term Regime factor (SMA200 + 12-1mo momentum)",
    )
    opt.add_argument(
        "--chop-filter", action="store_true",
        help="Veto any new entry while ADX says the market isn't trending",
    )
    opt.add_argument(
        "--slippage", type=float, default=0.0,
        help="Adverse slippage %% applied to entries, stop-loss exits, and score-fade exits (default 0)",
    )
    opt.add_argument(
        "--breadth-filter", action="store_true",
        help="Veto entries against a market-breadth reference ticker's own 200-SMA trend (default SPY)",
    )
    opt.add_argument("--breadth-ticker", default="SPY", help="Market-breadth reference ticker (default SPY)")
    opt.add_argument("--refresh", action="store_true")
    opt.set_defaults(func=cmd_optimize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
