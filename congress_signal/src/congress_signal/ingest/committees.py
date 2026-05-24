"""Committee-membership ingester.

Loads `legislators-current.yaml` + `committee-membership-current.yaml` from
the `unitedstates/congress-legislators` repo and produces an
`actor_id → Actor` lookup with committees populated. Cached as parquet so
repeat scoring runs are instant.

Falls back to a small synthetic actor list when the network is unavailable.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..schema import Actor, Chamber

log = logging.getLogger(__name__)

LEGISLATORS_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
COMMITTEES_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committee-membership-current.yaml"


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type((requests.RequestException,)),
)
def _fetch_yaml(url: str, timeout: float = 60.0) -> Any:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return yaml.safe_load(resp.text)


def _cache_path(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "committees.json"


def _is_fresh(cache_file: Path, max_age_days: int = 7) -> bool:
    if not cache_file.exists():
        return False
    age = date.today() - date.fromtimestamp(cache_file.stat().st_mtime)
    return age <= timedelta(days=max_age_days)


def load_committee_actors(cache_dir: Path | str = "data/cache") -> list[Actor]:
    """Return a list of `Actor` objects with committees populated.

    Result is JSON-cached for 7 days. On network failure, returns the small
    synthetic actor list so the pipeline can still run.
    """
    cache_dir = Path(cache_dir)
    cache_file = _cache_path(cache_dir)

    if _is_fresh(cache_file):
        try:
            with cache_file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            return [Actor(**a) for a in payload]
        except Exception as exc:
            log.warning("Committees cache unreadable (%s); refetching", exc)

    try:
        legislators = _fetch_yaml(LEGISLATORS_URL)
        committee_membership = _fetch_yaml(COMMITTEES_URL)
    except Exception as exc:
        log.warning("Committee fetch failed (%s); using synthetic actors", exc)
        from .synthetic import synthetic_actors
        return synthetic_actors()

    # Build bioguide → set of committee names.
    by_bioguide: dict[str, set[str]] = {}
    for committee_id, members in committee_membership.items():
        for m in members:
            bio = m.get("bioguide")
            if not bio:
                continue
            by_bioguide.setdefault(bio, set()).add(committee_id)

    actors: list[Actor] = []
    for leg in legislators:
        bio = leg.get("id", {}).get("bioguide")
        if not bio:
            continue
        latest_term = (leg.get("terms") or [{}])[-1]
        chamber_raw = latest_term.get("type")  # "rep" / "sen"
        if chamber_raw == "rep":
            chamber = Chamber.HOUSE
        elif chamber_raw == "sen":
            chamber = Chamber.SENATE
        else:
            continue
        name_parts = leg.get("name", {})
        name = f"{name_parts.get('first', '')} {name_parts.get('last', '')}".strip()
        actors.append(Actor(
            actor_id=bio,
            name=name or bio,
            chamber=chamber,
            party=latest_term.get("party"),
            state=latest_term.get("state"),
            district=str(latest_term.get("district")) if latest_term.get("district") is not None else None,
            committees=tuple(sorted(by_bioguide.get(bio, set()))),
        ))

    try:
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump([a.model_dump() for a in actors], f, default=str)
    except Exception as exc:
        log.debug("Could not write committees cache (%s)", exc)

    log.info("Loaded %d actors with committee assignments", len(actors))
    return actors


def actor_by_bioguide(actors: list[Actor]) -> dict[str, Actor]:
    return {a.actor_id: a for a in actors}
