"""Portfolio tracking: log real trades, mark them to market.

Storage model: trades live in ``portfolio/trades.csv`` on a dedicated
``portfolio-data`` branch of the user's own repo, read and written via
the GitHub contents API using a fine-grained PAT held in Streamlit
secrets (``PORTFOLIO_GH_TOKEN``). Why this design:

  - Streamlit Cloud wipes local disk on every deploy — files die.
  - A separate branch means logging a trade does NOT trigger an app
    redeploy (Streamlit only watches the deploy branch).
  - The trade log is versioned: every trade is a commit, history is
    auditable forever, and mistakes are revertable.

Without a token the UI falls back to session-only storage with CSV
download/upload for manual persistence — usable immediately, upgrade
path clearly signposted.

Position accounting: AVERAGE COST (the retail-standard method brokers
like Trading212 display). Buys move the average; sells realise
(price − avg_cost) × qty and never change the average of what remains.
Overselling is clamped to the held quantity and flagged.
"""

from __future__ import annotations

import base64
import io
import logging
import uuid
from datetime import date

import pandas as pd

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
PORTFOLIO_BRANCH = "portfolio-data"
PORTFOLIO_PATH = "portfolio/trades.csv"

TRADE_COLUMNS = ["id", "date", "ticker", "side", "qty", "price", "note"]


def empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLUMNS)


def new_trade(
    ticker: str, side: str, qty: float, price: float,
    trade_date: date | None = None, note: str = "",
) -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "date": (trade_date or date.today()).isoformat(),
        "ticker": ticker.strip().upper(),
        "side": side,
        "qty": float(qty),
        "price": float(price),
        "note": note.strip(),
    }


def normalise_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a loaded/uploaded trades frame into the canonical schema."""
    if df is None or df.empty:
        return empty_trades()
    out = df.copy()
    for col in TRADE_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col in ("id", "note") else None
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    out["side"] = out["side"].astype(str).str.strip().str.lower()
    out = out[out["side"].isin(["buy", "sell"])]
    out["qty"] = pd.to_numeric(out["qty"], errors="coerce")
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out[(out["qty"] > 0) & (out["price"] > 0) & (out["ticker"] != "")]
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
    out = out.dropna(subset=["date"])
    out["id"] = out["id"].astype(str)
    missing_id = out["id"].isin(["", "nan", "None"])
    out.loc[missing_id, "id"] = [
        uuid.uuid4().hex[:10] for _ in range(int(missing_id.sum()))
    ]
    return out[TRADE_COLUMNS].sort_values("date").reset_index(drop=True)


def positions_from_trades(
    trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Average-cost position engine.

    Returns (open_positions, realised_log):
      open_positions: ticker, qty, avg_cost, invested
      realised_log:   date, ticker, qty, sell_price, avg_cost,
                      realised_pnl, oversold (True when the sell
                      exceeded the held quantity and was clamped)
    """
    if trades is None or trades.empty:
        return (
            pd.DataFrame(columns=["ticker", "qty", "avg_cost", "invested"]),
            pd.DataFrame(columns=[
                "date", "ticker", "qty", "sell_price", "avg_cost",
                "realised_pnl", "oversold",
            ]),
        )
    t = normalise_trades(trades)
    holdings: dict[str, dict] = {}
    realised: list[dict] = []
    for _, tr in t.iterrows():
        tk = tr["ticker"]
        h = holdings.setdefault(tk, {"qty": 0.0, "avg": 0.0})
        if tr["side"] == "buy":
            new_qty = h["qty"] + tr["qty"]
            h["avg"] = (
                (h["avg"] * h["qty"] + tr["price"] * tr["qty"]) / new_qty
                if new_qty > 0 else 0.0
            )
            h["qty"] = new_qty
        else:
            sell_qty = min(tr["qty"], h["qty"])
            oversold = tr["qty"] > h["qty"] + 1e-9
            if sell_qty > 0:
                realised.append({
                    "date": tr["date"],
                    "ticker": tk,
                    "qty": sell_qty,
                    "sell_price": tr["price"],
                    "avg_cost": h["avg"],
                    "realised_pnl": (tr["price"] - h["avg"]) * sell_qty,
                    "oversold": oversold,
                })
                h["qty"] -= sell_qty
            elif oversold:
                realised.append({
                    "date": tr["date"], "ticker": tk, "qty": 0.0,
                    "sell_price": tr["price"], "avg_cost": h["avg"],
                    "realised_pnl": 0.0, "oversold": True,
                })
    open_rows = [
        {"ticker": tk, "qty": h["qty"], "avg_cost": h["avg"],
         "invested": h["qty"] * h["avg"]}
        for tk, h in holdings.items() if h["qty"] > 1e-9
    ]
    return (
        pd.DataFrame(open_rows).sort_values("invested", ascending=False)
        .reset_index(drop=True) if open_rows else
        pd.DataFrame(columns=["ticker", "qty", "avg_cost", "invested"]),
        pd.DataFrame(realised) if realised else pd.DataFrame(columns=[
            "date", "ticker", "qty", "sell_price", "avg_cost",
            "realised_pnl", "oversold",
        ]),
    )


def portfolio_totals(
    positions: pd.DataFrame,
    quotes: dict[str, dict],
) -> dict:
    """Aggregate live value / unrealised / day P&L across holdings.
    ``quotes``: {ticker: {"price": float, "prev_close": float|None}}."""
    value = invested = day_pnl = 0.0
    priced = 0
    for _, p in positions.iterrows():
        q = quotes.get(p["ticker"]) or {}
        px = q.get("price")
        invested += float(p["invested"])
        if px is None or not pd.notna(px):
            value += float(p["invested"])  # fall back to cost basis
            continue
        priced += 1
        value += float(p["qty"]) * float(px)
        prev = q.get("prev_close")
        if prev is not None and pd.notna(prev) and prev > 0:
            day_pnl += float(p["qty"]) * (float(px) - float(prev))
    return {
        "value": value,
        "invested": invested,
        "unrealised": value - invested,
        "unrealised_pct": ((value / invested - 1.0) * 100.0) if invested > 0 else 0.0,
        "day_pnl": day_pnl,
        "day_pct": (day_pnl / (value - day_pnl) * 100.0) if (value - day_pnl) > 0 else 0.0,
        "n_priced": priced,
        "n_positions": len(positions),
    }


def fetch_live_quotes(tickers: list[str]) -> dict[str, dict]:
    """Near-real-time quotes for the (small) set of held tickers via
    yfinance fast_info. Silently degrades per ticker."""
    out: dict[str, dict] = {}
    if not tickers:
        return out
    try:
        import yfinance as yf
    except ImportError:
        return out
    from .symbols import normalize_symbol
    from concurrent.futures import ThreadPoolExecutor

    def _one(t: str) -> tuple[str, dict]:
        try:
            fi = yf.Ticker(normalize_symbol(t)).fast_info
            price = getattr(fi, "last_price", None)
            prev = getattr(fi, "previous_close", None)
            if price is None and isinstance(fi, dict):
                price = fi.get("last_price") or fi.get("lastPrice")
                prev = fi.get("previous_close") or fi.get("previousClose")
            return t, {"price": float(price) if price else None,
                       "prev_close": float(prev) if prev else None}
        except Exception as exc:  # noqa: BLE001
            log.debug("quote failed for %s: %s", t, exc)
            return t, {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, q in ex.map(_one, tickers):
            out[t] = q
    return out


DEFAULT_PORTFOLIO_STOP_PCT = 0.12


def stop_breaches(
    positions: pd.DataFrame,
    latest_closes: dict[str, float],
    *,
    stop_pct: float = DEFAULT_PORTFOLIO_STOP_PCT,
    warn_within_pct: float = 3.0,
) -> pd.DataFrame:
    """The most valuable alert the app can send: 'your rule says sell'.

    Stop convention: avg_cost × (1 − stop_pct) — the runbook's 12% below
    the fill. Returns one row per holding that has BREACHED its stop
    (close ≤ stop) or is WITHIN ``warn_within_pct`` above it, columns:
    ticker, qty, avg_cost, stop, close, distance_pct, state
    ('breached' | 'near'). Holdings without a close are skipped —
    silence must never be mistaken for safety, so callers should report
    unpriced holdings separately."""
    rows: list[dict] = []
    if positions is None or positions.empty:
        return pd.DataFrame(columns=[
            "ticker", "qty", "avg_cost", "stop", "close",
            "distance_pct", "state",
        ])
    for _, p in positions.iterrows():
        close = latest_closes.get(p["ticker"])
        if close is None or not pd.notna(close) or close <= 0:
            continue
        stop = float(p["avg_cost"]) * (1.0 - stop_pct)
        if stop <= 0:
            continue
        distance_pct = (float(close) - stop) / stop * 100.0
        if float(close) <= stop:
            state = "breached"
        elif distance_pct <= warn_within_pct:
            state = "near"
        else:
            continue
        rows.append({
            "ticker": p["ticker"],
            "qty": float(p["qty"]),
            "avg_cost": float(p["avg_cost"]),
            "stop": stop,
            "close": float(close),
            "distance_pct": distance_pct,
            "state": state,
        })
    return pd.DataFrame(rows)


def load_public_trades(
    repo: str,
    *, branch: str = PORTFOLIO_BRANCH, path: str = PORTFOLIO_PATH,
) -> pd.DataFrame:
    """Tokenless read of the trade log via raw.githubusercontent — the
    repo is public, so the notifier can check stops without any secret."""
    import requests
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    try:
        resp = requests.get(url, timeout=20)
        if resp.status_code == 404:
            return empty_trades()
        resp.raise_for_status()
        text = resp.text
        if not text.strip():
            return empty_trades()
        return normalise_trades(pd.read_csv(io.StringIO(text), dtype=str))
    except Exception as exc:  # noqa: BLE001
        log.warning("Public trade read failed (%s)", exc)
        return empty_trades()


# ---------------------------------------------------------------------------
# GitHub-backed persistence (portfolio-data branch)
# ---------------------------------------------------------------------------


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_remote_trades(
    token: str, repo: str,
    *, branch: str = PORTFOLIO_BRANCH, path: str = PORTFOLIO_PATH,
) -> tuple[pd.DataFrame, str | None]:
    """Read trades.csv from the data branch. Returns (df, blob_sha).
    Missing file/branch → (empty, None)."""
    import requests
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        params={"ref": branch}, headers=_gh_headers(token), timeout=20,
    )
    if resp.status_code == 404:
        return empty_trades(), None
    resp.raise_for_status()
    payload = resp.json()
    raw = base64.b64decode(payload["content"]).decode("utf-8")
    df = pd.read_csv(io.StringIO(raw), dtype=str) if raw.strip() else empty_trades()
    return normalise_trades(df), payload.get("sha")


def _ensure_branch(token: str, repo: str, branch: str) -> None:
    import requests
    h = _gh_headers(token)
    r = requests.get(f"{GITHUB_API}/repos/{repo}/branches/{branch}", headers=h, timeout=20)
    if r.status_code == 200:
        return
    repo_info = requests.get(f"{GITHUB_API}/repos/{repo}", headers=h, timeout=20)
    repo_info.raise_for_status()
    default = repo_info.json()["default_branch"]
    base = requests.get(
        f"{GITHUB_API}/repos/{repo}/git/ref/heads/{default}", headers=h, timeout=20,
    )
    base.raise_for_status()
    sha = base.json()["object"]["sha"]
    create = requests.post(
        f"{GITHUB_API}/repos/{repo}/git/refs", headers=h, timeout=20,
        json={"ref": f"refs/heads/{branch}", "sha": sha},
    )
    if create.status_code not in (200, 201, 422):  # 422 = raced into existence
        create.raise_for_status()


def save_remote_trades(
    token: str, repo: str, trades: pd.DataFrame, sha: str | None,
    *, branch: str = PORTFOLIO_BRANCH, path: str = PORTFOLIO_PATH,
    message: str = "Log trade",
) -> str:
    """Write trades.csv to the data branch; returns the new blob sha."""
    import requests
    _ensure_branch(token, repo, branch)
    csv_text = normalise_trades(trades).to_csv(index=False)
    body = {
        "message": message,
        "content": base64.b64encode(csv_text.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    resp = requests.put(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        headers=_gh_headers(token), json=body, timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["content"]["sha"]
