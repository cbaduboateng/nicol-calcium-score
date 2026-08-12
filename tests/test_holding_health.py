"""Tests for the holdings health card (informs, never exits)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.holding_health import assess_holding, scan_falsifier_headlines


def _series(vals, start="2025-06-01"):
    idx = pd.date_range(start, periods=len(vals), freq="B")
    return pd.Series(vals, index=idx)


def test_falsifier_scan_catches_the_killers():
    tags = scan_falsifier_headlines([
        "XYZ announces $25M registered direct offering",
        "Auditor flags going concern doubt for XYZ",
        "XYZ receives Nasdaq non-compliance notice",
        "XYZ beats earnings estimates",           # benign
    ])
    assert "dilution" in tags
    assert "going-concern" in tags
    assert "listing-compliance" in tags
    assert len(tags) == 3


def test_falsifier_scan_clean_headlines():
    assert scan_falsifier_headlines(["Q2 revenue up 40%", "New contract win"]) == []
    assert scan_falsifier_headlines([]) == []


def test_assess_holding_card_contents():
    hist = _series(list(np.linspace(1.0, 1.5, 200)))
    card = assess_holding(
        "aqb", {"avg_cost": 1.36}, hist, stop_price=1.09,
        falsifiers={"AQB": {"tags": ["dilution"], "sample": "Offering priced"}},
    )
    assert card["ticker"] == "AQB"
    assert card["pnl_pct"] == pytest.approx((1.5 / 1.36 - 1) * 100, abs=0.5)
    assert card["stop_distance_pct"] > 0
    assert card["momentum_6m"] > 0
    assert card["falsifier_tags"] == ["dilution"]
    assert "🚨" in card["line"] and "context only" in card["line"]
    # Charter: the card never contains a sell instruction
    assert "sell" not in card["line"].lower()


def test_assess_holding_no_data():
    card = assess_holding("XXX", {"avg_cost": 0}, None)
    assert card["line"] == "no data"
