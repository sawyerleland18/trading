"""Portfolio-level backtest: the whole watchlist traded from ONE shared account.

Every other backtest in this package (backtest.py, multi_asset.py) tests one
ticker at a time against its own dedicated $10k. That's useful for asking
"does this rule help this ticker?", but it isn't how anyone actually trades
a watchlist — in a real account, capital is shared and finite: if SPY, QQQ,
and AAPL all signal a long the same week, you can't fund three full-size
positions out of thin air, and holding all three at once isn't really three
independent bets if they move together.

This module runs every ticker's confluence signals against ONE cash account:

  - Position sizing draws from *current total account equity*, not a
    per-ticker allowance, and a new position's dollar size is capped by
    whatever cash is actually still uncommitted (no leverage/margin
    modeled — a position reserves its full notional out of cash, like a
    cash-secured account, and that notional is released back, adjusted by
    P&L, when the position closes).
  - Optional correlation-aware sizing: a new position's risk is shrunk if
    it's highly correlated (trailing `corr_lookback`-day returns, computed
    only on data strictly before the entry date — no lookahead) with
    positions already open, since two correlated positions aren't really
    two independent bets.
  - Optional max_concurrent_positions caps how many names can be held at
    once, on top of whatever capital already constrains.

Per-ticker signal generation (compute_confluence) is identical to every
other module here — this only changes how *capital* is allocated across
those signals, not the signals themselves.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Trade, _slip
from .signals import ConfluenceParams, compute_confluence


@dataclass
class PortfolioTrade(Trade):
    ticker: str = ""


def _trailing_correlation(
    returns: dict[str, pd.Series], ticker_a: str, ticker_b: str, as_of: pd.Timestamp, lookback: int
) -> float:
    """Pearson correlation of daily returns, using only bars strictly before
    `as_of` (no lookahead) — returns 0.0 (no penalty) if there isn't enough
    overlapping history to trust a correlation estimate, rather than
    guessing off a handful of points."""
    s1 = returns[ticker_a]
    s2 = returns[ticker_b]
    s1 = s1[s1.index < as_of].tail(lookback)
    s2 = s2[s2.index < as_of].tail(lookback)
    aligned = pd.concat([s1, s2], axis=1, join="inner").dropna()
    min_obs = max(20, lookback // 3)
    if len(aligned) < min_obs:
        return 0.0
    corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    return 0.0 if pd.isna(corr) else float(corr)


def run_portfolio_backtest(
    price_data: dict[str, pd.DataFrame],
    params: ConfluenceParams | None = None,
    initial_capital: float = 100_000.0,
    use_regime_filter: bool = False,
    use_chop_filter: bool = False,
    use_breadth_filter: bool = False,
    breadth: pd.DataFrame | None = None,
    use_strength_sizing: bool = False,
    correlation_aware: bool = False,
    corr_lookback: int = 60,
    corr_penalty_floor: float = 0.3,
    max_concurrent_positions: int | None = None,
    commission_pct: float = 0.05,
    slippage_pct: float = 0.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """Backtest every ticker in `price_data` against one shared cash account.

    price_data: {ticker: raw OHLCV DataFrame}. Filter/sizing flags mirror
    backtest.run_backtest() exactly (same meaning, same defaults) — see
    that module's docstring for what each one does. New here:

    correlation_aware=True shrinks a new position's risk dollars by
    max(corr_penalty_floor, 1 - avg_abs_corr_with_open_positions) — never
    below corr_penalty_floor, so a correlated signal is still tradeable at
    reduced size, not vetoed outright.

    max_concurrent_positions caps how many tickers can be held
    simultaneously, independent of capital. None (default) means capital
    availability is the only cap.

    Returns (equity_curve, trades_df) — trades_df has the same columns as
    backtest.trades_to_frame() plus a `ticker` column.
    """
    p = params or ConfluenceParams()

    signals: dict[str, pd.DataFrame] = {}
    returns: dict[str, pd.Series] = {}
    for ticker, df in price_data.items():
        data = compute_confluence(df, p)
        if use_breadth_filter:
            if breadth is None:
                raise ValueError("use_breadth_filter=True requires a `breadth` DataFrame (see signals.compute_breadth).")
            aligned = breadth.reindex(data.index, method="ffill")
            data["breadth_bullish"] = aligned["breadth_bullish"].fillna(False)
            data["breadth_bearish"] = aligned["breadth_bearish"].fillna(False)
        else:
            data["breadth_bullish"] = True
            data["breadth_bearish"] = True
        signals[ticker] = data
        returns[ticker] = df["close"].pct_change()

    all_dates = sorted(set().union(*[set(d.index) for d in signals.values()]))

    cash = initial_capital
    positions: dict[str, PortfolioTrade] = {}
    reserved: dict[str, float] = {}
    last_close: dict[str, float] = {}
    trades: list[PortfolioTrade] = []
    equity_curve: list[tuple[pd.Timestamp, float]] = []

    for ts in all_dates:
        # ---- manage open positions: stop / target / score-fade exit ----
        for ticker in list(positions.keys()):
            data = signals[ticker]
            if ts not in data.index:
                continue
            row = data.loc[ts]
            last_close[ticker] = row["close"]
            if pd.isna(row["atr"]) or pd.isna(row["net_score"]):
                continue
            position = positions[ticker]
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
                cash += reserved.pop(ticker) + position.pnl - fee
                trades.append(position)
                del positions[ticker]

        # ---- look for new entries, most-confident signal first ----
        candidates = []
        for ticker, data in signals.items():
            if ticker in positions or ts not in data.index:
                continue
            row = data.loc[ts]
            if pd.isna(row["atr"]) or pd.isna(row["net_score"]):
                continue
            regime_long_ok = (not use_regime_filter) or row["regime_bullish"]
            regime_short_ok = (not use_regime_filter) or row["regime_bearish"]
            chop_ok = (not use_chop_filter) or row["trending"]
            breadth_long_ok = row["breadth_bullish"]
            breadth_short_ok = row["breadth_bearish"]
            if row["long_signal"] and regime_long_ok and chop_ok and breadth_long_ok:
                candidates.append((ticker, "long", row))
            elif row["short_signal"] and regime_short_ok and chop_ok and breadth_short_ok:
                candidates.append((ticker, "short", row))
        candidates.sort(key=lambda c: abs(c[2]["net_score"]), reverse=True)

        for ticker, side, row in candidates:
            if max_concurrent_positions is not None and len(positions) >= max_concurrent_positions:
                break
            if cash <= 0:
                break

            total_equity = cash + sum(reserved.values()) + sum(
                (last_close.get(t, positions[t].entry_price) - positions[t].entry_price) * positions[t].qty
                if positions[t].side == "long"
                else (positions[t].entry_price - last_close.get(t, positions[t].entry_price)) * positions[t].qty
                for t in positions
            )
            strength_mult = (abs(row["net_score"]) / 100.0) if use_strength_sizing else 1.0
            risk_dollars = total_equity * (p.risk_per_trade_pct / 100) * strength_mult

            if correlation_aware and positions:
                corrs = [
                    abs(_trailing_correlation(returns, ticker, other, ts, corr_lookback))
                    for other in positions
                ]
                avg_abs_corr = sum(corrs) / len(corrs)
                risk_dollars *= max(corr_penalty_floor, 1 - avg_abs_corr)

            risk_dist = row["atr"] * p.atr_mult_sl
            if risk_dist <= 0:
                continue
            qty = risk_dollars / risk_dist
            entry_price = _slip(row["close"], slippage_pct, "buy" if side == "long" else "sell")
            notional = qty * entry_price
            fee = notional * (commission_pct / 100)

            # Shared-capital constraint: can't spend cash that isn't there.
            # Scale the position down to whatever's actually available
            # rather than skipping it outright, matching how you'd actually
            # size a smaller position if a signal fires with limited buying
            # power left, instead of taking it all-or-nothing.
            if notional + fee > cash:
                if cash <= 0:
                    continue
                qty = cash / (entry_price * (1 + commission_pct / 100))
                notional = qty * entry_price
                fee = notional * (commission_pct / 100)
            if qty <= 0 or notional < 1.0:
                continue

            cash -= notional + fee
            reserved[ticker] = notional
            positions[ticker] = PortfolioTrade(
                side=side, entry_date=ts, entry_price=entry_price, qty=qty,
                entry_atr=row["atr"], ticker=ticker,
            )
            last_close[ticker] = row["close"]

        # ---- mark-to-market total equity ----
        unrealized = 0.0
        for ticker, position in positions.items():
            price = last_close.get(ticker, position.entry_price)
            diff = (price - position.entry_price) if position.side == "long" else (position.entry_price - price)
            unrealized += diff * position.qty
        equity_curve.append((ts, cash + sum(reserved.values()) + unrealized))

    equity = pd.Series([v for _, v in equity_curve], index=[t for t, _ in equity_curve], name="equity")
    trades_df = _portfolio_trades_to_frame(trades)
    return equity, trades_df


def _portfolio_trades_to_frame(trades: list[PortfolioTrade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=["ticker", "side", "entry_date", "entry_price", "exit_date", "exit_price", "qty", "pnl", "pnl_pct", "exit_reason"]
        )
    return pd.DataFrame(
        [
            {
                "ticker": t.ticker,
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
