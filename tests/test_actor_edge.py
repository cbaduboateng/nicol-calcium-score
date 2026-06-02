"""Tests for actor_edge: per-member YTD realised-return scoring."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from icarus.actor_edge import (
    compute_actor_edge,
    compute_trade_returns,
)


AS_OF = date(2026, 6, 1)


def _prices() -> pd.DataFrame:
    # ~8-month daily series for two tickers; starts before the prior-year
    # trade so the ytd_only=False path has data to resolve.
    idx = pd.date_range("2025-10-01", "2026-06-01", freq="D")
    return pd.DataFrame({
        "LMT": [400.0 + i * 0.5 for i in range(len(idx))],   # steadily up
        "BMY": [60.0 - i * 0.1 for i in range(len(idx))],    # steadily down
    }, index=idx)


def _trades() -> pd.DataFrame:
    return pd.DataFrame([
        {"trade_id": "t1", "actor_id": "A1", "ticker": "LMT",
         "transaction_date": date(2026, 1, 15), "direction": "buy",
         "amount_midpoint_usd": 50_000.0},
        {"trade_id": "t2", "actor_id": "A1", "ticker": "BMY",
         "transaction_date": date(2026, 2, 10), "direction": "buy",
         "amount_midpoint_usd": 25_000.0},
        {"trade_id": "t3", "actor_id": "A2", "ticker": "LMT",
         "transaction_date": date(2026, 3, 1), "direction": "buy",
         "amount_midpoint_usd": 100_000.0},
        # Prior-year trade: dropped when ytd_only=True
        {"trade_id": "t4", "actor_id": "A2", "ticker": "BMY",
         "transaction_date": date(2025, 11, 1), "direction": "buy",
         "amount_midpoint_usd": 10_000.0},
        # Sell: dropped by direction_filter='buy'
        {"trade_id": "t5", "actor_id": "A1", "ticker": "LMT",
         "transaction_date": date(2026, 4, 1), "direction": "sell",
         "amount_midpoint_usd": 50_000.0},
    ])


# ---- compute_trade_returns ----------------------------------------------


def test_trade_returns_basic_winner_and_loser():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF)
    assert {"t1", "t2", "t3"}.issubset(set(tr["trade_id"]))
    # LMT rises -> positive return; BMY falls -> negative return
    lmt = tr[tr["trade_id"] == "t1"].iloc[0]
    bmy = tr[tr["trade_id"] == "t2"].iloc[0]
    assert lmt["return_pct"] > 0
    assert bool(lmt["winner"]) is True
    assert bmy["return_pct"] < 0
    assert bool(bmy["winner"]) is False


def test_trade_returns_excludes_prior_year_when_ytd():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF, ytd_only=True)
    assert "t4" not in set(tr["trade_id"])


def test_trade_returns_includes_prior_year_when_ytd_off():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF, ytd_only=False)
    assert "t4" in set(tr["trade_id"])


def test_trade_returns_filters_to_buys_by_default():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF)
    assert "t5" not in set(tr["trade_id"])


def test_trade_returns_includes_sells_when_filter_disabled():
    tr = compute_trade_returns(
        _trades(), _prices(), as_of=AS_OF, direction_filter=None,
    )
    assert "t5" in set(tr["trade_id"])


def test_trade_returns_skips_missing_ticker():
    trades = _trades().copy()
    trades.loc[len(trades)] = {
        "trade_id": "tX", "actor_id": "A3", "ticker": "UNKNOWN",
        "transaction_date": date(2026, 2, 1), "direction": "buy",
        "amount_midpoint_usd": 10_000.0,
    }
    tr = compute_trade_returns(trades, _prices(), as_of=AS_OF)
    assert "tX" not in set(tr["trade_id"])


def test_trade_returns_weekend_uses_asof_match():
    # 2026-01-17 is a Saturday — pretend a trade was filed on that date.
    trades = pd.DataFrame([{
        "trade_id": "tw", "actor_id": "A1", "ticker": "LMT",
        "transaction_date": date(2026, 1, 17), "direction": "buy",
        "amount_midpoint_usd": 1000,
    }])
    tr = compute_trade_returns(trades, _prices(), as_of=AS_OF)
    # Falls back to the prior trading day's close (2026-01-16 in our daily index)
    assert len(tr) == 1
    assert tr.iloc[0]["entry_price"] > 0


def test_trade_returns_empty_inputs_return_empty():
    assert compute_trade_returns(pd.DataFrame(), _prices()).empty
    assert compute_trade_returns(_trades(), pd.DataFrame()).empty


# ---- compute_actor_edge --------------------------------------------------


def test_actor_edge_counts_wins_and_losses():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF)
    edge = compute_actor_edge(tr)
    a1 = edge[edge["actor_id"] == "A1"].iloc[0]
    # A1 made 2 YTD buys: LMT win, BMY loss
    assert a1["n_trades"] == 2
    assert a1["n_winners"] == 1
    assert a1["n_losers"] == 1
    assert a1["hit_rate"] == pytest.approx(0.5)


def test_actor_edge_sorted_by_mean_return_descending():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF)
    edge = compute_actor_edge(tr)
    means = edge["mean_return_pct"].tolist()
    assert means == sorted(means, reverse=True)


def test_actor_edge_cumulative_equals_sum_of_trade_returns():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF)
    edge = compute_actor_edge(tr)
    a1_cum = edge[edge["actor_id"] == "A1"].iloc[0]["cumulative_return_pct"]
    a1_sum = tr[tr["actor_id"] == "A1"]["return_pct"].sum()
    assert a1_cum == pytest.approx(a1_sum)


def test_actor_edge_min_trades_filters_one_hit_wonders():
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF)
    edge = compute_actor_edge(tr, min_trades=2)
    # A2 has only 1 YTD trade, should be dropped
    assert "A2" not in set(edge["actor_id"])
    assert "A1" in set(edge["actor_id"])


def test_actor_edge_merges_actor_metadata():
    actors = pd.DataFrame([
        {"actor_id": "A1", "name": "Alice Alpha", "party": "D", "state": "CA",
         "chamber": "house"},
        {"actor_id": "A2", "name": "Bob Beta", "party": "R", "state": "TX",
         "chamber": "senate"},
    ])
    tr = compute_trade_returns(_trades(), _prices(), as_of=AS_OF)
    edge = compute_actor_edge(tr, actors=actors)
    assert "name" in edge.columns
    assert "Alice Alpha" in set(edge["name"])


def test_actor_edge_empty_returns_empty():
    assert compute_actor_edge(pd.DataFrame()).empty
