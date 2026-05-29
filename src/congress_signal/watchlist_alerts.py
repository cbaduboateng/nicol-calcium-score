"""Hubris watchlist alert engine.

Reads the curated watchlist (analyst entry / exit targets), fetches live
prices, and surfaces:

  - BUY ZONE      : live price <= target_entry  (entry triggered)
  - APPROACHING   : live price within 15% above target_entry
  - SELL ZONE     : live price >= target_exit   (exit triggered)
  - HOLD          : between zones, no action
  - WATCH         : has no targets set; live price tracked only

Also computes price momentum over 1m / 3m / 6m / 12m so we can rank
candidates by 'parabolic' behaviour, and a per-theme momentum score
derived from the Description column so we can answer 'which themes
are running this month?'.

The watchlist itself is curated by the user in
`data/watchlist.csv`. The engine never writes back.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

WATCHLIST_PATH = Path("data/watchlist.csv")


# ---------------------------------------------------------------------------
# Loading + light cleaning
# ---------------------------------------------------------------------------


def load_watchlist(path: Path | str = WATCHLIST_PATH) -> pd.DataFrame:
    """Read the CSV watchlist and normalise types.

    Returns columns: ticker, name, description, target_entry, target_exit.
    Empty cells become NaN. Tickers are upper-cased and stripped.
    """
    p = Path(path)
    if not p.exists():
        log.warning("Watchlist file missing: %s", p)
        return pd.DataFrame(
            columns=["ticker", "name", "description", "target_entry", "target_exit"],
        )
    df = pd.read_csv(p, dtype=str).fillna("")
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df = df[df["ticker"] != ""]
    df["target_entry"] = pd.to_numeric(df["target_entry"], errors="coerce")
    df["target_exit"] = pd.to_numeric(df["target_exit"], errors="coerce")
    df["description"] = df["description"].fillna("").str.strip()
    df["name"] = df["name"].fillna("").str.strip()
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Theme mapping
# ---------------------------------------------------------------------------


_THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI / Big Data",      ("ai", "artificial intelligence", "big data", "data mgt",
                            "machine learning", "voice ai")),
    ("Quantum",            ("quantum",)),
    ("Nuclear / Uranium",  ("nuclear", "uranium", "smr")),
    ("Crypto / Blockchain", ("crypto", "bitcoin", "ethereum", "blockchain",
                             "btc", "eth", "mining")),
    ("Cybersecurity",      ("cyber", "cybersec", "security", "cybersecurity")),
    ("EV / Battery",       ("ev", "electric vehicle", "battery", "charging",
                            "lithium", "tesla")),
    ("Renewables / Solar", ("renewable", "solar", "wind", "clean energy")),
    ("Biotech / Pharma",   ("biotech", "pharma", "gene", "therapeutics",
                            "oncology", "cancer", "vaccine", "crispr",
                            "diagnostic", "clinical")),
    ("Med devices / Health", ("medical", "med devices", "med dev",
                              "health", "telemed", "telehealth", "surgery")),
    ("Cannabis",           ("cannabis", "cbd", "marijuana")),
    ("Space / Aerospace",  ("space", "satellite", "rocket", "aerospace",
                            "aviation", "drone")),
    ("Defence",            ("defence", "defense", "military", "armed")),
    ("Semiconductors",     ("semi", "semiconductor", "chip", "5g", "nanotech",
                            "photonics")),
    ("Cloud / SaaS",       ("saas", "cloud", "software", "platform",
                            "enterprise", "devops")),
    ("Fintech / Payments", ("fintech", "payment", "bank", "broker",
                            "exchange", "trading", "insurance")),
    ("Gaming / Esports",   ("gaming", "esports", "game", "casino", "betting")),
    ("Media / Streaming",  ("streaming", "media", "video", "music", "podcast",
                            "social media", "content")),
    ("E-commerce / Retail", ("e-commerce", "ecommerce", "retail", "shop",
                             "consumer")),
    ("Real estate / REIT", ("reit", "real estate", "property", "warehouse",
                            "datacentre", "data centre")),
    ("Mining / Metals",    ("mining", "metals", "gold", "silver", "copper",
                            "rare earth")),
    ("Energy / Oil & Gas", ("oil", "gas", "energy", "petroleum")),
    ("Cars / Auto",        ("auto", "car", "vehicle", "motor")),
    ("Travel / Hospitality", ("travel", "hotel", "airline", "cruise",
                              "restaurant", "hospitality")),
    ("Food / Beverage",    ("food", "beverage", "snack", "drink", "coffee")),
    ("Apparel / Fashion",  ("apparel", "fashion", "clothing", "footwear")),
)


def map_theme(description: str | None) -> str:
    """Return the first matching theme label for a description, or 'Other'."""
    if not isinstance(description, str) or not description:
        return "Other"
    d = description.lower()
    for label, needles in _THEME_RULES:
        if any(n in d for n in needles):
            return label
    return "Other"


# ---------------------------------------------------------------------------
# Status calculation
# ---------------------------------------------------------------------------


APPROACHING_PCT_ABOVE_ENTRY = 0.15  # within 15% above entry counts as approaching


def compute_status(
    live_price: float | None,
    target_entry: float | None,
    target_exit: float | None,
) -> str:
    if live_price is None or not np.isfinite(live_price) or live_price <= 0:
        return "PRICE MISSING"
    has_entry = target_entry is not None and np.isfinite(target_entry) and target_entry > 0
    has_exit  = target_exit  is not None and np.isfinite(target_exit)  and target_exit  > 0
    if not (has_entry or has_exit):
        return "WATCH"
    if has_exit and live_price >= target_exit:
        return "SELL ZONE"
    if has_entry and live_price <= target_entry:
        return "BUY ZONE"
    if has_entry and live_price <= target_entry * (1 + APPROACHING_PCT_ABOVE_ENTRY):
        return "APPROACHING"
    return "HOLD"


def gap_to_entry_pct(live: float, entry: float | None) -> float:
    if entry is None or not np.isfinite(entry) or entry <= 0:
        return float("nan")
    return (live - entry) / entry * 100.0


def reward_risk_to_targets(
    live: float, entry: float | None, exit_: float | None,
) -> float:
    """Upside-to-exit / downside-to-entry, from current price.
    Higher = better risk/reward right now. Returns NaN if missing."""
    if (entry is None or exit_ is None or not np.isfinite(entry) or
            not np.isfinite(exit_) or live <= 0):
        return float("nan")
    upside = (exit_ - live) / live
    downside = (live - entry) / live
    if downside <= 0:
        return float("inf")  # already below entry
    return upside / downside


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


def _pct_change_from_history(history: pd.Series, days: int) -> float:
    """Return % change over `days` calendar days ending today."""
    if history is None or history.empty:
        return float("nan")
    end = history.iloc[-1]
    cutoff = history.index[-1] - pd.Timedelta(days=days)
    earlier = history.loc[history.index <= cutoff]
    if earlier.empty:
        return float("nan")
    start = earlier.iloc[-1]
    if start is None or start <= 0:
        return float("nan")
    return float((end / start - 1.0) * 100.0)


@dataclass
class MomentumSnapshot:
    ticker: str
    live_price: float | None
    pct_1m: float
    pct_3m: float
    pct_6m: float
    pct_12m: float


def momentum_snapshot(ticker: str, history: pd.Series) -> MomentumSnapshot:
    last = float(history.iloc[-1]) if history is not None and not history.empty else None
    return MomentumSnapshot(
        ticker=ticker,
        live_price=last,
        pct_1m=_pct_change_from_history(history, 30),
        pct_3m=_pct_change_from_history(history, 90),
        pct_6m=_pct_change_from_history(history, 180),
        pct_12m=_pct_change_from_history(history, 365),
    )


# ---------------------------------------------------------------------------
# Top-level orchestration: build a fully-decorated watchlist DataFrame
# ---------------------------------------------------------------------------


def build_watchlist_view(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
) -> pd.DataFrame:
    """Take the raw watchlist + a {ticker -> daily close series} dict and
    return a single DataFrame ready to render in the dashboard.

    Output columns:
      ticker, name, description, theme, target_entry, target_exit,
      live_price, status, gap_to_entry_pct, reward_risk,
      pct_1m, pct_3m, pct_6m, pct_12m
    """
    rows: list[dict] = []
    for _, row in watchlist.iterrows():
        ticker = row["ticker"]
        hist = price_history.get(ticker)
        snap = (
            momentum_snapshot(ticker, hist)
            if hist is not None and not hist.empty
            else MomentumSnapshot(ticker, None, float("nan"), float("nan"),
                                  float("nan"), float("nan"))
        )
        entry = row["target_entry"] if pd.notna(row["target_entry"]) else None
        exit_ = row["target_exit"]  if pd.notna(row["target_exit"])  else None
        status = compute_status(snap.live_price, entry, exit_)
        rows.append({
            "ticker": ticker,
            "name": row["name"],
            "description": row["description"],
            "theme": map_theme(row["description"]),
            "target_entry": entry,
            "target_exit": exit_,
            "live_price": snap.live_price,
            "status": status,
            "gap_to_entry_pct": (
                gap_to_entry_pct(snap.live_price, entry)
                if snap.live_price is not None else float("nan")
            ),
            "reward_risk": (
                reward_risk_to_targets(snap.live_price, entry, exit_)
                if snap.live_price is not None else float("nan")
            ),
            "pct_1m": snap.pct_1m,
            "pct_3m": snap.pct_3m,
            "pct_6m": snap.pct_6m,
            "pct_12m": snap.pct_12m,
        })
    df = pd.DataFrame(rows)
    return df


def theme_heat(view: pd.DataFrame) -> pd.DataFrame:
    """Group by theme and rank by median 3m momentum (excluding NaN). Tells
    us which themes are 'running' right now."""
    valid = view[view["pct_3m"].notna()]
    if valid.empty:
        return pd.DataFrame(columns=["theme", "n", "median_3m", "median_6m", "median_12m"])
    out = (
        valid.groupby("theme")
        .agg(
            n=("ticker", "count"),
            median_3m=("pct_3m", "median"),
            median_6m=("pct_6m", "median"),
            median_12m=("pct_12m", "median"),
        )
        .reset_index()
        .sort_values("median_3m", ascending=False)
    )
    return out


def parabolic_rank(
    view: pd.DataFrame, *, horizon: str = "pct_6m", top_n: int = 30,
) -> pd.DataFrame:
    """Top-N tickers by raw % gain over the chosen horizon. The 'parabolic
    winners' ranking — independent of the analyst targets."""
    valid = view[view[horizon].notna()].copy()
    return valid.sort_values(horizon, ascending=False).head(top_n).reset_index(drop=True)


def fetch_price_history(
    tickers: list[str],
    *,
    period: str = "1y",
    cache_dir: Path | str = "data/cache",
) -> dict[str, pd.Series]:
    """Pull daily close prices for each ticker. Wraps yfinance with caching.

    Returns dict mapping ticker -> daily Close Series. Tickers that fail
    (delisted, rate-limited, missing data) are silently omitted.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance unavailable; skipping price fetch")
        return {}
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"watchlist_prices_{period}.parquet"

    # Cheap on-disk cache (24h max age) so the dashboard rerender is fast.
    if cache_file.exists():
        import time
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600.0
        if age_h < 24:
            try:
                df = pd.read_parquet(cache_file)
                df.index = pd.to_datetime(df.index)
                return {c: df[c].dropna() for c in df.columns if df[c].notna().any()}
            except Exception as exc:
                log.debug("Could not read cache (%s); refetching", exc)

    log.info("Fetching %d tickers from yfinance (period=%s)", len(tickers), period)
    try:
        data = yf.download(
            tickers=" ".join(tickers),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
        )
    except Exception as exc:
        log.warning("yfinance bulk download failed: %s", exc)
        return {}

    out: dict[str, pd.Series] = {}
    if isinstance(data.columns, pd.MultiIndex):
        for t in tickers:
            try:
                col = data[t]["Close"].dropna()
            except (KeyError, ValueError):
                continue
            if not col.empty:
                out[t] = col
    elif "Close" in getattr(data, "columns", []):
        col = data["Close"].dropna()
        if not col.empty and tickers:
            out[tickers[0]] = col

    # Persist a single tidy frame for the cache.
    if out:
        try:
            tidy = pd.DataFrame(out)
            tidy.to_parquet(cache_file)
        except Exception as exc:
            log.debug("Could not write spartan price cache (%s)", exc)
    return out
