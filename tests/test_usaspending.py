from __future__ import annotations

from datetime import date
from unittest.mock import patch

from icarus.ingest import usaspending


def test_normalise_recipient_known():
    assert usaspending.normalise_recipient("LOCKHEED MARTIN CORPORATION") == "LMT"
    assert usaspending.normalise_recipient("lockheed martin corporation") == "LMT"


def test_normalise_recipient_unknown_returns_none():
    assert usaspending.normalise_recipient("Acme Bagels Inc") is None


def test_awards_by_ticker_aggregates_known_recipients():
    fake_rows = [
        {"Recipient Name": "LOCKHEED MARTIN CORPORATION", "Award Amount": 50_000_000.0},
        {"Recipient Name": "LOCKHEED MARTIN CORPORATION", "Award Amount": 25_000_000.0},
        {"Recipient Name": "RTX CORPORATION", "Award Amount": 10_000_000.0},
        {"Recipient Name": "Unknown Subcontractor LLC", "Award Amount": 99_000_000.0},
    ]
    with patch.object(usaspending, "fetch_awards", return_value=fake_rows):
        totals = usaspending.awards_by_ticker(date(2024, 1, 1), date(2024, 12, 31))
    assert totals == {"LMT": 75_000_000.0, "RTX": 10_000_000.0}


def test_fetch_awards_returns_empty_on_failure():
    with patch.object(usaspending, "_post", side_effect=Exception("network down")):
        rows = usaspending.fetch_awards(date(2024, 1, 1), date(2024, 12, 31))
    assert rows == []
