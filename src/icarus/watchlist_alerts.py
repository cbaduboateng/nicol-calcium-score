"""Icarus watchlist alert engine.

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


# ---------------------------------------------------------------------------
# Winner-picking composite (reuses the Jegadeesh-Titman logistic from
# scoring/momentum.py and the layered combiner pattern from scoring/combined.py)
# ---------------------------------------------------------------------------


_STATUS_SCORE: dict[str, float] = {
    "BUY ZONE": 1.0,
    "APPROACHING": 0.65,
    "HOLD": 0.4,
    "WATCH": 0.5,
    "SELL ZONE": 0.0,
    "PRICE MISSING": 0.0,
}


DEFAULT_PICK_WEIGHTS: dict[str, float] = {
    "analyst": 0.30,
    "reward_risk": 0.20,
    "theme_momentum": 0.15,
    "personal_momentum": 0.15,
    "congress": 0.10,
    "catalyst": 0.10,
}


def _logistic_pct(pct: float | None, steepness: float = 3.0) -> float:
    """Map a percentage return through a logistic centred at 0%.
    +20% -> ~0.65, -20% -> ~0.35. Same shape as scoring/momentum.py."""
    if pct is None or not np.isfinite(pct):
        return 0.5
    import math
    return 1.0 / (1.0 + math.exp(-steepness * (float(pct) / 100.0)))


def _analyst_status_score(status: str | None) -> float:
    if not status:
        return 0.5
    return _STATUS_SCORE.get(str(status), 0.5)


def _rr_score(rr: float | None) -> float:
    if rr is None or not np.isfinite(rr) or rr <= 0:
        return 0.5
    return float(min(rr / 5.0, 1.0))


def _blowoff_penalty(pct_6m: float | None, threshold_pct: float = 100.0) -> float:
    """Linear penalty above a runaway 6-month return. Capped at 0.2 so a
    single hot name doesn't get instantly zeroed."""
    if pct_6m is None or not np.isfinite(pct_6m) or pct_6m <= threshold_pct:
        return 0.0
    return float(min(0.2, 0.002 * (pct_6m - threshold_pct)))


def load_congress_overlay(
    candidates_path: Path | str = "data/processed/candidates.parquet",
    trades_path: Path | str = "data/processed/trades.parquet",
    actors_path: Path | str = "data/processed/actors.parquet",
    *,
    recency_window_days: int = 180,
) -> dict[str, dict]:
    """Map each ticker to a rich overlay dict derived from the congress-
    trading pipeline. Returns {} if the candidates file is missing (so the
    dashboard degrades cleanly when run without the pipeline).

    Each value is a dict with:
      score          float, 0-1 — max asymmetry_score for the ticker
      n_actors       int        — distinct actors trading the ticker
      cluster_size   int        — max cluster_size from candidates
      last_trade     date|None  — most recent transaction_date
      days_ago       int|None   — days since last_trade
      top_actors     list[str]  — up to 3 actor names sorted by recency
      signal_summary str        — one-line UI string
    """
    p_cand = Path(candidates_path)
    if not p_cand.exists():
        return {}
    try:
        cand = pd.read_parquet(p_cand)
    except Exception as exc:
        log.warning("Could not load congress candidates (%s)", exc)
        return {}
    if cand.empty or "ticker" not in cand.columns or "asymmetry_score" not in cand.columns:
        return {}

    cand = cand.copy()
    cand["ticker"] = cand["ticker"].astype(str).str.upper()

    trades = pd.DataFrame()
    p_tr = Path(trades_path)
    if p_tr.exists():
        try:
            trades = pd.read_parquet(p_tr)
        except Exception as exc:
            log.warning("Could not load trades (%s)", exc)
    if not trades.empty:
        trades = trades.copy()
        trades["ticker"] = trades["ticker"].astype(str).str.upper()
        if "transaction_date" in trades.columns:
            trades["transaction_date"] = pd.to_datetime(
                trades["transaction_date"], errors="coerce",
            )

    name_by_id: dict[str, str] = {}
    p_act = Path(actors_path)
    if p_act.exists():
        try:
            actors = pd.read_parquet(p_act)
            if not actors.empty and {"actor_id", "name"}.issubset(actors.columns):
                name_by_id = dict(zip(
                    actors["actor_id"].astype(str),
                    actors["name"].astype(str),
                ))
        except Exception as exc:
            log.warning("Could not load actors (%s)", exc)

    today = pd.Timestamp(date.today())
    overlay: dict[str, dict] = {}

    for ticker, sub in cand.groupby("ticker"):
        score = float(np.clip(sub["asymmetry_score"].max(), 0.0, 1.0))
        n_actors = int(sub["actor_id"].astype(str).nunique()) if "actor_id" in sub.columns else 0
        cluster_size = int(sub["cluster_size"].max()) if "cluster_size" in sub.columns else 0

        last_trade: date | None = None
        days_ago: int | None = None
        top_actors: list[str] = []

        if not trades.empty:
            cand_trade_ids = set(sub["trade_id"].astype(str)) if "trade_id" in sub.columns else set()
            ticker_trades = trades[trades["ticker"] == ticker]
            if cand_trade_ids and "trade_id" in ticker_trades.columns:
                ticker_trades = ticker_trades[
                    ticker_trades["trade_id"].astype(str).isin(cand_trade_ids)
                ]
            if not ticker_trades.empty:
                # Only count trades within the recency window
                if "transaction_date" in ticker_trades.columns:
                    cutoff = today - pd.Timedelta(days=recency_window_days)
                    in_window = ticker_trades[ticker_trades["transaction_date"] >= cutoff]
                    if not in_window.empty:
                        most_recent = in_window["transaction_date"].max()
                        if pd.notna(most_recent):
                            last_trade = most_recent.date()
                            days_ago = int((today - most_recent).days)

                        ranked = in_window.sort_values("transaction_date", ascending=False)
                        if "actor_id" in ranked.columns:
                            seen: list[str] = []
                            for aid in ranked["actor_id"].astype(str):
                                nm = name_by_id.get(aid, aid)
                                if nm not in seen:
                                    seen.append(nm)
                                if len(seen) >= 3:
                                    break
                            top_actors = seen

        summary_bits: list[str] = []
        if n_actors:
            summary_bits.append(
                f"{n_actors} member{'s' if n_actors != 1 else ''} trading"
            )
        if days_ago is not None:
            summary_bits.append(f"last buy {days_ago}d ago")
        signal_summary = " · ".join(summary_bits)

        overlay[ticker] = {
            "score": score,
            "n_actors": n_actors,
            "cluster_size": cluster_size,
            "last_trade": last_trade,
            "days_ago": days_ago,
            "top_actors": top_actors,
            "signal_summary": signal_summary,
        }
    return overlay


def load_catalyst_overlay(
    catalysts_path: Path | str = "data/processed/catalysts.parquet",
    *,
    horizon_days: int = 180,
    as_of: date | None = None,
) -> dict[str, dict]:
    """Map each ticker to its NEXT upcoming catalyst within `horizon_days`.

    Each value is a dict:
      score        float, 0-1 — proximity score (1.0 at 0 days, 0 at horizon)
      next_date    date       — event date
      days_until   int        — days from `as_of` to event
      category     str        — e.g. 'dod_obligation_cycle', 'pdufa'
      rationale    str        — short human-readable hook

    Returns {} when the file is missing or empty.
    """
    p = Path(catalysts_path)
    if not p.exists():
        return {}
    try:
        df = pd.read_parquet(p)
    except Exception as exc:
        log.warning("Could not load catalysts (%s)", exc)
        return {}
    if df.empty or "ticker" not in df.columns or "event_date" not in df.columns:
        return {}

    df = df.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df = df.dropna(subset=["event_date"])
    today = pd.Timestamp(as_of or date.today())
    horizon = today + pd.Timedelta(days=horizon_days)
    upcoming = df[(df["event_date"] >= today) & (df["event_date"] <= horizon)]
    if upcoming.empty:
        return {}

    # Keep only the *nearest* upcoming event per ticker
    upcoming = upcoming.sort_values("event_date").drop_duplicates("ticker", keep="first")

    overlay: dict[str, dict] = {}
    for _, row in upcoming.iterrows():
        days_until = int((row["event_date"] - today).days)
        score = float(max(0.0, 1.0 - days_until / max(horizon_days, 1)))
        overlay[str(row["ticker"])] = {
            "score": score,
            "next_date": row["event_date"].date(),
            "days_until": days_until,
            "category": str(row.get("category") or ""),
            "rationale": str(row.get("rationale") or ""),
        }
    return overlay


def _overlay_score(entry) -> float:
    """Coerce an overlay entry (dict or bare float) into its 0-1 score."""
    if entry is None:
        return 0.0
    if isinstance(entry, dict):
        return float(entry.get("score", 0.0) or 0.0)
    try:
        return float(entry)
    except (TypeError, ValueError):
        return 0.0


def pick_winners(
    view: pd.DataFrame,
    *,
    top_n: int = 15,
    blowoff_threshold_pct: float = 100.0,
    exclude_sell_zone: bool = True,
    weights: dict[str, float] | None = None,
    congress_overlay: dict[str, dict | float] | None = None,
    catalyst_overlay: dict[str, dict | float] | None = None,
) -> pd.DataFrame:
    """Composite winner-picker.

    Combines six normalised sub-scores per ticker into a single 0-1
    composite, subtracts a blow-off penalty (cap on chasing parabolic
    tops), sorts descending, and returns the top N.

    Sub-scores (each 0-1):
      analyst           — derived from BUY ZONE / APPROACHING / ... status
      reward_risk       — R:R to the analyst exit target, clipped at 5
      theme_momentum    — the theme's 3m median % through a logistic
      personal_momentum — (12m - 1m) % through the same logistic
      congress          — max asymmetry_score from candidates.parquet
                          (0 when no overlay supplied)
      catalyst          — proximity to the next upcoming catalyst within
                          the horizon (1.0 at 0 days, 0 at horizon)

    Overlays accept either a bare 0-1 float per ticker or a rich dict
    with a 'score' key — the latter lets the UI surface contextual detail
    without forcing a second lookup.
    """
    w = dict(DEFAULT_PICK_WEIGHTS)
    if weights:
        w.update(weights)
    c_overlay = congress_overlay or {}
    k_overlay = catalyst_overlay or {}

    if view.empty:
        return pd.DataFrame()

    heat = theme_heat(view)
    theme_3m: dict[str, float] = (
        dict(zip(heat["theme"], heat["median_3m"])) if not heat.empty else {}
    )

    rows: list[dict] = []
    for _, r in view.iterrows():
        status = r.get("status")
        if exclude_sell_zone and status == "SELL ZONE":
            continue

        ticker = str(r.get("ticker") or "").upper()
        theme = r.get("theme")
        pct_12m = r.get("pct_12m")
        pct_1m = r.get("pct_1m")
        # 12m-1m skips short-term reversal noise (Asness 2010)
        if pct_12m is not None and np.isfinite(pct_12m):
            skip = pct_1m if (pct_1m is not None and np.isfinite(pct_1m)) else 0.0
            mom_pct = float(pct_12m) - float(skip)
        else:
            mom_pct = None

        s_analyst = _analyst_status_score(status)
        s_rr = _rr_score(r.get("reward_risk"))
        s_theme = _logistic_pct(theme_3m.get(theme))
        s_mom = _logistic_pct(mom_pct)
        s_congress = _overlay_score(c_overlay.get(ticker))
        s_catalyst = _overlay_score(k_overlay.get(ticker))
        penalty = _blowoff_penalty(r.get("pct_6m"), blowoff_threshold_pct)

        composite = (
            w["analyst"] * s_analyst
            + w["reward_risk"] * s_rr
            + w["theme_momentum"] * s_theme
            + w["personal_momentum"] * s_mom
            + w["congress"] * s_congress
            + w["catalyst"] * s_catalyst
        ) - penalty
        composite = float(np.clip(composite, 0.0, 1.0))

        # Optional context fields for UI rendering (catalyst countdown etc.)
        cat_entry = k_overlay.get(ticker)
        catalyst_days = (
            cat_entry.get("days_until")
            if isinstance(cat_entry, dict) else None
        )
        catalyst_label = (
            cat_entry.get("category")
            if isinstance(cat_entry, dict) else None
        )
        cong_entry = c_overlay.get(ticker)
        congress_summary = (
            cong_entry.get("signal_summary")
            if isinstance(cong_entry, dict) else None
        )

        rows.append({
            "ticker": ticker,
            "name": r.get("name"),
            "theme": theme,
            "status": status,
            "live_price": r.get("live_price"),
            "target_entry": r.get("target_entry"),
            "target_exit": r.get("target_exit"),
            "reward_risk": r.get("reward_risk"),
            "pct_1m": pct_1m,
            "pct_3m": r.get("pct_3m"),
            "pct_6m": r.get("pct_6m"),
            "pct_12m": pct_12m,
            "score_analyst": s_analyst,
            "score_rr": s_rr,
            "score_theme": s_theme,
            "score_momentum": s_mom,
            "score_congress": s_congress,
            "score_catalyst": s_catalyst,
            "blowoff_penalty": penalty,
            "composite": composite,
            "catalyst_days": catalyst_days,
            "catalyst_label": catalyst_label,
            "congress_summary": congress_summary,
        })

    out = (
        pd.DataFrame(rows)
        .sort_values("composite", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    out.insert(0, "rank", out.index + 1)
    return out


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
