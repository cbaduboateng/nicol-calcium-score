"""Monotonicity tests for the composite multi-signal scorer."""

from __future__ import annotations

from congress_signal.scoring.combined import CompositeScoreInputs, score_composite


def test_all_high_yields_high_composite():
    score = score_composite(CompositeScoreInputs(
        ticker="ACME",
        congressional=0.9, insider=0.9, momentum=0.9, quality=0.9, catalyst=0.9,
    ))
    assert score.composite > 0.85


def test_all_low_yields_low_composite():
    score = score_composite(CompositeScoreInputs(
        ticker="ACME",
        congressional=0.1, insider=0.1, momentum=0.1, quality=0.1, catalyst=0.1,
    ))
    assert score.composite < 0.15


def test_missing_inputs_default_to_neutral():
    score = score_composite(CompositeScoreInputs(ticker="ACME"))
    assert abs(score.composite - 0.5) < 0.01


def test_raising_one_layer_raises_composite():
    base = score_composite(CompositeScoreInputs(
        ticker="ACME",
        congressional=0.5, insider=0.5, momentum=0.5, quality=0.5, catalyst=0.5,
    ))
    up = score_composite(CompositeScoreInputs(
        ticker="ACME",
        congressional=0.5, insider=0.9, momentum=0.5, quality=0.5, catalyst=0.5,
    ))
    assert up.composite > base.composite


def test_custom_weights_shift_emphasis():
    # All insider, no congressional weight — insider should dominate.
    weights = {"congressional": 0.0, "insider": 1.0,
               "momentum": 0.0, "quality": 0.0, "catalyst": 0.0}
    score = score_composite(
        CompositeScoreInputs(ticker="ACME", congressional=0.1, insider=0.9),
        weights=weights,
    )
    assert abs(score.composite - 0.9) < 0.01
