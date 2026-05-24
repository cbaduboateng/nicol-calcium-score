"""Read-only Streamlit dashboard.

Run with:

    streamlit run -m congress_signal.dashboard

Or via the convenience entry point:

    csig-dashboard          # if installed via [project.scripts]
    streamlit run $(python -c "import congress_signal.dashboard as d; print(d.__file__)")

The dashboard reads from `data/processed/` only and never writes back. The
spec is firm on this: surveillance / alerting is a business decision and
the engine stays pure.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def main() -> None:
    try:
        import streamlit as st
    except ImportError:
        raise SystemExit(
            "streamlit is not installed. Install with "
            "`pip install congress-signal[dashboard]`."
        )

    processed = Path("data/processed")
    st.set_page_config(page_title="congress-signal", layout="wide")
    st.title("congress-signal — asymmetric trade screen")
    st.caption("Read-only research view. Refresh the underlying parquet files to update.")

    trades = _read_parquet(processed / "trades.parquet")
    actors = _read_parquet(processed / "actors.parquet")
    candidates = _read_parquet(processed / "candidates.parquet")
    catalysts = _read_parquet(processed / "catalysts.parquet")

    if candidates.empty:
        st.warning(
            "No candidates yet. Run: "
            "`csig ingest --source synthetic && csig score`"
        )
        return

    tab_top, tab_actors, tab_clusters, tab_catalysts = st.tabs(
        ["Top candidates", "Actor leaderboard", "Clusters", "Catalyst calendar"],
    )

    with tab_top:
        st.subheader("Top asymmetric candidates")
        top_n = st.slider("Top N", 5, 50, 20)
        view = candidates.sort_values("asymmetry_score", ascending=False).head(top_n)
        if "signal_types" in view.columns:
            view = view.copy()
            view["signal_types"] = view["signal_types"].apply(
                lambda x: ", ".join(x) if hasattr(x, "__iter__") and not isinstance(x, str) else str(x)
            )
        st.dataframe(
            view[["ticker", "actor_id", "asymmetry_score", "cluster_size",
                  "catalyst_pending", "signal_types", "rationale"]],
            use_container_width=True, hide_index=True,
        )

    with tab_actors:
        st.subheader("Actor leaderboard")
        if not trades.empty:
            top_by_actor = (
                trades.groupby("actor_id")
                .agg(trade_count=("trade_id", "count"))
                .reset_index()
            )
            cand_by_actor = (
                candidates.groupby("actor_id")
                .agg(candidate_count=("trade_id", "count"),
                     mean_score=("asymmetry_score", "mean"))
                .reset_index()
            )
            board = top_by_actor.merge(cand_by_actor, on="actor_id", how="left")
            if not actors.empty:
                actor_lookup = actors[["actor_id", "name", "chamber", "state"]]
                board = board.merge(actor_lookup, on="actor_id", how="left")
            board = board.sort_values(
                ["candidate_count", "mean_score"], ascending=[False, False],
            )
            st.dataframe(board, use_container_width=True, hide_index=True)

    with tab_clusters:
        st.subheader("Tickers with cluster activity (>=2 actors)")
        if "cluster_size" in candidates.columns:
            clusters = candidates[candidates["cluster_size"] >= 2]
            if clusters.empty:
                st.info("No active clusters with cluster_size >= 2.")
            else:
                cluster_view = (
                    clusters.groupby("ticker")
                    .agg(cluster_size=("cluster_size", "max"),
                         mean_score=("asymmetry_score", "mean"),
                         actors=("actor_id", lambda s: ", ".join(sorted(set(s)))))
                    .reset_index()
                    .sort_values("mean_score", ascending=False)
                )
                st.dataframe(cluster_view, use_container_width=True, hide_index=True)

    with tab_catalysts:
        st.subheader("Forward catalyst calendar")
        if catalysts.empty:
            st.info(
                "No catalysts loaded. Run `csig catalysts` to build the "
                "forward calendar (DoD obligation cycle is offline-safe)."
            )
        else:
            st.dataframe(catalysts.sort_values("event_date"),
                         use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
