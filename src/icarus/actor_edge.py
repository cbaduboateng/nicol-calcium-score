"""Actor-edge metrics: per-member realised return on their own trades.

Pure functions for ranking congressional members by trading performance:
counts trades, computes hit rate, mean return, and cumulative return for
each actor over a configurable window (default: year-to-date).

This is the simpler, frequentist-style view the tester asked for. A
shrinkage / IR variant for the picker overlay will follow once we've
validated the UI and data flow.

Returns are computed as ``(current_price - entry_price) / entry_price``
where entry_price is the close on (or asof) the transaction_date and
current_price is the most recent close in the price frame. Buys only —
sells without buy-side matching are confusing to surface.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _year_start(d: date) -> date:
    return date(d.year, 1, 1)


def compute_trade_returns(
    trades: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of: date | None = None,
    ytd_only: bool = True,
    direction_filter: str | None = "buy",
) -> pd.DataFrame:
    """For each trade, compute the % return from transaction_date to as_of.

    ``prices`` has ticker columns and a DatetimeIndex. Entry price uses
    as-of matching (closest prior trading day) so weekend / holiday
    transactions still resolve. Trades whose ticker isn't in the price
    frame are silently dropped.
    """
    if trades.empty or prices.empty:
        return pd.DataFrame()

    as_of_d = as_of or date.today()
    df = trades.copy()
    df["transaction_date"] = pd.to_datetime(df["transaction_date"]).dt.date

    if direction_filter is not None and "direction" in df.columns:
        df = df[df["direction"] == direction_filter]
    if ytd_only:
        df = df[df["transaction_date"] >= _year_start(as_of_d)]
    if df.empty:
        return pd.DataFrame()

    prices = prices.copy()
    prices.index = pd.to_datetime(prices.index)

    rows: list[dict] = []
    for _, t in df.iterrows():
        ticker = str(t["ticker"]).upper()
        if ticker not in prices.columns:
            continue
        series = prices[ticker].dropna()
        if series.empty:
            continue
        tx_ts = pd.Timestamp(t["transaction_date"])
        on_or_before = series[series.index <= tx_ts]
        if on_or_before.empty:
            continue
        entry_price = float(on_or_before.iloc[-1])
        if entry_price <= 0:
            continue
        current_price = float(series.iloc[-1])
        return_pct = (current_price - entry_price) / entry_price * 100.0
        days_held = (as_of_d - t["transaction_date"]).days
        rows.append({
            "trade_id": t.get("trade_id"),
            "actor_id": t.get("actor_id"),
            "ticker": ticker,
            "transaction_date": t["transaction_date"],
            "direction": t.get("direction"),
            "entry_price": entry_price,
            "current_price": current_price,
            "return_pct": return_pct,
            "days_held": days_held,
            "size_usd": t.get("amount_midpoint_usd"),
            "winner": bool(return_pct > 0),
        })
    return pd.DataFrame(rows)


def compute_actor_edge(
    trade_returns: pd.DataFrame,
    *,
    actors: pd.DataFrame | None = None,
    min_trades: int = 1,
) -> pd.DataFrame:
    """Aggregate trade-level returns into per-actor edge metrics.

    Output columns:
      actor_id, name, party, state, chamber  (when actors df supplied)
      n_trades, n_winners, n_losers, hit_rate
      mean_return_pct, median_return_pct, cumulative_return_pct
      best_return_pct, worst_return_pct, avg_days_held
    """
    if trade_returns.empty:
        return pd.DataFrame()

    grp = trade_returns.groupby("actor_id").agg(
        n_trades=("trade_id", "count"),
        n_winners=("winner", "sum"),
        mean_return_pct=("return_pct", "mean"),
        median_return_pct=("return_pct", "median"),
        cumulative_return_pct=("return_pct", "sum"),
        best_return_pct=("return_pct", "max"),
        worst_return_pct=("return_pct", "min"),
        avg_days_held=("days_held", "mean"),
    ).reset_index()
    grp["n_winners"] = grp["n_winners"].astype(int)
    grp["n_losers"] = grp["n_trades"] - grp["n_winners"]
    grp["hit_rate"] = grp["n_winners"] / grp["n_trades"]
    grp = grp[grp["n_trades"] >= min_trades]

    if actors is not None and not actors.empty and "actor_id" in actors.columns:
        meta_cols = [c for c in ("actor_id", "name", "chamber", "party", "state")
                     if c in actors.columns]
        grp = grp.merge(actors[meta_cols], on="actor_id", how="left")

    return grp.sort_values("mean_return_pct", ascending=False).reset_index(drop=True)


def build_actor_edge_files(
    trades_path: Path | str = "data/processed/trades.parquet",
    actors_path: Path | str = "data/processed/actors.parquet",
    cache_dir: Path | str = "data/cache",
    out_dir: Path | str = "data/processed",
    *,
    as_of: date | None = None,
    ytd_only: bool = True,
) -> tuple[Path | None, Path | None]:
    """Orchestrate the price fetch + edge calc, persist parquets."""
    trades_path = Path(trades_path)
    actors_path = Path(actors_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not trades_path.exists():
        log.warning("trades.parquet missing; skipping actor edge build")
        return None, None

    trades = pd.read_parquet(trades_path)
    if trades.empty:
        return None, None

    as_of_d = as_of or date.today()
    trades_filtered = trades.copy()
    trades_filtered["transaction_date"] = pd.to_datetime(
        trades_filtered["transaction_date"]
    ).dt.date
    if "direction" in trades_filtered.columns:
        trades_filtered = trades_filtered[trades_filtered["direction"] == "buy"]
    if ytd_only:
        trades_filtered = trades_filtered[
            trades_filtered["transaction_date"] >= _year_start(as_of_d)
        ]

    if trades_filtered.empty:
        log.info("No YTD buy trades; nothing to score")
        return None, None

    tickers = sorted(set(trades_filtered["ticker"].astype(str).str.upper()))
    earliest = trades_filtered["transaction_date"].min()
    log.info(
        "Fetching prices for %d tickers from %s to %s for actor edge",
        len(tickers), earliest, as_of_d,
    )

    from .ingest.prices import fetch_prices
    try:
        prices, _, _ = fetch_prices(
            tickers,
            start=earliest - timedelta(days=10),
            end=as_of_d,
            cache_dir=Path(cache_dir),
        )
    except Exception as exc:
        log.warning("Price fetch failed for actor edge (%s)", exc)
        return None, None

    tr = compute_trade_returns(
        trades_filtered, prices,
        as_of=as_of_d, ytd_only=False, direction_filter=None,
    )
    if tr.empty:
        log.info("compute_trade_returns produced no rows; skipping persist")
        return None, None

    actors = pd.read_parquet(actors_path) if actors_path.exists() else pd.DataFrame()
    edge = compute_actor_edge(tr, actors=actors, min_trades=1)

    tr_path = out_dir / "trade_returns.parquet"
    edge_path = out_dir / "actor_edge.parquet"
    tr.to_parquet(tr_path)
    edge.to_parquet(edge_path)
    log.info(
        "Persisted trade_returns (%d rows), actor_edge (%d actors)",
        len(tr), len(edge),
    )
    return tr_path, edge_path


def load_actor_edge(
    path: Path | str = "data/processed/actor_edge.parquet",
) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception as exc:
        log.warning("Could not load actor_edge (%s)", exc)
        return pd.DataFrame()


def load_trade_returns(
    path: Path | str = "data/processed/trade_returns.parquet",
) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception as exc:
        log.warning("Could not load trade_returns (%s)", exc)
        return pd.DataFrame()
