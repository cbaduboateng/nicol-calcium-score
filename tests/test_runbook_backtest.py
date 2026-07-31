"""Tests for the £5k runbook backtest simulator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.runbook_backtest import RunbookParams, simulate_runbook


def _series(prices: list[float], start: str = "2025-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(prices), freq="D")
    return pd.Series(prices, index=idx)


def _rise_dip(entry_dip: float, tail: list[float]) -> pd.Series:
    """70 days rising 8→12 (positive 3m momentum), then dip into the buy
    zone at ``entry_dip``, then the caller-supplied tail."""
    ramp = list(np.linspace(8.0, 12.0, 70))
    return _series(ramp + [entry_dip] + tail)


def _watchlist(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


WIN_ROW = {"ticker": "WIN", "name": "Winner", "description": "AI play",
           "target_entry": 10.0, "target_exit": 20.0}


def test_winning_trade_hits_target_and_grows_equity():
    tail = list(np.linspace(10.5, 21.0, 30))  # rally through the target
    hist = {"WIN": _rise_dip(9.9, tail)}
    res = simulate_runbook(_watchlist([WIN_ROW]), hist)
    trades = res["trades"]
    assert len(trades) == 1
    t = trades.iloc[0]
    assert t["reason"] == "target"
    assert t["return_pct"] > 0
    assert res["stats"]["final_equity"] > res["stats"]["start_capital"]
    assert res["stats"]["win_rate"] == 1.0


def test_winner_pyramids_on_the_way_up():
    tail = list(np.linspace(10.5, 21.0, 30))
    hist = {"WIN": _rise_dip(9.9, tail)}
    res = simulate_runbook(_watchlist([WIN_ROW]), hist)
    assert bool(res["trades"].iloc[0]["pyramided"]) is True


def test_losing_trade_stops_out_near_stop_pct():
    tail = list(np.linspace(9.5, 8.2, 15))  # slide through the -12% stop
    hist = {"LOSE": _rise_dip(9.9, tail)}
    row = dict(WIN_ROW, ticker="LOSE")
    res = simulate_runbook(_watchlist([row]), hist)
    t = res["trades"].iloc[0]
    assert t["reason"] == "stop"
    # Close-based stop: loss should be near -12%, never catastrophic
    assert -16.0 < t["return_pct"] < -10.0
    assert res["stats"]["final_equity"] < res["stats"]["start_capital"]


def test_momentum_gate_blocks_falling_knife():
    # Declining the whole way: crossing happens but 3m momentum is negative.
    prices = list(np.linspace(15.0, 9.9, 80))
    hist = {"KNIFE": _series(prices)}
    row = dict(WIN_ROW, ticker="KNIFE")
    res = simulate_runbook(_watchlist([row]), hist)
    assert res["trades"].empty
    assert res["stats"]["final_equity"] == res["stats"]["start_capital"]


def test_rr_gate_blocks_thin_upside():
    tail = list(np.linspace(10.5, 21.0, 30))
    hist = {"THIN": _rise_dip(9.9, tail)}
    # Exit barely above entry: rr = (10.5-9.9)/(9.9*0.12) ≈ 0.5 < 3
    row = dict(WIN_ROW, ticker="THIN", target_exit=10.5)
    res = simulate_runbook(_watchlist([row]), hist)
    assert res["trades"].empty


def test_max_two_concurrent_positions():
    tail = list(np.linspace(10.5, 21.0, 30))
    hist = {t: _rise_dip(9.9, tail) for t in ("AAA", "BBB", "CCC")}
    rows = [dict(WIN_ROW, ticker=t) for t in ("AAA", "BBB", "CCC")]
    res = simulate_runbook(_watchlist(rows), hist)
    # All three signal on the same day; only two slots exist.
    assert res["trades"]["ticker"].nunique() <= 2


def test_cap_gate_excludes_big_and_unknown_caps():
    tail = list(np.linspace(10.5, 21.0, 30))
    hist = {"BIG": _rise_dip(9.9, tail), "UNK": _rise_dip(9.9, tail)}
    rows = [dict(WIN_ROW, ticker="BIG"), dict(WIN_ROW, ticker="UNK")]
    res = simulate_runbook(
        _watchlist(rows), hist,
        RunbookParams(max_market_cap_usd=300_000_000.0, require_known_cap=True),
        market_caps={"BIG": 500_000_000.0},  # UNK has no cap entry
    )
    assert res["trades"].empty
    # Same setup but caps below the ceiling → trades happen
    res2 = simulate_runbook(
        _watchlist(rows), hist,
        RunbookParams(max_market_cap_usd=300_000_000.0, require_known_cap=True),
        market_caps={"BIG": 50_000_000.0, "UNK": 80_000_000.0},
    )
    assert not res2["trades"].empty


def test_open_position_marks_to_market():
    # Enters then drifts inside the band — still open at the end.
    tail = [10.2] * 20
    hist = {"OPEN": _rise_dip(9.9, tail)}
    row = dict(WIN_ROW, ticker="OPEN")
    res = simulate_runbook(_watchlist([row]), hist)
    t = res["trades"].iloc[0]
    assert t["reason"] == "open"
    assert res["stats"]["n_open"] == 1
    assert res["stats"]["n_closed"] == 0


def test_equity_curve_final_matches_stats():
    tail = list(np.linspace(10.5, 21.0, 30))
    hist = {"WIN": _rise_dip(9.9, tail)}
    res = simulate_runbook(_watchlist([WIN_ROW]), hist)
    eq = res["equity"]
    assert not eq.empty
    assert eq["equity"].iloc[-1] == pytest.approx(res["stats"]["final_equity"])
    # Position sizing: first entry risks half the account, stop is 12%,
    # so max drawdown should stay modest in a winning path.
    assert res["stats"]["max_drawdown_pct"] > -20.0


def test_empty_inputs_return_neutral_stats():
    res = simulate_runbook(pd.DataFrame(), {})
    assert res["trades"].empty
    assert res["stats"]["final_equity"] == res["stats"]["start_capital"]
    res2 = simulate_runbook(_watchlist([WIN_ROW]), {})
    assert res2["trades"].empty
