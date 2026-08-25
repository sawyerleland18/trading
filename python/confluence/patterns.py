"""Classical chart pattern detection — Double Top/Bottom and Head-and-Shoulders.

Unlike every other factor in this system, chart patterns have a much weaker
evidence base than academically-grounded rules (SMA timing, time-series
momentum). The one real academic anchor here is Lo, Mamaysky & Wang (2000),
"Foundations of Technical Analysis" (Journal of Finance), which used kernel
regression to algorithmically identify 10 classical patterns — including
Head-and-Shoulders and Double Top/Bottom — and tested whether their forward
returns were statistically distinguishable from the unconditional
distribution. This module implements a simpler, more tractable version of
that idea: pivot ("fractal") detection instead of kernel regression, plus
explicit geometric tolerance rules instead of a statistical fit. Started
with 2 pattern families (4 directional signals) rather than the full 10, to
prove the pipeline works and validate against real data before expanding —
see docs/BACKTEST_RESULTS.md.

Detection is a three-step pipeline:

1. **Pivots**: a bar is a pivot high if its high is the max of the
   `left`+`right`+1 bar window centered on it (a "fractal"/swing point) —
   only *knowable* `right` bars later, once the bars after it are seen.
   Matches Pine's built-in `ta.pivothigh(left, right)` exactly, so both
   implementations detect the same swing points from the same data.
2. **Zigzag**: consecutive same-direction pivots (two highs in a row with
   no low between them) are collapsed to just the more extreme one, so
   patterns can be matched against a strictly alternating High/Low/High/...
   sequence — the standard "zigzag" simplification.
3. **Pattern + breakout confirmation**: a pattern is only a *candidate*
   once its shape satisfies tolerance rules (peaks/shoulders close enough
   in price, a trough/head meaningfully deeper/higher). The actual
   directional *signal* doesn't fire until price closes through the
   pattern's neckline within `breakout_window` bars afterward — matching
   how these patterns are actually traded (wait for confirmation, not just
   the shape), and keeping detection point-in-time correct (no lookahead:
   every check only uses bars already confirmed as of that point).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def find_pivots(df: pd.DataFrame, left: int = 5, right: int = 5) -> tuple[pd.Series, pd.Series]:
    """Bool Series (aligned to df.index) marking pivot highs/lows at their
    OWN bar — not yet shifted for point-in-time use. A pivot at position i
    is only knowable once bar i+right has been seen; callers doing signal
    generation (not just plotting) must account for that lag themselves,
    same as `detect_chart_patterns` does internally.
    """
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    n = len(df)
    pivot_high = np.zeros(n, dtype=bool)
    pivot_low = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        window_high = high[i - left : i + right + 1]
        window_low = low[i - left : i + right + 1]
        if high[i] == window_high.max():
            pivot_high[i] = True
        if low[i] == window_low.min():
            pivot_low[i] = True
    return pd.Series(pivot_high, index=df.index), pd.Series(pivot_low, index=df.index)


def detect_chart_patterns(
    df: pd.DataFrame,
    left: int = 5,
    right: int = 5,
    tolerance_pct: float = 0.03,
    trough_depth_pct: float = 0.02,
    max_pattern_bars: int = 60,
    breakout_window: int = 20,
) -> pd.DataFrame:
    """Detect Double Top, Double Bottom, Head-and-Shoulders, and Inverse
    Head-and-Shoulders. Returns a DataFrame (aligned to df.index) with four
    bool columns, each True only on the bar where that pattern's neckline
    breakout *confirms* — the actionable signal bar, not the bar the shape
    finished forming.

    tolerance_pct: how close two peaks (or two shoulders) must be, as a
        fraction of their average price, to count as "comparable."
    trough_depth_pct: how far below (double top) / above (double bottom)
        the peaks/troughs the middle point must be, as a fraction of the
        peak/trough price — filters out two peaks with only a trivial dip
        between them.
    max_pattern_bars: longest span (in bars) allowed between the two outer
        points of a pattern before it's considered too spread out to count.
    breakout_window: how many bars after the pattern completes to wait for
        a neckline breakout before the candidate expires unconfirmed.
    """
    pivot_high, pivot_low = find_pivots(df, left, right)
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()

    # Confirmed-pivot events, sorted by the bar each is first knowable on
    # (pivot's own bar + right), not by the pivot's own bar.
    raw_events: list[list] = []
    for i in range(n):
        if pivot_high.iloc[i]:
            raw_events.append([i + right, i, float(high[i]), "H"])
        if pivot_low.iloc[i]:
            raw_events.append([i + right, i, float(low[i]), "L"])
    raw_events.sort(key=lambda e: (e[0], e[1]))

    # Zigzag: collapse consecutive same-direction pivots to the more extreme one.
    zigzag: list[list] = []
    for ev in raw_events:
        if zigzag and zigzag[-1][3] == ev[3]:
            if (ev[3] == "H" and ev[2] > zigzag[-1][2]) or (ev[3] == "L" and ev[2] < zigzag[-1][2]):
                zigzag[-1] = ev
            # else: less extreme than what's already recorded — discard ev
        else:
            zigzag.append(ev)

    out = {
        "double_top_confirmed": np.zeros(n, dtype=bool),
        "double_bottom_confirmed": np.zeros(n, dtype=bool),
        "head_shoulders_confirmed": np.zeros(n, dtype=bool),
        "inverse_head_shoulders_confirmed": np.zeros(n, dtype=bool),
    }

    def confirm_breakout(start_idx: int, neckline: float, direction: str, out_key: str) -> None:
        end_idx = min(start_idx + breakout_window, n - 1)
        for t in range(start_idx, end_idx + 1):
            if direction == "down" and close[t] < neckline:
                out[out_key][t] = True
                return
            if direction == "up" and close[t] > neckline:
                out[out_key][t] = True
                return

    for k in range(len(zigzag)):
        confirm_idx, _pivot_idx, _price, kind = zigzag[k]

        # ---- Double Top / Double Bottom: two same-kind pivots (k-2, k) with
        # an opposite-kind pivot between them (k-1) ----
        if k >= 2:
            p1, mid, p2 = zigzag[k - 2], zigzag[k - 1], zigzag[k]
            if p1[3] == p2[3] == kind and mid[3] != kind:
                bars_apart = p2[1] - p1[1]
                if 0 < bars_apart <= max_pattern_bars:
                    if kind == "H":
                        avg_peak = (p1[2] + p2[2]) / 2
                        if avg_peak > 0 and abs(p2[2] - p1[2]) / avg_peak <= tolerance_pct:
                            trough = mid[2]
                            min_peak = min(p1[2], p2[2])
                            if min_peak > 0 and (min_peak - trough) / min_peak >= trough_depth_pct:
                                confirm_breakout(confirm_idx, trough, "down", "double_top_confirmed")
                    else:  # kind == "L"
                        avg_trough = (p1[2] + p2[2]) / 2
                        if avg_trough > 0 and abs(p2[2] - p1[2]) / avg_trough <= tolerance_pct:
                            peak = mid[2]
                            max_trough = max(p1[2], p2[2])
                            if peak > 0 and (peak - max_trough) / peak >= trough_depth_pct:
                                confirm_breakout(confirm_idx, peak, "up", "double_bottom_confirmed")

        # ---- Head & Shoulders / Inverse: shoulder, trough, head, trough, shoulder ----
        if k >= 4:
            ls, t1, hd, t2, rs = zigzag[k - 4], zigzag[k - 3], zigzag[k - 2], zigzag[k - 1], zigzag[k]
            if ls[3] == hd[3] == rs[3] == kind and t1[3] != kind and t2[3] != kind:
                bars_apart = rs[1] - ls[1]
                if 0 < bars_apart <= max_pattern_bars * 2:
                    avg_shoulder = (ls[2] + rs[2]) / 2
                    shoulders_comparable = avg_shoulder > 0 and abs(rs[2] - ls[2]) / avg_shoulder <= tolerance_pct
                    if kind == "H" and hd[2] > ls[2] and hd[2] > rs[2] and shoulders_comparable:
                        # Neckline approximated as flat, at the HIGHER of the two troughs
                        # (conservative: price must decisively clear the tougher level).
                        neckline = max(t1[2], t2[2])
                        confirm_breakout(confirm_idx, neckline, "down", "head_shoulders_confirmed")
                    elif kind == "L" and hd[2] < ls[2] and hd[2] < rs[2] and shoulders_comparable:
                        neckline = min(t1[2], t2[2])
                        confirm_breakout(confirm_idx, neckline, "up", "inverse_head_shoulders_confirmed")

    return pd.DataFrame(out, index=df.index)
