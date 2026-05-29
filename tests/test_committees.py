from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from icarus.ingest import committees


FAKE_LEGISLATORS = [
    {
        "id": {"bioguide": "A000001"},
        "name": {"first": "Alex", "last": "Defence"},
        "terms": [
            {"type": "rep", "party": "Republican", "state": "TX", "district": 1},
        ],
    },
    {
        "id": {"bioguide": "S000001"},
        "name": {"first": "Eli", "last": "Energy"},
        "terms": [
            {"type": "sen", "party": "Democrat", "state": "VA"},
        ],
    },
]

FAKE_COMMITTEES = {
    "HSAS00": [{"bioguide": "A000001"}],
    "SSEG00": [{"bioguide": "S000001"}],
}


def test_load_committee_actors_from_mocked_yaml(tmp_path: Path):
    with patch.object(committees, "_fetch_yaml", side_effect=[FAKE_LEGISLATORS, FAKE_COMMITTEES]):
        actors = committees.load_committee_actors(tmp_path)
    assert len(actors) == 2
    by_id = {a.actor_id: a for a in actors}
    assert by_id["A000001"].chamber.value == "house"
    assert by_id["A000001"].committees == ("HSAS00",)
    assert by_id["S000001"].chamber.value == "senate"


def test_load_falls_back_to_synthetic_on_network_failure(tmp_path: Path):
    with patch.object(committees, "_fetch_yaml", side_effect=Exception("network down")):
        actors = committees.load_committee_actors(tmp_path)
    assert actors  # synthetic generator returns a non-empty list


def test_cache_is_used_when_fresh(tmp_path: Path):
    with patch.object(committees, "_fetch_yaml", side_effect=[FAKE_LEGISLATORS, FAKE_COMMITTEES]):
        first = committees.load_committee_actors(tmp_path)
    # Second call should hit the cache; if it tried to fetch, the side_effect
    # iterator would raise StopIteration.
    with patch.object(committees, "_fetch_yaml", side_effect=AssertionError("should not refetch")):
        second = committees.load_committee_actors(tmp_path)
    assert [a.actor_id for a in first] == [a.actor_id for a in second]
