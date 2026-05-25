"""Streamlit Community Cloud entry point.

Streamlit Cloud looks for `streamlit_app.py` at the repository root by
default. This file is a thin wrapper that delegates to the real dashboard
module so the package layout stays clean.

If `QUIVER_API_KEY` is set (via Streamlit Cloud Secrets), the bootstrap
pulls live congressional trades from the Quiver API on cold start; otherwise
it falls back to the synthetic generator so the app always renders.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def _bootstrap_data_if_missing() -> None:
    """Generate or fetch the input tape on cold start so the dashboard always
    has something to render. No-op when files already exist on disk."""
    processed = Path("data/processed")
    if (processed / "candidates.parquet").exists():
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

    # Pull Streamlit secrets into env so the existing API clients pick them
    # up via os.environ without any code change.
    try:
        import streamlit as st
        for key in ("QUIVER_API_KEY", "CONGRESS_API_KEY"):
            if key in st.secrets and key not in os.environ:
                os.environ[key] = st.secrets[key]
    except Exception:
        pass

    have_quiver = bool(os.environ.get("QUIVER_API_KEY"))

    if have_quiver:
        log.info("QUIVER_API_KEY present; pulling live congressional trades")
        client = QuiverClient()
        trades = client.congress_trades(
            since=date.today() - timedelta(days=365 * 2),
        )
        # Quiver returns synthetic-fallback list on failure; we still get a
        # usable tape either way.
        actors = load_committee_actors(Path(cfg["paths"]["cache"]))
        # When live actors come back, supplement any actor_ids the trade
        # tape mentions but the committee feed doesn't (e.g. ex-members).
        known = {a.actor_id for a in actors}
        from congress_signal.schema import Actor, Chamber
        for t in trades:
            if t.actor_id not in known:
                actors.append(Actor(
                    actor_id=t.actor_id, name=t.actor_id,
                    chamber=Chamber.HOUSE,
                ))
                known.add(t.actor_id)
    else:
        log.info("QUIVER_API_KEY not set; using synthetic tape")
        trades = synthetic_trades(span_days=2555, n_trades=1277)
        actors = synthetic_actors()

    pd.DataFrame([t.model_dump() for t in trades]).to_parquet(
        processed / "trades.parquet",
    )
    pd.DataFrame([a.model_dump() for a in actors]).to_parquet(
        processed / "actors.parquet",
    )

    result = run_full_pipeline(cfg, trades, actors)
    pd.DataFrame([c.model_dump() for c in result.candidates]).to_parquet(
        processed / "candidates.parquet"
    )

    events = build_calendar(horizon_days=365)
    pd.DataFrame([{
        "event_date": e.event_date, "ticker": e.ticker,
        "category": e.category, "source": e.source, "rationale": e.rationale,
    } for e in events]).to_parquet(processed / "catalysts.parquet")


_bootstrap_data_if_missing()

from congress_signal.dashboard import main as _main  # noqa: E402

_main()
