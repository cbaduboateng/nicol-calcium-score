"""Tests for the analyst target-pattern learner and applier."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.target_inference import (
    derive_targets,
    describe_pattern,
    learn_target_pattern,
)


def _flat_series(level: float, n: int = 250) -> pd.Series:
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.Series([level] * n, index=idx)


def _range_series(low: float, high: float, n: int = 250) -> pd.Series:
    """Rises low→high then settles at the midpoint: 52w low/high are
    distinct from the live price, so anchors are distinguishable."""
    ramp = list(np.linspace(low, high, n - 50))
    tail = [(low + high) / 2] * 50
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.Series(ramp + tail, index=idx)


def _watchlist_consistent_low52(n: int = 25) -> tuple[pd.DataFrame, dict]:
    """Entries set at exactly 1.2x the 52w low — tight around low52,
    noisy vs live/high. Exits at 2x entry."""
    rows, hist = [], {}
    rng = np.random.default_rng(7)
    for i in range(n):
        t = f"T{i:03d}"
        low = float(rng.uniform(5, 50))
        high = low * float(rng.uniform(2.0, 6.0))  # varying range widths
        hist[t] = _range_series(low, high)
        entry = round(low * 1.2, 2)
        rows.append({
            "ticker": t, "name": t, "description": "AI play",
            "target_entry": entry, "target_exit": round(entry * 2.0, 2),
        })
    return pd.DataFrame(rows), hist


def test_learns_low52_anchor_when_entries_track_the_low():
    wl, hist = _watchlist_consistent_low52()
    p = learn_target_pattern(wl, hist)
    assert p is not None
    assert p["anchor"] == "low52"
    assert p["entry_ratio"] == pytest.approx(1.2, abs=0.05)
    assert p["exit_multiple"] == pytest.approx(2.0, abs=0.05)
    assert p["n_entry"] == 25


def test_refuses_to_learn_from_tiny_sample():
    wl, hist = _watchlist_consistent_low52(n=5)
    assert learn_target_pattern(wl, hist) is None


def test_derive_fills_blanks_and_flags_provenance():
    wl, hist = _watchlist_consistent_low52()
    # Add two rows without targets: one with history, one without.
    blank_with_hist = {"ticker": "NEW1", "name": "New", "description": "AI play",
                       "target_entry": float("nan"), "target_exit": float("nan")}
    blank_no_hist = {"ticker": "NEW2", "name": "New2", "description": "AI play",
                     "target_entry": float("nan"), "target_exit": float("nan")}
    wl = pd.concat([wl, pd.DataFrame([blank_with_hist, blank_no_hist])],
                   ignore_index=True)
    hist["NEW1"] = _range_series(10.0, 40.0)

    p = learn_target_pattern(wl, hist)
    out = derive_targets(wl, hist, p)

    new1 = out[out["ticker"] == "NEW1"].iloc[0]
    assert new1["entry_source"] == "derived"
    assert new1["exit_source"] == "derived"
    # low52=10, ratio≈1.2 → entry ≈ 12; exit ≈ 24
    assert new1["target_entry"] == pytest.approx(12.0, rel=0.1)
    assert new1["target_exit"] == pytest.approx(24.0, rel=0.15)

    new2 = out[out["ticker"] == "NEW2"].iloc[0]
    assert pd.isna(new2["target_entry"])  # no history → nothing derivable
    assert pd.isna(new2["entry_source"])  # None/NaN both mean 'no source'


def test_derive_never_touches_analyst_values():
    wl, hist = _watchlist_consistent_low52()
    p = learn_target_pattern(wl, hist)
    out = derive_targets(wl, hist, p)
    orig = wl.set_index("ticker")
    for _, row in out.iterrows():
        t = row["ticker"]
        assert row["target_entry"] == orig.at[t, "target_entry"]
        assert row["target_exit"] == orig.at[t, "target_exit"]
        assert row["entry_source"] == "analyst"
        assert row["exit_source"] == "analyst"


def test_derive_fills_missing_exit_from_analyst_entry():
    wl, hist = _watchlist_consistent_low52()
    # A row with an analyst entry but no exit
    extra = {"ticker": "HALFSET", "name": "Half", "description": "AI play",
             "target_entry": 15.0, "target_exit": float("nan")}
    wl = pd.concat([wl, pd.DataFrame([extra])], ignore_index=True)
    hist["HALFSET"] = _range_series(12.0, 30.0)
    p = learn_target_pattern(wl, hist)
    out = derive_targets(wl, hist, p)
    half = out[out["ticker"] == "HALFSET"].iloc[0]
    assert half["entry_source"] == "analyst"
    assert half["exit_source"] == "derived"
    assert half["target_exit"] == pytest.approx(30.0, rel=0.1)  # 15 × 2.0


def test_absurd_multiples_excluded_from_learning():
    wl, hist = _watchlist_consistent_low52()
    # Poison one row with exit < entry (mis-set) — learner should ignore it.
    wl.loc[0, "target_exit"] = wl.loc[0, "target_entry"] * 0.3
    p = learn_target_pattern(wl, hist)
    assert p["exit_multiple"] == pytest.approx(2.0, abs=0.05)


def test_derive_exits_from_entries_uses_analyst_median_multiple():
    from icarus.target_inference import derive_exits_from_entries
    wl = pd.DataFrame([
        {"ticker": "A", "target_entry": 10.0, "target_exit": 25.0},   # 2.5x
        {"ticker": "B", "target_entry": 20.0, "target_exit": 50.0},   # 2.5x
        {"ticker": "C", "target_entry": 8.0, "target_exit": float("nan")},
        {"ticker": "D", "target_entry": float("nan"), "target_exit": float("nan")},
    ])
    filled, mult = derive_exits_from_entries(wl)
    assert mult == pytest.approx(2.5)
    c = filled[filled["ticker"] == "C"].iloc[0]
    assert c["target_exit"] == pytest.approx(20.0)   # 8 × 2.5
    assert c["exit_source"] == "derived"
    # Analyst exits untouched, no-entry rows untouched
    assert filled[filled["ticker"] == "A"].iloc[0]["target_exit"] == 25.0
    assert filled[filled["ticker"] == "A"].iloc[0]["exit_source"] == "analyst"
    assert pd.isna(filled[filled["ticker"] == "D"].iloc[0]["target_exit"])


def test_derive_exits_excludes_mis_set_multiples():
    from icarus.target_inference import derive_exits_from_entries
    wl = pd.DataFrame([
        {"ticker": "A", "target_entry": 10.0, "target_exit": 20.0},   # 2.0x
        {"ticker": "B", "target_entry": 10.0, "target_exit": 3.0},    # 0.3x mis-set
        {"ticker": "C", "target_entry": 10.0, "target_exit": float("nan")},
    ])
    filled, mult = derive_exits_from_entries(wl)
    assert mult == pytest.approx(2.0)   # the 0.3x row is excluded


def test_derive_exits_falls_back_to_default_when_no_pairs():
    from icarus.target_inference import (
        DEFAULT_EXIT_MULTIPLE,
        derive_exits_from_entries,
    )
    wl = pd.DataFrame([
        {"ticker": "A", "target_entry": 10.0, "target_exit": float("nan")},
    ])
    filled, mult = derive_exits_from_entries(wl)
    assert mult == DEFAULT_EXIT_MULTIPLE
    assert filled.iloc[0]["target_exit"] == pytest.approx(10.0 * DEFAULT_EXIT_MULTIPLE)


def test_describe_pattern_is_human_readable():
    wl, hist = _watchlist_consistent_low52()
    p = learn_target_pattern(wl, hist)
    text = describe_pattern(p)
    assert "52-week low" in text
    assert "2.0×" in text


# ---- target staleness ------------------------------------------------------


def _px(vals, start="2025-06-01"):
    idx = pd.date_range(start, periods=len(vals), freq="D")
    return pd.Series(vals, index=idx)


def test_stale_when_price_never_neared_the_zone():
    from icarus.target_inference import flag_stale_targets
    view = pd.DataFrame([
        {"ticker": "FAR", "target_entry": 10.0},    # price lived at ~30
        {"ticker": "NEAR", "target_entry": 10.0},   # dips toward the zone
        {"ticker": "NOTGT", "target_entry": float("nan")},
    ])
    hist = {
        "FAR": _px([30.0] * 200),
        "NEAR": _px([30.0] * 100 + [12.0] * 100),   # within 50% band recently
    }
    out = flag_stale_targets(view, hist, lookback_sessions=126)
    by = out.set_index("ticker")["target_stale"]
    assert bool(by["FAR"]) is True
    assert bool(by["NEAR"]) is False
    assert bool(by["NOTGT"]) is False


def test_not_stale_without_enough_history():
    from icarus.target_inference import flag_stale_targets
    view = pd.DataFrame([{"ticker": "NEWCO", "target_entry": 10.0}])
    out = flag_stale_targets(view, {"NEWCO": _px([30.0] * 40)})
    assert bool(out.iloc[0]["target_stale"]) is False  # benefit of the doubt
