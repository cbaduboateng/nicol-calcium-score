"""Tests for the SEC Form 4 insider-buying overlay."""

from __future__ import annotations

from datetime import date, timedelta

from icarus.insider_overlay import build_insider_overlay
from icarus.scoring.insider import InsiderTransaction

AS_OF = date(2026, 8, 1)


def _tx(ticker: str, name: str, role: str, direction: str, value: float,
        days_ago: int = 15) -> InsiderTransaction:
    return InsiderTransaction(
        ticker=ticker,
        insider_name=name,
        insider_role=role,
        transaction_date=AS_OF - timedelta(days=days_ago),
        direction=direction,  # type: ignore[arg-type]
        is_open_market=True,
        shares=value / 10,
        price=10,
        value_usd=value,
    )


def test_clustered_senior_buying_scores_and_summarises():
    txns = [
        _tx("ACME", "Alice", "CEO", "buy", 200_000, days_ago=10),
        _tx("ACME", "Bob", "CFO", "buy", 150_000, days_ago=20),
        _tx("ACME", "Carol", "Director", "buy", 100_000, days_ago=30),
    ]
    overlay = build_insider_overlay(txns, as_of=AS_OF)
    assert "ACME" in overlay
    e = overlay["ACME"]
    assert e["score"] > 0
    assert e["n_buyers"] == 3
    assert e["n_senior"] == 2
    assert e["total_bought_usd"] == 450_000
    assert e["last_buy_days"] == 10
    assert "3 insiders bought $450,000" in e["summary"]
    assert "2 C-suite" in e["summary"]


def test_tickers_with_no_buying_are_omitted():
    txns = [_tx("SELL", "Dan", "CEO", "sell", 500_000)]
    overlay = build_insider_overlay(txns, as_of=AS_OF)
    assert "SELL" not in overlay


def test_universe_filter_restricts_output():
    txns = [
        _tx("AAA", "Alice", "CEO", "buy", 200_000),
        _tx("BBB", "Bob", "CEO", "buy", 200_000),
    ]
    overlay = build_insider_overlay(txns, as_of=AS_OF, tickers=["AAA"])
    assert set(overlay) == {"AAA"}


def test_stale_transactions_outside_window_ignored():
    txns = [_tx("OLD", "Alice", "CEO", "buy", 200_000, days_ago=200)]
    overlay = build_insider_overlay(txns, as_of=AS_OF, window_days=90)
    assert "OLD" not in overlay


def test_empty_input_gives_empty_overlay():
    assert build_insider_overlay([], as_of=AS_OF) == {}
