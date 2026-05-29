from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from icarus.schema import (
    ActorScore,
    AssetType,
    Direction,
    Owner,
    Trade,
)
from icarus.scoring.clustering import find_clusters


def _trade(actor_id: str, ticker: str, days_offset: int) -> Trade:
    txn = date(2024, 6, 1) + timedelta(days=days_offset)
    return Trade(
        trade_id=f"{actor_id}-{ticker}-{days_offset}",
        actor_id=actor_id,
        transaction_date=txn,
        disclosure_date=txn + timedelta(days=10),
        ticker=ticker, asset_type=AssetType.STOCK, direction=Direction.BUY,
        amount_min_usd=50_000.0, amount_max_usd=100_000.0,
        owner=Owner.SELF, source="test",
    )


def _score(actor_id: str, composite: float) -> ActorScore:
    return ActorScore(
        actor_id=actor_id,
        as_of=datetime.now(timezone.utc),
        committee_relevance=0.5,
        historical_alpha_bps=0.0,
        historical_alpha_normalised=0.5,
        concentration_score=0.5,
        skin_in_game=0.5,
        composite=composite,
        trades_observed=1,
    )


def test_three_actors_in_window_form_a_cluster():
    trades = [
        _trade("A", "LMT", 0),
        _trade("B", "LMT", 3),
        _trade("C", "LMT", 7),
    ]
    scores = [_score("A", 0.6), _score("B", 0.6), _score("C", 0.6)]
    clusters = find_clusters(trades, scores, window_days=14, min_actors=3,
                             min_combined_quality=1.5)
    assert len(clusters) == 1
    assert clusters[0].ticker == "LMT"
    assert set(clusters[0].actor_ids) == {"A", "B", "C"}


def test_low_quality_actors_do_not_form_cluster():
    trades = [_trade("A", "LMT", 0), _trade("B", "LMT", 3)]
    scores = [_score("A", 0.1), _score("B", 0.1)]
    clusters = find_clusters(trades, scores, min_combined_quality=0.5)
    assert clusters == []


def test_wider_window_finds_more_actors():
    trades = [_trade("A", "RTX", 0), _trade("B", "RTX", 20)]
    scores = [_score("A", 0.6), _score("B", 0.6)]
    short = find_clusters(trades, scores, window_days=10, min_actors=2,
                          min_combined_quality=1.0)
    long_ = find_clusters(trades, scores, window_days=30, min_actors=2,
                          min_combined_quality=1.0)
    assert short == []
    assert len(long_) == 1
