"""Read-only Streamlit dashboard.

Run with:

    streamlit run -m icarus.dashboard

Or via the convenience entry point:

    icarus-dashboard          # if installed via [project.scripts]
    streamlit run $(python -c "import icarus.dashboard as d; print(d.__file__)")

The dashboard reads from `data/processed/` only and never writes back. The
spec is firm on this: surveillance / alerting is a business decision and
the engine stays pure.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .mobile import APP_ICON_EMOJI, APP_TITLE, inject as inject_mobile
from .ticker_facts import lookup as ticker_lookup, top_level_category


CAP_LABEL = {
    "mega": "Mega cap (>$200B)",
    "large": "Large cap ($10B-$200B)",
    "mid": "Mid cap ($2B-$10B)",
    "small": "Small cap ($300M-$2B)",
    "micro": "Micro cap (<$300M)",
}


def _fmt_cap_short(mcap: float | None) -> str:
    """Compact market-cap label for tables: $50M, $1.2B, $850M, '—' for unknown."""
    if mcap is None or not pd.notna(mcap) or mcap <= 0:
        return "—"
    if mcap >= 1_000_000_000:
        return f"${mcap / 1e9:.1f}B"
    return f"${mcap / 1e6:.0f}M"


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
    enriched["category"] = enriched["sector"].apply(top_level_category)

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
            "`icarus/ticker_facts.py` to enrich this view."
        )

    st.markdown("**Why this specific trade was flagged:**")
    with st.container(border=True):
        st.markdown(_narrative(row))


def _render_watchlist_tab(st) -> None:
    """Render the Watchlist tab: curated analyst picks with live
    alerts, theme momentum, and a parabolic-winners ranking."""
    from .watchlist_alerts import (
        WATCHLIST_PATH,
        build_watchlist_view,
        fetch_price_history,
        load_catalyst_overlay,

        load_watchlist,
        parabolic_rank,
        pick_winners,
        theme_heat,
    )

    st.subheader("Watchlist — analyst-curated picks with live alerts")
    st.caption(
        "Hand-picked tickers with analyst buy / sell targets. "
        "Live prices compared every page load; themes ranked by 3-month "
        "median momentum; parabolic ranking by raw 6-month gain."
    )

    # Data-freshness caption so the user can tell whether the bootstrap fired
    freshness_bits: list[str] = []
    for label, path in (
        ("watchlist", "data/watchlist.csv"),
        ("catalysts", "data/processed/catalysts.parquet"),
    ):
        p = Path(path)
        if p.exists():
            import time as _time
            age_h = (_time.time() - p.stat().st_mtime) / 3600.0
            if age_h < 1:
                freshness_bits.append(f"{label} {int(age_h * 60)}m ago")
            elif age_h < 48:
                freshness_bits.append(f"{label} {age_h:.0f}h ago")
            else:
                freshness_bits.append(f"{label} {age_h / 24:.0f}d ago")
    if freshness_bits:
        st.caption("**Data refreshed:** " + " · ".join(freshness_bits))

    watchlist = load_watchlist(WATCHLIST_PATH)
    if watchlist.empty:
        st.warning(
            f"No watchlist file found at `{WATCHLIST_PATH}`. "
            "Add tickers + target_entry / target_exit columns to the CSV."
        )
        return
    st.caption(
        f"**{len(watchlist)} tickers** in the watchlist; "
        f"**{int(watchlist['target_entry'].notna().sum())} with a buy target**, "
        f"**{int(watchlist['target_exit'].notna().sum())} with a sell target**."
    )

    # ---- Live price fetch (cached 24h to keep page fast) -------------------
    tickers = sorted(set(watchlist["ticker"].tolist()))
    with st.spinner(f"Loading prices for {len(tickers)} tickers..."):
        try:
            history = fetch_price_history(tickers, period="1y")
        except Exception as exc:
            st.error(f"Price fetch failed: {exc}")
            history = {}

    # ---- 🧮 Derive missing targets from the analyst's learned pattern ------
    derive_on = st.toggle(
        "🧮 Derive missing targets from the analyst pattern",
        value=True,
        key="derive_targets_toggle",
        help=(
            "Learns the analyst's target-setting rule from the rows that HAVE "
            "targets (which price anchor entries cluster around, and the "
            "typical exit-to-entry multiple), then fills the blanks. Derived "
            "targets are flagged 'D' and are for screening only — the Track "
            "record and £5k backtest always use analyst targets exclusively."
        ),
    )
    if derive_on and history:
        from .target_inference import (
            derive_targets,
            describe_pattern,
            learn_target_pattern,
        )
        pattern = learn_target_pattern(watchlist, history)
        if pattern is None:
            st.caption(
                "🧮 Not enough analyst targets with price history to learn a "
                "pattern yet — showing analyst targets only."
            )
        else:
            watchlist = derive_targets(watchlist, history, pattern)
            n_e = int((watchlist["entry_source"] == "derived").sum())
            n_x = int((watchlist["exit_source"] == "derived").sum())
            st.caption(
                f"🧮 {describe_pattern(pattern)}. Derived **{n_e} entries** "
                f"and **{n_x} exits**; analyst values untouched."
            )

    view = build_watchlist_view(watchlist, history)
    if "entry_source" in watchlist.columns:
        view = view.merge(
            watchlist[["ticker", "entry_source", "exit_source"]],
            on="ticker", how="left",
        )
        view["tgt_src"] = (
            view["entry_source"].map({"analyst": "A", "derived": "D"}).fillna("—")
            + "/"
            + view["exit_source"].map({"analyst": "A", "derived": "D"}).fillna("—")
        )
    n_with_price = int(view["live_price"].notna().sum())
    st.caption(f"Live price available for **{n_with_price} / {len(view)}**.")
    missing_px = view[view["live_price"].isna()]["ticker"].astype(str).tolist()
    if missing_px:
        with st.expander(f"⚠️ {len(missing_px)} tickers without prices"):
            st.caption(
                "International prefixes (LON:THG → THG.L) are translated "
                "automatically, so what's left here is mostly delisted or "
                "acquired names (e.g. ATVI, VMW, SPLK) and OCR-mangled "
                "symbols. Prune or correct these in `data/watchlist.csv` — "
                "they can never alert."
            )
            st.write(", ".join(missing_px))

    # ---- Shared day-scale inputs (volumes, news, overlays) -----------------
    from .daily_signals import (
        compute_daily_signals,
        fetch_news_counts,
        find_gems,
        gem_gate_failures,
    )
    from .watchlist_alerts import fetch_volume_history

    from .insider_overlay import load_insider_overlay
    try:
        insider_overlay = load_insider_overlay()
    except Exception:
        insider_overlay = {}
    catalyst_overlay = load_catalyst_overlay()

    buy_zone_tickers = sorted(
        view[view["status"] == "BUY ZONE"]["ticker"].astype(str).tolist()
    )
    volumes: dict = {}
    news: dict = {}
    if buy_zone_tickers:
        with st.spinner("Checking volume and news for the buy-zone names..."):
            try:
                volumes = fetch_volume_history(sorted(set(view["ticker"])))
            except Exception:
                volumes = {}
            try:
                news = fetch_news_counts(buy_zone_tickers)
            except Exception:
                news = {}

    heat_for_today = theme_heat(view)
    theme_3m_map = (
        dict(zip(heat_for_today["theme"], heat_for_today["median_3m"]))
        if not heat_for_today.empty else {}
    )
    today = (
        compute_daily_signals(
            view, history, volumes,
            news_counts=news, theme_3m=theme_3m_map, top_n=5,
        )
        if buy_zone_tickers else pd.DataFrame()
    )

    # ---- 🔎 Ticker lookup (bypasses every filter) --------------------------
    lookup_q = st.text_input(
        "🔎 Look up any watchlist ticker",
        placeholder="e.g. HIVE — shows status, targets, and why it is / isn't a gem",
        key="ticker_lookup_box",
    )
    if lookup_q.strip():
        q = lookup_q.strip().upper()
        matches = view[view["ticker"].astype(str).str.contains(q, na=False)]
        if matches.empty:
            st.warning(f"No watchlist ticker matching **{q}**.")
        else:
            exact = matches[matches["ticker"] == q]
            found = exact.iloc[0] if not exact.empty else matches.iloc[0]
            if len(matches) > 1 and exact.empty:
                st.caption(
                    f"{len(matches)} matches ({', '.join(matches['ticker'].head(8))}"
                    f"{'…' if len(matches) > 8 else ''}) — showing **{found['ticker']}**."
                )
            # Gem-gate diagnosis, right where the investigation happens
            fails = gem_gate_failures(found, theme_3m_map)
            if fails:
                st.warning(f"**{found['ticker']} is not a gem right now:** {'; '.join(fails)}")
            else:
                st.success(
                    f"**{found['ticker']} passes every strict gate** — if it isn't "
                    "in 💎 Gems above, it scored below the top-5 cut."
                )
            src = found.get("tgt_src")
            if src and src != "—/—":
                st.caption(
                    f"Target provenance: **{src}** (entry/exit; A = analyst, "
                    "D = derived from the learned pattern — derived targets "
                    "re-derive on data refresh and can drift slightly)."
                )
            _render_watchlist_ticker_card(
                st, found,
                insider_overlay=insider_overlay,
                catalyst_overlay=catalyst_overlay,
            )
        st.divider()

    gems = find_gems(
        view, history, volumes,
        news_counts=news,
        insider_overlay=insider_overlay or None,
        catalyst_overlay=catalyst_overlay or None,
        top_n=5,
    )

    # ---- 🧭 Explorer pool (optional second universe, derived targets) ------
    explorer_gems = pd.DataFrame()
    explorer_note: str | None = None
    try:
        from .target_inference import derive_targets, learn_target_pattern
        from .universe import load_explorer_watchlist
        explorer_wl = load_explorer_watchlist()
        if explorer_wl.empty:
            explorer_note = (
                "🧭 Explorer universe not built yet — run the **'Build "
                "explorer universe'** workflow in GitHub Actions to add "
                "~1,000+ screener candidates to the pick (weekly Sunday "
                "refresh once it exists)."
            )
        else:
            exp_pattern = learn_target_pattern(watchlist, history)
            if exp_pattern is None:
                explorer_note = (
                    f"🧭 Explorer list present ({len(explorer_wl)} names) but "
                    "no target pattern could be learned from the curated "
                    "list — explorer pool skipped this load."
                )
            else:
                exp_tickers = sorted(set(explorer_wl["ticker"].tolist()))
                exp_history = fetch_price_history(exp_tickers, period="1y")
                if exp_history:
                    explorer_wl = derive_targets(explorer_wl, exp_history, exp_pattern)
                    exp_view = build_watchlist_view(explorer_wl, exp_history)
                    exp_view["tgt_src"] = "D/D"
                    exp_volumes = fetch_volume_history(exp_tickers, period="3mo")
                    explorer_gems = find_gems(
                        exp_view, exp_history, exp_volumes, top_n=5,
                    )
                    explorer_note = (
                        f"🧭 Explorer pool active: **{len(explorer_wl)} "
                        f"candidates**, {len(explorer_gems)} gem"
                        f"{'s' if len(explorer_gems) != 1 else ''} this load "
                        "(trust-discounted ×0.85 in the pick)."
                    )
                else:
                    explorer_note = (
                        "🧭 Explorer list present but no prices available "
                        "yet — pool skipped this load."
                    )
    except Exception as exc:  # noqa: BLE001
        explorer_note = f"🧭 Explorer pool unavailable this load ({exc})."

    # ---- 👑 Pick of the day ------------------------------------------------
    from .daily_signals import pick_of_the_day
    verdict = pick_of_the_day([
        (gems, "curated", 1.0),
        (explorer_gems, "explorer", 0.85),
    ])
    st.markdown("### 👑 Pick of the day")
    if explorer_note:
        st.caption(explorer_note)
    if verdict["pick"] is None:
        reason = verdict["reason"] or "no qualifying gem"
        st.info(
            f"**No trade today** — {reason}. Abstention is the system "
            "working; the runner-up detail is below in 💎 Gems."
        )
    else:
        p = verdict["pick"]
        pool_label = (
            "curated watchlist (analyst-anchored)"
            if p["pool"] == "curated"
            else "🧭 explorer universe (fully derived targets — screener grade)"
        )
        with st.container(border=True):
            pl, pr = st.columns([3, 2])
            with pl:
                st.markdown(f"#### 👑 {p['ticker']} — {p.get('name') or ''}")
                st.caption(p.get("reasons") or "")
                st.caption(f"Pool: {pool_label}")
            with pr:
                def _p(v):
                    return f"{v:,.2f}" if pd.notna(v) else "—"
                st.markdown(
                    f"Adjusted score **{p['adjusted_score']:.2f}** "
                    f"(gem {p['gem_score']:.2f} × trust {p['trust']:.2f})  \n"
                    f"Live {_p(p.get('live_price'))} · Buy ≤ {_p(p.get('target_entry'))} · "
                    f"**Stop {_p(p.get('stop_price'))}** · Sell ≥ {_p(p.get('target_exit'))}"
                )
        runners = verdict["runners"]
        if runners is not None and not runners.empty:
            runner_bits = [
                f"{r['ticker']} ({r['adjusted_score']:.2f}, {r['pool']})"
                for _, r in runners.iterrows()
            ]
            st.caption("Runners-up: " + " · ".join(runner_bits))
        st.caption(
            "⚠️ One name, ranked by trust-adjusted gem score. Read the "
            "company card and pre-commit the stop before acting. Not "
            "financial advice."
        )

    st.divider()

    # ---- 💎 Gems (quality gates AND day-scale agreement) -------------------
    st.markdown("### 💎 Gems — every filter agrees")
    st.caption(
        "A gem passes EVERY strict quality gate (buy zone, own 3m momentum "
        "> 0, hot theme, R:R ≥ 3, not parabolic) AND shows day-scale action "
        "(volume, freshness, news). Insider buying (SEC Form 4, 2-day lag) "
        "and catalysts add soft weight only — never a gate. "
        "**Empty most days by design** — six signal families rarely agree."
    )
    if not explorer_gems.empty:
        st.caption(
            f"🧭 Explorer pool contributed **{len(explorer_gems)} additional "
            "gems** (fully derived targets, trust-discounted) — shown in the "
            "Pick of the Day ranking above."
        )
    if gems.empty:
        st.info(
            "💤 No gems today. That's the discipline, not a malfunction — "
            "the names below are *close*, but don't loosen the gates to "
            "make this list less empty."
        )
        # Diagnostic: say exactly which gate each top signal failed, so an
        # empty list is a teaching moment instead of a dead end.
        if not today.empty:
            st.caption("**Why today's top signals aren't gems:**")
            for _, sig in today.head(3).iterrows():
                sig_row = view[view["ticker"] == sig["ticker"]]
                if sig_row.empty:
                    continue
                fails = gem_gate_failures(sig_row.iloc[0], theme_3m_map)
                if fails:
                    st.caption(f"• **{sig['ticker']}** — {'; '.join(fails)}")
                else:
                    st.caption(
                        f"• **{sig['ticker']}** — passes every gate; if it "
                        "isn't showing above after a refresh, that's a bug "
                        "worth reporting."
                    )
    else:
        runbook_only = st.toggle(
            "🎯 Runbook-sized only (< $300M)",
            value=False,
            key="gems_runbook_only",
            help="Size informs the position decision, not the gem's validity — "
                 "large-cap gems are steadier trades, small caps are the "
                 "parabolic candidates. Unknown caps stay visible either way.",
        )
        gems_shown = gems
        if runbook_only and "market_cap_usd" in gems.columns:
            keep = gems["market_cap_usd"].isna() | (
                gems["market_cap_usd"] < 300_000_000
            )
            gems_shown = gems[keep]
            if gems_shown.empty:
                st.info(
                    "All of today's gems are larger than $300M — flip the "
                    "toggle off to see them."
                )
        for _, gem in gems_shown.iterrows():
            mcap = gem.get("market_cap_usd")
            cap_s = _fmt_cap_short(mcap)
            runbook_sized = (
                pd.notna(mcap) and mcap is not None and mcap < 300_000_000
            )
            cap_line = f"Cap {cap_s}"
            if runbook_sized:
                cap_line += " · 🎯 runbook-sized"
            elif cap_s == "—":
                cap_line += " (unknown)"
            with st.container(border=True):
                gl, gr = st.columns([3, 2])
                with gl:
                    st.markdown(
                        f"**💎 #{int(gem['rank'])}  {gem['ticker']}** — "
                        f"{gem['name'] or ''}"
                    )
                    st.caption(gem["reasons"])
                    if gem.get("insider_summary"):
                        st.caption(f"💼 Insiders: {gem['insider_summary']}")
                with gr:
                    live = gem.get("live_price")
                    entry = gem.get("target_entry")
                    exit_ = gem.get("target_exit")
                    stop = gem.get("stop_price")
                    live_s = f"{live:,.2f}" if pd.notna(live) else "—"
                    entry_s = f"{entry:,.2f}" if pd.notna(entry) else "—"
                    exit_s = f"{exit_:,.2f}" if pd.notna(exit_) else "—"
                    stop_s = f"{stop:,.2f}" if pd.notna(stop) else "—"
                    st.markdown(
                        f"Gem score **{gem['gem_score']:.2f}** "
                        f"(quality {gem['composite']:.2f} · today {gem['today_score']:.2f})  \n"
                        f"Live {live_s} · Buy ≤ {entry_s} · Sell ≥ {exit_s} · "
                        f"**Stop {stop_s}**  \n"
                        f"{cap_line}"
                    )
                with st.expander("Company card"):
                    gem_row = view[view["ticker"] == gem["ticker"]]
                    if not gem_row.empty:
                        _render_watchlist_ticker_card(
                            st, gem_row.iloc[0],
                            insider_overlay=insider_overlay,
                            catalyst_overlay=catalyst_overlay,
                        )

    st.divider()

    # ---- ☀️ Today's signals (day-scale action ranking) ---------------------
    st.markdown("### ☀️ Today's signals")
    st.caption(
        "Of everything in the buy zone, which deserves attention TODAY. "
        "Ranked by relative volume (is money flowing in right now?), zone "
        "freshness (crossed in today beats sat-there-for-months), 5-day "
        "momentum, theme heat, R:R — plus a bonus for 48h news headlines. "
        "Unlike 💎 Gems, no quality gates apply here — this is the "
        "attention list, not the buy list."
    )
    if not buy_zone_tickers:
        st.info("Nothing in the buy zone right now — no daily signals to rank.")
    else:
        if today.empty:
            st.info("No buy-zone stock produced a rankable signal today.")
        else:
            for _, sig in today.iterrows():
                with st.container(border=True):
                    hl, hr = st.columns([3, 2])
                    with hl:
                        st.markdown(
                            f"**#{int(sig['rank'])}  {sig['ticker']}** — "
                            f"{sig['name'] or ''}"
                        )
                        st.caption(sig["reasons"])
                    with hr:
                        score_pct = f"{sig['today_score']:.2f}"
                        live = sig.get("live_price")
                        entry = sig.get("target_entry")
                        stop = sig.get("stop_price")
                        live_s = f"{live:,.2f}" if pd.notna(live) else "—"
                        entry_s = f"{entry:,.2f}" if pd.notna(entry) else "—"
                        stop_s = f"{stop:,.2f}" if pd.notna(stop) else "—"
                        st.markdown(
                            f"Today score **{score_pct}**  \n"
                            f"Live {live_s} · Buy ≤ {entry_s} · Stop {stop_s}"
                        )
            st.caption(
                "⚠️ Volume and news are *attention* signals, not quality "
                "signals — they say 'look here today', not 'buy this'. "
                "Check the company card and the Top picks composite before acting."
            )

    st.divider()

    # ---- 🏆 Top picks today (composite winner ranker) ----------------------
    st.markdown("### 🏆 Top picks today")
    st.caption(
        "Composite of analyst signal (30%), reward-to-risk (20%), theme momentum (15%), "
        "personal 12-1 momentum (15%), insider-buying overlay (10%), and upcoming-catalyst "
        "proximity (10%). Blow-off penalty subtracted when 6-month gain exceeds the threshold "
        "below (don't chase parabolic tops). Click any row to expand the full company card."
    )
    with st.expander("Tune the picker", expanded=False):
        # One-tap preset: the £5k Runbook (Xu-style concentrated momentum).
        # Callback sets widget session-state BEFORE the rerun re-creates them.
        def _apply_runbook_preset() -> None:
            ss = st.session_state
            ss["picker_top_n"] = 10
            ss["picker_blowoff"] = 100
            ss["picker_excl_sell"] = True
            ss["picker_cap_label"] = "Small cap < $300M"
            ss["picker_require_cap"] = True
            ss["picker_strict"] = True
            ss["picker_strict_rr"] = 3.0

        st.button(
            "⚡ £5k Runbook preset",
            on_click=_apply_runbook_preset,
            help="One tap: Strict mode ON, R:R floor 3.0, cap < $300M with "
                 "known cap required, blow-off 100%, top 10. The survivors "
                 "list SHOULD be empty most days — that's the discipline.",
        )

        tc = st.columns(3)
        with tc[0]:
            picks_n = st.slider("How many picks", 5, 50, 15, step=5,
                                key="picker_top_n")
        with tc[1]:
            blowoff = st.slider(
                "Blow-off threshold (6m %)", 30, 300, 100, step=10,
                key="picker_blowoff",
                help="6-month returns above this start subtracting from the composite.",
            )
        with tc[2]:
            exclude_sell = st.checkbox("Exclude SELL ZONE", value=True,
                                       key="picker_excl_sell")

        # Market-cap filter row
        cap_known = int(view["market_cap_usd"].notna().sum()) if "market_cap_usd" in view.columns else 0
        cap_pct = (cap_known / max(len(view), 1)) * 100
        st.caption(
            f"Market caps known for **{cap_known} / {len(view)}** tickers "
            f"({cap_pct:.0f}%). Uncached tickers show '—' until fetched."
        )
        if cap_known < len(view) * 0.75:
            cap_btn_cols = st.columns([3, 2])
            with cap_btn_cols[0]:
                st.warning(
                    "Many caps are still uncached. Click to fetch them now "
                    "(~30-90 s for the full watchlist via yfinance `fast_info`)."
                )
            with cap_btn_cols[1]:
                if st.button("🔄 Fetch missing market caps", use_container_width=True):
                    from .ticker_facts import quick_market_caps
                    tickers_to_fetch = view["ticker"].astype(str).tolist()
                    progress = st.progress(0.0, text="Fetching market caps…")
                    total = len(tickers_to_fetch)

                    def _cb(done: int, total_: int) -> None:
                        try:
                            progress.progress(min(1.0, done / total_),
                                              text=f"Fetching market caps… {done}/{total_}")
                        except Exception:  # noqa: BLE001
                            pass

                    with st.spinner("Hitting yfinance fast_info in parallel…"):
                        n_new = quick_market_caps(
                            tickers_to_fetch, max_workers=16, progress_cb=_cb,
                        )
                    st.success(f"Fetched {n_new} new market caps. Refreshing view…")
                    st.rerun()
        cap_row = st.columns([3, 2])
        with cap_row[0]:
            cap_options = {
                "No filter": (None, None),
                "Microcap < $100M (parabolic hunting)": (None, 100_000_000),
                "Small cap < $300M": (None, 300_000_000),
                "Sub-$1B": (None, 1_000_000_000),
                "Sub-$5B": (None, 5_000_000_000),
                "$100M – $1B": (100_000_000, 1_000_000_000),
            }
            cap_label = st.selectbox(
                "Market cap filter", list(cap_options.keys()), index=0,
                key="picker_cap_label",
                help="When 'Require known cap' is on, tickers without a known cap are excluded.",
            )
            min_cap, max_cap = cap_options[cap_label]
        with cap_row[1]:
            require_known = st.checkbox(
                "Require known cap", value=True,
                key="picker_require_cap",
                help="Excludes tickers we don't have a market cap for. "
                     "On by default so the cap filter actually filters.",
            )

        # Strict mode — hard gates, no weighted-average dilution
        strict_row = st.columns([3, 2])
        with strict_row[0]:
            strict_mode = st.checkbox(
                "🎯 Strict mode (hard gates instead of weighted average)",
                value=False,
                key="picker_strict",
                help=(
                    "Only ticks that pass ALL of these survive: BUY ZONE, "
                    "3m momentum > 0, theme 3m median > 0, R:R ≥ threshold, "
                    "6m < blow-off threshold. Composite then ranks the survivors."
                ),
            )
        with strict_row[1]:
            strict_min_rr = st.slider(
                "Strict R:R floor", 1.0, 5.0, 2.0, step=0.5,
                key="picker_strict_rr",
                disabled=not strict_mode,
                help="Minimum reward-to-risk to pass the strict gate. R:R=∞ (live ≤ entry) always passes.",
            )
        overlay_notes = []
        if insider_overlay:
            overlay_notes.append(
                f"💼 Insider overlay: **{len(insider_overlay)} tickers** with "
                "recent open-market Form 4 buying (2-day filing lag)."
            )
        else:
            overlay_notes.append(
                "💼 Insider overlay inactive — OpenInsider unreachable this "
                "load; picks rely on the other layers."
            )
        if catalyst_overlay:
            overlay_notes.append(
                f"Catalyst overlay: **{len(catalyst_overlay)} tickers** with "
                "upcoming events in the next 180 days."
            )
        else:
            overlay_notes.append("Catalyst overlay inactive (no `catalysts.parquet`).")
        for n in overlay_notes:
            st.caption(n)

    picks = pick_winners(
        view,
        top_n=picks_n,
        blowoff_threshold_pct=float(blowoff),
        exclude_sell_zone=exclude_sell,
        insider_overlay=insider_overlay or None,
        catalyst_overlay=catalyst_overlay or None,
        min_market_cap_usd=min_cap,
        max_market_cap_usd=max_cap,
        require_known_cap=require_known,
        strict_mode=strict_mode,
        strict_min_rr=float(strict_min_rr),
    )
    if strict_mode:
        st.caption(
            f"🎯 Strict mode active: **{len(picks)} tickers** passed every hard gate "
            f"(BUY ZONE, 3m>0, hot theme, R:R≥{strict_min_rr:.1f}, 6m<{blowoff:.0f}%)."
        )
    if picks.empty:
        st.info("No picks meet the criteria. Loosen the filters or check that prices loaded.")
    else:
        picks = picks.copy()
        if "market_cap_usd" in picks.columns:
            picks["mkt_cap"] = picks["market_cap_usd"].apply(_fmt_cap_short)
        # Compact default for phones — fewer columns means no horizontal scroll.
        # Power users can flip the toggle to see every sub-score.
        show_all_picks = st.toggle(
            "🔬 Show all score columns",
            value=False,
            key="picks_show_all_cols",
            help="Reveals the per-layer sub-scores and target prices. Off by default for phone-friendly width.",
        )
        compact_picks_cols = [
            "rank", "ticker", "name", "status",
            "mkt_cap", "composite",
            "reward_risk", "pct_3m", "pct_6m",
        ]
        full_picks_cols = [
            "rank", "ticker", "name", "theme", "status",
            "mkt_cap", "composite",
            "score_analyst", "score_rr", "score_theme",
            "score_momentum", "score_insider", "score_catalyst",
            "catalyst_days", "blowoff_penalty",
            "live_price", "target_entry", "target_exit",
            "reward_risk", "pct_3m", "pct_6m",
        ]
        picks_cols = full_picks_cols if show_all_picks else compact_picks_cols
        picks_cols = [c for c in picks_cols if c in picks.columns]
        picks_event = st.dataframe(
            picks[picks_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="top_picks_table",
            column_config={
                "rank": st.column_config.NumberColumn("#", format="%d"),
                "ticker": "Ticker",
                "name": "Name",
                "theme": "Theme",
                "status": "Status",
                "mkt_cap": st.column_config.TextColumn(
                    "Mkt cap",
                    help="Compact market cap: $50M, $1.2B, '—' for unknown.",
                ),
                "composite": st.column_config.ProgressColumn(
                    "Composite", min_value=0.0, max_value=1.0, format="%.2f",
                ),
                "score_analyst": st.column_config.NumberColumn("Analyst", format="%.2f"),
                "score_rr": st.column_config.NumberColumn("R:R sub", format="%.2f"),
                "score_theme": st.column_config.NumberColumn("Theme", format="%.2f"),
                "score_momentum": st.column_config.NumberColumn("12-1 mo", format="%.2f"),
                "score_insider": st.column_config.NumberColumn(
                    "Insider", format="%.2f",
                    help="SEC Form 4 insider-buying composite: clustered open-market buys by senior insiders.",
                ),
                "score_catalyst": st.column_config.NumberColumn(
                    "Cat", format="%.2f",
                    help="Proximity to the next upcoming catalyst (1.0 at 0 days, 0 at 180d).",
                ),
                "catalyst_days": st.column_config.NumberColumn(
                    "Cat in", format="%d d",
                    help="Days until the next upcoming catalyst.",
                ),
                "blowoff_penalty": st.column_config.NumberColumn(
                    "Penalty", format="%.2f",
                    help="Subtracted from the composite for runaway 6m returns.",
                ),
                "live_price": st.column_config.NumberColumn("Live", format="%.2f"),
                "target_entry": st.column_config.NumberColumn("Buy ≤", format="%.2f"),
                "target_exit": st.column_config.NumberColumn("Sell ≥", format="%.2f"),
                "reward_risk": st.column_config.NumberColumn("R:R", format="%.2f"),
                "pct_3m": st.column_config.NumberColumn("3m", format="%+.1f%%"),
                "pct_6m": st.column_config.NumberColumn("6m", format="%+.1f%%"),
            },
        )
        if picks_event is not None and picks_event.selection.rows:
            sel_ticker = str(picks.iloc[picks_event.selection.rows[0]]["ticker"])
            sel_row = view[view["ticker"] == sel_ticker].iloc[0]
            _render_watchlist_ticker_card(
                st, sel_row,
                insider_overlay=insider_overlay,
                catalyst_overlay=catalyst_overlay,
            )

    st.divider()

    # ---- Filter bar --------------------------------------------------------
    with st.expander("Filters", expanded=True):
        cols = st.columns(3)
        with cols[0]:
            f_status = st.multiselect(
                "Status",
                options=["BUY ZONE", "APPROACHING", "HOLD", "SELL ZONE", "WATCH"],
                default=["BUY ZONE", "APPROACHING"],
                help="Default shows only actionable rows.",
            )
        with cols[1]:
            f_themes = st.multiselect(
                "Themes",
                options=sorted(view["theme"].dropna().unique().tolist()),
                default=[],
            )
        with cols[2]:
            f_ticker = st.text_input("Ticker contains", placeholder="e.g. NVDA")

    cut = view.copy()
    if f_status:
        cut = cut[cut["status"].isin(f_status)]
    if f_themes:
        cut = cut[cut["theme"].isin(f_themes)]
    if f_ticker.strip():
        needle = f_ticker.strip().upper()
        cut = cut[cut["ticker"].str.contains(needle, na=False)]
    cut = cut.sort_values(
        by=["status", "gap_to_entry_pct"], ascending=[True, True],
    )

    # ---- Headline counts ---------------------------------------------------
    n_buy = int((view["status"] == "BUY ZONE").sum())
    n_appr = int((view["status"] == "APPROACHING").sum())
    n_sell = int((view["status"] == "SELL ZONE").sum())
    cols = st.columns(4)
    cols[0].metric("🟢 In buy zone", n_buy)
    cols[1].metric("🟡 Approaching", n_appr)
    cols[2].metric("🔴 In sell zone", n_sell)
    cols[3].metric("Total tracked", len(view))

    # ---- Main table --------------------------------------------------------
    cut = cut.copy()
    if "market_cap_usd" in cut.columns:
        cut["mkt_cap"] = cut["market_cap_usd"].apply(_fmt_cap_short)
    show_all_main = st.toggle(
        "📊 Show all columns",
        value=False,
        key="main_show_all_cols",
        help="Reveals theme, exit target, all four momentum periods, and the analyst note. Off for phone-friendly width.",
    )
    compact_main_cols = [
        "status", "ticker", "mkt_cap",
        "live_price", "target_entry", "stop_price", "tgt_src",
        "gap_to_entry_pct", "pct_3m",
    ]
    full_main_cols = [
        "status", "ticker", "name", "theme", "mkt_cap",
        "live_price", "target_entry", "target_exit", "stop_price", "tgt_src",
        "gap_to_entry_pct", "reward_risk",
        "pct_1m", "pct_3m", "pct_6m", "pct_12m",
        "description",
    ]
    display_cols = full_main_cols if show_all_main else compact_main_cols
    display_cols = [c for c in display_cols if c in cut.columns]
    st.caption("👇 Click any row to expand the company description below.")
    cut_display = cut[display_cols].reset_index(drop=True)
    main_event = st.dataframe(
        cut_display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="watchlist_main_table",
        column_config={
            "status": "Status",
            "ticker": "Ticker",
            "name": "Name",
            "theme": "Theme",
            "mkt_cap": st.column_config.TextColumn(
                "Mkt cap",
                help="Compact market cap: $50M, $1.2B, '—' for unknown.",
            ),
            "live_price": st.column_config.NumberColumn("Live", format="%.2f"),
            "target_entry": st.column_config.NumberColumn("Buy ≤", format="%.2f"),
            "target_exit": st.column_config.NumberColumn("Sell ≥", format="%.2f"),
            "stop_price": st.column_config.NumberColumn(
                "Stop", format="%.2f",
                help="Suggested stop: 12% below your fill — the live price "
                     "when in the buy zone, otherwise the entry target. "
                     "Pre-commit it before you buy.",
            ),
            "tgt_src": st.column_config.TextColumn(
                "Tgt",
                help="Target provenance, entry/exit: A = analyst-set, "
                     "D = derived from the learned pattern, — = none.",
            ),
            "gap_to_entry_pct": st.column_config.NumberColumn(
                "Gap to buy",
                format="%+.1f%%",
                help="How far above the buy target the live price is. Negative = in buy zone.",
            ),
            "reward_risk": st.column_config.NumberColumn(
                "R:R", format="%.2f",
                help="Upside-to-exit divided by downside-to-entry, from current price.",
            ),
            "pct_1m": st.column_config.NumberColumn("1m", format="%+.1f%%"),
            "pct_3m": st.column_config.NumberColumn("3m", format="%+.1f%%"),
            "pct_6m": st.column_config.NumberColumn("6m", format="%+.1f%%"),
            "pct_12m": st.column_config.NumberColumn("12m", format="%+.1f%%"),
            "description": "Notes",
        },
    )
    if main_event is not None and main_event.selection.rows:
        selected_idx = main_event.selection.rows[0]
        # The main table is filtered + sorted, so go through the displayed
        # ticker rather than positional index from `view`.
        selected_ticker = str(cut_display.iloc[selected_idx]["ticker"])
        selected_row = view[view["ticker"] == selected_ticker].iloc[0]
        _render_watchlist_ticker_card(
            st, selected_row,
            insider_overlay=insider_overlay,
            catalyst_overlay=catalyst_overlay,
        )

    # ---- Theme heat + parabolic ranking ------------------------------------
    cols = st.columns(2)
    heat_event = None
    heat = theme_heat(view)
    with cols[0]:
        st.markdown("#### 🔥 Theme heat (3m median %)")
        st.caption("Click a row to see the tickers in that theme below.")
        if heat.empty:
            st.info("Not enough price history to rank themes yet.")
        else:
            heat_event = st.dataframe(
                heat, use_container_width=True, hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="theme_heat_table",
                column_config={
                    "theme": "Theme",
                    "n": "Tickers",
                    "median_3m": st.column_config.NumberColumn("3m", format="%+.1f%%"),
                    "median_6m": st.column_config.NumberColumn("6m", format="%+.1f%%"),
                    "median_12m": st.column_config.NumberColumn("12m", format="%+.1f%%"),
                },
            )
    para_event = None
    para = parabolic_rank(view, horizon="pct_6m", top_n=25)
    with cols[1]:
        st.markdown("#### 🚀 Parabolic winners (6m gain)")
        st.caption("Click a row to expand the company info below.")
        if para.empty:
            st.info("No price history available to rank.")
        else:
            para_event = st.dataframe(
                para[["ticker", "name", "theme", "pct_6m", "pct_12m", "status"]],
                use_container_width=True, hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="parabolic_winners_table",
                column_config={
                    "ticker": "Ticker",
                    "name": "Name",
                    "theme": "Theme",
                    "pct_6m": st.column_config.NumberColumn("6m", format="%+.1f%%"),
                    "pct_12m": st.column_config.NumberColumn("12m", format="%+.1f%%"),
                    "status": "Status",
                },
            )

    if para_event is not None and para_event.selection.rows:
        sel_idx = para_event.selection.rows[0]
        sel_ticker = str(para.iloc[sel_idx]["ticker"])
        sel_row = view[view["ticker"] == sel_ticker].iloc[0]
        _render_watchlist_ticker_card(
            st, sel_row,
            insider_overlay=insider_overlay,
            catalyst_overlay=catalyst_overlay,
        )

    # ---- Theme drill-down --------------------------------------------------
    selected_theme: str | None = None
    if heat_event is not None and getattr(heat_event, "selection", None):
        selected_rows = heat_event.selection.rows
        if selected_rows:
            selected_theme = str(heat.iloc[selected_rows[0]]["theme"])

    if selected_theme:
        drill = view[view["theme"] == selected_theme].copy()
        drill = drill.sort_values(by="pct_3m", ascending=False, na_position="last")
        st.markdown(f"### 🔍 {selected_theme} — {len(drill)} tickers")
        st.caption(
            "Sorted by 3-month momentum. Company description and signal-worthy "
            "context pulled from the curated facts file (yfinance fallback)."
        )
        for _, row in drill.iterrows():
            _render_watchlist_ticker_card(
                st, row,
                insider_overlay=insider_overlay,
                catalyst_overlay=catalyst_overlay,
            )
    else:
        st.info(
            "👆 Pick a theme above to drill into its tickers with company "
            "descriptions and catalyst notes."
        )

    st.caption(
        "Status definitions — **BUY ZONE**: live ≤ analyst buy target. "
        "**APPROACHING**: within 15% above buy target. **SELL ZONE**: live ≥ analyst sell target. "
        "**HOLD**: between zones. **WATCH**: no targets set yet."
    )


def _render_watchlist_ticker_card(
    st,
    row: pd.Series,
    *,
    insider_overlay: dict | None = None,
    catalyst_overlay: dict | None = None,
) -> None:
    """Compact card for a single watchlist ticker: name, live vs targets,
    short company description, and any catalyst hook. Falls back to the
    analyst note from the CSV when curated facts are missing.

    When `insider_overlay` / `catalyst_overlay` are passed, surfaces the
    matching ticker's detail (who, when, upcoming events) inside the card."""
    ticker = str(row.get("ticker", "?"))
    fact = ticker_lookup(ticker)
    display_name = (fact.name if fact else None) or row.get("name") or ticker

    status = row.get("status") or ""
    badge = {
        "BUY ZONE": "🟢", "APPROACHING": "🟡", "HOLD": "⚪",
        "SELL ZONE": "🔴", "WATCH": "⚫", "PRICE MISSING": "❔",
    }.get(status, "")

    live = row.get("live_price")
    entry = row.get("target_entry")
    exit_ = row.get("target_exit")
    pct_3m = row.get("pct_3m")
    pct_6m = row.get("pct_6m")

    def _fmt(v, suffix=""):
        if v is None or pd.isna(v):
            return "—"
        return f"{v:,.2f}{suffix}"

    def _fmt_pct(v):
        if v is None or pd.isna(v):
            return "—"
        return f"{v:+.1f}%"

    with st.container(border=True):
        header_l, header_r = st.columns([3, 2])
        with header_l:
            st.markdown(f"#### {badge} {display_name}  ·  `{ticker}`")
            meta_bits = []
            if fact:
                meta_bits.extend([fact.exchange, CAP_LABEL.get(fact.cap, fact.cap.title()), fact.sector])
            theme = row.get("theme")
            if theme:
                meta_bits.append(f"Theme: {theme}")
            mcap = row.get("market_cap_usd")
            cap_short = _fmt_cap_short(mcap)
            if cap_short != "—":
                meta_bits.append(f"Mkt cap **{cap_short}**")
            if meta_bits:
                st.caption(" · ".join(b for b in meta_bits if b))
        with header_r:
            stop = row.get("stop_price")
            st.markdown(
                f"**Live** {_fmt(live)}  ·  **Buy ≤** {_fmt(entry)}  ·  **Sell ≥** {_fmt(exit_)}"
                f"  ·  **Stop** {_fmt(stop)}  \n"
                f"3m {_fmt_pct(pct_3m)}  ·  6m {_fmt_pct(pct_6m)}  ·  Status **{status or '—'}**"
            )

        # What they do
        summary = (fact.summary if fact else "") or ""
        if summary:
            st.markdown(f"**What they do.** {summary}")
        elif row.get("description"):
            st.markdown(f"**Analyst note.** {row['description']}")

        # Why it tends to be signal-worthy (catalysts / setup)
        why = (fact.why_it_matters if fact else "") or ""
        if why:
            st.markdown(f"**Signal-worthy because.** {why}")
        # If we had a curated summary but also have an analyst note, still surface it
        if summary and row.get("description"):
            st.markdown(f"**Analyst note.** {row['description']}")

        # ---- Insider buying (SEC Form 4) ------------------------------------
        ck = ticker.upper()
        ins = (insider_overlay or {}).get(ck)
        if ins:
            st.markdown(
                f"**💼 Insider buying.** {ins.get('summary') or 'active'} "
                f"(composite **{ins.get('score', 0.0):.2f}**). Open-market "
                "Form 4 purchases, filed within 2 business days — insiders "
                "buying their own stock near your entry level is one of the "
                "strongest confluences this screen knows."
            )

        # ---- Upcoming catalyst ----------------------------------------------
        cat = (catalyst_overlay or {}).get(ck)
        if cat:
            d = cat.get("days_until")
            when = cat.get("next_date")
            cat_label = cat.get("category") or "event"
            rationale = cat.get("rationale") or ""
            head = (
                f"**📅 Upcoming catalyst.** {cat_label.replace('_', ' ').title()} in "
                f"**{int(d)}d** ({when})" if d is not None and when
                else f"**📅 Upcoming catalyst.** {cat_label}"
            )
            st.markdown(f"{head}. {rationale}" if rationale else head + ".")


def _fmt_dollar(v: float) -> str:
    if not pd.notna(v):
        return "—"
    sign = "−" if v < 0 else ""
    av = abs(float(v))
    if av >= 1_000_000:
        return f"{sign}${av / 1e6:.2f}M"
    if av >= 1_000:
        return f"{sign}${av / 1e3:.1f}k"
    return f"{sign}${av:.0f}"


def _render_track_record_tab(st) -> None:
    """Forward-marked signal history. Replays watchlist BUY ZONE crossings
    against actual price data and grades each one (target / stop / timeout
    / open). No persistence — fully reproducible from price history."""
    from .track_record import (
        DEFAULT_POSITION_SIZE_USD,
        build_track_record,
        cumulative_pnl_series,
        summarise_track_record,
    )
    from .watchlist_alerts import (
        WATCHLIST_PATH,
        fetch_price_history,
        load_watchlist,
    )

    st.subheader("📊 Track record — every BUY ZONE signal, marked forward")
    st.caption(
        "Every time a watchlist ticker has crossed into its analyst buy zone "
        "we treat it as a signal, then walk forward bar-by-bar until it hits "
        "the target, hits the stop, or times out at 6 months. No look-ahead, "
        "no edits, no survivorship — every signal that fired is here."
    )

    watchlist = load_watchlist(WATCHLIST_PATH)
    if watchlist.empty:
        st.warning(f"No watchlist file at `{WATCHLIST_PATH}`.")
        return
    tradable = watchlist[
        watchlist["target_entry"].notna() & (watchlist["target_entry"] > 0)
    ]
    if tradable.empty:
        st.info(
            "No watchlist tickers have a target_entry yet — nothing to score. "
            "Add buy targets in `data/watchlist.csv`."
        )
        return

    with st.expander("Replay parameters", expanded=False):
        prm = st.columns(4)
        with prm[0]:
            stop_pct = st.slider(
                "Stop %", 5, 25, 10, step=1,
                help="How far below entry triggers the stop.",
            ) / 100.0
        with prm[1]:
            timeout_days = st.slider(
                "Timeout days", 30, 365, 180, step=30,
                help="How long a signal can stay open before forced close.",
            )
        with prm[2]:
            cooldown_days = st.slider(
                "Re-signal cooldown", 0, 90, 30, step=5,
                help="Minimum days between two signals on the same ticker.",
            )
        with prm[3]:
            position_size_usd = st.number_input(
                "Position size ($)",
                min_value=1_000.0, max_value=50_000_000.0,
                value=float(DEFAULT_POSITION_SIZE_USD), step=1_000.0,
                help="Notional per signal. Doesn't change relative performance — only the dollar headlines.",
            )

    tickers = sorted(set(tradable["ticker"].tolist()))
    with st.spinner(f"Replaying {len(tickers)} tickers with 2y of price history..."):
        try:
            history = fetch_price_history(tickers, period="2y")
        except Exception as exc:
            st.error(f"Price fetch failed: {exc}")
            return

    if not history:
        st.warning("No price history available — track record is empty.")
        return

    signals = build_track_record(
        tradable, history,
        stop_pct=stop_pct,
        timeout_days=int(timeout_days),
        cooldown_days=int(cooldown_days),
    )
    if signals.empty:
        st.info("No BUY ZONE crossings detected in the price history.")
        return

    summary = summarise_track_record(signals, position_size_usd=position_size_usd)

    # ---- At a glance -------------------------------------------------------
    st.markdown("### At a glance")
    g = st.columns(6)
    g[0].metric("Picks", summary["total"])
    g[1].metric("Closed", summary["closed"])
    g[2].metric("Win rate", f"{summary['win_rate'] * 100:.0f}%")
    g[3].metric("Hit rate", f"{summary['hit_rate'] * 100:.0f}%",
                help="Closed via target only (not stop or timeout).")
    g[4].metric("Avg return", f"{summary['avg_return_pct']:+.2f}%")
    g[5].metric("Realised", _fmt_dollar(summary["total_realised_usd"]))

    if summary["closed"] < 30:
        st.caption(
            f"⚠️ Only **{summary['closed']} closed signals** — too few to draw "
            "conclusions. Win/hit rates need at least 30 closures before the "
            "noise floor drops below the signal."
        )

    # ---- Cumulative P&L chart ---------------------------------------------
    pnl = cumulative_pnl_series(signals, position_size_usd=position_size_usd)
    if not pnl.empty:
        st.markdown("#### Cumulative realised P&L")
        chart_df = pnl.set_index("close_date")["cumulative_usd"]
        st.line_chart(chart_df, height=240)

    # ---- Recent closed ----------------------------------------------------
    closed = signals[~signals["open"]].copy()
    if not closed.empty:
        st.markdown("#### Recent closed signals")
        closed = closed.sort_values("close_date", ascending=False).head(15)
        closed["realised_usd"] = (
            closed["return_pct"] / 100.0 * position_size_usd
        ).apply(_fmt_dollar)
        result_label = closed["close_reason"].map({
            "target": "🎯 Hit target",
            "stop": "🛑 Hit stop",
            "timeout": "⏰ Timeout",
        }).fillna(closed["close_reason"])
        closed_display = closed.assign(result=result_label)[[
            "close_date", "ticker", "entry_price", "close_price",
            "return_pct", "realised_usd", "days_held", "result",
        ]].reset_index(drop=True)
        st.dataframe(
            closed_display, use_container_width=True, hide_index=True,
            column_config={
                "close_date": "Closed",
                "ticker": "Ticker",
                "entry_price": st.column_config.NumberColumn("Entry", format="$%.2f"),
                "close_price": st.column_config.NumberColumn("Exit", format="$%.2f"),
                "return_pct": st.column_config.NumberColumn("Return", format="%+.1f%%"),
                "realised_usd": st.column_config.TextColumn("P&L"),
                "days_held": st.column_config.NumberColumn("Days", format="%d"),
                "result": "Result",
            },
        )

    # ---- Open signals -----------------------------------------------------
    open_signals = signals[signals["open"]].copy()
    if not open_signals.empty:
        st.markdown("#### Live signals (still in play)")
        open_signals = open_signals.sort_values("return_pct", ascending=False)
        open_signals["mtm_usd"] = (
            open_signals["return_pct"] / 100.0 * position_size_usd
        ).apply(_fmt_dollar)
        st.dataframe(
            open_signals[[
                "signal_date", "ticker", "entry_price", "close_price",
                "return_pct", "mtm_usd", "days_held",
            ]].reset_index(drop=True),
            use_container_width=True, hide_index=True,
            column_config={
                "signal_date": "Signal",
                "ticker": "Ticker",
                "entry_price": st.column_config.NumberColumn("Entry", format="$%.2f"),
                "close_price": st.column_config.NumberColumn("Current", format="$%.2f"),
                "return_pct": st.column_config.NumberColumn("Move", format="%+.1f%%"),
                "mtm_usd": st.column_config.TextColumn("MTM"),
                "days_held": st.column_config.NumberColumn("Days", format="%d"),
            },
        )

    # ---- Honest caveats --------------------------------------------------
    with st.expander("How this stays honest"):
        st.markdown(
            "- **Forward-marking only.** A signal's entry price is the close on the "
            "day price first crossed at or below the analyst's buy target. Exits use "
            "prices strictly *after* that date — no look-ahead.\n"
            "- **Pre-set exits.** Target (analyst's `target_exit`), stop (entry × "
            f"{1 - stop_pct:.0%}), and a {int(timeout_days)}-day timeout are fixed "
            "the moment the signal fires.\n"
            "- **Conservative tie-break.** When a daily bar's range could plausibly "
            "have touched both target and stop, we assume the stop fired — never "
            "the optimistic outcome.\n"
            "- **No survivorship.** Every signal that fired is on this page, "
            "winners and losers alike. Re-signals on the same ticker within the "
            "cooldown are merged into the existing one.\n"
            "- **Caveat:** the replay assumes *today's* analyst targets applied "
            "historically. If a target was raised last week, the entire history is "
            "rescored against the new level. Fair approximation, not literal history.\n"
            "- **Hit rate ≠ win rate.** Win rate is *any* profitable close (could be "
            "a timeout above water). Hit rate is the stricter set that actually "
            "hit the target. Both matter — they tell different stories about R:R.\n"
            f"- **Sample size.** Below 30 closed signals (currently {summary['closed']}), "
            "headline figures are noisy. Wait for the count to build before drawing conclusions."
        )

    # ---- ⚡ £5k Runbook backtest -------------------------------------------
    st.divider()
    st.markdown("### ⚡ £5k Runbook backtest — concentrated momentum, replayed")
    st.caption(
        "Simulates the Xu-style runbook on this watchlist over the same price "
        "history: max 2 positions, hard −12% stop, entries only when a BUY "
        "ZONE crossing coincides with positive stock momentum, a hot theme, "
        "R:R ≥ 3 to the analyst exit, and a small market cap. Winners get one "
        "pyramid add at +25% with the stop moved to breakeven. "
        "Currency-agnostic notional — treat the £ figures as relative."
    )

    with st.expander("Runbook parameters", expanded=False):
        rb = st.columns(4)
        with rb[0]:
            rb_capital = st.number_input(
                "Start capital (£)", min_value=500.0, max_value=1_000_000.0,
                value=5_000.0, step=500.0, key="runbook_capital",
            )
        with rb[1]:
            rb_stop = st.slider("Stop %", 5, 25, 12, step=1, key="runbook_stop")
        with rb[2]:
            rb_rr = st.slider("Min R:R", 1.0, 5.0, 3.0, step=0.5, key="runbook_rr")
        with rb[3]:
            rb_cap_label = st.selectbox(
                "Cap ceiling", ["< $100M", "< $300M", "< $1B", "No cap filter"],
                index=1, key="runbook_cap",
            )
        rb_require_cap = st.checkbox(
            "Require known market cap", value=True, key="runbook_require_cap",
            help="With this off, tickers whose cap we don't know are allowed through the cap gate.",
        )

    if st.button("▶ Run the £5k backtest", key="runbook_run"):
        from .runbook_backtest import RunbookParams, simulate_runbook
        from .ticker_facts import lookup as _facts_lookup

        cap_map = {
            "< $100M": 100_000_000.0, "< $300M": 300_000_000.0,
            "< $1B": 1_000_000_000.0, "No cap filter": None,
        }
        rb_tradable = watchlist[
            watchlist["target_entry"].notna() & (watchlist["target_entry"] > 0)
            & watchlist["target_exit"].notna() & (watchlist["target_exit"] > 0)
        ]
        market_caps: dict[str, float] = {}
        for t in rb_tradable["ticker"].astype(str):
            fact = _facts_lookup(t, cache_only=True)
            if fact is not None and fact.market_cap_usd is not None:
                market_caps[t.upper()] = float(fact.market_cap_usd)

        params = RunbookParams(
            start_capital=float(rb_capital),
            stop_pct=rb_stop / 100.0,
            min_rr=float(rb_rr),
            max_market_cap_usd=cap_map[rb_cap_label],
            require_known_cap=bool(rb_require_cap),
        )
        with st.spinner("Replaying the runbook bar-by-bar..."):
            st.session_state["runbook_result"] = simulate_runbook(
                rb_tradable, history, params, market_caps=market_caps,
            )

    result = st.session_state.get("runbook_result")
    if result is not None:
        stats = result["stats"]
        m = st.columns(5)
        m[0].metric("Final equity", f"£{stats['final_equity']:,.0f}",
                    f"{stats['return_pct']:+.1f}%")
        m[1].metric("Max drawdown", f"{stats['max_drawdown_pct']:.1f}%")
        m[2].metric("Closed trades", stats["n_closed"])
        m[3].metric("Win rate", f"{stats['win_rate'] * 100:.0f}%")
        m[4].metric("Avg / trade", f"{stats['avg_return_pct']:+.1f}%")

        if stats["n_closed"] == 0 and stats["n_open"] == 0:
            st.info(
                "The runbook never fired — no watchlist name passed every gate "
                "in this price window. That's informative in itself: either the "
                "gates are too tight for this list, or the list lacks the "
                "small-cap runners the style needs. Try relaxing the cap "
                "ceiling or R:R floor."
            )
        else:
            equity = result["equity"]
            if not equity.empty:
                st.markdown("#### Equity curve")
                st.line_chart(equity.set_index("date")["equity"], height=240)

            trades = result["trades"]
            if not trades.empty:
                st.markdown("#### Trades")
                reason_label = trades["reason"].map({
                    "target": "🎯 Target", "stop": "🛑 Stop",
                    "breakeven-stop": "⚖️ Breakeven stop", "trail": "📉 Trail",
                    "strength": "🚀 Sold into strength", "timeout": "⏰ Timeout",
                    "open": "🟢 Open",
                }).fillna(trades["reason"])
                tdisp = trades.assign(result=reason_label)[[
                    c for c in ("entry_date", "exit_date", "ticker",
                                "entry_price", "exit_price", "return_pct",
                                "days_held", "pyramided", "result")
                    if c in trades.columns
                ]]
                st.dataframe(
                    tdisp, use_container_width=True, hide_index=True,
                    column_config={
                        "entry_date": "In", "exit_date": "Out",
                        "ticker": "Ticker",
                        "entry_price": st.column_config.NumberColumn("Entry", format="$%.2f"),
                        "exit_price": st.column_config.NumberColumn("Exit", format="$%.2f"),
                        "return_pct": st.column_config.NumberColumn("Return", format="%+.1f%%"),
                        "days_held": st.column_config.NumberColumn("Days", format="%d"),
                        "pyramided": st.column_config.CheckboxColumn("Pyramided"),
                        "result": "Result",
                    },
                )
        st.caption(
            "⚠️ One simulated path with today's targets and caps applied "
            "historically, close-only fills, no slippage or commissions. "
            "Treat as an upper bound on the style's performance here — "
            "not an expectation, and not financial advice."
        )

    # ---- 🧪 Signal Lab: comparison backtest across signal variants ---------
    st.divider()
    st.markdown("### 🧪 Signal Lab — which signal definition actually works?")
    st.caption(
        "The gem gates were designed from priors, not proof. This replays "
        "SEVEN signal definitions over the same price history with the same "
        "exits — different momentum windows (1m / 3m / 6m), gates switched "
        "off one at a time, and a no-gate control (every buy-zone crossing). "
        "If the gated variants can't beat the control, the gates subtract "
        "value. The walk-forward split is the honesty check: **believe only "
        "variants that win in BOTH halves** of history — one-half winners "
        "are curve-fit noise."
    )
    if st.button("▶ Run the signal comparison", key="signal_lab_run"):
        from .signal_lab import compare_variants
        with st.spinner("Replaying 7 signal variants over 2y of history..."):
            st.session_state["signal_lab_result"] = compare_variants(
                tradable, history,
            )
    lab = st.session_state.get("signal_lab_result")
    if lab is not None:
        if lab.empty:
            st.info("No signals fired for any variant — not enough targets or history.")
        else:
            lab_disp = lab.copy()
            lab_disp["win_rate"] = lab_disp["win_rate"] * 100.0
            st.dataframe(
                lab_disp, use_container_width=True, hide_index=True,
                column_config={
                    "variant": "Signal definition",
                    "n_signals": st.column_config.NumberColumn("Signals", format="%d"),
                    "n_closed": st.column_config.NumberColumn("Closed", format="%d"),
                    "win_rate": st.column_config.NumberColumn("Win rate", format="%.0f%%"),
                    "avg_return_pct": st.column_config.NumberColumn(
                        "Avg ret", format="%+.1f%%",
                        help="Equal-weighted mean return of closed signals.",
                    ),
                    "median_return_pct": st.column_config.NumberColumn("Median", format="%+.1f%%"),
                    "avg_days_held": st.column_config.NumberColumn("Avg days", format="%.0f"),
                    "n_train": st.column_config.NumberColumn("n 1st half", format="%d"),
                    "avg_train_pct": st.column_config.NumberColumn(
                        "1st half", format="%+.1f%%",
                        help="Mean return of signals fired in the FIRST half of the date range.",
                    ),
                    "n_test": st.column_config.NumberColumn("n 2nd half", format="%d"),
                    "avg_test_pct": st.column_config.NumberColumn(
                        "2nd half", format="%+.1f%%",
                        help="Mean return of signals fired in the SECOND half — the out-of-sample check.",
                    ),
                },
            )
            st.caption(
                "How to read it: a variant earns trust only if its average "
                "return beats the control in BOTH halves with a reasonable "
                "sample (n ≥ 15 per half). Win rate alone misleads — a 60% "
                "win rate on 2:1 payoffs beats 80% on 0.5:1. If a variant "
                "wins decisively here, tell Claude to make it the default "
                "gate set. Not financial advice."
            )


def _render_about_tab(st) -> None:
    """Plain-English guide to what the app is and how each piece works."""
    st.subheader("ℹ️ What is Icarus?")
    st.markdown(
        """
Icarus is a **stock-watching research tool**. It tracks a curated list of
shares that an analyst has set buy and sell price targets for, compares those
targets against live market prices every day, and tells you which — if any —
deserve attention **today**.

It does not place trades, it does not manage money, and nothing in it is
financial advice. It ranks; you decide.

---

### The one-minute version

Every stock on the watchlist has a **buy target** (the price at which it looks
cheap) and a **sell target** (the price at which the gains have been made).
When the live price falls to or below the buy target, the stock is **in the
buy zone**. Being cheap isn't enough, though — a stock can be cheap because
it's dying. So Icarus runs every buy-zone stock through a series of quality
checks, and only the rare names that pass *everything* while also showing
signs of life today are called **💎 Gems**. From the gems, one name is crowned
**👑 Pick of the Day** — or the app explicitly says *"no trade today"*, which
is a real answer, not a failure.

---

### The Watchlist tab, from top to bottom

**🔎 Ticker lookup** — type any ticker to see its full picture: price,
targets, stop, and exactly why it is or isn't a gem right now.

**👑 Pick of the Day** — the single best opportunity across every pool,
ranked by *trust-adjusted* score. Names with genuine analyst targets count
fully; names whose targets were estimated by the app count less. If nothing
clears the conviction bar, the verdict is "no trade today".

**💎 Gems** — every stock that passed ALL of these at once:
- price in the **buy zone**
- its own momentum is positive over 3 months (not a falling knife)
- its **theme** (AI, nuclear, biotech…) is rising as a group
- the potential reward is at least **3× the risk** to the stop
- it hasn't already gone parabolic (no chasing tops)
- plus something is *happening* today — unusual volume, a fresh entry into
  the zone, or news

Empty most days **by design**. When it's empty, the app explains what the
nearest misses failed on.

**☀️ Today's signals** — the attention list: buy-zone stocks ranked by
what's moving *today* (volume surges, fresh crossings, news). No quality
checks here — it says "look at this", never "buy this".

**🏆 Top picks** — a broader scored ranking of the whole watchlist, with a
tuning panel (including the **⚡ £5k Runbook preset**, which switches
everything to strict small-cap hunting mode).

**Main table** — all tickers with status, price, targets, suggested stop,
market cap and momentum. Tap any row for the company card.

**Theme heat / Parabolic winners** — which themes are running as a group,
and which individual names have moved most in 6 months.

---

### The other tabs

**📊 Track record** — the honesty page. Every time a stock ever crossed
into its buy zone, the app replays what would have happened next: hit the
target 🎯, hit the stop 🛑, or timed out ⏰. No editing, no cherry-picking.
It also hosts the **£5k Runbook backtest** — a simulation of a small,
concentrated trading account run under strict rules. Give the record 30+
closed signals before believing any of the percentages.

**Where did the congress tabs go?** Retired. Congressional-trade
filings arrive up to 45 days late and failed validation as a standalone
signal, so they've been replaced by something faster and stronger:
**insider buying** (SEC Form 4). When a company's own executives buy
their stock on the open market — filed within 2 business days — that
shows up as a 💼 line on gem cards and the company card, and adds soft
weight to the picks. Like every overlay: a tailwind, never a gate.

---

### Key terms

| Term | Meaning |
|---|---|
| **Buy zone** | Live price at or below the analyst's buy target |
| **Stop** | Pre-committed exit ~12% below your fill — set it *before* buying |
| **R:R** | Reward-to-risk: upside to the sell target vs downside to the stop |
| **Theme heat** | Median 3-month move of a theme's stocks — is the group running? |
| **Market cap** | Company size. Small (under \\$300M) can multiply; big is steadier |
| **Tgt A/D** | Target provenance: **A** = analyst-set, **D** = derived by the app from the analyst's pattern. Derived targets are estimates and count less |
| **🧭 Explorer** | An optional wider universe of US small-caps, screened weekly. All its targets are derived, so its gems are trust-discounted |
| **Gem score** | Half quality (the gates), half today (volume/freshness/news) |

---

### The philosophy in three lines

1. **Agreement beats any single signal.** Cheap alone, or moving alone, or
   newsy alone is noise. Cheap AND rising AND hot theme AND asymmetric AND
   waking up today — that's a gem.
2. **Not trading is a position.** Most days the right answer is nothing.
   The app is built to say so plainly.
3. **The record keeps us honest.** Signals are graded forward against real
   prices, with the losses on display next to the wins.

---

*Research tool only. Prices via Yahoo Finance (may be delayed). Nothing here
is financial advice — always do your own research, and never risk money you
can't afford to lose.*
        """
    )


def main() -> None:
    try:
        import streamlit as st
    except ImportError:
        raise SystemExit(
            "streamlit is not installed. Install with "
            "`pip install icarus[dashboard]`."
        )

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=APP_ICON_EMOJI,
        layout="wide",
        initial_sidebar_state="collapsed",
        menu_items={
            "Get help": None,
            "Report a Bug": None,
            "About": f"{APP_TITLE} — analyst-watchlist research screen.",
        },
    )
    inject_mobile(st)
    st.title(f"{APP_ICON_EMOJI} {APP_TITLE}")
    st.caption(
        "Analyst-watchlist screen with quality gates, day-scale signals and "
        "a forward-marked track record. Read-only research view — not "
        "financial advice."
    )

    tab_watchlist, tab_track, tab_about = st.tabs(
        ["Watchlist", "📊 Track record", "ℹ️ About"],
    )

    # ---- Watchlist: analyst-curated picks with live alerts ----------------
    with tab_watchlist:
        _render_watchlist_tab(st)

    # ---- Track record: forward-marked signal history ----------------------
    with tab_track:
        _render_track_record_tab(st)

    # ---- About: plain-English guide ---------------------------------------
    with tab_about:
        _render_about_tab(st)

if __name__ == "__main__":
    main()
