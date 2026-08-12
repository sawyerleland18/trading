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


def _slip(price: float, slippage_pct: float, direction: str) -> float:
    """Apply adverse slippage to a market-style fill. `direction` is "buy" (fill
    moves against you, i.e. higher) or "sell" (fill moves against you, i.e. lower)."""
    if slippage_pct <= 0:
        return price
    factor = 1 + slippage_pct / 100 if direction == "buy" else 1 - slippage_pct / 100
    return price * factor


@dataclass
class Trade:
    side: str  # "long" | "short"
    entry_date: pd.Timestamp
    entry_price: float
    qty: float
    entry_atr: float = 0.0  # ATR *at entry*, frozen — stop/target are locked to this, not the live ATR
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
    use_regime_filter: bool = False,
    use_chop_filter: bool = False,
    slippage_pct: float = 0.0,
) -> tuple[pd.Series, list[Trade]]:
    """Run the confluence strategy over `df` (raw OHLCV) and return (equity_curve, trades).

    df must have open/high/low/close/volume columns and a sorted datetime index.
    Signals are computed internally via compute_confluence (and add_htf_filter
    if use_htf_filter is True) so callers just need to pass raw price data.

    use_regime_filter=True vetoes new entries against the Long-Term Regime
    factor's direction (200-SMA + 12-1mo momentum) — no new shorts while
    that regime reads bullish, no new longs while it reads bearish. See
    docs/BACKTEST_RESULTS.md for why: without this, the system took nearly
    as many shorts as longs on SPY through an 11-year bull market.

    use_chop_filter=True vetoes any new entry (long or short) while ADX says
    the market isn't trending — a complementary filter to use_regime_filter:
    that one says "don't fight the big trend", this one says "don't trade
    when there's no trend to catch at all."

    slippage_pct models adverse fills on market-style orders — new entries,
    stop-loss exits, and score-fade exits (all effectively market orders in
    this engine) fill slippage_pct worse than their nominal price. Take-profit
    exits are treated as resting limit orders and are not slipped, matching
    standard backtesting convention. Defaults to 0 (no slippage) to keep
    existing callers' results unchanged unless explicitly opted in.
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
            # Locked to entry_atr (frozen at entry), NOT row["atr"] (today's
            # live ATR) — stop/target must not drift day to day. Matches the
            # Pine script, which assigns longSL/longTP with `:=` exactly once,
            # in the entry block, and never touches them again.
            stop = (
                position.entry_price - position.entry_atr * p.atr_mult_sl
                if position.side == "long"
                else position.entry_price + position.entry_atr * p.atr_mult_sl
            )
            target = (
                position.entry_price + position.entry_atr * p.atr_mult_tp
                if position.side == "long"
                else position.entry_price - position.entry_atr * p.atr_mult_tp
            )
            exit_price = None
            exit_reason = None
            # Exiting a long is a sell (slips lower); exiting a short is a buy
            # to cover (slips higher). take_profit is a resting limit order —
            # not slipped, by standard backtesting convention.
            exit_slip_dir = "sell" if position.side == "long" else "buy"

            if position.side == "long":
                if row["low"] <= stop:
                    exit_price, exit_reason = _slip(stop, slippage_pct, exit_slip_dir), "stop_loss"
                elif row["high"] >= target:
                    exit_price, exit_reason = target, "take_profit"
                elif row["exit_long_signal"]:
                    exit_price, exit_reason = _slip(row["close"], slippage_pct, exit_slip_dir), "score_fade"
            else:
                if row["high"] >= stop:
                    exit_price, exit_reason = _slip(stop, slippage_pct, exit_slip_dir), "stop_loss"
                elif row["low"] <= target:
                    exit_price, exit_reason = target, "take_profit"
                elif row["exit_short_signal"]:
                    exit_price, exit_reason = _slip(row["close"], slippage_pct, exit_slip_dir), "score_fade"

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

            regime_long_ok = (not use_regime_filter) or row["regime_bullish"]
            regime_short_ok = (not use_regime_filter) or row["regime_bearish"]
            chop_ok = (not use_chop_filter) or row["trending"]

            if allow_long and row["long_signal"] and row["htf_bullish"] and regime_long_ok and chop_ok and qty > 0:
                entry_price = _slip(row["close"], slippage_pct, "buy")
                fee = abs(entry_price * qty) * (commission_pct / 100)
                cash -= fee
                position = Trade(side="long", entry_date=ts, entry_price=entry_price, qty=qty, entry_atr=row["atr"])
            elif allow_short and row["short_signal"] and row["htf_bearish"] and regime_short_ok and chop_ok and qty > 0:
                entry_price = _slip(row["close"], slippage_pct, "sell")
                fee = abs(entry_price * qty) * (commission_pct / 100)
                cash -= fee
                position = Trade(side="short", entry_date=ts, entry_price=entry_price, qty=qty, entry_atr=row["atr"])

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
