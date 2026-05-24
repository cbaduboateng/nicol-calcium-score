"""End-to-end pipeline orchestrator.

Glues the scoring layers together and returns the ranked asymmetric candidates
plus the intermediate score objects so callers can inspect "why".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .filters.asymmetric import rank_asymmetric_candidates
from .ingest.prices import fetch_prices
from .schema import (
    Actor,
    ActorScore,
    AsymmetricCandidate,
    Cluster,
    ResidualVerdict,
    Trade,
    TradeSignal,
)
from .scoring import (
    compute_residuals,
    find_clusters,
    score_actors,
    score_trades,
)


@dataclass
class PipelineResult:
    candidates: list[AsymmetricCandidate]
    actor_scores: list[ActorScore]
    trade_signals: list[TradeSignal]
    clusters: list[Cluster]
    residuals: list[ResidualVerdict]
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)


def _spot_prices(prices: pd.DataFrame, trades: list[Trade]) -> dict[str, float]:
    """Spot price per ticker at the most recent close on or before each
    trade's transaction date. We just return the last close per ticker; the
    filter compares strike against this when computing OTM-ness.
    """
    if prices.empty:
        return {}
    spots: dict[str, float] = {}
    last = prices.iloc[-1]
    for ticker in {t.ticker for t in trades}:
        if ticker in prices.columns:
            spots[ticker] = float(last[ticker])
    return spots


def run_full_pipeline(
    cfg: dict[str, Any],
    trades: list[Trade],
    actors: list[Actor],
    *,
    prices: pd.DataFrame | None = None,
) -> PipelineResult:
    """Run every scoring layer and return ranked candidates plus intermediates."""
    scoring = cfg.get("scoring", {})
    actor_cfg = scoring.get("actor_quality", {})
    signal_cfg = scoring.get("trade_signal", {})
    cluster_cfg = scoring.get("cluster", {})
    residual_cfg = scoring.get("residual", {})
    asym_cfg = scoring.get("asymmetric", {})

    actor_scores = score_actors(
        actors, trades,
        weights=actor_cfg.get("weights"),
        min_trades_for_alpha=actor_cfg.get("min_trades_for_alpha", 5),
    )
    trade_signals = score_trades(
        trades, actors,
        weights={
            "options": signal_cfg.get("options_weight", 0.4),
            "size": signal_cfg.get("size_weight", 0.3),
            "speed": signal_cfg.get("speed_weight", 0.2),
            "committee_overlap": signal_cfg.get("committee_overlap_weight", 0.1),
        },
        size_z_threshold=signal_cfg.get("size_z_threshold", 1.0),
        fast_disclosure_days=signal_cfg.get("fast_disclosure_days", 14),
    )
    clusters = find_clusters(
        trades, actor_scores,
        window_days=cluster_cfg.get("window_days", 14),
        min_actors=cluster_cfg.get("min_actors", 2),
        min_combined_quality=cluster_cfg.get("min_combined_quality", 0.5),
    )

    if prices is None:
        tickers = sorted({t.ticker for t in trades})
        if tickers:
            min_date = min(t.transaction_date for t in trades)
            max_date = max(t.transaction_date for t in trades)
            start = min_date - timedelta(days=30)
            end = max(max_date + timedelta(days=residual_cfg.get("lookahead_days", 30)),
                      date.today())
            cache_dir = Path(cfg.get("paths", {}).get("cache", "data/cache"))
            prices, _, _ = fetch_prices(
                tickers, start, end,
                cache_dir=cache_dir,
                benchmark=cfg.get("backtest", {}).get("benchmark", "SPY"),
            )
        else:
            prices = pd.DataFrame()

    residuals = compute_residuals(
        trades, prices,
        catalyst_threshold_pct=residual_cfg.get("catalyst_threshold_pct", 5.0),
    )

    candidates = rank_asymmetric_candidates(
        trades,
        trade_signals,
        actor_scores,
        clusters,
        residuals,
        spot_prices=_spot_prices(prices, trades),
        minimum_trade_signal_score=asym_cfg.get("minimum_trade_signal_score", 0.5),
        minimum_actor_quality=asym_cfg.get("minimum_actor_quality", 0.3),
    )

    return PipelineResult(
        candidates=candidates,
        actor_scores=actor_scores,
        trade_signals=trade_signals,
        clusters=clusters,
        residuals=residuals,
        prices=prices,
    )
