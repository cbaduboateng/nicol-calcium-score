"""Core–satellite portfolio blueprint: 80% ETF core, 20% stock satellite.

Planning arithmetic, not prophecy. The core presets are sensible fixed
mixes from the ETF pool; their stats are computed from the committed
10-year cache (monthly rebalanced) and clearly labelled as HISTORY —
the past decade was unusually kind to US tech, and none of these mixes
is a return forecast. The blend identity the whole feature exists to
make visible:

    blend = core_weight × core + (1 − core_weight) × satellite

so a 20–25% blend target on top of a diversified core forces the 20%
satellite to compound at 40–90%/yr — world-class-and-then-some, every
year. The tool shows that number instead of letting it hide.

Rebalancing guidance uses simple 5-percentage-point drift bands — a
convention, not a Lab-validated claim, and labelled as such.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .portfolio import native_to_usd

log = logging.getLogger(__name__)

DEFAULT_CORE_WEIGHT = 0.80
DRIFT_BAND_PTS = 5.0

PRESET_CORES: dict[str, dict[str, float]] = {
    "Steady (equities + bonds + gold)": {
        "SPY": 0.40, "EFA": 0.15, "EEM": 0.05,
        "TLT": 0.20, "GLD": 0.10, "VNQ": 0.10,
    },
    "Balanced growth": {
        "SPY": 0.45, "QQQ": 0.20, "EFA": 0.10,
        "GLD": 0.10, "TLT": 0.10, "EEM": 0.05,
    },
    "Aggressive growth (tech-tilted)": {
        "QQQ": 0.35, "SPY": 0.25, "SMH": 0.15,
        "EFA": 0.10, "GLD": 0.10, "IWM": 0.05,
    },
}


def core_history_stats(
    prices: pd.DataFrame, weights: dict[str, float],
) -> dict | None:
    """CAGR / max drawdown / annualised vol of a monthly-rebalanced mix
    over the shared history of its members. None when data is missing."""
    cols = {t: prices[t].dropna() for t in weights if t in prices.columns}
    if len(cols) < len(weights):
        return None
    idx = None
    for s in cols.values():
        idx = s.index if idx is None else idx.intersection(s.index)
    f = pd.DataFrame({t: s.reindex(idx) for t, s in cols.items()}).dropna()
    if len(f) < 260:
        return None
    keys = f.index.to_period("M")
    me = [i for i in range(len(f) - 1) if keys[i] != keys[i + 1]]
    me.append(len(f) - 1)
    monthly = f.iloc[me].pct_change().dropna()
    port = sum(monthly[t] * w for t, w in weights.items())
    eq = (1.0 + port).cumprod()
    years = max(len(port) / 12.0, 1e-9)
    return {
        "cagr_pct": (float(eq.iloc[-1]) ** (1.0 / years) - 1.0) * 100.0,
        "max_drawdown_pct": float((eq / eq.cummax() - 1.0).min() * 100.0),
        "vol_pct": float(port.std() * np.sqrt(12) * 100.0),
        "years": years,
    }


def required_satellite_cagr(
    target_pct: float,
    core_cagr_pct: float,
    *,
    core_weight: float = DEFAULT_CORE_WEIGHT,
) -> float:
    """The CAGR the satellite must sustain for the blend to hit target."""
    sat_w = 1.0 - core_weight
    if sat_w <= 0:
        return float("nan")
    req = ((1.0 + target_pct / 100.0)
           - core_weight * (1.0 + core_cagr_pct / 100.0)) / sat_w - 1.0
    return req * 100.0


def classify_holdings(
    positions: pd.DataFrame,
    quotes: dict[str, dict],
    etf_symbols: set[str],
) -> dict:
    """Split current holdings into core (ETFs) vs satellite (stocks) by
    market value, using live quotes with cost fallback."""
    core_v = sat_v = 0.0
    core_names: list[str] = []
    sat_names: list[str] = []
    if positions is not None and not positions.empty:
        for _, p in positions.iterrows():
            t = str(p["ticker"]).upper()
            q = quotes.get(t) or {}
            px = q.get("price")
            v = native_to_usd(
                t, float(p["qty"]) * float(px)
                if px and pd.notna(px) else float(p["invested"]))
            if t in etf_symbols:
                core_v += v
                core_names.append(t)
            else:
                sat_v += v
                sat_names.append(t)
    total = core_v + sat_v
    return {
        "core_value": core_v,
        "satellite_value": sat_v,
        "total_value": total,
        "core_pct": core_v / total * 100.0 if total > 0 else 0.0,
        "satellite_pct": sat_v / total * 100.0 if total > 0 else 0.0,
        "core_names": sorted(core_names),
        "satellite_names": sorted(sat_names),
    }


def rebalance_hint(
    split: dict,
    *,
    core_weight: float = DEFAULT_CORE_WEIGHT,
    band_pts: float = DRIFT_BAND_PTS,
) -> str | None:
    """Plain-English drift note when outside the band; None inside it."""
    total = split.get("total_value", 0.0)
    if total <= 0:
        return None
    target_core_pct = core_weight * 100.0
    drift = split["core_pct"] - target_core_pct
    if abs(drift) <= band_pts:
        return None
    move = abs(drift) / 100.0 * total
    if drift < 0:
        return (f"Core is {split['core_pct']:.0f}% vs the {target_core_pct:.0f}% "
                f"target — moving ≈ {move:,.0f} from stocks into the core "
                "would restore the blueprint.")
    return (f"Core is {split['core_pct']:.0f}% vs the {target_core_pct:.0f}% "
            f"target — deploying ≈ {move:,.0f} of core into satellite ideas "
            "(as gems appear) would restore the blueprint.")


# ---------------------------------------------------------------------------
# The adopted plan (11 Aug 2026): per-wrapper caps + rotation lists.
# Chat decisions made executable — the app measures reality against THIS.
# ---------------------------------------------------------------------------

ADOPTED_PLAN: dict = {
    "SIPP": {
        "stock_cap_pct": 10.0,
        # core + capped tilt never count against the stock cap
        "core": {"VWRP", "EQQQ", "SGLN", "INRG.L"},
        "sell": ["SLNH", "MNTS", "WWR", "SNAP", "JKS", "SBET", "LITS",
                 "OMG.L", "YYAI"],
    },
    "ISA": {
        "stock_cap_pct": 20.0,
        "core": {"VWRP", "SGLN"},
        "sell": ["SRXH", "IREN", "SMR", "KITT"],
    },
}


def plan_progress(positions: pd.DataFrame, quotes: dict[str, dict]) -> dict:
    """Per wrapper: stock share vs cap, and the rotation checklist state
    (a sell-list ticker is 'done' once it no longer appears among that
    wrapper's holdings)."""
    out: dict = {}
    for wrapper, plan in ADOPTED_PLAN.items():
        rows = positions[positions.get("account", "") == wrapper] \
            if positions is not None and not positions.empty else pd.DataFrame()
        total = stock = 0.0
        held: set[str] = set()
        for _, p in rows.iterrows():
            t = str(p["ticker"]).upper()
            held.add(t)
            q = quotes.get(t) or {}
            px = q.get("price")
            v = native_to_usd(
                t, float(p["qty"]) * float(px)
                if px and pd.notna(px) else float(p["invested"]))
            total += v
            if t not in plan["core"]:
                stock += v
        stock_pct = stock / total * 100.0 if total > 0 else 0.0
        out[wrapper] = {
            "stock_pct": stock_pct,
            "cap_pct": plan["stock_cap_pct"],
            "over_cap": stock_pct > plan["stock_cap_pct"],
            "sell_pending": [t for t in plan["sell"] if t.upper() in held],
            "sell_done": [t for t in plan["sell"] if t.upper() not in held],
        }
    return out
