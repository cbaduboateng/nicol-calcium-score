"""Monotonicity tests for actor-quality scoring.

The spec calls out monotonicity as the key correctness property: more of an
input should never *decrease* its corresponding component (modulo other
inputs held fixed).
"""

from __future__ import annotations

from datetime import date, timedelta

from congress_signal.schema import Actor, AssetType, Chamber, Direction, Owner, Trade
from congress_signal.scoring.actor_quality import score_actors


def _trade(actor_id: str, ticker: str, amount: float, days_ago: int = 30) -> Trade:
    txn = date.today() - timedelta(days=days_ago)
    return Trade(
        trade_id=f"t-{actor_id}-{ticker}-{txn}",
        actor_id=actor_id,
        transaction_date=txn,
        disclosure_date=txn + timedelta(days=20),
        ticker=ticker,
        asset_type=AssetType.STOCK,
        direction=Direction.BUY,
        amount_min_usd=amount * 0.9,
        amount_max_usd=amount * 1.1,
        owner=Owner.SELF,
        source="test",
    )


def test_more_committee_overlap_raises_committee_relevance():
    base = Actor(actor_id="A", name="A", chamber=Chamber.HOUSE, committees=())
    with_committee = Actor(
        actor_id="B", name="B", chamber=Chamber.HOUSE,
        committees=("House Armed Services",),
    )
    trades = [_trade("A", "LMT", 100_000.0), _trade("B", "LMT", 100_000.0)]
    scores = {s.actor_id: s for s in score_actors([base, with_committee], trades)}
    assert scores["B"].committee_relevance > scores["A"].committee_relevance


def test_more_skin_in_game_raises_skin_score():
    actor = Actor(
        actor_id="A", name="A", chamber=Chamber.HOUSE,
        net_worth_estimate_usd=10_000_000.0,
    )
    small = [_trade("A", "LMT", 10_000.0)]
    large = [_trade("A", "LMT", 1_000_000.0)]
    [small_score] = score_actors([actor], small)
    [large_score] = score_actors([actor], large)
    assert large_score.skin_in_game > small_score.skin_in_game


def test_more_concentration_raises_concentration_score():
    actor = Actor(actor_id="A", name="A", chamber=Chamber.HOUSE)
    spread = [_trade("A", t, 50_000.0) for t in ("LMT", "RTX", "NOC", "GD", "HII")]
    focused = [_trade("A", "LMT", 250_000.0)]
    [spread_score] = score_actors([actor], spread)
    [focused_score] = score_actors([actor], focused)
    assert focused_score.concentration_score > spread_score.concentration_score


def test_composite_in_unit_interval():
    actors = [
        Actor(actor_id="A", name="A", chamber=Chamber.HOUSE,
              committees=("House Armed Services",),
              net_worth_estimate_usd=2_000_000.0),
    ]
    trades = [_trade("A", "LMT", 1_500_000.0, days_ago=10)]
    [s] = score_actors(actors, trades)
    assert 0.0 <= s.composite <= 1.0
