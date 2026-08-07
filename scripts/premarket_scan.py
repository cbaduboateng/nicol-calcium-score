"""Premarket scan — runs on GitHub Actions ~08:45 ET, before the US open.

Shortlist = real holdings + current gems (computed from the committed
warm caches, so no big fetch) + the swing ETF pool. Fetches premarket
quotes + overnight headlines for that shortlist, writes
data/cache/premarket.json for the dashboard, and pushes material moves
to ntfy when NTFY_TOPIC is configured.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[premarket] %(levelname)s %(message)s")
log = logging.getLogger("premarket_scan")

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
REPO = "cbaduboateng/nicol-calcium-score"


def _shortlist() -> tuple[list[str], list[str], list[str]]:
    """(tickers, holdings, gems) — small enough for per-symbol quotes."""
    import pandas as pd

    holdings: list[str] = []
    try:
        from icarus.portfolio import load_public_trades, positions_from_trades
        trades = load_public_trades(
            REPO, token=os.environ.get("PICKLOG_TOKEN", "").strip(),
        )
        positions, _ = positions_from_trades(trades)
        holdings = sorted(positions["ticker"].astype(str))
    except Exception as exc:  # noqa: BLE001
        log.warning("holdings unavailable (%s)", exc)

    gems: list[str] = []
    try:
        from icarus.daily_signals import find_gems
        from icarus.target_inference import derive_targets, learn_target_pattern
        from icarus.watchlist_alerts import (
            WATCHLIST_PATH,
            build_watchlist_view,
            load_watchlist,
        )
        wl = load_watchlist(WATCHLIST_PATH)
        prices = pd.read_parquet("data/cache/watchlist_prices_v2_1y.parquet")
        vols = pd.read_parquet("data/cache/watchlist_volumes_v2_3mo.parquet")
        history = {c: prices[c].dropna() for c in prices.columns
                   if not prices[c].dropna().empty}
        volumes = {c: vols[c].dropna() for c in vols.columns
                   if not vols[c].dropna().empty}
        pattern = learn_target_pattern(wl, history)
        if pattern is not None:
            wl = derive_targets(wl, history, pattern)
        view = build_watchlist_view(wl, history)
        g = find_gems(view, history, volumes, top_n=5)
        if not g.empty:
            gems = sorted(g["ticker"].astype(str))
    except Exception as exc:  # noqa: BLE001
        log.warning("gems unavailable (%s)", exc)

    from icarus.swing import SWING_POOLS
    etfs = list(SWING_POOLS["etf"]["tickers"])

    tickers = sorted(set(holdings) | set(gems) | set(etfs))
    return tickers, holdings, gems


def main() -> int:
    from icarus.daily_signals import fetch_news_counts
    from icarus.premarket import (
        PREMARKET_CACHE_PATH,
        build_premarket_report,
        fetch_premarket_quotes,
        format_premarket_push,
    )

    tickers, holdings, gems = _shortlist()
    log.info("Shortlist: %d tickers (%d holdings, %d gems)",
             len(tickers), len(holdings), len(gems))
    quotes = fetch_premarket_quotes(tickers)
    n_pm = sum(1 for q in quotes.values() if q.get("premarket_price"))
    log.info("Premarket prints for %d/%d", n_pm, len(tickers))

    movers = [t for t, q in quotes.items()
              if q.get("premarket_price") and q.get("prev_close")]
    try:
        news = fetch_news_counts(movers[:40], window_hours=16.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("news unavailable (%s)", exc)
        news = {}

    rows = build_premarket_report(
        quotes, holdings=holdings, gems=gems, news=news,
    )
    payload = {
        "scanned_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "n_quoted": n_pm,
        "rows": rows,
    }
    Path(PREMARKET_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(PREMARKET_CACHE_PATH).write_text(json.dumps(payload, indent=1))
    log.info("Wrote %s (%d material rows)", PREMARKET_CACHE_PATH, len(rows))

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    push = format_premarket_push(rows)
    if not topic:
        log.warning("NTFY_TOPIC not set — report written, push skipped")
        return 0
    if push is None:
        log.info("Nothing material premarket — staying silent")
        return 0
    title, body = push
    import requests
    resp = requests.post(
        f"{NTFY_SERVER}/{topic}",
        data=body.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Priority": "high",
                 "Tags": "sunrise"},
        timeout=30,
    )
    resp.raise_for_status()
    log.info("Pushed %d premarket rows", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
