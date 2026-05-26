"""Path A diagnostic: figure out why the asymmetric filter underperformed
baseline in Phase 0.

Breaks down event returns at the primary horizon across many dimensions
(chamber, party, sector, direction, disclosure speed, cluster size, trade
size, signal types, per-actor) to identify viable sub-populations where
the filter does add alpha — and to spot where it actively destroys value.

Output: a thorough markdown report at `docs/phase0_diagnostic.md`.

Usage:
    csig diagnose --start 2018-01-01
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest.engine import compute_event_returns
from .config import load_config
from .ingest.committees import load_committee_actors
from .ingest.prices import fetch_prices
from .ingest.quiver import QuiverClient
from .pipeline import run_full_pipeline
from .schema import Actor, Chamber, Trade
from .ticker_facts import lookup as ticker_lookup, top_level_category

log = logging.getLogger(__name__)

PRIMARY_HORIZON = 90


# ---------------------------------------------------------------------------
# Metadata frame: one row per trade with everything the breakdown needs
# ---------------------------------------------------------------------------


def _build_metadata_frame(
    trades: list[Trade],
    actors: list[Actor],
    filtered_trade_ids: set[str],
    candidate_signal_types: dict[str, tuple[str, ...]],
    candidate_cluster_size: dict[str, int],
    candidate_catalyst_pending: dict[str, bool],
) -> pd.DataFrame:
    actor_by_id = {a.actor_id: a for a in actors}
    rows: list[dict[str, Any]] = []
    for t in trades:
        actor = actor_by_id.get(t.actor_id)
        fact = ticker_lookup(t.ticker)
        days_to_disclose = (t.disclosure_date - t.transaction_date).days
        rows.append({
            "trade_id": t.trade_id,
            "actor_id": t.actor_id,
            "actor_name": actor.name if actor else t.actor_id,
            "chamber": (actor.chamber.value if actor and actor.chamber else "unknown"),
            "party": actor.party if actor else None,
            "state": actor.state if actor else None,
            "ticker": t.ticker,
            "company": fact.name if fact else None,
            "sector": fact.sector if fact else None,
            "category": top_level_category(fact.sector) if fact else "Other",
            "cap": fact.cap if fact else None,
            "direction": t.direction.value if t.direction else "unknown",
            "transaction_date": t.transaction_date,
            "disclosure_date": t.disclosure_date,
            "days_to_disclose": days_to_disclose,
            "amount_min_usd": t.amount_min_usd,
            "amount_max_usd": t.amount_max_usd,
            "in_filter": t.trade_id in filtered_trade_ids,
            "signal_types": ", ".join(candidate_signal_types.get(t.trade_id, ())),
            "cluster_size": candidate_cluster_size.get(t.trade_id, 0),
            "catalyst_pending": candidate_catalyst_pending.get(t.trade_id, False),
        })
    return pd.DataFrame(rows)


def _disclosure_speed_bin(days: int) -> str:
    if days <= 7:
        return "0-7 days (very fast)"
    if days <= 14:
        return "8-14 days (fast)"
    if days <= 30:
        return "15-30 days (normal)"
    if days <= 45:
        return "31-45 days (slow, near limit)"
    return ">45 days (late)"


def _amount_bin(amount_max: float) -> str:
    if amount_max <= 15_000:
        return "$1k-$15k"
    if amount_max <= 50_000:
        return "$15k-$50k"
    if amount_max <= 100_000:
        return "$50k-$100k"
    if amount_max <= 250_000:
        return "$100k-$250k"
    if amount_max <= 1_000_000:
        return "$250k-$1M"
    if amount_max <= 5_000_000:
        return "$1M-$5M"
    return ">$5M"


def _cluster_bin(n: int) -> str:
    if n <= 1:
        return "1 (solo)"
    if n == 2:
        return "2 (pair)"
    if n <= 4:
        return "3-4 (small cluster)"
    return "5+ (large cluster)"


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _summarise(cars: pd.Series) -> dict[str, float]:
    if cars.empty:
        return {"n": 0, "mean_car": float("nan"), "hit_rate": float("nan")}
    return {
        "n": int(len(cars)),
        "mean_car": float(cars.mean()),
        "hit_rate": float((cars > 0).mean()),
    }


def _breakdown(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Group `df` by `group_col`, split into filtered vs baseline, and
    return a per-group summary table. Baseline here means the full universe
    *including* the filtered rows — same convention as Phase 0."""
    out: list[dict[str, Any]] = []
    if group_col not in df.columns:
        return pd.DataFrame()
    for group_val, slc in df.groupby(group_col, dropna=False):
        f = slc[slc["in_filter"]]
        # Baseline = the whole group (matches Phase 0 baseline definition).
        b = slc
        f_summary = _summarise(f["car"].dropna())
        b_summary = _summarise(b["car"].dropna())
        out.append({
            "group": "—" if pd.isna(group_val) else str(group_val),
            "n_filtered": f_summary["n"],
            "n_baseline": b_summary["n"],
            "car_filtered": f_summary["mean_car"],
            "car_baseline": b_summary["mean_car"],
            "delta": (
                f_summary["mean_car"] - b_summary["mean_car"]
                if not (np.isnan(f_summary["mean_car"]) or np.isnan(b_summary["mean_car"]))
                else float("nan")
            ),
            "hit_filtered": f_summary["hit_rate"],
            "hit_baseline": b_summary["hit_rate"],
        })
    return pd.DataFrame(out).sort_values("n_filtered", ascending=False)


def _per_actor_top_bottom(df: pd.DataFrame, k: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank actors by mean CAR across their *baseline* trades (filtered is too
    sparse). Returns (top-k by mean CAR, bottom-k by mean CAR)."""
    per_actor = (
        df.dropna(subset=["car"])
        .groupby(["actor_id", "actor_name", "chamber", "party"], dropna=False)
        .agg(
            n=("car", "count"),
            mean_car=("car", "mean"),
            hit_rate=("car", lambda s: float((s > 0).mean())),
            n_filtered=("in_filter", "sum"),
        )
        .reset_index()
    )
    # Require at least 20 trades for stability.
    stable = per_actor[per_actor["n"] >= 20].copy()
    top = stable.sort_values("mean_car", ascending=False).head(k).reset_index(drop=True)
    bottom = stable.sort_values("mean_car", ascending=True).head(k).reset_index(drop=True)
    return top, bottom


def _per_signal_type(df: pd.DataFrame) -> pd.DataFrame:
    """Split filtered candidates by each individual signal type they carry."""
    rows: list[dict[str, Any]] = []
    f = df[df["in_filter"]].copy()
    if f.empty:
        return pd.DataFrame()
    # Each candidate has a comma-separated signal_types string; split and
    # tabulate per individual signal label.
    seen_labels: set[str] = set()
    for s in f["signal_types"]:
        if not isinstance(s, str):
            continue
        for part in s.split(","):
            label = part.strip()
            if label:
                seen_labels.add(label)
    for label in sorted(seen_labels):
        match = f[f["signal_types"].str.contains(label, regex=False, na=False)]
        cars = match["car"].dropna()
        rows.append({
            "signal": label,
            "n": int(len(cars)),
            "mean_car": float(cars.mean()) if len(cars) else float("nan"),
            "hit_rate": float((cars > 0).mean()) if len(cars) else float("nan"),
        })
    return pd.DataFrame(rows).sort_values("mean_car", ascending=False)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_diagnostic(
    *,
    start: date = date(2018, 1, 1),
    end: date | None = None,
    top_n: int = 50,
    slippage_bps: float = 25.0,
    horizon_days: int = PRIMARY_HORIZON,
    output_dir: Path | str = "docs",
) -> dict[str, Any]:
    """Run the diagnostic and write a markdown report."""
    end = end or date.today()
    cfg = load_config()
    cache_dir = Path(cfg["paths"]["cache"])

    if not os.environ.get("QUIVER_API_KEY"):
        raise RuntimeError("QUIVER_API_KEY not set; diagnostic needs real data.")

    log.info("Pulling Quiver trades %s..%s", start, end)
    client = QuiverClient()
    trades = client.congress_trades(since=start)
    trades = [t for t in trades if start <= t.transaction_date <= end]
    log.info("Got %d Quiver trades", len(trades))

    log.info("Loading committee actors")
    actors = load_committee_actors(cache_dir)
    known = {a.actor_id for a in actors}
    for t in trades:
        if t.actor_id not in known:
            actors.append(Actor(actor_id=t.actor_id, name=t.actor_id, chamber=Chamber.HOUSE))
            known.add(t.actor_id)

    log.info("Fetching prices for %d unique tickers", len({t.ticker for t in trades}))
    tickers = sorted({t.ticker for t in trades})
    prices, price_returns, bench_returns = fetch_prices(
        tickers,
        start=start - timedelta(days=30),
        end=end + timedelta(days=horizon_days + 30),
        cache_dir=cache_dir,
    )

    log.info("Running scoring pipeline")
    pipeline_result = run_full_pipeline(cfg, trades, actors, prices=prices)
    ranked = sorted(pipeline_result.candidates, key=lambda c: -c.asymmetry_score)
    top = ranked[:top_n]
    filtered_trade_ids = {c.trade_id for c in top}
    sig_types = {c.trade_id: c.signal_types for c in top}
    cluster_sizes = {c.trade_id: c.cluster_size for c in top}
    catalyst_pending = {c.trade_id: c.catalyst_pending for c in top}

    log.info("Computing event returns at %d days", horizon_days)
    event_returns = compute_event_returns(
        trades, price_returns, bench_returns,
        holding_period_days=horizon_days,
        slippage_bps=slippage_bps,
    )
    er_map = {e.trade_id: e for e in event_returns}

    log.info("Building metadata frame for %d trades", len(trades))
    df = _build_metadata_frame(
        trades, actors, filtered_trade_ids,
        sig_types, cluster_sizes, catalyst_pending,
    )
    df["car"] = df["trade_id"].map(
        {tid: e.car_net_of_slippage for tid, e in er_map.items()},
    )
    df["speed_bin"] = df["days_to_disclose"].apply(_disclosure_speed_bin)
    df["amount_bin"] = df["amount_max_usd"].apply(
        lambda x: _amount_bin(x) if pd.notna(x) else "unknown",
    )
    df["cluster_bin"] = df["cluster_size"].apply(_cluster_bin)

    log.info("Running breakdowns")
    headline = {
        "n_filtered": int(df["in_filter"].sum()),
        "n_baseline": int(len(df)),
        "car_filtered": float(df[df["in_filter"]]["car"].dropna().mean()),
        "car_baseline": float(df["car"].dropna().mean()),
        "hit_filtered": float((df[df["in_filter"]]["car"].dropna() > 0).mean()),
        "hit_baseline": float((df["car"].dropna() > 0).mean()),
    }
    breakdowns = {
        "Chamber":          _breakdown(df, "chamber"),
        "Party":            _breakdown(df, "party"),
        "Direction":        _breakdown(df, "direction"),
        "Sector (top-level)": _breakdown(df, "category"),
        "Market-cap bucket": _breakdown(df, "cap"),
        "Disclosure speed": _breakdown(df, "speed_bin"),
        "Trade size bracket": _breakdown(df, "amount_bin"),
        "Cluster size":     _breakdown(df, "cluster_bin"),
        "Catalyst pending": _breakdown(df, "catalyst_pending"),
    }
    top_actors, bottom_actors = _per_actor_top_bottom(df, k=20)
    signal_breakdown = _per_signal_type(df)

    out_path = Path(output_dir) / "phase0_diagnostic.md"
    _write_report(
        out_path,
        start=start, end=end, top_n=top_n, horizon=horizon_days,
        slippage_bps=slippage_bps,
        headline=headline,
        breakdowns=breakdowns,
        top_actors=top_actors, bottom_actors=bottom_actors,
        signal_breakdown=signal_breakdown,
    )
    log.info("Wrote diagnostic report to %s", out_path)
    return {
        "report_path": str(out_path),
        "headline": headline,
        "breakdowns": {k: v.to_dict("records") for k, v in breakdowns.items()},
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _pct(x: float) -> str:
    return "—" if not np.isfinite(x) else f"{x * 100:+.2f}%"


def _table(rows: pd.DataFrame, cols: list[tuple[str, str, str]]) -> list[str]:
    """Render a markdown table. `cols` is a list of (col_name, header, fmt)
    where fmt is one of 'pct', 'int', 'str'."""
    out: list[str] = []
    out.append("| " + " | ".join(h for _, h, _ in cols) + " |")
    out.append("|" + "|".join("---:" if f != "str" else "---" for _, _, f in cols) + "|")
    for _, r in rows.iterrows():
        cells = []
        for col, _, fmt in cols:
            v = r.get(col)
            if fmt == "pct":
                cells.append(_pct(v) if v is not None else "—")
            elif fmt == "int":
                cells.append(str(int(v)) if pd.notna(v) else "—")
            else:
                cells.append("—" if pd.isna(v) else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return out


_BREAKDOWN_COLS = [
    ("group",         "Group",          "str"),
    ("n_filtered",    "n filt",         "int"),
    ("n_baseline",    "n base",         "int"),
    ("car_filtered",  "CAR filt",       "pct"),
    ("car_baseline",  "CAR base",       "pct"),
    ("delta",         "Δ (filt-base)",  "pct"),
    ("hit_filtered",  "Hit filt",       "pct"),
    ("hit_baseline",  "Hit base",       "pct"),
]

_ACTOR_COLS = [
    ("actor_name",  "Member",      "str"),
    ("chamber",     "Chamber",     "str"),
    ("party",       "Party",       "str"),
    ("n",           "Trades",      "int"),
    ("n_filtered",  "In filter",   "int"),
    ("mean_car",    "Mean CAR",    "pct"),
    ("hit_rate",    "Hit rate",    "pct"),
]

_SIGNAL_COLS = [
    ("signal",   "Signal type", "str"),
    ("n",        "n",           "int"),
    ("mean_car", "Mean CAR",    "pct"),
    ("hit_rate", "Hit rate",    "pct"),
]


def _write_report(
    path: Path,
    *,
    start: date, end: date,
    top_n: int, horizon: int, slippage_bps: float,
    headline: dict[str, Any],
    breakdowns: dict[str, pd.DataFrame],
    top_actors: pd.DataFrame, bottom_actors: pd.DataFrame,
    signal_breakdown: pd.DataFrame,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# Phase 0 diagnostic — why did the filter underperform?\n")
    lines.append(f"- Window: **{start} → {end}**")
    lines.append(f"- Primary horizon: **{horizon} days**")
    lines.append(f"- Top-N filter: **{top_n}**")
    lines.append(f"- Slippage assumption: **{slippage_bps} bps** round-trip\n")

    lines.append("## Headline\n")
    lines.append("| | Filtered | Baseline (all) | Delta |")
    lines.append("|---|---:|---:|---:|")
    delta = headline["car_filtered"] - headline["car_baseline"]
    lines.append(
        f"| n | {headline['n_filtered']:,} | {headline['n_baseline']:,} | — |"
    )
    lines.append(
        f"| Mean CAR | {_pct(headline['car_filtered'])} | "
        f"{_pct(headline['car_baseline'])} | **{_pct(delta)}** |"
    )
    lines.append(
        f"| Hit rate | {_pct(headline['hit_filtered'])} | "
        f"{_pct(headline['hit_baseline'])} | — |"
    )
    lines.append("")

    for name, frame in breakdowns.items():
        lines.append(f"## {name}\n")
        if frame.empty:
            lines.append("_no data_\n")
            continue
        lines.extend(_table(frame, _BREAKDOWN_COLS))
        lines.append("")

    lines.append("## Top 20 actors by mean CAR (≥20 trades, baseline)\n")
    if top_actors.empty:
        lines.append("_no actor with ≥20 trades_\n")
    else:
        lines.extend(_table(top_actors, _ACTOR_COLS))
        lines.append("")

    lines.append("## Bottom 20 actors by mean CAR (≥20 trades, baseline)\n")
    if bottom_actors.empty:
        lines.append("_no actor with ≥20 trades_\n")
    else:
        lines.extend(_table(bottom_actors, _ACTOR_COLS))
        lines.append("")

    lines.append("## Signal-type breakdown (filtered candidates only)\n")
    if signal_breakdown.empty:
        lines.append("_no signal-type breakdown_\n")
    else:
        lines.extend(_table(signal_breakdown, _SIGNAL_COLS))
        lines.append("")

    lines.append("## Reading this report\n")
    lines.append(
        "- **Group**: the slice. **n filt / base**: number of trades in the "
        "filter top-N vs in the full baseline. **CAR**: mean cumulative "
        "abnormal return at the primary horizon, net of slippage. "
        "**Δ**: filtered minus baseline within the same group. **Hit rate**: "
        "share with positive CAR.\n"
    )
    lines.append(
        "- A **positive Δ in a group** is the alpha pocket — the filter "
        "is genuinely picking winners within that slice. A consistently "
        "**negative Δ across all groups** means the filter is broken; a "
        "**bimodal Δ** (good in some slices, bad in others) means we can "
        "rescue it by restricting to the good slices and reweighting.\n"
    )

    path.write_text("\n".join(lines), encoding="utf-8")
