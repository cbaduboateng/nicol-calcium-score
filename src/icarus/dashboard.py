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


_POS = "#1baf7a"
_NEG = "#e66767"
_GOLD = "#eda100"


def _sparkline_values(series: pd.Series | None, n: int = 30) -> list[float] | None:
    """Last n closes as a plain list for inline sparkline columns."""
    if series is None:
        return None
    s = series.dropna()
    if len(s) < 2:
        return None
    return [float(v) for v in s.iloc[-n:].tolist()]


def _svg_spark(
    values: list[float] | None, *, w: int = 96, h: int = 32,
) -> str:
    """Inline SVG sparkline (line + soft area fill), coloured by
    direction. Pure string — renders inside the T212-style row list
    without a chart library, so hundreds of rows stay instant."""
    if not values or len(values) < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    pts = [
        (i * (w - 2) / (n - 1) + 1, (h - 3) - (v - lo) / span * (h - 6) + 1.5)
        for i, v in enumerate(values)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"1,{h - 1} " + line + f" {w - 1},{h - 1}"
    up = values[-1] >= values[0]
    stroke = "#2fcf96" if up else "#ef8585"
    fill = "rgba(27,175,122,0.14)" if up else "rgba(230,103,103,0.14)"
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<polygon points="{area}" fill="{fill}"/>'
        f'<polyline points="{line}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
        f"</svg>"
    )


_STATUS_DOT = {
    "BUY ZONE": "buy", "APPROACHING": "appr", "HOLD": "hold",
    "SELL ZONE": "sell", "WATCH": "hold", "PRICE MISSING": "hold",
}


def _instrument_row_html(
    row: pd.Series, spark: list[float] | None, day_pct: float | None,
) -> str:
    """One tappable T212-style row: dot+ticker+name | sparkline | price+chip.
    The anchor sets ?sel=<ticker> which the tab reads to open the
    instrument view."""
    ticker = str(row.get("ticker") or "")
    name = str(row.get("name") or "")
    live = row.get("live_price")
    px = f"{live:,.2f}" if pd.notna(live) else "—"
    cap_s = _fmt_cap_short(row.get("market_cap_usd"))
    stale_mark = "⏳ stale target" if bool(row.get("target_stale")) else ""
    sub_bits = [b for b in (name, cap_s if cap_s != "—" else "", stale_mark) if b]
    dot = _STATUS_DOT.get(str(row.get("status") or ""), "hold")
    chip = _change_chip(day_pct) or '<span class="chip hold"></span>'
    return (
        f'<a class="irow" href="?sel={ticker}" target="_self">'
        f'<div class="irow-l">'
        f'<div class="irow-name"><span class="dot {dot}"></span>{ticker}</div>'
        f'<div class="irow-sub">{" · ".join(sub_bits)}</div>'
        f"</div>"
        f'<div class="irow-spark">{_svg_spark(spark)}</div>'
        f'<div class="irow-r"><div class="irow-px">{px}</div>{chip}</div>'
        f"</a>"
    )


def _change_chip(pct: float | None, label: str = "") -> str:
    """Green/red pill for a % change, Trading212-style."""
    if pct is None or not pd.notna(pct):
        return ""
    cls = "up" if pct >= 0 else "down"
    arrow = "▲" if pct >= 0 else "▼"
    suffix = f" {label}" if label else ""
    return f'<span class="chip {cls}">{arrow} {pct:+.2f}%{suffix}</span>'


def _render_price_chart(
    st,
    series: pd.Series | None,
    *,
    entry: float | None = None,
    exit_: float | None = None,
    stop: float | None = None,
    key: str = "chart",
) -> None:
    """T212-style gradient area chart with range pills — plus the one
    thing a broker chart never shows: the analyst buy / sell / stop
    levels drawn on the price."""
    if series is None or series.dropna().shape[0] < 5:
        st.caption("Not enough price history to chart.")
        return
    import altair as alt

    rng = st.radio(
        "Range", ["1M", "3M", "6M", "1Y"],
        horizontal=True, index=2, key=f"{key}_range",
        label_visibility="collapsed",
    )
    days = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}[rng]
    s = series.dropna().iloc[-days:]
    if len(s) < 2:
        st.caption("Not enough history for that range.")
        return

    first, last = float(s.iloc[0]), float(s.iloc[-1])
    change = (last / first - 1.0) * 100.0 if first > 0 else 0.0
    color = _POS if change >= 0 else _NEG

    st.markdown(
        f'<span class="px-big">{last:,.2f}</span>&nbsp;'
        f'{_change_chip(change, rng)}',
        unsafe_allow_html=True,
    )

    df = pd.DataFrame({"date": pd.to_datetime(s.index), "price": s.values})
    base = alt.Chart(df).encode(
        x=alt.X("date:T", axis=alt.Axis(
            title=None, grid=False, labelColor="#8a897f",
            domainColor="rgba(242,241,236,0.15)", tickColor="rgba(242,241,236,0.15)",
        )),
    )
    area = base.mark_area(
        line={"color": color, "strokeWidth": 2},
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color=color, offset=0),
                alt.GradientStop(color="#101312", offset=1),
            ],
            x1=1, x2=1, y1=0, y2=1,
        ),
        opacity=0.45,
        interpolate="monotone",
    ).encode(
        y=alt.Y("price:Q", scale=alt.Scale(zero=False), axis=alt.Axis(
            title=None, labelColor="#8a897f",
            gridColor="rgba(242,241,236,0.06)", domainOpacity=0,
        )),
        tooltip=[
            alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("price:Q", title="Price", format=",.2f"),
        ],
    )
    layers = [area]
    lo, hi = float(s.min()), float(s.max())
    pad = (hi - lo) * 0.25 if hi > lo else hi * 0.05
    for level, label, lcolor, dash in (
        (entry, "Buy", _GOLD, [5, 4]),
        (exit_, "Sell", _POS, [2, 3]),
        (stop, "Stop", _NEG, [7, 3]),
    ):
        if level is None or not pd.notna(level) or level <= 0:
            continue
        if not (lo - pad) <= float(level) <= (hi + pad):
            continue  # level far off-screen — don't crush the price scale
        ldf = pd.DataFrame({
            "y": [float(level)],
            "label": [f"{label} {level:,.2f}"],
            "date": [pd.to_datetime(s.index[-1])],
        })
        layers.append(
            alt.Chart(ldf).mark_rule(
                color=lcolor, strokeDash=dash, opacity=0.85, strokeWidth=1.2,
            ).encode(y="y:Q")
        )
        layers.append(
            alt.Chart(ldf).mark_text(
                align="right", baseline="bottom", dx=0, dy=-3,
                color=lcolor, fontSize=10, fontWeight=600,
            ).encode(x="date:T", y="y:Q", text="label:N")
        )
    chart = (
        alt.layer(*layers)
        .properties(height=230, background="transparent")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)


def _render_area_chart(st, series: pd.Series, *, height: int = 240) -> None:
    """Gradient area chart for cumulative series (P&L, equity), coloured
    by the sign of the final value."""
    s2 = series.dropna()
    if s2.empty:
        return
    import altair as alt
    color = _POS if float(s2.iloc[-1]) >= 0 else _NEG
    df = pd.DataFrame({"date": pd.to_datetime(s2.index), "value": s2.values})
    chart = (
        alt.Chart(df)
        .mark_area(
            line={"color": color, "strokeWidth": 2},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color=color, offset=0),
                    alt.GradientStop(color="#101312", offset=1),
                ],
                x1=1, x2=1, y1=0, y2=1,
            ),
            opacity=0.45,
            interpolate="monotone",
        )
        .encode(
            x=alt.X("date:T", axis=alt.Axis(
                title=None, grid=False, labelColor="#8a897f",
            )),
            y=alt.Y("value:Q", axis=alt.Axis(
                title=None, labelColor="#8a897f",
                gridColor="rgba(242,241,236,0.06)", format="~s",
            )),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("value:Q", title="Value", format=",.0f"),
            ],
        )
        .properties(height=height, background="transparent")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)


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
        st.session_state["_target_pattern"] = pattern
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
    from .target_inference import flag_stale_targets
    view = flag_stale_targets(view, history)
    n_stale = int(view["target_stale"].sum())
    n_with_price = int(view["live_price"].notna().sum())
    st.caption(f"Live price available for **{n_with_price} / {len(view)}**.")
    if n_stale:
        st.caption(
            f"⚠️ **{n_stale} buy targets look stale** — price has spent the "
            "last ~6 months more than 50% above the target, so the alert can "
            "never fire and the level likely predates a re-rating. They're "
            "flagged ⏳ in the list; the durable fix is refreshing the "
            "analyst source."
        )
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
    theme_6m_map = (
        dict(zip(heat_for_today["theme"], heat_for_today["median_6m"]))
        if not heat_for_today.empty else {}
    )
    today = (
        compute_daily_signals(
            view, history, volumes,
            news_counts=news, theme_3m=theme_3m_map, top_n=5,
        )
        if buy_zone_tickers else pd.DataFrame()
    )

    # ---- Instrument view (opened by tapping a T212-style list row) ---------
    sel_param = None
    try:
        sel_param = st.query_params.get("sel")
    except Exception:  # noqa: BLE001
        pass
    if sel_param:
        sel_t = str(sel_param).upper()
        sel_rows = view[view["ticker"] == sel_t]
        if not sel_rows.empty:
            st.markdown(
                '<a class="clear-sel" href="?" target="_self">✕ Close instrument view</a>',
                unsafe_allow_html=True,
            )
            sel_fails = gem_gate_failures(sel_rows.iloc[0], theme_6m_map)
            if sel_fails:
                st.caption(f"Not a gem right now: {'; '.join(sel_fails)}")
            else:
                st.caption("✅ Passes every strict gate.")
            _render_watchlist_ticker_card(
                st, sel_rows.iloc[0],
                insider_overlay=insider_overlay,
                catalyst_overlay=catalyst_overlay,
                price_series=history.get(sel_t),
                chart_key="selrow",
            )
            st.divider()

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
            fails = gem_gate_failures(found, theme_6m_map)
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
                price_series=history.get(str(found["ticker"])),
                chart_key="lookup",
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
    try:
        import os as _os

        from .portfolio import load_public_scans
        _tok = ""
        try:
            _tok = str(st.secrets.get("PORTFOLIO_GH_TOKEN", "")).strip()
        except Exception:  # noqa: BLE001
            pass
        _tok = _tok or _os.environ.get("PORTFOLIO_GH_TOKEN", "").strip()
        scans = load_public_scans("cbaduboateng/nicol-calcium-score", token=_tok)
        if scans.empty:
            st.caption(
                "📡 **No scheduled scan has ever reported in.** If this "
                "persists past the next weekday scan (10:45 / 14:30 ET), "
                "the notifier scheduler is broken — silence should mean "
                "'gates working', never 'nobody looked'."
            )
        else:
            last = scans.iloc[-1]
            st.caption(
                f"📡 Last scheduled scan **{last['scanned_at_utc']} UTC** — "
                f"{last['verdict']} "
                f"(curated gems: {last['n_curated_gems']}, explorer: "
                f"{last['n_explorer_gems']})."
            )
    except Exception:  # noqa: BLE001
        pass

    # 🌅 Premarket context (unvalidated by design — annotates, never gates)
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        from pathlib import Path as _P

        from .premarket import PREMARKET_CACHE_PATH
        _pmf = _P(PREMARKET_CACHE_PATH)
        if _pmf.exists():
            pm = _json.loads(_pmf.read_text())
            ts = _dt.strptime(pm["scanned_at_utc"], "%Y-%m-%d %H:%M").replace(
                tzinfo=_tz.utc,
            )
            age_h = (_dt.now(_tz.utc) - ts).total_seconds() / 3600.0
            if age_h < 16 and pm.get("rows"):
                bits = []
                for r in pm["rows"][:6]:
                    badge = "💼" if r.get("is_holding") else (
                        "💎" if r.get("is_gem") else "👀")
                    bits.append(f"{badge}{r['ticker']} {r['gap_pct']:+.1f}%")
                st.caption(
                    f"🌅 Premarket ({pm['scanned_at_utc']} UTC): "
                    + " · ".join(bits)
                    + " — thin prints, context only, never a gate."
                )
    except Exception:  # noqa: BLE001
        pass

    st.caption(
        "A gem passes EVERY strict quality gate (buy zone, own 6m momentum "
        "> 0, hot theme on the 6m median, R:R ≥ 3, not parabolic) AND shows day-scale action "
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
                fails = gem_gate_failures(sig_row.iloc[0], theme_6m_map)
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
                            price_series=history.get(str(gem["ticker"])),
                            chart_key="gem",
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
                    "6m momentum > 0, theme 6m median > 0, R:R ≥ threshold, "
                    "6m < blow-off threshold. Horizons chosen by Signal Lab "
                    "evidence. Composite then ranks the survivors."
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
            f"(BUY ZONE, 6m>0, hot theme 6m, R:R≥{strict_min_rr:.1f}, 6m<{blowoff:.0f}%)."
        )
    if picks.empty:
        st.info("No picks meet the criteria. Loosen the filters or check that prices loaded.")
    else:
        picks = picks.copy()
        if "market_cap_usd" in picks.columns:
            picks["mkt_cap"] = picks["market_cap_usd"].apply(_fmt_cap_short)
        picks["spark"] = picks["ticker"].map(
            lambda t: _sparkline_values(history.get(str(t)))
        )
        # Compact default for phones — fewer columns means no horizontal scroll.
        # Power users can flip the toggle to see every sub-score.
        show_all_picks = st.toggle(
            "🔬 Show all score columns",
            value=False,
            key="picks_show_all_cols",
            help="Reveals the per-layer sub-scores and target prices. Off by default for phone-friendly width.",
        )
        compact_picks_cols = [
            "rank", "ticker", "spark", "name", "status",
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
                "spark": st.column_config.AreaChartColumn(
                    "30d", width="small", help="Last 30 daily closes.",
                ),
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

    # ---- Instrument list (T212-style tappable rows) ------------------------
    cut = cut.copy()
    if "market_cap_usd" in cut.columns:
        cut["mkt_cap"] = cut["market_cap_usd"].apply(_fmt_cap_short)
    cut["spark"] = cut["ticker"].map(
        lambda t: _sparkline_values(history.get(str(t)))
    )

    from .daily_signals import pct_change_over
    max_rows = 40
    shown = cut.head(max_rows)
    row_html: list[str] = ['<div class="ilist">']
    for _, r in shown.iterrows():
        t = str(r.get("ticker") or "")
        day_pct = pct_change_over(history.get(t), 1)
        day_pct = day_pct if pd.notna(day_pct) else None
        row_html.append(_instrument_row_html(r, r.get("spark"), day_pct))
    row_html.append("</div>")
    st.markdown("".join(row_html), unsafe_allow_html=True)
    if len(cut) > max_rows:
        st.caption(
            f"Showing the first {max_rows} of {len(cut)} matches — tighten "
            "the filters above, or open the table view for everything."
        )
    st.caption("Tap a row to open the instrument view at the top of the page.")

    # Full spreadsheet for power users (and the accessibility table view).
    with st.expander("📋 Table view — every column, all rows"):
        cut_display = cut[[c for c in (
            "status", "ticker", "spark", "name", "theme", "mkt_cap",
            "live_price", "target_entry", "target_exit", "stop_price", "tgt_src",
            "gap_to_entry_pct", "reward_risk",
            "pct_1m", "pct_3m", "pct_6m", "pct_12m",
            "description",
        ) if c in cut.columns]].reset_index(drop=True)
        st.dataframe(
            cut_display,
            use_container_width=True,
            hide_index=True,
            key="watchlist_main_table",
            column_config={
            "status": "Status",
            "ticker": "Ticker",
            "name": "Name",
            "theme": "Theme",
            "spark": st.column_config.AreaChartColumn(
                "30d", width="small",
                help="Last 30 daily closes.",
            ),
            "mkt_cap": st.column_config.TextColumn(
                "Mkt cap",
                help="Compact market cap: $50M, $1.2B, '—' for unknown.",
            ),
            "live_price": st.column_config.NumberColumn("Live", format="%.2f"),
            "target_entry": st.column_config.NumberColumn("Buy ≤", format="%.2f"),
            "target_exit": st.column_config.NumberColumn("Sell ≥", format="%.2f"),
            "stop_price": st.column_config.NumberColumn(
                "Stop", format="%.2f",
                help="Suggested stop: 20% below your fill (Exit-Lab verdict: "
                     "tighter stops shook out winners) — the live price "
                     "when in the buy zone, otherwise the entry target. "
                     "Pre-commit it before you buy, and size ~0.6x vs a "
                     "12% stop so per-trade risk stays constant.",
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
            price_series=history.get(sel_ticker),
            chart_key="para",
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
                price_series=history.get(str(row.get("ticker"))),
                chart_key="drill",
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
    price_series: pd.Series | None = None,
    chart_key: str = "card",
) -> None:
    """Compact card for a single watchlist ticker: name, live vs targets,
    a T212-style price chart with the buy/sell/stop levels drawn on it,
    short company description, and any catalyst hook.

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
                f"**Buy ≤** {_fmt(entry)}  ·  **Sell ≥** {_fmt(exit_)}"
                f"  ·  **Stop** {_fmt(stop)}  \n"
                f"3m {_fmt_pct(pct_3m)}  ·  6m {_fmt_pct(pct_6m)}  ·  Status **{status or '—'}**"
            )

        # Price chart with the levels drawn on it (T212 look, but with
        # the buy/sell/stop lines a broker never shows).
        if price_series is not None:
            _render_price_chart(
                st, price_series,
                entry=entry, exit_=exit_, stop=row.get("stop_price"),
                key=f"px_{chart_key}_{ticker}",
            )
        elif live is not None and pd.notna(live):
            st.markdown(f'<span class="px-big">{live:,.2f}</span>', unsafe_allow_html=True)

        if bool(row.get("target_stale")):
            refreshed_txt = ""
            pattern = st.session_state.get("_target_pattern")
            if pattern and price_series is not None:
                from .dynamic_targets import current_dynamic_entry
                ratio = pattern.get("theme_entry_ratios", {}).get(
                    row.get("theme"), pattern.get("entry_ratio"),
                )
                lvl = current_dynamic_entry(price_series, ratio)
                if lvl is not None:
                    refreshed_txt = (
                        f" Under the learned rule (entry ≈ {ratio:.0%} of the "
                        f"52-week low, tracked live) the refreshed level would "
                        f"be **{lvl:,.2f}** — surfaced for context, not yet a "
                        "signal (Entry-mode Lab evidence is promising but "
                        "under-sampled)."
                    )
            st.warning(
                "⏳ **Stale buy target.** Price has spent ~6 months more than "
                "50% above this level — the alert can never fire, and if price "
                "ever fell this far the original thesis likely broke on the "
                "way down. Treat the level as historical until refreshed."
                + refreshed_txt
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

        # ---- Reddit attention (context only, never scored) ------------------
        try:
            from .reddit_overlay import attention_label, load_reddit_overlay
            _ratt = (load_reddit_overlay() or {}).get(ticker.upper())
            _rlabel = attention_label(_ratt)
            if _rlabel != "quiet" and _ratt:
                icon = "🔥" if _rlabel == "viral" else "👁"
                st.caption(
                    f"{icon} **Reddit attention: {_rlabel}** — "
                    f"{_ratt['mentions']} mentions "
                    f"(vs {_ratt['mentions_24h_ago']} yesterday, "
                    f"rank #{_ratt['rank']}). Context only: on this "
                    "universe, peak crowd attention has historically "
                    "coincided with tops, not entries."
                )
        except Exception:  # noqa: BLE001
            pass

        # ---- Short-interest positioning (context only) ----------------------
        try:
            from .positioning import load_positioning, positioning_note
            _pnote = positioning_note(
                load_positioning().get(ticker.upper()))
            if _pnote:
                st.caption(_pnote)
        except Exception:  # noqa: BLE001
            pass

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


def _render_swing_tab(st) -> None:
    """⚡ Swing: short-horizon +5% trades, evidence-gated.

    Live candidates render ONLY for a strategy that beat the control in
    both walk-forward halves with positive net averages. Until one does,
    this tab is a Lab verdict, not a trade list — showing candidates for
    a strategy the evidence says loses money would be malpractice.
    """
    from .swing import (
        DEFAULT_COST_PCT,
        DEFAULT_SWING_VARIANTS,
        SWING_POOLS,
        compare_swing_variants,
        load_swing_universe_cache,
        todays_swing_candidates,
    )
    from .watchlist_alerts import (
        WATCHLIST_PATH,
        fetch_price_history,
        fetch_volume_history,
        load_watchlist,
    )

    st.subheader("⚡ Swing — 5% targets, days not months")
    st.caption(
        "A different game from the watchlist engine: instead of waiting "
        "months for a 2.8× analyst target, a swing trade wants **+5% in "
        "≤10 sessions** and exits fast when wrong (3% stop). At this size "
        "of win, costs decide everything — so each instrument pool is "
        "tested at ITS OWN round-trip cost, target fills are credited at "
        "the limit price (never the gap), and live candidates require "
        "≥ $1M average daily dollar volume. Pool constituent lists are "
        "today's members replayed over history — mild survivorship bias."
    )

    pool_options = {
        "curated": "Curated watchlist (microcaps · 0.5% cost)",
        "largecap": "S&P 100 / Nasdaq-100 large caps (0.15% cost)",
        "etf": "Index & sector ETFs — S&P, Nasdaq, sectors (0.1% cost)",
        "otc": "OTC liquid ADRs — optimistic bound for OTC (1% cost)",
    }
    pool = st.radio(
        "Instrument pool",
        list(pool_options), format_func=pool_options.get,
        horizontal=True, key="swing_pool",
    )

    def _pool_data(which: str) -> tuple[dict, dict, float]:
        if which == "curated":
            watchlist = load_watchlist(WATCHLIST_PATH)
            if watchlist.empty:
                return {}, {}, DEFAULT_COST_PCT
            tickers = sorted(set(watchlist["ticker"].astype(str)))
            hist = fetch_price_history(tickers, period="2y")
            vols = fetch_volume_history(tickers, period="3mo")
            return hist, vols, DEFAULT_COST_PCT
        hist_all, vols_all = load_swing_universe_cache()
        members = set(SWING_POOLS[which]["tickers"])
        return (
            {t: s for t, s in hist_all.items() if t in members},
            {t: s for t, s in vols_all.items() if t in members},
            float(SWING_POOLS[which]["cost_pct"]),
        )

    if st.button("▶ Run the swing-strategy comparison", key="swing_lab_run"):
        with st.spinner("Loading pool history..."):
            history, _, cost = _pool_data(pool)
        if not history:
            st.warning(
                "No 2-year history for this pool yet — the nightly warm-cache "
                "job builds it; retry after the next warm."
            )
        else:
            st.caption(f"Pool loaded: **{len(history)} instruments**, "
                       f"cost haircut **{cost:.2f}%**.")
            with st.spinner("Replaying 7 swing strategies..."):
                st.session_state["swing_lab_result"] = compare_swing_variants(
                    history, cost_pct=cost,
                )
                st.session_state["swing_lab_pool"] = pool

    swing_lab = st.session_state.get("swing_lab_result")
    if swing_lab is None:
        st.info("👆 Run the comparison — it replays seven swing strategies "
                "(dip-buys, oversold RSI, breakouts, a no-strategy control) "
                "over 2 years of the whole watchlist.")
    elif swing_lab.empty:
        st.info("No swing setups fired — not enough history.")
    else:
        sd = swing_lab.copy()
        sd["win_rate"] = sd["win_rate"] * 100.0
        st.dataframe(
            sd, use_container_width=True, hide_index=True,
            column_config={
                "variant": "Strategy",
                "n_signals": st.column_config.NumberColumn("Signals", format="%d"),
                "n_closed": st.column_config.NumberColumn("Closed", format="%d"),
                "win_rate": st.column_config.NumberColumn("Win rate", format="%.0f%%"),
                "avg_return_pct": st.column_config.NumberColumn(
                    "Avg net", format="%+.2f%%",
                    help="Mean net return per closed trade after the 0.5% cost haircut.",
                ),
                "median_return_pct": st.column_config.NumberColumn("Median", format="%+.2f%%"),
                "avg_days_held": st.column_config.NumberColumn("Avg days", format="%.1f"),
                "n_train": st.column_config.NumberColumn("n 1st half", format="%d"),
                "avg_train_pct": st.column_config.NumberColumn("1st half", format="%+.2f%%"),
                "n_test": st.column_config.NumberColumn("n 2nd half", format="%d"),
                "avg_test_pct": st.column_config.NumberColumn("2nd half", format="%+.2f%%"),
            },
        )

        # Evidence gate: positive in both halves AND beats control in both.
        ctrl = swing_lab[swing_lab["variant"].str.startswith("control")]
        c_tr = float(ctrl["avg_train_pct"].iloc[0]) if len(ctrl) else float("nan")
        c_te = float(ctrl["avg_test_pct"].iloc[0]) if len(ctrl) else float("nan")
        passing = swing_lab[
            (~swing_lab["variant"].str.startswith("control"))
            & (swing_lab["avg_train_pct"] > 0)
            & (swing_lab["avg_test_pct"] > 0)
            & (swing_lab["avg_train_pct"] > c_tr)
            & (swing_lab["avg_test_pct"] > c_te)
            & (swing_lab["n_train"] >= 15)
            & (swing_lab["n_test"] >= 15)
        ]
        result_pool = st.session_state.get("swing_lab_pool", "curated")
        if result_pool != pool:
            st.caption(
                f"ℹ️ Table shows the last run "
                f"(**{pool_options.get(result_pool, result_pool)}**) — press "
                "run to test the selected pool."
            )
        if passing.empty:
            if result_pool == "curated":
                st.error(
                    "🧾 **Verdict (2026-08-04 run): no swing strategy earns "
                    "its keep on this universe.** With honest fills and a "
                    "0.5% cost, every strategy — including 'buy any uptrend "
                    "session' — averaged a net LOSS in both halves of the "
                    "last 2 years. Dip-buying was worst; oversold-RSI's "
                    "apparent edge was entirely gap-inflation that a real "
                    "limit order never captures. These thematic small caps "
                    "chop and bleed on a 5–10 session horizon — the money "
                    "here has come from the rare multi-month riders, not "
                    "quick scalps. Try the large-cap or ETF pools above."
                )
            else:
                st.error(
                    "🧾 **Verdict: no strategy cleared the bar on this pool** "
                    "(positive AND above its control in both halves, "
                    "n ≥ 15/half, net of this pool's costs). Live candidates "
                    "stay locked; re-run as history accumulates or after a "
                    "regime change."
                )
        else:
            best_name = passing.sort_values(
                "avg_test_pct", ascending=False,
            ).iloc[0]["variant"]
            best_variant = next(
                v for v in DEFAULT_SWING_VARIANTS if v.name == best_name
            )
            st.success(
                f"✅ **{best_name}** beat the control in both halves net of "
                "costs — live candidates below. Re-verify after any regime "
                "change; this gate re-evaluates on every run."
            )
            with st.spinner("Scanning today's setups (liquidity-gated)..."):
                history, volumes, _ = _pool_data(result_pool)
                cands = todays_swing_candidates(history, volumes, best_variant)
            if cands.empty:
                st.info("No liquid ticker satisfies the setup today.")
            else:
                cd = cands.copy()
                cd["avg_dollar_volume"] = cd["avg_dollar_volume"].map(_fmt_dollar)
                st.dataframe(
                    cd, use_container_width=True, hide_index=True,
                    column_config={
                        "ticker": "Ticker",
                        "live_price": st.column_config.NumberColumn("Last", format="%.2f"),
                        "target_price": st.column_config.NumberColumn("Sell ≥", format="%.2f"),
                        "stop_price": st.column_config.NumberColumn("Stop", format="%.2f"),
                        "target_pct": st.column_config.NumberColumn("Target", format="+%.0f%%"),
                        "stop_pct": st.column_config.NumberColumn("Stop %", format="-%.0f%%"),
                        "timeout_sessions": st.column_config.NumberColumn("Max hold", format="%d sess"),
                        "avg_dollar_volume": "ADV ($)",
                        "est_cost_pct": st.column_config.NumberColumn("Est. cost", format="%.1f%%"),
                    },
                )
        st.caption(
            "Close-only data; stops fill at the (worse) gap close, targets "
            "at the limit price. Same evidence bar as every Lab: positive "
            "AND above the control in both halves, n ≥ 15 per half. Not "
            "financial advice."
        )


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
                "Stop %", 5, 25, 20, step=1,
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

    # Luck detector: is the P&L a process or a couple of moonshots?
    t3 = summary.get("top3_pnl_share_pct")
    if t3 is not None and pd.notna(t3) and summary["closed"] >= 10:
        if t3 > 70:
            st.warning(
                f"🎲 **{t3:.0f}% of all winning P&L came from just 3 trades.** "
                "That's a lottery-ticket profile, not (yet) a repeatable "
                "edge — expect long droughts between the moonshots and size "
                "so the droughts are survivable."
            )
        else:
            st.caption(
                f"🎲 Top-3 winners carry {t3:.0f}% of winning P&L — the "
                "lower this is, the more the returns look like a process "
                "rather than luck."
            )

    # ---- Cumulative P&L chart ---------------------------------------------
    pnl = cumulative_pnl_series(signals, position_size_usd=position_size_usd)
    if not pnl.empty:
        st.markdown("#### Cumulative realised P&L")
        chart_df = pnl.set_index("close_date")["cumulative_usd"]
        _render_area_chart(st, chart_df, height=240)

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
            rb_stop = st.slider("Stop %", 5, 25, 20, step=1, key="runbook_stop")
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
                _render_area_chart(st, equity.set_index("date")["equity"], height=240)

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



def _render_portfolio_tab(st) -> None:
    """💼 Portfolio: log real trades, marked to near-real-time quotes.

    Persistence: GitHub 'portfolio-data' branch via PORTFOLIO_GH_TOKEN
    secret (each trade = a commit; no app redeploys since Streamlit only
    watches the deploy branch). Falls back to session-only storage with
    CSV download/upload when no token is configured."""
    import os

    from .portfolio import (
        empty_trades,
        fetch_live_quotes,
        load_remote_trades,
        new_trade,
        normalise_trades,
        portfolio_totals,
        positions_from_trades,
        save_remote_trades,
    )

    st.subheader("💼 Portfolio")

    repo = "cbaduboateng/nicol-calcium-score"
    token = ""
    try:
        token = str(st.secrets.get("PORTFOLIO_GH_TOKEN", "")).strip()
    except Exception:  # noqa: BLE001
        pass
    token = token or os.environ.get("PORTFOLIO_GH_TOKEN", "").strip()

    remote = bool(token)
    if remote:
        if "portfolio_trades" not in st.session_state:
            try:
                trades, sha = load_remote_trades(token, repo)
                st.session_state["portfolio_trades"] = trades
                st.session_state["portfolio_sha"] = sha
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not load the portfolio branch: {exc}")
                remote = False
    if "portfolio_trades" not in st.session_state:
        st.session_state["portfolio_trades"] = empty_trades()

    trades = st.session_state["portfolio_trades"]

    if not remote:
        st.warning(
            "**Session-only storage** — trades vanish when this session ends. "
            "For permanent storage: GitHub → Settings → Developer settings → "
            "Fine-grained tokens → new token with **Contents: read & write** "
            "on this repo only → add it to Streamlit Secrets as "
            "`PORTFOLIO_GH_TOKEN`. Each trade then becomes a commit on a "
            "`portfolio-data` branch: versioned, auditable, deploy-proof."
        )

    # ---- Positions + quotes ------------------------------------------------
    positions, realised = positions_from_trades(trades)
    held = sorted(positions["ticker"].tolist())
    quotes: dict = {}
    if held:
        # 60s session cache: widget interactions rerun the whole script,
        # and refetching quotes on every click made the tab feel like it
        # was reloading. Fresh enough for a personal portfolio.
        import time as _time
        cached = st.session_state.get("portfolio_quotes_cache")
        if cached and cached[0] == held and _time.time() - cached[1] < 60:
            quotes = cached[2]
        else:
            with st.spinner("Fetching live quotes..."):
                try:
                    quotes = fetch_live_quotes(held)
                except Exception:  # noqa: BLE001
                    quotes = {}
            if quotes:
                st.session_state["portfolio_quotes_cache"] = (
                    held, _time.time(), quotes,
                )
    _gbpusd_now = None
    try:
        from .portfolio import fetch_gbpusd as _fgx
        import time as _t0
        _fxc = st.session_state.get("gbpusd_cache")
        if _fxc and _t0.time() - _fxc[0] < 900:
            _gbpusd_now = _fxc[1]
        else:
            _gbpusd_now = _fgx()
            if _gbpusd_now:
                st.session_state["gbpusd_cache"] = (_t0.time(), _gbpusd_now)
    except Exception:  # noqa: BLE001
        pass
    totals = portfolio_totals(positions, quotes, gbpusd=_gbpusd_now)
    realised_total = float(realised["realised_pnl"].sum()) if not realised.empty else 0.0

    # ---- Hero --------------------------------------------------------------
    if totals["n_positions"]:
        st.markdown(
            f'<span class="px-big">${totals["value"]:,.2f}</span>&nbsp;'
            f'{_change_chip(totals["day_pct"], "today")}&nbsp;'
            f'{_change_chip(totals["unrealised_pct"], "all")}',
            unsafe_allow_html=True,
        )
        # ---- £ equivalents (display only; book currency stays USD) --------
        rate = None
        try:
            import time as _t

            from .portfolio import fetch_gbpusd
            fx = st.session_state.get("gbpusd_cache")
            if fx and _t.time() - fx[0] < 900:
                rate = fx[1]
            else:
                rate = fetch_gbpusd()
                if rate:
                    st.session_state["gbpusd_cache"] = (_t.time(), rate)
        except Exception:  # noqa: BLE001
            rate = None
        if rate:
            def _gbp(v: float) -> str:
                sign = "-" if v < 0 else ""
                return f"{sign}£{abs(v) / rate:,.2f}"
            st.caption(
                f"💷 ≈ **{_gbp(totals['value'])}** · unrealised "
                f"{_gbp(totals['unrealised'])} · day {_gbp(totals['day_pnl'])} · "
                f"realised {_gbp(realised_total)} — at GBP/USD {rate:.4f}, "
                "display only (the book stays in USD)."
            )
            # FX-aware split: stocks vs currency, booked at trade-date rates
            try:
                from pathlib import Path as _P

                from .portfolio import fx_pnl_breakdown
                _fxf = _P("data/cache/gbpusd_v1_10y.parquet")
                if _fxf.exists():
                    fx_series = pd.read_parquet(_fxf)["GBPUSD"]
                    fxb = fx_pnl_breakdown(trades, positions, quotes, fx_series)
                    if fxb:
                        st.caption(
                            f"💱 In pounds you're {fxb['total_gbp_return_pct']:+.1f}% "
                            f"overall: stocks {fxb['stock_return_pct']:+.1f}% "
                            f"{'+' if fxb['fx_contribution_pts'] >= 0 else '−'} "
                            f"currency {abs(fxb['fx_contribution_pts']):.1f}pts "
                            "(each buy booked at its trade-date rate)."
                        )
            except Exception:  # noqa: BLE001
                pass
        h = st.columns(3)
        h[0].metric("Unrealised", _fmt_dollar(totals["unrealised"]))
        h[1].metric("Day P&L", _fmt_dollar(totals["day_pnl"]))
        h[2].metric("Realised", _fmt_dollar(realised_total))
        if totals["n_priced"] < totals["n_positions"]:
            st.caption(
                f"Live quotes for {totals['n_priced']}/{totals['n_positions']} "
                "holdings — the rest are valued at cost until quotes return."
            )
    else:
        st.info("No open positions yet — log your first trade below.")

    # ---- Risk view ---------------------------------------------------------
    if totals["n_positions"]:
        try:
            from .portfolio import portfolio_risk, theme_concentration
            from .ticker_facts import lookup as _facts
            from .watchlist_alerts import load_watchlist as _lw, map_theme as _mt

            wl_desc = {}
            try:
                _wl = _lw()
                wl_desc = dict(zip(_wl["ticker"], _wl["description"]))
            except Exception:  # noqa: BLE001
                pass
            themes = {}
            for t in positions["ticker"]:
                fact = _facts(t, cache_only=True)
                themes[t] = _mt(wl_desc.get(t, ""), sector=(fact.sector if fact else None))

            from .portfolio import load_stop_overrides
            _ovr = load_stop_overrides(repo, token=token)
            risk = portfolio_risk(positions, quotes, overrides=_ovr)
            conc = theme_concentration(positions, quotes, themes)
            r = st.columns(2)
            r[0].metric(
                "Risk at stops",
                f"{_fmt_dollar(risk['risk_at_stops'])} · {risk['risk_pct_of_value']:.1f}%",
                help="Total loss if EVERY holding fell to its stop (avg cost −20%) "
                     "tomorrow. The number that prevents ruin — keep it a size "
                     "you can shrug off.",
            )
            if conc["top_theme"]:
                r[1].metric(
                    "Top theme", f"{conc['top_theme']} · {conc['top_share_pct']:.0f}%",
                    help="Share of portfolio value in the largest theme.",
                )
            if conc["top_share_pct"] > 50:
                st.warning(
                    f"⚠️ **{conc['top_share_pct']:.0f}% of the portfolio is one "
                    f"theme ({conc['top_theme']})** — several tickers, one bet. "
                    "Fine if intentional; dangerous if accidental."
                )
            if risk["n_below_stop"]:
                st.error(
                    f"🛑 {risk['n_below_stop']} holding(s) already below their "
                    "stop — the rule says these should have been sold. See the "
                    "push alerts."
                )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Risk view unavailable this refresh ({exc})")

    # ---- Holdings as T212-style rows --------------------------------------
    if totals["n_positions"]:
        rows_html = ['<div class="ilist">']
        for _, p in positions.iterrows():
            q = quotes.get(p["ticker"]) or {}
            px = q.get("price")
            prev = q.get("prev_close")
            day_pct = (
                (px / prev - 1.0) * 100.0
                if px and prev and pd.notna(px) and pd.notna(prev) and prev > 0
                else None
            )
            from .portfolio import native_to_usd as _n2u
            value = _n2u(str(p["ticker"]),
                         float(p["qty"]) * float(px)
                         if px and pd.notna(px) else float(p["invested"]))
            unreal_pct = (
                (value / float(p["invested"]) - 1.0) * 100.0
                if float(p["invested"]) > 0 else 0.0
            )
            px_s = f"{px:,.2f}" if px and pd.notna(px) else "—"
            chip = _change_chip(day_pct) if day_pct is not None else ""
            unreal_chip = _change_chip(unreal_pct)
            rows_html.append(
                f'<a class="irow" href="?sel={p["ticker"]}" target="_self">'
                f'<div class="irow-l">'
                f'<div class="irow-name">{p["ticker"]}</div>'
                f'<div class="irow-sub">{p["qty"]:g} @ {p["avg_cost"]:,.2f} · '
                f'now {px_s}</div></div>'
                f'<div class="irow-r"><div class="irow-px">${value:,.2f}</div>'
                f"{unreal_chip}{chip}</div></a>"
            )
        rows_html.append("</div>")
        st.markdown("".join(rows_html), unsafe_allow_html=True)
        st.caption(
            "Value on the right; chips = all-time and today. Tap a holding "
            "to open its chart on the Watchlist tab."
        )

        # ---- 🩺 Holdings health (informs, never exits) -------------------------
    if totals["n_positions"]:
        with st.expander("🩺 Holdings health — dynamic assessment (never an exit signal)"):
            st.caption(
                "Live context per position: P&L, stop distance, momentum and "
                "🚨 falsifier headlines (dilution / going-concern / delisting "
                "language). **By charter this card cannot sell** — the "
                "thesis-exit experiment (ledger #25) proved momentum wobble "
                "exits gut returns; exits remain stop · target · timeout · "
                "written falsifiers only."
            )
            try:
                from .holding_health import assess_holding
                from .portfolio import load_stop_overrides as _lso
                from .watchlist_alerts import fetch_price_history as _fph
                _hovr = _lso(repo, token=token)
                _htick = sorted(set(positions["ticker"].astype(str)))
                _hhist = _fph(_htick, period="1y")
                for _, hp in positions.iterrows():
                    hk = (str(hp["ticker"]).upper(),
                          str(hp.get("account", "") or "").upper())
                    stopv = _hovr.get(hk, float(hp["avg_cost"]) * 0.8)
                    card = assess_holding(
                        hp["ticker"], hp.to_dict(),
                        _hhist.get(hp["ticker"]), stop_price=stopv,
                    )
                    acct = str(hp.get("account", "") or "")
                    flag = " 🚨" if card["falsifier_tags"] else ""
                    st.markdown(
                        f"**{card['ticker']}**"
                        + (f" `{acct}`" if acct else "")
                        + f"{flag} — {card['line']}"
                    )
                    if card["falsifier_sample"]:
                        st.caption(f"  ↳ “{card['falsifier_sample']}” — read "
                                   "it; a fact falsifier means exit next "
                                   "session, any price.")
            except Exception as exc:  # noqa: BLE001
                st.caption(f"Health cards unavailable this refresh ({exc})")

    # ---- 🥧 Allocation donuts ------------------------------------------
        try:
            import altair as alt

            from .swing import SWING_POOLS as _sp
            from .ticker_facts import lookup as _pf
            from .watchlist_alerts import load_watchlist as _plw, map_theme as _pmt

            _wl_desc = {}
            try:
                _pwl = _plw()
                _wl_desc = dict(zip(_pwl["ticker"], _pwl["description"]))
            except Exception:  # noqa: BLE001
                pass
            _etfset = set(_sp["etf"]["tickers"]) | {"INRG.L"}
            rows_alloc = []
            for _, p in positions.iterrows():
                q = quotes.get(p["ticker"]) or {}
                px = q.get("price")
                from .portfolio import native_to_usd as _n2u
                v = _n2u(str(p["ticker"]),
                         float(p["qty"]) * float(px)
                         if px and pd.notna(px) else float(p["invested"]))
                acct = str(p.get("account", "") or "?")
                fact = _pf(p["ticker"], cache_only=True)
                theme = _pmt(_wl_desc.get(p["ticker"], ""),
                             sector=(fact.sector if fact else None))
                is_core = p["ticker"] in _etfset
                rows_alloc.append({
                    "label": f"{p['ticker']} ({acct})",
                    "value": v,
                    "theme": "ETF core" if is_core else theme,
                    "kind": "Core (ETFs)" if is_core else "Satellite (stocks)",
                })
            adf = pd.DataFrame(rows_alloc)
            if not adf.empty:
                st.markdown("#### 🥧 Allocation")
                c1, c2 = st.columns(2)
                base = dict(innerRadius=48, outerRadius=95)
                with c1:
                    top = adf.nlargest(9, "value")
                    rest = adf[~adf.index.isin(top.index)]["value"].sum()
                    pie1 = pd.concat([top, pd.DataFrame(
                        [{"label": "Other", "value": rest, "theme": "",
                          "kind": ""}])]) if rest > 0 else top
                    st.altair_chart(
                        alt.Chart(pie1).mark_arc(**base).encode(
                            theta=alt.Theta("value:Q"),
                            color=alt.Color("label:N", legend=alt.Legend(
                                title=None, labelLimit=140)),
                            tooltip=["label:N",
                                     alt.Tooltip("value:Q", format=",.0f")],
                        ).properties(height=260, title="By holding"),
                        use_container_width=True,
                    )
                with c2:
                    tdf = adf.groupby("theme", as_index=False)["value"].sum()
                    st.altair_chart(
                        alt.Chart(tdf).mark_arc(**base).encode(
                            theta=alt.Theta("value:Q"),
                            color=alt.Color("theme:N", legend=alt.Legend(
                                title=None, labelLimit=140)),
                            tooltip=["theme:N",
                                     alt.Tooltip("value:Q", format=",.0f")],
                        ).properties(height=260, title="By theme"),
                        use_container_width=True,
                    )
                core_v = adf[adf["kind"] == "Core (ETFs)"]["value"].sum()
                st.caption(
                    f"Core (ETFs) {core_v / adf['value'].sum() * 100.0:.0f}% "
                    f"vs the Blueprint's 80% target — the rotation gap, "
                    "drawn to scale."
                )
        except Exception:  # noqa: BLE001
            pass

    # ---- Log a trade -------------------------------------------------------
    st.markdown("### ➕ Log a trade")
    with st.form("log_trade", clear_on_submit=True):
        f = st.columns([2, 1, 1, 1, 1])
        with f[0]:
            t_ticker = st.text_input("Ticker", placeholder="HIVE")
        with f[1]:
            t_account = st.selectbox("Account", ["ISA", "SIPP", ""])
        with f[4]:
            t_side = st.selectbox("Side", ["buy", "sell"])
        with f[2]:
            t_qty = st.number_input("Quantity", min_value=0.0, step=1.0, format="%g")
        with f[3]:
            t_price = st.number_input("Price", min_value=0.0, step=0.01, format="%.4f")
        f2 = st.columns([1, 3])
        with f2[0]:
            t_date = st.date_input("Date", value=None, format="YYYY-MM-DD")
        with f2[1]:
            t_note = st.text_input("Note (optional)", placeholder="gem pick · stop 2.49")
        submitted = st.form_submit_button("Log trade")
    if submitted:
        if not t_ticker.strip() or t_qty <= 0 or t_price <= 0:
            st.error("Ticker, a positive quantity and a positive price are required.")
        else:
            trade = new_trade(
                t_ticker, t_side, t_qty, t_price,
                trade_date=t_date, note=t_note, account=t_account,
            )
            updated = normalise_trades(pd.concat(
                [trades, pd.DataFrame([trade])], ignore_index=True,
            ))
            if remote:
                try:
                    sha = save_remote_trades(
                        token, repo, updated, st.session_state.get("portfolio_sha"),
                        message=f"Log {t_side} {t_qty:g} {trade['ticker']} @ {t_price}",
                    )
                    st.session_state["portfolio_sha"] = sha
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Saving to GitHub failed: {exc}")
            st.session_state["portfolio_trades"] = updated
            st.rerun()

    # ---- History + realised + backup --------------------------------------
    if not realised.empty:
        with st.expander(f"Realised P&L ({len(realised)} closes)"):
            r = realised.copy()
            r["realised_pnl"] = r["realised_pnl"].apply(_fmt_dollar)
            st.dataframe(
                r, use_container_width=True, hide_index=True,
                column_config={
                    "date": "Date", "ticker": "Ticker",
                    "qty": st.column_config.NumberColumn("Qty", format="%g"),
                    "sell_price": st.column_config.NumberColumn("Sold @", format="%.2f"),
                    "avg_cost": st.column_config.NumberColumn("Avg cost", format="%.2f"),
                    "realised_pnl": st.column_config.TextColumn("P&L"),
                    "oversold": st.column_config.CheckboxColumn(
                        "Clamped", help="Sell exceeded held quantity and was clamped.",
                    ),
                },
            )
    # ---- 📜 The Plan: adopted targets vs reality ---------------------------
    with st.expander("📜 The Plan — adopted 11 Aug 2026 (SIPP ≤10% stocks · ISA ≤20%)"):
        from .blueprint import ADOPTED_PLAN, plan_progress
        prog = plan_progress(positions, quotes)
        for wrapper, w in prog.items():
            st.markdown(f"**{wrapper}** — stocks {w['stock_pct']:.0f}% "
                        f"(cap {w['cap_pct']:.0f}%"
                        + (" · ⏳ converging via contributions/exits, no new "
                           "spec buys meanwhile" if w['over_cap'] else " · ✅ within cap")
                        + ")")
            if w["sell_pending"]:
                st.caption("Rotation pending: " + " · ".join(w["sell_pending"]))
            if w["sell_done"]:
                st.caption("✅ Rotated: " + " · ".join(w["sell_done"]))
        st.caption(
            "Core builds: SIPP → VWRP £20–22k · EQQQ £5k · SGLN £3.5k "
            "(INRG stays £3.9k, capped). ISA Pie → VWRP £14k · SGLN £3.5k, "
            "auto-invest. Contracts: AQB & DDD to their written exits. "
            "Calendar: SLNH earnings 13 Aug · AQB timeout 10 Feb 2027. "
            "Full terms in the hypothesis ledger (allocation-constitution)."
        )

    # ---- 🎯 Blueprint: 80/20 core-satellite planner -----------------------
    with st.expander("🎯 Blueprint — ETF core + stock satellite"):
        from pathlib import Path as _P

        from .blueprint import (
            PRESET_CORES,
            classify_holdings,
            core_history_stats,
            rebalance_hint,
            required_satellite_cagr,
        )
        st.caption(
            "Plan the 80% ETF core / 20% stock satellite split. Core stats "
            "are the LAST DECADE's history (monthly rebalanced) — a decade "
            "that was unusually kind to US tech — **not a forecast**. The "
            "blend maths below shows what your target demands of the "
            "satellite; if that number looks heroic, the target is."
        )
        bp_cols = st.columns([2, 1, 1])
        with bp_cols[0]:
            preset_name = st.selectbox(
                "Core preset", list(PRESET_CORES), index=1, key="bp_preset",
            )
        with bp_cols[1]:
            bp_target = st.number_input(
                "Blend target %/yr", min_value=5.0, max_value=40.0,
                value=20.0, step=1.0, format="%g", key="bp_target",
            )
        with bp_cols[2]:
            bp_core_w = st.number_input(
                "Core weight %", min_value=50.0, max_value=95.0,
                value=80.0, step=5.0, format="%g", key="bp_core_w",
            )
        weights = PRESET_CORES[preset_name]
        st.caption("Core mix: " + " · ".join(
            f"{t} {w * 100:.0f}%" for t, w in weights.items()))

        _etf10p = _P("data/cache/etf_prices_v1_10y.parquet")
        stats = None
        if _etf10p.exists():
            stats = core_history_stats(pd.read_parquet(_etf10p), weights)
        if stats:
            req = required_satellite_cagr(
                bp_target, stats["cagr_pct"], core_weight=bp_core_w / 100.0,
            )
            bcols = st.columns(3)
            bcols[0].metric(
                "Core CAGR (last decade)", f"{stats['cagr_pct']:+.1f}%",
                help="History, not a forecast. Monthly rebalanced.",
            )
            bcols[1].metric("Core max drawdown", f"{stats['max_drawdown_pct']:.1f}%")
            bcols[2].metric(
                f"Satellite must do ({100 - bp_core_w:.0f}%)",
                f"{req:+.0f}%/yr",
                help="What the stock sleeve must compound at, EVERY year, "
                     "for the blend to hit your target — assuming the core "
                     "repeats its decade, which it may not.",
            )
            if req > 35:
                st.warning(
                    f"⚠️ A {bp_target:.0f}% blend on this core needs the "
                    f"satellite to compound at **{req:+.0f}%/yr** — beyond "
                    "world-class. Either the target, the core choice, or "
                    "the split has to give. The honest levers: a growthier "
                    "core (more risk), a bigger satellite (more risk), or "
                    "a target the maths can reach."
                )
        else:
            st.info("Core stats need the 10-year ETF cache — available "
                    "after the next nightly warm.")

        # Actual vs blueprint, from real holdings
        from .swing import SWING_POOLS
        etf_syms = set(SWING_POOLS["etf"]["tickers"])
        split = classify_holdings(positions, quotes, etf_syms)
        if split["total_value"] > 0:
            st.markdown(
                f"**Your current split:** core {split['core_pct']:.0f}% "
                f"({', '.join(split['core_names']) or 'none'}) · satellite "
                f"{split['satellite_pct']:.0f}% "
                f"({', '.join(split['satellite_names']) or 'none'})"
            )
            hint = rebalance_hint(split, core_weight=bp_core_w / 100.0)
            if hint:
                st.info("⚖️ " + hint + " (5-point drift band — a convention, "
                        "not Lab-validated.)")
        else:
            st.caption("Log trades and the actual core/satellite split "
                       "appears here against the blueprint.")

    # ---- Position sizer (the '2% rule': size follows from the stop) -------
    with st.expander("📐 Position sizer — risk first, size second"):
        st.caption(
            "Pick how much of the account one losing trade may cost (the "
            "classic answer is 2%); the stop distance then dictates the "
            "size. With the house 20% stop, 2% risk ≈ 10% of the account "
            "per position — the Exit-Lab's 'size smaller at wider stops' "
            "rule made concrete."
        )
        pcols = st.columns(4)
        with pcols[0]:
            ps_account = st.number_input(
                "Account value", min_value=0.0, value=5000.0, step=500.0,
                format="%g", key="ps_account",
            )
        with pcols[1]:
            ps_risk = st.number_input(
                "Risk per trade %", min_value=0.1, max_value=10.0,
                value=2.0, step=0.5, format="%g", key="ps_risk",
            )
        with pcols[2]:
            ps_entry = st.number_input(
                "Entry price", min_value=0.0, value=0.0, step=0.01,
                format="%.4f", key="ps_entry",
            )
        with pcols[3]:
            ps_stop = st.number_input(
                "Stop price (0 = entry −20%)", min_value=0.0, value=0.0,
                step=0.01, format="%.4f", key="ps_stop",
            )
        if ps_entry > 0:
            from .portfolio import position_size
            stop_eff = ps_stop if ps_stop > 0 else ps_entry * 0.80
            sz = position_size(ps_account, ps_risk, ps_entry, stop_eff)
            if sz["qty"] > 0:
                st.markdown(
                    f"**{sz['qty']:,.0f} shares** ≈ "
                    f"{_fmt_dollar(sz['position_value'])} "
                    f"({sz['pct_of_account']:.1f}% of the account) — "
                    f"if the stop at {stop_eff:,.2f} fires you lose "
                    f"{_fmt_dollar(sz['risk_amount'])}."
                )
            else:
                st.warning("Stop must be below entry.")

    # ---- Delete trades (own section — NOT hidden in an expander) ----------
    if not trades.empty:
        st.markdown("### 🗑 Delete trades")
        st.caption(
            "Fix typos or remove test entries. Every change is a commit on "
            "the data branch, so nothing is ever truly lost."
        )

        def _label(row: pd.Series) -> str:
            note = f" · {row['note']}" if str(row.get("note") or "").strip() else ""
            # Short id suffix keeps labels unique even for identical
            # duplicate trades (the realistic delete target).
            acct = str(row.get("account", "") or "")
            acct_tag = f" [{acct}]" if acct else ""
            return (f"{row['date']}  {row['side']} {float(row['qty']):g} "
                    f"{row['ticker']}{acct_tag} @ {float(row['price']):g}{note} "
                    f"· #{str(row['id'])[:6]}")

        options = {
            _label(row): str(row["id"])
            for _, row in trades.iterrows()
        }
        # Inside a form, picking entries does NOT rerun the page — only
        # the submit button does. Without this every selection triggered
        # a full rerun + quote refetch, which read as a broken reload.
        with st.form("delete_trades_form"):
            chosen = st.multiselect("Trades to delete", list(options))
            delete_submitted = st.form_submit_button("🗑 Delete selected")
        if delete_submitted and not chosen:
            st.warning("Pick at least one trade first.")
        elif delete_submitted:
            doomed_ids = {options[c] for c in chosen}
            updated = trades[~trades["id"].astype(str).isin(doomed_ids)]
            updated = updated.reset_index(drop=True)
            if remote:
                try:
                    sha = save_remote_trades(
                        token, repo, updated,
                        st.session_state.get("portfolio_sha"),
                        message=f"Delete {len(doomed_ids)} trade(s)",
                    )
                    st.session_state["portfolio_sha"] = sha
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Saving to GitHub failed: {exc}")
                    st.stop()
            st.session_state["portfolio_trades"] = updated
            st.rerun()

    if not trades.empty:
        with st.expander(f"📜 Trade history ({len(trades)})"):
            st.dataframe(trades, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download trades.csv",
                trades.to_csv(index=False).encode(),
                file_name="trades.csv", mime="text/csv",
            )
    up = st.file_uploader(
        "Restore / import trades.csv", type=["csv"], key="portfolio_upload",
        help="Replaces the current trade log with the uploaded file.",
    )
    if up is not None and st.button("Import uploaded trades", key="portfolio_import"):
        try:
            imported = normalise_trades(pd.read_csv(up, dtype=str))
            if remote:
                sha = save_remote_trades(
                    token, repo, imported, st.session_state.get("portfolio_sha"),
                    message="Import trades.csv",
                )
                st.session_state["portfolio_sha"] = sha
            st.session_state["portfolio_trades"] = imported
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Import failed: {exc}")

    # ---- Pick adherence (the behavioural mirror) ---------------------------
    from .portfolio import adherence, load_public_picks
    picks_log = load_public_picks(repo, token=token)
    if not picks_log.empty:
        st.markdown("### 🎯 Pick adherence")
        adh = adherence(picks_log, trades)
        acted_pct = float(adh["acted"].mean() * 100.0) if len(adh) else 0.0
        st.caption(
            f"**{len(adh)} picks logged** · you acted on "
            f"**{acted_pct:.0f}%** (a buy within 3 days of the pick). Over "
            "time this answers the question most traders never get to ask: "
            "do your overrides beat the system, or does the system beat you?"
        )
        st.dataframe(
            adh.head(15).assign(
                followed=adh.head(15)["acted"].map({True: "✅", False: "—"}),
            )[["date", "ticker", "adjusted_score", "pool", "followed"]],
            use_container_width=True, hide_index=True,
            column_config={
                "date": "Date", "ticker": "Pick",
                "adjusted_score": "Adj score", "pool": "Pool",
                "followed": "Acted",
            },
        )
    else:
        st.caption(
            "🎯 Pick adherence: the notifier now logs every 👑 Pick of the Day "
            "to your portfolio branch — the adherence mirror appears here "
            "once the first picks accumulate."
        )

    st.caption(
        "Average-cost accounting, like your broker shows. Research tool — "
        "reconcile against your broker statements; not financial advice."
    )


def _render_lab_tab(st) -> None:
    """🧪 Signal Lab in its own tab — self-contained data load with an
    explicit message at every guard, so it can never silently vanish
    behind another tab's early returns again."""
    from .signal_lab import compare_variants
    from .watchlist_alerts import (
        WATCHLIST_PATH,
        fetch_price_history,
        load_watchlist,
    )

    # ---- 🧬 Hypothesis ledger: the memory of everything ever tested -------
    from .hypotheses import ledger_summary, load_hypotheses
    ledger = load_hypotheses()
    if not ledger.empty:
        counts = ledger_summary(ledger)
        headline = " · ".join(
            f"{counts.get(s, 0)} {s}" for s in
            ("adopted", "rejected", "monitoring", "untestable", "proposed")
            if counts.get(s, 0)
        )
        with st.expander(f"🧬 Hypothesis ledger — {headline}"):
            st.caption(
                "Every idea this project has tested, and how it died. The "
                "rejections are the most valuable rows — each one is a "
                "strategy that LOOKED good and would have cost real money. "
                "Nothing is ever deleted; new tests only append."
            )
            _status_icon = {"adopted": "✅", "rejected": "🪦",
                            "monitoring": "🔬", "untestable": "🚫",
                            "proposed": "📋"}
            led = ledger.copy()
            led["status"] = led["status"].map(
                lambda s: f"{_status_icon.get(s, '')} {s}")
            st.dataframe(
                led[["date", "hypothesis", "verdict", "status"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "date": "Date", "hypothesis": "Hypothesis",
                    "verdict": "What the data said", "status": "Status",
                },
            )

    st.subheader("🧪 Signal Lab — which signal definition actually works?")
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

    watchlist = load_watchlist(WATCHLIST_PATH)
    if watchlist.empty:
        st.warning(f"No watchlist file at `{WATCHLIST_PATH}` — nothing to test.")
        return
    tradable = watchlist[
        watchlist["target_entry"].notna() & (watchlist["target_entry"] > 0)
    ]
    if tradable.empty:
        st.warning("No watchlist tickers have a buy target — nothing to test.")
        return

    # Expand the testable universe: fill missing EXIT targets as
    # analyst_entry × the analyst's own exit multiple. Price-free, so
    # unlike price-anchored entry derivation this does NOT contaminate
    # the backtest — the R:R gate just stops strangling the sample.
    from .target_inference import derive_exits_from_entries
    expanded, exit_mult = derive_exits_from_entries(tradable)
    n_analyst_x = int((expanded["exit_source"] == "analyst").sum())
    n_derived_x = int((expanded["exit_source"] == "derived").sum())
    st.caption(
        f"Universe: **{len(expanded)} curated tickers** with buy targets — "
        f"exits: {n_analyst_x} analyst-set + {n_derived_x} derived as "
        f"entry × {exit_mult:.1f} (the analyst's own median multiple; "
        "price-free, so non-circular). Replayed over up to 2 years."
    )

    if st.button("▶ Run the signal comparison", key="signal_lab_run"):
        tickers = sorted(set(expanded["ticker"].tolist()))
        with st.spinner(f"Loading 2y history for {len(tickers)} tickers..."):
            try:
                history = fetch_price_history(tickers, period="2y")
            except Exception as exc:
                st.error(f"Price fetch failed: {exc}")
                return
        if not history:
            st.warning(
                "No 2-year price history available yet — run the warm-cache "
                "workflow or retry after the next scheduled warm."
            )
            return
        st.caption(f"History loaded for **{len(history)} / {len(tickers)}** tickers.")
        with st.spinner("Replaying 8 signal variants..."):
            st.session_state["signal_lab_result"] = compare_variants(
                expanded, history,
            )

    lab = st.session_state.get("signal_lab_result")
    if lab is None:
        st.info("👆 Press the button — the comparison takes a minute or two.")
    elif lab.empty:
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
            "How to read it: a variant earns trust only if its average return "
            "beats the control in BOTH halves with a reasonable sample "
            "(n ≥ 15 per half). Win rate alone misleads — a 60% win rate on "
            "2:1 payoffs beats 80% on 0.5:1. If a variant wins decisively "
            "here, tell Claude to make it the default gate set. Not financial "
            "advice."
        )

    # ---- Exit-policy panel -------------------------------------------------
    st.divider()
    st.markdown("### 🚪 Exit policies — same entries, different exits")
    st.caption(
        "The track record's 1% hit rate exposed that analyst 2.5× targets "
        "are almost never reached in 6 months — today's profits come from "
        "*accidental* timeouts. This panel fixes the entries to the "
        "validated 6m gate set and varies ONLY the exit: longer holds, "
        "wider stops (microcaps gap through 10% routinely), a 20-day-low "
        "trailing exit, taking half at +30%, and pure trend-following with "
        "no target. Same walk-forward honesty rules."
    )
    if st.button("▶ Run the exit comparison", key="exit_lab_run"):
        from .signal_lab import compare_exit_variants
        exit_tickers = sorted(set(expanded["ticker"].tolist()))
        with st.spinner(f"Loading 2y history for {len(exit_tickers)} tickers..."):
            try:
                exit_history = fetch_price_history(exit_tickers, period="2y")
            except Exception as exc:
                st.error(f"Price fetch failed: {exc}")
                exit_history = {}
        if not exit_history:
            st.warning(
                "No 2-year price history available yet — run the warm-cache "
                "workflow or retry after the next scheduled warm."
            )
        else:
            with st.spinner("Replaying 7 exit policies over the same entries..."):
                st.session_state["exit_lab_result"] = compare_exit_variants(
                    expanded, exit_history,
                )
    exit_lab = st.session_state.get("exit_lab_result")
    if exit_lab is not None:
        if exit_lab.empty:
            st.info("No entries fired — run after the caches warm.")
        else:
            xd = exit_lab.copy()
            xd["win_rate"] = xd["win_rate"] * 100.0
            st.dataframe(
                xd, use_container_width=True, hide_index=True,
                column_config={
                    "variant": "Exit policy",
                    "n_signals": st.column_config.NumberColumn("Signals", format="%d"),
                    "n_closed": st.column_config.NumberColumn("Closed", format="%d"),
                    "win_rate": st.column_config.NumberColumn("Win rate", format="%.0f%%"),
                    "avg_return_pct": st.column_config.NumberColumn("Avg ret", format="%+.1f%%"),
                    "median_return_pct": st.column_config.NumberColumn("Median", format="%+.1f%%"),
                    "avg_days_held": st.column_config.NumberColumn("Avg days", format="%.0f"),
                    "n_train": st.column_config.NumberColumn("n 1st half", format="%d"),
                    "avg_train_pct": st.column_config.NumberColumn("1st half", format="%+.1f%%"),
                    "n_test": st.column_config.NumberColumn("n 2nd half", format="%d"),
                    "avg_test_pct": st.column_config.NumberColumn("2nd half", format="%+.1f%%"),
                },
            )
            st.caption(
                "Same evidence bar as above: beat the baseline in BOTH "
                "halves at n ≥ 15 per half before believing it. Caveat: "
                "close-only data — trailing exits and wide stops behave "
                "worse intraday than daily closes suggest. **Adopted "
                "2026-08-03: the 20% stop won in both halves and is now "
                "the track-record default.**"
            )

    # ---- Entry-mode panel --------------------------------------------------
    st.divider()
    st.markdown("### 🎯 Entry modes — static analyst levels vs the learned rule, live")
    st.caption(
        "The analyst sets a buy target once and never updates it "
        "(reverse-engineered rule: entry ≈ 90% of the 52-week low, sell "
        "≈ 2.8× entry). This panel replays that SAME rule point-in-time — "
        "each session's level is the ratio × the trailing 52-week low as "
        "of the prior close, so the level tracks the market instead of "
        "fossilising. Three arms: static analyst entries (control), the "
        "dynamic rule on the same tickers, and the dynamic rule on the "
        "full watchlist (no analyst needed). Same gates, same walk-forward "
        "honesty rules. The R:R gate is omitted on dynamic arms — with "
        "exit = entry × multiple it's a constant, not a filter."
    )
    if st.button("▶ Run the entry-mode comparison", key="entry_mode_run"):
        from .dynamic_targets import compare_entry_modes
        from .target_inference import learn_target_pattern
        em_tickers = sorted(set(watchlist["ticker"].tolist()))
        with st.spinner(f"Loading 2y history for {len(em_tickers)} tickers..."):
            try:
                em_history = fetch_price_history(em_tickers, period="2y")
            except Exception as exc:
                st.error(f"Price fetch failed: {exc}")
                em_history = {}
        if not em_history:
            st.warning(
                "No 2-year price history available yet — run the warm-cache "
                "workflow or retry after the next scheduled warm."
            )
        else:
            em_pattern = learn_target_pattern(watchlist, em_history)
            if em_pattern is None:
                st.warning("Not enough analyst targets to learn the rule from.")
            else:
                with st.spinner("Replaying static vs dynamic entries..."):
                    st.session_state["entry_mode_result"] = compare_entry_modes(
                        expanded, em_history, em_pattern,
                    )
    entry_mode = st.session_state.get("entry_mode_result")
    if entry_mode is not None:
        if entry_mode.empty:
            st.info("No entries fired — run after the caches warm.")
        else:
            ed = entry_mode.copy()
            ed["win_rate"] = ed["win_rate"] * 100.0
            st.dataframe(
                ed, use_container_width=True, hide_index=True,
                column_config={
                    "variant": "Entry mode",
                    "n_signals": st.column_config.NumberColumn("Signals", format="%d"),
                    "n_closed": st.column_config.NumberColumn("Closed", format="%d"),
                    "win_rate": st.column_config.NumberColumn("Win rate", format="%.0f%%"),
                    "avg_return_pct": st.column_config.NumberColumn("Avg ret", format="%+.1f%%"),
                    "median_return_pct": st.column_config.NumberColumn("Median", format="%+.1f%%"),
                    "avg_days_held": st.column_config.NumberColumn("Avg days", format="%.0f"),
                    "n_train": st.column_config.NumberColumn("n 1st half", format="%d"),
                    "avg_train_pct": st.column_config.NumberColumn("1st half", format="%+.1f%%"),
                    "n_test": st.column_config.NumberColumn("n 2nd half", format="%d"),
                    "avg_test_pct": st.column_config.NumberColumn("2nd half", format="%+.1f%%"),
                },
            )
            st.caption(
                "First run (2026-08-04, 2y cache): dynamic-same-tickers beat "
                "the control in BOTH halves with a higher win rate and a "
                "positive median — but at n = 11/7 per half it is UNDER the "
                "n ≥ 15 pre-registered bar, so static analyst entries stay "
                "live and the refreshed levels are surfaced on stale rows "
                "only. Re-run as history accumulates; adopt only when the "
                "bar is met. Not financial advice."
            )

    # ---- Rotation panel (pre-registered ledger experiment) -----------------
    st.divider()
    st.markdown("### 🔄 ETF momentum rotation — pre-registered experiment")
    st.caption(
        "Ledger id `etf-momentum-rotation`, design fixed BEFORE results: "
        "each month-end, rank the ETF pool by trailing momentum and hold "
        "the top K for a month, 0.10% per one-way trade on turnover. "
        "Believed only if it beats BOTH controls (SPY buy-and-hold and "
        "equal-weight-everything) in BOTH halves of a decade at ≥ 36 "
        "months per half. **Verdict (2026-08-09 run, 120 months): 🪦 "
        "rejected** — the flashy variant (12m lookback, 23.5% CAGR vs "
        "SPY's 15.4%) lost the FIRST half and won only the second (the "
        "2024-26 metals/crypto regime), 3m did the mirror image, and "
        "every variant drew down deeper than just holding SPY. The bar "
        "exists precisely so that 23.5% headline doesn't get traded."
    )
    from pathlib import Path as _Path
    _etf10 = _Path("data/cache/etf_prices_v1_10y.parquet")
    if not _etf10.exists():
        st.info("Awaiting the 10-year ETF cache — the nightly warm job "
                "builds it; check back after the next warm.")
    elif st.button("▶ Run the rotation experiment", key="rotation_run"):
        from .rotation import compare_rotation, rotation_verdict
        px10 = pd.read_parquet(_etf10)
        with st.spinner("Replaying a decade of monthly rotations..."):
            rot = compare_rotation(px10)
        st.session_state["rotation_result"] = rot
    rot = st.session_state.get("rotation_result")
    if rot is not None and not rot.empty:
        st.dataframe(
            rot, use_container_width=True, hide_index=True,
            column_config={
                "variant": "Strategy",
                "n_months": st.column_config.NumberColumn("Months", format="%d"),
                "mean_monthly_pct": st.column_config.NumberColumn(
                    "Mean/mo", format="%+.2f%%"),
                "cagr_pct": st.column_config.NumberColumn("CAGR", format="%+.1f%%"),
                "max_drawdown_pct": st.column_config.NumberColumn(
                    "Max DD", format="%.1f%%"),
                "pct_positive_months": st.column_config.NumberColumn(
                    "+months", format="%.0f%%"),
                "n_first": st.column_config.NumberColumn("n 1st", format="%d"),
                "mean_first_pct": st.column_config.NumberColumn(
                    "1st half/mo", format="%+.2f%%"),
                "n_second": st.column_config.NumberColumn("n 2nd", format="%d"),
                "mean_second_pct": st.column_config.NumberColumn(
                    "2nd half/mo", format="%+.2f%%"),
            },
        )
        from .rotation import rotation_verdict as _rv
        passing = _rv(rot)
        if passing.empty:
            st.error(
                "🪦 **No rotation variant cleared the pre-registered bar** "
                "— the ledger records the tombstone. Momentum rotation on "
                "this pool does not beat simply holding, after costs, in "
                "both halves."
            )
        else:
            st.success(
                "✅ Cleared the bar: "
                + ", ".join(passing["variant"])
                + " — beat both controls in both halves. Tell Claude to "
                "flip the ledger row and surface monthly holdings."
            )

    # ---- Trend-filter panel (pre-registered experiment #2) -----------------
    st.divider()
    st.markdown("### 🛡 Trend filter on SPY — pre-registered experiment #2")
    st.caption(
        "Ledger id `trend-filter-defensive`: hold SPY only above its "
        "long-term trend, cash (at 0%) otherwise; 0.10% per switch. "
        "Defensive bar: drawdown ≥ 25% shallower AND CAGR within 3pts of "
        "buy-and-hold, in BOTH halves. **Verdict (2026-08-09 run, 10y): "
        "🪦 rejected** — SMA filters gave up ~7pts of CAGR/yr for almost "
        "no drawdown relief (this decade's crashes were too fast for "
        "month-end signals); 12m momentum came closest but helped not at "
        "all in the first half. Re-runnable below as history grows."
    )
    if _etf10.exists() and st.button("▶ Re-run the trend-filter experiment",
                                     key="trend_run"):
        from .trend_filter import compare_trend_filters, trend_verdict
        spy10 = pd.read_parquet(_etf10)
        if "SPY" in spy10.columns:
            with st.spinner("Replaying a decade of trend filtering..."):
                st.session_state["trend_result"] = compare_trend_filters(
                    spy10["SPY"].dropna(),
                )
    trend_res = st.session_state.get("trend_result")
    if trend_res is not None and not trend_res.empty:
        st.dataframe(
            trend_res, use_container_width=True, hide_index=True,
            column_config={
                "variant": "Strategy",
                "n_months": st.column_config.NumberColumn("Months", format="%d"),
                "cagr_pct": st.column_config.NumberColumn("CAGR", format="%+.1f%%"),
                "max_drawdown_pct": st.column_config.NumberColumn("Max DD", format="%.1f%%"),
                "pct_in_market": st.column_config.NumberColumn("Time in mkt", format="%.0f%%"),
                "n_first": st.column_config.NumberColumn("n 1st", format="%d"),
                "cagr_first_pct": st.column_config.NumberColumn("CAGR 1st", format="%+.1f%%"),
                "dd_first_pct": st.column_config.NumberColumn("DD 1st", format="%.1f%%"),
                "n_second": st.column_config.NumberColumn("n 2nd", format="%d"),
                "cagr_second_pct": st.column_config.NumberColumn("CAGR 2nd", format="%+.1f%%"),
                "dd_second_pct": st.column_config.NumberColumn("DD 2nd", format="%.1f%%"),
            },
        )


def _render_about_tab(st) -> None:
    """Plain-English guide to what the app is and how each piece works."""
    st.subheader("ℹ️ What is Icarus?")
    st.markdown(
        """
Icarus is a **stock-watching and trade-tracking research tool**. It watches a
curated list of shares with analyst buy/sell price targets, compares them
against live market prices, tells you which — if any — deserve attention
**today**, and then keeps score of the trades you actually make.

It does not place trades, it does not manage money, and nothing in it is
financial advice. It ranks and records; you decide.

---

### The one-minute version

Every stock has a **buy target** (where it looks cheap) and a **sell target**
(where the gains have been made). When the live price reaches the buy target,
the stock is **in the buy zone**. Cheap isn't enough — a stock can be cheap
because it's dying — so buy-zone stocks pass through quality checks, and only
the rare names passing *everything* while showing signs of life today become
**💎 Gems**. One gem is crowned **👑 Pick of the Day** — or the app says
*"no trade today"*, which is a real answer. If you then buy, you log the trade
in **💼 Portfolio**, and the app tracks it against your levels, warns you when
a stop is hit, and remembers whether following the picks worked.

---

### Watchlist tab, top to bottom

**🔎 Ticker lookup** — type any ticker for its full picture: price chart with
your levels drawn on it, targets, stop, and why it is or isn't a gem.

**👑 Pick of the Day** — the single best opportunity across the curated list
and the wider 🧭 Explorer universe, ranked by trust-adjusted score (analyst
targets count fully; app-derived targets count less). Every pick is logged
automatically so your adherence can be measured later.

**💎 Gems** — passed ALL of: buy zone · own 6-month momentum positive · theme
rising on the 6-month median · reward at least 3× the risk · not already
parabolic — **horizons chosen by backtest evidence in the 🧪 Lab, not by
opinion** — plus something happening today (volume, freshness, news).
Insider buying (SEC filings, 2-day lag) adds a soft 💼 boost. Empty most
days by design; when empty, the near-misses explain which gate they failed.

**☀️ Today's signals** — the attention list: buy-zone stocks ranked by what's
moving today. No quality gates — "look here", never "buy this".

**The instrument list** — tappable rows (status dot · ticker · sparkline ·
price · day change), Trading212-style. Tap to open the chart view. Targets
the market has ignored for 6+ months are flagged **⏳ stale** — those alerts
can never fire and the level likely predates a re-rating.

---

### 💼 Portfolio

Log the trades you actually make (buy/sell, quantity, price). The app then:

- values everything at near-live quotes with day and all-time change chips
- computes **Risk at stops** — your total loss if every holding fell to its
  stop tomorrow. Keep this a number you can shrug at.
- warns when most of your money is secretly **one theme** — several tickers,
  one bet
- sends a **🛑 push alert when a holding closes at or below its stop** —
  "the rule says sell", repeated every scan until you act — and an early
  warning when a close comes within 3% of the stop
- tracks **🎯 adherence**: every daily pick is logged, and the tab shows how
  often you acted on them — building toward the answer to "do my overrides
  beat the system?"

Trades are stored as commits in your own GitHub repository — versioned,
auditable, and durable across app updates.

---

### 📊 Track record

The honesty page. Every historical buy-zone entry is replayed forward —
🎯 hit target, 🛑 hit stop, ⏰ timed out — with no editing and no
cherry-picking, plus the £5k concentrated-trading simulation. Wait for 30+
closed signals before believing any percentage.

### ⚡ Swing

A separate, short-horizon game: **+5% targets in ≤10 sessions** with a 3%
stop, across four instrument pools (curated microcaps, S&P/Nasdaq large
caps, index & sector ETFs, liquid OTC ADRs) — each tested net of its own
real-world cost with conservative fills. **Live candidates only unlock
where a strategy beats that pool's control in both walk-forward halves.**
Verdict so far (Aug 2026): the curated microcaps, large caps and OTC all
FAIL — costs and chop eat the edge. The one qualifier: **oversold RSI<30
on index/sector ETFs** (71% win rate, ≈+1.5% net per ~9-session trade,
positive in both halves) — buying index panic works; buying stock stories
for a quick flip doesn't. Note it fires mostly in corrections, so signals
cluster — size accordingly.

### 🧪 Lab

Where signal arguments go to be settled. It opens with the **🧬 hypothesis
ledger** — an append-only record of every idea ever tested here and how it
died (the rejections are the point: each is a strategy that looked good and
would have cost money). Below it, the experiment panels: **entry
definitions**, **exit policies**, **entry modes** (static analyst levels vs
the learned rule tracked live), **ETF momentum rotation** (rejected — its
23.5% CAGR headline was one regime's story) and the **SPY trend filter**
(rejected — insurance that cost 7%/yr and didn't pay out). Every comparison
uses a walk-forward split with pre-registered verdict bars — a variant must
win in BOTH halves of history with a decent sample before it changes any
default, and the bar is written down before the experiment runs. The
current 6-month gates and 20% stop were chosen exactly this way; a
post-earnings-drift experiment is queued next.

---

### Key terms

| Term | Meaning |
|---|---|
| **Buy zone** | Live price at or below the analyst's buy target |
| **Stop** | Pre-commit exit 20% below your fill (chosen by Exit-Lab evidence). Size ~0.6× what you would at a tighter stop so per-trade risk stays constant |
| **R:R** | Reward-to-risk: upside to the sell target vs downside to the stop |
| **⏳ Stale target** | Price has ignored the level for 6+ months — treat as historical |
| **Tgt A/D** | Target provenance: Analyst-set vs Derived by the app (counts less) |
| **🧭 Explorer** | Wider screened universe of US small caps; fully derived targets |
| **Risk at stops** | Total loss if every stop hits tomorrow — the ruin-prevention number |
| **Adherence** | How often you actually acted on the logged daily picks |

---

### The philosophy in three lines

1. **Agreement beats any single signal** — cheap AND rising AND hot theme AND
   asymmetric AND waking up today.
2. **Not trading is a position.** Most days the right answer is nothing, and
   the app says so plainly.
3. **Evidence changes the rules; opinions don't.** Gates and exits are set by
   backtests in the Lab, picks are logged before outcomes are known, and the
   track record grades everything in public.

---

*Research tool only. Prices via Yahoo Finance (may be delayed). Nothing here
is financial advice — do your own research, and never risk money you can't
afford to lose.*
        """
    )


def _build_sha() -> str:
    """Short git SHA of the running deploy, shown in the header caption so
    'which version am I looking at?' is answerable at a glance. Falls back
    gracefully when .git isn't available."""
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True, timeout=3, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


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
        f"a forward-marked track record. Read-only research view — not "
        f"financial advice. · build `{_build_sha()}`"
    )

    tab_watchlist, tab_portfolio, tab_swing, tab_track, tab_lab, tab_about = st.tabs(
        ["Watchlist", "💼 Portfolio", "⚡ Swing", "📊 Track record", "🧪 Lab",
         "ℹ️ About"],
    )

    # ---- Watchlist: analyst-curated picks with live alerts ----------------
    with tab_watchlist:
        _render_watchlist_tab(st)

    # ---- Portfolio: real trades, marked to market -------------------------
    with tab_portfolio:
        _render_portfolio_tab(st)

    # ---- Swing: short-horizon +5% engine (evidence-gated) -----------------
    with tab_swing:
        _render_swing_tab(st)

    # ---- Track record: forward-marked signal history ----------------------
    with tab_track:
        _render_track_record_tab(st)

    # ---- Lab: signal-definition comparison backtest -----------------------
    with tab_lab:
        _render_lab_tab(st)

    # ---- About: plain-English guide ---------------------------------------
    with tab_about:
        _render_about_tab(st)

if __name__ == "__main__":
    main()
