"""Monotonicity tests for the momentum scoring layer."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from icarus.scoring.momentum import score_momentum


def _make_prices(start: str, end: str, returns: dict[str, float]) -> pd.DataFrame:
    """Build a daily price frame with constant daily return per ticker."""
    idx = pd.bdate_range(start, end)
    data = {}
    for ticker, daily_ret in returns.items():
        path = 100.0 * np.cumprod(1 + np.full(len(idx), daily_ret))
        data[ticker] = path
    return pd.DataFrame(data, index=idx)


def test_strong_uptrend_scores_above_neutral():
    prices = _make_prices("2023-01-01", "2024-08-01", {"UP": 0.001})  # ~28%/yr
    score = score_momentum(prices, ticker="UP", as_of=date(2024, 6, 1))
    assert score.score > 0.5
    assert score.raw_return > 0


def test_strong_downtrend_scores_below_neutral():
    prices = _make_prices("2023-01-01", "2024-08-01", {"DN": -0.001})
    score = score_momentum(prices, ticker="DN", as_of=date(2024, 6, 1))
    assert score.score < 0.5
    assert score.raw_return < 0


def test_unknown_ticker_returns_neutral():
    prices = _make_prices("2023-01-01", "2024-08-01", {"OTHER": 0.001})
    score = score_momentum(prices, ticker="UP", as_of=date(2024, 6, 1))
    assert score.score == 0.5


def test_steeper_uptrend_scores_higher_than_milder():
    prices = _make_prices("2023-01-01", "2024-08-01", {
        "MILD": 0.0003, "STRONG": 0.002,
    })
    mild = score_momentum(prices, ticker="MILD", as_of=date(2024, 6, 1))
    strong = score_momentum(prices, ticker="STRONG", as_of=date(2024, 6, 1))
    assert strong.score > mild.score
