"""Single-asset event-driven backtest engine.

Deliberately not fully vectorized: entries/exits depend on stateful
stop-loss/take-profit levels that must be checked bar-by-bar (identical
in spirit to how strategy.exit() works inside the Pine script), so
correctness wins over raw speed here. For thousands of daily bars across
a watchlist this is still fast (see multi_asset.py for batch runs).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .signals import ConfluenceParams, compute_confluence


@dataclass
class Trade:
    side: str  # "long" | "short"
    entry_date: pd.Timestamp
    entry_price: float
    qty: float
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        diff = (self.exit_price - self.entry_price) if self.side == "long" else (self.entry_price - self.exit_price)
        return diff * self.qty

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None or self.entry_price == 0:
            return 0.0
        diff = (self.exit_price - self.entry_price) if self.side == "long" else (self.entry_price - self.exit_price)
        return diff / self.entry_price


def run_backtest(
    df: pd.DataFrame,
    params: ConfluenceParams | None = None,
    initial_capital: float = 10_000.0,
    allow_long: bool = True,
    allow_short: bool = True,
    commission_pct: float = 0.05,
    use_htf_filter: bool = False,
) -> tuple[pd.Series, list[Trade]]:
    """Run the confluence strategy over `df` (raw OHLCV) and return (equity_curve, trades).

    df must have open/high/low/close/volume columns and a sorted datetime index.
    Signals are computed internally via compute_confluence (and add_htf_filter
    if use_htf_filter is True) so callers just need to pass raw price data.
    """
    p = params or ConfluenceParams()
    data = compute_confluence(df, p)

    if use_htf_filter:
        from .signals import add_htf_filter

        data = add_htf_filter(data)
    else:
        data["htf_bullish"] = True
        data["htf_bearish"] = True

    cash = initial_capital
    position: Trade | None = None
    equity_curve = []
    trades: list[Trade] = []

    for ts, row in data.iterrows():
        if pd.isna(row["atr"]) or pd.isna(row["net_score"]):
            equity_curve.append((ts, cash))
            continue

        # ---- manage open position: stop / target / score-fade exit ----
        if position is not None:
            stop = (
                position.entry_price - row["atr"] * p.atr_mult_sl
                if position.side == "long"
                else position.entry_price + row["atr"] * p.atr_mult_sl
            )
            target = (
                position.entry_price + row["atr"] * p.atr_mult_tp
                if position.side == "long"
                else position.entry_price - row["atr"] * p.atr_mult_tp
            )
            exit_price = None
            exit_reason = None

            if position.side == "long":
                if row["low"] <= stop:
                    exit_price, exit_reason = stop, "stop_loss"
                elif row["high"] >= target:
                    exit_price, exit_reason = target, "take_profit"
                elif row["exit_long_signal"]:
                    exit_price, exit_reason = row["close"], "score_fade"
            else:
                if row["high"] >= stop:
                    exit_price, exit_reason = stop, "stop_loss"
                elif row["low"] <= target:
                    exit_price, exit_reason = target, "take_profit"
                elif row["exit_short_signal"]:
                    exit_price, exit_reason = row["close"], "score_fade"

            if exit_price is not None:
                position.exit_date = ts
                position.exit_price = exit_price
                position.exit_reason = exit_reason
                fee = abs(exit_price * position.qty) * (commission_pct / 100)
                cash += position.pnl - fee
                trades.append(position)
                position = None

        # ---- look for new entry (only when flat) ----
        if position is None:
            risk_dollars = cash * (p.risk_per_trade_pct / 100)
            risk_dist = row["atr"] * p.atr_mult_sl
            qty = (risk_dollars / risk_dist) if risk_dist > 0 else 0.0

            if allow_long and row["long_signal"] and row["htf_bullish"] and qty > 0:
                fee = abs(row["close"] * qty) * (commission_pct / 100)
                cash -= fee
                position = Trade(side="long", entry_date=ts, entry_price=row["close"], qty=qty)
            elif allow_short and row["short_signal"] and row["htf_bearish"] and qty > 0:
                fee = abs(row["close"] * qty) * (commission_pct / 100)
                cash -= fee
                position = Trade(side="short", entry_date=ts, entry_price=row["close"], qty=qty)

        # ---- mark-to-market equity ----
        unrealized = 0.0
        if position is not None:
            diff = (
                (row["close"] - position.entry_price)
                if position.side == "long"
                else (position.entry_price - row["close"])
            )
            unrealized = diff * position.qty
        equity_curve.append((ts, cash + unrealized))

    equity = pd.Series(
        [v for _, v in equity_curve], index=[t for t, _ in equity_curve], name="equity"
    )
    return equity, trades


def trades_to_frame(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=["side", "entry_date", "entry_price", "exit_date", "exit_price", "qty", "pnl", "pnl_pct", "exit_reason"]
        )
    return pd.DataFrame(
        [
            {
                "side": t.side,
                "entry_date": t.entry_date,
                "entry_price": t.entry_price,
                "exit_date": t.exit_date,
                "exit_price": t.exit_price,
                "qty": t.qty,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "exit_reason": t.exit_reason,
            }
            for t in trades
        ]
    )
