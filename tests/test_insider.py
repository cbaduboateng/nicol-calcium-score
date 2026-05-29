"""Monotonicity tests for the insider-buying scoring layer."""

from __future__ import annotations

from datetime import date, timedelta

from icarus.scoring.insider import (
    InsiderTransaction,
    score_insider_buying,
)


AS_OF = date(2024, 6, 1)


def _tx(name: str, role: str, direction: str, value: float, days_ago: int = 30) -> InsiderTransaction:
    return InsiderTransaction(
        ticker="ACME",
        insider_name=name,
        insider_role=role,
        transaction_date=AS_OF - timedelta(days=days_ago),
        direction=direction,  # type: ignore[arg-type]
        is_open_market=True,
        shares=value / 100,
        price=100,
        value_usd=value,
    )


def test_no_transactions_yields_zero_composite():
    score = score_insider_buying([], ticker="ACME", as_of=AS_OF)
    assert score.composite == 0.0


def test_more_distinct_buyers_raises_cluster_score():
    one_buyer = [_tx("Alice", "Director", "buy", 100_000)]
    five_buyers = [
        _tx(name, "Director", "buy", 100_000)
        for name in ("Alice", "Bob", "Carol", "Dan", "Eve")
    ]
    low = score_insider_buying(one_buyer, ticker="ACME", as_of=AS_OF)
    high = score_insider_buying(five_buyers, ticker="ACME", as_of=AS_OF)
    assert high.cluster_score > low.cluster_score
    assert high.composite > low.composite


def test_senior_roles_raise_composite():
    juniors = [
        _tx("Alice", "Director", "buy", 100_000),
        _tx("Bob",   "Director", "buy", 100_000),
    ]
    seniors = [
        _tx("Alice", "CEO", "buy", 100_000),
        _tx("Bob",   "CFO", "buy", 100_000),
    ]
    low = score_insider_buying(juniors, ticker="ACME", as_of=AS_OF)
    high = score_insider_buying(seniors, ticker="ACME", as_of=AS_OF)
    assert high.senior_share > low.senior_share
    assert high.composite > low.composite


def test_sells_reduce_net_buy_ratio():
    pure_buys = [_tx("Alice", "CEO", "buy", 100_000)]
    mixed = [
        _tx("Alice", "CEO", "buy", 100_000),
        _tx("Bob",   "Director", "sell", 500_000),
    ]
    high = score_insider_buying(pure_buys, ticker="ACME", as_of=AS_OF)
    low = score_insider_buying(mixed, ticker="ACME", as_of=AS_OF)
    assert high.net_buy_ratio > low.net_buy_ratio


def test_transactions_outside_window_are_ignored():
    far = [_tx("Alice", "CEO", "buy", 100_000, days_ago=200)]
    near = [_tx("Alice", "CEO", "buy", 100_000, days_ago=30)]
    assert score_insider_buying(far, ticker="ACME", as_of=AS_OF, window_days=90).composite == 0.0
    assert score_insider_buying(near, ticker="ACME", as_of=AS_OF, window_days=90).composite > 0.0


def test_tiny_trades_below_minimum_ignored():
    trivial = [_tx("Alice", "CEO", "buy", 5_000)]
    score = score_insider_buying(
        trivial, ticker="ACME", as_of=AS_OF, minimum_open_market_value=50_000,
    )
    assert score.composite == 0.0
