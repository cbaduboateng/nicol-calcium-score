"""Deterministic synthetic data generators.

Used when external sources are unavailable. The output exercises every branch
of the downstream pipeline: clustering, options signals, federal contractors,
mega-cap demotion, etc.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..schema import (
    Actor,
    AssetType,
    Chamber,
    Direction,
    Owner,
    Trade,
)

# A small but diverse universe that touches every asymmetric-filter branch.
SYNTHETIC_TICKERS = [
    # mega-caps (demoted)
    "AAPL", "MSFT", "NVDA",
    # bounded-downside defence primes (also federal contractors)
    "LMT", "RTX", "NOC", "GD",
    # regulated utilities (bounded downside)
    "NEE", "DUK",
    # small/mid federal contractors
    "AXON", "PLTR", "KTOS", "AVAV", "MRCY", "CACI",
    # non-special names
    "F", "T", "INTC",
]

SYNTHETIC_ACTORS = [
    # (actor_id, name, chamber, party, state, committees)
    ("H001075", "Alex Defence", Chamber.HOUSE, "R", "TX",
     ("House Armed Services", "House Intelligence")),
    ("H001076", "Bea Energy", Chamber.HOUSE, "D", "CA",
     ("House Energy and Commerce",)),
    ("H001077", "Chris Tech", Chamber.HOUSE, "D", "WA",
     ("House Science, Space, and Technology",)),
    ("S001081", "Dana Banking", Chamber.SENATE, "R", "FL",
     ("Senate Banking",)),
    ("S001082", "Eli Defence", Chamber.SENATE, "D", "VA",
     ("Senate Armed Services", "Senate Intelligence")),
]


def _stable_seed(*parts: object) -> int:
    digest = hashlib.sha256(repr(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big")


def synthetic_actors() -> list[Actor]:
    return [
        Actor(
            actor_id=aid,
            name=name,
            chamber=chamber,
            party=party,
            state=state,
            committees=committees,
        )
        for aid, name, chamber, party, state, committees in SYNTHETIC_ACTORS
    ]


def _amount_brackets(rng: np.random.Generator) -> tuple[float, float]:
    """Approximate the bracketed-amount style of real PTRs."""
    buckets = [
        (1_000, 15_000),
        (15_001, 50_000),
        (50_001, 100_000),
        (100_001, 250_000),
        (250_001, 500_000),
        (500_001, 1_000_000),
        (1_000_001, 5_000_000),
    ]
    lo, hi = buckets[int(rng.integers(0, len(buckets)))]
    return float(lo), float(hi)


def synthetic_trades(
    *,
    n_trades: int = 80,
    end: date | None = None,
    span_days: int = 180,
    seed: int = 7,
) -> list[Trade]:
    """Generate a deterministic synthetic trade tape.

    Includes:
    - A defence-cluster event: 3 actors buy LMT within a 5-day window.
    - An OTM long-dated call on PLTR by a defence-committee actor.
    - Mega-cap noise trades that should be demoted.
    """
    end = end or date(2024, 12, 31)
    rng = np.random.default_rng(seed)
    actors = synthetic_actors()
    trades: list[Trade] = []

    # ---- planted cluster: LMT defence buy ---------------------------------
    cluster_date = end - timedelta(days=span_days // 2)
    for offset, actor in enumerate(actors[:3]):
        lo, hi = 50_001.0, 100_000.0
        txn = cluster_date + timedelta(days=offset)
        trades.append(Trade(
            trade_id=f"synth-cluster-LMT-{actor.actor_id}-{txn}",
            actor_id=actor.actor_id,
            transaction_date=txn,
            disclosure_date=txn + timedelta(days=8),
            ticker="LMT",
            asset_type=AssetType.STOCK,
            direction=Direction.BUY,
            amount_min_usd=lo,
            amount_max_usd=hi,
            owner=Owner.SELF,
            source="synthetic",
        ))

    # ---- planted OTM long-dated call on PLTR ------------------------------
    pltr_txn = end - timedelta(days=span_days // 3)
    trades.append(Trade(
        trade_id=f"synth-otm-PLTR-{actors[0].actor_id}",
        actor_id=actors[0].actor_id,
        transaction_date=pltr_txn,
        disclosure_date=pltr_txn + timedelta(days=10),
        ticker="PLTR",
        asset_type=AssetType.CALL,
        direction=Direction.BUY,
        amount_min_usd=15_001.0,
        amount_max_usd=50_000.0,
        owner=Owner.SELF,
        option_strike=80.0,
        option_expiry=pltr_txn + timedelta(days=365),
        option_type=AssetType.CALL,
        source="synthetic",
    ))

    # ---- background noise -------------------------------------------------
    for i in range(n_trades - len(trades)):
        actor = actors[int(rng.integers(0, len(actors)))]
        ticker = SYNTHETIC_TICKERS[int(rng.integers(0, len(SYNTHETIC_TICKERS)))]
        txn = end - timedelta(days=int(rng.integers(1, span_days)))
        direction = Direction.BUY if rng.random() < 0.6 else Direction.SELL
        lo, hi = _amount_brackets(rng)
        trades.append(Trade(
            trade_id=f"synth-noise-{i}-{actor.actor_id}-{ticker}-{txn}",
            actor_id=actor.actor_id,
            transaction_date=txn,
            disclosure_date=txn + timedelta(days=int(rng.integers(1, 45))),
            ticker=ticker,
            asset_type=AssetType.STOCK,
            direction=direction,
            amount_min_usd=lo,
            amount_max_usd=hi,
            owner=Owner.SELF,
            source="synthetic",
        ))

    return trades


def synthetic_prices(
    tickers: list[str],
    start: date,
    end: date,
    *,
    benchmark: str = "SPY",
    seed: int = 11,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Geometric Brownian Motion price paths with a planted post-cluster rally
    on LMT and PLTR so the backtest can show non-zero CARs.
    """
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start=start, end=end)
    if len(days) == 0:
        days = pd.bdate_range(end=end, periods=2)

    all_tickers = sorted(set(tickers) | {benchmark, "LMT", "PLTR"})
    drift = 0.00025
    vol = 0.012

    returns = pd.DataFrame(
        rng.normal(loc=drift, scale=vol, size=(len(days), len(all_tickers))),
        index=days,
        columns=all_tickers,
    )

    # Planted alpha: LMT and PLTR get +0.4% drift in the second half of the window.
    midpoint = len(days) // 2
    for ticker in ("LMT", "PLTR"):
        if ticker in returns.columns:
            returns.loc[returns.index[midpoint:], ticker] += 0.004

    benchmark_returns = returns[benchmark].copy()
    prices = (1 + returns).cumprod() * 100.0
    return prices, returns, benchmark_returns
