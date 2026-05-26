"""Streamlit Community Cloud entry point.

Streamlit Cloud looks for `streamlit_app.py` at the repository root by
default. This file is a thin wrapper that delegates to the real dashboard
module so the package layout stays clean.

If `QUIVER_API_KEY` is set (via env or Streamlit Cloud Secrets) the
bootstrap pulls live congressional trades from the Quiver API on cold
start; otherwise it falls back to the synthetic generator so the app
always renders.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Make sure INFO-level logs from our package show up in the Render /
# Streamlit Cloud logs panel. Root logger is at WARNING by default.
logging.basicConfig(
    level=logging.INFO,
    format="[csig] %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("streamlit_app")


_MAX_DATA_AGE_HOURS = 24


def _existing_data_is_fresh_and_live() -> bool:
    """Skip the bootstrap only when we already have *live* data that isn't
    too old. Synthetic-only data is treated as stale so the next cold start
    (after a Quiver key lands) upgrades it to live."""
    processed = Path("data/processed")
    candidates_file = processed / "candidates.parquet"
    trades_file = processed / "trades.parquet"
    if not (candidates_file.exists() and trades_file.exists()):
        return False
    import time

    age_hours = (time.time() - trades_file.stat().st_mtime) / 3600.0
    if age_hours > _MAX_DATA_AGE_HOURS:
        log.info("Existing data is %.1fh old; will rebootstrap", age_hours)
        return False
    try:
        import pandas as pd

        sources = set(pd.read_parquet(trades_file)["source"].dropna().unique())
    except Exception as exc:
        log.info("Could not inspect existing trades.parquet (%s); rebootstrapping", exc)
        return False
    has_live = bool(sources - {"synthetic"})
    has_key = bool(os.environ.get("QUIVER_API_KEY", "").strip())
    if has_key and not has_live:
        log.info("Existing data is synthetic but Quiver key now set; upgrading to live")
        return False
    log.info("Existing data is fresh and %s; skipping bootstrap", sources)
    return True


def _bootstrap_data_if_missing() -> None:
    """Generate or fetch the input tape on cold start so the dashboard always
    has something to render. Skips re-bootstrap only when existing data is
    both fresh (<24h) and already includes a live source."""
    processed = Path("data/processed")
    if _existing_data_is_fresh_and_live():
        return

    processed.mkdir(parents=True, exist_ok=True)
    Path("data/cache").mkdir(parents=True, exist_ok=True)

    import pandas as pd

    from congress_signal.config import load_config
    from congress_signal.ingest.committees import load_committee_actors
    from congress_signal.ingest.quiver import QuiverClient
    from congress_signal.ingest.synthetic import synthetic_actors, synthetic_trades
    from congress_signal.pipeline import run_full_pipeline
    from congress_signal.scoring.catalyst import build_calendar

    cfg = load_config()

    # Pull Streamlit secrets into env (no-op on Render where env vars are
    # already set directly).
    try:
        import streamlit as st
        for key in ("QUIVER_API_KEY", "CONGRESS_API_KEY"):
            if key in st.secrets and key not in os.environ:
                os.environ[key] = st.secrets[key]
                log.info("Loaded %s from st.secrets into env", key)
    except Exception as exc:
        log.info("st.secrets not available (%s)", exc)

    quiver_key = os.environ.get("QUIVER_API_KEY", "").strip()
    log.info(
        "QUIVER_API_KEY present=%s (length=%d)",
        bool(quiver_key), len(quiver_key),
    )

    trades = []
    if quiver_key:
        log.info("Attempting Quiver fetch (last 2 years)")
        try:
            client = QuiverClient(api_key=quiver_key)
            trades = client.congress_trades(
                since=date.today() - timedelta(days=365 * 2),
            )
            log.info("Quiver returned %d trades", len(trades))
        except Exception as exc:
            log.warning("Quiver client raised: %s", exc)
            trades = []

    if not trades:
        log.warning(
            "No live trades available; falling back to synthetic tape. "
            "Common causes: Hobbyist tier doesn't include /bulk/congresstrading, "
            "key invalid, or rate-limit. Check Quiver dashboard."
        )
        trades = synthetic_trades(span_days=2555, n_trades=1277)
        actors = synthetic_actors()
    else:
        # ---- Dedup Quiver entries -----------------------------------------
        # Quiver often returns multiple rows for what is effectively the
        # same trade (multiple sub-accounts, amendments, mirror filings).
        # Collapse by (actor_id, ticker, transaction_date, direction) and
        # keep the row with the largest disclosure amount so we don't lose
        # signal.
        before = len(trades)
        deduped: dict[tuple, "object"] = {}
        for t in trades:
            key = (t.actor_id, t.ticker, t.transaction_date, t.direction)
            existing = deduped.get(key)
            if existing is None or (t.amount_max_usd or 0) > (existing.amount_max_usd or 0):
                deduped[key] = t
        trades = list(deduped.values())
        log.info("Deduped trades: %d -> %d", before, len(trades))

        # ---- Build actor list with real names ------------------------------
        log.info("Loading committee actors from unitedstates/congress-legislators")
        try:
            actors = load_committee_actors(Path(cfg["paths"]["cache"]))
        except Exception as exc:
            log.warning("Committee load failed (%s); using synthetic actors", exc)
            actors = []

        from congress_signal.schema import Actor, Chamber

        actor_by_id: dict[str, Actor] = {a.actor_id: a for a in actors}

        for t in trades:
            raw = t.raw_source if isinstance(t.raw_source, dict) else {}
            quiver_name = (raw.get("Name") or "").strip()
            quiver_state = (raw.get("State") or "").strip() or None
            quiver_chamber_raw = (raw.get("Chamber") or "").strip()
            chamber = (
                Chamber.SENATE if quiver_chamber_raw == "Senators"
                else Chamber.HOUSE
            )
            party = {
                "Democratic": "D", "Democrat": "D",
                "Republican": "R", "Independent": "I",
            }.get((raw.get("Party") or "").strip())

            existing = actor_by_id.get(t.actor_id)
            if existing is None:
                actor_by_id[t.actor_id] = Actor(
                    actor_id=t.actor_id,
                    name=quiver_name or t.actor_id,
                    chamber=chamber,
                    state=quiver_state,
                    party=party,
                )
            elif existing.name == existing.actor_id and quiver_name:
                # Committee feed had a bare stub for this bioguide; upgrade
                # name (and state/party) from Quiver.
                actor_by_id[t.actor_id] = existing.model_copy(update={
                    "name": quiver_name,
                    "state": existing.state or quiver_state,
                    "party": existing.party or party,
                })

        actors = list(actor_by_id.values())

    pd.DataFrame([t.model_dump() for t in trades]).to_parquet(
        processed / "trades.parquet",
    )
    pd.DataFrame([a.model_dump() for a in actors]).to_parquet(
        processed / "actors.parquet",
    )

    log.info("Running scoring pipeline on %d trades / %d actors", len(trades), len(actors))
    # Skip the in-bootstrap yfinance fetch — pulling prices for hundreds of
    # tickers blows the request timeout on Render's free tier. The residual
    # scoring layer falls back to a neutral verdict when prices are missing.
    result = run_full_pipeline(cfg, trades, actors, prices=pd.DataFrame())
    log.info("Pipeline produced %d candidates", len(result.candidates))
    pd.DataFrame([c.model_dump() for c in result.candidates]).to_parquet(
        processed / "candidates.parquet"
    )

    events = build_calendar(horizon_days=365)
    pd.DataFrame([{
        "event_date": e.event_date, "ticker": e.ticker,
        "category": e.category, "source": e.source, "rationale": e.rationale,
    } for e in events]).to_parquet(processed / "catalysts.parquet")
    log.info("Bootstrap complete: %d trades, %d candidates, %d catalysts",
             len(trades), len(result.candidates), len(events))


_bootstrap_data_if_missing()

from congress_signal.dashboard import main as _main  # noqa: E402

_main()
