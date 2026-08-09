"""Short-interest positioning: who is against the stock, and how hard.

FINRA short-interest data via yfinance ``.info`` (sharesShort,
shortRatio = days-to-cover, shortPercentOfFloat), cached nightly by the
warm job. Bi-monthly data with a lag — positioning context, not a
signal, and it never scores or gates.

Framing thresholds (fixed conventions, not tuned):
  battleground : >= 15% of float short — squeeze fuel AND informed
                 conviction against; expect violence both ways
  elevated     : >= 7% — a real bear contingent
  normal       : below that
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

POSITIONING_CACHE_PATH = Path("data/cache/positioning_v1.json")
BATTLEGROUND_PCT = 15.0
ELEVATED_PCT = 7.0


def fetch_positioning(tickers: list[str], *, max_workers: int = 8) -> dict[str, dict]:
    """Threaded ``.info`` pulls; entries appear only when Yahoo carries
    short data for the name (mostly US listings)."""
    out: dict[str, dict] = {}
    if not tickers:
        return out
    try:
        import yfinance as yf
    except ImportError:
        return out
    from concurrent.futures import ThreadPoolExecutor

    from .symbols import normalize_symbol

    def _one(t: str) -> tuple[str, dict | None]:
        try:
            info = yf.Ticker(normalize_symbol(t)).info or {}
        except Exception as exc:  # noqa: BLE001
            log.debug("positioning failed for %s: %s", t, exc)
            return t, None
        spf = info.get("shortPercentOfFloat")
        shares_short = info.get("sharesShort")
        if spf is None and not shares_short:
            return t, None
        return t.upper(), {
            "short_pct_float": (float(spf) * 100.0) if spf is not None else None,
            "days_to_cover": (float(info["shortRatio"])
                              if info.get("shortRatio") else None),
            "shares_short": float(shares_short) if shares_short else None,
            "float_shares": (float(info["floatShares"])
                             if info.get("floatShares") else None),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for t, entry in ex.map(_one, tickers):
            if entry:
                out[t] = entry
    return out


def load_positioning(
    path: Path | str = POSITIONING_CACHE_PATH,
) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {}


def positioning_label(entry: dict | None) -> str:
    """'battleground' | 'elevated' | 'normal' | 'unknown'."""
    if not entry or entry.get("short_pct_float") is None:
        return "unknown"
    pct = float(entry["short_pct_float"])
    if pct >= BATTLEGROUND_PCT:
        return "battleground"
    if pct >= ELEVATED_PCT:
        return "elevated"
    return "normal"


def positioning_note(entry: dict | None) -> str | None:
    """One-line ticker-card note; None when there is nothing to say."""
    label = positioning_label(entry)
    if label == "unknown":
        return None
    pct = float(entry["short_pct_float"])
    dtc = entry.get("days_to_cover")
    bits = [f"{pct:.1f}% of float sold short"]
    if dtc:
        bits.append(f"{dtc:.1f} days to cover")
    body = " · ".join(bits)
    if label == "battleground":
        return (f"🩳 **Battleground stock** — {body}. Heavy squeeze fuel AND "
                "heavy informed conviction against it: expect violence in "
                "both directions, and know rallies may be forced covering "
                "rather than real accumulation.")
    if label == "elevated":
        return f"🩳 Elevated short interest — {body}."
    return None
