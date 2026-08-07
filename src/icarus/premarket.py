"""Premarket awareness: gap + news context before the US open.

Inspired by a colleague's premarket picker. Everything else in Icarus
runs on daily closes, so a gem alert computed on yesterday's close can
be stale by 09:30 ET — the buy zone may have gapped away overnight, or
a holding may be about to open through its stop. This module fetches
premarket quotes for a SHORTLIST (holdings + current gems + the swing
ETF pool — never the whole watchlist) and reports material gaps with
any overnight headlines.

Honesty rules:
  - Premarket data has no free history, so gaps CANNOT be backtested
    with this stack. Premarket context therefore never gates and never
    scores — it annotates validated signals and real holdings only.
  - Premarket prints are thin: a ±3% gap on no volume routinely halves
    at the open. The report says what it sees, not what it means.

Pure builders (`build_premarket_report`, `format_premarket_push`) are
unit-tested; the fetch wrapper degrades to {} like every other ingest.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MATERIAL_GAP_PCT = 3.0        # below this a gap is noise, not news
PREMARKET_CACHE_PATH = "data/cache/premarket.json"


def fetch_premarket_quotes(tickers: list[str]) -> dict[str, dict]:
    """Premarket price + previous close per ticker via yfinance .info.

    Only meaningful ~04:00-09:30 ET; outside that window Yahoo returns
    no premarket fields and entries degrade to {}. Keep the list short —
    .info is one HTTP round trip per symbol.
    """
    out: dict[str, dict] = {}
    if not tickers:
        return out
    try:
        import yfinance as yf
    except ImportError:
        return out
    from concurrent.futures import ThreadPoolExecutor

    from .symbols import normalize_symbol

    def _one(t: str) -> tuple[str, dict]:
        try:
            info = yf.Ticker(normalize_symbol(t)).info or {}
            pm = info.get("preMarketPrice")
            prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
            return t.upper(), {
                "premarket_price": float(pm) if pm else None,
                "prev_close": float(prev) if prev else None,
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("premarket quote failed for %s: %s", t, exc)
            return t.upper(), {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, q in ex.map(_one, tickers):
            out[t] = q
    return out


def build_premarket_report(
    quotes: dict[str, dict],
    *,
    holdings: list[str] | None = None,
    gems: list[str] | None = None,
    news: dict[str, dict] | None = None,
    material_gap_pct: float = MATERIAL_GAP_PCT,
) -> list[dict]:
    """Rows for every ticker with a material premarket gap, plus EVERY
    holding that has any premarket print at all (a -2% drift on a real
    position matters more than a +3% pop on a watch-only name).

    Pure: quotes/news are plain dicts. Sorted by |gap| descending.
    """
    holdings_set = {t.upper() for t in (holdings or [])}
    gems_set = {t.upper() for t in (gems or [])}
    rows: list[dict] = []
    for t, q in quotes.items():
        pm, prev = q.get("premarket_price"), q.get("prev_close")
        if not pm or not prev or prev <= 0:
            continue
        gap = (float(pm) / float(prev) - 1.0) * 100.0
        if not np.isfinite(gap):
            continue
        is_holding = t in holdings_set
        if abs(gap) < material_gap_pct and not is_holding:
            continue
        n = (news or {}).get(t, {})
        rows.append({
            "ticker": t,
            "gap_pct": round(gap, 2),
            "premarket_price": float(pm),
            "prev_close": float(prev),
            "is_holding": is_holding,
            "is_gem": t in gems_set,
            "news_count": int(n.get("count") or 0),
            "news_tags": list(n.get("tags") or []),
        })
    rows.sort(key=lambda r: abs(r["gap_pct"]), reverse=True)
    return rows


def format_premarket_push(rows: list[dict]) -> tuple[str, str] | None:
    """(title, body) for ntfy, or None when there is nothing worth a
    phone buzz (no material gaps and no moving holdings)."""
    if not rows:
        return None
    lines: list[str] = []
    for r in rows:
        badge = "💼" if r["is_holding"] else ("💎" if r["is_gem"] else "👀")
        arrow = "▲" if r["gap_pct"] >= 0 else "▼"
        line = (f"{badge} {r['ticker']} {arrow} {r['gap_pct']:+.1f}% premarket "
                f"({r['prev_close']:,.2f} → {r['premarket_price']:,.2f})")
        if r["news_count"]:
            tags = f" [{', '.join(r['news_tags'])}]" if r["news_tags"] else ""
            line += f" · {r['news_count']} headline(s){tags}"
        lines.append(line)
    n_up = sum(1 for r in rows if r["gap_pct"] >= 0)
    title = f"🌅 Premarket: {n_up}▲ {len(rows) - n_up}▼ on your radar"
    body = "\n".join(lines) + (
        "\n\nThin premarket prints — treat as context, not signal. "
        "Buy zones may have moved; stops are judged at the close."
    )
    return title, body
