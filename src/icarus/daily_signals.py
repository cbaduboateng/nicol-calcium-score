"""Daily action ranking: which BUY ZONE stock deserves attention TODAY.

The watchlist tells you *which* stocks are in their buy zone; this module
answers *which one today*. It layers day-scale signals on top of the
zone status:

  rel_volume   today's volume / trailing 20-day average. The best free
               "something is happening right now" indicator — a stock in
               the buy zone on 3x normal volume is a different trade
               from one drifting sideways on no interest.
  freshness    days spent consecutively in the buy zone. A stock that
               crossed in TODAY is a fresh setup; one that's sat there
               for four months is dead money until proven otherwise.
  pct_1d/5d    is the bounce already starting?
  news_count   headlines in the last 48h (yfinance feed, cached, flaky —
               a bonus signal, never a gate) + catalyst keyword tags.

Today score (0-1):
  0.30  rel_volume through a logistic centred at 1.5x
  0.25  freshness (1.0 crossed today, decaying to 0 over ~20 sessions)
  0.15  5-day momentum through a logistic
  0.15  theme heat (theme 3m median through the same logistic)
  0.15  reward:risk to the analyst exit, clipped at 5
  +0.10 news bonus (capped): 0.05 per headline in 48h, up to 2

Pure functions throughout except ``fetch_news_counts`` which hits the
network (cached to disk, 6h TTL) and is kept separate so the scoring
stays testable.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


REL_VOLUME_MIDPOINT = 1.5      # logistic centre: 1.5x average volume = notable
FRESHNESS_DECAY_SESSIONS = 20  # freshness fades to ~0 over a trading month
NEWS_CACHE_TTL_HOURS = 6.0
NEWS_WINDOW_HOURS = 48.0

_CATALYST_KEYWORDS = (
    ("fda", "FDA"), ("approval", "approval"), ("contract", "contract"),
    ("award", "award"), ("earnings", "earnings"), ("guidance", "guidance"),
    ("upgrade", "upgrade"), ("downgrade", "downgrade"),
    ("merger", "M&A"), ("acquisition", "M&A"), ("acquire", "M&A"),
    ("partnership", "partnership"), ("patent", "patent"),
    ("offering", "offering/dilution"), ("dilution", "offering/dilution"),
)


def _logistic(x: float, midpoint: float = 0.0, steepness: float = 3.0) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if x < midpoint else 1.0


def relative_volume(volumes: pd.Series | None, *, window: int = 20) -> float:
    """Latest volume / mean of the prior `window` days. NaN when unknown."""
    if volumes is None:
        return float("nan")
    v = volumes.dropna()
    if len(v) < window + 1:
        return float("nan")
    latest = float(v.iloc[-1])
    base = float(v.iloc[-(window + 1):-1].mean())
    if base <= 0:
        return float("nan")
    return latest / base


def days_in_zone(history: pd.Series | None, target_entry: float | None) -> int:
    """Consecutive most-recent sessions with close at or below the entry.
    0 = not currently in the zone. 1 = crossed in today."""
    if (history is None or target_entry is None
            or not np.isfinite(target_entry) or target_entry <= 0):
        return 0
    closes = history.dropna()
    if closes.empty:
        return 0
    n = 0
    for px in reversed(closes.values.tolist()):
        if float(px) <= target_entry:
            n += 1
        else:
            break
    return n


def pct_change_over(history: pd.Series | None, sessions: int) -> float:
    """% change over the last `sessions` trading days."""
    if history is None:
        return float("nan")
    closes = history.dropna()
    if len(closes) <= sessions:
        return float("nan")
    prev = float(closes.iloc[-(sessions + 1)])
    last = float(closes.iloc[-1])
    if prev <= 0:
        return float("nan")
    return (last - prev) / prev * 100.0


def _freshness_score(dz: int) -> float:
    """1.0 for crossed-today, linear decay to 0 over the decay window."""
    if dz <= 0:
        return 0.0
    return max(0.0, 1.0 - (dz - 1) / FRESHNESS_DECAY_SESSIONS)


def _rr_score(rr: float | None) -> float:
    if rr is None or not np.isfinite(rr) or rr <= 0:
        return 0.5
    return float(min(rr / 5.0, 1.0))


def compute_daily_signals(
    view: pd.DataFrame,
    price_history: dict[str, pd.Series],
    volume_history: dict[str, pd.Series] | None = None,
    *,
    news_counts: dict[str, dict] | None = None,
    theme_3m: dict[str, float] | None = None,
    statuses: tuple[str, ...] = ("BUY ZONE",),
    top_n: int = 5,
) -> pd.DataFrame:
    """Rank today's actionable stocks. Returns the top N with reasons.

    ``view`` is the standard watchlist view (needs ticker, status, theme,
    target_entry, reward_risk columns). Only rows whose status is in
    ``statuses`` are considered.
    """
    if view is None or view.empty:
        return pd.DataFrame()
    vols = volume_history or {}
    news = news_counts or {}
    themes = theme_3m or {}

    rows: list[dict] = []
    for _, r in view.iterrows():
        status = r.get("status")
        if status not in statuses:
            continue
        ticker = str(r.get("ticker") or "").upper()
        hist = price_history.get(ticker)
        entry = r.get("target_entry")

        rv = relative_volume(vols.get(ticker))
        dz = days_in_zone(hist, float(entry) if pd.notna(entry) else None)
        p1 = pct_change_over(hist, 1)
        p5 = pct_change_over(hist, 5)

        s_vol = _logistic(rv, midpoint=REL_VOLUME_MIDPOINT) if np.isfinite(rv) else 0.5
        s_fresh = _freshness_score(dz)
        s_mom = _logistic(p5 / 100.0, steepness=8.0) if np.isfinite(p5) else 0.5
        t3 = themes.get(r.get("theme"))
        s_theme = (
            _logistic(t3 / 100.0, steepness=3.0)
            if t3 is not None and np.isfinite(t3) else 0.5
        )
        s_rr = _rr_score(r.get("reward_risk"))

        n_info = news.get(ticker) or {}
        n_count = int(n_info.get("count", 0) or 0)
        news_bonus = min(0.10, 0.05 * n_count)

        score = (
            0.30 * s_vol + 0.25 * s_fresh + 0.15 * s_mom
            + 0.15 * s_theme + 0.15 * s_rr + news_bonus
        )
        score = float(np.clip(score, 0.0, 1.0))

        reasons: list[str] = []
        if dz == 1:
            reasons.append("crossed into the buy zone today")
        elif 1 < dz <= 5:
            reasons.append(f"in the buy zone {dz} sessions")
        if np.isfinite(rv) and rv >= 1.5:
            reasons.append(f"{rv:.1f}× average volume")
        if np.isfinite(p1) and abs(p1) >= 3:
            reasons.append(f"{p1:+.1f}% today")
        if np.isfinite(p5) and p5 > 0:
            reasons.append(f"{p5:+.1f}% over 5 days")
        if t3 is not None and np.isfinite(t3) and t3 > 0:
            reasons.append(f"hot theme ({t3:+.0f}% 3m median)")
        rr = r.get("reward_risk")
        if rr is not None and np.isfinite(rr) and rr >= 2:
            reasons.append(f"R:R {rr:.1f}")
        if n_count:
            tags = n_info.get("tags") or []
            tag_str = f" ({', '.join(tags[:3])})" if tags else ""
            reasons.append(f"{n_count} headline{'s' if n_count != 1 else ''} in 48h{tag_str}")

        rows.append({
            "ticker": ticker,
            "name": r.get("name"),
            "theme": r.get("theme"),
            "live_price": r.get("live_price"),
            "target_entry": entry,
            "target_exit": r.get("target_exit"),
            "today_score": score,
            "rel_volume": rv,
            "days_in_zone": dz,
            "pct_1d": p1,
            "pct_5d": p5,
            "news_count": n_count,
            "reasons": " · ".join(reasons) if reasons else "in the buy zone, quiet",
        })

    if not rows:
        return pd.DataFrame()
    out = (
        pd.DataFrame(rows)
        .sort_values("today_score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    out.insert(0, "rank", out.index + 1)
    return out


def find_gems(
    view: pd.DataFrame,
    price_history: dict[str, pd.Series],
    volume_history: dict[str, pd.Series] | None = None,
    *,
    news_counts: dict[str, dict] | None = None,
    congress_overlay: dict | None = None,
    catalyst_overlay: dict | None = None,
    strict_min_rr: float = 3.0,
    blowoff_threshold_pct: float = 100.0,
    min_market_cap_usd: float | None = None,
    max_market_cap_usd: float | None = None,
    require_known_cap: bool = False,
    top_n: int = 5,
) -> pd.DataFrame:
    """The intersection filter: quality gates AND day-scale signals.

    A gem must FIRST survive every strict hard gate (BUY ZONE, own 3m
    momentum > 0, theme 3m median > 0, R:R >= floor, not parabolic,
    optional cap band) and is THEN ranked by what's happening today
    (relative volume, freshness, 5d momentum, news).

    gem_score = 0.5 x quality composite + 0.5 x today score.

    Congress and catalyst overlays contribute soft weight inside the
    quality composite only — never a gate (STOCK Act filings lag up to
    45 days, so congressional buying is a tailwind, not a trigger).

    Empty most days by design: six signal families rarely agree.
    """
    from .watchlist_alerts import pick_winners, theme_heat

    if view is None or view.empty:
        return pd.DataFrame()

    survivors = pick_winners(
        view,
        top_n=100_000,
        strict_mode=True,
        strict_min_rr=strict_min_rr,
        blowoff_threshold_pct=blowoff_threshold_pct,
        min_market_cap_usd=min_market_cap_usd,
        max_market_cap_usd=max_market_cap_usd,
        require_known_cap=require_known_cap,
        congress_overlay=congress_overlay,
        catalyst_overlay=catalyst_overlay,
    )
    if survivors.empty:
        return pd.DataFrame()

    heat = theme_heat(view)  # theme temperature from the FULL watchlist
    theme_3m = (
        dict(zip(heat["theme"], heat["median_3m"])) if not heat.empty else {}
    )
    subset = view[view["ticker"].isin(set(survivors["ticker"]))]
    daily = compute_daily_signals(
        subset, price_history, volume_history,
        news_counts=news_counts, theme_3m=theme_3m,
        top_n=100_000,
    )
    if daily.empty:
        return pd.DataFrame()

    quality_cols = [c for c in (
        "ticker", "composite", "score_congress", "score_catalyst",
        "catalyst_days", "congress_summary",
    ) if c in survivors.columns]
    merged = daily.drop(columns=["rank"]).merge(
        survivors[quality_cols], on="ticker", how="inner",
    )
    if merged.empty:
        return pd.DataFrame()
    merged["gem_score"] = 0.5 * merged["composite"] + 0.5 * merged["today_score"]
    merged = (
        merged.sort_values("gem_score", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    merged.insert(0, "rank", merged.index + 1)
    return merged


def gem_gate_failures(
    row: pd.Series,
    theme_3m: dict[str, float] | None = None,
    *,
    min_rr: float = 3.0,
    blowoff_threshold_pct: float = 100.0,
) -> list[str]:
    """Explain which strict gates a candidate fails, in plain English.

    Used by the Gems empty state so 'no gems today' comes with the
    reason each near-miss didn't qualify — turning a dead end into a
    diagnostic. An empty return list means the row passes every gate."""
    themes = theme_3m or {}
    fails: list[str] = []

    if row.get("status") != "BUY ZONE":
        fails.append(f"not in buy zone ({row.get('status', '—')})")

    p3 = row.get("pct_3m")
    if p3 is None or not np.isfinite(p3) or p3 <= 0:
        if p3 is not None and np.isfinite(p3):
            fails.append(f"own 3m momentum negative ({p3:+.0f}%)")
        else:
            fails.append("3m momentum unknown")

    t3 = themes.get(row.get("theme"))
    if t3 is None or not np.isfinite(t3) or t3 <= 0:
        if t3 is not None and np.isfinite(t3):
            fails.append(f"theme cold ({row.get('theme')}: {t3:+.0f}% 3m median)")
        else:
            fails.append(f"theme momentum unknown ({row.get('theme')})")

    rr = row.get("reward_risk")
    if rr is None or not np.isfinite(rr):
        # inf means live <= entry — passes by design; NaN means no targets
        if rr is None or (isinstance(rr, float) and math.isnan(rr)):
            fails.append("no usable R:R (missing exit target)")
    elif rr < min_rr:
        fails.append(f"R:R {rr:.1f} below the {min_rr:.0f} floor")

    p6 = row.get("pct_6m")
    if p6 is not None and np.isfinite(p6) and p6 > blowoff_threshold_pct:
        fails.append(f"already parabolic ({p6:+.0f}% in 6m)")

    return fails


def fetch_news_counts(
    tickers: list[str],
    *,
    cache_dir: Path | str = "data/cache",
    window_hours: float = NEWS_WINDOW_HOURS,
    max_tickers: int = 60,
) -> dict[str, dict]:
    """Headline counts + catalyst keyword tags for the last `window_hours`.

    Uses yfinance's per-ticker news feed — flaky and rate-limit-prone, so
    only call this for the (small) BUY ZONE subset, never the whole
    watchlist. Disk-cached with a 6h TTL. Returns {} on total failure so
    the daily ranking degrades to price/volume signals only.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "watchlist_news_counts.json"

    if cache_file.exists():
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600.0
        if age_h < NEWS_CACHE_TTL_HOURS:
            try:
                cached = json.loads(cache_file.read_text())
                if set(t.upper() for t in tickers) <= set(cached.keys()):
                    return cached
            except Exception:  # noqa: BLE001
                pass

    from .symbols import normalize_symbol

    cutoff = time.time() - window_hours * 3600.0
    out: dict[str, dict] = {}
    for t in tickers[:max_tickers]:
        upper = t.upper()
        count = 0
        tags: list[str] = []
        try:
            items = yf.Ticker(normalize_symbol(upper)).news or []
        except Exception as exc:  # noqa: BLE001
            log.debug("news fetch failed for %s: %s", upper, exc)
            items = []
        for item in items:
            content = item.get("content", item) if isinstance(item, dict) else {}
            ts = (
                content.get("providerPublishTime")
                or item.get("providerPublishTime") or 0
            )
            pub_date = content.get("pubDate") or ""
            if isinstance(ts, (int, float)) and ts > 0:
                if ts < cutoff:
                    continue
            elif pub_date:
                try:
                    if pd.Timestamp(pub_date).timestamp() < cutoff:
                        continue
                except Exception:  # noqa: BLE001
                    continue
            else:
                continue
            count += 1
            title = str(content.get("title") or item.get("title") or "").lower()
            for needle, tag in _CATALYST_KEYWORDS:
                if needle in title and tag not in tags:
                    tags.append(tag)
        out[upper] = {"count": count, "tags": tags}

    try:
        cache_file.write_text(json.dumps(out))
    except Exception:  # noqa: BLE001
        pass
    return out
