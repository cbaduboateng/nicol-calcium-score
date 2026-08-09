"""Reddit-attention overlay: mention counts as CONTEXT, never a gate.

Source: ApeWisdom's free API (aggregates r/wallstreetbets and friends).
X and Discord are deliberately absent — one is paywalled, the other is
private servers; pretending to cover them would be worse than saying so.

House position, printed wherever this surfaces: crowd attention on this
universe historically coincides with TOPS (see the PEAD inversion — the
sell-the-news effect), so a 🔥 marker is a caution flag, not a buy
signal. Whether that's true for OUR gems is a pre-registered hypothesis
(ledger id: reddit-attention-contrarian) that the daily scan log is now
accumulating data to answer: every scan records each gem's mention
count, and once there are >= 15 hot and >= 15 quiet gem signals per
walk-forward half, the forward returns decide.

Pure builders tested; the fetch degrades to {} like every ingest.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
CACHE_PATH = Path("data/cache/reddit_mentions.json")
CACHE_TTL_HOURS = 3.0
HOT_MIN_MENTIONS = 30       # below this, "spikes" are 3 posts vs 1
HOT_SPIKE_RATIO = 2.0       # mentions >= 2x yesterday's = spiking


def build_reddit_overlay(results: list[dict]) -> dict[str, dict]:
    """Normalise raw ApeWisdom rows to {ticker: {...}}. Pure."""
    out: dict[str, dict] = {}
    for row in results or []:
        try:
            t = str(row.get("ticker") or "").upper().strip()
            if not t:
                continue
            mentions = int(float(row.get("mentions") or 0))
            prev = int(float(row.get("mentions_24h_ago") or 0))
            rank = int(float(row.get("rank") or 0))
        except (TypeError, ValueError):
            continue
        out[t] = {
            "mentions": mentions,
            "mentions_24h_ago": prev,
            "rank": rank,
            "spike_ratio": (mentions / prev) if prev > 0 else float("inf"),
        }
    return out


def attention_label(entry: dict | None) -> str:
    """'viral' | 'elevated' | 'quiet' — thresholds fixed with the
    pre-registered hypothesis; do not tune them after looking at data."""
    if not entry:
        return "quiet"
    mentions = entry.get("mentions", 0)
    if mentions < HOT_MIN_MENTIONS:
        return "quiet"
    if entry.get("spike_ratio", 0.0) >= HOT_SPIKE_RATIO:
        return "viral"
    return "elevated"


def format_gem_mentions(
    gem_tickers: list[str], overlay: dict[str, dict],
) -> str:
    """Compact 'TICKER:mentions' log line for the scan log — the raw
    material of the forward test."""
    return " ".join(
        f"{t}:{(overlay.get(t) or {}).get('mentions', 0)}"
        for t in gem_tickers
    )


def load_reddit_overlay(
    *, pages: int = 3, cache_path: Path | str = CACHE_PATH,
    ttl_hours: float = CACHE_TTL_HOURS,
) -> dict[str, dict]:
    """Fetch (or serve cached) mention data. {} on any failure."""
    cache_path = Path(cache_path)
    if cache_path.exists():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600.0
        if age_h < ttl_hours:
            try:
                return json.loads(cache_path.read_text())
            except Exception:  # noqa: BLE001
                pass
    try:
        import requests
        results: list[dict] = []
        for page in range(1, pages + 1):
            r = requests.get(APEWISDOM_URL.format(page=page), timeout=15)
            r.raise_for_status()
            payload = r.json() or {}
            results.extend(payload.get("results") or [])
            if page >= int(payload.get("pages") or 1):
                break
        overlay = build_reddit_overlay(results)
        if overlay:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(overlay))
        return overlay
    except Exception as exc:  # noqa: BLE001
        log.warning("Reddit overlay fetch failed (%s)", exc)
        try:
            return json.loads(cache_path.read_text())
        except Exception:  # noqa: BLE001
            return {}
