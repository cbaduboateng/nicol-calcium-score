"""Pydantic v2 data contracts for the entire pipeline.

Every downstream module consumes and produces these types. Treat the field
sets here as the public interface and avoid adding ad-hoc dict shapes
elsewhere.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


class Chamber(StrEnum):
    HOUSE = "house"
    SENATE = "senate"
    EXECUTIVE = "executive"


class AssetType(StrEnum):
    STOCK = "stock"
    CALL = "call"
    PUT = "put"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    BOND_CORP = "bond_corp"
    BOND_MUNI = "bond_muni"
    BOND_TREASURY = "bond_treasury"
    CRYPTO = "crypto"
    OTHER = "other"


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    EXCHANGE = "exchange"
    PARTIAL_SALE = "partial_sale"


class Owner(StrEnum):
    SELF = "self"
    SPOUSE = "spouse"
    JOINT = "joint"
    DEPENDENT = "dependent"
    TRUST = "trust"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------


class Actor(BaseModel):
    """A disclosing individual: member of Congress, presidential appointee, etc."""

    model_config = ConfigDict(frozen=True)

    actor_id: str = Field(..., description="Stable identifier; bioguide ID for Congress.")
    name: str
    chamber: Chamber
    party: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    committees: tuple[str, ...] = ()
    leadership_role: Optional[str] = None
    net_worth_estimate_usd: Optional[float] = None
    active: bool = True


class Trade(BaseModel):
    """A single disclosed transaction, normalised across sources."""

    model_config = ConfigDict(frozen=True)

    trade_id: str
    actor_id: str
    transaction_date: date
    disclosure_date: date
    ticker: str
    asset_type: AssetType
    direction: Direction
    amount_min_usd: float = Field(..., ge=0)
    amount_max_usd: float = Field(..., ge=0)
    owner: Owner = Owner.SELF

    # Option-specific fields
    option_strike: Optional[float] = None
    option_expiry: Optional[date] = None
    option_type: Optional[AssetType] = None  # CALL or PUT

    # Provenance
    source: str = Field(..., description="quiver | house_ptr | senate_efd | oge_278t | ...")
    raw_source: Optional[dict[str, Any]] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount_midpoint_usd(self) -> float:
        return (self.amount_min_usd + self.amount_max_usd) / 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def disclosure_lag_days(self) -> int:
        return (self.disclosure_date - self.transaction_date).days

    @computed_field  # type: ignore[prop-decorator]
    @property
    def days_to_expiry(self) -> Optional[int]:
        if self.option_expiry is None:
            return None
        return (self.option_expiry - self.transaction_date).days

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_option(self) -> bool:
        return self.asset_type in (AssetType.CALL, AssetType.PUT)


# ---------------------------------------------------------------------------
# Scores and signals
# ---------------------------------------------------------------------------


class ActorScore(BaseModel):
    """Output of the actor-quality scoring layer."""

    actor_id: str
    as_of: datetime
    committee_relevance: float = Field(..., ge=0, le=1)
    historical_alpha_bps: float = Field(..., description="Annualised abnormal return in basis points.")
    historical_alpha_normalised: float = Field(..., ge=0, le=1)
    concentration_score: float = Field(..., ge=0, le=1)
    skin_in_game: float = Field(..., ge=0, le=1)
    composite: float = Field(..., ge=0, le=1)
    trades_observed: int
    rationale: str = ""


class TradeSignal(BaseModel):
    """Output of the per-trade signal-richness classifier."""

    trade_id: str
    is_signal_rich: bool
    signal_types: tuple[str, ...]
    raw_score: float = Field(..., ge=0)
    rationale: str = ""


class Cluster(BaseModel):
    """A ticker with multiple quality actors trading in the same window."""

    ticker: str
    window_start: date
    window_end: date
    actor_ids: tuple[str, ...]
    combined_quality: float
    net_direction: Direction
    total_midpoint_usd: float
    rationale: str = ""


class ResidualVerdict(BaseModel):
    """Output of the catalyst-residual filter for a single trade."""

    trade_id: str
    ticker: str
    transaction_date: date
    price_move_since_pct: float
    catalyst_fired: bool
    residual_opportunity: bool
    rationale: str = ""


class AsymmetricCandidate(BaseModel):
    """A trade that survives all filter layers and merits human review."""

    trade_id: str
    ticker: str
    actor_id: str
    asymmetry_score: float = Field(..., ge=0)
    signal_types: tuple[str, ...]
    cluster_size: int
    catalyst_pending: bool
    rationale: str = ""


# ---------------------------------------------------------------------------
# Backtest outputs
# ---------------------------------------------------------------------------


class BacktestResult(BaseModel):
    """Aggregate output of a backtest run."""

    start: date
    end: date
    holding_period_days: int
    n_trades: int
    mean_car: float = Field(..., description="Mean cumulative abnormal return over holding period.")
    median_car: float
    hit_rate: float
    sharpe: float
    max_drawdown: float
    car_ci_lower: float
    car_ci_upper: float
    slippage_bps: float
    notes: str = ""
