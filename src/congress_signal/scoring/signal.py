"""Per-trade signal-richness scoring.

A trade is "signal-rich" when one or more of the following holds:
- It is an option (especially OTM, long-dated).
- The amount is large relative to the actor's own history.
- It was disclosed unusually quickly.
- The ticker overlaps with the actor's committee jurisdiction.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from ..schema import Actor, AssetType, Direction, Trade, TradeSignal
from .actor import COMMITTEE_TICKER_HINTS


def _committee_overlap(actor: Actor, ticker: str) -> bool:
    if not actor.committees:
        return False
    for committee in actor.committees:
        key = committee.lower()
        for fragment, tickers in COMMITTEE_TICKER_HINTS.items():
            if fragment in key and ticker.upper() in tickers:
                return True
    return False


def score_trades(
    trades: list[Trade],
    actors: list[Actor],
    *,
    weights: dict[str, float] | None = None,
    size_z_threshold: float = 1.0,
    fast_disclosure_days: int = 14,
) -> list[TradeSignal]:
    weights = weights or {
        "options": 0.4,
        "size": 0.3,
        "speed": 0.2,
        "committee_overlap": 0.1,
    }
    actor_by_id: dict[str, Actor] = {a.actor_id: a for a in actors}
    by_actor: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by_actor[t.actor_id].append(t.amount_midpoint_usd)

    actor_stats: dict[str, tuple[float, float]] = {}
    for actor_id, amounts in by_actor.items():
        if len(amounts) >= 2:
            mu = statistics.mean(amounts)
            sigma = statistics.pstdev(amounts) or 1.0
        else:
            mu, sigma = (amounts[0] if amounts else 0.0), 1.0
        actor_stats[actor_id] = (mu, sigma)

    signals: list[TradeSignal] = []
    for t in trades:
        types: list[str] = []
        score = 0.0

        if t.is_option:
            types.append("option")
            score += weights["options"]
            if t.asset_type == AssetType.CALL and t.direction == Direction.BUY:
                if t.days_to_expiry and t.days_to_expiry >= 180:
                    types.append("long-dated call")
                    score += 0.2

        mu, sigma = actor_stats.get(t.actor_id, (0.0, 1.0))
        z = (t.amount_midpoint_usd - mu) / sigma if sigma > 0 else 0.0
        if z >= size_z_threshold:
            types.append(f"large vs personal history (z={z:.1f})")
            score += weights["size"]

        if t.disclosure_lag_days <= fast_disclosure_days:
            types.append("fast disclosure")
            score += weights["speed"]

        actor = actor_by_id.get(t.actor_id)
        if actor and _committee_overlap(actor, t.ticker):
            types.append("committee jurisdiction")
            score += weights["committee_overlap"]

        signals.append(TradeSignal(
            trade_id=t.trade_id,
            is_signal_rich=score >= 0.5,
            signal_types=tuple(types),
            raw_score=float(min(score, 1.5)),
            rationale="; ".join(types) if types else "no signal triggers",
        ))
    return signals
