"""Confluence scoring model — the Python mirror of pine/confluence_signals.pine.

The six weighted factor groups and their point values are kept identical
to the Pine script on purpose. If you change a weight or a rule in one
place, change it in the other — see docs/ARCHITECTURE.md for the full
breakdown table that both implementations must agree with.

Factor 6 ("Long-Term Regime") is deliberately built from two of the most
heavily-published, out-of-sample-replicated rules in empirical finance
rather than another discretionary indicator:

  - 200-day SMA trend timing (Faber, "A Quantitative Approach to Tactical
    Asset Allocation", 2007/2013) — tested back to 1901 across US equities,
    foreign equities, bonds, commodities and REITs.
  - 12-1 month time-series momentum (Jegadeesh & Titman 1993; Moskowitz,
    Ooi & Pedersen 2012, "Time Series Momentum", JFE — 58 futures markets
    across 25+ years; replicated across 8 asset classes/markets over more
    than a century by Asness, Moskowitz & Pedersen 2013 and over 212 years
    by Geczy & Samonov 2016).

See docs/ARCHITECTURE.md for citations and the full weight table.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import indicators as ind
from . import patterns as pat


@dataclass
class ConfluenceParams:
    # Trend
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    # Momentum
    rsi_len: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # Volume
    obv_lookback: int = 5
    rel_vol_len: int = 20
    rel_vol_mult: float = 1.2
    # Volatility regime
    adx_len: int = 14
    adx_thresh: float = 20.0
    # Mean reversion / Bollinger
    bb_len: int = 20
    bb_mult: float = 2.0
    # Long-term regime (SMA200 timing + 12-1 month time-series momentum)
    lt_sma_len: int = 200
    mom_lookback_bars: int = 252  # ~12 months of trading days
    mom_skip_bars: int = 21       # ~1 month, skipped to avoid short-term reversal
    # Signal thresholds
    buy_threshold: float = 40.0
    sell_threshold: float = -40.0
    strong_buy_level: float = 70.0
    strong_sell_level: float = -70.0
    exit_long_score: float = 10.0
    exit_short_score: float = -10.0
    # Signal trigger: "ema_cross_confluence" fires on the exact bar the
    # chosen EMA pair crosses, gated by the confluence score already
    # agreeing (>= emaConfirmScore in that direction). "score_threshold_cross"
    # ignores EMA crossovers and fires purely when net_score crosses
    # buy_threshold/sell_threshold. Must match the Pine script's `triggerMode`.
    trigger_mode: str = "ema_cross_confluence"  # or "score_threshold_cross"
    ema_cross_pair: str = "fast_mid"  # "fast_mid" | "fast_slow" | "mid_slow"
    ema_confirm_score: float = 15.0
    # Risk
    atr_len: int = 14
    atr_mult_sl: float = 1.5
    atr_mult_tp: float = 3.0
    risk_per_trade_pct: float = 1.0
    # Chart patterns (Double Top/Bottom, Head-and-Shoulders/Inverse) — see
    # patterns.py module docstring for the evidence caveat and methodology.
    # pattern_weight defaults to 0.0 (inert): this factor contributes
    # nothing to net_score until explicitly validated and turned on, same
    # as every other new signal here (see docs/BACKTEST_RESULTS.md).
    pattern_weight: float = 0.0
    pattern_pivot_left: int = 5
    pattern_pivot_right: int = 5
    pattern_tolerance_pct: float = 0.03
    pattern_trough_depth_pct: float = 0.02
    pattern_max_bars: int = 60
    pattern_breakout_window: int = 20


REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")


def compute_confluence(df: pd.DataFrame, params: ConfluenceParams | None = None) -> pd.DataFrame:
    """Compute all factor scores + net_score + long/short signal columns.

    Parameters
    ----------
    df : DataFrame with columns open, high, low, close, volume (indexed by datetime).
    params : ConfluenceParams, uses defaults (matching the Pine script defaults) if None.

    Returns
    -------
    A copy of df with the following columns appended:
        ema_fast, ema_mid, ema_slow, rsi, macd_line, macd_signal, macd_hist,
        obv, rel_vol_sma, plus_di, minus_di, adx, bb_mid, bb_upper, bb_lower, bb_width,
        atr, lt_sma, ts_momentum, trend_pts, momentum_pts, volume_pts, vola_pts,
        bb_pts, long_term_pts, net_score, regime, long_signal, short_signal
    """
    _validate(df)
    p = params or ConfluenceParams()
    out = df.copy()

    close, high, low, volume, open_ = out["close"], out["high"], out["low"], out["volume"], out["open"]

    out["ema_fast"] = ind.ema(close, p.ema_fast)
    out["ema_mid"] = ind.ema(close, p.ema_mid)
    out["ema_slow"] = ind.ema(close, p.ema_slow)

    out["rsi"] = ind.rsi(close, p.rsi_len)
    macd_line, macd_signal, macd_hist = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    out["macd_line"], out["macd_signal"], out["macd_hist"] = macd_line, macd_signal, macd_hist

    out["obv"] = ind.obv(close, volume)
    out["rel_vol_sma"] = ind.sma(volume, p.rel_vol_len)

    plus_di, minus_di, adx = ind.dmi(high, low, close, p.adx_len)
    out["plus_di"], out["minus_di"], out["adx"] = plus_di, minus_di, adx

    bb_mid, bb_upper, bb_lower, bb_width = ind.bollinger_bands(close, p.bb_len, p.bb_mult)
    out["bb_mid"], out["bb_upper"], out["bb_lower"], out["bb_width"] = bb_mid, bb_upper, bb_lower, bb_width

    out["atr"] = ind.atr(high, low, close, p.atr_len)

    lt_sma = ind.sma(close, p.lt_sma_len)
    out["lt_sma"] = lt_sma
    mom_ref_recent = close.shift(p.mom_skip_bars)
    mom_ref_past = close.shift(p.mom_skip_bars + p.mom_lookback_bars)
    ts_momentum = mom_ref_recent / mom_ref_past - 1
    out["ts_momentum"] = ts_momentum

    # ---- Factor 1: Trend (+-20) ----
    trend_pts = (
        np.where(close > out["ema_fast"], 5, -5)
        + np.where(out["ema_fast"] > out["ema_mid"], 5, -5)
        + np.where(out["ema_mid"] > out["ema_slow"], 5, -5)
        + np.where(close > out["ema_slow"], 5, -5)
    )
    out["trend_pts"] = trend_pts.astype(float)

    # ---- Factor 2: Momentum (+-20) ----
    momentum_pts = (
        np.where(out["rsi"] > 50, 5, -5)
        + np.where(out["rsi"] > out["rsi"].shift(1), 3, -3)
        + np.where(out["macd_line"] > out["macd_signal"], 7, -7)
        + np.where(out["macd_hist"] > out["macd_hist"].shift(1), 5, -5)
    )
    out["momentum_pts"] = momentum_pts.astype(float)

    # ---- Factor 3: Volume (+-15) ----
    obv_rising = out["obv"] > out["obv"].shift(p.obv_lookback)
    rel_vol_spike = volume > (out["rel_vol_sma"] * p.rel_vol_mult)
    vol_direction = np.where(close > open_, 7, np.where(close < open_, -7, 0))
    volume_pts = np.where(obv_rising, 8, -8) + np.where(rel_vol_spike, vol_direction, 0)
    out["volume_pts"] = volume_pts.astype(float)

    # ---- Factor 4: Volatility regime via ADX (+-10) ----
    trending = out["adx"] > p.adx_thresh
    vola_pts = np.where(trending, np.where(out["plus_di"] > out["minus_di"], 10, -10), 0)
    out["vola_pts"] = vola_pts.astype(float)
    # Exposed separately (not just folded into vola_pts) so
    # `run_backtest(use_chop_filter=True)` can veto *any* new entry —
    # long or short — while ADX says the market isn't trending at all,
    # rather than just softening the score like vola_pts does.
    out["trending"] = trending

    # ---- Factor 5: Mean-reversion / Bollinger (+-10) ----
    breakout_up = (close > out["bb_upper"]) & (out["bb_width"] > out["bb_width"].shift(1))
    breakout_down = (close < out["bb_lower"]) & (out["bb_width"] > out["bb_width"].shift(1))
    bounce_up = (close <= out["bb_lower"]) & (out["rsi"] < 30)
    bounce_down = (close >= out["bb_upper"]) & (out["rsi"] > 70)
    bb_pts = np.select(
        [breakout_up, breakout_down, bounce_up, bounce_down],
        [10, -10, 5, -5],
        default=0,
    )
    out["bb_pts"] = bb_pts.astype(float)

    # ---- Factor 6: Long-Term Regime — SMA200 timing + 12-1mo momentum (+-25) ----
    # The single largest weight of any factor group, on purpose: this is the
    # component with the deepest, most-replicated academic evidence behind
    # it (see module docstring for citations) rather than a discretionary
    # technical rule.
    long_term_pts = np.where(close > lt_sma, 12, -12) + np.where(ts_momentum > 0, 13, -13)
    out["long_term_pts"] = long_term_pts.astype(float)
    # Regime gate derived from the same factor: when the 200-SMA/momentum
    # regime agrees with a direction (long_term_pts strictly positive or
    # negative — it's never exactly 0 given the +-12/+-13 point values),
    # `run_backtest(use_regime_filter=True)` vetoes new entries against it.
    # See docs/BACKTEST_RESULTS.md — real-data testing showed the system
    # taking near-equal long/short trades on SPY through a sustained bull
    # market (15 short vs 12 long) without this gate.
    out["regime_bullish"] = out["long_term_pts"] > 0
    out["regime_bearish"] = out["long_term_pts"] < 0

    # ---- Factor 7 (optional): Chart Patterns — Double Top/Bottom, Head-and-
    # Shoulders/Inverse (+-pattern_weight, default 0 = inert) ----
    # See patterns.py module docstring for the evidence caveat: this factor
    # has a much weaker evidence base than the other six and defaults to
    # zero weight so it changes nothing until explicitly validated and
    # turned on (see docs/BACKTEST_RESULTS.md).
    detected = pat.detect_chart_patterns(
        df,
        left=p.pattern_pivot_left,
        right=p.pattern_pivot_right,
        tolerance_pct=p.pattern_tolerance_pct,
        trough_depth_pct=p.pattern_trough_depth_pct,
        max_pattern_bars=p.pattern_max_bars,
        breakout_window=p.pattern_breakout_window,
    )
    out["double_top_confirmed"] = detected["double_top_confirmed"]
    out["double_bottom_confirmed"] = detected["double_bottom_confirmed"]
    out["head_shoulders_confirmed"] = detected["head_shoulders_confirmed"]
    out["inverse_head_shoulders_confirmed"] = detected["inverse_head_shoulders_confirmed"]
    bullish_pattern = out["double_bottom_confirmed"] | out["inverse_head_shoulders_confirmed"]
    bearish_pattern = out["double_top_confirmed"] | out["head_shoulders_confirmed"]
    out["pattern_pts"] = np.where(bullish_pattern, p.pattern_weight, np.where(bearish_pattern, -p.pattern_weight, 0.0))

    out["net_score"] = (
        out["trend_pts"]
        + out["momentum_pts"]
        + out["volume_pts"]
        + out["vola_pts"]
        + out["bb_pts"]
        + out["long_term_pts"]
        + out["pattern_pts"]
    )

    out["regime"] = np.select(
        [
            out["net_score"] >= p.strong_buy_level,
            out["net_score"] >= p.buy_threshold,
            out["net_score"] <= p.strong_sell_level,
            out["net_score"] <= p.sell_threshold,
        ],
        ["STRONG_BUY", "BUY", "STRONG_SELL", "SELL"],
        default="NEUTRAL",
    )

    # ---- Signal trigger ----
    pair_map = {
        "fast_mid": ("ema_fast", "ema_mid"),
        "fast_slow": ("ema_fast", "ema_slow"),
        "mid_slow": ("ema_mid", "ema_slow"),
    }
    fast_col, slow_col = pair_map.get(p.ema_cross_pair, pair_map["fast_mid"])
    a, b = out[fast_col], out[slow_col]
    a_prev, b_prev = a.shift(1), b.shift(1)
    ema_cross_up = (a_prev <= b_prev) & (a > b)
    ema_cross_down = (a_prev >= b_prev) & (a < b)
    out["ema_cross_up"] = ema_cross_up
    out["ema_cross_down"] = ema_cross_down

    prev_score = out["net_score"].shift(1)
    score_cross_long = (prev_score <= p.buy_threshold) & (out["net_score"] > p.buy_threshold)
    score_cross_short = (prev_score >= p.sell_threshold) & (out["net_score"] < p.sell_threshold)

    if p.trigger_mode == "ema_cross_confluence":
        out["long_signal"] = ema_cross_up & (out["net_score"] >= p.ema_confirm_score)
        out["short_signal"] = ema_cross_down & (out["net_score"] <= -p.ema_confirm_score)
    else:
        out["long_signal"] = score_cross_long
        out["short_signal"] = score_cross_short

    out["exit_long_signal"] = out["net_score"] < p.exit_long_score
    out["exit_short_signal"] = out["net_score"] > p.exit_short_score

    return out


def add_htf_filter(
    df: pd.DataFrame, rule: str = "W", ema_fast: int = 20, ema_slow: int = 50
) -> pd.DataFrame:
    """Approximate the Pine script's request.security() multi-timeframe filter.

    Resamples close price to a higher timeframe (`rule`, e.g. "W" for weekly
    on daily data, or "4H" on intraday data), computes the EMA-fast/EMA-slow
    trend on that timeframe, and forward-fills it back onto the original
    index. The higher-timeframe trend is shifted by one completed bar before
    filling so a signal never sees a still-forming higher-timeframe candle
    (no lookahead bias) — the same guarantee `barmerge.lookahead_off` gives
    the Pine script.

    Adds columns: htf_bullish, htf_bearish (bool).
    """
    out = df.copy()
    htf = out[["close"]].resample(rule).last().dropna()
    htf_ema_fast = ind.ema(htf["close"], ema_fast)
    htf_ema_slow = ind.ema(htf["close"], ema_slow)
    htf_bullish = (htf_ema_fast > htf_ema_slow).shift(1)

    aligned = htf_bullish.reindex(out.index, method="ffill")
    known = aligned.notna()
    out["htf_bullish"] = (aligned.fillna(False)) & known
    out["htf_bearish"] = (~aligned.fillna(True)) & known
    return out


def compute_breadth(breadth_df: pd.DataFrame, sma_len: int = 200) -> pd.DataFrame:
    """Market-breadth regime from a reference index/ETF (SPY by default) —
    distinct from a ticker's own Long-Term Regime factor, which only looks at
    that ticker's own price. The idea: don't short an individual name just
    because its own chart looks weak if the broad market itself is still in
    an uptrend, and vice versa for longs against a weak broad market.

    Same rule as the Long-Term Regime factor for consistency (Faber SMA
    timing) — close > its own sma_len-period SMA — applied to the reference
    ticker's data instead of the traded ticker's.

    Returns a DataFrame indexed by date with breadth_bullish / breadth_bearish
    (bool) columns, meant to be aligned onto a traded ticker's index via
    `run_backtest(breadth=..., use_breadth_filter=True)`.
    """
    out = pd.DataFrame(index=breadth_df.index)
    sma = ind.sma(breadth_df["close"], sma_len)
    out["breadth_bullish"] = breadth_df["close"] > sma
    out["breadth_bearish"] = breadth_df["close"] < sma
    return out
