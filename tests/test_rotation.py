"""Tests for the momentum rotation backtest (pre-registered experiment)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from icarus.rotation import (
    buy_and_hold_monthly,
    compare_rotation,
    equal_weight_monthly,
    momentum_rotation_backtest,
    rotation_verdict,
)


def _frame(n_days: int = 800, seed_trend: float = 0.001) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n_days, freq="B")
    up = 100 * np.cumprod(np.full(n_days, 1.0 + seed_trend))      # strong
    flat = np.full(n_days, 100.0)                                  # flat
    down = 100 * np.cumprod(np.full(n_days, 1.0 - seed_trend))     # weak
    return pd.DataFrame({"UP": up, "FLAT": flat, "DOWN": down}, index=idx)


def test_rotation_holds_the_trending_asset():
    px = _frame()
    r = momentum_rotation_backtest(px, lookback_days=126, top_k=1,
                                   cost_pct=0.0)
    assert not r.empty
    # Once eligible, top-1 rotation should ride UP: mean monthly ≈ UP's
    # steady monthly gain (~+2.1%), certainly positive.
    assert r.mean() > 0.015


def test_costs_reduce_returns_only_on_turnover():
    px = _frame()
    free = momentum_rotation_backtest(px, lookback_days=126, top_k=1,
                                      cost_pct=0.0)
    costly = momentum_rotation_backtest(px, lookback_days=126, top_k=1,
                                        cost_pct=0.50)
    # Stable winner -> turnover only on the first month; totals nearly equal.
    assert costly.sum() <= free.sum()
    assert free.sum() - costly.sum() < 0.02


def test_buy_and_hold_and_equal_weight_controls():
    px = _frame()
    bh = buy_and_hold_monthly(px, "UP")
    assert bh.mean() > 0
    ew = equal_weight_monthly(px, cost_pct=0.0)
    # Equal weight of up/flat/down ≈ a third of UP's drift.
    assert 0 < ew.mean() < bh.mean()
    assert buy_and_hold_monthly(px, "MISSING").empty


def test_compare_has_controls_and_variants():
    px = _frame()
    table = compare_rotation(px, spy_ticker="FLAT")
    names = list(table["variant"])
    assert any(n.startswith("control: FLAT") for n in names)
    assert any("equal weight" in n for n in names)
    assert sum(n.startswith("rotation:") for n in names) == 4
    for col in ("mean_monthly_pct", "cagr_pct", "max_drawdown_pct",
                "mean_first_pct", "mean_second_pct"):
        assert col in table.columns


def test_verdict_bar_requires_both_halves_and_sample():
    table = pd.DataFrame([
        {"variant": "control: SPY buy & hold", "mean_first_pct": 0.5,
         "mean_second_pct": 0.8, "n_first": 60, "n_second": 60},
        {"variant": "rotation: winner", "mean_first_pct": 1.0,
         "mean_second_pct": 1.1, "n_first": 60, "n_second": 60},
        {"variant": "rotation: half-winner", "mean_first_pct": 1.2,
         "mean_second_pct": 0.4, "n_first": 60, "n_second": 60},
        {"variant": "rotation: thin", "mean_first_pct": 2.0,
         "mean_second_pct": 2.0, "n_first": 10, "n_second": 10},
    ])
    passing = rotation_verdict(table)
    assert list(passing["variant"]) == ["rotation: winner"]


def test_empty_inputs():
    assert momentum_rotation_backtest(pd.DataFrame()).empty
    assert compare_rotation(pd.DataFrame()).empty
