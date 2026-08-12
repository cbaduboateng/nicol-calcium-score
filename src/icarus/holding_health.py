"""Dynamic holding assessment: a health card per open position.

Born directly from the thesis-exit-momentum experiment (ledger #25,
REJECTED): selling when the entry signal wobbles cut returns by a third
to four-fifths, because this universe's winners routinely look broken
mid-flight. So this module's charter is explicit:

    THE HEALTH CARD INFORMS. IT NEVER EXITS.

Exits remain exclusively: stop (depth), target (completion), timeout
(staleness) — plus written FACT falsifiers, the one Level-3 idea the
evidence endorses. The card automates the watchable part of those
falsifiers: nightly headline scans for dilution/going-concern/delisting
language on held names, surfaced as 🚨 flags that demand a human read —
never an automatic sale.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Headline language that historically precedes the true thesis-killers.
# A match is a FLAG for human reading, never an order.
FALSIFIER_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("offering", "dilution"),
    ("registered direct", "dilution"),
    ("private placement", "dilution"),
    ("at-the-market", "dilution"),
    ("dilut", "dilution"),
    ("going concern", "going-concern"),
    ("substantial doubt", "going-concern"),
    ("delist", "delisting"),
    ("non-compliance", "listing-compliance"),
    ("reverse split", "reverse-split"),
    ("reverse stock split", "reverse-split"),
    ("chapter 11", "bankruptcy"),
    ("bankruptcy", "bankruptcy"),
    ("resigns", "leadership-exit"),
    ("resignation", "leadership-exit"),
    ("investigation", "legal"),
    ("subpoena", "legal"),
    ("restatement", "accounting"),
)


def scan_falsifier_headlines(titles: list[str]) -> list[str]:
    """Match headline titles against falsifier language. Pure.
    Returns the distinct falsifier tags found."""
    tags: list[str] = []
    for title in titles or []:
        low = str(title).lower()
        for needle, tag in FALSIFIER_KEYWORDS:
            if needle in low and tag not in tags:
                tags.append(tag)
    return tags


def fetch_falsifier_flags(
    tickers: list[str], *, window_hours: float = 48.0,
) -> dict[str, dict]:
    """Nightly falsifier sweep over held names via yfinance news.
    {ticker: {"tags": [...], "sample": "worst headline"}} — {} on failure."""
    out: dict[str, dict] = {}
    try:
        import time as _time

        import yfinance as yf

        from .symbols import normalize_symbol
        cutoff = _time.time() - window_hours * 3600.0
        for t in tickers:
            try:
                items = yf.Ticker(normalize_symbol(t)).news or []
            except Exception:  # noqa: BLE001
                continue
            titles: list[str] = []
            for item in items:
                content = item.get("content", item) if isinstance(item, dict) else {}
                ts = (content.get("providerPublishTime")
                      or item.get("providerPublishTime") or 0)
                if isinstance(ts, (int, float)) and ts > 0 and ts < cutoff:
                    continue
                titles.append(str(content.get("title") or item.get("title") or ""))
            tags = scan_falsifier_headlines(titles)
            if tags:
                sample = next(
                    (ti for ti in titles
                     if scan_falsifier_headlines([ti])), "")
                out[str(t).upper()] = {"tags": tags, "sample": sample[:140]}
    except ImportError:
        pass
    return out


def assess_holding(
    ticker: str,
    position: dict,
    history: pd.Series | None,
    *,
    stop_price: float | None = None,
    falsifiers: dict | None = None,
) -> dict:
    """One position's health card. Pure given inputs.

    Returns pnl_pct, stop_distance_pct, momentum_3m/6m (CONTEXT ONLY),
    falsifier tags, and a one-line summary. Never returns an
    instruction to sell — by charter.
    """
    avg = float(position.get("avg_cost") or 0)
    last = m3 = m6 = None
    if history is not None:
        s = history.dropna()
        if not s.empty:
            last = float(s.iloc[-1])
            if len(s) > 64:
                m3 = (last / float(s.iloc[-64]) - 1) * 100.0
            if len(s) > 127:
                m6 = (last / float(s.iloc[-127]) - 1) * 100.0
    pnl = (last / avg - 1) * 100.0 if (last and avg > 0) else None
    stop_dist = ((last - stop_price) / stop_price * 100.0
                 if (last and stop_price and stop_price > 0) else None)
    f = (falsifiers or {}).get(str(ticker).upper()) or {}

    bits: list[str] = []
    if pnl is not None:
        bits.append(f"{pnl:+.1f}% vs cost")
    if stop_dist is not None:
        bits.append(f"{stop_dist:+.1f}% above stop" if stop_dist >= 0
                    else f"BELOW stop by {-stop_dist:.1f}%")
    if m6 is not None:
        state = "warm" if m6 > 0 else "cooling"
        bits.append(f"6m momentum {state} ({m6:+.0f}%, context only)")
    if f.get("tags"):
        bits.append("🚨 falsifier headlines: " + ", ".join(f["tags"]))
    return {
        "ticker": str(ticker).upper(),
        "pnl_pct": pnl,
        "stop_distance_pct": stop_dist,
        "momentum_3m": m3,
        "momentum_6m": m6,
        "falsifier_tags": list(f.get("tags") or []),
        "falsifier_sample": f.get("sample", ""),
        "line": " · ".join(bits) if bits else "no data",
    }
