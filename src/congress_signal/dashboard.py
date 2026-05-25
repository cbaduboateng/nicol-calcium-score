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

from datetime import date
from pathlib import Path

import pandas as pd


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _enrich_candidates(
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    actors: pd.DataFrame,
) -> pd.DataFrame:
    """Join candidates back to trades (for dates / amount / direction) and
    actors (for human-readable name + state)."""
    if candidates.empty:
        return candidates

    enriched = candidates.copy()

    if not trades.empty and "trade_id" in trades.columns:
        trade_cols = [
            c for c in (
                "trade_id", "transaction_date", "disclosure_date",
                "direction", "asset_type",
                "amount_min_usd", "amount_max_usd",
            ) if c in trades.columns
        ]
        enriched = enriched.merge(
            trades[trade_cols], on="trade_id", how="left",
        )
        # Days between trade and filing — the "speed" component.
        if "transaction_date" in enriched.columns and "disclosure_date" in enriched.columns:
            enriched["days_to_disclose"] = (
                pd.to_datetime(enriched["disclosure_date"])
                - pd.to_datetime(enriched["transaction_date"])
            ).dt.days

    if not actors.empty and "actor_id" in actors.columns:
        cols = [c for c in ("actor_id", "name", "chamber", "state", "party")
                if c in actors.columns]
        enriched = enriched.merge(actors[cols], on="actor_id", how="left")
        if "name" in enriched.columns:
            # Fall back to actor_id when we don't have a name yet.
            enriched["who"] = enriched["name"].fillna(enriched["actor_id"])
        else:
            enriched["who"] = enriched["actor_id"]
    else:
        enriched["who"] = enriched["actor_id"]

    if "signal_types" in enriched.columns:
        enriched["signal_types"] = enriched["signal_types"].apply(
            lambda x: ", ".join(x)
            if hasattr(x, "__iter__") and not isinstance(x, str)
            else str(x)
        )
    return enriched


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

    enriched = _enrich_candidates(candidates, trades, actors)

    tab_top, tab_actors, tab_clusters, tab_catalysts = st.tabs(
        ["Top candidates", "Actor leaderboard", "Clusters", "Catalyst calendar"],
    )

    with tab_top:
        st.subheader("Top asymmetric candidates")
        st.caption(
            "Highest-scoring trades the model flagged. Higher score = better "
            "risk/reward by this filter stack."
        )
        top_n = st.slider("Top N", 5, 50, 20)
        view = enriched.sort_values("asymmetry_score", ascending=False).head(top_n)

        display_cols = [c for c in (
            "transaction_date", "ticker", "who", "chamber", "state",
            "direction", "amount_max_usd", "days_to_disclose",
            "asymmetry_score", "cluster_size", "catalyst_pending",
            "signal_types", "rationale",
        ) if c in view.columns]
        st.dataframe(
            view[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "transaction_date": st.column_config.DateColumn("Trade date"),
                "ticker": "Ticker",
                "who": "Member",
                "chamber": "Chamber",
                "state": "State",
                "direction": "Buy/Sell",
                "amount_max_usd": st.column_config.NumberColumn(
                    "Amount (upper bracket)", format="$%d"),
                "days_to_disclose": st.column_config.NumberColumn(
                    "Days to file", help="Days between the trade and the public disclosure. Faster filings imply higher conviction."),
                "asymmetry_score": st.column_config.NumberColumn(
                    "Score", format="%.2f",
                    help="Composite signal. Higher = better risk/reward."),
                "cluster_size": st.column_config.NumberColumn(
                    "Cluster", help="How many members traded the same ticker around the same time."),
                "catalyst_pending": st.column_config.CheckboxColumn(
                    "Catalyst ahead", help="A known catalyst (contract award, hearing) is pending."),
                "signal_types": "Why flagged",
                "rationale": "Notes",
            },
        )
        st.caption(
            "This is a research screen, not a recommendation. Disclosure "
            "amounts are filed in brackets, so 'Amount' is the bracket ceiling."
        )

    with tab_actors:
        st.subheader("Actor leaderboard")
        st.caption("Which members trade most, and whose trades score best.")
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
                actor_lookup = actors[[c for c in (
                    "actor_id", "name", "chamber", "state", "party",
                ) if c in actors.columns]]
                board = board.merge(actor_lookup, on="actor_id", how="left")
                if "name" in board.columns:
                    board["Member"] = board["name"].fillna(board["actor_id"])
                    board = board.drop(columns=["name"])
            else:
                board["Member"] = board["actor_id"]
            board = board.sort_values(
                ["candidate_count", "mean_score"], ascending=[False, False],
            )
            ordered = [c for c in (
                "Member", "chamber", "state", "party",
                "trade_count", "candidate_count", "mean_score", "actor_id",
            ) if c in board.columns]
            st.dataframe(
                board[ordered], use_container_width=True, hide_index=True,
                column_config={
                    "chamber": "Chamber",
                    "state": "State",
                    "party": "Party",
                    "trade_count": "Trades filed",
                    "candidate_count": "Flagged",
                    "mean_score": st.column_config.NumberColumn(
                        "Avg score", format="%.2f"),
                    "actor_id": "Bioguide ID",
                },
            )

    with tab_clusters:
        st.subheader("Tickers with cluster activity (>=2 members)")
        st.caption(
            "When multiple members buy the same ticker in the same window, "
            "that's the strongest collective signal."
        )
        if "cluster_size" in candidates.columns:
            clusters = enriched[enriched["cluster_size"] >= 2]
            if clusters.empty:
                st.info("No active clusters with cluster_size >= 2.")
            else:
                cluster_view = (
                    clusters.groupby("ticker")
                    .agg(
                        cluster_size=("cluster_size", "max"),
                        mean_score=("asymmetry_score", "mean"),
                        members=("who", lambda s: ", ".join(sorted(set(s)))),
                        latest_trade=("transaction_date", "max") if "transaction_date" in clusters.columns else ("ticker", "count"),
                    )
                    .reset_index()
                    .sort_values("mean_score", ascending=False)
                )
                st.dataframe(
                    cluster_view, use_container_width=True, hide_index=True,
                    column_config={
                        "ticker": "Ticker",
                        "cluster_size": "Members in cluster",
                        "mean_score": st.column_config.NumberColumn(
                            "Avg score", format="%.2f"),
                        "members": "Who",
                        "latest_trade": st.column_config.DateColumn(
                            "Latest trade"),
                    },
                )

    with tab_catalysts:
        st.subheader("Forward catalyst calendar")
        st.caption(
            "Known upcoming events that could move a ticker. The model "
            "promotes trades on tickers with a pending catalyst."
        )
        if catalysts.empty:
            st.info(
                "No catalysts loaded. Run `csig catalysts` to build the "
                "forward calendar (DoD obligation cycle is offline-safe)."
            )
        else:
            today = pd.Timestamp(date.today())
            view = catalysts.copy()
            view["event_date"] = pd.to_datetime(view["event_date"])
            view = view[view["event_date"] >= today].sort_values("event_date")
            st.dataframe(
                view, use_container_width=True, hide_index=True,
                column_config={
                    "event_date": st.column_config.DateColumn("When"),
                    "ticker": "Ticker",
                    "category": "Type",
                    "source": "Source",
                    "rationale": "Why",
                },
            )


if __name__ == "__main__":
    main()
