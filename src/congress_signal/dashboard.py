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

from .mobile import APP_ICON_EMOJI, APP_TITLE, inject as inject_mobile
from .ticker_facts import lookup as ticker_lookup


CAP_LABEL = {
    "mega": "Mega cap (>$200B)",
    "large": "Large cap ($10B-$200B)",
    "mid": "Mid cap ($2B-$10B)",
    "small": "Small cap ($300M-$2B)",
    "micro": "Micro cap (<$300M)",
}


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
    actors (for human-readable name + state), plus static ticker facts
    (company name, exchange, cap bucket)."""
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
            enriched["who"] = enriched["name"].fillna(enriched["actor_id"])
        else:
            enriched["who"] = enriched["actor_id"]
    else:
        enriched["who"] = enriched["actor_id"]

    facts = enriched["ticker"].apply(ticker_lookup)
    enriched["company"] = facts.apply(lambda f: f.name if f else None)
    enriched["exchange"] = facts.apply(lambda f: f.exchange if f else None)
    enriched["cap"] = facts.apply(lambda f: f.cap if f else None)
    enriched["sector"] = facts.apply(lambda f: f.sector if f else None)

    if "signal_types" in enriched.columns:
        enriched["signal_types"] = enriched["signal_types"].apply(
            lambda x: ", ".join(x)
            if hasattr(x, "__iter__") and not isinstance(x, str)
            else str(x)
        )
    return enriched


def _format_amount(lo: float | None, hi: float | None) -> str:
    if lo is None and hi is None:
        return "unknown"
    if lo and hi and lo > 0:
        return f"${lo:,.0f} – ${hi:,.0f}"
    return f"up to ${hi:,.0f}" if hi else "unknown"


def _narrative(row: pd.Series) -> str:
    """Build a plain-English story explaining why this specific trade matters."""
    parts: list[str] = []

    who = row.get("who") or row.get("actor_id") or "A member"
    chamber = (row.get("chamber") or "").lower()
    chamber_word = {"house": "(House)", "senate": "(Senate)"}.get(chamber, "")
    state = row.get("state")
    party = row.get("party")
    when_raw = row.get("transaction_date")
    when = (
        pd.to_datetime(when_raw).strftime("%-d %B %Y")
        if pd.notna(when_raw) else "(date unknown)"
    )
    direction = row.get("direction") or "trade"
    direction_word = {
        "buy": "bought", "sell": "sold", "partial_sale": "partially sold",
        "exchange": "exchanged",
    }.get(direction, direction)

    ticker = row.get("ticker", "?")
    company = row.get("company") or ticker
    amount = _format_amount(row.get("amount_min_usd"), row.get("amount_max_usd"))

    who_prefix = who
    if state and party:
        who_prefix = f"{who} ({party[:1].upper()}-{state})"
    if chamber_word:
        who_prefix = f"{who_prefix} {chamber_word}"

    parts.append(
        f"On {when}, {who_prefix} {direction_word} {amount} of "
        f"**{company} ({ticker})**."
    )

    days = row.get("days_to_disclose")
    if pd.notna(days):
        if days <= 14:
            parts.append(
                f"They disclosed it in {int(days)} days — well inside the "
                "STOCK-Act 45-day window, which the model treats as a "
                "high-conviction signal."
            )
        elif days <= 30:
            parts.append(f"Disclosed {int(days)} days later (typical lag).")
        else:
            parts.append(
                f"Disclosed only {int(days)} days later, near the legal "
                "filing limit — a stale signal by the time it surfaced."
            )

    cluster = row.get("cluster_size") or 0
    if cluster >= 3:
        parts.append(
            f"**{int(cluster)} members of Congress traded {ticker} in the "
            "same two-week window** — a cluster signal worth following."
        )
    elif cluster == 2:
        parts.append(f"One other member also traded {ticker} in the same window.")

    if row.get("catalyst_pending"):
        parts.append(
            "A known catalyst is pending (contract award cycle, hearing, "
            "or budget event) — see the Catalyst tab."
        )

    if row.get("signal_types"):
        parts.append(f"Filter triggers: _{row['signal_types']}_.")

    return "\n\n".join(parts)


def _render_ticker_card(st, row: pd.Series) -> None:
    ticker = row.get("ticker", "?")
    fact = ticker_lookup(ticker)

    st.markdown(f"### {fact.name if fact else ticker}  ·  `{ticker}`")
    if fact:
        meta = " · ".join([
            fact.exchange,
            CAP_LABEL.get(fact.cap, fact.cap.title()),
            fact.sector,
        ])
        st.caption(meta)
        if fact.summary or fact.why_it_matters:
            with st.container(border=True):
                if fact.summary:
                    st.markdown(f"**What they do.** {fact.summary}")
                if fact.why_it_matters:
                    st.markdown(f"**Why it tends to be signal-worthy.** {fact.why_it_matters}")
    else:
        st.info(
            f"No reference data on file for {ticker}. Add it to "
            "`congress_signal/ticker_facts.py` to enrich this view."
        )

    st.markdown("**Why this specific trade was flagged:**")
    with st.container(border=True):
        st.markdown(_narrative(row))


def main() -> None:
    try:
        import streamlit as st
    except ImportError:
        raise SystemExit(
            "streamlit is not installed. Install with "
            "`pip install congress-signal[dashboard]`."
        )

    processed = Path("data/processed")
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=APP_ICON_EMOJI,
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={
            "Get help": None,
            "Report a Bug": None,
            "About": f"{APP_TITLE} — read-only research view of congressional trading signals.",
        },
    )
    inject_mobile(st)
    st.title(f"{APP_ICON_EMOJI} {APP_TITLE}")
    st.caption(
        "Asymmetric-trade screen for congressional disclosures. "
        "Read-only research view — not financial advice."
    )

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

    # Surface the data source so the user knows whether this is live or
    # synthetic. Quiver-sourced trades carry source=='quiver'; the synthetic
    # generator uses 'synthetic'.
    sources = (
        set(trades["source"].dropna().unique()) if "source" in trades.columns else set()
    )
    if "quiver" in sources or "house_ptr" in sources or "senate_efd" in sources:
        live = ", ".join(sorted(s for s in sources if s != "synthetic"))
        last_disc = (
            pd.to_datetime(trades["disclosure_date"]).max()
            if "disclosure_date" in trades.columns else None
        )
        label = f"📡 Live data from **{live}**"
        if last_disc is not None and not pd.isna(last_disc):
            label += f" — latest disclosure {last_disc.strftime('%-d %b %Y')}"
        st.success(label)
    elif "synthetic" in sources or not sources:
        st.info(
            "🧪 Showing **synthetic data** (no QUIVER_API_KEY configured). "
            "Set the secret in Streamlit Cloud → Settings → Secrets to switch to live trades."
        )

    enriched = _enrich_candidates(candidates, trades, actors)

    tab_top, tab_actors, tab_clusters, tab_catalysts = st.tabs(
        ["Top candidates", "Actor leaderboard", "Clusters", "Catalyst calendar"],
    )

    with tab_top:
        st.subheader("Top asymmetric candidates")
        st.caption(
            "Highest-scoring trades the model flagged. Higher score = better "
            "risk/reward by this filter stack. Click a row's ticker below to see details."
        )
        top_n = st.slider("Top N", 5, 50, 20)
        view = enriched.sort_values("asymmetry_score", ascending=False).head(top_n).reset_index(drop=True)

        display_cols = [c for c in (
            "transaction_date", "ticker", "company", "exchange", "cap",
            "who", "chamber", "state",
            "direction", "amount_max_usd", "days_to_disclose",
            "asymmetry_score", "cluster_size", "catalyst_pending",
            "signal_types",
        ) if c in view.columns]
        st.dataframe(
            view[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "transaction_date": st.column_config.DateColumn("Trade date"),
                "ticker": "Ticker",
                "company": "Company",
                "exchange": "Exchange",
                "cap": st.column_config.TextColumn(
                    "Cap", help="Market-cap bucket: mega >$200B, large $10-200B, mid $2-10B, small $300M-$2B, micro <$300M"),
                "who": "Member",
                "chamber": "Chamber",
                "state": "State",
                "direction": "Buy/Sell",
                "amount_max_usd": st.column_config.NumberColumn(
                    "Amount (upper)", format="$%d"),
                "days_to_disclose": st.column_config.NumberColumn(
                    "Days to file", help="Days between the trade and the public disclosure. Faster = higher conviction signal."),
                "asymmetry_score": st.column_config.NumberColumn(
                    "Score", format="%.2f",
                    help="Composite signal. Higher = better risk/reward."),
                "cluster_size": st.column_config.NumberColumn(
                    "Cluster", help="How many members traded the same ticker in the same window."),
                "catalyst_pending": st.column_config.CheckboxColumn(
                    "Catalyst", help="A known catalyst is pending."),
                "signal_types": "Why flagged",
            },
        )

        st.markdown("---")
        st.markdown("#### Details")
        choice_options = [
            (
                f"{i+1}. {row.get('company') or row['ticker']} "
                f"({row['ticker']}) — {row.get('who','?')} on "
                f"{pd.to_datetime(row.get('transaction_date')).strftime('%Y-%m-%d') if pd.notna(row.get('transaction_date')) else '?'}"
            )
            for i, row in view.iterrows()
        ]
        selected = st.selectbox(
            "Show details for:", options=list(range(len(view))),
            format_func=lambda i: choice_options[i] if i < len(choice_options) else "?",
        )
        if selected is not None and selected < len(view):
            _render_ticker_card(st, view.iloc[selected])

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
                agg = {
                    "cluster_size": ("cluster_size", "max"),
                    "mean_score": ("asymmetry_score", "mean"),
                    "members": ("who", lambda s: ", ".join(sorted(set(s)))),
                }
                if "transaction_date" in clusters.columns:
                    agg["latest_trade"] = ("transaction_date", "max")
                if "company" in clusters.columns:
                    agg["company"] = ("company", "first")
                cluster_view = (
                    clusters.groupby("ticker")
                    .agg(**agg)
                    .reset_index()
                    .sort_values("mean_score", ascending=False)
                )
                st.dataframe(
                    cluster_view, use_container_width=True, hide_index=True,
                    column_config={
                        "ticker": "Ticker",
                        "company": "Company",
                        "cluster_size": "Members",
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
            # Decorate with company name where available.
            view["company"] = view["ticker"].apply(
                lambda t: (ticker_lookup(t).name if ticker_lookup(t) else "")
            )
            st.dataframe(
                view[["event_date", "ticker", "company", "category", "source", "rationale"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "event_date": st.column_config.DateColumn("When"),
                    "ticker": "Ticker",
                    "company": "Company",
                    "category": "Type",
                    "source": "Source",
                    "rationale": "Why",
                },
            )


if __name__ == "__main__":
    main()
