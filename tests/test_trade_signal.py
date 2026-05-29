from __future__ import annotations

from datetime import date, timedelta

from icarus.schema import Actor, AssetType, Chamber, Direction, Owner, Trade
from icarus.scoring.trade_signal import score_trades


def _stock(actor_id: str, amount: float, lag_days: int = 30) -> Trade:
    txn = date.today() - timedelta(days=60)
    return Trade(
        trade_id=f"t-{actor_id}-{amount}-{lag_days}",
        actor_id=actor_id,
        transaction_date=txn,
        disclosure_date=txn + timedelta(days=lag_days),
        ticker="LMT",
        asset_type=AssetType.STOCK,
        direction=Direction.BUY,
        amount_min_usd=amount, amount_max_usd=amount,
        owner=Owner.SELF, source="test",
    )


def test_option_trade_outscores_stock_trade():
    actor = Actor(actor_id="A", name="A", chamber=Chamber.HOUSE)
    txn = date.today() - timedelta(days=30)
    stock = _stock("A", 50_000.0)
    option = Trade(
        trade_id="opt", actor_id="A",
        transaction_date=txn, disclosure_date=txn + timedelta(days=10),
        ticker="LMT", asset_type=AssetType.CALL, direction=Direction.BUY,
        amount_min_usd=50_000.0, amount_max_usd=50_000.0,
        option_strike=600.0, option_expiry=txn + timedelta(days=400),
        option_type=AssetType.CALL,
        owner=Owner.SELF, source="test",
    )
    signals = {s.trade_id: s for s in score_trades([stock, option], [actor])}
    assert signals["opt"].raw_score > signals[stock.trade_id].raw_score


def test_faster_disclosure_outscores_slow():
    actor = Actor(actor_id="A", name="A", chamber=Chamber.HOUSE)
    slow = _stock("A", 50_000.0, lag_days=40)
    fast = _stock("A", 50_000.0, lag_days=5)
    signals = {s.trade_id: s for s in score_trades([slow, fast], [actor])}
    assert signals[fast.trade_id].raw_score > signals[slow.trade_id].raw_score


def test_committee_jurisdiction_raises_score():
    base = Actor(actor_id="A", name="A", chamber=Chamber.HOUSE)
    on_committee = Actor(
        actor_id="B", name="B", chamber=Chamber.HOUSE,
        committees=("House Armed Services",),
    )
    trades = [_stock("A", 50_000.0), _stock("B", 50_000.0)]
    signals = {s.trade_id: s for s in score_trades(trades, [base, on_committee])}
    assert signals[trades[1].trade_id].raw_score > signals[trades[0].trade_id].raw_score
