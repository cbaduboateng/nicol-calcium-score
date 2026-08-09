"""Tests for the Reddit-attention overlay (pure parts)."""

from __future__ import annotations

from icarus.reddit_overlay import (
    attention_label,
    build_reddit_overlay,
    format_gem_mentions,
    load_reddit_overlay,
)


RAW = [
    {"ticker": "VIRAL", "mentions": "120", "mentions_24h_ago": "40", "rank": "3"},
    {"ticker": "STEADY", "mentions": "80", "mentions_24h_ago": "75", "rank": "12"},
    {"ticker": "TINY", "mentions": "6", "mentions_24h_ago": "1", "rank": "300"},
    {"ticker": "", "mentions": "50"},                     # junk: no ticker
    {"ticker": "BAD", "mentions": "not-a-number"},        # junk: bad value
]


def test_build_overlay_normalises_and_drops_junk():
    ov = build_reddit_overlay(RAW)
    assert set(ov) == {"VIRAL", "STEADY", "TINY"}
    assert ov["VIRAL"]["mentions"] == 120
    assert ov["VIRAL"]["spike_ratio"] == 3.0
    assert ov["STEADY"]["rank"] == 12


def test_attention_labels_fixed_thresholds():
    ov = build_reddit_overlay(RAW)
    assert attention_label(ov["VIRAL"]) == "viral"      # >=30 and >=2x
    assert attention_label(ov["STEADY"]) == "elevated"  # >=30, no spike
    assert attention_label(ov["TINY"]) == "quiet"       # 6x spike but 6 posts
    assert attention_label(None) == "quiet"
    assert attention_label({}) == "quiet"


def test_format_gem_mentions_line():
    ov = build_reddit_overlay(RAW)
    line = format_gem_mentions(["VIRAL", "GHOST"], ov)
    assert line == "VIRAL:120 GHOST:0"


def test_load_overlay_missing_cache_graceful(tmp_path, monkeypatch):
    # Point at an empty cache dir and break the network import path —
    # must return {} rather than raise.
    import icarus.reddit_overlay as ro
    monkeypatch.setattr(ro, "APEWISDOM_URL", "https://127.0.0.1:1/{page}")
    out = load_reddit_overlay(cache_path=tmp_path / "none.json")
    assert out == {}
