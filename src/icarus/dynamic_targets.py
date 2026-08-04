"""Dynamic, point-in-time entry levels from the analyst's own learned rule.

``target_inference`` answered *what rule generates the analyst's buy
targets* (entry ≈ ratio × an anchor — empirically the 52-week low, with
per-theme ratios). But the analyst applies that rule once and never
updates it, so the levels go stale as prices move: the staleness
detector shows dozens of targets the market left behind long ago.

This module evaluates the same rule **point-in-time**: each session's
entry level is ratio × the trailing 252-session low as of the *prior*
session (``shift(1)`` — no same-day look-ahead). The level then tracks
the market — rising as the base rises, resetting when the base breaks —
responsive instead of reactionary.

Adoption discipline (same as every gate change in this project):
dynamic entries redefine the signal, so they go through the Lab first.
``compare_entry_modes`` replays static analyst entries and dynamic
entries over the same history with the same gates and the same
walk-forward split; the evidence bar is unchanged — beat the static
control in BOTH halves before anything goes live. Until then the UI
only *surfaces* the refreshed level next to stale analyst targets.

Exit convention under dynamic entries: exit = entry × the learned exit
multiple (price-free given the entry, mirroring
``derive_exits_from_entries``). Note the R:R gate is vacuous under this
convention — (mult−1)/stop is a constant — so the comparison applies
momentum and theme gates only, and says so.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from .track_record import (
    DEFAULT_COOLDOWN_DAYS,
    DEFAULT_TIMEOUT_DAYS,
    _mark_forward,
)
from .watchlist_alerts import map_theme

log = logging.getLogger(__name__)

ROLLING_WINDOW_SESSIONS = 252   # ~52 trading weeks
MIN_HISTORY_SESSIONS = 60       # refuse to compute a level on less
LAB_STOP_PCT = 0.10             # entry-Lab convention: all entry
                                # comparisons mark forward with the 10%
                                # stop the entry set was validated at


def rolling_entry_series(
    history: pd.Series,
    ratio: float,
    *,
    window: int = ROLLING_WINDOW_SESSIONS,
    min_history: int = MIN_HISTORY_SESSIONS,
) -> pd.Series:
    """Point-in-time entry level: ratio × trailing ``window``-session low,
    shifted one session so today's level never sees today's close."""
    s = history.dropna().sort_index()
    if len(s) < min_history or ratio <= 0 or not np.isfinite(ratio):
        return pd.Series(dtype=float)
    return s.rolling(window, min_periods=min_history).min().shift(1) * ratio


def current_dynamic_entry(
    history: pd.Series,
    ratio: float,
    *,
    window: int = ROLLING_WINDOW_SESSIONS,
) -> float | None:
    """Today's refreshed entry level under the learned rule, or None."""
    lvl = rolling_entry_series(history, ratio, window=window)
    if lvl.empty:
        return None
    last = lvl.dropna()
    if last.empty:
        return None
    return float(last.iloc[-1])


def detect_signals_dynamic(
    ticker: str,
    history: pd.Series,
    ratio: float,
    exit_multiple: float,
    *,
    stop_pct: float = LAB_STOP_PCT,
    timeout_days: int = DEFAULT_TIMEOUT_DAYS,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    as_of: date | None = None,
    window: int = ROLLING_WINDOW_SESSIONS,
) -> list[dict]:
    """Find crossings below the *moving* entry level and mark each forward.

    A crossing is the transition from above yesterday's level to at or
    below today's. Exits: entry × ``exit_multiple`` target, entry-based
    stop, timeout — via the same conservative ``_mark_forward`` walker
    the static replay uses.
    """
    if history is None or history.dropna().empty:
        return []
    as_of_d = as_of or date.today()
    series = history.dropna().sort_index()
    levels = rolling_entry_series(series, ratio, window=window)
    if levels.empty:
        return []

    signals: list[dict] = []
    last_signal_date: date | None = None
    prev_price: float | None = None
    prev_level: float | None = None
    for ts, price in series.items():
        lvl = levels.get(ts, np.nan)
        if not np.isfinite(price) or not np.isfinite(lvl):
            prev_price, prev_level = price, lvl
            continue
        price, lvl = float(price), float(lvl)
        d_date = ts.date() if hasattr(ts, "date") else ts
        crossed = (
            prev_price is not None and prev_level is not None
            and np.isfinite(prev_level) and float(prev_price) > float(prev_level)
            and price <= lvl
        )
        if crossed and (
            last_signal_date is None
            or (d_date - last_signal_date).days >= cooldown_days
        ):
            target_exit = price * exit_multiple
            target_stop = price * (1.0 - stop_pct)
            sig = {
                "signal_date": d_date,
                "ticker": ticker,
                "entry_price": price,
                "target_entry": lvl,
                "target_exit": target_exit,
                "target_stop": target_stop,
            }
            sig.update(_mark_forward(
                series, d_date, price, target_exit, target_stop,
                timeout_days, as_of_d,
            ))
            signals.append(sig)
            last_signal_date = d_date
        prev_price, prev_level = price, lvl
    return signals


def _prices_frame(price_history: dict[str, pd.Series]) -> pd.DataFrame:
    from .signal_lab import _prices_frame as _pf
    return _pf(price_history)


def _summarise(name: str, sigs: pd.DataFrame, midpoint: pd.Timestamp) -> dict:
    if sigs.empty:
        return {
            "variant": name, "n_signals": 0, "n_closed": 0,
            "win_rate": np.nan, "avg_return_pct": np.nan,
            "median_return_pct": np.nan, "avg_days_held": np.nan,
            "n_train": 0, "avg_train_pct": np.nan,
            "n_test": 0, "avg_test_pct": np.nan,
        }
    closed = sigs[~sigs["open"]]
    sd = pd.to_datetime(sigs["signal_date"])
    train, test = sigs[sd <= midpoint], sigs[sd > midpoint]
    return {
        "variant": name,
        "n_signals": len(sigs),
        "n_closed": len(closed),
        "win_rate": float((closed["return_pct"] > 0).mean()) if len(closed) else np.nan,
        "avg_return_pct": float(closed["return_pct"].mean()) if len(closed) else np.nan,
        "median_return_pct": float(closed["return_pct"].median()) if len(closed) else np.nan,
        "avg_days_held": float(closed["days_held"].mean()) if len(closed) else np.nan,
        "n_train": len(train),
        "avg_train_pct": float(train["return_pct"].mean()) if len(train) else np.nan,
        "n_test": len(test),
        "avg_test_pct": float(test["return_pct"].mean()) if len(test) else np.nan,
    }


def compare_entry_modes(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    pattern: dict,
    *,
    as_of: date | None = None,
    momentum_days: int = 126,
) -> pd.DataFrame:
    """Static analyst entries vs dynamic point-in-time entries.

    Three arms, same prices, same walk-forward split:
      1. static  — analyst entries, validated 6m gate set (the control)
      2. dynamic — same tickers as (1), entry recomputed each session
      3. dynamic (full watchlist) — every priced ticker, analyst target
         or not: the coverage upside of a rule that needs no analyst

    Gates on the dynamic arms: own 6m momentum > 0 and theme 6m median
    > 0 at the signal date, identical to the control. The R:R gate is
    omitted on dynamic arms because exit = entry × multiple makes it a
    constant (stated here so nobody mistakes that for leniency).
    """
    from .signal_lab import SignalVariant, run_variant

    if watchlist is None or watchlist.empty or not price_history or not pattern:
        return pd.DataFrame()
    prices = _prices_frame(price_history)
    if prices.empty:
        return pd.DataFrame()
    d0, d1 = prices.index.min(), prices.index.max()
    midpoint = d0 + (d1 - d0) / 2

    has_analyst = watchlist["target_entry"].notna() & (watchlist["target_entry"] > 0)
    if "entry_source" in watchlist.columns:
        has_analyst &= watchlist["entry_source"].fillna("analyst").eq("analyst")
    analyst_rows = watchlist[has_analyst]

    static = run_variant(
        analyst_rows, price_history,
        SignalVariant("static", momentum_days=momentum_days),
        as_of=as_of,
    )

    mom = prices.pct_change(momentum_days, fill_method=None)
    theme_map = {
        str(r["ticker"]).upper(): map_theme(r.get("description"))
        for _, r in watchlist.iterrows()
    }
    by_theme: dict[str, list[str]] = {}
    for t in prices.columns:
        by_theme.setdefault(theme_map.get(t, "Other"), []).append(t)
    theme_mom = {th: mom[m].median(axis=1) for th, m in by_theme.items()}

    def _dynamic_signals(rows: pd.DataFrame) -> pd.DataFrame:
        out: list[dict] = []
        for _, row in rows.iterrows():
            ticker = str(row.get("ticker") or "").upper()
            hist = price_history.get(ticker)
            if hist is None or hist.dropna().empty:
                continue
            theme = theme_map.get(ticker, "Other")
            ratio = pattern.get("theme_entry_ratios", {}).get(
                theme, pattern["entry_ratio"],
            )
            mult = pattern.get("theme_exit_multiples", {}).get(
                theme, pattern["exit_multiple"],
            )
            for sig in detect_signals_dynamic(
                ticker, hist, ratio, mult, as_of=as_of,
            ):
                d = pd.Timestamp(sig["signal_date"])
                m = mom.at[d, ticker] if (d in mom.index and ticker in mom.columns) else np.nan
                if not np.isfinite(m) or m <= 0:
                    continue
                tm_series = theme_mom.get(theme)
                tm = tm_series.get(d, np.nan) if tm_series is not None else np.nan
                if not np.isfinite(tm) or tm <= 0:
                    continue
                out.append(sig)
        return pd.DataFrame(out)

    dyn_same = _dynamic_signals(analyst_rows)
    dyn_full = _dynamic_signals(watchlist)

    df = pd.DataFrame([
        _summarise("static: analyst entries (control)", static, midpoint),
        _summarise("dynamic: same tickers", dyn_same, midpoint),
        _summarise("dynamic: full watchlist", dyn_full, midpoint),
    ])
    return df
