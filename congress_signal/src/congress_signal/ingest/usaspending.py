"""USAspending.gov contract-award ingester.

The USAspending API is free and key-less. We hit the spending_by_award
endpoint to pull recent federal contract awards by recipient, then join
recipient name → ticker via a small static map (real production should
maintain a UEI→ticker lookup table).

API docs: https://api.usaspending.gov/docs/endpoints
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.usaspending.gov/api/v2"

# UEI / recipient name → ticker. Populate from your own mapping table for
# production; this static seed covers the asymmetric-filter universe.
RECIPIENT_TICKER_MAP: dict[str, str] = {
    "LOCKHEED MARTIN CORPORATION": "LMT",
    "RAYTHEON COMPANY": "RTX",
    "RTX CORPORATION": "RTX",
    "NORTHROP GRUMMAN SYSTEMS CORPORATION": "NOC",
    "GENERAL DYNAMICS CORPORATION": "GD",
    "L3HARRIS TECHNOLOGIES, INC.": "LHX",
    "LEIDOS, INC.": "LDOS",
    "BOOZ ALLEN HAMILTON INC.": "BAH",
    "CACI INTERNATIONAL INC": "CACI",
    "SCIENCE APPLICATIONS INTERNATIONAL CORPORATION": "SAIC",
    "PALANTIR USG, INC.": "PLTR",
    "AXON ENTERPRISE, INC.": "AXON",
    "KRATOS DEFENSE & SECURITY SOLUTIONS, INC.": "KTOS",
    "AEROVIRONMENT, INC.": "AVAV",
    "MERCURY SYSTEMS, INC.": "MRCY",
    "HUNTINGTON INGALLS INDUSTRIES, INC.": "HII",
    "TEXTRON INC.": "TXT",
    "TELEDYNE TECHNOLOGIES INCORPORATED": "TDY",
}


def normalise_recipient(name: str | None) -> str | None:
    if not name:
        return None
    upper = name.upper().strip()
    return RECIPIENT_TICKER_MAP.get(upper)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _post(url: str, body: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    resp = requests.post(url, json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_awards(
    start: date,
    end: date,
    *,
    minimum_award_usd: float = 1_000_000.0,
    recipients: list[str] | None = None,
    award_type_codes: tuple[str, ...] = ("A", "B", "C", "D"),
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return raw award rows. Falls back to an empty list on any failure.

    award_type_codes A/B/C/D are the standard contract families. Filtering on
    a recipient list is much faster when you know who you care about.
    """
    body: dict[str, Any] = {
        "filters": {
            "time_period": [{
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }],
            "award_type_codes": list(award_type_codes),
            "award_amounts": [{"lower_bound": minimum_award_usd}],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "recipient_id",
            "Award Amount",
            "Awarding Agency",
            "Awarding Sub Agency",
            "Description",
            "Period of Performance Start Date",
            "Period of Performance Current End Date",
            "Place of Performance State Code",
        ],
        "page": 1,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
    }
    if recipients:
        body["filters"]["recipient_search_text"] = recipients

    try:
        payload = _post(f"{BASE_URL}/search/spending_by_award/", body)
    except Exception as exc:
        log.warning("USAspending fetch failed (%s); returning empty list", exc)
        return []
    return payload.get("results", []) or []


def awards_by_ticker(
    start: date,
    end: date,
    **kwargs: Any,
) -> dict[str, float]:
    """Aggregate award dollars per ticker, joining via RECIPIENT_TICKER_MAP."""
    rows = fetch_awards(start, end, **kwargs)
    totals: dict[str, float] = {}
    for r in rows:
        ticker = normalise_recipient(r.get("Recipient Name"))
        if ticker is None:
            continue
        amount = r.get("Award Amount") or 0
        try:
            totals[ticker] = totals.get(ticker, 0.0) + float(amount)
        except (TypeError, ValueError):
            continue
    return totals
