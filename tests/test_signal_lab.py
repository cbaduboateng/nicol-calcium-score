"""Tests for the Signal Lab comparison backtest."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.signal_lab import (
    DEFAULT_VARIANTS,
    SignalVariant,
    compare_variants,
    run_variant,
)


def _series(vals: list[float], start: str = "2025-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(vals), freq="D")
    return pd.Series(vals, index=idx)


def _watchlist(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


ROW = {"ticker": "WIN", "name": "Winner", "description": "AI play",
       "target_entry": 10.0, "target_exit": 25.0}


def _rise_dip_rally() -> pd.Series:
    """150 rising days (steep enough that momentum is positive at every
    lookback window even after the dip), dip into the zone, rally to the
    target. With a 63-day lookback the pre-dip reference is ~9.1, so the
    9.9 crossing still shows ~+9% momentum."""
    ramp = list(np.linspace(5.0, 12.0, 150))
    return _series(ramp + [9.9] + list(np.linspace(10.5, 26.0, 30)))


def _early_dip_rally() -> pd.Series:
    """Only ~30 sessions of history before the crossing: the 1m momentum
    window can evaluate it, but 3m/6m windows can't (NaN -> gated out)."""
    ramp = list(np.linspace(8.0, 12.0, 30))
    return _series(ramp + [9.9] + list(np.linspace(10.5, 26.0, 30)))


def test_control_counts_at_least_as_many_signals_as_gated():
    hist = {"WIN": _rise_dip_rally()}
    wl = _watchlist([ROW])
    control = run_variant(wl, hist, DEFAULT_VARIANTS[0])
    gated = run_variant(wl, hist, DEFAULT_VARIANTS[1])
    assert len(control) >= len(gated)
    assert len(control) >= 1


def test_fast_window_catches_signals_slow_windows_miss():
    hist = {"EARLY": _early_dip_rally()}
    wl = _watchlist([dict(ROW, ticker="EARLY")])
    fast = run_variant(wl, hist, SignalVariant("fast", momentum_days=21))
    slow = run_variant(wl, hist, SignalVariant("slow", momentum_days=126))
    assert len(fast) >= 1       # 1m momentum computable and positive
    assert len(slow) == 0       # 6m window has no data -> gated out


def test_momentum_gate_blocks_downtrending_crossings():
    # Price declines the whole way into the zone: momentum negative.
    hist = {"KNIFE": _series(list(np.linspace(15.0, 9.9, 150)))}
    wl = _watchlist([dict(ROW, ticker="KNIFE")])
    gated = run_variant(wl, hist, SignalVariant("gated"))
    control = run_variant(wl, hist, SignalVariant(
        "control", require_positive_momentum=False,
        require_positive_theme=False, min_rr=0.0,
    ))
    assert len(gated) == 0
    assert len(control) >= 1


def test_rr_gate_requires_exit_target():
    hist = {"NOEXIT": _rise_dip_rally()}
    row = dict(ROW, ticker="NOEXIT", target_exit=float("nan"))
    wl = _watchlist([row])
    with_rr = run_variant(wl, hist, SignalVariant("rr", min_rr=3.0))
    no_rr = run_variant(wl, hist, SignalVariant(
        "norr", min_rr=0.0, require_positive_theme=False,
    ))
    assert len(with_rr) == 0    # no exit -> can't compute R:R -> gated
    assert len(no_rr) >= 1


def test_compare_variants_produces_one_row_per_variant():
    hist = {"WIN": _rise_dip_rally()}
    wl = _watchlist([ROW])
    table = compare_variants(wl, hist)
    assert len(table) == len(DEFAULT_VARIANTS)
    assert set(table["variant"]) == {v.name for v in DEFAULT_VARIANTS}
    # The control fires and closes at the target -> positive avg return.
    control_row = table[table["variant"] == "control: every crossing"].iloc[0]
    assert control_row["n_signals"] >= 1
    assert control_row["avg_return_pct"] > 0


def test_walk_forward_split_counts_sum_to_total():
    hist = {"WIN": _rise_dip_rally()}
    wl = _watchlist([ROW])
    table = compare_variants(wl, hist)
    for _, r in table.iterrows():
        assert r["n_train"] + r["n_test"] == r["n_signals"]


# ---- exit-policy variants -------------------------------------------------


def _exit_sig(entry=10.0, d="2025-06-01", exit_=25.0):
    return {"signal_date": pd.Timestamp(d), "entry_price": entry,
            "target_exit": exit_, "ticker": "T"}


def test_exit_wide_stop_survives_a_shakeout_the_tight_stop_sells():
    from icarus.signal_lab import ExitVariant, _mark_forward_exit
    # Dips to -12% then rallies to the target.
    vals = [10.0, 9.4, 8.8, 9.5, 12.0, 20.0, 26.0]
    s = _series(vals, start="2025-06-01")
    sig = _exit_sig()
    tight = _mark_forward_exit(s, None, sig, ExitVariant("t", stop_pct=0.10))
    wide = _mark_forward_exit(s, None, sig, ExitVariant("w", stop_pct=0.20))
    assert tight["close_reason"] == "stop" and tight["return_pct"] < 0
    assert wide["close_reason"] == "target" and wide["return_pct"] > 100


def test_exit_trailing_sells_the_rollover():
    from icarus.signal_lab import ExitVariant, _mark_forward_exit
    # Rally then roll over WITHOUT hitting the -10% stop or the target.
    vals = [10.0] + list(np.linspace(10.5, 18.0, 25)) + list(np.linspace(17.5, 12.0, 10))
    s = _series(vals, start="2025-06-01")
    roll = s.rolling(5).min().shift(1)
    v = ExitVariant("trail", trail_low_days=5)
    m = _mark_forward_exit(s, roll, _exit_sig(), v)
    assert m["close_reason"] == "trail"
    assert m["return_pct"] > 0   # sold on the way down, still green


def test_exit_take_half_blends_the_return():
    from icarus.signal_lab import ExitVariant, _mark_forward_exit
    # Runs to +40% then collapses to the stop.
    vals = [10.0, 12.0, 14.0, 12.0, 10.0, 8.9]
    s = _series(vals, start="2025-06-01")
    v = ExitVariant("half", take_half_at_pct=30.0)
    m = _mark_forward_exit(s, None, _exit_sig(), v)
    assert m["close_reason"] == "stop"
    # Half locked at +30, half stopped at -11: blended positive-ish
    assert m["return_pct"] == pytest.approx(0.5 * 30.0 + 0.5 * (-11.0), abs=0.5)


def test_exit_longer_timeout_holds_longer():
    from icarus.signal_lab import ExitVariant, _mark_forward_exit
    vals = [10.0] + [10.5] * 400   # drifts forever inside the band
    s = _series(vals, start="2025-01-01")
    six = _mark_forward_exit(s, None, _exit_sig(d="2025-01-01"), ExitVariant("6m"))
    twelve = _mark_forward_exit(
        s, None, _exit_sig(d="2025-01-01"), ExitVariant("12m", timeout_days=365),
    )
    assert six["close_reason"] == "timeout" and six["days_held"] <= 185
    assert twelve["days_held"] > six["days_held"]


def test_exit_trend_only_rides_past_the_target():
    from icarus.signal_lab import ExitVariant, _mark_forward_exit
    # Steady rally far beyond the 25 target; trend variant keeps riding.
    vals = [10.0] + list(np.linspace(10.5, 60.0, 60))
    s = _series(vals, start="2025-06-01")
    roll = s.rolling(20).min().shift(1)
    with_target = _mark_forward_exit(s, None, _exit_sig(), ExitVariant("t"))
    trend = _mark_forward_exit(
        s, roll, _exit_sig(),
        ExitVariant("trend", trail_low_days=20, use_target=False, timeout_days=365),
    )
    assert with_target["close_reason"] == "target"
    assert trend["return_pct"] > with_target["return_pct"]


def test_compare_exit_variants_one_row_per_policy():
    from icarus.signal_lab import DEFAULT_EXIT_VARIANTS, compare_exit_variants
    hist = {"WIN": _rise_dip_rally()}
    wl = _watchlist([ROW])
    table = compare_exit_variants(wl, hist)
    assert not table.empty
    assert set(table["variant"]) <= {v.name for v in DEFAULT_EXIT_VARIANTS}
    for _, r in table.iterrows():
        assert r["n_train"] + r["n_test"] == r["n_signals"]


def test_empty_inputs_are_graceful():
    assert run_variant(pd.DataFrame(), {}, DEFAULT_VARIANTS[0]).empty
    assert compare_variants(pd.DataFrame(), {}).empty
