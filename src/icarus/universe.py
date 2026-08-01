"""Explorer universe: US exchange listings beyond the curated watchlist.

Sources the official NASDAQ Trader symbol directories (free, no key):
  nasdaqlisted.txt — NASDAQ listings
  otherlisted.txt  — NYSE / NYSE American / ARCA etc.

The raw universe (~6,000 names) is filtered down to the "runbook
habitat" by the warm-explorer job — price, cap, and liquidity bounds —
and persisted to ``data/explorer/watchlist.csv`` in the same schema as
the curated watchlist (ticker, name, description, target_entry,
target_exit) with EMPTY targets: the dashboard derives them from the
pattern learned on the curated list. Explorer rows are therefore
always fully synthetic-target (D/D) and are trust-discounted wherever
they compete with curated gems.
"""

from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

EXPLORER_WATCHLIST_PATH = Path("data/explorer/watchlist.csv")

# Security-name fragments that mark non-common-stock instruments.
_JUNK_NAME_FRAGMENTS = (
    "warrant", " unit", " units", " right", " rights", "preferred",
    "depositary", " notes", "% ", "due 20", "trust preferred",
)


def parse_symbol_directory(text: str, *, symbol_col: str) -> pd.DataFrame:
    """Parse one pipe-delimited NASDAQ Trader symbol file into
    (ticker, name) rows of plain common stock only."""
    df = pd.read_csv(StringIO(text), sep="|", dtype=str)
    if symbol_col not in df.columns or "Security Name" not in df.columns:
        return pd.DataFrame(columns=["ticker", "name"])
    # Drop the file-footer row ("File Creation Time...")
    df = df[df[symbol_col].notna()]
    df = df[~df[symbol_col].str.contains("File Creation", na=False)]
    if "Test Issue" in df.columns:
        df = df[df["Test Issue"] != "Y"]
    if "ETF" in df.columns:
        df = df[df["ETF"] != "Y"]
    df = df.rename(columns={symbol_col: "ticker", "Security Name": "name"})
    df["ticker"] = df["ticker"].str.strip().str.upper()
    # Plain common stock: alphabetic symbols only (kills warrants/units
    # like XYZ.W, XYZ$ and most preferred classes).
    df = df[df["ticker"].str.fullmatch(r"[A-Z]{1,5}", na=False)]
    lower_names = df["name"].str.lower().fillna("")
    for frag in _JUNK_NAME_FRAGMENTS:
        df = df[~lower_names.str.contains(frag, regex=False)]
        lower_names = df["name"].str.lower().fillna("")
    return df[["ticker", "name"]].drop_duplicates("ticker").reset_index(drop=True)


def fetch_us_universe(timeout: float = 60.0) -> pd.DataFrame:
    """Download and combine both symbol directories. Network — run this
    from the warm-explorer job, not the dashboard."""
    import requests

    frames: list[pd.DataFrame] = []
    for url, col in (
        (NASDAQ_LISTED_URL, "Symbol"),
        (OTHER_LISTED_URL, "ACT Symbol"),
    ):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            frames.append(parse_symbol_directory(resp.text, symbol_col=col))
        except Exception as exc:  # noqa: BLE001
            log.warning("Universe fetch failed for %s: %s", url, exc)
    if not frames:
        return pd.DataFrame(columns=["ticker", "name"])
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates("ticker").reset_index(drop=True)


def load_explorer_watchlist(
    path: Path | str = EXPLORER_WATCHLIST_PATH,
) -> pd.DataFrame:
    """Load the pre-filtered explorer watchlist committed by the warm
    job. Empty frame when the job hasn't run yet."""
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(
            columns=["ticker", "name", "description", "target_entry", "target_exit"],
        )
    df = pd.read_csv(p, dtype=str).fillna("")
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df = df[df["ticker"] != ""]
    df["target_entry"] = pd.to_numeric(df["target_entry"], errors="coerce")
    df["target_exit"] = pd.to_numeric(df["target_exit"], errors="coerce")
    return df.reset_index(drop=True)
