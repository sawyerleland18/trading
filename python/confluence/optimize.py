"""Walk-forward grid-search parameter optimization.

Plain in-sample grid search overfits almost by definition — the params
that maximize a single backtest's Sharpe ratio are partly fitting noise.
This module does walk-forward validation instead: split history into N
sequential folds, fit (grid search) on each in-sample fold, evaluate on
the following untouched out-of-sample fold, and report the out-of-sample
aggregate — a much more honest estimate of how a parameter set would have
actually performed.
"""
from __future__ import annotations

import itertools
from dataclasses import replace

import pandas as pd

from .backtest import run_backtest, trades_to_frame
from .metrics import summarize
from .signals import ConfluenceParams


def _score(equity: pd.Series, trade_pnls: pd.Series) -> float:
    """Objective to maximize: Sharpe, but zeroed out if too few trades to trust."""
    s = summarize(equity, trade_pnls)
    if s["num_trades"] < 5:
        return -999.0
    return s["sharpe"]


def grid_search(
    df: pd.DataFrame,
    param_grid: dict[str, list],
    base_params: ConfluenceParams | None = None,
    initial_capital: float = 10_000.0,
    use_regime_filter: bool = False,
    use_chop_filter: bool = False,
    slippage_pct: float = 0.0,
    breadth: pd.DataFrame | None = None,
    use_breadth_filter: bool = False,
    use_strength_sizing: bool = False,
) -> pd.DataFrame:
    """Try every combination in param_grid (dict of field_name -> list of values).

    Example:
        grid_search(df, {"buy_threshold": [30, 40, 50], "atr_mult_sl": [1.0, 1.5, 2.0]})

    Returns a DataFrame of all combinations ranked by Sharpe, descending.
    """
    base = base_params or ConfluenceParams()
    keys = list(param_grid.keys())
    rows = []
    for combo in itertools.product(*param_grid.values()):
        overrides = dict(zip(keys, combo))
        params = replace(base, **overrides)
        equity, trades = run_backtest(
            df, params=params, initial_capital=initial_capital, use_regime_filter=use_regime_filter,
            use_chop_filter=use_chop_filter, slippage_pct=slippage_pct,
            breadth=breadth, use_breadth_filter=use_breadth_filter,
            use_strength_sizing=use_strength_sizing,
        )
        trade_df = trades_to_frame(trades)
        pnl_pct = trade_df["pnl_pct"] if len(trade_df) else pd.Series(dtype=float)
        summary = summarize(equity, pnl_pct)
        summary.update(overrides)
        rows.append(summary)
    result = pd.DataFrame(rows)
    return result.sort_values("sharpe", ascending=False).reset_index(drop=True)


def walk_forward(
    df: pd.DataFrame,
    param_grid: dict[str, list],
    n_folds: int = 4,
    base_params: ConfluenceParams | None = None,
    initial_capital: float = 10_000.0,
    use_regime_filter: bool = False,
    use_chop_filter: bool = False,
    slippage_pct: float = 0.0,
    breadth: pd.DataFrame | None = None,
    use_breadth_filter: bool = False,
    use_strength_sizing: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Sequential walk-forward: fold i is in-sample, fold i+1 is out-of-sample.

    Returns (per_fold_results, best_params_from_final_fold). per_fold_results
    has one row per fold with the best in-sample params and their
    out-of-sample performance — the out-of-sample Sharpe column is the
    number to trust, not the in-sample one.
    """
    base = base_params or ConfluenceParams()
    fold_edges = pd.date_range(df.index[0], df.index[-1], periods=n_folds + 1)
    rows = []
    best_params = base

    for i in range(n_folds - 1):
        in_sample = df[(df.index >= fold_edges[i]) & (df.index < fold_edges[i + 1])]
        out_sample = df[(df.index >= fold_edges[i + 1]) & (df.index < fold_edges[i + 2])]
        if len(in_sample) < 100 or len(out_sample) < 50:
            continue

        is_results = grid_search(
            in_sample, param_grid, base_params=base, initial_capital=initial_capital,
            use_regime_filter=use_regime_filter, use_chop_filter=use_chop_filter,
            slippage_pct=slippage_pct, breadth=breadth, use_breadth_filter=use_breadth_filter,
            use_strength_sizing=use_strength_sizing,
        )
        if is_results.empty:
            continue
        keys = list(param_grid.keys())
        best_row = is_results.iloc[0]
        overrides = {k: best_row[k] for k in keys}
        best_params = replace(base, **overrides)

        oos_equity, oos_trades = run_backtest(
            out_sample, params=best_params, initial_capital=initial_capital,
            use_regime_filter=use_regime_filter, use_chop_filter=use_chop_filter,
            slippage_pct=slippage_pct, breadth=breadth, use_breadth_filter=use_breadth_filter,
            use_strength_sizing=use_strength_sizing,
        )
        oos_trade_df = trades_to_frame(oos_trades)
        oos_pnl = oos_trade_df["pnl_pct"] if len(oos_trade_df) else pd.Series(dtype=float)
        oos_summary = summarize(oos_equity, oos_pnl)

        rows.append(
            {
                "fold": i,
                "in_sample_start": in_sample.index[0],
                "in_sample_end": in_sample.index[-1],
                "out_sample_start": out_sample.index[0],
                "out_sample_end": out_sample.index[-1],
                **{f"param_{k}": v for k, v in overrides.items()},
                "in_sample_sharpe": best_row["sharpe"],
                "out_sample_sharpe": oos_summary["sharpe"],
                "out_sample_cagr_pct": oos_summary["cagr_pct"],
                "out_sample_max_dd_pct": oos_summary["max_drawdown_pct"],
                "out_sample_trades": oos_summary["num_trades"],
            }
        )

    return pd.DataFrame(rows), best_params
