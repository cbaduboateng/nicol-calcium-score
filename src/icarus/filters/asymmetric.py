"""Layer 6: Asymmetric-bias filter.

The default scoring stack will surface a familiar mega-cap AI cluster. For an
investor with an asymmetric, illiquid, multi-year style, that's table stakes.
This filter tunes the ranking *away* from the mega-cap cluster and *toward*:

- OTM long-dated options (rare but very high information)
- Small/mid-cap federal contractors
- Bounded-downside names (defence primes with backlogs, regulated utilities)
- Pre-IPO disclosures appearing in executive-branch filings

The output is an `asymmetry_score` that re-ranks candidates. It is not a
replacement for the upstream layers; it's a re-weighting.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable

from ..schema import (
    ActorScore,
    AssetType,
    AsymmetricCandidate,
    Cluster,
    Direction,
    ResidualVerdict,
    Trade,
    TradeSignal,
)

# Mega-cap exclusion list — these will surface from the upstream layers without
# any asymmetric boost. We deliberately *demote* them here so the asymmetric
# ranking doesn't double-count them.
MEGA_CAP_TICKERS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA",
    "TSLA", "BRK.A", "BRK.B", "JPM", "V", "MA", "UNH", "XOM",
    "WMT", "JNJ", "PG", "HD", "AVGO", "ORCL",
})

# Known federal-contractor universe by ticker. Replace with a maintained list
# pulled from USAspending.gov recipient_uei -> ticker mappings.
KNOWN_FEDERAL_CONTRACTORS: frozenset[str] = frozenset({
    "LMT", "RTX", "NOC", "GD", "LDOS", "BAH", "CACI", "SAIC",
    "AXON", "PLTR", "KTOS", "AVAV", "MRCY", "HII", "TXT", "TDY",
})

# Names with bounded downside (very rough heuristic — real implementation
# should compute this from balance-sheet metrics, dividend yield stability,
# and historical max drawdown).
BOUNDED_DOWNSIDE_TICKERS: frozenset[str] = frozenset({
    "LMT", "RTX", "NOC", "GD",       # defence primes with multi-year backlogs
    "NEE", "DUK", "SO", "AEP",        # regulated utilities
    "JNJ", "PG", "KO", "PEP",         # consumer staples with dividend records
})


def _is_otm_long_dated_call(trade: Trade, spot_price: float | None) -> bool:
    """An OTM long-dated call: strike >= 110% of spot at trade date, DTE >= 180."""
    if trade.asset_type != AssetType.CALL or trade.direction != Direction.BUY:
        return False
    if trade.days_to_expiry is None or trade.days_to_expiry < 180:
        return False
    if trade.option_strike is None or spot_price is None or spot_price <= 0:
        return False
    return trade.option_strike >= spot_price * 1.10


def _asymmetry_components(
    trade: Trade,
    actor_score: ActorScore,
    cluster: Cluster | None,
    residual: ResidualVerdict | None,
    spot_price: float | None,
) -> tuple[float, list[str]]:
    """Compute the asymmetry score components and the reasons feeding into them."""
    score = 0.0
    reasons: list[str] = []
    ticker = trade.ticker.upper()

    # Demote mega-caps.
    if ticker in MEGA_CAP_TICKERS:
        score -= 0.3
        reasons.append("mega-cap demote (-0.3)")

    # Reward OTM long-dated calls.
    if _is_otm_long_dated_call(trade, spot_price):
        score += 0.6
        reasons.append("OTM long-dated call (+0.6)")

    # Reward federal contractor exposure for actors on defence committees.
    if ticker in KNOWN_FEDERAL_CONTRACTORS:
        score += 0.3
        reasons.append("federal contractor (+0.3)")

    # Reward bounded-downside names — only modestly, since the asymmetry here
    # is from a low-drawdown floor, not explosive upside.
    if ticker in BOUNDED_DOWNSIDE_TICKERS:
        score += 0.15
        reasons.append("bounded downside (+0.15)")

    # Reward the actor's underlying quality directly.
    score += actor_score.composite * 0.5
    reasons.append(f"actor quality (+{actor_score.composite * 0.5:.2f})")

    # Reward cluster presence.
    if cluster is not None:
        cluster_boost = min(0.4, 0.1 * len(cluster.actor_ids))
        score += cluster_boost
        reasons.append(f"cluster of {len(cluster.actor_ids)} actors (+{cluster_boost:.2f})")

    # Reward residual opportunity.
    if residual is not None and residual.residual_opportunity:
        score += 0.25
        reasons.append("catalyst not yet fired (+0.25)")
    elif residual is not None and residual.catalyst_fired:
        score -= 0.4
        reasons.append("catalyst already fired (-0.4)")

    return max(score, 0.0), reasons


def rank_asymmetric_candidates(
    trades: list[Trade],
    trade_signals: list[TradeSignal],
    actor_scores: list[ActorScore],
    clusters: Iterable[Cluster],
    residuals: list[ResidualVerdict],
    spot_prices: dict[str, float] | None = None,
    *,
    minimum_trade_signal_score: float = 0.5,
    minimum_actor_quality: float = 0.3,
) -> list[AsymmetricCandidate]:
    """Combine all upstream layers into a ranked list of asymmetric candidates."""
    spot_prices = spot_prices or {}
    actor_score_by_id = {s.actor_id: s for s in actor_scores}
    signal_by_id = {s.trade_id: s for s in trade_signals}
    residual_by_id = {r.trade_id: r for r in residuals}
    cluster_by_ticker = {c.ticker: c for c in clusters}

    candidates: list[AsymmetricCandidate] = []
    for trade in trades:
        actor_score = actor_score_by_id.get(trade.actor_id)
        if actor_score is None or actor_score.composite < minimum_actor_quality:
            continue
        trade_signal = signal_by_id.get(trade.trade_id)
        if trade_signal is None or trade_signal.raw_score < minimum_trade_signal_score:
            continue

        cluster = cluster_by_ticker.get(trade.ticker)
        residual = residual_by_id.get(trade.trade_id)
        spot = spot_prices.get(trade.ticker)

        asymmetry, reasons = _asymmetry_components(
            trade, actor_score, cluster, residual, spot,
        )
        if asymmetry <= 0.0:
            continue

        candidates.append(AsymmetricCandidate(
            trade_id=trade.trade_id,
            ticker=trade.ticker,
            actor_id=trade.actor_id,
            asymmetry_score=asymmetry,
            signal_types=trade_signal.signal_types,
            cluster_size=len(cluster.actor_ids) if cluster else 0,
            catalyst_pending=residual.residual_opportunity if residual else False,
            rationale=" | ".join(reasons),
        ))

    return sorted(candidates, key=lambda c: c.asymmetry_score, reverse=True)
