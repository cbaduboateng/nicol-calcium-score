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


def _warm_swing_universe(chunk: int = 40) -> None:
    """Fetch 2y closes + 3mo volumes for the swing instrument pools and
    write the dedicated swing parquets."""
    import time as _time

    import pandas as pd
    import yfinance as yf

    from icarus.swing import (
        SWING_POOLS,
        SWING_PRICES_CACHE,
        SWING_VOLUMES_CACHE,
    )

    # 10y ETF closes for the rotation experiment (monthly rotation needs
    # far more than 2y under the project's own >=3y backtest rule).
    etf = sorted(SWING_POOLS["etf"]["tickers"])
    try:
        df10 = yf.download(etf, period="10y", interval="1d",
                           progress=False, group_by="ticker",
                           threads=True, auto_adjust=True)
        cols10 = {}
        for s in etf:
            try:
                c = (df10[s]["Close"] if len(etf) > 1 else df10["Close"]).dropna()
                if not c.empty:
                    cols10[s] = c
            except Exception:  # noqa: BLE001
                continue
        if cols10:
            pd.DataFrame(cols10).sort_index().to_parquet(
                "data/cache/etf_prices_v1_10y.parquet",
            )
            log.info("10y ETF cache: %d/%d", len(cols10), len(etf))
    except Exception as exc:  # noqa: BLE001
        log.warning("10y ETF fetch failed (%s)", exc)

    # GBP/USD daily history for FX-aware P&L (booking trades at their
    # trade-date rate splits stock returns from currency drift).
    try:
        fx = yf.download("GBPUSD=X", period="10y", interval="1d",
                         progress=False, auto_adjust=True)["Close"].dropna()
        if isinstance(fx, pd.DataFrame):
            fx = fx.iloc[:, 0].dropna()
        if not fx.empty:
            fx.to_frame("GBPUSD").sort_index().to_parquet(
                "data/cache/gbpusd_v1_10y.parquet",
            )
            log.info("GBPUSD cache: %d sessions", len(fx))
    except Exception as exc:  # noqa: BLE001
        log.warning("GBPUSD fetch failed (%s)", exc)

    symbols = sorted({t for p in SWING_POOLS.values() for t in p["tickers"]})
    log.info("Warming swing universe: %d symbols", len(symbols))
    closes: dict[str, pd.Series] = {}
    vols: dict[str, pd.Series] = {}
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        try:
            df = yf.download(batch, period="2y", interval="1d",
                             progress=False, group_by="ticker",
                             threads=True, auto_adjust=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("swing chunk failed (%s)", exc)
            continue
        for s in batch:
            try:
                sub = df[s] if len(batch) > 1 else df
                c = sub["Close"].dropna()
                if not c.empty:
                    closes[s] = c
                    v = sub["Volume"].dropna().tail(63)
                    if not v.empty:
                        vols[s] = v
            except Exception:  # noqa: BLE001
                continue
        _time.sleep(2)
    log.info("Swing universe: %d/%d priced", len(closes), len(symbols))
    if closes:
        pd.DataFrame(closes).sort_index().to_parquet(SWING_PRICES_CACHE)
    if vols:
        pd.DataFrame(vols).sort_index().to_parquet(SWING_VOLUMES_CACHE)


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

    # ---- Short-interest positioning (context layer, US names) -------------
    try:
        import json as _json

        from icarus.positioning import POSITIONING_CACHE_PATH, fetch_positioning
        pos = fetch_positioning(tickers)
        if pos:
            POSITIONING_CACHE_PATH.write_text(_json.dumps(pos))
            log.info("Positioning: short data for %d/%d tickers",
                     len(pos), len(tickers))
    except Exception as exc:  # noqa: BLE001
        log.warning("Positioning warm failed (%s)", exc)

    # ---- Swing-universe caches (ETFs / large caps / OTC ADRs) -------------
    # Separate parquets keyed by bare Yahoo symbols: these pools are not
    # watchlist rows and must not pollute the watchlist caches' coverage
    # accounting.
    try:
        _warm_swing_universe()
    except Exception as exc:  # noqa: BLE001
        log.warning("Swing-universe warm failed (%s) — app degrades gracefully", exc)

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
