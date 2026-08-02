"""Tests for the portfolio average-cost engine and totals."""

from __future__ import annotations

import pandas as pd
import pytest

from icarus.portfolio import (
    empty_trades,
    new_trade,
    normalise_trades,
    portfolio_totals,
    positions_from_trades,
)


def _t(ticker, side, qty, price, d):
    return {"id": "", "date": d, "ticker": ticker, "side": side,
            "qty": qty, "price": price, "note": ""}


def test_buys_average_the_cost():
    trades = pd.DataFrame([
        _t("HIVE", "buy", 100, 2.00, "2026-01-05"),
        _t("HIVE", "buy", 100, 4.00, "2026-02-05"),
    ])
    pos, realised = positions_from_trades(trades)
    assert len(pos) == 1
    p = pos.iloc[0]
    assert p["qty"] == pytest.approx(200)
    assert p["avg_cost"] == pytest.approx(3.00)
    assert p["invested"] == pytest.approx(600.0)
    assert realised.empty


def test_partial_sell_realises_against_average_cost():
    trades = pd.DataFrame([
        _t("HIVE", "buy", 100, 2.00, "2026-01-05"),
        _t("HIVE", "buy", 100, 4.00, "2026-02-05"),
        _t("HIVE", "sell", 50, 5.00, "2026-03-05"),
    ])
    pos, realised = positions_from_trades(trades)
    p = pos.iloc[0]
    assert p["qty"] == pytest.approx(150)
    assert p["avg_cost"] == pytest.approx(3.00)   # sells don't move the average
    r = realised.iloc[0]
    assert r["realised_pnl"] == pytest.approx((5.00 - 3.00) * 50)
    assert not r["oversold"]


def test_full_exit_removes_position():
    trades = pd.DataFrame([
        _t("AAA", "buy", 10, 1.00, "2026-01-05"),
        _t("AAA", "sell", 10, 2.00, "2026-01-06"),
    ])
    pos, realised = positions_from_trades(trades)
    assert pos.empty
    assert realised.iloc[0]["realised_pnl"] == pytest.approx(10.0)


def test_oversell_is_clamped_and_flagged():
    trades = pd.DataFrame([
        _t("AAA", "buy", 10, 1.00, "2026-01-05"),
        _t("AAA", "sell", 25, 2.00, "2026-01-06"),
    ])
    pos, realised = positions_from_trades(trades)
    assert pos.empty
    r = realised.iloc[0]
    assert r["qty"] == pytest.approx(10)          # clamped to holdings
    assert r["realised_pnl"] == pytest.approx(10.0)
    assert bool(r["oversold"]) is True


def test_multi_ticker_isolation():
    trades = pd.DataFrame([
        _t("AAA", "buy", 10, 1.00, "2026-01-05"),
        _t("BBB", "buy", 5, 10.00, "2026-01-05"),
        _t("AAA", "sell", 10, 3.00, "2026-01-06"),
    ])
    pos, realised = positions_from_trades(trades)
    assert set(pos["ticker"]) == {"BBB"}
    assert set(realised["ticker"]) == {"AAA"}


def test_normalise_drops_junk_and_fills_ids():
    df = pd.DataFrame([
        {"date": "2026-01-05", "ticker": " hive ", "side": "BUY",
         "qty": "100", "price": "2.5"},
        {"date": "not-a-date", "ticker": "BAD", "side": "buy",
         "qty": "10", "price": "1"},
        {"date": "2026-01-06", "ticker": "ZERO", "side": "buy",
         "qty": "0", "price": "1"},
    ])
    out = normalise_trades(df)
    assert len(out) == 1
    assert out.iloc[0]["ticker"] == "HIVE"
    assert out.iloc[0]["side"] == "buy"
    assert out.iloc[0]["id"]  # generated


def test_totals_with_quotes_and_fallback():
    trades = pd.DataFrame([
        _t("AAA", "buy", 10, 10.00, "2026-01-05"),   # invested 100
        _t("BBB", "buy", 10, 5.00, "2026-01-05"),    # invested 50, no quote
    ])
    pos, _ = positions_from_trades(trades)
    quotes = {"AAA": {"price": 12.0, "prev_close": 11.0}}
    t = portfolio_totals(pos, quotes)
    # AAA valued live (120), BBB falls back to cost (50)
    assert t["value"] == pytest.approx(170.0)
    assert t["invested"] == pytest.approx(150.0)
    assert t["unrealised"] == pytest.approx(20.0)
    assert t["day_pnl"] == pytest.approx(10.0)       # 10 shares x (12-11)
    assert t["n_priced"] == 1 and t["n_positions"] == 2


def test_stop_breaches_flags_breached_and_near():
    from icarus.portfolio import stop_breaches
    trades = pd.DataFrame([
        _t("GONE", "buy", 10, 10.00, "2026-01-05"),   # stop 8.80
        _t("NEAR", "buy", 10, 10.00, "2026-01-05"),   # stop 8.80
        _t("SAFE", "buy", 10, 10.00, "2026-01-05"),
        _t("NOPX", "buy", 10, 10.00, "2026-01-05"),
    ])
    pos, _ = positions_from_trades(trades)
    closes = {"GONE": 8.50, "NEAR": 8.95, "SAFE": 11.00}
    out = stop_breaches(pos, closes)
    by = out.set_index("ticker")
    assert by.loc["GONE", "state"] == "breached"
    assert by.loc["NEAR", "state"] == "near"
    assert "SAFE" not in by.index
    assert "NOPX" not in by.index          # unpriced skipped, reported by caller
    assert by.loc["GONE", "stop"] == pytest.approx(8.80)


def test_stop_breaches_respects_custom_stop_pct():
    from icarus.portfolio import stop_breaches
    trades = pd.DataFrame([_t("AAA", "buy", 10, 10.00, "2026-01-05")])
    pos, _ = positions_from_trades(trades)
    # At 20% stop (8.00), a 8.50 close is safe-ish (6.25% above, > 3% band)
    out = stop_breaches(pos, {"AAA": 8.50}, stop_pct=0.20)
    assert out.empty


def test_stop_breaches_empty_positions():
    from icarus.portfolio import stop_breaches
    pos, _ = positions_from_trades(empty_trades())
    assert stop_breaches(pos, {"AAA": 1.0}).empty


def test_new_trade_and_empty_frames():
    tr = new_trade("hive", "buy", 100, 2.87)
    assert tr["ticker"] == "HIVE" and tr["id"]
    pos, realised = positions_from_trades(empty_trades())
    assert pos.empty and realised.empty
