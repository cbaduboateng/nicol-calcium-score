from __future__ import annotations

from datetime import date
from unittest.mock import patch

import requests

from congress_signal.ingest.quiver import QuiverClient


FAKE_ROWS = [
    {
        "Representative": "Alex Defence",
        "BioguideID": "A000001",
        "Ticker": "LMT",
        "TransactionDate": "2024-09-15",
        "ReportDate": "2024-09-30",
        "Transaction": "Purchase",
        "Amount": "$50,001 - $100,000",
    },
    {
        "Representative": "Bea Energy",
        "BioguideID": "B000002",
        "Ticker": "RTX",
        "TransactionDate": "2024-08-10",
        "ReportDate": "2024-08-25",
        "Transaction": "Sale (Full)",
        "Amount": "$15,001 - $50,000",
    },
]


def test_quiver_parses_rows_when_api_succeeds():
    client = QuiverClient(api_key="dummy")
    with patch.object(client, "_fetch_raw", return_value=FAKE_ROWS):
        trades = client.congress_trades(since=date(2024, 1, 1))
    assert len(trades) == 2
    by_ticker = {t.ticker: t for t in trades}
    assert by_ticker["LMT"].direction.value == "buy"
    assert by_ticker["RTX"].direction.value == "sell"
    assert by_ticker["LMT"].amount_min_usd == 50_001


def test_quiver_falls_back_to_synthetic_on_failure():
    client = QuiverClient()  # no key set
    with patch.object(client, "_fetch_raw", side_effect=requests.ConnectionError("down")):
        trades = client.congress_trades(since=date(2024, 1, 1))
    assert trades  # synthetic generator returns a non-empty list


def test_quiver_skips_rows_without_ticker():
    client = QuiverClient(api_key="dummy")
    rows = FAKE_ROWS + [{"Representative": "X", "TransactionDate": "2024-01-01"}]
    with patch.object(client, "_fetch_raw", return_value=rows):
        trades = client.congress_trades(since=date(2024, 1, 1))
    assert len(trades) == 2
