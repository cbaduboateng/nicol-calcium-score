"""Ticker-symbol normalisation: Google Finance notation → Yahoo notation.

The watchlist was curated in Google Sheets, whose GOOGLEFINANCE() uses
exchange *prefixes* (``LON:THG``, ``EPA:KER``, ``TPE:2330``). yfinance
wraps Yahoo, which uses exchange *suffixes* (``THG.L``, ``KER.PA``,
``2330.TW``) and bare symbols for US listings. Every prefixed ticker
fails silently on Yahoo without this translation.

The app keys everything by the ORIGINAL watchlist ticker; normalisation
happens only at the data-fetch boundary, so the user's CSV never needs
rewriting.
"""

from __future__ import annotations

# Google Finance exchange prefix -> Yahoo suffix
_PREFIX_SUFFIX: dict[str, str] = {
    "LON": ".L",     # London
    "EPA": ".PA",    # Euronext Paris
    "ETR": ".DE",    # Xetra
    "FRA": ".F",     # Frankfurt floor
    "AMS": ".AS",    # Euronext Amsterdam
    "EBR": ".BR",    # Euronext Brussels
    "ELI": ".LS",    # Euronext Lisbon
    "BIT": ".MI",    # Borsa Italiana
    "MIL": ".MI",
    "STO": ".ST",    # Stockholm
    "CPH": ".CO",    # Copenhagen
    "HEL": ".HE",    # Helsinki
    "OSL": ".OL",    # Oslo
    "SWX": ".SW",    # SIX Swiss
    "VIE": ".VI",    # Vienna
    "WSE": ".WA",    # Warsaw
    "BME": ".MC",    # Madrid
    "TSE": ".TO",    # Toronto (Google uses TYO: for Tokyo)
    "CVE": ".V",     # TSX Venture
    "ASX": ".AX",    # Australia
    "NZE": ".NZ",    # New Zealand
    "TYO": ".T",     # Tokyo
    "HKG": ".HK",    # Hong Kong (numeric, zero-padded to 4)
    "KRX": ".KS",    # Korea
    "KOSDAQ": ".KQ",
    "TPE": ".TW",    # Taiwan
    "BOM": ".BO",    # Bombay
    "NSE": ".NS",    # India NSE
    "SGX": ".SI",    # Singapore
    "JSE": ".JO",    # Johannesburg
    "SHA": ".SS",    # Shanghai
    "SHE": ".SZ",    # Shenzhen
}

# US exchanges: Yahoo wants the bare symbol.
_US_PREFIXES: frozenset[str] = frozenset({
    "NYSE", "NASDAQ", "AMEX", "BATS", "NYSEARCA", "NYSEAMERICAN",
    "OTCMKTS", "OTC", "CBOE",
})


def normalize_symbol(ticker: str) -> str:
    """Translate one watchlist ticker to its Yahoo Finance symbol.

    Unknown prefixes fall back to the bare symbol (best effort); tickers
    without a prefix pass through unchanged.
    """
    t = (ticker or "").strip().upper()
    if not t or ":" not in t:
        return t
    prefix, sym = t.split(":", 1)
    sym = sym.strip()
    if not sym:
        return t
    if prefix in _US_PREFIXES:
        return sym
    suffix = _PREFIX_SUFFIX.get(prefix)
    if suffix is None:
        return sym
    if prefix == "HKG" and sym.isdigit():
        sym = sym.zfill(4)
    return sym + suffix


def yahoo_symbol_map(tickers: list[str]) -> dict[str, str]:
    """Map each original ticker to its Yahoo symbol. Collisions (e.g.
    ``NYSE:HL`` and ``HL`` both present) simply share the same data."""
    return {t: normalize_symbol(t) for t in tickers}
