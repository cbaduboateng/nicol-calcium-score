"""£5k Runbook backtest: Xu-style concentrated momentum, replayed honestly.

Simulates a small account trading ONLY watchlist names under strict rules:

  Capital
  - Start capital (default £5,000), max 2 concurrent positions
  - Position size = equity / max_positions at entry (compounding), capped
    by available cash
  - Never average down; a single pyramid add is allowed on a WINNER

  Entry — all gates must pass on the signal day
  - Price crosses down into the analyst BUY ZONE (same crossing detection
    philosophy as track_record.py: prev close above entry, today at/below)
  - The stock's own 3-month momentum is positive (no falling knives)
  - The stock's THEME 3-month median momentum is positive (hot theme)
  - Reward-to-risk >= min_rr, where risk is the stop distance:
        rr = (target_exit - price) / (price * stop_pct)
  - Market cap under the cap ceiling (today's caps — see caveat)

  Managing
  - Hard stop at entry * (1 - stop_pct); cut same day it triggers
  - At +pyramid_trigger_pct the stop moves to breakeven and ONE add of
    pyramid_add_frac x initial cost is bought from cash
  - After the pyramid trigger, a close below the 10-day low exits
  - Sell into strength: a single day >= strength_day_pct while total
    gain >= strength_total_pct exits at that close
  - Analyst target_exit reached exits; timeout_days force-closes

Honest caveats (surfaced in the UI):
  - Today's market caps and today's analyst targets are applied to
    historical dates — a fair approximation, not literal history.
  - Daily closes only: stops and fills assume close-based execution,
    which understates intraday whipsaw on volatile microcaps.
  - One simulated path, no slippage/commissions. Treat results as an
    upper bound, not an expectation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from .watchlist_alerts import map_theme

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunbookParams:
    start_capital: float = 5_000.0
    max_positions: int = 2
    stop_pct: float = 0.12
    min_rr: float = 3.0
    pyramid_trigger_pct: float = 0.25
    pyramid_add_frac: float = 0.5      # add = this fraction of initial cost
    trail_lookback: int = 10           # 10-day-low trail, post-pyramid only
    strength_day_pct: float = 0.15     # single-day spike...
    strength_total_pct: float = 0.50   # ...while up this much overall → sell
    timeout_days: int = 180
    momentum_days: int = 63            # ~3 months of trading days
    require_positive_theme: bool = True
    max_market_cap_usd: float | None = 300_000_000.0
    require_known_cap: bool = True


def _prices_frame(
    price_history: dict[str, pd.Series], tickers: list[str],
) -> pd.DataFrame:
    cols: dict[str, pd.Series] = {}
    for t in tickers:
        s = price_history.get(t)
        if s is None or len(s) == 0:
            continue
        s = s.dropna()
        if s.empty:
            continue
        idx = pd.to_datetime(s.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        s = pd.Series(s.values, index=idx)
        cols[t] = s[~s.index.duplicated(keep="last")]
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index()


def _collect_signals(
    prices: pd.DataFrame,
    entry_map: dict[str, float],
    exit_map: dict[str, float],
    theme_map: dict[str, str],
    market_caps: dict[str, float] | None,
    params: RunbookParams,
) -> dict[pd.Timestamp, list[dict]]:
    """Pre-compute gated entry signals keyed by date."""
    mom = prices.pct_change(params.momentum_days, fill_method=None)

    # Per-theme median 3m momentum, computed across the theme's members.
    theme_mom: dict[str, pd.Series] = {}
    by_theme: dict[str, list[str]] = {}
    for t in prices.columns:
        by_theme.setdefault(theme_map.get(t, "Other"), []).append(t)
    for theme, members in by_theme.items():
        theme_mom[theme] = mom[members].median(axis=1)

    caps = market_caps or {}
    out: dict[pd.Timestamp, list[dict]] = {}
    for t in prices.columns:
        entry_target = entry_map.get(t)
        exit_target = exit_map.get(t)
        if entry_target is None or entry_target <= 0:
            continue
        if exit_target is None or exit_target <= 0:
            continue  # R:R gate needs a target — Xu rides TO something

        # Cap gate (today's caps — honest-caveat territory). Only applies
        # when the caller supplied cap data at all; a None market_caps map
        # means "no cap information available", not "everything is unknown".
        if params.max_market_cap_usd is not None and market_caps is not None:
            cap = caps.get(t)
            if cap is None:
                if params.require_known_cap:
                    continue
            elif cap > params.max_market_cap_usd:
                continue

        s = prices[t]
        prev = s.shift(1)
        crossing = (prev > entry_target) & (s <= entry_target)
        for d in s.index[crossing.fillna(False)]:
            p = float(s.at[d])
            if not np.isfinite(p) or p <= 0:
                continue
            # Momentum gate
            m = mom.at[d, t] if d in mom.index else np.nan
            if not np.isfinite(m) or m <= 0:
                continue
            # Theme gate
            if params.require_positive_theme:
                tm = theme_mom[theme_map.get(t, "Other")].get(d, np.nan)
                if not np.isfinite(tm) or tm <= 0:
                    continue
            # R:R gate — risk is the stop distance
            rr = (exit_target - p) / (p * params.stop_pct)
            if rr < params.min_rr:
                continue
            out.setdefault(d, []).append({
                "ticker": t, "price": p, "rr": float(rr),
                "target_exit": float(exit_target),
            })
    for d in out:
        out[d].sort(key=lambda x: -x["rr"])
    return out


def simulate_runbook(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    params: RunbookParams | None = None,
    *,
    market_caps: dict[str, float] | None = None,
) -> dict:
    """Run the account simulation. Returns {"trades", "equity", "stats"}."""
    params = params or RunbookParams()
    empty = {
        "trades": pd.DataFrame(), "equity": pd.DataFrame(),
        "stats": {
            "start_capital": params.start_capital,
            "final_equity": params.start_capital,
            "return_pct": 0.0, "max_drawdown_pct": 0.0,
            "n_closed": 0, "n_open": 0, "win_rate": 0.0,
            "avg_return_pct": 0.0, "best_return_pct": 0.0,
            "worst_return_pct": 0.0,
        },
    }
    if watchlist is None or watchlist.empty or not price_history:
        return empty

    entry_map: dict[str, float] = {}
    exit_map: dict[str, float] = {}
    theme_map: dict[str, str] = {}
    for _, row in watchlist.iterrows():
        t = str(row.get("ticker") or "").upper()
        if not t:
            continue
        e = row.get("target_entry")
        x = row.get("target_exit")
        if pd.notna(e) and float(e) > 0:
            entry_map[t] = float(e)
        if pd.notna(x) and float(x) > 0:
            exit_map[t] = float(x)
        theme_map[t] = map_theme(row.get("description"))

    tickers = [t for t in entry_map if t in exit_map]
    prices = _prices_frame(price_history, tickers)
    if prices.empty:
        return empty

    signals = _collect_signals(
        prices, entry_map, exit_map, theme_map, market_caps, params,
    )

    pf = prices.ffill()
    day_ret = prices.pct_change(fill_method=None)
    roll_low = prices.rolling(params.trail_lookback).min().shift(1)

    cash = params.start_capital
    positions: dict[str, dict] = {}
    closed: list[dict] = []
    equity_rows: list[dict] = []

    def _equity_at(d) -> float:
        val = cash
        for t, pos in positions.items():
            px = pf.at[d, t] if d in pf.index else np.nan
            if np.isfinite(px):
                val += pos["shares"] * float(px)
            else:
                val += pos["cost"]
        return float(val)

    def _close(pos: dict, d, px: float, reason: str) -> None:
        nonlocal cash
        proceeds = pos["shares"] * px
        cash += proceeds
        closed.append({
            "ticker": pos["ticker"],
            "entry_date": pos["entry_date"],
            "exit_date": d,
            "entry_price": pos["entry_price"],
            "exit_price": px,
            "cost": pos["cost"],
            "proceeds": proceeds,
            "return_pct": (proceeds - pos["cost"]) / pos["cost"] * 100.0,
            "days_held": (d - pos["entry_date"]).days,
            "reason": reason,
            "pyramided": pos["pyramided"],
        })

    for d in prices.index:
        exited_today: set[str] = set()

        # ---- manage open positions ------------------------------------
        for t in list(positions.keys()):
            pos = positions[t]
            px_raw = prices.at[d, t] if t in prices.columns else np.nan
            if not np.isfinite(px_raw):
                continue
            px = float(px_raw)
            gain = (px - pos["entry_price"]) / pos["entry_price"]
            dret = day_ret.at[d, t]
            reason = None
            if px <= pos["stop_price"]:
                reason = "stop" if not pos["breakeven"] else "breakeven-stop"
            elif px >= pos["target_exit"]:
                reason = "target"
            elif (np.isfinite(dret) and dret >= params.strength_day_pct
                    and gain >= params.strength_total_pct):
                reason = "strength"
            elif pos["pyramided"]:
                low = roll_low.at[d, t]
                if np.isfinite(low) and px < float(low):
                    reason = "trail"
            if reason is None and (d - pos["entry_date"]).days >= params.timeout_days:
                reason = "timeout"

            if reason is not None:
                _close(pos, d, px, reason)
                del positions[t]
                exited_today.add(t)
                continue

            # Pyramid: one add on the way up, stop to breakeven
            if not pos["pyramided"] and gain >= params.pyramid_trigger_pct:
                add_cost = min(cash, params.pyramid_add_frac * pos["initial_cost"])
                if add_cost > 0:
                    pos["shares"] += add_cost / px
                    pos["cost"] += add_cost
                    cash -= add_cost
                pos["pyramided"] = True
                pos["breakeven"] = True
                pos["stop_price"] = pos["entry_price"]

        # ---- entries ---------------------------------------------------
        if len(positions) < params.max_positions:
            for sig in signals.get(d, []):
                if len(positions) >= params.max_positions:
                    break
                t = sig["ticker"]
                if t in positions or t in exited_today:
                    continue
                equity_now = _equity_at(d)
                size = min(cash, equity_now / params.max_positions)
                if size < 1.0:
                    continue
                px = sig["price"]
                positions[t] = {
                    "ticker": t,
                    "entry_date": d,
                    "entry_price": px,
                    "shares": size / px,
                    "cost": size,
                    "initial_cost": size,
                    "stop_price": px * (1.0 - params.stop_pct),
                    "target_exit": sig["target_exit"],
                    "pyramided": False,
                    "breakeven": False,
                }
                cash -= size

        equity_rows.append({"date": d, "equity": _equity_at(d)})

    # ---- mark open positions at last close ------------------------------
    open_rows: list[dict] = []
    last_d = prices.index[-1]
    for t, pos in positions.items():
        px = pf.at[last_d, t]
        px = float(px) if np.isfinite(px) else pos["entry_price"]
        proceeds = pos["shares"] * px
        open_rows.append({
            "ticker": t,
            "entry_date": pos["entry_date"],
            "exit_date": None,
            "entry_price": pos["entry_price"],
            "exit_price": px,
            "cost": pos["cost"],
            "proceeds": proceeds,
            "return_pct": (proceeds - pos["cost"]) / pos["cost"] * 100.0,
            "days_held": (last_d - pos["entry_date"]).days,
            "reason": "open",
            "pyramided": pos["pyramided"],
        })

    trades = pd.DataFrame(closed + open_rows)
    equity = pd.DataFrame(equity_rows)

    final_equity = (
        float(equity["equity"].iloc[-1]) if not equity.empty
        else params.start_capital
    )
    if not equity.empty:
        eq = equity["equity"]
        max_dd = float((eq / eq.cummax() - 1.0).min() * 100.0)
    else:
        max_dd = 0.0

    closed_df = trades[trades["reason"] != "open"] if not trades.empty else pd.DataFrame()
    n_closed = len(closed_df)
    wins = int((closed_df["return_pct"] > 0).sum()) if n_closed else 0
    stats = {
        "start_capital": params.start_capital,
        "final_equity": final_equity,
        "return_pct": (final_equity / params.start_capital - 1.0) * 100.0,
        "max_drawdown_pct": max_dd,
        "n_closed": n_closed,
        "n_open": len(open_rows),
        "win_rate": (wins / n_closed) if n_closed else 0.0,
        "avg_return_pct": float(closed_df["return_pct"].mean()) if n_closed else 0.0,
        "best_return_pct": float(closed_df["return_pct"].max()) if n_closed else 0.0,
        "worst_return_pct": float(closed_df["return_pct"].min()) if n_closed else 0.0,
    }
    return {"trades": trades, "equity": equity, "stats": stats}
