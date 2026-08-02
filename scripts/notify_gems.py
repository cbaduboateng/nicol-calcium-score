"""Scheduled gem notifier — run from GitHub Actions, pushes via ntfy.sh.

Computes gems exactly the way the dashboard does (derived targets
included, news omitted for speed — news is a bonus signal, never a
gate) and, when any exist, POSTs a summary to the ntfy topic named in
the NTFY_TOPIC env var. Subscribe to that topic in the free ntfy app
on your phone and the push arrives like any other notification.

No topic configured -> exits quietly (the workflow is a no-op until
the user adds the secret). No gems -> no notification; silence means
the gates are doing their job.
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="[notify] %(levelname)s %(message)s")
log = logging.getLogger("notify_gems")

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")


def main() -> int:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        log.info("NTFY_TOPIC not set — skipping notification run")
        return 0

    from icarus.daily_signals import find_gems
    from icarus.target_inference import derive_targets, learn_target_pattern
    from icarus.insider_overlay import load_insider_overlay
    from icarus.watchlist_alerts import (
        WATCHLIST_PATH,
        build_watchlist_view,
        fetch_price_history,
        fetch_volume_history,
        load_catalyst_overlay,
        load_watchlist,
    )

    watchlist = load_watchlist(WATCHLIST_PATH)
    if watchlist.empty:
        log.error("Watchlist empty; nothing to scan")
        return 1
    tickers = sorted(set(watchlist["ticker"].astype(str)))
    history = fetch_price_history(tickers, period="1y")
    if not history:
        log.error("No price history; aborting scan")
        return 1
    volumes = fetch_volume_history(tickers, period="3mo")

    # ---- Stop-breach alerts on real holdings (fires regardless of gems) ----
    # A breached stop re-alerts on every scan until resolved: for a rule
    # that says SELL, persistent nagging is the correct behaviour.
    try:
        import requests as _rq

        from icarus.portfolio import (
            fetch_live_quotes,
            load_public_trades,
            positions_from_trades,
            stop_breaches,
        )
        pt = load_public_trades(
            "cbaduboateng/nicol-calcium-score",
            token=os.environ.get("PICKLOG_TOKEN", "").strip(),
        )
        positions, _ = positions_from_trades(pt)
        if not positions.empty:
            closes: dict[str, float] = {}
            missing: list[str] = []
            for t in positions["ticker"]:
                s = history.get(t)
                if s is not None and not s.dropna().empty:
                    closes[t] = float(s.dropna().iloc[-1])
                else:
                    missing.append(t)
            for t, q in (fetch_live_quotes(missing) if missing else {}).items():
                if q.get("price"):
                    closes[t] = q["price"]
            unpriced = [t for t in positions["ticker"] if t not in closes]
            breaches = stop_breaches(positions, closes)
            if not breaches.empty or unpriced:
                blines: list[str] = []
                for _, b in breaches.iterrows():
                    if b["state"] == "breached":
                        blines.append(
                            f"🛑 {b['ticker']}: close {b['close']:,.2f} ≤ stop "
                            f"{b['stop']:,.2f} — THE RULE SAYS SELL"
                        )
                    else:
                        blines.append(
                            f"⚠️ {b['ticker']}: close {b['close']:,.2f}, only "
                            f"{b['distance_pct']:+.1f}% above stop {b['stop']:,.2f}"
                        )
                for t in unpriced:
                    blines.append(f"❔ {t}: no price — check it manually")
                if any(b["state"] == "breached" for _, b in breaches.iterrows()):
                    b_title = "🛑 Stop breached — action required"
                    prio = "urgent"
                else:
                    b_title = "⚠️ Position near its stop"
                    prio = "high"
                if blines:
                    _rq.post(
                        f"{NTFY_SERVER}/{topic}",
                        data=("\n".join(blines)
                              + "\n\nStops = avg cost −12%. Not financial advice."
                              ).encode("utf-8"),
                        headers={"Title": b_title.encode("utf-8"),
                                 "Priority": prio, "Tags": "rotating_light"},
                        timeout=30,
                    )
                    log.info("Pushed %d stop lines", len(blines))
    except Exception as exc:  # noqa: BLE001
        log.warning("Stop-breach check failed (%s)", exc)

    pattern = learn_target_pattern(watchlist, history)
    if pattern is not None:
        watchlist = derive_targets(watchlist, history, pattern)

    view = build_watchlist_view(watchlist, history)
    try:
        insider = load_insider_overlay()
    except Exception:
        insider = {}
    gems = find_gems(
        view, history, volumes,
        insider_overlay=insider or None,
        catalyst_overlay=load_catalyst_overlay() or None,
        top_n=5,
    )

    # Explorer pool, when the weekly job has produced one.
    import pandas as pd
    explorer_gems = pd.DataFrame()
    try:
        from icarus.universe import load_explorer_watchlist
        explorer_wl = load_explorer_watchlist()
        if not explorer_wl.empty and pattern is not None:
            exp_tickers = sorted(set(explorer_wl["ticker"].astype(str)))
            exp_history = fetch_price_history(exp_tickers, period="1y")
            if exp_history:
                explorer_wl = derive_targets(explorer_wl, exp_history, pattern)
                exp_view = build_watchlist_view(explorer_wl, exp_history)
                exp_view["tgt_src"] = "D/D"
                exp_volumes = fetch_volume_history(exp_tickers, period="3mo")
                explorer_gems = find_gems(exp_view, exp_history, exp_volumes, top_n=5)
    except Exception as exc:  # noqa: BLE001
        log.warning("Explorer pool skipped (%s)", exc)

    if gems.empty and explorer_gems.empty:
        log.info("No gems this scan — staying silent")
        return 0

    from icarus.daily_signals import pick_of_the_day
    verdict = pick_of_the_day([
        (gems, "curated", 1.0),
        (explorer_gems, "explorer", 0.85),
    ])

    # ---- Log the pick for the adherence mirror -----------------------------
    if verdict["pick"] is not None:
        pick_tok = os.environ.get("PICKLOG_TOKEN", "").strip()
        if pick_tok:
            try:
                from datetime import date as _date

                from icarus.portfolio import append_pick
                pk = verdict["pick"]
                append_pick(pick_tok, "cbaduboateng/nicol-calcium-score", {
                    "date": _date.today().isoformat(),
                    "ticker": str(pk["ticker"]),
                    "adjusted_score": f"{pk['adjusted_score']:.3f}",
                    "pool": str(pk["pool"]),
                })
                log.info("Pick logged to portfolio-data")
            except Exception as exc:  # noqa: BLE001
                log.warning("Pick logging failed (%s)", exc)

    lines: list[str] = []
    if verdict["pick"] is not None:
        p = verdict["pick"]
        lines.append(
            f"👑 PICK: {p['ticker']} adj {p['adjusted_score']:.2f} "
            f"({p['pool']})"
        )
        lines.append("")
    if not explorer_gems.empty:
        gems = pd.concat([gems, explorer_gems], ignore_index=True)
    for _, g in gems.iterrows():
        live = g.get("live_price")
        entry = g.get("target_entry")
        stop = g.get("stop_price")
        exit_ = g.get("target_exit")

        def _f(v):
            import pandas as pd
            return f"{v:,.2f}" if v is not None and pd.notna(v) else "—"

        lines.append(
            f"{g['ticker']}  score {g['gem_score']:.2f} | "
            f"live {_f(live)} buy≤{_f(entry)} stop {_f(stop)} sell≥{_f(exit_)}"
        )
        reasons = str(g.get("reasons") or "")
        if reasons:
            lines.append(f"   {reasons}")

    n = len(gems)
    title = f"💎 {n} gem{'s' if n != 1 else ''} on the watchlist"
    body = "\n".join(lines) + "\n\nScreening signal, not financial advice."

    import requests
    resp = requests.post(
        f"{NTFY_SERVER}/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Priority": "high",
            "Tags": "gem",
        },
        timeout=30,
    )
    resp.raise_for_status()
    log.info("Pushed %d gems to ntfy topic", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
