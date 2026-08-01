"""Tests for the Explorer universe symbol-directory parser."""

from __future__ import annotations

from icarus.universe import load_explorer_watchlist, parse_symbol_directory


NASDAQ_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
ZAZZT|Test Symbol|Q|Y|N|100|N|N
QQQ|Invesco QQQ Trust|G|N|N|100|Y|N
ABCW|ABC Corp - Warrant|Q|N|N|100|N|N
ABC|ABC Corp - Common Stock|Q|N|N|100|N|N
File Creation Time: 0131202518:01|||||||
"""

OTHER_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
HL|Hecla Mining Company|N|HL|N|100|N|HL
BRK.A|Berkshire Hathaway Class A|N|BRK.A|N|1|N|BRK$A
SPY|SPDR S&P 500 ETF|P|SPY|Y|100|N|SPY
PFD|Some Preferred Series B|N|PFD|N|100|N|PFD
File Creation Time: 0131202518:01|||||||
"""


def test_parses_common_stock_and_drops_test_issues_and_etfs():
    df = parse_symbol_directory(NASDAQ_SAMPLE, symbol_col="Symbol")
    tickers = set(df["ticker"])
    assert "AAPL" in tickers
    assert "ABC" in tickers
    assert "ZAZZT" not in tickers   # test issue
    assert "QQQ" not in tickers     # ETF
    assert "ABCW" not in tickers    # warrant (by name fragment)


def test_drops_multi_class_dot_symbols_and_preferred():
    df = parse_symbol_directory(OTHER_SAMPLE, symbol_col="ACT Symbol")
    tickers = set(df["ticker"])
    assert "HL" in tickers
    assert "BRK.A" not in tickers   # non-alpha symbol
    assert "SPY" not in tickers     # ETF
    assert "PFD" not in tickers     # preferred (by name fragment)


def test_footer_row_is_dropped():
    df = parse_symbol_directory(NASDAQ_SAMPLE, symbol_col="Symbol")
    assert not df["ticker"].str.contains("FILE", na=False).any()


def test_load_explorer_watchlist_missing_file_is_empty(tmp_path):
    df = load_explorer_watchlist(tmp_path / "nope.csv")
    assert df.empty
    assert list(df.columns) == [
        "ticker", "name", "description", "target_entry", "target_exit",
    ]
