"""Post-earnings announcement drift — pre-registered ledger experiment #3.

Hypothesis (ledger id: pead-drift): after a clearly positive earnings
surprise, the price keeps drifting upward for weeks — the market
underreacts to the news.

Pre-registered design (written 2026-08-09, before any earnings data was
fetched):
  - Events: quarterly reports for the watchlist universe with a
    reported-vs-estimate EPS surprise. Positive arm: surprise >= +5%.
    Neutral CONTROL arm: surprise between -2% and +2% (same tickers,
    same mechanics — isolates the surprise itself).
  - Entry: the first close AFTER the report date (no same-day fills).
  - Hold: 20 sessions; net of a 0.30% round-trip cost.
  - Verdict bar: the positive arm's mean net return beats the neutral
    arm's in BOTH halves of the event window, with >= 30 events per arm
    per half. Below that sample the row stays 'monitoring'.

Pure functions; the earnings ingest lives in scripts/warm_earnings.py.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

POSITIVE_SURPRISE_PCT = 5.0
NEUTRAL_BAND_PCT = 2.0
HOLD_SESSIONS = 20
COST_PCT = 0.30
MIN_EVENTS_PER_HALF = 30
EARNINGS_CACHE_PATH = "data/cache/earnings_v1.parquet"


def event_returns(
    events: pd.DataFrame,
    price_history: dict[str, pd.Series],
    *,
    hold_sessions: int = HOLD_SESSIONS,
    cost_pct: float = COST_PCT,
) -> pd.DataFrame:
    """Net forward return per event (entry = first close AFTER the
    report; exit = ``hold_sessions`` later or last available close).

    ``events`` columns: ticker, date, surprise_pct.
    """
    rows: list[dict] = []
    if events is None or events.empty:
        return pd.DataFrame(rows)
    for _, ev in events.iterrows():
        t = str(ev["ticker"]).upper()
        s = price_history.get(t)
        if s is None:
            continue
        s = s.dropna().sort_index()
        if s.empty:
            continue
        d = pd.Timestamp(ev["date"])
        if getattr(d, "tz", None) is not None:
            d = d.tz_localize(None)
        pos = s.index.searchsorted(d, side="right")
        if pos >= len(s) - 1:
            continue                      # no forward window yet
        entry = float(s.iloc[pos])
        exit_pos = min(pos + hold_sessions, len(s) - 1)
        exit_px = float(s.iloc[exit_pos])
        if entry <= 0:
            continue
        rows.append({
            "ticker": t,
            "event_date": s.index[pos].date(),
            "surprise_pct": float(ev["surprise_pct"]),
            "return_pct": (exit_px / entry - 1.0) * 100.0 - cost_pct,
            "sessions_held": int(exit_pos - pos),
        })
    return pd.DataFrame(rows)


def compare_pead(
    events: pd.DataFrame,
    price_history: dict[str, pd.Series],
    *,
    positive_pct: float = POSITIVE_SURPRISE_PCT,
    neutral_band_pct: float = NEUTRAL_BAND_PCT,
    hold_sessions: int = HOLD_SESSIONS,
    cost_pct: float = COST_PCT,
) -> pd.DataFrame:
    """Positive-surprise arm vs neutral-surprise control, halves split."""
    marked = event_returns(
        events, price_history,
        hold_sessions=hold_sessions, cost_pct=cost_pct,
    )
    if marked.empty:
        return pd.DataFrame()
    marked["event_date"] = pd.to_datetime(marked["event_date"])
    d0, d1 = marked["event_date"].min(), marked["event_date"].max()
    midpoint = d0 + (d1 - d0) / 2

    arms = {
        f"positive surprise (≥ +{positive_pct:.0f}%)":
            marked[marked["surprise_pct"] >= positive_pct],
        f"control: neutral surprise (±{neutral_band_pct:.0f}%)":
            marked[marked["surprise_pct"].abs() <= neutral_band_pct],
    }
    out: list[dict] = []
    for name, arm in arms.items():
        first = arm[arm["event_date"] <= midpoint]
        second = arm[arm["event_date"] > midpoint]
        out.append({
            "arm": name,
            "n_events": len(arm),
            "mean_return_pct": float(arm["return_pct"].mean()) if len(arm) else np.nan,
            "median_return_pct": float(arm["return_pct"].median()) if len(arm) else np.nan,
            "win_rate": float((arm["return_pct"] > 0).mean()) if len(arm) else np.nan,
            "n_first": len(first),
            "mean_first_pct": float(first["return_pct"].mean()) if len(first) else np.nan,
            "n_second": len(second),
            "mean_second_pct": float(second["return_pct"].mean()) if len(second) else np.nan,
        })
    return pd.DataFrame(out)


def pead_verdict(table: pd.DataFrame) -> str:
    """'pass' | 'fail' | 'undersampled' against the pre-registered bar."""
    if table is None or len(table) < 2:
        return "undersampled"
    pos = table[~table["arm"].str.startswith("control")].iloc[0]
    ctrl = table[table["arm"].str.startswith("control")].iloc[0]
    if min(pos["n_first"], pos["n_second"],
           ctrl["n_first"], ctrl["n_second"]) < MIN_EVENTS_PER_HALF:
        return "undersampled"
    beats_both = (
        pos["mean_first_pct"] > ctrl["mean_first_pct"]
        and pos["mean_second_pct"] > ctrl["mean_second_pct"]
    )
    return "pass" if beats_both else "fail"
