"""Cluster detection: multiple high-quality actors trading the same ticker
within a rolling window.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ..schema import ActorScore, Cluster, Direction, Trade


def _net_direction(trades: list[Trade]) -> Direction:
    buys = sum(t.amount_midpoint_usd for t in trades if t.direction == Direction.BUY)
    sells = sum(
        t.amount_midpoint_usd for t in trades
        if t.direction in (Direction.SELL, Direction.PARTIAL_SALE)
    )
    return Direction.BUY if buys >= sells else Direction.SELL


def find_clusters(
    trades: list[Trade],
    actor_scores: list[ActorScore],
    *,
    window_days: int = 14,
    min_actors: int = 2,
    min_combined_quality: float = 0.5,
) -> list[Cluster]:
    by_ticker: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_ticker[t.ticker].append(t)

    score_by_actor = {s.actor_id: s.composite for s in actor_scores}
    clusters: list[Cluster] = []
    seen_windows: set[tuple[str, str]] = set()

    for ticker, ticker_trades in by_ticker.items():
        ticker_trades.sort(key=lambda t: t.transaction_date)
        n = len(ticker_trades)
        for i in range(n):
            window_end = ticker_trades[i].transaction_date + timedelta(days=window_days)
            window = [t for t in ticker_trades[i:] if t.transaction_date <= window_end]
            actor_ids = sorted({t.actor_id for t in window})
            if len(actor_ids) < min_actors:
                continue
            combined = sum(score_by_actor.get(a, 0.0) for a in actor_ids)
            if combined < min_combined_quality:
                continue
            window_start = window[0].transaction_date
            window_end_actual = window[-1].transaction_date
            key = (ticker, f"{window_start}-{window_end_actual}-{','.join(actor_ids)}")
            if key in seen_windows:
                continue
            seen_windows.add(key)
            total = sum(t.amount_midpoint_usd for t in window)
            clusters.append(Cluster(
                ticker=ticker,
                window_start=window_start,
                window_end=window_end_actual,
                actor_ids=tuple(actor_ids),
                combined_quality=float(combined),
                net_direction=_net_direction(window),
                total_midpoint_usd=float(total),
                rationale=(
                    f"{len(actor_ids)} actors, combined quality {combined:.2f}, "
                    f"net ${total:,.0f}"
                ),
            ))
    # Dedupe: keep the highest-quality cluster per ticker.
    best: dict[str, Cluster] = {}
    for c in clusters:
        if c.ticker not in best or c.combined_quality > best[c.ticker].combined_quality:
            best[c.ticker] = c
    return sorted(best.values(), key=lambda c: c.combined_quality, reverse=True)
