"""Layer 10 (Phase 1): Fundamental-quality signal scoring.

Empirical basis: Asness, Frazzini & Pedersen (AQR) — combining quality
(high ROE, low debt, improving margins) with momentum has historically
beaten the market net of costs. Quality alone is mildly defensive; quality
+ momentum is the workhorse.

This module is pure: takes a `QualityInputs` payload + an optional set of
weights, returns a 0-1 score. The ingest layer (SimFin / Financial Modeling
Prep / SEC XBRL) fills the payload.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field


def _logistic(x: float, midpoint: float, steepness: float = 8.0) -> float:
    """Logistic centred at `midpoint`, returns 0-1."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if x < midpoint else 1.0


class QualityInputs(BaseModel):
    """Per-ticker fundamental snapshot. Missing values are treated as the
    neutral midpoint (0.5 score for that sub-component)."""

    ticker: str
    revenue_growth_yoy: float | None = None        # 0.20 = 20%
    revenue_growth_qoq_delta: float | None = None  # change in QoQ growth (accel)
    gross_margin: float | None = None              # 0.40 = 40%
    gross_margin_yoy_delta: float | None = None    # change in GM year-over-year
    debt_to_equity: float | None = None            # 0.5 = healthy, 2.0+ = stressed
    return_on_equity: float | None = None          # 0.15 = 15%


class QualityScore(BaseModel):
    ticker: str
    revenue_growth_score: float = Field(..., ge=0, le=1)
    revenue_accel_score: float = Field(..., ge=0, le=1)
    margin_level_score: float = Field(..., ge=0, le=1)
    margin_trend_score: float = Field(..., ge=0, le=1)
    leverage_score: float = Field(..., ge=0, le=1)
    roe_score: float = Field(..., ge=0, le=1)
    composite: float = Field(..., ge=0, le=1)


_DEFAULT_WEIGHTS: dict[str, float] = {
    "revenue_growth": 0.30,
    "revenue_accel":  0.20,
    "margin_level":   0.20,
    "margin_trend":   0.10,
    "leverage":       0.10,
    "roe":            0.10,
}


def score_quality(
    inputs: QualityInputs,
    *,
    weights: dict[str, float] | None = None,
) -> QualityScore:
    """Map a `QualityInputs` snapshot to a 0-1 composite quality score."""
    w = weights or _DEFAULT_WEIGHTS

    rg = (
        _logistic(inputs.revenue_growth_yoy, midpoint=0.20)
        if inputs.revenue_growth_yoy is not None else 0.5
    )
    ra = (
        _logistic(inputs.revenue_growth_qoq_delta, midpoint=0.0)
        if inputs.revenue_growth_qoq_delta is not None else 0.5
    )
    ml = (
        _logistic(inputs.gross_margin, midpoint=0.40)
        if inputs.gross_margin is not None else 0.5
    )
    mt = (
        _logistic(inputs.gross_margin_yoy_delta, midpoint=0.0)
        if inputs.gross_margin_yoy_delta is not None else 0.5
    )
    # Leverage: lower D/E is better. 0.5 -> 0.5, 0.0 -> 1.0, 2.0+ -> ~0.
    if inputs.debt_to_equity is None:
        lev = 0.5
    else:
        lev = 1.0 - min(1.0, max(0.0, inputs.debt_to_equity / 2.0))
    roe = (
        _logistic(inputs.return_on_equity, midpoint=0.15)
        if inputs.return_on_equity is not None else 0.5
    )

    composite = (
        w["revenue_growth"] * rg
        + w["revenue_accel"]  * ra
        + w["margin_level"]   * ml
        + w["margin_trend"]   * mt
        + w["leverage"]       * lev
        + w["roe"]            * roe
    )
    return QualityScore(
        ticker=inputs.ticker.upper(),
        revenue_growth_score=rg,
        revenue_accel_score=ra,
        margin_level_score=ml,
        margin_trend_score=mt,
        leverage_score=lev,
        roe_score=roe,
        composite=min(1.0, max(0.0, composite)),
    )
