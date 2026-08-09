"""Earnings-events ingest for the PEAD experiment — runs on Actions.

Fetches recent quarterly report dates + EPS surprise for the watchlist
universe via yfinance (one request per ticker — slow and flaky, hence a
weekly job, not part of the nightly warm) and writes
data/cache/earnings_v1.parquet with columns ticker, date, surprise_pct.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[earnings] %(levelname)s %(message)s")
log = logging.getLogger("warm_earnings")

OUT_PATH = Path("data/cache/earnings_v1.parquet")


def main() -> int:
    import pandas as pd
    import yfinance as yf

    from icarus.symbols import normalize_symbol
    from icarus.watchlist_alerts import WATCHLIST_PATH, load_watchlist

    wl = load_watchlist(WATCHLIST_PATH)
    if wl.empty:
        log.error("Watchlist empty")
        return 1
    tickers = sorted(set(wl["ticker"].astype(str)))
    log.info("Fetching earnings dates for %d tickers", len(tickers))

    rows: list[dict] = []
    fetched = 0
    for i, t in enumerate(tickers):
        try:
            ed = yf.Ticker(normalize_symbol(t)).get_earnings_dates(limit=12)
        except Exception as exc:  # noqa: BLE001
            log.debug("earnings failed for %s: %s", t, exc)
            ed = None
        if ed is not None and not ed.empty:
            fetched += 1
            for ts, row in ed.iterrows():
                surprise = row.get("Surprise(%)")
                reported = row.get("Reported EPS")
                if pd.isna(surprise) or pd.isna(reported):
                    continue          # future dates / missing estimates
                d = pd.Timestamp(ts)
                if getattr(d, "tz", None) is not None:
                    d = d.tz_localize(None)
                rows.append({
                    "ticker": t.upper(),
                    "date": d.normalize(),
                    "surprise_pct": float(surprise),
                })
        if i % 25 == 24:
            log.info("...%d/%d (%d with data, %d events)",
                     i + 1, len(tickers), fetched, len(rows))
            time.sleep(2)

    if not rows:
        log.error("No earnings events fetched — not writing")
        return 1
    df = pd.DataFrame(rows).drop_duplicates(["ticker", "date"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values(["ticker", "date"]).to_parquet(OUT_PATH, index=False)
    log.info("Wrote %s: %d events from %d tickers", OUT_PATH, len(df), fetched)
    return 0


if __name__ == "__main__":
    sys.exit(main())
