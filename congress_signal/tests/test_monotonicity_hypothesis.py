"""Hypothesis-driven monotonicity tests.

The scoring spec says: "validate that scores are monotonic in the obvious
dimensions". These tests sample plausible inputs and assert the dimension
holds across the sampled space.

Skipped silently if `hypothesis` is not installed.
"""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from datetime import date, timedelta  # noqa: E402

from congress_signal.schema import (  # noqa: E402
    Actor,
    AssetType,
    Chamber,
    Direction,
    Owner,
    Trade,
)
from congress_signal.scoring.actor_quality import score_actors


def _trade(actor_id: str, ticker: str, amount: float, days_ago: int = 30) -> Trade:
    txn = date(2024, 6, 1) - timedelta(days=days_ago)
    return Trade(
        trade_id=f"t-{actor_id}-{ticker}-{txn}-{amount}",
        actor_id=actor_id,
        transaction_date=txn,
        disclosure_date=txn + timedelta(days=20),
        ticker=ticker,
        asset_type=AssetType.STOCK,
        direction=Direction.BUY,
        amount_min_usd=max(0.0, amount * 0.9),
        amount_max_usd=max(0.0, amount * 1.1),
        owner=Owner.SELF,
        source="test",
    )


@settings(max_examples=30, deadline=None)
@given(
    small=st.floats(min_value=1_000.0, max_value=50_000.0),
    large=st.floats(min_value=200_000.0, max_value=5_000_000.0),
    net_worth=st.floats(min_value=1_000_000.0, max_value=50_000_000.0),
)
def test_skin_in_game_monotone_in_amount(small: float, large: float, net_worth: float):
    actor = Actor(
        actor_id="A", name="A", chamber=Chamber.HOUSE,
        net_worth_estimate_usd=net_worth,
    )
    [low] = score_actors([actor], [_trade("A", "LMT", small)])
    [high] = score_actors([actor], [_trade("A", "LMT", large)])
    assert high.skin_in_game >= low.skin_in_game


@settings(max_examples=30, deadline=None)
@given(
    spread_tickers=st.lists(
        st.sampled_from(["LMT", "RTX", "NOC", "GD", "HII", "AVAV", "MRCY"]),
        min_size=3, max_size=7, unique=True,
    ),
    amount=st.floats(min_value=50_000.0, max_value=250_000.0),
)
def test_concentration_monotone_when_spread_collapses(
    spread_tickers: list[str], amount: float,
):
    actor = Actor(actor_id="A", name="A", chamber=Chamber.HOUSE)
    spread = [_trade("A", t, amount) for t in spread_tickers]
    focused = [_trade("A", "LMT", amount * len(spread_tickers))]
    [spread_score] = score_actors([actor], spread)
    [focused_score] = score_actors([actor], focused)
    assert focused_score.concentration_score >= spread_score.concentration_score
