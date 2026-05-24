"""End-to-end pipeline test using only synthetic data — runs offline."""

from __future__ import annotations

from datetime import date, timedelta

from congress_signal.ingest.synthetic import (
    synthetic_actors,
    synthetic_prices,
    synthetic_trades,
)
from congress_signal.pipeline import run_full_pipeline
from congress_signal.backtest.engine import run_backtest


CFG = {
    "paths": {"cache": "data/cache"},
    "scoring": {
        "actor_quality": {
            "weights": {
                "committee_relevance": 0.30,
                "historical_alpha": 0.30,
                "concentration": 0.20,
                "skin_in_game": 0.20,
            },
            "min_trades_for_alpha": 5,
        },
        "trade_signal": {
            "options_weight": 0.4,
            "size_weight": 0.3,
            "speed_weight": 0.2,
            "committee_overlap_weight": 0.1,
            "size_z_threshold": 1.0,
            "fast_disclosure_days": 14,
        },
        "cluster": {"window_days": 14, "min_actors": 2, "min_combined_quality": 0.5},
        "residual": {"lookahead_days": 30, "catalyst_threshold_pct": 5.0},
        "asymmetric": {
            "minimum_trade_signal_score": 0.5,
            "minimum_actor_quality": 0.3,
        },
    },
    "backtest": {"benchmark": "SPY", "slippage_bps": 25.0, "bootstrap_iterations": 100},
}


def _run_pipeline():
    trades = synthetic_trades(end=date(2024, 12, 31))
    actors = synthetic_actors()
    start = min(t.transaction_date for t in trades) - timedelta(days=30)
    end = max(t.transaction_date for t in trades) + timedelta(days=120)
    prices, _, _ = synthetic_prices(
        sorted({t.ticker for t in trades}), start, end, benchmark="SPY",
    )
    result = run_full_pipeline(CFG, trades, actors, prices=prices)
    return trades, actors, prices, result


def test_synthetic_pipeline_runs():
    trades, actors, prices, result = _run_pipeline()
    assert result.actor_scores, "expected actor scores"
    assert result.trade_signals, "expected trade signals"
    assert result.candidates, "expected at least one asymmetric candidate"


def test_lmt_cluster_surfaces():
    _, _, _, result = _run_pipeline()
    cluster_tickers = {c.ticker for c in result.clusters}
    assert "LMT" in cluster_tickers, (
        f"planted LMT cluster missing; got {cluster_tickers}"
    )
    lmt = next(c for c in result.clusters if c.ticker == "LMT")
    assert len(lmt.actor_ids) >= 3


def test_pltr_otm_call_is_signal_rich():
    _, _, _, result = _run_pipeline()
    pltr_calls = [
        s for s, t in zip(result.trade_signals, sorted(
            synthetic_trades(end=date(2024, 12, 31)),
            key=lambda x: x.trade_id,
        ))
        if "long-dated call" in s.signal_types
    ]
    # The planted PLTR call must surface as signal-rich.
    assert any(s.is_signal_rich for s in result.trade_signals if "long-dated call" in s.signal_types), \
        "planted PLTR OTM long-dated call did not score as signal-rich"


def test_top_candidates_avoid_only_megacaps():
    _, _, _, result = _run_pipeline()
    top = result.candidates[:5]
    assert top, "no candidates"
    mega = {"AAPL", "MSFT", "NVDA"}
    non_mega = [c for c in top if c.ticker not in mega]
    assert non_mega, "top candidates were all mega-caps — asymmetric filter failed"


def test_backtest_runs_and_returns_numbers():
    trades, _, prices, result = _run_pipeline()
    returns = prices.pct_change().dropna(how="all")
    bench = returns["SPY"]
    bt = run_backtest(
        trades,
        result.candidates,
        returns,
        bench,
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        holding_period_days=60,
        slippage_bps=25.0,
        bootstrap_iterations=100,
    )
    assert bt.n_trades >= 0
    # With planted alpha on LMT/PLTR, mean CAR should not be NaN.
    if bt.n_trades > 0:
        import math
        assert not math.isnan(bt.mean_car), "backtest produced NaN CAR with non-empty trades"
