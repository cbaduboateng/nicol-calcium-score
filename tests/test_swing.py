"""Tests for the swing engine: setups, conservative fills, evidence table."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.swing import (
    DEFAULT_SWING_VARIANTS,
    SwingVariant,
    compare_swing_variants,
    replay_swing,
    rsi,
    swing_setups,
    todays_swing_candidates,
)


def _series(prices: list[float], start: str = "2025-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(prices), freq="D")
    return pd.Series(prices, index=idx)


def _uptrend_base(n: int = 80) -> list[float]:
    return list(np.linspace(10.0, 14.0, n))


def _dip_base() -> list[float]:
    """Flat floor then a fresh ramp: the 50-session mean stays low, so a
    5-10% pullback off the high remains ABOVE trend (a real dip-buy)."""
    return [10.0] * 60 + list(np.linspace(10.0, 14.0, 20))


def test_rsi_extremes():
    up = _series(list(np.linspace(10, 20, 40)))
    down = _series(list(np.linspace(20, 10, 40)))
    assert rsi(up).iloc[-1] > 70
    assert rsi(down).iloc[-1] < 30


def test_dip_setup_fires_only_on_pullback_in_uptrend():
    v = SwingVariant("dip", "dip")
    smooth = _series(_dip_base())
    assert not swing_setups(smooth, v).any()          # no pullback, no setup
    dipped = _series(_dip_base() + [12.6])            # 10% off the 14.0 high
    assert bool(swing_setups(dipped, v).iloc[-1])


def test_breakout_setup_fires_on_new_high():
    v = SwingVariant("bo", "breakout")
    base = _uptrend_base() + [13.0] * 20 + [14.5]     # pause then new high
    assert bool(swing_setups(_series(base), v).iloc[-1])


def test_replay_fills_next_close_and_caps_target_fill():
    # Setup on the dip close; entry is the NEXT close (12.5); then a gap
    # far above target must be credited at the limit price only.
    prices = _dip_base() + [12.6, 12.5, 20.0]
    v = SwingVariant("dip", "dip", target_pct=5.0, stop_pct=3.0)
    trades = replay_swing("T", _series(prices), v, cost_pct=0.0)
    assert len(trades) == 1
    t = trades[0]
    assert t["entry_price"] == pytest.approx(12.5)
    assert t["close_reason"] == "target"
    assert t["exit_price"] == pytest.approx(12.5 * 1.05)  # limit, not the gap
    assert t["return_pct"] == pytest.approx(5.0)


def test_replay_stop_fills_at_gap_close():
    prices = _dip_base() + [12.6, 12.5, 8.0]          # gap through the stop
    v = SwingVariant("dip", "dip", stop_pct=3.0)
    t = replay_swing("T", _series(prices), v, cost_pct=0.0)[0]
    assert t["close_reason"] == "stop"
    assert t["exit_price"] == pytest.approx(8.0)      # worse than the 12.125 stop
    assert t["return_pct"] < -3.0


def test_cost_haircut_reduces_return():
    prices = _dip_base() + [12.6, 12.5, 12.8]
    v = SwingVariant("dip", "dip")
    gross = replay_swing("T", _series(prices), v, cost_pct=0.0)[0]["return_pct"]
    net = replay_swing("T", _series(prices), v, cost_pct=0.5)[0]["return_pct"]
    assert net == pytest.approx(gross - 0.5)


def test_timeout_closes_at_last_window_close():
    flat_after = _dip_base() + [12.6, 12.5] + [12.4] * 12
    v = SwingVariant("dip", "dip", timeout_sessions=10)
    t = replay_swing("T", _series(flat_after), v, cost_pct=0.0)[0]
    assert t["close_reason"] == "timeout"


def test_compare_has_all_variants_and_split_columns():
    hist = {"AAA": _series(_uptrend_base(300))}
    res = compare_swing_variants(hist)
    assert len(res) == len(DEFAULT_SWING_VARIANTS)
    for col in ("variant", "n_signals", "win_rate", "avg_train_pct",
                "avg_test_pct"):
        assert col in res.columns


def test_candidates_require_liquidity():
    prices = _dip_base() + [12.6]
    hist = {"LIQ": _series(prices), "THIN": _series(prices)}
    vols = {
        "LIQ": _series([500_000.0] * len(prices)),    # ~$6M ADV
        "THIN": _series([1_000.0] * len(prices)),     # ~$12k ADV
    }
    v = SwingVariant("dip", "dip")
    cands = todays_swing_candidates(hist, vols, v)
    assert list(cands["ticker"]) == ["LIQ"]
    row = cands.iloc[0]
    assert row["target_price"] == pytest.approx(row["live_price"] * 1.05)
    assert row["stop_price"] == pytest.approx(row["live_price"] * 0.97)


def test_pools_are_well_formed():
    from icarus.swing import SWING_POOLS
    for name, pool in SWING_POOLS.items():
        assert pool["tickers"], name
        assert len(set(pool["tickers"])) == len(pool["tickers"]), f"dupes in {name}"
        assert 0.0 < pool["cost_pct"] <= 2.0
    all_syms = [t for p in SWING_POOLS.values() for t in p["tickers"]]
    assert len(set(all_syms)) == len(all_syms), "symbol in two pools"


def test_swing_cache_loader_missing_files_graceful(tmp_path):
    from icarus.swing import load_swing_universe_cache
    h, v = load_swing_universe_cache(
        str(tmp_path / "nope.parquet"), str(tmp_path / "nope2.parquet"),
    )
    assert h == {} and v == {}


def test_compare_swing_pools_tags_pool_and_cost():
    from icarus.swing import compare_swing_pools
    hist = {"AAA": _series(_uptrend_base(300))}
    res = compare_swing_pools({"etf": hist, "empty": {}})
    assert not res.empty
    assert set(res["pool"]) == {"etf"}
    assert res["cost_pct"].iloc[0] == pytest.approx(0.10)


def test_candidates_empty_without_volume_data():
    prices = _dip_base() + [12.6]
    cands = todays_swing_candidates({"A": _series(prices)}, None,
                                    SwingVariant("dip", "dip"))
    assert cands.empty
