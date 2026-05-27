"""Tests for the walk-forward actor-skill scorer."""

from __future__ import annotations

from datetime import date, timedelta

from congress_signal.backtest.engine import EventReturn
from congress_signal.schema import AssetType, Direction, Owner, Trade
from congress_signal.scoring.actor_skill import compute_actor_skill


def _trade(actor: str, ticker: str, day_offset: int, trade_id: str | None = None) -> Trade:
    t = date(2023, 1, 1) + timedelta(days=day_offset)
    return Trade(
        trade_id=trade_id or f"{actor}-{ticker}-{day_offset}",
        actor_id=actor,
        transaction_date=t,
        disclosure_date=t + timedelta(days=10),
        ticker=ticker,
        asset_type=AssetType.STOCK,
        direction=Direction.BUY,
        amount_min_usd=10_000, amount_max_usd=20_000,
        owner=Owner.SELF, source="test",
    )


def _er(trade_id: str, car: float) -> EventReturn:
    return EventReturn(
        trade_id=trade_id,
        ticker="XYZ",
        entry_date=date(2023, 1, 1),
        exit_date=date(2023, 4, 1),
        stock_return=car,
        benchmark_return=0.0,
        car=car,
        car_net_of_slippage=car,
    )


def test_actor_with_no_priors_gets_neutral():
    trades = [_trade("A", "X", 0)]
    out = compute_actor_skill(trades, [_er(trades[0].trade_id, 0.05)])
    score = out[trades[0].trade_id]
    assert score.n_prior_trades == 0
    assert score.skill == 0.5


def test_actor_with_winning_priors_scores_high():
    # 20 priors at 15-day intervals so the [latest - 365d, latest - 90d]
    # window comfortably captures >= 10 of them.
    trades = [
        _trade("A", "X", i * 15, trade_id=f"prior-{i}")
        for i in range(20)
    ]
    latest = _trade("A", "X", 400, trade_id="latest")
    trades.append(latest)
    event_returns = [_er(f"prior-{i}", 0.08) for i in range(20)]
    out = compute_actor_skill(trades, event_returns, min_prior_trades=10)
    assert out["latest"].n_prior_trades >= 10
    assert out["latest"].mean_prior_car > 0.05
    assert out["latest"].skill > 0.7


def test_actor_with_losing_priors_scores_low():
    trades = [_trade("A", "X", i * 15, trade_id=f"prior-{i}") for i in range(20)]
    latest = _trade("A", "X", 400, trade_id="latest")
    trades.append(latest)
    event_returns = [_er(f"prior-{i}", -0.08) for i in range(20)]
    out = compute_actor_skill(trades, event_returns, min_prior_trades=10)
    assert out["latest"].mean_prior_car < -0.05
    assert out["latest"].skill < 0.3


def test_no_lookahead_future_trades_do_not_affect_prior_scores():
    """Trade A at day 0 must not be influenced by a return realised on
    trade B at day 200 — even if both are by the same actor."""
    trades = [
        _trade("A", "X", 0, trade_id="day-0"),
        _trade("A", "X", 200, trade_id="day-200"),
    ]
    event_returns = [
        _er("day-0", 0.0),
        _er("day-200", 0.5),  # future trade, huge return
    ]
    out = compute_actor_skill(trades, event_returns, min_prior_trades=1)
    # The day-0 trade has no priors, so it gets neutral.
    assert out["day-0"].skill == 0.5
    assert out["day-0"].n_prior_trades == 0


def test_priors_outside_lookback_are_excluded():
    """A trade 500 days ago should not count toward a 365-day lookback."""
    trades = [_trade("A", "X", -500, trade_id="old")]
    for i in range(12):
        trades.append(_trade("A", "X", i * 20 - 400, trade_id=f"recent-{i}"))
    latest = _trade("A", "X", 0, trade_id="latest")
    trades.append(latest)
    # Old prior has huge CAR; recent priors are flat.
    ers = [_er("old", 1.0)]
    ers += [_er(f"recent-{i}", 0.0) for i in range(12)]
    out = compute_actor_skill(
        trades, ers,
        lookback_days=365, holding_period_days=90, min_prior_trades=10,
    )
    # Mean should be ~0 (just the recent flat priors), not pulled by the old huge one.
    assert abs(out["latest"].mean_prior_car) < 0.05


def test_priors_within_holding_period_are_excluded():
    """A prior trade made 30 days ago hasn't realised its 90-day CAR yet —
    must be excluded."""
    trades = [
        _trade("A", "X", -30, trade_id="too-recent"),
        _trade("A", "X", 0, trade_id="latest"),
    ]
    ers = [_er("too-recent", 1.0)]  # huge CAR but not yet realised
    out = compute_actor_skill(
        trades, ers,
        holding_period_days=90, min_prior_trades=1,
    )
    # The too-recent trade should not contribute, so latest gets neutral.
    assert out["latest"].n_prior_trades == 0
    assert out["latest"].skill == 0.5
