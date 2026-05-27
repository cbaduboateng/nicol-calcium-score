"""Actor-skill scoring: walk-forward per-actor historical performance.

The Phase 0 diagnostic showed that individual member skill is the strongest
signal in the data — Sara Jacobs hits 96%, John Larson hits 10%, across
hundreds of trades each. The existing `actor_quality` module weights
*committee relevance* and *concentration* heavily; this module replaces
the historical-alpha placeholder with a proper realised-CAR computation,
without any lookahead.

For each trade T by actor A at date D, the actor-skill score is:

  mean(CAR_net_of_slippage of A's prior trades whose exit_date < D
       and transaction_date in [D - lookback_days, D - holding_period])

In other words: 'as of date D, how well has this actor done on trades they
made between 12 months ago and 90 days ago, where the holding period has
already elapsed?' That's the strict no-lookahead version.

Logistic-mapped to [0, 1]:
  - mean CAR  0.00  ->  0.50
  - mean CAR +5%   ->  ~0.73
  - mean CAR -5%   ->  ~0.27
  - mean CAR +10%  ->  ~0.88
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from pydantic import BaseModel, Field

from ..backtest.engine import EventReturn
from ..schema import Trade


class ActorSkillScore(BaseModel):
    """Per-trade actor-skill score with the inputs that built it."""

    trade_id: str
    actor_id: str
    n_prior_trades: int
    mean_prior_car: float
    hit_rate: float
    skill: float = Field(..., ge=0, le=1)


def _logistic(x: float, steepness: float = 20.0) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-steepness * x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def compute_actor_skill(
    trades: list[Trade],
    event_returns: list[EventReturn],
    *,
    lookback_days: int = 365,
    holding_period_days: int = 90,
    min_prior_trades: int = 10,
) -> dict[str, ActorSkillScore]:
    """Return `{trade_id -> ActorSkillScore}` for every trade.

    Walk-forward: a trade at date D scores only on prior trades the actor
    made in `[D - lookback_days, D - holding_period_days]`. Actors with
    fewer than `min_prior_trades` realised priors get a neutral 0.5.

    The function is pure: no I/O, no globals.
    """
    er_by_trade = {e.trade_id: e for e in event_returns}

    by_actor: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_actor[t.actor_id].append(t)
    for actor_id, ts in by_actor.items():
        ts.sort(key=lambda t: t.transaction_date)

    out: dict[str, ActorSkillScore] = {}
    for actor_id, actor_trades in by_actor.items():
        for i, current in enumerate(actor_trades):
            cutoff_recent = current.transaction_date - timedelta(days=holding_period_days)
            cutoff_far = current.transaction_date - timedelta(days=lookback_days)

            prior_cars: list[float] = []
            for prior in actor_trades[:i]:
                if prior.transaction_date < cutoff_far:
                    continue
                if prior.transaction_date > cutoff_recent:
                    continue
                er = er_by_trade.get(prior.trade_id)
                if er is None:
                    continue
                prior_cars.append(float(er.car_net_of_slippage))

            n = len(prior_cars)
            if n < min_prior_trades:
                out[current.trade_id] = ActorSkillScore(
                    trade_id=current.trade_id,
                    actor_id=actor_id,
                    n_prior_trades=n,
                    mean_prior_car=0.0,
                    hit_rate=0.0,
                    skill=0.5,
                )
                continue

            mean_car = sum(prior_cars) / n
            hits = sum(1 for c in prior_cars if c > 0) / n
            # 70/30 blend of mean-CAR (logistic) and hit rate.
            blended = 0.7 * _logistic(mean_car) + 0.3 * hits
            out[current.trade_id] = ActorSkillScore(
                trade_id=current.trade_id,
                actor_id=actor_id,
                n_prior_trades=n,
                mean_prior_car=mean_car,
                hit_rate=hits,
                skill=min(1.0, max(0.0, blended)),
            )
    return out


def rank_trades_by_actor_skill(
    skill_scores: dict[str, ActorSkillScore],
    *,
    top_n: int = 50,
    min_skill: float | None = None,
) -> list[str]:
    """Return trade_ids sorted by skill score (descending). Optionally
    filter to skill >= `min_skill` before truncating to top_n."""
    items = list(skill_scores.values())
    if min_skill is not None:
        items = [s for s in items if s.skill >= min_skill]
    items.sort(key=lambda s: -s.skill)
    return [s.trade_id for s in items[:top_n]]
