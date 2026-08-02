"""Forward-marked track record: replays watchlist BUY ZONE crossings.

Pure functions. Given a watchlist (with target_entry / target_exit) and
historical daily-close prices, scan each ticker's history for moments
when the price crossed from above the entry target down to or below it
— that's a "signal" the live dashboard would have raised.

For each signal we then walk forward bar-by-bar until one of three
exit conditions fires:

  - **target** : price reaches target_exit (winning close)
  - **stop**   : price falls to entry × (1 − stop_pct) (losing close)
  - **timeout**: ``timeout_days`` elapse without target or stop (closed
                 at last-available price)

Signals that haven't yet fired their exit stay **open** and mark to
the most recent close.

This design is honest because:
  - No look-ahead: a signal's entry uses prices at or before the
    signal date, exits use prices strictly after.
  - No survivorship: every signal that fired in the window appears,
    winners and losers alike.
  - Reproducible: regenerates deterministically from price history,
    so no fragile cross-restart persistence is needed.

Caveat to surface in the UI: the replay assumes *today's* analyst
targets applied historically. If a target was updated in the CSV last
week, the entire history is rescored against the new level. That's a
fair approximation but not the real-world track of edits.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Position size only scales the dollar headlines, never the relative
# performance. \$10k per signal reads as a realistic personal notional;
# the slider allows anything.
DEFAULT_STOP_PCT: float = 0.10            # 10% below entry = stop
DEFAULT_TIMEOUT_DAYS: int = 180           # ~6 months
DEFAULT_COOLDOWN_DAYS: int = 30           # min gap between re-signals
DEFAULT_POSITION_SIZE_USD: float = 10_000.0


def _mark_forward(
    series: pd.Series,
    signal_date: date,
    entry_price: float,
    target_exit: float | None,
    target_stop: float,
    timeout_days: int,
    as_of: date,
) -> dict:
    """Walk forward from ``signal_date`` to the first exit trigger.

    Conservative tie-break: if a bar's daily range would have hit both
    target and stop, we assume the stop fired first. We can't tell from
    daily-close data; the conservative choice protects against
    over-stating performance.
    """
    timeout_d = signal_date + timedelta(days=timeout_days)
    after = series[series.index > pd.Timestamp(signal_date)]

    for ts, price in after.items():
        d_date = ts.date() if hasattr(ts, "date") else ts
        if not np.isfinite(price):
            continue
        price = float(price)
        # Stop check first — conservative.
        if price <= target_stop:
            return {
                "close_date": d_date,
                "close_price": price,
                "close_reason": "stop",
                "return_pct": (price - entry_price) / entry_price * 100.0,
                "days_held": (d_date - signal_date).days,
                "open": False,
            }
        if target_exit is not None and price >= target_exit:
            return {
                "close_date": d_date,
                "close_price": price,
                "close_reason": "target",
                "return_pct": (price - entry_price) / entry_price * 100.0,
                "days_held": (d_date - signal_date).days,
                "open": False,
            }
        if d_date >= timeout_d:
            return {
                "close_date": d_date,
                "close_price": price,
                "close_reason": "timeout",
                "return_pct": (price - entry_price) / entry_price * 100.0,
                "days_held": (d_date - signal_date).days,
                "open": False,
            }

    # Still open — mark to the most recent available close.
    if not series.empty:
        last_price = float(series.iloc[-1])
        return {
            "close_date": None,
            "close_price": last_price,
            "close_reason": "open",
            "return_pct": (last_price - entry_price) / entry_price * 100.0,
            "days_held": (as_of - signal_date).days,
            "open": True,
        }
    return {
        "close_date": None, "close_price": None, "close_reason": "open",
        "return_pct": 0.0, "days_held": 0, "open": True,
    }


def detect_signals(
    ticker: str,
    history: pd.Series,
    target_entry: float,
    target_exit: float | None,
    *,
    stop_pct: float = DEFAULT_STOP_PCT,
    timeout_days: int = DEFAULT_TIMEOUT_DAYS,
    as_of: date | None = None,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> list[dict]:
    """For a single ticker, find every BUY ZONE crossing and mark each forward.

    A crossing is the transition from above ``target_entry`` to at-or-below
    it. Re-entries within ``cooldown_days`` are merged into the existing
    signal (avoids logging the same trade three times when a stock chops
    around the entry level).
    """
    if history is None or history.empty or target_entry is None or target_entry <= 0:
        return []
    as_of_d = as_of or date.today()
    series = history.dropna().sort_index()
    if series.empty:
        return []

    target_stop = target_entry * (1.0 - stop_pct)

    signals: list[dict] = []
    in_zone = bool(float(series.iloc[0]) <= target_entry)
    last_signal_date: date | None = (
        series.index[0].date() if (in_zone and hasattr(series.index[0], "date"))
        else None
    )
    if in_zone:
        sig = {
            "signal_date": last_signal_date,
            "ticker": ticker,
            "entry_price": float(series.iloc[0]),
            "target_entry": float(target_entry),
            "target_exit": float(target_exit) if target_exit is not None else None,
            "target_stop": float(target_stop),
        }
        sig.update(_mark_forward(
            series, last_signal_date, float(series.iloc[0]),
            target_exit, target_stop, timeout_days, as_of_d,
        ))
        signals.append(sig)

    prev_price = float(series.iloc[0])
    for ts, price in series.iloc[1:].items():
        if not np.isfinite(price):
            continue
        price = float(price)
        d_date = ts.date() if hasattr(ts, "date") else ts
        # Crossing into zone: prev was above entry, current is at or below.
        if prev_price > target_entry and price <= target_entry:
            if (last_signal_date is None
                    or (d_date - last_signal_date).days >= cooldown_days):
                entry_price = price
                sig = {
                    "signal_date": d_date,
                    "ticker": ticker,
                    "entry_price": entry_price,
                    "target_entry": float(target_entry),
                    "target_exit": (
                        float(target_exit) if target_exit is not None else None
                    ),
                    "target_stop": float(target_stop),
                }
                sig.update(_mark_forward(
                    series, d_date, entry_price,
                    target_exit, target_stop, timeout_days, as_of_d,
                ))
                signals.append(sig)
                last_signal_date = d_date
        prev_price = price

    return signals


def build_track_record(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    *,
    as_of: date | None = None,
    stop_pct: float = DEFAULT_STOP_PCT,
    timeout_days: int = DEFAULT_TIMEOUT_DAYS,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> pd.DataFrame:
    """Scan every watchlist ticker's price history for BUY ZONE signals
    and mark each forward to its exit.

    Returns a DataFrame with one row per signal, columns:
      signal_date, ticker, entry_price, target_entry, target_exit,
      target_stop, close_date, close_price, close_reason, return_pct,
      days_held, open
    """
    if watchlist is None or watchlist.empty or not price_history:
        return pd.DataFrame()
    all_signals: list[dict] = []
    for _, row in watchlist.iterrows():
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        entry = row.get("target_entry")
        exit_ = row.get("target_exit")
        if entry is None or not pd.notna(entry) or float(entry) <= 0:
            continue
        hist = price_history.get(ticker)
        if hist is None or len(hist) == 0:
            continue
        sigs = detect_signals(
            ticker, hist, float(entry),
            float(exit_) if pd.notna(exit_) else None,
            stop_pct=stop_pct, timeout_days=timeout_days,
            cooldown_days=cooldown_days, as_of=as_of,
        )
        all_signals.extend(sigs)

    if not all_signals:
        return pd.DataFrame()
    df = pd.DataFrame(all_signals)
    return df.sort_values("signal_date").reset_index(drop=True)


def summarise_track_record(
    signals: pd.DataFrame,
    *,
    position_size_usd: float = DEFAULT_POSITION_SIZE_USD,
) -> dict:
    """Headline stats for the track record card.

    Returns a dict with:
      total, open, closed
      win_rate          : fraction of CLOSED signals with return_pct > 0
      hit_rate          : fraction of CLOSED that hit target (not stop / timeout)
      avg_return_pct    : equal-weighted mean across closed
      total_realised_usd: sum(return_pct / 100 × position_size_usd)
      avg_days_held     : among closed
    """
    if signals.empty:
        return {
            "total": 0, "open": 0, "closed": 0,
            "win_rate": 0.0, "hit_rate": 0.0,
            "avg_return_pct": 0.0, "total_realised_usd": 0.0,
            "avg_days_held": 0.0,
        }
    total = len(signals)
    closed = signals[~signals["open"]]
    n_closed = len(closed)
    n_open = total - n_closed
    if n_closed == 0:
        return {
            "total": total, "open": n_open, "closed": 0,
            "win_rate": 0.0, "hit_rate": 0.0,
            "avg_return_pct": 0.0, "total_realised_usd": 0.0,
            "avg_days_held": 0.0,
        }
    wins = closed[closed["return_pct"] > 0]
    hits = closed[closed["close_reason"] == "target"]
    return {
        "total": total,
        "open": n_open,
        "closed": n_closed,
        "win_rate": float(len(wins) / n_closed),
        "hit_rate": float(len(hits) / n_closed),
        "avg_return_pct": float(closed["return_pct"].mean()),
        "total_realised_usd": float(
            (closed["return_pct"] / 100.0 * position_size_usd).sum()
        ),
        "avg_days_held": float(closed["days_held"].mean()),
    }


def cumulative_pnl_series(
    signals: pd.DataFrame,
    *,
    position_size_usd: float = DEFAULT_POSITION_SIZE_USD,
) -> pd.DataFrame:
    """Return a date-indexed DataFrame of cumulative realised P&L.

    Each closed signal contributes its realised P&L on its close_date;
    we then forward-fill so the line stays flat between closures.
    Useful for a chart on the track-record tab.
    """
    if signals.empty:
        return pd.DataFrame(columns=["close_date", "realised_usd", "cumulative_usd"])
    closed = signals[~signals["open"]].copy()
    if closed.empty:
        return pd.DataFrame(columns=["close_date", "realised_usd", "cumulative_usd"])
    closed = closed.dropna(subset=["close_date"]).copy()
    closed["realised_usd"] = closed["return_pct"] / 100.0 * position_size_usd
    by_day = (
        closed.groupby("close_date")["realised_usd"].sum().reset_index()
        .sort_values("close_date")
    )
    by_day["cumulative_usd"] = by_day["realised_usd"].cumsum()
    return by_day
