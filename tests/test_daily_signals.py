"""Tests for the daily action-ranking signals."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.daily_signals import (
    compute_daily_signals,
    days_in_zone,
    pct_change_over,
    relative_volume,
)


def _series(vals: list[float]) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=len(vals), freq="D")
    return pd.Series(vals, index=idx)


# ---- primitives ----------------------------------------------------------


def test_relative_volume_flags_a_surge():
    vols = [1_000_000.0] * 20 + [3_000_000.0]
    assert relative_volume(_series(vols)) == pytest.approx(3.0)


def test_relative_volume_nan_when_history_short():
    assert np.isnan(relative_volume(_series([1e6] * 5)))
    assert np.isnan(relative_volume(None))


def test_days_in_zone_counts_consecutive_sessions():
    # Above entry (10) for a while, then 3 closes at/below it.
    hist = _series([12, 11, 10.5, 9.9, 9.8, 9.7])
    assert days_in_zone(hist, 10.0) == 3


def test_days_in_zone_zero_when_above_entry():
    hist = _series([12, 11, 10.5])
    assert days_in_zone(hist, 10.0) == 0


def test_days_in_zone_one_means_crossed_today():
    hist = _series([12, 11, 9.9])
    assert days_in_zone(hist, 10.0) == 1


def test_pct_change_over_sessions():
    hist = _series([100, 100, 100, 100, 100, 110])
    assert pct_change_over(hist, 1) == pytest.approx(10.0)
    assert pct_change_over(hist, 5) == pytest.approx(10.0)
    assert np.isnan(pct_change_over(hist, 50))


# ---- compute_daily_signals ------------------------------------------------


def _view() -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": "HOT", "name": "Hot Co", "theme": "AI / Big Data",
         "status": "BUY ZONE", "live_price": 9.9, "target_entry": 10.0,
         "target_exit": 25.0, "reward_risk": 3.0},
        {"ticker": "COLD", "name": "Cold Co", "theme": "Cannabis",
         "status": "BUY ZONE", "live_price": 4.9, "target_entry": 5.0,
         "target_exit": 7.0, "reward_risk": 1.2},
        {"ticker": "HELD", "name": "Held Co", "theme": "AI / Big Data",
         "status": "HOLD", "live_price": 30.0, "target_entry": 20.0,
         "target_exit": 60.0, "reward_risk": 2.0},
    ])


def _histories() -> dict[str, pd.Series]:
    # HOT crossed into the zone today; COLD has sat in the zone for weeks.
    hot = [12.0] * 30 + [9.9]
    cold = [4.9] * 31
    return {"HOT": _series(hot), "COLD": _series(cold),
            "HELD": _series([30.0] * 31)}


def _volumes(surge_hot: bool = True) -> dict[str, pd.Series]:
    hot = [1e6] * 30 + ([4e6] if surge_hot else [1e6])
    return {"HOT": _series(hot), "COLD": _series([1e6] * 31)}


def test_fresh_crossing_with_volume_surge_ranks_first():
    today = compute_daily_signals(
        _view(), _histories(), _volumes(),
        theme_3m={"AI / Big Data": 25.0, "Cannabis": -10.0},
    )
    assert today.iloc[0]["ticker"] == "HOT"
    assert today.iloc[0]["days_in_zone"] == 1
    assert today.iloc[0]["rel_volume"] == pytest.approx(4.0)
    assert "crossed into the buy zone today" in today.iloc[0]["reasons"]
    assert "4.0× average volume" in today.iloc[0]["reasons"]


def test_hold_status_rows_are_excluded():
    today = compute_daily_signals(_view(), _histories(), _volumes(), top_n=10)
    assert "HELD" not in set(today["ticker"])


def test_news_bonus_lifts_score():
    base = compute_daily_signals(_view(), _histories(), _volumes())
    with_news = compute_daily_signals(
        _view(), _histories(), _volumes(),
        news_counts={"COLD": {"count": 2, "tags": ["FDA"]}},
    )
    cold_base = float(base[base["ticker"] == "COLD"]["today_score"].iloc[0])
    cold_news = float(with_news[with_news["ticker"] == "COLD"]["today_score"].iloc[0])
    assert cold_news == pytest.approx(cold_base + 0.10, abs=1e-6)
    assert "2 headlines in 48h (FDA)" in (
        with_news[with_news["ticker"] == "COLD"]["reasons"].iloc[0]
    )


def test_missing_volume_degrades_to_neutral_not_crash():
    today = compute_daily_signals(_view(), _histories(), None)
    assert not today.empty
    assert np.isnan(today[today["ticker"] == "COLD"]["rel_volume"].iloc[0])


def test_empty_view_returns_empty():
    assert compute_daily_signals(pd.DataFrame(), {}, {}).empty
