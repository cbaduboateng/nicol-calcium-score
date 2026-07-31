"""Tests for Google Finance → Yahoo symbol normalisation."""

from __future__ import annotations

from icarus.symbols import normalize_symbol, yahoo_symbol_map


def test_london_prefix_becomes_l_suffix():
    assert normalize_symbol("LON:THG") == "THG.L"
    assert normalize_symbol("LON:SHOE") == "SHOE.L"


def test_paris_and_xetra():
    assert normalize_symbol("EPA:KER") == "KER.PA"
    assert normalize_symbol("ETR:DPW") == "DPW.DE"


def test_us_prefixes_strip_to_bare_symbol():
    assert normalize_symbol("NYSE:HL") == "HL"
    assert normalize_symbol("NASDAQ:AAPL") == "AAPL"
    assert normalize_symbol("OTCMKTS:TCEHY") == "TCEHY"


def test_taiwan_toronto_and_swiss():
    assert normalize_symbol("TPE:2330") == "2330.TW"
    assert normalize_symbol("TSE:AIF") == "AIF.TO"
    assert normalize_symbol("SWX:ABBN") == "ABBN.SW"


def test_hong_kong_pads_to_four_digits():
    assert normalize_symbol("HKG:700") == "0700.HK"
    assert normalize_symbol("HKG:9988") == "9988.HK"


def test_plain_and_already_yahoo_symbols_pass_through():
    assert normalize_symbol("AAPL") == "AAPL"
    assert normalize_symbol("VOD.L") == "VOD.L"
    assert normalize_symbol("BTC-USD") == "BTC-USD"
    assert normalize_symbol("brk-b") == "BRK-B"


def test_unknown_prefix_falls_back_to_bare_symbol():
    assert normalize_symbol("WEIRD:XYZ") == "XYZ"


def test_empty_and_whitespace():
    assert normalize_symbol("") == ""
    assert normalize_symbol("  lon:thg ") == "THG.L"


def test_yahoo_symbol_map_handles_collisions():
    m = yahoo_symbol_map(["NYSE:HL", "HL", "LON:THG"])
    assert m["NYSE:HL"] == "HL"
    assert m["HL"] == "HL"          # collision: both map to the same data
    assert m["LON:THG"] == "THG.L"
