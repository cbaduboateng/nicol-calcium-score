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


# ---- find_gems (strict gates ∩ day-scale signals) ------------------------


def _gems_view() -> pd.DataFrame:
    return pd.DataFrame([
        # Passes every strict gate AND has day-scale action → the gem
        {"ticker": "GEM", "name": "Gem Co", "theme": "AI / Big Data",
         "status": "BUY ZONE", "live_price": 9.9, "target_entry": 10.0,
         "target_exit": 25.0, "reward_risk": 4.0,
         "pct_1m": 5.0, "pct_3m": 25.0, "pct_6m": 40.0, "pct_12m": 60.0},
        # Big volume surge but NEGATIVE 3m momentum → fails strict, no gem
        {"ticker": "NOISY", "name": "Noisy Co", "theme": "Cannabis",
         "status": "BUY ZONE", "live_price": 4.9, "target_entry": 5.0,
         "target_exit": 20.0, "reward_risk": 4.0,
         "pct_1m": 2.0, "pct_3m": -10.0, "pct_6m": -20.0, "pct_12m": -30.0},
        # Quality name but only HOLD status → fails the zone gate
        {"ticker": "HELD", "name": "Held Co", "theme": "AI / Big Data",
         "status": "HOLD", "live_price": 30.0, "target_entry": 20.0,
         "target_exit": 90.0, "reward_risk": 3.5,
         "pct_1m": 4.0, "pct_3m": 20.0, "pct_6m": 35.0, "pct_12m": 50.0},
    ])


def _gems_histories() -> dict[str, pd.Series]:
    return {
        "GEM": _series([12.0] * 30 + [9.9]),      # crossed in today
        "NOISY": _series([5.5] * 5 + [4.9] * 26),  # sat in zone for weeks
        "HELD": _series([30.0] * 31),
    }


def _gems_volumes() -> dict[str, pd.Series]:
    return {
        "GEM": _series([1e6] * 30 + [3e6]),
        "NOISY": _series([1e6] * 30 + [8e6]),  # huge surge, but it's a knife
    }


def test_find_gems_requires_strict_gates_and_daily_action():
    from icarus.daily_signals import find_gems
    gems = find_gems(_gems_view(), _gems_histories(), _gems_volumes())
    assert list(gems["ticker"]) == ["GEM"]
    g = gems.iloc[0]
    # Blend of quality composite and today score
    assert g["gem_score"] == pytest.approx(
        0.5 * g["composite"] + 0.5 * g["today_score"],
    )
    assert "crossed into the buy zone today" in g["reasons"]


def test_find_gems_volume_surge_cannot_rescue_a_falling_knife():
    from icarus.daily_signals import find_gems
    gems = find_gems(_gems_view(), _gems_histories(), _gems_volumes(), top_n=10)
    assert "NOISY" not in set(gems["ticker"])
    assert "HELD" not in set(gems["ticker"])


def test_find_gems_insider_overlay_is_soft_not_gating():
    from icarus.daily_signals import find_gems
    # No insider data at all → GEM must still qualify (overlay is a bonus)
    without = find_gems(_gems_view(), _gems_histories(), _gems_volumes())
    assert "GEM" in set(without["ticker"])
    boosted = find_gems(
        _gems_view(), _gems_histories(), _gems_volumes(),
        insider_overlay={"GEM": {"score": 1.0, "summary": "2 insiders bought"}},
    )
    g_without = float(without[without["ticker"] == "GEM"]["gem_score"].iloc[0])
    g_boosted = float(boosted[boosted["ticker"] == "GEM"]["gem_score"].iloc[0])
    assert g_boosted > g_without


def test_find_gems_carries_market_cap_for_size_badging():
    from icarus.daily_signals import find_gems
    view = _gems_view().copy()
    view["market_cap_usd"] = [85_000_000.0, 2_000_000_000.0, None]
    gems = find_gems(view, _gems_histories(), _gems_volumes())
    assert "market_cap_usd" in gems.columns
    assert gems.iloc[0]["market_cap_usd"] == pytest.approx(85_000_000.0)


def test_find_gems_empty_inputs():
    from icarus.daily_signals import find_gems
    assert find_gems(pd.DataFrame(), {}, {}).empty
    # All strict-failers → empty even with histories present
    knife_only = _gems_view().iloc[[1]]
    assert find_gems(knife_only, _gems_histories(), _gems_volumes()).empty


# ---- pick_of_the_day -------------------------------------------------------


def _pool(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_pick_prefers_curated_over_slightly_stronger_explorer():
    from icarus.daily_signals import pick_of_the_day
    curated = _pool([{"ticker": "CUR", "gem_score": 0.60, "tgt_src": "A/A"}])
    explorer = _pool([{"ticker": "EXP", "gem_score": 0.65}])
    # 0.60 x 1.0 = 0.60 beats 0.65 x 0.85 = 0.5525
    v = pick_of_the_day([(curated, "curated", 1.0), (explorer, "explorer", 0.85)])
    assert v["pick"]["ticker"] == "CUR"


def test_pick_lets_a_much_stronger_explorer_win():
    from icarus.daily_signals import pick_of_the_day
    curated = _pool([{"ticker": "CUR", "gem_score": 0.55, "tgt_src": "A/A"}])
    explorer = _pool([{"ticker": "EXP", "gem_score": 0.80}])
    # 0.80 x 0.85 = 0.68 beats 0.55
    v = pick_of_the_day([(curated, "curated", 1.0), (explorer, "explorer", 0.85)])
    assert v["pick"]["ticker"] == "EXP"


def test_pick_abstains_below_conviction_floor():
    from icarus.daily_signals import pick_of_the_day
    weak = _pool([{"ticker": "MEH", "gem_score": 0.45, "tgt_src": "A/A"}])
    v = pick_of_the_day([(weak, "curated", 1.0)])
    assert v["pick"] is None
    assert "conviction floor" in v["reason"]
    assert "MEH" in v["reason"]


def test_pick_derived_targets_get_row_level_discount():
    from icarus.daily_signals import pick_of_the_day
    pool = _pool([
        {"ticker": "ANA", "gem_score": 0.60, "tgt_src": "A/A"},
        {"ticker": "DER", "gem_score": 0.62, "tgt_src": "D/D"},
    ])
    # DER: 0.62 x 0.93 = 0.5766 < ANA: 0.60
    v = pick_of_the_day([(pool, "curated", 1.0)])
    assert v["pick"]["ticker"] == "ANA"


def test_pick_empty_pools_abstain():
    from icarus.daily_signals import pick_of_the_day
    v = pick_of_the_day([(pd.DataFrame(), "curated", 1.0)])
    assert v["pick"] is None
    assert v["reason"] == "no gems in any pool"


# ---- gem_gate_failures (the near-miss explainer) --------------------------


def test_gate_failures_names_each_failed_gate():
    from icarus.daily_signals import gem_gate_failures
    knife = _gems_view().iloc[1]  # NOISY: buy zone, but -10% 3m, cold theme
    fails = gem_gate_failures(knife, {"Cannabis": -12.0})
    joined = " ".join(fails)
    assert "own 3m momentum negative" in joined
    assert "theme cold" in joined
    assert "not in buy zone" not in joined  # it IS in the zone


def test_gate_failures_empty_for_a_true_gem():
    from icarus.daily_signals import gem_gate_failures
    gem = _gems_view().iloc[0]
    assert gem_gate_failures(gem, {"AI / Big Data": 22.0}) == []


def test_gate_failures_flags_hold_status_and_weak_rr():
    from icarus.daily_signals import gem_gate_failures
    row = pd.Series({
        "ticker": "X", "status": "HOLD", "theme": "AI / Big Data",
        "pct_3m": 10.0, "pct_6m": 20.0, "reward_risk": 1.2,
    })
    fails = gem_gate_failures(row, {"AI / Big Data": 15.0})
    joined = " ".join(fails)
    assert "not in buy zone" in joined
    assert "R:R 1.2 below the 3 floor" in joined


def test_gate_failures_infinite_rr_passes():
    from icarus.daily_signals import gem_gate_failures
    row = pd.Series({
        "ticker": "X", "status": "BUY ZONE", "theme": "AI / Big Data",
        "pct_3m": 10.0, "pct_6m": 20.0, "reward_risk": float("inf"),
    })
    fails = gem_gate_failures(row, {"AI / Big Data": 15.0})
    assert not any("R:R" in f for f in fails)


def test_gate_failures_flags_parabolic():
    from icarus.daily_signals import gem_gate_failures
    row = pd.Series({
        "ticker": "X", "status": "BUY ZONE", "theme": "AI / Big Data",
        "pct_3m": 60.0, "pct_6m": 250.0, "reward_risk": 4.0,
    })
    fails = gem_gate_failures(row, {"AI / Big Data": 15.0})
    assert any("parabolic" in f for f in fails)
