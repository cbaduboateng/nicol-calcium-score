"""Tests for the SPArtans watchlist alert engine."""

from __future__ import annotations

import pandas as pd
import pytest

from icarus.watchlist_alerts import (
    APPROACHING_PCT_ABOVE_ENTRY,
    compute_status,
    gap_to_entry_pct,
    map_theme,
    parabolic_rank,
    pick_winners,
    reward_risk_to_targets,
    theme_heat,
)


# ---- status logic --------------------------------------------------------


def test_status_buy_zone_when_price_below_entry():
    assert compute_status(8.0, 10.0, 20.0) == "BUY ZONE"


def test_status_sell_zone_when_price_above_exit():
    assert compute_status(22.0, 10.0, 20.0) == "SELL ZONE"


def test_status_approaching_when_within_15pct_above_entry():
    # 10% above entry of 10 = 11; 15% bound = 11.5
    assert compute_status(11.0, 10.0, 20.0) == "APPROACHING"
    assert compute_status(11.5, 10.0, 20.0) == "APPROACHING"
    assert compute_status(11.6, 10.0, 20.0) == "HOLD"


def test_status_watch_when_no_targets():
    assert compute_status(10.0, None, None) == "WATCH"


def test_status_missing_price():
    assert compute_status(None, 10.0, 20.0) == "PRICE MISSING"
    assert compute_status(0, 10.0, 20.0) == "PRICE MISSING"


def test_sell_zone_wins_over_buy_zone():
    """Edge: if a stock has exit < entry (mis-set targets) and price is
    above exit, we should still report SELL ZONE rather than mis-flag."""
    assert compute_status(50.0, 10.0, 40.0) == "SELL ZONE"


# ---- helpers -------------------------------------------------------------


def test_gap_to_entry_positive_when_above_entry():
    assert gap_to_entry_pct(11.0, 10.0) == pytest.approx(10.0)


def test_gap_to_entry_negative_when_below_entry():
    assert gap_to_entry_pct(9.0, 10.0) == pytest.approx(-10.0)


def test_reward_risk_basic():
    # Live 12, entry 10, exit 20: upside 8/12, downside 2/12 -> ratio 4
    assert reward_risk_to_targets(12.0, 10.0, 20.0) == pytest.approx(4.0)


def test_reward_risk_infinite_when_in_buy_zone():
    import math
    rr = reward_risk_to_targets(9.0, 10.0, 20.0)
    assert math.isinf(rr)


# ---- theme mapping -------------------------------------------------------


def test_map_theme_known_keywords():
    assert map_theme("Big Data AI") == "AI / Big Data"
    assert map_theme("Quantum computing") == "Quantum"
    assert map_theme("Bitcoin mining") == "Crypto / Blockchain"
    assert map_theme("Uranium - evs") == "Nuclear / Uranium"
    assert map_theme("EV Charging") == "EV / Battery"
    assert map_theme("Datacentre REIT") == "Real estate / REIT"


def test_map_theme_unknown_defaults_to_other():
    assert map_theme("totally novel sector xyz") == "Other"
    assert map_theme(None) == "Other"
    assert map_theme("") == "Other"


# ---- aggregation helpers -------------------------------------------------


def _sample_view() -> pd.DataFrame:
    return pd.DataFrame([
        {"ticker": "A", "theme": "AI / Big Data", "pct_3m": 30.0,
         "pct_6m": 80.0, "pct_12m": 200.0},
        {"ticker": "B", "theme": "AI / Big Data", "pct_3m": 20.0,
         "pct_6m": 60.0, "pct_12m": 150.0},
        {"ticker": "C", "theme": "Cannabis", "pct_3m": -10.0,
         "pct_6m": -20.0, "pct_12m": -40.0},
        {"ticker": "D", "theme": "Cannabis", "pct_3m": -5.0,
         "pct_6m": float("nan"), "pct_12m": float("nan")},
    ])


def test_theme_heat_ranks_ai_above_cannabis():
    heat = theme_heat(_sample_view())
    assert list(heat["theme"]) == ["AI / Big Data", "Cannabis"]


def test_parabolic_rank_returns_top_n_by_horizon():
    top = parabolic_rank(_sample_view(), horizon="pct_6m", top_n=2)
    assert list(top["ticker"]) == ["A", "B"]


# ---- pick_winners --------------------------------------------------------


def _picks_view() -> pd.DataFrame:
    """View where ticker A is the obvious winner and E is a sell-zone laggard."""
    return pd.DataFrame([
        # In buy zone, hot theme, healthy R:R, momentum building, not parabolic
        {"ticker": "A", "name": "Alpha", "theme": "AI / Big Data",
         "status": "BUY ZONE", "live_price": 9.0, "target_entry": 10.0,
         "target_exit": 20.0, "reward_risk": 3.0,
         "pct_1m": 5.0, "pct_3m": 25.0, "pct_6m": 40.0, "pct_12m": 60.0},
        # Approaching, same hot theme, weaker R:R
        {"ticker": "B", "name": "Beta", "theme": "AI / Big Data",
         "status": "APPROACHING", "live_price": 11.0, "target_entry": 10.0,
         "target_exit": 13.0, "reward_risk": 0.8,
         "pct_1m": 3.0, "pct_3m": 15.0, "pct_6m": 25.0, "pct_12m": 40.0},
        # HOLD, weak theme
        {"ticker": "C", "name": "Gamma", "theme": "Cannabis",
         "status": "HOLD", "live_price": 5.0, "target_entry": 3.0,
         "target_exit": 8.0, "reward_risk": 1.5,
         "pct_1m": -2.0, "pct_3m": -10.0, "pct_6m": -15.0, "pct_12m": -20.0},
        # Parabolic blow-off (6m=250%) — should be penalised
        {"ticker": "D", "name": "Delta", "theme": "AI / Big Data",
         "status": "HOLD", "live_price": 50.0, "target_entry": 20.0,
         "target_exit": 60.0, "reward_risk": 0.5,
         "pct_1m": 30.0, "pct_3m": 120.0, "pct_6m": 250.0, "pct_12m": 400.0},
        # SELL ZONE — should be filtered out by default
        {"ticker": "E", "name": "Epsilon", "theme": "Cannabis",
         "status": "SELL ZONE", "live_price": 30.0, "target_entry": 5.0,
         "target_exit": 25.0, "reward_risk": 0.0,
         "pct_1m": 0.0, "pct_3m": 5.0, "pct_6m": 10.0, "pct_12m": 20.0},
    ])


def test_pick_winners_promotes_buy_zone_with_hot_theme():
    picks = pick_winners(_picks_view(), top_n=5)
    # A wins: BUY ZONE + hot theme + good R:R + non-parabolic
    assert picks.iloc[0]["ticker"] == "A"
    assert picks.iloc[0]["composite"] > picks.iloc[1]["composite"]


def test_pick_winners_excludes_sell_zone_by_default():
    picks = pick_winners(_picks_view(), top_n=10)
    assert "E" not in set(picks["ticker"])


def test_pick_winners_can_include_sell_zone_when_asked():
    picks = pick_winners(_picks_view(), top_n=10, exclude_sell_zone=False)
    assert "E" in set(picks["ticker"])
    # But it should rank near the bottom (analyst score = 0)
    assert int(picks[picks["ticker"] == "E"]["rank"].iloc[0]) >= 3


def test_pick_winners_applies_blowoff_penalty():
    no_penalty = pick_winners(_picks_view(), top_n=10, blowoff_threshold_pct=500.0)
    with_penalty = pick_winners(_picks_view(), top_n=10, blowoff_threshold_pct=100.0)
    d_no = float(no_penalty[no_penalty["ticker"] == "D"]["composite"].iloc[0])
    d_pen = float(with_penalty[with_penalty["ticker"] == "D"]["composite"].iloc[0])
    assert d_no > d_pen


def test_pick_winners_congress_overlay_boosts_score():
    base = pick_winners(_picks_view(), top_n=10)
    boosted = pick_winners(
        _picks_view(), top_n=10,
        congress_overlay={"C": 1.0},  # boost Gamma which would otherwise rank low
    )
    c_base = float(base[base["ticker"] == "C"]["composite"].iloc[0])
    c_boost = float(boosted[boosted["ticker"] == "C"]["composite"].iloc[0])
    assert c_boost > c_base


def test_pick_winners_top_n_limits_output():
    picks = pick_winners(_picks_view(), top_n=2)
    assert len(picks) == 2
    assert list(picks["rank"]) == [1, 2]


def test_pick_winners_empty_view_returns_empty():
    picks = pick_winners(pd.DataFrame())
    assert picks.empty
