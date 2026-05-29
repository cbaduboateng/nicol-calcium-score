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
