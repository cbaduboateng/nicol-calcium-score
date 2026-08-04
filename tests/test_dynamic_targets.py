"""Tests for dynamic point-in-time entry levels."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.dynamic_targets import (
    compare_entry_modes,
    current_dynamic_entry,
    detect_signals_dynamic,
    rolling_entry_series,
)


def _series(prices: list[float], start: str = "2025-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(prices), freq="D")
    return pd.Series(prices, index=idx)


def test_rolling_entry_is_ratio_times_trailing_low():
    s = _series([10.0] * 70)
    lvl = rolling_entry_series(s, 0.9)
    assert lvl.dropna().iloc[-1] == pytest.approx(9.0)


def test_rolling_entry_has_no_same_day_lookahead():
    base = [10.0] * 70
    crash_today = base[:-1] + [1.0]      # today collapses
    lvl_base = rolling_entry_series(_series(base), 0.9)
    lvl_crash = rolling_entry_series(_series(crash_today), 0.9)
    # Today's level must be identical: it only sees closes up to yesterday.
    assert lvl_base.iloc[-1] == pytest.approx(lvl_crash.iloc[-1])


def test_level_rises_with_a_rising_base():
    s = _series(list(np.linspace(10.0, 20.0, 400)))
    lvl = rolling_entry_series(s, 0.9).dropna()
    # Once the 252-window is full, the trailing low starts climbing.
    assert lvl.iloc[-1] > lvl.iloc[100]


def test_current_dynamic_entry_matches_series_tail():
    s = _series([10.0] * 70)
    assert current_dynamic_entry(s, 0.9) == pytest.approx(9.0)
    assert current_dynamic_entry(_series([10.0] * 10), 0.9) is None  # too short


def test_dynamic_signal_fires_on_cross_and_hits_target():
    # Flat 10s -> level 9.0; dip to 8.9 fires; rally to 2x closes at target.
    prices = [10.0] * 70 + [8.9] + list(np.linspace(9.5, 19.0, 20))
    sigs = detect_signals_dynamic("T", _series(prices), 0.9, 2.0)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["entry_price"] == pytest.approx(8.9)
    assert s["target_entry"] == pytest.approx(9.0)
    assert s["target_exit"] == pytest.approx(17.8)
    assert s["close_reason"] == "target"
    assert s["return_pct"] > 0


def test_cooldown_merges_rapid_recrossings():
    # Two dips five days apart: second is inside the 30-day cooldown.
    prices = [10.0] * 70 + [8.9, 9.6, 9.7, 9.6, 8.85] + [9.5] * 10
    sigs = detect_signals_dynamic("T", _series(prices), 0.9, 2.0)
    assert len(sigs) == 1


def test_no_signal_without_enough_history():
    assert detect_signals_dynamic("T", _series([10.0] * 20), 0.9, 2.0) == []


def test_compare_entry_modes_shapes_and_arms():
    n = 400
    ramp = list(np.linspace(8.0, 12.0, n - 40))
    tail = [7.0] + list(np.linspace(9.0, 21.0, 39))   # dip then rally
    hist = {"AAA": _series(ramp + tail), "BBB": _series([5.0] * n)}
    wl = pd.DataFrame([
        {"ticker": "AAA", "name": "A", "description": "AI play",
         "target_entry": 8.0, "target_exit": 20.0},
        {"ticker": "BBB", "name": "B", "description": "AI play",
         "target_entry": np.nan, "target_exit": np.nan},
    ])
    pattern = {
        "anchor": "low52", "entry_ratio": 0.9, "theme_entry_ratios": {},
        "exit_multiple": 2.0, "theme_exit_multiples": {},
        "dispersions": {"low52": 0.5}, "n_entry": 30, "n_exit": 10,
    }
    res = compare_entry_modes(wl, hist, pattern)
    assert list(res["variant"]) == [
        "static: analyst entries (control)",
        "dynamic: same tickers",
        "dynamic: full watchlist",
    ]
    for col in ("n_signals", "win_rate", "avg_train_pct", "avg_test_pct"):
        assert col in res.columns
    # Full-watchlist arm can only ever see >= the same-ticker arm's universe.
    assert res.iloc[2]["n_signals"] >= res.iloc[1]["n_signals"]


def test_compare_entry_modes_empty_inputs():
    assert compare_entry_modes(pd.DataFrame(), {}, {}).empty
    wl = pd.DataFrame([{"ticker": "A", "description": "", "target_entry": 1.0,
                        "target_exit": 2.0}])
    assert compare_entry_modes(wl, {}, {"entry_ratio": 0.9}).empty
