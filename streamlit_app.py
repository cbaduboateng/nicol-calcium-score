"""Streamlit Community Cloud entry point.

Streamlit Cloud looks for `streamlit_app.py` at the repository root by
default. This file is a thin wrapper that delegates to the real dashboard
module so the package layout stays clean.
"""

from __future__ import annotations

from pathlib import Path


def _bootstrap_synthetic_data_if_missing() -> None:
    """Generate a synthetic tape on cold start so the deployed dashboard has
    something to show without any user setup. No-op when files exist."""
    processed = Path("data/processed")
    if (processed / "candidates.parquet").exists():
        return

    processed.mkdir(parents=True, exist_ok=True)
    Path("data/cache").mkdir(parents=True, exist_ok=True)

    import pandas as pd

    from congress_signal.config import load_config
    from congress_signal.ingest.synthetic import synthetic_actors, synthetic_trades
    from congress_signal.pipeline import run_full_pipeline
    from congress_signal.scoring.catalyst import build_calendar

    cfg = load_config()
    trades = synthetic_trades(span_days=2555, n_trades=1277)
    actors = synthetic_actors()

    pd.DataFrame([t.model_dump() for t in trades]).to_parquet(processed / "trades.parquet")
    pd.DataFrame([a.model_dump() for a in actors]).to_parquet(processed / "actors.parquet")

    result = run_full_pipeline(cfg, trades, actors)
    pd.DataFrame([c.model_dump() for c in result.candidates]).to_parquet(
        processed / "candidates.parquet"
    )

    events = build_calendar(horizon_days=365)
    pd.DataFrame([{
        "event_date": e.event_date, "ticker": e.ticker,
        "category": e.category, "source": e.source, "rationale": e.rationale,
    } for e in events]).to_parquet(processed / "catalysts.parquet")


_bootstrap_synthetic_data_if_missing()

from congress_signal.dashboard import main as _main  # noqa: E402

_main()
