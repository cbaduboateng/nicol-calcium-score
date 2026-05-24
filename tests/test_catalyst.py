from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from congress_signal.scoring import catalyst


def test_dod_calendar_emits_year_end_events():
    today = date(2024, 8, 1)
    horizon = today + timedelta(days=120)
    events = catalyst.dod_obligation_calendar(horizon, today=today)
    assert events
    assert all(e.event_date == date(2024, 9, 30) for e in events)
    assert "LMT" in {e.ticker for e in events}


def test_dod_calendar_skips_past_window():
    today = date(2024, 11, 1)
    horizon = today + timedelta(days=30)  # well before next year's 9/30
    events = catalyst.dod_obligation_calendar(horizon, today=today)
    assert events == []


def test_usaspending_catalysts_joins_recipient_to_ticker():
    fake = [{
        "Recipient Name": "LOCKHEED MARTIN CORPORATION",
        "Award Amount": 100_000_000.0,
        "Period of Performance Start Date": "2024-07-01",
    }]
    with patch.object(catalyst, "fetch_awards", return_value=fake):
        events = catalyst.usaspending_catalysts(today=date(2024, 8, 1))
    assert len(events) == 1
    assert events[0].ticker == "LMT"


def test_build_calendar_combines_sources():
    today = date(2024, 1, 1)
    with patch.object(catalyst, "fetch_awards", return_value=[]):
        events = catalyst.build_calendar(horizon_days=365, today=today)
    assert any(e.category == "dod_obligation_cycle" for e in events)
