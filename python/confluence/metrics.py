"""Performance metrics for an equity curve / trade log."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    if n_years <= 0:
        return 0.0
    total_return = equity.iloc[-1] / equity.iloc[0]
    if total_return <= 0:
        return -1.0
    return total_return ** (1 / n_years) - 1


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return drawdown.min()


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / TRADING_DAYS_PER_YEAR
    std = excess.std()
    if std == 0 or np.isnan(std):
        return 0.0
    return (excess.mean() / std) * np.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / TRADING_DAYS_PER_YEAR
    downside = excess[excess < 0]
    downside_std = downside.std()
    if downside_std == 0 or np.isnan(downside_std):
        return 0.0
    return (excess.mean() / downside_std) * np.sqrt(TRADING_DAYS_PER_YEAR)


def win_rate(trade_pnls: pd.Series) -> float:
    if len(trade_pnls) == 0:
        return 0.0
    return float((trade_pnls > 0).sum() / len(trade_pnls))


def profit_factor(trade_pnls: pd.Series) -> float:
    gains = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def summarize(equity: pd.Series, trade_pnls: pd.Series) -> dict:
    """One-stop performance summary dict used by backtest.py and multi_asset.py."""
    daily_returns = equity.pct_change().dropna()
    return {
        "start": equity.index[0] if len(equity) else None,
        "end": equity.index[-1] if len(equity) else None,
        "start_equity": float(equity.iloc[0]) if len(equity) else 0.0,
        "end_equity": float(equity.iloc[-1]) if len(equity) else 0.0,
        "total_return_pct": float((equity.iloc[-1] / equity.iloc[0] - 1) * 100) if len(equity) else 0.0,
        "cagr_pct": float(cagr(equity) * 100),
        "max_drawdown_pct": float(max_drawdown(equity) * 100),
        "sharpe": float(sharpe_ratio(daily_returns)),
        "sortino": float(sortino_ratio(daily_returns)),
        "num_trades": int(len(trade_pnls)),
        "win_rate_pct": float(win_rate(trade_pnls) * 100),
        "profit_factor": float(profit_factor(trade_pnls)),
        "avg_trade_pnl_pct": float(trade_pnls.mean() * 100) if len(trade_pnls) else 0.0,
    }
