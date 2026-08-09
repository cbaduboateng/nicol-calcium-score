"""Tests for the short-interest positioning layer (pure parts)."""

from __future__ import annotations

from icarus.positioning import (
    load_positioning,
    positioning_label,
    positioning_note,
)


def test_labels_at_fixed_thresholds():
    assert positioning_label({"short_pct_float": 18.2}) == "battleground"
    assert positioning_label({"short_pct_float": 15.0}) == "battleground"
    assert positioning_label({"short_pct_float": 8.0}) == "elevated"
    assert positioning_label({"short_pct_float": 2.0}) == "normal"
    assert positioning_label({"short_pct_float": None}) == "unknown"
    assert positioning_label(None) == "unknown"
    assert positioning_label({}) == "unknown"


def test_note_content_by_severity():
    hot = positioning_note({"short_pct_float": 18.2, "days_to_cover": 10.6})
    assert hot and "Battleground" in hot and "18.2%" in hot and "10.6 days" in hot
    warm = positioning_note({"short_pct_float": 9.0, "days_to_cover": None})
    assert warm and "Elevated" in warm and "days to cover" not in warm
    assert positioning_note({"short_pct_float": 1.0}) is None
    assert positioning_note(None) is None


def test_load_missing_cache_graceful(tmp_path):
    assert load_positioning(tmp_path / "nope.json") == {}
