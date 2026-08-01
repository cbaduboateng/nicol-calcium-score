"""Insider-buying overlay: SEC Form 4 signal for the picker and gems.

Replaces the retired congressional overlay. Corporate insider buying is
everything congressional trading wasn't:

  - Filed within 2 business days (STOCK Act filings lag up to 45 days)
  - Direct information — executives buying their OWN company on the
    open market, not a diversified portfolio someone else manages
  - Free and official (SEC Form 4, surfaced via OpenInsider's screener)
  - Academically robust: clustered open-market buying by senior
    insiders is one of the most persistent documented anomalies
    (Lakonishok & Lee 2001 and successors)

``build_insider_overlay`` is pure (transactions in, overlay out) so the
signal logic is fully testable; ``load_insider_overlay`` wraps it with
the network fetch and a 12h disk cache, degrading to the stale cache
and then to {} so the dashboard never blocks on OpenInsider.

Like every overlay: soft weight in the composite, NEVER a gate.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_TTL_HOURS = 12.0
LOOKBACK_DAYS = 90
MIN_TXN_VALUE_USD = 25_000.0


def build_insider_overlay(
    transactions: list,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    window_days: int = LOOKBACK_DAYS,
) -> dict[str, dict]:
    """Score each ticker's insider activity. Pure — no I/O.

    Returns {ticker: {score, n_buyers, n_senior, total_bought_usd,
    last_buy_days, summary}} for tickers with a non-zero composite.
    """
    from .scoring.insider import score_insider_buying

    as_of_d = as_of or date.today()
    universe = {t.upper() for t in tickers} if tickers else None

    by_ticker: dict[str, list] = {}
    for t in transactions:
        tk = t.ticker.upper()
        if universe is not None and tk not in universe:
            continue
        by_ticker.setdefault(tk, []).append(t)

    overlay: dict[str, dict] = {}
    for tk, txns in by_ticker.items():
        score = score_insider_buying(
            txns, ticker=tk, as_of=as_of_d, window_days=window_days,
        )
        if score.composite <= 0:
            continue
        buys = [
            t for t in txns
            if t.direction == "buy" and t.is_open_market
            and (as_of_d - t.transaction_date).days <= window_days
        ]
        total_bought = sum(t.value_usd for t in buys)
        last_buy_days = (
            min((as_of_d - t.transaction_date).days for t in buys)
            if buys else None
        )
        bits = [
            f"{score.n_distinct_buyers} insider"
            f"{'s' if score.n_distinct_buyers != 1 else ''} bought "
            f"${total_bought:,.0f}"
        ]
        if score.n_senior_buyers:
            bits.append(f"{score.n_senior_buyers} C-suite")
        if last_buy_days is not None:
            bits.append(f"last buy {last_buy_days}d ago")
        overlay[tk] = {
            "score": float(score.composite),
            "n_buyers": int(score.n_distinct_buyers),
            "n_senior": int(score.n_senior_buyers),
            "total_bought_usd": float(total_bought),
            "last_buy_days": last_buy_days,
            "summary": " · ".join(bits),
        }
    return overlay


def load_insider_overlay(
    *,
    cache_dir: Path | str = "data/cache",
    max_age_hours: float = CACHE_TTL_HOURS,
) -> dict[str, dict]:
    """Fetch + score + cache. Serves the cache within TTL; falls back to
    a stale cache (any age) when OpenInsider is unreachable; {} only when
    there has never been a successful fetch."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "insider_overlay.json"

    if cache_file.exists():
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600.0
        if age_h < max_age_hours:
            try:
                return json.loads(cache_file.read_text())
            except Exception:  # noqa: BLE001
                pass

    try:
        from .ingest.insider import fetch_recent_transactions
        txns = fetch_recent_transactions(
            lookback_days=LOOKBACK_DAYS,
            minimum_value_usd=MIN_TXN_VALUE_USD,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Insider fetch raised (%s)", exc)
        txns = []

    if not txns:
        # Stale cache beats nothing.
        if cache_file.exists():
            try:
                log.info("Insider fetch empty — serving stale overlay cache")
                return json.loads(cache_file.read_text())
            except Exception:  # noqa: BLE001
                pass
        return {}

    overlay = build_insider_overlay(txns)
    try:
        cache_file.write_text(json.dumps(overlay))
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not persist insider overlay (%s)", exc)
    log.info("Insider overlay built: %d tickers with active buying", len(overlay))
    return overlay
