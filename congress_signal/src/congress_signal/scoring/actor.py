"""Actor-quality scoring.

Composite = w_committee * committee_relevance
          + w_alpha     * historical_alpha_normalised
          + w_conc      * concentration_score
          + w_skin      * skin_in_game

Committee relevance is a tiny rules table keyed on committee name fragments
mapped to a coarse sector. The default table is intentionally minimal and
biased toward defence / tech / energy, which is where this style of signal
historically pays off; extend it for production use.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from ..schema import Actor, ActorScore, Trade

COMMITTEE_TICKER_HINTS: dict[str, set[str]] = {
    "armed services": {"LMT", "RTX", "NOC", "GD", "HII", "LDOS", "BAH", "CACI", "SAIC",
                       "AXON", "PLTR", "KTOS", "AVAV", "MRCY", "TXT", "TDY"},
    "intelligence":   {"PLTR", "BAH", "CACI", "SAIC", "LDOS"},
    "energy":         {"XOM", "CVX", "COP", "EOG", "OXY", "NEE", "DUK", "SO", "AEP"},
    "science":        {"NVDA", "AMD", "MSFT", "GOOGL", "META", "PLTR"},
    "banking":        {"JPM", "BAC", "C", "WFC", "GS", "MS"},
    "transportation": {"BA", "GE", "RTX", "TXT", "TDY"},
}


def _committee_relevance(actor: Actor, traded_tickers: set[str]) -> float:
    if not actor.committees or not traded_tickers:
        return 0.0
    relevant = 0
    for committee in actor.committees:
        key = committee.lower()
        for fragment, tickers in COMMITTEE_TICKER_HINTS.items():
            if fragment in key and traded_tickers & tickers:
                relevant += 1
                break
    return min(1.0, relevant / max(1, len(actor.committees)))


def _historical_alpha_bps(trades_for_actor: list[Trade]) -> float:
    """Stand-in alpha: a deterministic, bounded score derived from disclosure
    speed and option usage. Production should compute realised CAR vs SPY.
    """
    if not trades_for_actor:
        return 0.0
    fast = sum(1 for t in trades_for_actor if t.disclosure_lag_days <= 30)
    options = sum(1 for t in trades_for_actor if t.is_option)
    score = 50 * (fast / len(trades_for_actor)) + 200 * (options / len(trades_for_actor))
    return float(min(score, 500.0))


def _normalise_bps(values: list[float]) -> list[float]:
    if not values:
        return []
    arr = np.array(values, dtype=float)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return ((arr - lo) / (hi - lo)).tolist()


def _concentration(trades_for_actor: list[Trade]) -> float:
    """Herfindahl-style concentration in [0, 1]; 1 = single ticker, 0 = spread."""
    if not trades_for_actor:
        return 0.0
    by_ticker: dict[str, float] = defaultdict(float)
    for t in trades_for_actor:
        by_ticker[t.ticker] += t.amount_midpoint_usd
    total = sum(by_ticker.values()) or 1.0
    shares = np.array([v / total for v in by_ticker.values()])
    hhi = float((shares ** 2).sum())
    return min(1.0, hhi)


def _skin_in_game(trades_for_actor: list[Trade], net_worth: float | None) -> float:
    if not trades_for_actor:
        return 0.0
    deployed = sum(t.amount_midpoint_usd for t in trades_for_actor)
    if not net_worth or net_worth <= 0:
        # Fall back to absolute scale: $250k deployed = 1.0.
        return float(min(1.0, deployed / 250_000.0))
    return float(min(1.0, deployed / net_worth))


def score_actors(
    actors: list[Actor],
    trades: list[Trade],
    *,
    weights: dict[str, float] | None = None,
    min_trades_for_alpha: int = 5,
) -> list[ActorScore]:
    weights = weights or {
        "committee_relevance": 0.30,
        "historical_alpha": 0.30,
        "concentration": 0.20,
        "skin_in_game": 0.20,
    }
    by_actor: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_actor[t.actor_id].append(t)

    raw_alpha = {a.actor_id: _historical_alpha_bps(by_actor[a.actor_id]) for a in actors}
    normalised = dict(zip(raw_alpha.keys(), _normalise_bps(list(raw_alpha.values()))))

    now = datetime.now(timezone.utc)
    scores: list[ActorScore] = []
    for actor in actors:
        actor_trades = by_actor[actor.actor_id]
        traded_tickers = {t.ticker for t in actor_trades}
        committee = _committee_relevance(actor, traded_tickers)
        alpha_norm = normalised.get(actor.actor_id, 0.0)
        if len(actor_trades) < min_trades_for_alpha:
            alpha_norm *= 0.5  # discount thin histories
        conc = _concentration(actor_trades)
        skin = _skin_in_game(actor_trades, actor.net_worth_estimate_usd)

        composite = (
            weights["committee_relevance"] * committee
            + weights["historical_alpha"]     * alpha_norm
            + weights["concentration"]        * conc
            + weights["skin_in_game"]         * skin
        )
        composite = float(min(1.0, max(0.0, composite)))

        scores.append(ActorScore(
            actor_id=actor.actor_id,
            as_of=now,
            committee_relevance=committee,
            historical_alpha_bps=raw_alpha[actor.actor_id],
            historical_alpha_normalised=alpha_norm,
            concentration_score=conc,
            skin_in_game=skin,
            composite=composite,
            trades_observed=len(actor_trades),
            rationale=(
                f"committee={committee:.2f} alpha={alpha_norm:.2f} "
                f"conc={conc:.2f} skin={skin:.2f}"
            ),
        ))
    return scores
