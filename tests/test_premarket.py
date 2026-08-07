"""Tests for the premarket report builders (pure parts only)."""

from __future__ import annotations

import pytest

from icarus.premarket import build_premarket_report, format_premarket_push


QUOTES = {
    "GAPPER": {"premarket_price": 10.8, "prev_close": 10.0},   # +8%
    "DRIFT": {"premarket_price": 10.1, "prev_close": 10.0},    # +1% noise
    "MYPOS": {"premarket_price": 9.8, "prev_close": 10.0},     # -2%, held
    "DEADQ": {"premarket_price": None, "prev_close": 10.0},    # no print
    "GEMUP": {"premarket_price": 21.0, "prev_close": 20.0},    # +5%, gem
}


def test_material_gaps_and_holdings_included_noise_excluded():
    rows = build_premarket_report(
        QUOTES, holdings=["MYPOS"], gems=["GEMUP"],
    )
    tickers = [r["ticker"] for r in rows]
    assert "GAPPER" in tickers          # material gap
    assert "GEMUP" in tickers           # material gap on a gem
    assert "MYPOS" in tickers           # small move BUT it's a holding
    assert "DRIFT" not in tickers       # small move, watch-only -> noise
    assert "DEADQ" not in tickers       # no premarket print


def test_rows_sorted_by_absolute_gap_and_flagged():
    rows = build_premarket_report(QUOTES, holdings=["MYPOS"], gems=["GEMUP"])
    assert rows[0]["ticker"] == "GAPPER"
    by = {r["ticker"]: r for r in rows}
    assert by["MYPOS"]["is_holding"] and not by["MYPOS"]["is_gem"]
    assert by["GEMUP"]["is_gem"] and not by["GEMUP"]["is_holding"]
    assert by["MYPOS"]["gap_pct"] == pytest.approx(-2.0)


def test_news_annotation_attached():
    rows = build_premarket_report(
        {"GAPPER": QUOTES["GAPPER"]},
        news={"GAPPER": {"count": 3, "tags": ["earnings"]}},
    )
    assert rows[0]["news_count"] == 3
    assert rows[0]["news_tags"] == ["earnings"]


def test_push_formatting_and_silence():
    assert format_premarket_push([]) is None
    rows = build_premarket_report(QUOTES, holdings=["MYPOS"], gems=["GEMUP"])
    title, body = format_premarket_push(rows)
    assert "Premarket" in title
    assert "GAPPER" in body and "💼 MYPOS" in body and "💎 GEMUP" in body
    assert "context, not signal" in body


def test_empty_quotes_no_rows():
    assert build_premarket_report({}) == []
