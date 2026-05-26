"""Monotonicity tests for the fundamental-quality scoring layer."""

from __future__ import annotations

from congress_signal.scoring.quality import QualityInputs, score_quality


def _q(**overrides) -> QualityInputs:
    """Build a neutral baseline QualityInputs with overrides applied."""
    base = dict(
        ticker="ACME",
        revenue_growth_yoy=0.20,
        revenue_growth_qoq_delta=0.0,
        gross_margin=0.40,
        gross_margin_yoy_delta=0.0,
        debt_to_equity=1.0,
        return_on_equity=0.15,
    )
    base.update(overrides)
    return QualityInputs(**base)


def test_higher_revenue_growth_raises_composite():
    low = score_quality(_q(revenue_growth_yoy=0.05))
    high = score_quality(_q(revenue_growth_yoy=0.50))
    assert high.composite > low.composite


def test_accelerating_growth_raises_composite():
    flat = score_quality(_q(revenue_growth_qoq_delta=0.0))
    accel = score_quality(_q(revenue_growth_qoq_delta=0.10))
    assert accel.composite > flat.composite


def test_higher_margin_raises_composite():
    low = score_quality(_q(gross_margin=0.20))
    high = score_quality(_q(gross_margin=0.60))
    assert high.composite > low.composite


def test_lower_leverage_raises_composite():
    levered = score_quality(_q(debt_to_equity=3.0))
    healthy = score_quality(_q(debt_to_equity=0.2))
    assert healthy.composite > levered.composite


def test_higher_roe_raises_composite():
    low = score_quality(_q(return_on_equity=0.02))
    high = score_quality(_q(return_on_equity=0.30))
    assert high.composite > low.composite


def test_missing_data_yields_neutral_sub_scores():
    score = score_quality(QualityInputs(ticker="ACME"))
    # All sub-scores should default to 0.5; composite is the weighted mean
    # which should also be ~0.5.
    assert abs(score.composite - 0.5) < 0.01
