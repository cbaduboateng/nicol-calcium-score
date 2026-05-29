from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from icarus.schema import AssetType, Direction, Owner, Trade
from icarus.scoring.residual import compute_residuals


def _trade(ticker: str) -> Trade:
    txn = date(2024, 6, 1)
    return Trade(
        trade_id=f"t-{ticker}",
        actor_id="A", transaction_date=txn,
        disclosure_date=txn + timedelta(days=10),
        ticker=ticker, asset_type=AssetType.STOCK, direction=Direction.BUY,
        amount_min_usd=10_000.0, amount_max_usd=20_000.0,
        owner=Owner.SELF, source="test",
    )


def _prices(start: date, end: date, by_ticker: dict[str, list[float]]) -> pd.DataFrame:
    idx = pd.bdate_range(start, end)
    arr = {ticker: prices[: len(idx)] for ticker, prices in by_ticker.items()}
    return pd.DataFrame(arr, index=idx)


def test_catalyst_fires_when_price_moved_a_lot():
    prices = _prices(date(2024, 5, 1), date(2024, 8, 1), {
        "LMT": [400.0 + i * 2 for i in range(70)],
    })
    [verdict] = compute_residuals([_trade("LMT")], prices, catalyst_threshold_pct=5.0)
    assert verdict.catalyst_fired
    assert not verdict.residual_opportunity


def test_residual_opportunity_when_price_flat():
    prices = _prices(date(2024, 5, 1), date(2024, 8, 1), {"LMT": [400.0] * 70})
    [verdict] = compute_residuals([_trade("LMT")], prices, catalyst_threshold_pct=5.0)
    assert not verdict.catalyst_fired
    assert verdict.residual_opportunity


def test_missing_ticker_yields_neutral_verdict():
    prices = _prices(date(2024, 5, 1), date(2024, 8, 1), {"OTHER": [100.0] * 70})
    [verdict] = compute_residuals([_trade("LMT")], prices)
    assert not verdict.catalyst_fired
    assert not verdict.residual_opportunity
