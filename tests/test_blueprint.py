"""Tests for the core-satellite blueprint arithmetic."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.blueprint import (
    PRESET_CORES,
    classify_holdings,
    core_history_stats,
    rebalance_hint,
    required_satellite_cagr,
)
from icarus.portfolio import positions_from_trades


def test_presets_weights_sum_to_one():
    for name, w in PRESET_CORES.items():
        assert sum(w.values()) == pytest.approx(1.0), name


def test_required_satellite_cagr_blend_identity():
    # 80% core at 10%: a 20% blend needs the satellite at +60%.
    assert required_satellite_cagr(20.0, 10.0) == pytest.approx(60.0)
    # Core alone already at target -> satellite just needs the target.
    assert required_satellite_cagr(20.0, 20.0) == pytest.approx(20.0)
    # Bigger satellite sleeve lowers the requirement.
    assert (required_satellite_cagr(20.0, 10.0, core_weight=0.6)
            < required_satellite_cagr(20.0, 10.0, core_weight=0.8))


def test_core_history_stats_on_synthetic_decade():
    idx = pd.date_range("2016-01-01", periods=2600, freq="B")
    a = pd.Series(100 * np.cumprod(np.full(2600, 1.0004)), index=idx)
    b = pd.Series(100 * np.cumprod(np.full(2600, 1.0002)), index=idx)
    stats = core_history_stats(pd.DataFrame({"A": a, "B": b}),
                               {"A": 0.5, "B": 0.5})
    assert stats is not None
    assert 7.0 < stats["cagr_pct"] < 9.0        # ~0.03%/day blended
    assert stats["max_drawdown_pct"] <= 0.0
    # Missing member -> None
    assert core_history_stats(pd.DataFrame({"A": a}), {"A": .5, "C": .5}) is None


def _pos(rows):
    trades = pd.DataFrame([
        {"id": str(i), "date": "2026-01-05", "ticker": t, "side": "buy",
         "qty": q, "price": p, "note": ""}
        for i, (t, q, p) in enumerate(rows)
    ])
    return positions_from_trades(trades)[0]


def test_classify_and_rebalance_hint():
    positions = _pos([("SPY", 8, 100.0), ("HIVE", 100, 2.0)])
    split = classify_holdings(positions, {}, {"SPY"})
    assert split["core_pct"] == pytest.approx(80.0)
    assert split["satellite_names"] == ["HIVE"]
    # On-target: no hint
    assert rebalance_hint(split) is None
    # Satellite-heavy: hint says move INTO the core
    heavy = classify_holdings(_pos([("SPY", 5, 100.0), ("HIVE", 250, 2.0)]),
                              {}, {"SPY"})
    hint = rebalance_hint(heavy)
    assert hint and "into the core" in hint


def test_classify_empty():
    split = classify_holdings(pd.DataFrame(), {}, {"SPY"})
    assert split["total_value"] == 0.0
    assert rebalance_hint(split) is None


def test_plan_progress_tracks_caps_and_rotation():
    from icarus.blueprint import plan_progress
    positions = pd.DataFrame([
        {"ticker": "VWRP", "account": "SIPP", "qty": 100, "avg_cost": 100.0,
         "invested": 10000.0},
        {"ticker": "MNTS", "account": "SIPP", "qty": 100, "avg_cost": 10.0,
         "invested": 1000.0},
        {"ticker": "VWRP", "account": "ISA", "qty": 80, "avg_cost": 100.0,
         "invested": 8000.0},
        {"ticker": "AQB", "account": "ISA", "qty": 100, "avg_cost": 10.0,
         "invested": 1000.0},
    ])
    prog = plan_progress(positions, {})
    sipp, isa = prog["SIPP"], prog["ISA"]
    assert sipp["stock_pct"] == pytest.approx(1000 / 11000 * 100)
    assert not sipp["over_cap"]                  # 9.1% < 10%
    assert "MNTS" in sipp["sell_pending"]
    assert "SLNH" in sipp["sell_done"]           # not held in SIPP here
    assert isa["stock_pct"] == pytest.approx(1000 / 9000 * 100)
    assert not isa["over_cap"]                   # 11% < 20%
    assert isa["sell_done"] == ["SRXH", "IREN", "SMR", "KITT"]


def test_plan_progress_empty():
    from icarus.blueprint import plan_progress
    prog = plan_progress(pd.DataFrame(), {})
    assert prog["SIPP"]["stock_pct"] == 0.0
    assert not prog["ISA"]["over_cap"]
