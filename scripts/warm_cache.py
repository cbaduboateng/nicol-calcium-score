"""Nightly cache warmer — run from GitHub Actions, not from Streamlit.

Streamlit Cloud wipes its disk on every deploy, so runtime-fetched
price/volume/cap caches die with each push and the app re-fights
Yahoo's rate limits from zero. This script runs on a GitHub runner
(different egress IPs, nobody waiting on a spinner), fetches everything
the dashboard needs, and the workflow commits the resulting cache files
into the repo — so every deploy boots with warm data.

Fetches:
  - 1y close prices  (Watchlist tab)
  - 2y close prices  (Track record + runbook backtest)
  - 3mo volumes      (Today's Signals relative-volume)
  - market caps      (cap filters / display)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[warm] %(levelname)s %(message)s")
log = logging.getLogger("warm_cache")

CACHE_DIR = Path("data/cache")


def _expire_existing_caches() -> None:
    """Backdate committed cache files so the TTL check refetches, while
    keeping them on disk as backfill for anything the fresh fetch misses.
    Also clear top-up cooldown markers."""
    two_days_ago = time.time() - 48 * 3600
    for f in CACHE_DIR.glob("watchlist_*_v2_*.parquet"):
        os.utime(f, (two_days_ago, two_days_ago))
        log.info("Backdated %s", f.name)
    for m in CACHE_DIR.glob("*.topup"):
        m.unlink(missing_ok=True)


def main() -> int:
    from icarus.ticker_facts import quick_market_caps
    from icarus.watchlist_alerts import (
        WATCHLIST_PATH,
        fetch_price_history,
        fetch_volume_history,
        load_watchlist,
    )

    watchlist = load_watchlist(WATCHLIST_PATH)
    if watchlist.empty:
        log.error("Watchlist is empty — nothing to warm")
        return 1
    tickers = sorted(set(watchlist["ticker"].astype(str)))
    log.info("Warming caches for %d tickers", len(tickers))

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _expire_existing_caches()

    p1 = fetch_price_history(tickers, period="1y")
    log.info("1y prices: %d / %d", len(p1), len(tickers))
    p2 = fetch_price_history(tickers, period="2y")
    log.info("2y prices: %d / %d", len(p2), len(tickers))
    vol = fetch_volume_history(tickers, period="3mo")
    log.info("3mo volumes: %d / %d", len(vol), len(tickers))
    n_caps = quick_market_caps(tickers, max_workers=8)
    log.info("Market caps: %d newly fetched", n_caps)

    # Clear cooldown markers so the freshly-deployed app can still top up.
    for m in CACHE_DIR.glob("*.topup"):
        m.unlink(missing_ok=True)

    # Fail the job if coverage is poor so a rate-limited run doesn't
    # commit a thin cache over a previously fat one. (The merge logic
    # makes shrinkage unlikely, but belt and braces.)
    if len(p1) < 0.5 * len(tickers):
        log.error("1y coverage below 50%% — refusing to bless this run")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
