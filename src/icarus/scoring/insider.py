"""Layer 8 (Phase 1): Insider-buying signal scoring.

Empirical basis: Lakonishok & Lee (2001) and subsequent literature show
that clustered open-market insider buying predicts forward returns. The
edge is strongest when:

  - Multiple distinct insiders buy in a tight window (90 days).
  - Buyers are C-suite (CEO/CFO/COO/CTO) rather than directors or 10%
    holders.
  - Transaction sizes are meaningful (≥ $50k) and unusual versus the
    insider's personal history.
  - Buyers outweigh sellers in net dollar terms.

This module is pure: takes a list of `InsiderTransaction` objects + a
target ticker + an `as_of` date, returns a 0-1 score. No I/O. The
matching ingest layer (SEC Form 4 / OpenInsider) lives in
`ingest/insider.py` (TODO).
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

# Word-boundary regex so "Director" doesn't false-match "cto", and
# "Officer" doesn't false-match "chief". Conservative keyword set:
# chief-anything, the standard C-suite abbreviations, chairman, founder.
_SENIOR_ROLE_PATTERN = re.compile(
    r"\b(chief|ceo|cfo|coo|cto|chairman|founder)\b",
    re.IGNORECASE,
)


class InsiderTransaction(BaseModel):
    """A normalised SEC Form 4 transaction. The ingest layer maps from
    OpenInsider / SEC EDGAR XML into this contract."""

    ticker: str
    insider_name: str
    insider_role: str           # raw role string from the filing
    transaction_date: date
    direction: Literal["buy", "sell"]
    is_open_market: bool        # excludes option exercises, gifts, RSU vests
    shares: float = Field(..., ge=0)
    price: float = Field(..., ge=0)
    value_usd: float = Field(..., ge=0)


class InsiderScore(BaseModel):
    """Per-ticker insider-buying score and the sub-components that built it."""

    ticker: str
    as_of: date
    n_open_market_buys: int
    n_distinct_buyers: int
    n_senior_buyers: int
    net_buy_ratio: float = Field(..., ge=0, le=1)  # buy_value / (buy + sell)
    cluster_score: float = Field(..., ge=0, le=1)
    senior_share: float = Field(..., ge=0, le=1)
    composite: float = Field(..., ge=0, le=1)


def _is_senior(role: str) -> bool:
    if not role:
        return False
    return bool(_SENIOR_ROLE_PATTERN.search(role))


def score_insider_buying(
    transactions: list[InsiderTransaction],
    *,
    ticker: str,
    as_of: date,
    window_days: int = 90,
    minimum_open_market_value: float = 50_000.0,
    weights: dict[str, float] | None = None,
) -> InsiderScore:
    """Return an `InsiderScore` for `ticker` as of `as_of`.

    Composite is a weighted average of three sub-scores (each 0-1):

      - cluster_score   : log-scaled count of distinct open-market buyers
      - senior_share    : fraction of buyers in C-suite / chair roles
      - net_buy_ratio   : buy dollar value / (buy + sell) dollar value

    Default weights: 50% cluster, 25% senior, 25% net ratio. Override via
    the `weights` argument (must sum to 1.0 — not enforced).
    """
    w = weights or {"cluster": 0.50, "senior": 0.25, "net": 0.25}
    cutoff = as_of - timedelta(days=window_days)

    in_window = [
        t for t in transactions
        if t.ticker.upper() == ticker.upper()
        and cutoff <= t.transaction_date <= as_of
        and t.is_open_market
        and t.value_usd >= minimum_open_market_value
    ]

    buys = [t for t in in_window if t.direction == "buy"]
    sells = [t for t in in_window if t.direction == "sell"]

    distinct_buyer_names = {t.insider_name for t in buys}
    n_buyers = len(distinct_buyer_names)
    senior_buyer_names = {t.insider_name for t in buys if _is_senior(t.insider_role)}
    n_senior = len(senior_buyer_names)

    # Cluster score: 0.0 for no buyers; 0.5 for one buyer; +0.15 per extra
    # distinct buyer up to a cap of 1.0. Empirically the marginal value of
    # additional buyers tails off past 4-5.
    if n_buyers == 0:
        cluster = 0.0
    else:
        cluster = min(1.0, 0.5 + 0.15 * (n_buyers - 1))

    senior_share = n_senior / n_buyers if n_buyers else 0.0

    buy_value = sum(t.value_usd for t in buys)
    sell_value = sum(t.value_usd for t in sells)
    total_value = buy_value + sell_value
    net_ratio = buy_value / total_value if total_value > 0 else 0.0

    composite = (
        w["cluster"] * cluster
        + w["senior"] * senior_share
        + w["net"] * net_ratio
    )
    return InsiderScore(
        ticker=ticker.upper(),
        as_of=as_of,
        n_open_market_buys=len(buys),
        n_distinct_buyers=n_buyers,
        n_senior_buyers=n_senior,
        net_buy_ratio=net_ratio,
        cluster_score=cluster,
        senior_share=senior_share,
        composite=min(1.0, max(0.0, composite)),
    )


def score_universe(
    transactions: list[InsiderTransaction],
    tickers: list[str],
    *,
    as_of: date,
    **kwargs,
) -> dict[str, InsiderScore]:
    """Convenience: score multiple tickers at once."""
    return {
        t.upper(): score_insider_buying(transactions, ticker=t, as_of=as_of, **kwargs)
        for t in tickers
    }
