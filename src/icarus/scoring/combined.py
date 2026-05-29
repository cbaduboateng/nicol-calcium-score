"""Multi-signal composite scorer (Phase 1).

Combines the existing congressional-asymmetry score with the Phase 1
insider / momentum / quality layers into a single per-ticker meta-score.
This is the "multi-signal hypothesis" the Phase 0 verdict pointed us
toward: congressional trading alone underperformed; combining it with
other quant signals may rescue the strategy.

Pure: takes pre-computed sub-scores in, returns composite out. No I/O.

Default weight set (tunable in config):
  - Congressional asymmetry: 25%
  - Insider buying:           25%
  - Momentum (12-1):          20%
  - Quality:                  15%
  - Catalyst-residual:        15%

These are placeholders. Re-tune by gradient-ish backtest: vary one weight
at a time, re-validate, keep the configuration with best risk-adjusted
return.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


_DEFAULT_WEIGHTS: dict[str, float] = {
    "congressional": 0.25,
    "insider":       0.25,
    "momentum":      0.20,
    "quality":       0.15,
    "catalyst":      0.15,
}


class CompositeScoreInputs(BaseModel):
    """Per-ticker sub-scores. Missing fields default to neutral 0.5 so we
    don't penalise tickers for which a layer has no data."""

    ticker: str
    congressional: float | None = None
    insider: float | None = None
    momentum: float | None = None
    quality: float | None = None
    catalyst: float | None = None


class CompositeScore(BaseModel):
    ticker: str
    congressional: float = Field(..., ge=0, le=1)
    insider: float = Field(..., ge=0, le=1)
    momentum: float = Field(..., ge=0, le=1)
    quality: float = Field(..., ge=0, le=1)
    catalyst: float = Field(..., ge=0, le=1)
    composite: float = Field(..., ge=0, le=1)


def score_composite(
    inputs: CompositeScoreInputs,
    *,
    weights: dict[str, float] | None = None,
) -> CompositeScore:
    """Combine the per-layer sub-scores into a 0-1 composite."""
    w = weights or _DEFAULT_WEIGHTS

    def _coalesce(x: float | None) -> float:
        return 0.5 if x is None else max(0.0, min(1.0, x))

    c = _coalesce(inputs.congressional)
    i = _coalesce(inputs.insider)
    m = _coalesce(inputs.momentum)
    q = _coalesce(inputs.quality)
    ca = _coalesce(inputs.catalyst)

    composite = (
        w["congressional"] * c
        + w["insider"]       * i
        + w["momentum"]      * m
        + w["quality"]       * q
        + w["catalyst"]      * ca
    )
    return CompositeScore(
        ticker=inputs.ticker.upper(),
        congressional=c, insider=i, momentum=m, quality=q, catalyst=ca,
        composite=min(1.0, max(0.0, composite)),
    )
