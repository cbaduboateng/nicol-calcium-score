"""Absolute-momentum trend filter — pre-registered ledger experiment #2.

Hypothesis (ledger id: trend-filter-defensive): holding the index only
while it trades above its long-term trend, and cash otherwise, avoids
the deep drawdowns without giving up much return. This is a DEFENSIVE
claim, so the bar differs from return-seeking experiments.

Pre-registered design (written 2026-08-09, before running):
  - Instrument: SPY, 10 years of daily closes (the committed ETF cache).
  - Variants: 10-month SMA (Faber's classic, month-end evaluation),
    200-day SMA (month-end evaluation), and 12-month absolute momentum
    (hold when trailing 12m total return > 0).
  - Cash earns ZERO while out (conservative — T-bills would flatter it).
  - Costs: 0.10% per one-way trade on each switch.
  - Verdict bar, BOTH halves at >= 36 months per half:
      max drawdown at least 25% shallower than buy-and-hold (relative),
      AND CAGR within 3 percentage points of buy-and-hold.
    Protection that costs more than 3pts/yr is insurance nobody renews;
    'protection' that only worked in one half is a coin that landed well.

Pure functions; no I/O.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_COST_PCT = 0.10
MIN_MONTHS_PER_HALF = 36
DRAWDOWN_IMPROVEMENT = 0.25    # relative reduction required
CAGR_TOLERANCE_PTS = 3.0


@dataclass(frozen=True)
class TrendVariant:
    name: str
    kind: str            # 'sma_months' | 'sma_days' | 'abs_momentum'
    window: int


DEFAULT_TREND_VARIANTS: tuple[TrendVariant, ...] = (
    TrendVariant("filter: 10-month SMA", "sma_months", 10),
    TrendVariant("filter: 200-day SMA", "sma_days", 200),
    TrendVariant("filter: 12m absolute momentum", "abs_momentum", 252),
)


def _month_end_positions(idx: pd.DatetimeIndex) -> list[int]:
    if len(idx) == 0:
        return []
    keys = idx.to_period("M")
    out = [i for i in range(len(idx) - 1) if keys[i] != keys[i + 1]]
    out.append(len(idx) - 1)
    return out


def trend_filter_monthly(
    prices: pd.Series,
    variant: TrendVariant,
    *,
    cost_pct: float = DEFAULT_COST_PCT,
) -> pd.Series:
    """Monthly net returns of the filtered strategy on one instrument.

    Signal is evaluated at each month-end using data up to that close;
    the position (in or out) applies to the FOLLOWING month. Cash = 0%.
    """
    px = prices.dropna().sort_index()
    if px.empty:
        return pd.Series(dtype=float)
    me = _month_end_positions(px.index)
    if len(me) < 3:
        return pd.Series(dtype=float)

    monthly: dict[pd.Timestamp, float] = {}
    prev_in = False
    for a, b in zip(me[:-1], me[1:]):
        close_a = float(px.iloc[a])
        if variant.kind == "sma_months":
            month_closes = px.iloc[[p for p in me if p <= a]]
            if len(month_closes) < variant.window:
                continue
            signal_in = close_a > float(
                month_closes.iloc[-variant.window:].mean())
        elif variant.kind == "sma_days":
            if a + 1 < variant.window:
                continue
            signal_in = close_a > float(
                px.iloc[a + 1 - variant.window:a + 1].mean())
        elif variant.kind == "abs_momentum":
            if a < variant.window:
                continue
            past = float(px.iloc[a - variant.window])
            signal_in = past > 0 and close_a / past - 1.0 > 0.0
        else:
            raise ValueError(f"unknown trend variant kind: {variant.kind}")

        gross = float(px.iloc[b]) / close_a - 1.0 if signal_in else 0.0
        switch_cost = (cost_pct / 100.0) if signal_in != prev_in else 0.0
        monthly[px.index[b]] = gross - switch_cost
        prev_in = signal_in
    return pd.Series(monthly).sort_index()


def _summarise(name: str, r: pd.Series, midpoint: pd.Timestamp) -> dict:
    if r.empty:
        return {"variant": name, "n_months": 0, "cagr_pct": np.nan,
                "max_drawdown_pct": np.nan, "pct_in_market": np.nan,
                "n_first": 0, "cagr_first_pct": np.nan, "dd_first_pct": np.nan,
                "n_second": 0, "cagr_second_pct": np.nan, "dd_second_pct": np.nan}

    def _cagr(rr: pd.Series) -> float:
        if rr.empty:
            return np.nan
        eq = (1.0 + rr).cumprod()
        years = max(len(rr) / 12.0, 1e-9)
        return float((float(eq.iloc[-1]) ** (1.0 / years) - 1.0) * 100.0)

    def _dd(rr: pd.Series) -> float:
        if rr.empty:
            return np.nan
        eq = (1.0 + rr).cumprod()
        return float((eq / eq.cummax() - 1.0).min() * 100.0)

    first, second = r[r.index <= midpoint], r[r.index > midpoint]
    return {
        "variant": name,
        "n_months": len(r),
        "cagr_pct": _cagr(r),
        "max_drawdown_pct": _dd(r),
        "pct_in_market": float((r != 0.0).mean() * 100.0),
        "n_first": len(first),
        "cagr_first_pct": _cagr(first),
        "dd_first_pct": _dd(first),
        "n_second": len(second),
        "cagr_second_pct": _cagr(second),
        "dd_second_pct": _dd(second),
    }


def compare_trend_filters(
    prices: pd.Series,
    variants: tuple[TrendVariant, ...] = DEFAULT_TREND_VARIANTS,
    *,
    cost_pct: float = DEFAULT_COST_PCT,
) -> pd.DataFrame:
    """Buy-and-hold control + each filter variant, with halves split."""
    px = prices.dropna().sort_index()
    if px.empty:
        return pd.DataFrame()
    d0, d1 = px.index.min(), px.index.max()
    midpoint = d0 + (d1 - d0) / 2

    me = _month_end_positions(px.index)
    bh = px.iloc[me].pct_change().dropna()
    rows = [_summarise("control: buy & hold", bh, midpoint)]
    for v in variants:
        rows.append(_summarise(
            v.name, trend_filter_monthly(px, v, cost_pct=cost_pct), midpoint,
        ))
    return pd.DataFrame(rows)


def trend_verdict(table: pd.DataFrame) -> pd.DataFrame:
    """Apply the pre-registered DEFENSIVE bar (see module docstring)."""
    if table.empty:
        return table
    ctrl = table[table["variant"].str.startswith("control")]
    if ctrl.empty:
        return table.iloc[0:0]
    c = ctrl.iloc[0]
    cand = table[~table["variant"].str.startswith("control")]
    ok = (
        (cand["n_first"] >= MIN_MONTHS_PER_HALF)
        & (cand["n_second"] >= MIN_MONTHS_PER_HALF)
        # materially shallower drawdowns in BOTH halves (dd is negative)
        & (cand["dd_first_pct"] >= float(c["dd_first_pct"])
           * (1.0 - DRAWDOWN_IMPROVEMENT))
        & (cand["dd_second_pct"] >= float(c["dd_second_pct"])
           * (1.0 - DRAWDOWN_IMPROVEMENT))
        # without giving up much return in EITHER half
        & (cand["cagr_first_pct"] >= float(c["cagr_first_pct"]) - CAGR_TOLERANCE_PTS)
        & (cand["cagr_second_pct"] >= float(c["cagr_second_pct"]) - CAGR_TOLERANCE_PTS)
    )
    return cand[ok]
