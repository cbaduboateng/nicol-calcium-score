"""Tests for the PEAD event study and the FX-aware P&L split."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.pead import compare_pead, event_returns, pead_verdict
from icarus.portfolio import fx_pnl_breakdown, positions_from_trades


def _series(vals: list[float], start: str = "2025-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(vals), freq="B")
    return pd.Series(vals, index=idx)


def _drifting(n: int = 60, drift: float = 0.005) -> pd.Series:
    return _series(list(100 * np.cumprod(np.full(n, 1.0 + drift))))


def test_event_entry_is_next_close_and_net_of_costs():
    px = _series([100.0] * 10 + [110.0] * 30)     # jump AFTER the event
    events = pd.DataFrame([{"ticker": "AAA",
                            "date": px.index[9], "surprise_pct": 10.0}])
    marked = event_returns(events, {"AAA": px}, hold_sessions=20,
                           cost_pct=0.3)
    assert len(marked) == 1
    m = marked.iloc[0]
    # Entry at the first close after the event = 110 (the jump is NOT
    # captured), then flat -> return is just the cost drag.
    assert m["return_pct"] == pytest.approx(-0.3)


def test_positive_arm_beats_neutral_when_drift_exists():
    # Positive-surprise names drift; neutral names stay flat.
    events = []
    hist = {}
    for i in range(8):
        t = f"POS{i}"
        hist[t] = _drifting()
        events.append({"ticker": t, "date": hist[t].index[10],
                       "surprise_pct": 12.0})
        t2 = f"NEU{i}"
        hist[t2] = _series([100.0] * 60)
        events.append({"ticker": t2, "date": hist[t2].index[10],
                       "surprise_pct": 0.5})
    table = compare_pead(pd.DataFrame(events), hist)
    assert len(table) == 2
    pos = table[~table["arm"].str.startswith("control")].iloc[0]
    ctrl = table[table["arm"].str.startswith("control")].iloc[0]
    assert pos["mean_return_pct"] > ctrl["mean_return_pct"]
    # 16 events split across halves is under the 30/half bar.
    assert pead_verdict(table) == "undersampled"


def test_verdict_pass_and_fail():
    def _tab(p1, p2):
        return pd.DataFrame([
            {"arm": "positive", "n_first": 40, "n_second": 40,
             "mean_first_pct": p1, "mean_second_pct": p2},
            {"arm": "control: neutral", "n_first": 40, "n_second": 40,
             "mean_first_pct": 1.0, "mean_second_pct": 1.0},
        ])
    assert pead_verdict(_tab(2.0, 1.5)) == "pass"
    assert pead_verdict(_tab(2.0, 0.5)) == "fail"


def test_fx_breakdown_splits_stock_and_currency():
    trades = pd.DataFrame([{
        "id": "1", "date": "2025-06-02", "ticker": "AAA",
        "side": "buy", "qty": 100, "price": 10.0, "note": "",
    }])
    positions, _ = positions_from_trades(trades)
    # Bought at GBPUSD 1.25; now 1.00: the dollar strengthened, so the
    # GBP value of the same dollars rose 25% on FX alone.
    fx = pd.Series([1.25, 1.25, 1.00],
                   index=pd.to_datetime(["2025-06-01", "2025-06-02",
                                         "2026-01-05"]))
    quotes = {"AAA": {"price": 12.0}}      # +20% in USD
    b = fx_pnl_breakdown(trades, positions, quotes, fx)
    assert b is not None
    assert b["stock_return_pct"] == pytest.approx(20.0)
    assert b["invested_gbp"] == pytest.approx(1000 / 1.25)
    assert b["value_gbp"] == pytest.approx(1200.0)
    assert b["total_gbp_return_pct"] == pytest.approx(50.0)
    assert b["fx_contribution_pts"] == pytest.approx(30.0)


def test_fx_breakdown_graceful_without_data():
    assert fx_pnl_breakdown(pd.DataFrame(), pd.DataFrame(), {},
                            pd.Series(dtype=float)) is None
