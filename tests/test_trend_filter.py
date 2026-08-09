"""Tests for the absolute-momentum trend filter experiment."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.trend_filter import (
    DEFAULT_TREND_VARIANTS,
    TrendVariant,
    compare_trend_filters,
    trend_filter_monthly,
    trend_verdict,
)


def _series(vals: np.ndarray, start: str = "2018-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(vals), freq="B")
    return pd.Series(vals, index=idx)


def _boom_bust(n: int = 1400) -> pd.Series:
    """Long rise, then a -50% crash over ~6 months, then recovery."""
    up = 100 * np.cumprod(np.full(600, 1.001))
    crash = up[-1] * np.cumprod(np.full(130, 0.9947))   # ~-50%
    recover = crash[-1] * np.cumprod(np.full(n - 730, 1.0012))
    return _series(np.concatenate([up, crash, recover]))


def test_filter_sidesteps_most_of_the_crash():
    px = _boom_bust()
    v = TrendVariant("sma10", "sma_months", 10)
    r = trend_filter_monthly(px, v, cost_pct=0.0)
    eq = (1.0 + r).cumprod()
    dd_filtered = float((eq / eq.cummax() - 1.0).min())
    me_bh = px.pct_change().dropna()
    # Buy-and-hold suffers ~-50%; the filter should suffer far less.
    assert dd_filtered > -0.30


def test_filter_stays_invested_in_a_straight_uptrend():
    px = _series(100 * np.cumprod(np.full(900, 1.0008)))
    v = TrendVariant("sma200", "sma_days", 200)
    r = trend_filter_monthly(px, v, cost_pct=0.0)
    assert not r.empty
    assert (r != 0).mean() > 0.95           # in the market ~always
    assert r.sum() > 0


def test_switch_costs_only_on_transitions():
    px = _series(100 * np.cumprod(np.full(900, 1.0008)))
    v = TrendVariant("sma200", "sma_days", 200)
    free = trend_filter_monthly(px, v, cost_pct=0.0)
    costly = trend_filter_monthly(px, v, cost_pct=0.5)
    # One entry transition only -> totals differ by ~one cost charge.
    assert free.sum() - costly.sum() == pytest.approx(0.005, abs=1e-6)


def test_compare_and_columns():
    px = _boom_bust()
    t = compare_trend_filters(px)
    assert list(t["variant"])[0] == "control: buy & hold"
    assert len(t) == 1 + len(DEFAULT_TREND_VARIANTS)
    for col in ("cagr_pct", "max_drawdown_pct", "dd_first_pct",
                "cagr_second_pct", "pct_in_market"):
        assert col in t.columns


def test_defensive_verdict_bar():
    t = pd.DataFrame([
        {"variant": "control: buy & hold", "n_first": 60, "n_second": 60,
         "cagr_first_pct": 10.0, "cagr_second_pct": 10.0,
         "dd_first_pct": -40.0, "dd_second_pct": -40.0},
        {"variant": "filter: good", "n_first": 60, "n_second": 60,
         "cagr_first_pct": 9.0, "cagr_second_pct": 8.5,
         "dd_first_pct": -20.0, "dd_second_pct": -25.0},
        {"variant": "filter: costly protection", "n_first": 60, "n_second": 60,
         "cagr_first_pct": 4.0, "cagr_second_pct": 9.0,
         "dd_first_pct": -15.0, "dd_second_pct": -15.0},
        {"variant": "filter: shallow help", "n_first": 60, "n_second": 60,
         "cagr_first_pct": 10.0, "cagr_second_pct": 10.0,
         "dd_first_pct": -35.0, "dd_second_pct": -38.0},
    ])
    passing = trend_verdict(t)
    assert list(passing["variant"]) == ["filter: good"]


def test_empty_inputs():
    assert trend_filter_monthly(pd.Series(dtype=float),
                                DEFAULT_TREND_VARIANTS[0]).empty
    assert compare_trend_filters(pd.Series(dtype=float)).empty
