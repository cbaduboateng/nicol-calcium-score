"""Weekly Explorer-universe builder — run from GitHub Actions.

Downloads the full US listing directory, filters it to the "runbook
habitat", and persists data/explorer/watchlist.csv (schema-compatible
with the curated watchlist, targets left empty for runtime derivation).
Also warms the shared price/volume caches for the surviving tickers so
the dashboard never fetches them itself.

Habitat filters (applied with data fetched on this runner):
  last close  $0.50 – $50    (tradeable range, kills sub-penny junk)
  market cap  $50M – $2B     (room to run, not shells)
  avg volume  > 200k shares  (liquid enough to exit)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[explorer] %(levelname)s %(message)s")
log = logging.getLogger("warm_explorer")

PRICE_MIN, PRICE_MAX = 0.50, 50.0
CAP_MIN, CAP_MAX = 50_000_000.0, 2_000_000_000.0
AVG_VOLUME_MIN = 200_000.0
OUT_PATH = Path("data/explorer/watchlist.csv")


def main() -> int:
    import pandas as pd

    from icarus.ticker_facts import lookup as facts_lookup
    from icarus.universe import fetch_us_universe
    from icarus.watchlist_alerts import (
        WATCHLIST_PATH,
        fetch_price_history,
        fetch_volume_history,
        load_watchlist,
    )

    universe = fetch_us_universe()
    if universe.empty:
        log.error("Universe download failed — keeping the existing explorer list")
        return 1
    log.info("Raw universe: %d common-stock symbols", len(universe))

    # Exclude anything already on the curated list — no double-counting.
    curated = set(load_watchlist(WATCHLIST_PATH)["ticker"].astype(str))
    universe = universe[~universe["ticker"].isin(curated)]
    log.info("After removing curated overlap: %d", len(universe))

    tickers = universe["ticker"].tolist()

    # Price filter first — cheapest way to shrink the cap-fetch load.
    prices = fetch_price_history(tickers, period="1y")
    log.info("Price history for %d / %d", len(prices), len(tickers))
    survivors: list[str] = []
    for t in tickers:
        s = prices.get(t)
        if s is None or len(s) < 60:
            continue
        last = float(s.dropna().iloc[-1]) if not s.dropna().empty else 0.0
        if PRICE_MIN <= last <= PRICE_MAX:
            survivors.append(t)
    log.info("After price band $%.2f-%.2f: %d", PRICE_MIN, PRICE_MAX, len(survivors))

    # Liquidity filter from 3mo volumes.
    volumes = fetch_volume_history(survivors, period="3mo")
    liquid: list[str] = []
    for t in survivors:
        v = volumes.get(t)
        if v is None or v.dropna().empty:
            continue
        if float(v.dropna().mean()) >= AVG_VOLUME_MIN:
            liquid.append(t)
    log.info("After liquidity floor %.0fk avg: %d", AVG_VOLUME_MIN / 1000, len(liquid))

    # Full facts (sector + cap) via get_info — slower than fast_info but
    # sector is what the theme gate runs on; without it every explorer
    # name lands in one giant meaningless "Other" theme.
    from icarus.ticker_facts import prewarm
    n_warmed = prewarm(liquid, max_workers=12)
    log.info("Prewarmed full facts for %d tickers", n_warmed)

    import re as _re

    def _clean_name(raw: str) -> str:
        # Symbol-directory names carry suffixes like " - Common Stock",
        # " - Class A Common Stock", " - American Depositary Shares".
        return _re.split(r"\s+-\s+", raw)[0].strip()

    name_by_ticker = dict(zip(universe["ticker"], universe["name"]))
    rows: list[dict] = []
    for t in liquid:
        fact = facts_lookup(t, cache_only=True)
        cap = fact.market_cap_usd if fact else None
        if cap is None or not (CAP_MIN <= cap <= CAP_MAX):
            continue
        name = (fact.name if fact and fact.name != t else "") or (
            name_by_ticker.get(t, "")
        )
        sector = (fact.sector if fact else "") or ""
        if sector == "Other":
            sector = ""
        rows.append({
            "ticker": t,
            "name": _clean_name(name),
            "description": sector,   # sector doubles as the theme hint
            "target_entry": "",
            "target_exit": "",
        })
    log.info("After cap band $50M-$2B: %d explorer names", len(rows))
    with_sector = sum(1 for r in rows if r["description"])
    log.info("Sector known for %d / %d", with_sector, len(rows))

    if len(rows) < 50:
        log.error("Explorer list suspiciously small (%d) — refusing to overwrite", len(rows))
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd  # noqa: F811
    pd.DataFrame(rows).to_csv(OUT_PATH, index=False)
    log.info("Wrote %s (%d tickers)", OUT_PATH, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
