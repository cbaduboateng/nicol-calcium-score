"""Momentum rotation across the ETF pool — the first 'proposed' ledger
experiment, pre-registered before any result was seen.

Hypothesis (ledger id: etf-momentum-rotation): rotating monthly into
the strongest few ETFs of a diversified sector/asset pool captures the
cross-sectional momentum premium after costs.

Pre-registered design (written 2026-08-09, before running):
  - Universe: the swing ETF pool (sector SPDRs, index, metals, bonds…),
    10 years of daily closes; ETFs enter the universe when they have
    enough history (no lookahead on listing dates).
  - Signal: at each month-end, rank by trailing ``lookback_days`` total
    return; hold the top ``top_k`` equal-weight for the next month.
  - Costs: ``cost_pct`` per ONE-WAY trade charged on turnover (a member
    swap costs two sides: one exit + one entry).
  - Controls: SPY buy-and-hold, and equal-weight-everything rebalanced
    monthly (same cost model).
  - Verdict bar: a variant is believed only if its mean monthly return
    beats BOTH controls in BOTH halves of the window with >= 36 months
    per half. Anything else goes to the ledger as rejected/monitoring.

Pure functions over a wide close-price DataFrame; no I/O.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_COST_PCT = 0.10       # per one-way trade, ETF-class costs
MIN_MONTHS_PER_HALF = 36


@dataclass(frozen=True)
class RotationVariant:
    name: str
    lookback_days: int = 126
    top_k: int = 3


DEFAULT_ROTATION_VARIANTS: tuple[RotationVariant, ...] = (
    RotationVariant("rotation: 3m lookback, top 3", 63, 3),
    RotationVariant("rotation: 6m lookback, top 3", 126, 3),
    RotationVariant("rotation: 12m lookback, top 3", 252, 3),
    RotationVariant("rotation: 6m lookback, top 5", 126, 5),
)


def _month_end_positions(idx: pd.DatetimeIndex) -> list[int]:
    """Positions of the last trading day of each month."""
    if len(idx) == 0:
        return []
    keys = idx.to_period("M")
    out: list[int] = []
    for i in range(len(idx) - 1):
        if keys[i] != keys[i + 1]:
            out.append(i)
    out.append(len(idx) - 1)
    return out


def momentum_rotation_backtest(
    prices: pd.DataFrame,
    *,
    lookback_days: int = 126,
    top_k: int = 3,
    cost_pct: float = DEFAULT_COST_PCT,
) -> pd.Series:
    """Monthly net return series for one rotation variant.

    A ticker is eligible at a rebalance only if it has ``lookback_days``
    of history by then — late-listed ETFs join when ready, no lookahead.
    """
    px = prices.sort_index()
    if px.empty:
        return pd.Series(dtype=float)
    me = _month_end_positions(px.index)
    if len(me) < 3:
        return pd.Series(dtype=float)

    monthly: dict[pd.Timestamp, float] = {}
    prev_hold: set[str] = set()
    for a, b in zip(me[:-1], me[1:]):
        t0 = px.index[a]
        window = px.iloc[max(0, a - lookback_days):a + 1]
        mom: dict[str, float] = {}
        for c in px.columns:
            col = window[c].dropna()
            if len(col) < lookback_days * 0.9:
                continue
            first, last = float(col.iloc[0]), float(col.iloc[-1])
            if first > 0 and np.isfinite(first) and np.isfinite(last):
                mom[c] = last / first - 1.0
        if len(mom) < top_k:
            prev_hold = set()
            continue
        hold = set(sorted(mom, key=mom.get, reverse=True)[:top_k])

        rets: list[float] = []
        for c in hold:
            p0, p1 = px[c].iloc[a], px[c].iloc[b]
            if pd.notna(p0) and pd.notna(p1) and float(p0) > 0:
                rets.append(float(p1) / float(p0) - 1.0)
        if not rets:
            prev_hold = hold
            continue
        gross = float(np.mean(rets))
        n_changed = len(hold - prev_hold)
        # Each swap = one exit + one entry, cost_pct per side, on the
        # changed fraction of the portfolio.
        cost = 2.0 * (cost_pct / 100.0) * (n_changed / top_k)
        monthly[px.index[b]] = gross - cost
        prev_hold = hold
    return pd.Series(monthly).sort_index()


def buy_and_hold_monthly(prices: pd.DataFrame, ticker: str) -> pd.Series:
    """Monthly returns of holding one ticker (control)."""
    if ticker not in prices.columns:
        return pd.Series(dtype=float)
    px = prices[ticker].dropna().sort_index()
    if px.empty:
        return pd.Series(dtype=float)
    me = _month_end_positions(px.index)
    vals = px.iloc[me]
    return vals.pct_change().dropna()


def equal_weight_monthly(
    prices: pd.DataFrame, *, cost_pct: float = DEFAULT_COST_PCT,
) -> pd.Series:
    """Equal-weight everything, rebalanced monthly (control). Rebalance
    turnover on an equal-weight book is small; costs are approximated as
    one side on 10% of the book per month."""
    px = prices.sort_index()
    if px.empty:
        return pd.Series(dtype=float)
    me = _month_end_positions(px.index)
    monthly: dict[pd.Timestamp, float] = {}
    for a, b in zip(me[:-1], me[1:]):
        rets: list[float] = []
        for c in px.columns:
            p0, p1 = px[c].iloc[a], px[c].iloc[b]
            if pd.notna(p0) and pd.notna(p1) and float(p0) > 0:
                rets.append(float(p1) / float(p0) - 1.0)
        if rets:
            monthly[px.index[b]] = float(np.mean(rets)) - (cost_pct / 100.0) * 0.1
    return pd.Series(monthly).sort_index()


def _summarise(name: str, r: pd.Series, midpoint: pd.Timestamp) -> dict:
    if r.empty:
        return {"variant": name, "n_months": 0, "mean_monthly_pct": np.nan,
                "cagr_pct": np.nan, "max_drawdown_pct": np.nan,
                "pct_positive_months": np.nan,
                "n_first": 0, "mean_first_pct": np.nan,
                "n_second": 0, "mean_second_pct": np.nan}
    eq = (1.0 + r).cumprod()
    dd = (eq / eq.cummax() - 1.0).min()
    years = max(len(r) / 12.0, 1e-9)
    first, second = r[r.index <= midpoint], r[r.index > midpoint]
    return {
        "variant": name,
        "n_months": len(r),
        "mean_monthly_pct": float(r.mean() * 100.0),
        "cagr_pct": float((float(eq.iloc[-1]) ** (1.0 / years) - 1.0) * 100.0),
        "max_drawdown_pct": float(dd * 100.0),
        "pct_positive_months": float((r > 0).mean() * 100.0),
        "n_first": len(first),
        "mean_first_pct": float(first.mean() * 100.0) if len(first) else np.nan,
        "n_second": len(second),
        "mean_second_pct": float(second.mean() * 100.0) if len(second) else np.nan,
    }


def compare_rotation(
    prices: pd.DataFrame,
    variants: tuple[RotationVariant, ...] = DEFAULT_ROTATION_VARIANTS,
    *,
    cost_pct: float = DEFAULT_COST_PCT,
    spy_ticker: str = "SPY",
) -> pd.DataFrame:
    """Variants + both controls, with the walk-forward halves split."""
    px = prices.sort_index()
    if px.empty:
        return pd.DataFrame()
    d0, d1 = px.index.min(), px.index.max()
    midpoint = d0 + (d1 - d0) / 2

    rows = [
        _summarise(f"control: {spy_ticker} buy & hold",
                   buy_and_hold_monthly(px, spy_ticker), midpoint),
        _summarise("control: equal weight, monthly",
                   equal_weight_monthly(px, cost_pct=cost_pct), midpoint),
    ]
    for v in variants:
        r = momentum_rotation_backtest(
            px, lookback_days=v.lookback_days, top_k=v.top_k,
            cost_pct=cost_pct,
        )
        rows.append(_summarise(v.name, r, midpoint))
    return pd.DataFrame(rows)


def rotation_verdict(table: pd.DataFrame) -> pd.DataFrame:
    """Apply the pre-registered bar: beat BOTH controls in BOTH halves
    at >= MIN_MONTHS_PER_HALF months per half. Returns passing rows."""
    if table.empty:
        return table
    ctrl = table[table["variant"].str.startswith("control")]
    if ctrl.empty:
        return table.iloc[0:0]
    c1 = float(ctrl["mean_first_pct"].max())
    c2 = float(ctrl["mean_second_pct"].max())
    cand = table[~table["variant"].str.startswith("control")]
    return cand[
        (cand["mean_first_pct"] > c1)
        & (cand["mean_second_pct"] > c2)
        & (cand["n_first"] >= MIN_MONTHS_PER_HALF)
        & (cand["n_second"] >= MIN_MONTHS_PER_HALF)
    ]
