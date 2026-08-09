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

    import requests

    def _from_yfinance(t: str) -> list[dict]:
        ed = yf.Ticker(normalize_symbol(t)).get_earnings_dates(limit=12)
        out: list[dict] = []
        if ed is None or ed.empty:
            return out
        for ts, row in ed.iterrows():
            surprise = row.get("Surprise(%)")
            reported = row.get("Reported EPS")
            if pd.isna(surprise) or pd.isna(reported):
                continue              # future dates / missing estimates
            d = pd.Timestamp(ts)
            if getattr(d, "tz", None) is not None:
                d = d.tz_localize(None)
            out.append({"ticker": t.upper(), "date": d.normalize(),
                        "surprise_pct": float(surprise)})
        return out

    _NQ_HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) research script",
        "Accept": "application/json",
    }

    def _from_nasdaq(t: str) -> list[dict]:
        """Nasdaq's public earnings-surprise endpoint: announcement dates
        + eps actual/estimate for recent quarters. US symbols only."""
        sym = normalize_symbol(t)
        if "." in sym or "-USD" in sym or ":" in sym:
            return []                 # non-US listings / crypto
        r = requests.get(
            f"https://api.nasdaq.com/api/company/{sym}/earnings-surprise",
            headers=_NQ_HEADERS, timeout=15,
        )
        r.raise_for_status()
        rows_json = (((r.json() or {}).get("data") or {})
                     .get("earningsSurpriseTable") or {}).get("rows") or []
        out: list[dict] = []
        for row in rows_json:
            try:
                d = pd.Timestamp(row.get("dateReported"))
                actual = float(str(row.get("eps")).replace("$", "")
                               .replace("(", "-").replace(")", ""))
                est = float(str(row.get("consensusForecast")).replace("$", "")
                            .replace("(", "-").replace(")", ""))
            except (TypeError, ValueError):
                continue
            if pd.isna(d) or est == 0:
                continue
            out.append({
                "ticker": t.upper(), "date": d.normalize(),
                "surprise_pct": (actual - est) / abs(est) * 100.0,
            })
        return out

    rows: list[dict] = []
    fetched = 0
    yf_dead = 0
    for i, t in enumerate(tickers):
        got: list[dict] = []
        # yfinance first (12 quarters when it works)…
        if yf_dead < 25:              # …but stop flogging it once it's
            try:                      # clearly broken wholesale
                got = _from_yfinance(t)
                if not got:
                    yf_dead += 1
                else:
                    yf_dead = 0
            except Exception:  # noqa: BLE001
                yf_dead += 1
        if not got:
            try:
                got = _from_nasdaq(t)
            except Exception as exc:  # noqa: BLE001
                log.debug("nasdaq failed for %s: %s", t, exc)
        if got:
            fetched += 1
            rows.extend(got)
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
