"""OpenInsider (SEC Form 4) ingester for the Phase 1 insider-buying signal.

OpenInsider scrapes the SEC Form 4 filings and publishes a clean HTML
table at <https://openinsider.com/screener>. We hit their "latest insider
trades" screener with a tight date window and parse the rendered table
with pandas.

Fallbacks:
  - If OpenInsider is unreachable, returns an empty list and logs a
    warning. The pipeline keeps running; downstream `score_insider_buying`
    returns 0.0 for all tickers in that case.

Heads-up: scraping HTML is fragile. Long-term we should switch to the
official SEC EDGAR Form 4 XML feed, which is stable and rate-limit
friendly but more code to parse.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..scoring.insider import InsiderTransaction

log = logging.getLogger(__name__)

BASE_URL = "https://openinsider.com/screener"
USER_AGENT = "icarus/0.1 (research)"


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _fetch_html(params: dict[str, str], timeout: float = 30.0) -> str:
    resp = requests.get(
        BASE_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def _parse_dollar(s: Any) -> float:
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    raw = str(s).strip()
    if not raw:
        return 0.0
    # OpenInsider uses "+$1,234,567" / "-$1,234,567" formatting.
    sign = -1.0 if raw.startswith("-") else 1.0
    digits = "".join(c for c in raw if c.isdigit() or c == ".")
    try:
        return sign * float(digits) if digits else 0.0
    except ValueError:
        return 0.0


def _parse_int(s: Any) -> float:
    if s is None:
        return 0.0
    raw = "".join(c for c in str(s) if c.isdigit() or c == ".")
    try:
        return float(raw) if raw else 0.0
    except ValueError:
        return 0.0


def fetch_recent_transactions(
    *,
    lookback_days: int = 90,
    minimum_value_usd: float = 25_000.0,
    max_rows: int = 1000,
) -> list[InsiderTransaction]:
    """Pull recent open-market insider transactions from OpenInsider.

    The default returns the last 90 days of open-market buys ≥ $25k.
    On any failure the function returns []; the caller can decide whether
    to fall back to neutral scoring.
    """
    params: dict[str, str] = {
        # Date window: most recent `lookback_days`.
        "fd": str(lookback_days),
        "fdr": "",
        # Filter to open-market buys (purchase) only.
        "xp": "1",
        "xs": "0",
        # Min value filter.
        "vl": str(int(minimum_value_usd)),
        "vh": "",
        # Sort by value descending, page 1, big page size.
        "sortcol": "1",
        "cnt": str(max_rows),
        "page": "1",
    }
    try:
        html = _fetch_html(params)
    except Exception as exc:
        log.warning("OpenInsider fetch failed (%s); returning empty list", exc)
        return []

    try:
        # OpenInsider renders one large table inside #ftable. pandas finds it.
        import pandas as pd
        tables = pd.read_html(io.StringIO(html))
    except Exception as exc:
        log.warning("OpenInsider HTML parse failed (%s)", exc)
        return []

    if not tables:
        log.warning("OpenInsider returned no parseable tables")
        return []

    # The relevant table has columns including "Filing Date", "Trade Date",
    # "Ticker", "Insider Name", "Title", "Trade Type", "Price", "Qty",
    # "Owned", "ΔOwn", "Value".
    df = max(tables, key=len)  # heuristic: pick the largest one
    required = {"Trade Date", "Ticker", "Insider Name", "Title", "Trade Type", "Value"}
    if not required.issubset(set(df.columns)):
        log.warning(
            "OpenInsider table schema unexpected; got %s", list(df.columns)[:15],
        )
        return []

    out: list[InsiderTransaction] = []
    for _, row in df.iterrows():
        trade_type = str(row.get("Trade Type") or "").strip()
        if "P - Purchase" not in trade_type and "S - Sale" not in trade_type:
            continue
        direction = "buy" if "Purchase" in trade_type else "sell"
        ticker = str(row.get("Ticker") or "").strip().upper()
        if not ticker:
            continue
        date_raw = str(row.get("Trade Date") or "").strip()
        try:
            txn_date = datetime.strptime(date_raw[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        value = _parse_dollar(row.get("Value"))
        if value < minimum_value_usd:
            continue
        try:
            out.append(InsiderTransaction(
                ticker=ticker,
                insider_name=str(row.get("Insider Name") or "").strip(),
                insider_role=str(row.get("Title") or "").strip(),
                transaction_date=txn_date,
                direction=direction,  # type: ignore[arg-type]
                is_open_market=True,
                shares=_parse_int(row.get("Qty")),
                price=_parse_dollar(row.get("Price")),
                value_usd=value,
            ))
        except Exception as exc:
            log.debug("Skipping malformed row (%s)", exc)
            continue

    log.info("OpenInsider returned %d normalised transactions", len(out))
    return out


def fetch_for_tickers(
    tickers: list[str],
    *,
    lookback_days: int = 90,
    minimum_value_usd: float = 25_000.0,
) -> list[InsiderTransaction]:
    """Pull recent transactions then filter to the given ticker universe.
    Convenient when the caller already has the candidate ticker list."""
    universe = {t.upper() for t in tickers}
    all_txn = fetch_recent_transactions(
        lookback_days=lookback_days,
        minimum_value_usd=minimum_value_usd,
    )
    return [t for t in all_txn if t.ticker in universe]
