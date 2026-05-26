"""Phase 0 validation: prove the asymmetric filter adds alpha on real data.

This is the decision gate the project hinges on. It answers:

  Does the asymmetric filter beat the raw congressional-trade tape by
  >=2% mean cumulative abnormal return per holding period, on real
  Quiver data, after slippage?

If yes -> the filter has a real edge; proceed to Phase 1.
If no  -> the filter is noise; rethink before spending more.

The script:

1. Pulls real congressional trades from Quiver (requires QUIVER_API_KEY).
2. Loads actors + committees from unitedstates/congress-legislators
   (free, no key).
3. Fetches price history via yfinance for every unique ticker traded.
4. Runs the full scoring pipeline -> filtered AsymmetricCandidates.
5. Runs two backtests at 30/60/90/180/365-day horizons:
     - Filtered:  the top-N candidates by asymmetry_score.
     - Baseline:  every trade, no filter (the "naive congressional
                  trades" strategy).
6. Reports the delta in mean CAR, hit rate, and Sharpe between the two.
7. Writes a markdown report and prints a clear PROCEED / KILL verdict.
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

from .backtest.engine import bootstrap_mean_ci, compute_event_returns
from .config import load_config
from .ingest.committees import load_committee_actors
from .ingest.prices import fetch_prices
from .ingest.quiver import QuiverClient
from .pipeline import run_full_pipeline
from .schema import Actor, AsymmetricCandidate, Chamber, Trade

log = logging.getLogger(__name__)

HORIZONS = (30, 60, 90, 180, 365)
DEFAULT_TOP_N = 50

# The decision thresholds. These are conservative; they say "the filter
# has to outperform the naive baseline by at least 2% mean CAR at 90 days,
# with the delta's bootstrap CI not crossing zero" before we commit
# further spend.
ALPHA_THRESHOLD = 0.02
PRIMARY_HORIZON_DAYS = 90


@dataclass(frozen=True)
class HorizonResult:
    horizon_days: int
    n_filtered: int
    n_baseline: int
    mean_car_filtered: float
    mean_car_baseline: float
    delta_car: float
    delta_ci_lower: float
    delta_ci_upper: float
    hit_rate_filtered: float
    hit_rate_baseline: float


def _ensure_actors_for_trades(
    trades: list[Trade],
    actors: list[Actor],
) -> list[Actor]:
    """Add minimal Actor stubs for any actor_id that appears in trades but
    isn't in the committee feed (ex-members, missing bioguide mappings)."""
    known = {a.actor_id for a in actors}
    for t in trades:
        if t.actor_id not in known:
            actors.append(Actor(
                actor_id=t.actor_id,
                name=t.actor_id,
                chamber=Chamber.HOUSE,
            ))
            known.add(t.actor_id)
    return actors


def _all_trades_as_candidates(trades: list[Trade]) -> list[AsymmetricCandidate]:
    """Convert every trade into a no-op candidate so the baseline backtest
    sees the full unfiltered tape with score=0 (rank doesn't matter for
    the baseline)."""
    return [
        AsymmetricCandidate(
            trade_id=t.trade_id,
            ticker=t.ticker,
            actor_id=t.actor_id,
            asymmetry_score=0.0,
            signal_types=("baseline",),
            cluster_size=0,
            catalyst_pending=False,
            rationale="baseline (no filter)",
        )
        for t in trades
    ]


def _event_returns_for(
    trades_subset: list[Trade],
    prices: pd.DataFrame,
    bench: pd.Series,
    *,
    horizon_days: int,
    slippage_bps: float,
) -> list:
    return compute_event_returns(
        trades_subset, prices, bench,
        holding_period_days=horizon_days,
        slippage_bps=slippage_bps,
    )


def _horizon_metrics(
    filtered_trades: list[Trade],
    baseline_trades: list[Trade],
    prices: pd.DataFrame,
    bench: pd.Series,
    *,
    horizon_days: int,
    slippage_bps: float,
    bootstrap_iters: int = 1000,
) -> HorizonResult:
    er_f = _event_returns_for(
        filtered_trades, prices, bench,
        horizon_days=horizon_days, slippage_bps=slippage_bps,
    )
    er_b = _event_returns_for(
        baseline_trades, prices, bench,
        horizon_days=horizon_days, slippage_bps=slippage_bps,
    )
    cars_f = np.array([e.car_net_of_slippage for e in er_f]) if er_f else np.array([])
    cars_b = np.array([e.car_net_of_slippage for e in er_b]) if er_b else np.array([])

    mean_f = float(cars_f.mean()) if len(cars_f) else float("nan")
    mean_b = float(cars_b.mean()) if len(cars_b) else float("nan")
    delta = mean_f - mean_b

    # Bootstrap CI on the delta.
    rng = np.random.default_rng(42)
    deltas = np.empty(bootstrap_iters)
    if len(cars_f) and len(cars_b):
        for i in range(bootstrap_iters):
            deltas[i] = (
                rng.choice(cars_f, size=len(cars_f), replace=True).mean()
                - rng.choice(cars_b, size=len(cars_b), replace=True).mean()
            )
        ci_lo = float(np.quantile(deltas, 0.025))
        ci_hi = float(np.quantile(deltas, 0.975))
    else:
        ci_lo = ci_hi = float("nan")

    return HorizonResult(
        horizon_days=horizon_days,
        n_filtered=len(cars_f),
        n_baseline=len(cars_b),
        mean_car_filtered=mean_f,
        mean_car_baseline=mean_b,
        delta_car=delta,
        delta_ci_lower=ci_lo,
        delta_ci_upper=ci_hi,
        hit_rate_filtered=float((cars_f > 0).mean()) if len(cars_f) else float("nan"),
        hit_rate_baseline=float((cars_b > 0).mean()) if len(cars_b) else float("nan"),
    )


def run_phase0_validation(
    *,
    start: date = date(2018, 1, 1),
    end: date | None = None,
    top_n: int = DEFAULT_TOP_N,
    slippage_bps: float = 25.0,
    output_dir: Path | str = "docs",
) -> dict[str, Any]:
    """Orchestrate the Phase 0 validation end-to-end. Returns a summary dict
    and writes a markdown report under `output_dir`.
    """
    end = end or date.today()
    cfg = load_config()
    cache_dir = Path(cfg["paths"]["cache"])

    if not os.environ.get("QUIVER_API_KEY"):
        raise RuntimeError(
            "QUIVER_API_KEY not set. Phase 0 validation requires real data."
        )

    log.info("Pulling Quiver congressional trades from %s to %s", start, end)
    client = QuiverClient()
    trades = client.congress_trades(since=start)
    trades = [t for t in trades if start <= t.transaction_date <= end]
    log.info("Got %d trades from Quiver", len(trades))
    if len(trades) < 100:
        raise RuntimeError(
            f"Quiver returned only {len(trades)} trades — likely an auth or "
            "tier problem. Validation needs at least a few thousand."
        )

    log.info("Loading committee actors from unitedstates/congress-legislators")
    actors = load_committee_actors(cache_dir)
    actors = _ensure_actors_for_trades(trades, actors)

    log.info("Fetching price history for %d tickers via yfinance", len({t.ticker for t in trades}))
    tickers = sorted({t.ticker for t in trades})
    prices, price_returns, bench_returns = fetch_prices(
        tickers,
        start=start - timedelta(days=30),
        end=end + timedelta(days=400),
        cache_dir=cache_dir,
    )

    log.info("Running scoring pipeline on real data")
    result = run_full_pipeline(cfg, trades, actors, prices=prices)
    ranked = sorted(result.candidates, key=lambda c: -c.asymmetry_score)
    top = ranked[:top_n]
    log.info("Filter retained %d / %d candidates; top_n=%d", len(ranked), len(trades), top_n)

    trade_lookup = {t.trade_id: t for t in trades}
    filtered_trades = [trade_lookup[c.trade_id] for c in top if c.trade_id in trade_lookup]
    baseline_trades = trades  # the no-filter benchmark

    log.info("Running horizon backtests at %s days", HORIZONS)
    results: list[HorizonResult] = []
    for h in HORIZONS:
        r = _horizon_metrics(
            filtered_trades, baseline_trades,
            price_returns, bench_returns,
            horizon_days=h, slippage_bps=slippage_bps,
        )
        results.append(r)

    # Decision logic on the primary horizon.
    primary = next(r for r in results if r.horizon_days == PRIMARY_HORIZON_DAYS)
    proceed = (
        primary.delta_car >= ALPHA_THRESHOLD
        and primary.delta_ci_lower > 0
    )
    verdict = "PROCEED" if proceed else "KILL"

    report_path = Path(output_dir) / "phase0_validation.md"
    _write_report(
        report_path,
        start=start, end=end, top_n=top_n, slippage_bps=slippage_bps,
        n_total_trades=len(trades),
        n_filtered=len(filtered_trades),
        results=results,
        verdict=verdict,
        primary=primary,
    )
    log.info("Wrote validation report to %s", report_path)
    return {
        "verdict": verdict,
        "primary": primary,
        "results": results,
        "report_path": str(report_path),
    }


def _fmt_pct(x: float) -> str:
    return "n/a" if not np.isfinite(x) else f"{x * 100:+.2f}%"


def _write_report(
    path: Path,
    *,
    start: date, end: date,
    top_n: int, slippage_bps: float,
    n_total_trades: int, n_filtered: int,
    results: list[HorizonResult],
    verdict: str,
    primary: HorizonResult,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Phase 0 validation — real-data backtest\n")
    lines.append(f"- Window: **{start} → {end}**")
    lines.append(f"- Top-N filtered: **{top_n}**")
    lines.append(f"- Slippage assumption: **{slippage_bps} bps** round-trip")
    lines.append(f"- Total raw trades: **{n_total_trades:,}**")
    lines.append(f"- Filtered candidates surviving asymmetric filter: **{n_filtered:,}**\n")

    lines.append("## Horizon results\n")
    lines.append("| Days | n filtered | n baseline | CAR filtered | CAR baseline | **Delta** | 95% CI on delta | Hit (F) | Hit (B) |")
    lines.append("|---:|---:|---:|---:|---:|---:|---|---:|---:|")
    for r in results:
        lines.append(
            f"| {r.horizon_days} | {r.n_filtered} | {r.n_baseline} | "
            f"{_fmt_pct(r.mean_car_filtered)} | {_fmt_pct(r.mean_car_baseline)} | "
            f"**{_fmt_pct(r.delta_car)}** | "
            f"[{_fmt_pct(r.delta_ci_lower)}, {_fmt_pct(r.delta_ci_upper)}] | "
            f"{_fmt_pct(r.hit_rate_filtered)} | {_fmt_pct(r.hit_rate_baseline)} |"
        )
    lines.append("")

    lines.append("## Decision gate\n")
    lines.append(
        f"Primary horizon: **{PRIMARY_HORIZON_DAYS} days**. Threshold: filter "
        f"must beat baseline by **≥{ALPHA_THRESHOLD * 100:.0f}%** mean CAR with "
        "the 95% bootstrap CI of the delta not crossing zero.\n"
    )
    lines.append(f"- Observed delta: **{_fmt_pct(primary.delta_car)}**")
    lines.append(
        f"- Delta 95% CI: [{_fmt_pct(primary.delta_ci_lower)}, "
        f"{_fmt_pct(primary.delta_ci_upper)}]\n"
    )
    lines.append(f"## Verdict: **{verdict}**\n")
    if verdict == "PROCEED":
        lines.append(
            "The asymmetric filter clears the decision gate. Move on to "
            "Phase 1 — add insider, momentum, quality and earnings-revision "
            "layers; re-validate on the combined signal.\n"
        )
    else:
        lines.append(
            "The asymmetric filter does not clear the decision gate. Before "
            "spending on Apple Developer / Railway / a native app, revisit "
            "filter weights, look at per-actor / per-sector breakdowns, "
            "and consider whether the layered Phase 1 signals (insider + "
            "momentum + earnings revisions) would change the picture.\n"
        )

    path.write_text("\n".join(lines), encoding="utf-8")
