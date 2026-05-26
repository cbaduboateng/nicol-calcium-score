"""QuiverQuant congressional-trades adapter.

Real Quiver API requires an API key (env: ``QUIVER_API_KEY``). When the key is
missing or the request fails, falls back to the synthetic generator so the
pipeline remains runnable.

API docs: https://api.quiverquant.com/docs/
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..schema import AssetType, Direction, Owner, Trade

log = logging.getLogger(__name__)

_AMOUNT_BUCKETS: dict[str, tuple[float, float]] = {
    "$1,001 - $15,000": (1_001, 15_000),
    "$15,001 - $50,000": (15_001, 50_000),
    "$50,001 - $100,000": (50_001, 100_000),
    "$100,001 - $250,000": (100_001, 250_000),
    "$250,001 - $500,000": (250_001, 500_000),
    "$500,001 - $1,000,000": (500_001, 1_000_000),
    "$1,000,001 - $5,000,000": (1_000_001, 5_000_000),
    "$5,000,001 - $25,000,000": (5_000_001, 25_000_000),
    "$25,000,001 - $50,000,000": (25_000_001, 50_000_000),
    "$50,000,001 +": (50_000_001, 100_000_000),
}


def _parse_amount(raw: str | None) -> tuple[float, float]:
    if not raw:
        return (0.0, 0.0)
    return _AMOUNT_BUCKETS.get(raw.strip(), (0.0, 0.0))


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    # Strip any trailing time component so the date-only formats can match.
    head = raw.split("T")[0].split(" ")[0].strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _direction(raw: str | None) -> Direction:
    if not raw:
        return Direction.BUY
    key = raw.lower()
    if "purchase" in key or "buy" in key:
        return Direction.BUY
    if "partial" in key:
        return Direction.PARTIAL_SALE
    if "exchange" in key:
        return Direction.EXCHANGE
    return Direction.SELL


class QuiverClient:
    """Thin wrapper over the Quiver congressional-trades endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.quiverquant.com/beta",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("QUIVER_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("QUIVER_API_KEY not set")
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception_type((requests.RequestException,)),
    )
    def _fetch_raw(self, since: date) -> list[dict[str, Any]]:
        url = f"{self.base_url}/bulk/congresstrading"
        resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        log.info(
            "Quiver GET %s -> HTTP %d (%d bytes)",
            url, resp.status_code, len(resp.content),
        )
        resp.raise_for_status()
        rows = resp.json()
        log.info("Quiver bulk endpoint returned %d total rows", len(rows))
        if rows:
            sample = rows[0]
            log.info(
                "Sample row keys: %s; TransactionDate=%r",
                sorted(sample.keys())[:10], sample.get("TransactionDate"),
            )
        # Parse TransactionDate via the multi-format parser before comparing.
        # The raw API can return MM/DD/YYYY, YYYY-MM-DD, or ISO timestamps;
        # naive string comparison silently rejects non-ISO formats.
        filtered: list[dict[str, Any]] = []
        for r in rows:
            d = _parse_date(r.get("TransactionDate"))
            if d is not None and d >= since:
                filtered.append(r)
        log.info("After filtering to since=%s: %d rows", since.isoformat(), len(filtered))
        return filtered

    def congress_trades(self, since: date | None = None) -> list[Trade]:
        """Fetch and normalise trades since `since` (default: 90 days ago).

        Falls back to synthetic data on any failure so the pipeline always has
        something to chew on. The fallback is logged at WARNING.
        """
        since = since or (date.today() - timedelta(days=90))
        try:
            raw = self._fetch_raw(since)
        except Exception as exc:  # network down, key missing, schema drift
            log.warning("Quiver fetch failed (%s); using synthetic fallback", exc)
            from .synthetic import synthetic_trades
            return synthetic_trades(end=date.today())

        trades: list[Trade] = []
        for r in raw:
            txn = _parse_date(r.get("TransactionDate"))
            disc = _parse_date(r.get("ReportDate")) or txn
            if txn is None or disc is None:
                continue
            lo, hi = _parse_amount(r.get("Amount"))
            actor_id = r.get("BioguideID") or r.get("Representative") or "UNKNOWN"
            ticker = (r.get("Ticker") or "").upper()
            if not ticker:
                continue
            trades.append(Trade(
                trade_id=f"quiver-{actor_id}-{ticker}-{txn}-{r.get('Transaction', '')}",
                actor_id=str(actor_id),
                transaction_date=txn,
                disclosure_date=disc,
                ticker=ticker,
                asset_type=AssetType.STOCK,
                direction=_direction(r.get("Transaction")),
                amount_min_usd=lo,
                amount_max_usd=hi,
                owner=Owner.SELF,
                source="quiver",
                raw_source=r,
            ))
        return trades
