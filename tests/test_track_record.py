"""Tests for the forward-marked track record."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from icarus.track_record import (
    build_track_record,
    cumulative_pnl_series,
    detect_signals,
    summarise_track_record,
)


AS_OF = date(2026, 6, 1)


def _series(prices: list[float], start: str = "2025-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(prices), freq="D")
    return pd.Series(prices, index=idx)


# ---- detect_signals ------------------------------------------------------


def test_signal_fires_on_crossing_into_zone():
    # Start above entry (12), cross down to 9, then bounce to 15 — should hit target.
    prices = [12.0, 11.0, 9.0, 10.5, 12.0, 14.0, 15.0]
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=15.0,
        as_of=AS_OF, cooldown_days=0,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["entry_price"] == 9.0
    assert s["close_reason"] == "target"
    assert s["return_pct"] > 0


def test_stop_triggers_when_price_drops_below():
    # Cross down to 10, then fall to 8 (stop at 9 with 10% stop)
    prices = [12.0, 10.0, 9.5, 8.5, 8.0]
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=20.0,
        stop_pct=0.10, as_of=AS_OF, cooldown_days=0,
    )
    assert len(sigs) == 1
    assert sigs[0]["close_reason"] == "stop"
    assert sigs[0]["return_pct"] < 0


def test_timeout_closes_signal_at_last_price():
    # Cross down to 10, then drift sideways forever within stop / target band.
    prices = [12.0, 10.0] + [10.5] * 200
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=20.0,
        stop_pct=0.10, timeout_days=180, as_of=AS_OF, cooldown_days=0,
    )
    assert len(sigs) == 1
    assert sigs[0]["close_reason"] == "timeout"


def test_open_signal_marks_to_last_price_when_no_exit_yet():
    # Cross down, drift for only 30 days — should be open.
    prices = [12.0, 10.0] + [10.5] * 29
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=20.0,
        stop_pct=0.10, timeout_days=180, as_of=AS_OF, cooldown_days=0,
    )
    assert len(sigs) == 1
    s = sigs[0]
    assert s["open"] is True
    assert s["close_reason"] == "open"
    assert s["close_price"] == pytest.approx(10.5, abs=0.01)


def test_cooldown_merges_re_signals_into_existing():
    # Cross down → bounce up → cross down again within cooldown — should be ONE signal.
    prices = [12.0, 10.0, 12.5, 9.5, 12.0, 15.0]
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=15.0,
        as_of=AS_OF, cooldown_days=30,
    )
    assert len(sigs) == 1


def test_cooldown_zero_allows_re_signals():
    prices = [12.0, 10.0, 12.5, 9.5, 12.0, 15.0]
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=15.0,
        as_of=AS_OF, cooldown_days=0,
    )
    assert len(sigs) >= 1


def test_signal_at_history_start_when_already_in_zone():
    # Series starts below entry — that's a signal on day 1.
    prices = [9.0, 9.5, 10.0, 11.0, 14.0, 15.0]
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=15.0,
        as_of=AS_OF, cooldown_days=0,
    )
    assert len(sigs) >= 1
    assert sigs[0]["entry_price"] == 9.0


def test_no_signals_when_price_never_enters_zone():
    prices = [15.0, 14.0, 13.0, 12.5, 13.0, 14.0, 15.0]
    sigs = detect_signals(
        "TST", _series(prices), target_entry=10.0, target_exit=20.0,
        as_of=AS_OF, cooldown_days=0,
    )
    assert sigs == []


def test_empty_or_invalid_inputs_return_no_signals():
    assert detect_signals("TST", _series([]), 10.0, 15.0) == []
    assert detect_signals("TST", None, 10.0, 15.0) == []
    assert detect_signals("TST", _series([10.0]), 0.0, 15.0) == []


# ---- build_track_record --------------------------------------------------


def test_build_track_record_combines_multiple_tickers():
    watchlist = pd.DataFrame([
        {"ticker": "WIN", "name": "Winner Co", "target_entry": 10.0,
         "target_exit": 15.0, "description": "AI"},
        {"ticker": "LOSE", "name": "Loser Co", "target_entry": 10.0,
         "target_exit": 20.0, "description": "AI"},
    ])
    histories = {
        "WIN":  _series([12.0, 10.0, 12.0, 14.0, 15.0]),     # hits target
        "LOSE": _series([12.0, 10.0, 9.5, 8.5, 8.0]),         # hits stop
    }
    tr = build_track_record(
        watchlist, histories, as_of=AS_OF, cooldown_days=0,
    )
    assert set(tr["ticker"]) == {"WIN", "LOSE"}
    assert tr.set_index("ticker").loc["WIN", "close_reason"] == "target"
    assert tr.set_index("ticker").loc["LOSE", "close_reason"] == "stop"


def test_build_track_record_skips_rows_without_entry():
    watchlist = pd.DataFrame([
        {"ticker": "X", "name": "X", "target_entry": float("nan"),
         "target_exit": 15.0, "description": ""},
    ])
    histories = {"X": _series([12.0, 10.0, 11.0, 15.0])}
    assert build_track_record(watchlist, histories, as_of=AS_OF).empty


def test_build_track_record_skips_tickers_with_no_price_history():
    watchlist = pd.DataFrame([
        {"ticker": "MISSING", "name": "Missing", "target_entry": 10.0,
         "target_exit": 15.0, "description": ""},
    ])
    assert build_track_record(watchlist, {}, as_of=AS_OF).empty


# ---- summarise_track_record ----------------------------------------------


def _sample_signals() -> pd.DataFrame:
    return pd.DataFrame([
        {"signal_date": date(2026, 1, 1), "ticker": "A", "entry_price": 10.0,
         "close_date": date(2026, 2, 1), "close_price": 15.0,
         "close_reason": "target", "return_pct": 50.0, "days_held": 31,
         "open": False},
        {"signal_date": date(2026, 1, 15), "ticker": "B", "entry_price": 20.0,
         "close_date": date(2026, 3, 1), "close_price": 18.0,
         "close_reason": "stop", "return_pct": -10.0, "days_held": 45,
         "open": False},
        {"signal_date": date(2026, 4, 1), "ticker": "C", "entry_price": 30.0,
         "close_date": None, "close_price": 32.0,
         "close_reason": "open", "return_pct": 6.7, "days_held": 60,
         "open": True},
    ])


def test_summary_counts_and_rates():
    s = summarise_track_record(_sample_signals(), position_size_usd=1_000_000)
    assert s["total"] == 3
    assert s["open"] == 1
    assert s["closed"] == 2
    assert s["win_rate"] == pytest.approx(0.5)        # A wins, B loses
    assert s["hit_rate"] == pytest.approx(0.5)        # A hit target
    assert s["avg_return_pct"] == pytest.approx(20.0)  # (50 - 10) / 2
    # P&L: A made +500k, B lost 100k → +400k
    assert s["total_realised_usd"] == pytest.approx(400_000.0)


def test_summary_handles_empty():
    s = summarise_track_record(pd.DataFrame())
    assert s["total"] == 0 and s["closed"] == 0
    assert s["win_rate"] == 0.0 and s["total_realised_usd"] == 0.0


def test_summary_all_open_yields_zero_closed_metrics():
    sig = _sample_signals().iloc[[2]]
    s = summarise_track_record(sig)
    assert s["total"] == 1 and s["open"] == 1 and s["closed"] == 0
    assert s["win_rate"] == 0.0
    assert s["total_realised_usd"] == 0.0


# ---- cumulative_pnl_series -----------------------------------------------


def test_cumulative_pnl_runs_in_close_date_order():
    pnl = cumulative_pnl_series(_sample_signals(), position_size_usd=1_000_000)
    assert list(pnl["close_date"]) == sorted(pnl["close_date"])
    # Final cumulative should equal sum of closed realised
    assert pnl["cumulative_usd"].iloc[-1] == pytest.approx(400_000.0)


def test_cumulative_pnl_empty_when_no_closed():
    sig = _sample_signals().iloc[[2]]  # only the open one
    assert cumulative_pnl_series(sig).empty
