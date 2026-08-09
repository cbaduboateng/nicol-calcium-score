"""Tests for the hypothesis ledger, position sizer and luck detector."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.hypotheses import (
    VALID_STATUSES,
    ledger_summary,
    load_hypotheses,
)
from icarus.portfolio import position_size
from icarus.track_record import summarise_track_record


def test_ledger_loads_and_all_statuses_valid():
    df = load_hypotheses()
    assert not df.empty
    assert set(df["status"]) <= VALID_STATUSES
    # The ledger must contain the project's famous kills and wins.
    ids = set(df["id"])
    assert {"congress-trades", "stop-20pct", "swing-oversold-etfs",
            "swing-dip-buying", "dynamic-entries"} <= ids
    counts = ledger_summary(df)
    assert counts.get("rejected", 0) >= 5     # kills are the point


def test_ledger_missing_file_graceful(tmp_path):
    df = load_hypotheses(tmp_path / "nope.csv")
    assert df.empty and list(df.columns)


def test_position_size_two_percent_rule():
    # £5k account, 2% risk (=£100), entry 10, stop 8 (20%): 50 shares,
    # £500 position = 10% of account.
    sz = position_size(5000, 2.0, 10.0, 8.0)
    assert sz["qty"] == pytest.approx(50.0)
    assert sz["position_value"] == pytest.approx(500.0)
    assert sz["risk_amount"] == pytest.approx(100.0)
    assert sz["pct_of_account"] == pytest.approx(10.0)


def test_position_size_never_levers_past_account():
    # Tiny stop distance would imply a levered position; clamp to 100%.
    sz = position_size(1000, 2.0, 10.0, 9.99)
    assert sz["position_value"] == pytest.approx(1000.0)
    assert sz["pct_of_account"] == pytest.approx(100.0)


def test_position_size_rejects_bad_inputs():
    assert position_size(0, 2, 10, 8)["qty"] == 0
    assert position_size(1000, 2, 10, 11)["qty"] == 0    # stop above entry
    assert position_size(1000, 0, 10, 8)["qty"] == 0


def _closed(returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "return_pct": returns,
        "open": [False] * len(returns),
        "close_reason": ["timeout"] * len(returns),
        "days_held": [30] * len(returns),
    })


def test_top3_share_flags_lottery_profile():
    # One +300% moonshot among small losers: top-3 share = 100%.
    s = summarise_track_record(_closed([300.0, -5.0, -4.0, -6.0, -3.0]))
    assert s["top3_pnl_share_pct"] == pytest.approx(100.0)


def test_top3_share_low_when_wins_are_spread():
    s = summarise_track_record(_closed([10.0] * 10))
    assert s["top3_pnl_share_pct"] == pytest.approx(30.0)


def test_top3_share_nan_without_winners():
    s = summarise_track_record(_closed([-1.0, -2.0]))
    assert np.isnan(s["top3_pnl_share_pct"])
