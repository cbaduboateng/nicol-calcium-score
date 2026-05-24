"""Catalyst calendar.

Combines four free sources into a per-ticker forward calendar:

1. Congress.gov: committee hearings + bill markup schedules
2. FDA: PDUFA action dates (drug approvals)
3. USAspending.gov: recent and pending federal contract awards
4. DoD: quarterly contract obligation cycles (deterministic)

Each entry has a date, a ticker, a coarse category, and a short rationale.
The catalyst-residual scoring layer joins this calendar with the trade tape:
if a trade is on a ticker with a pending catalyst within the lookahead
window, that trade scores higher; if the catalyst has already fired, the
trade is demoted.

The Congress.gov and FDA endpoints are stubbed pending API-key plumbing;
the DoD and USAspending paths are implemented. All paths return an empty
list (not an exception) on failure.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..ingest.usaspending import RECIPIENT_TICKER_MAP, fetch_awards

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalystEvent:
    event_date: date
    ticker: str
    category: str
    source: str
    rationale: str


# ---------------------------------------------------------------------------
# DoD obligation cycle: quarterly close dates are public and deterministic.
# Defence primes routinely beat consensus when fiscal year-end obligations
# get awarded in late Q4 / early Q1.
# ---------------------------------------------------------------------------

DEFENCE_TICKERS = ("LMT", "RTX", "NOC", "GD", "HII", "LDOS", "BAH", "CACI", "SAIC",
                   "TXT", "TDY", "AXON", "PLTR", "KTOS", "AVAV")


def dod_obligation_calendar(
    horizon: date,
    *,
    today: date | None = None,
) -> list[CatalystEvent]:
    today = today or date.today()
    events: list[CatalystEvent] = []
    cursor = date(today.year, 1, 1)
    while cursor <= horizon:
        # Federal fiscal year ends 30 September; the surge window is the last
        # two weeks of September.
        for ticker in DEFENCE_TICKERS:
            events.append(CatalystEvent(
                event_date=date(cursor.year, 9, 30),
                ticker=ticker,
                category="dod_obligation_cycle",
                source="dod_calendar",
                rationale=f"FY{cursor.year} year-end obligation surge",
            ))
        cursor = date(cursor.year + 1, 1, 1)
    return [e for e in events if today <= e.event_date <= horizon]


# ---------------------------------------------------------------------------
# USAspending: recent awards become catalysts on the announcement date.
# ---------------------------------------------------------------------------


def usaspending_catalysts(
    lookback_days: int = 90,
    *,
    today: date | None = None,
    minimum_award_usd: float = 50_000_000.0,
) -> list[CatalystEvent]:
    today = today or date.today()
    rows = fetch_awards(
        start=today - timedelta(days=lookback_days),
        end=today,
        minimum_award_usd=minimum_award_usd,
    )
    events: list[CatalystEvent] = []
    for r in rows:
        recipient = (r.get("Recipient Name") or "").upper()
        ticker = RECIPIENT_TICKER_MAP.get(recipient)
        if ticker is None:
            continue
        date_raw = r.get("Period of Performance Start Date") or ""
        try:
            event_date = date.fromisoformat(date_raw[:10])
        except ValueError:
            continue
        events.append(CatalystEvent(
            event_date=event_date,
            ticker=ticker,
            category="federal_award",
            source="usaspending",
            rationale=f"${r.get('Award Amount', 0):,.0f} contract to {recipient}",
        ))
    return events


# ---------------------------------------------------------------------------
# Congress.gov: hearings calendar (requires API key).
# ---------------------------------------------------------------------------


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _congress_get(url: str, api_key: str, timeout: float = 30.0) -> dict[str, Any]:
    resp = requests.get(url, params={"api_key": api_key, "format": "json"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def congress_hearings(
    horizon_days: int = 30,
    *,
    api_key: str | None = None,
) -> list[CatalystEvent]:
    api_key = api_key or os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        log.info("CONGRESS_API_KEY not set; skipping Congress.gov hearings")
        return []
    try:
        payload = _congress_get(
            "https://api.congress.gov/v3/committee-meeting",
            api_key=api_key,
        )
    except Exception as exc:
        log.warning("Congress.gov fetch failed (%s)", exc)
        return []
    events: list[CatalystEvent] = []
    today = date.today()
    horizon = today + timedelta(days=horizon_days)
    for m in payload.get("committeeMeetings", []) or []:
        date_raw = m.get("date") or m.get("updateDate") or ""
        try:
            event_date = date.fromisoformat(date_raw[:10])
        except ValueError:
            continue
        if not (today <= event_date <= horizon):
            continue
        # Without a per-meeting subject mapping, attach to the broad defence
        # bucket; replace with bill-text → ticker resolution.
        for ticker in DEFENCE_TICKERS:
            events.append(CatalystEvent(
                event_date=event_date,
                ticker=ticker,
                category="committee_hearing",
                source="congress_gov",
                rationale=m.get("title", "committee meeting"),
            ))
    return events


# ---------------------------------------------------------------------------
# FDA: PDUFA dates (stubbed; the open data feed is brittle).
# ---------------------------------------------------------------------------


def fda_pdufa_calendar(*_, **__) -> list[CatalystEvent]:
    """Stubbed; FDA does not publish PDUFA dates in a stable open feed.
    Production users typically scrape company 8-Ks or buy a Biopharm Catalyst
    feed. Returns empty list."""
    return []


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def build_calendar(
    horizon_days: int = 90,
    *,
    today: date | None = None,
    sources: tuple[str, ...] = ("dod", "usaspending", "congress", "fda"),
) -> list[CatalystEvent]:
    today = today or date.today()
    horizon = today + timedelta(days=horizon_days)
    events: list[CatalystEvent] = []
    if "dod" in sources:
        events.extend(dod_obligation_calendar(horizon, today=today))
    if "usaspending" in sources:
        events.extend(usaspending_catalysts(today=today))
    if "congress" in sources:
        events.extend(congress_hearings(horizon_days=horizon_days))
    if "fda" in sources:
        events.extend(fda_pdufa_calendar())
    events.sort(key=lambda e: e.event_date)
    return events


def by_ticker(events: list[CatalystEvent]) -> dict[str, list[CatalystEvent]]:
    out: dict[str, list[CatalystEvent]] = {}
    for e in events:
        out.setdefault(e.ticker, []).append(e)
    return out
