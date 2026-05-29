"""Configuration loader.

Reads `config/config.yaml`, allows environment overrides via
`CONGRESS_SIGNAL_<DOTTED_KEY>` (with `__` representing dots), e.g.
`CONGRESS_SIGNAL_SCORING__ACTOR_QUALITY__WEIGHTS__COMMITTEE_RELEVANCE=0.4`.
"""

from __future__ import annotations

import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.yaml"


def _coerce(value: str) -> Any:
    """Best-effort string -> Python coercion for environment overrides."""
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if lower == "none" or lower == "null":
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    prefix = "CONGRESS_SIGNAL_"
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        path = env_key[len(prefix):].lower().split("__")
        cursor: dict[str, Any] = cfg
        for part in path[:-1]:
            if part not in cursor or not isinstance(cursor[part], dict):
                cursor[part] = {}
            cursor = cursor[part]
        cursor[path[-1]] = _coerce(env_val)
    return cfg


@lru_cache(maxsize=1)
def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load configuration once and cache it."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return _apply_env_overrides(deepcopy(cfg))


def reset_config_cache() -> None:
    """Clear the cached config; useful in tests."""
    load_config.cache_clear()
