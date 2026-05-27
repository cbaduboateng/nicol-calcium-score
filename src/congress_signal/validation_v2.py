"""Phase 0 v2: actor-skill-weighted validation.

The Phase 0 diagnostic told us individual member skill is the strongest
signal in the data. Sara Jacobs hits 96% of trades, John Larson hits 10%,
across hundreds of trades each. The original asymmetric filter weighted
committee relevance + trade-attribute z-scores; this v2 puts walk-forward
per-actor historical mean CAR as the dominant ranking signal.

Hypothesis: ranking trades by their actor's trailing-12m mean CAR (no
lookahead) and taking the top-N produces meaningfully higher CAR than
either the original filter or the naive baseline.

Output: `docs/phase0_v2_validation.md` with the same horizon table as
Phase 0 plus an explicit per-actor coverage breakdown.
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
from .scoring.actor_skill import compute_actor_skill
from .schema import Actor, Chamber, Trade

log = logging.getLogger(__name__)


HORIZONS = (30, 60, 90, 180, 365)
PRIMARY_HORIZON_DAYS = 90
ALPHA_THRESHOLD = 0.02


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


def _fmt_pct(x: float) -> str:
    return "n/a" if not np.isfinite(x) else f"{x * 100:+.2f}%"


def _ensure_actors_for_trades(
    trades: list[Trade],
    actors: list[Actor],
) -> list[Actor]:
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


def _horizon_metrics(
    filtered_trades: list[Trade],
    baseline_trades: list[Trade],
    price_returns: pd.DataFrame,
    bench_returns: pd.Series,
    *,
    horizon_days: int,
    slippage_bps: float,
    bootstrap_iters: int = 1000,
) -> HorizonResult:
    er_f = compute_event_returns(
        filtered_trades, price_returns, bench_returns,
        holding_period_days=horizon_days, slippage_bps=slippage_bps,
    )
    er_b = compute_event_returns(
        baseline_trades, price_returns, bench_returns,
        holding_period_days=horizon_days, slippage_bps=slippage_bps,
    )
    cars_f = np.array([e.car_net_of_slippage for e in er_f]) if er_f else np.array([])
    cars_b = np.array([e.car_net_of_slippage for e in er_b]) if er_b else np.array([])
    mean_f = float(cars_f.mean()) if len(cars_f) else float("nan")
    mean_b = float(cars_b.mean()) if len(cars_b) else float("nan")
    delta = mean_f - mean_b

    rng = np.random.default_rng(42)
    if len(cars_f) and len(cars_b):
        deltas = np.empty(bootstrap_iters)
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


def run_phase0_v2(
    *,
    start: date = date(2018, 1, 1),
    end: date | None = None,
    top_n: int = 50,
    slippage_bps: float = 25.0,
    min_prior_trades: int = 10,
    lookback_days: int = 365,
    output_dir: Path | str = "docs",
) -> dict[str, Any]:
    """Run Phase 0 v2: rank trades by walk-forward actor skill, take top-N,
    backtest at multiple horizons, compare to naive baseline."""
    end = end or date.today()
    cfg = load_config()
    cache_dir = Path(cfg["paths"]["cache"])

    if not os.environ.get("QUIVER_API_KEY"):
        raise RuntimeError("QUIVER_API_KEY not set; v2 validation needs real data.")

    log.info("Pulling Quiver trades %s..%s", start, end)
    client = QuiverClient()
    trades = client.congress_trades(since=start)
    trades = [t for t in trades if start <= t.transaction_date <= end]
    log.info("Got %d trades from Quiver", len(trades))

    log.info("Loading committee actors")
    actors = load_committee_actors(cache_dir)
    actors = _ensure_actors_for_trades(trades, actors)

    log.info("Fetching prices for %d unique tickers", len({t.ticker for t in trades}))
    tickers = sorted({t.ticker for t in trades})
    prices, price_returns, bench_returns = fetch_prices(
        tickers,
        start=start - timedelta(days=30),
        end=end + timedelta(days=400),
        cache_dir=cache_dir,
    )

    # Compute event returns at the primary horizon — needed both for the
    # walk-forward actor-skill scorer AND for the horizon backtests.
    log.info("Computing event returns at %d days for skill calculation", PRIMARY_HORIZON_DAYS)
    primary_event_returns = compute_event_returns(
        trades, price_returns, bench_returns,
        holding_period_days=PRIMARY_HORIZON_DAYS,
        slippage_bps=slippage_bps,
    )
    log.info(
        "Computed %d event returns (of %d trades — rest lack price data)",
        len(primary_event_returns), len(trades),
    )

    log.info(
        "Computing walk-forward actor skill (lookback=%dd, min priors=%d)",
        lookback_days, min_prior_trades,
    )
    skill_scores = compute_actor_skill(
        trades, primary_event_returns,
        lookback_days=lookback_days,
        holding_period_days=PRIMARY_HORIZON_DAYS,
        min_prior_trades=min_prior_trades,
    )

    # Only rank trades that have a meaningful skill score (not the neutral
    # 0.5 fallback for actors with too few priors).
    ranked = sorted(
        (s for s in skill_scores.values() if s.n_prior_trades >= min_prior_trades),
        key=lambda s: -s.skill,
    )
    top_ids = [s.trade_id for s in ranked[:top_n]]
    log.info(
        "Ranked %d trades with sufficient actor history; top-%d picked",
        len(ranked), top_n,
    )

    trade_lookup = {t.trade_id: t for t in trades}
    filtered_trades = [trade_lookup[tid] for tid in top_ids if tid in trade_lookup]
    baseline_trades = trades  # naive: every trade

    # Per-actor coverage: how many distinct actors are in the top-N?
    actor_ids_in_filter = {t.actor_id for t in filtered_trades}
    actor_name_lookup = {a.actor_id: a.name for a in actors}
    skill_lookup = {s.trade_id: s for s in ranked}

    log.info("Running horizon backtests at %s days", HORIZONS)
    results: list[HorizonResult] = []
    for h in HORIZONS:
        results.append(_horizon_metrics(
            filtered_trades, baseline_trades,
            price_returns, bench_returns,
            horizon_days=h, slippage_bps=slippage_bps,
        ))

    primary = next(r for r in results if r.horizon_days == PRIMARY_HORIZON_DAYS)
    proceed = (
        primary.delta_car >= ALPHA_THRESHOLD
        and primary.delta_ci_lower > 0
    )
    verdict = "PROCEED" if proceed else "KILL"

    out_path = Path(output_dir) / "phase0_v2_validation.md"
    _write_report(
        out_path,
        start=start, end=end, top_n=top_n, slippage_bps=slippage_bps,
        min_prior_trades=min_prior_trades, lookback_days=lookback_days,
        n_total_trades=len(trades),
        n_with_event_returns=len(primary_event_returns),
        n_with_skill=len(ranked),
        n_filtered=len(filtered_trades),
        n_distinct_actors=len(actor_ids_in_filter),
        actor_name_lookup=actor_name_lookup,
        skill_lookup=skill_lookup,
        filtered_trades=filtered_trades,
        results=results,
        verdict=verdict,
        primary=primary,
    )
    log.info("Wrote validation v2 report to %s", out_path)
    return {
        "verdict": verdict,
        "primary": primary,
        "results": results,
        "report_path": str(out_path),
        "n_distinct_actors": len(actor_ids_in_filter),
    }


def _write_report(
    path: Path,
    *,
    start: date, end: date,
    top_n: int, slippage_bps: float,
    min_prior_trades: int, lookback_days: int,
    n_total_trades: int, n_with_event_returns: int,
    n_with_skill: int, n_filtered: int, n_distinct_actors: int,
    actor_name_lookup: dict[str, str],
    skill_lookup: dict,
    filtered_trades: list[Trade],
    results: list[HorizonResult],
    verdict: str,
    primary: HorizonResult,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Phase 0 v2 — actor-skill-weighted validation\n")
    lines.append(f"- Window: **{start} → {end}**")
    lines.append(f"- Top-N filtered: **{top_n}**")
    lines.append(f"- Slippage assumption: **{slippage_bps} bps** round-trip")
    lines.append(f"- Actor-skill lookback: **{lookback_days} days**")
    lines.append(f"- Minimum prior trades per actor: **{min_prior_trades}**\n")

    lines.append("## Sample sizes\n")
    lines.append(f"- Total Quiver trades: **{n_total_trades:,}**")
    lines.append(f"- Trades with usable price-window event returns: **{n_with_event_returns:,}**")
    lines.append(f"- Trades with sufficient actor history to score: **{n_with_skill:,}**")
    lines.append(f"- Filtered top-N: **{n_filtered}** drawn from **{n_distinct_actors}** distinct actors\n")

    lines.append("## Horizon results\n")
    lines.append("| Days | n filt | n base | CAR filt | CAR base | **Δ** | 95% CI on Δ | Hit (F) | Hit (B) |")
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

    lines.append("## Top-N actors represented (and their skill scores at pick time)\n")
    lines.append("| Member | Trades in top-N | Avg skill score | Best skill |")
    lines.append("|---|---:|---:|---:|")
    by_actor: dict[str, list[float]] = {}
    for t in filtered_trades:
        s = skill_lookup.get(t.trade_id)
        if s is None:
            continue
        by_actor.setdefault(t.actor_id, []).append(s.skill)
    rows = sorted(by_actor.items(), key=lambda kv: -max(kv[1]))
    for actor_id, skills in rows[:30]:
        name = actor_name_lookup.get(actor_id, actor_id)
        avg = sum(skills) / len(skills)
        best = max(skills)
        lines.append(f"| {name} | {len(skills)} | {avg:.3f} | {best:.3f} |")
    lines.append("")

    lines.append("## Decision gate\n")
    lines.append(
        f"Primary horizon: **{PRIMARY_HORIZON_DAYS} days**. Threshold: "
        f"filter must beat baseline by **≥{ALPHA_THRESHOLD * 100:.0f}%** "
        "mean CAR with the 95% bootstrap CI of the delta not crossing zero.\n"
    )
    lines.append(f"- Observed delta: **{_fmt_pct(primary.delta_car)}**")
    lines.append(
        f"- Delta 95% CI: [{_fmt_pct(primary.delta_ci_lower)}, "
        f"{_fmt_pct(primary.delta_ci_upper)}]\n"
    )
    lines.append(f"## Verdict: **{verdict}**\n")
    if verdict == "PROCEED":
        lines.append(
            "The actor-skill-weighted filter clears the decision gate. The "
            "core hypothesis — that individual member historical performance "
            "is the dominant signal — is validated. Next: productionise (top-N "
            "picks daily, push alerts on new high-skill-actor trades, watchlist "
            "of currently-high-skill members).\n"
        )
    else:
        lines.append(
            "The actor-skill filter does not clear the decision gate. Possible "
            "diagnoses: yfinance data hole biasing the per-actor stats; "
            "instability of the top-actor list across time windows; sample-size "
            "issues with shorter member careers. Compare to the original Phase 0 "
            "for context before further iteration.\n"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
