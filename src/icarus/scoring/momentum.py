"""Layer 9 (Phase 1): Price-momentum signal scoring.

Empirical basis: Jegadeesh & Titman (1993) — 12-1 month price momentum
predicts 3-12 month forward returns more robustly than any other single
factor. The "skip the most recent month" detail removes short-term reversal
noise (Asness 2010).

Pure function: takes a price DataFrame + ticker + as_of date, returns a
0-1 momentum score by logistic-mapping the raw return.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
from pydantic import BaseModel, Field


class MomentumScore(BaseModel):
    ticker: str
    as_of: date
    lookback_days: int
    raw_return: float                       # raw price return over the 12-1 window
    score: float = Field(..., ge=0, le=1)   # logistic-mapped 0-1


def score_momentum(
    prices: pd.DataFrame,
    *,
    ticker: str,
    as_of: date,
    lookback_long_days: int = 252,
    skip_recent_days: int = 21,
    logistic_steepness: float = 3.0,
) -> MomentumScore:
    """Return a `MomentumScore` for `ticker` as of `as_of`.

    Computes the raw return between `(as_of - lookback_long_days)` and
    `(as_of - skip_recent_days)`. Maps to 0-1 via a logistic centred at
    zero return — so +20% maps to ~0.65, -20% to ~0.35, and large moves
    saturate towards 1 / 0.
    """
    score = 0.5  # neutral when we can't compute
    raw_return = 0.0
    lookback = lookback_long_days

    if ticker in prices.columns and len(prices) > lookback_long_days:
        ts = pd.Timestamp(as_of)
        idx = prices.index
        end_pos = idx.searchsorted(ts) - skip_recent_days
        start_pos = end_pos - (lookback_long_days - skip_recent_days)
        if 0 <= start_pos < end_pos < len(idx):
            start_price = prices.iloc[start_pos][ticker]
            end_price = prices.iloc[end_pos][ticker]
            if pd.notna(start_price) and pd.notna(end_price) and start_price > 0:
                raw_return = float((end_price / start_price) - 1.0)
                score = 1.0 / (1.0 + math.exp(-logistic_steepness * raw_return))

    return MomentumScore(
        ticker=ticker.upper(),
        as_of=as_of,
        lookback_days=lookback,
        raw_return=raw_return,
        score=score,
    )


def score_universe(
    prices: pd.DataFrame,
    tickers: list[str],
    *,
    as_of: date,
    **kwargs,
) -> dict[str, MomentumScore]:
    """Score multiple tickers at once."""
    return {
        t.upper(): score_momentum(prices, ticker=t, as_of=as_of, **kwargs)
        for t in tickers
    }
