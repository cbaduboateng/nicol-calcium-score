"""Signal Lab: comparison backtest across signal-definition variants.

Response to the hedge-fund critique: "your 6-combo signal hasn't been
proven — try other signals and do a comparison backtest." Correct. The
gem gates were assembled from priors, not evidence. This module makes
them falsifiable.

Each ``SignalVariant`` is one definition of "a signal fired": a BUY ZONE
crossing plus a configurable gate set (momentum window and requirement,
theme requirement, R:R floor). Every variant is replayed over the SAME
price history with the SAME exits (target / stop / timeout, conservative
tie-break), so differences in outcome are attributable to the signal
definition alone.

Honesty rules:
  - No look-ahead: gates are evaluated with data up to the signal date
    only (momentum uses trailing closes; theme medians use each theme
    member's trailing closes at that date).
  - Walk-forward split: signals are labelled train (first half of the
    date range) or test (second half). A variant that only wins in one
    half is curve-fit noise; believe the ones that win in both.
  - A no-gate CONTROL variant is always included: if gated variants
    can't beat "buy every crossing", the gates subtract value.
  - Same caveats as the track record: today's targets applied
    historically, close-only fills, no slippage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .track_record import (
    DEFAULT_STOP_PCT,
    DEFAULT_TIMEOUT_DAYS,
    detect_signals,
)
from .watchlist_alerts import map_theme

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalVariant:
    name: str
    momentum_days: int = 63             # trailing window for the momentum gate
    require_positive_momentum: bool = True
    require_positive_theme: bool = True
    min_rr: float = 3.0                 # 0 disables the gate
    stop_pct: float = DEFAULT_STOP_PCT
    timeout_days: int = DEFAULT_TIMEOUT_DAYS


DEFAULT_VARIANTS: tuple[SignalVariant, ...] = (
    SignalVariant("control: every crossing", require_positive_momentum=False,
                  require_positive_theme=False, min_rr=0.0),
    SignalVariant("baseline: 3m momentum"),
    SignalVariant("fast: 1m momentum", momentum_days=21),
    SignalVariant("slow: 6m momentum", momentum_days=126),
    SignalVariant("no theme gate", require_positive_theme=False),
    SignalVariant("no momentum gate", require_positive_momentum=False),
    SignalVariant("looser R:R (2)", min_rr=2.0),
    # Completes the ablation matrix: with 'no momentum' = theme+RR and
    # 'no theme' = momentum+RR, this isolates what R:R does alone.
    SignalVariant("rr only (no theme, no momentum)",
                  require_positive_momentum=False,
                  require_positive_theme=False, min_rr=3.0),
)


@dataclass(frozen=True)
class ExitVariant:
    """One exit policy, applied to the SAME validated entries.

    The track record showed hit-rate ~1%: analyst 2.5x targets are almost
    never reached in 6 months, so all profit currently comes from lucky
    timeouts — the exit policy is accidental. This panel makes it chosen.
    """
    name: str
    stop_pct: float = 0.10
    timeout_days: int = 180
    trail_low_days: int | None = None   # exit on close below the N-day low
    take_half_at_pct: float | None = None  # realise half at +X%, ride the rest
    use_target: bool = True             # False = pure trend-follow, no target


DEFAULT_EXIT_VARIANTS: tuple[ExitVariant, ...] = (
    ExitVariant("baseline: 10% stop / target / 6m"),
    ExitVariant("hold longer: 12m timeout", timeout_days=365),
    ExitVariant("wide stop 15%", stop_pct=0.15),
    ExitVariant("wide stop 20%", stop_pct=0.20),
    ExitVariant("trail the 20d low", trail_low_days=20),
    ExitVariant("take half at +30%", take_half_at_pct=30.0),
    ExitVariant("trend only: trail, no target",
                trail_low_days=20, use_target=False, timeout_days=365),
)


def _mark_forward_exit(
    series: pd.Series,
    roll_low: pd.Series | None,
    sig: dict,
    v: ExitVariant,
) -> dict:
    """Walk one entry forward under an exit policy. Conservative ordering
    per bar: stop, then trailing, then target, then timeout. With
    take-half active, half the position locks at +X% and the final
    return blends 50/50 with the remainder's outcome."""
    entry = float(sig["entry_price"])
    d0 = pd.Timestamp(sig["signal_date"])
    stop = entry * (1.0 - v.stop_pct)
    target = sig.get("target_exit") if v.use_target else None
    timeout_d = d0 + pd.Timedelta(days=v.timeout_days)
    half_locked: float | None = None

    def _blend(r: float) -> float:
        return 0.5 * half_locked + 0.5 * r if half_locked is not None else r

    after = series[series.index > d0]
    for ts, px in after.items():
        if not np.isfinite(px):
            continue
        px = float(px)
        gain_pct = (px - entry) / entry * 100.0
        if (half_locked is None and v.take_half_at_pct is not None
                and gain_pct >= v.take_half_at_pct):
            half_locked = float(v.take_half_at_pct)
        reason = None
        if px <= stop:
            reason = "stop"
        elif v.trail_low_days and roll_low is not None:
            low = roll_low.get(ts, np.nan)
            if np.isfinite(low) and px < float(low):
                reason = "trail"
        if reason is None and target is not None and pd.notna(target) and px >= float(target):
            reason = "target"
        if reason is None and ts >= timeout_d:
            reason = "timeout"
        if reason:
            return {
                "return_pct": _blend(gain_pct),
                "days_held": int((ts - d0).days),
                "close_reason": reason,
                "open": False,
            }
    last = float(series.dropna().iloc[-1])
    return {
        "return_pct": _blend((last - entry) / entry * 100.0),
        "days_held": int((series.index[-1] - d0).days),
        "close_reason": "open",
        "open": True,
    }


def compare_exit_variants(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    variants: tuple[ExitVariant, ...] = DEFAULT_EXIT_VARIANTS,
    *,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Fix the ENTRY definition to the Lab-validated 6m gate set and vary
    only the exit. One summary row per exit policy, with the same
    walk-forward split as the entry comparison."""
    entry_def = SignalVariant("entries: validated 6m gates", momentum_days=126)
    entries = run_variant(watchlist, price_history, entry_def, as_of=as_of)
    if entries.empty:
        return pd.DataFrame()

    prices = _prices_frame(price_history)
    d0, d1 = prices.index.min(), prices.index.max()
    midpoint = d0 + (d1 - d0) / 2

    series_by_ticker = {
        t: prices[t].dropna() for t in entries["ticker"].unique()
        if t in prices.columns
    }

    out: list[dict] = []
    for v in variants:
        roll_by_ticker: dict[str, pd.Series] = {}
        if v.trail_low_days:
            roll_by_ticker = {
                t: s.rolling(v.trail_low_days).min().shift(1)
                for t, s in series_by_ticker.items()
            }
        marked: list[dict] = []
        for _, sig in entries.iterrows():
            s = series_by_ticker.get(sig["ticker"])
            if s is None or s.empty:
                continue
            m = _mark_forward_exit(
                s, roll_by_ticker.get(sig["ticker"]), sig.to_dict(), v,
            )
            m["signal_date"] = sig["signal_date"]
            marked.append(m)
        mdf = pd.DataFrame(marked)
        if mdf.empty:
            continue
        closed = mdf[~mdf["open"]]
        sd = pd.to_datetime(mdf["signal_date"])
        train, test = mdf[sd <= midpoint], mdf[sd > midpoint]
        out.append({
            "variant": v.name,
            "n_signals": len(mdf),
            "n_closed": len(closed),
            "win_rate": float((closed["return_pct"] > 0).mean()) if len(closed) else np.nan,
            "avg_return_pct": float(closed["return_pct"].mean()) if len(closed) else np.nan,
            "median_return_pct": float(closed["return_pct"].median()) if len(closed) else np.nan,
            "avg_days_held": float(closed["days_held"].mean()) if len(closed) else np.nan,
            "n_train": len(train),
            "avg_train_pct": float(train["return_pct"].mean()) if len(train) else np.nan,
            "n_test": len(test),
            "avg_test_pct": float(test["return_pct"].mean()) if len(test) else np.nan,
        })
    df = pd.DataFrame(out)
    return df.sort_values(
        "avg_return_pct", ascending=False, na_position="last",
    ).reset_index(drop=True) if not df.empty else df


def _prices_frame(price_history: dict[str, pd.Series]) -> pd.DataFrame:
    cols = {}
    for t, s in price_history.items():
        s = s.dropna()
        if s.empty:
            continue
        idx = pd.to_datetime(s.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        cols[t] = pd.Series(s.values, index=idx)
    return pd.DataFrame(cols).sort_index() if cols else pd.DataFrame()


def run_variant(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    variant: SignalVariant,
    *,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Replay one variant. Returns the gated, forward-marked signals."""
    if watchlist is None or watchlist.empty or not price_history:
        return pd.DataFrame()

    prices = _prices_frame(price_history)
    if prices.empty:
        return pd.DataFrame()
    mom = prices.pct_change(variant.momentum_days, fill_method=None)

    theme_map = {
        str(r["ticker"]).upper(): map_theme(r.get("description"))
        for _, r in watchlist.iterrows()
    }
    theme_mom: dict[str, pd.Series] = {}
    if variant.require_positive_theme:
        by_theme: dict[str, list[str]] = {}
        for t in prices.columns:
            by_theme.setdefault(theme_map.get(t, "Other"), []).append(t)
        for theme, members in by_theme.items():
            theme_mom[theme] = mom[members].median(axis=1)

    rows: list[dict] = []
    for _, row in watchlist.iterrows():
        ticker = str(row.get("ticker") or "").upper()
        entry = row.get("target_entry")
        exit_ = row.get("target_exit")
        if not pd.notna(entry) or float(entry) <= 0:
            continue
        hist = price_history.get(ticker)
        if hist is None or len(hist) == 0:
            continue
        signals = detect_signals(
            ticker, hist, float(entry),
            float(exit_) if pd.notna(exit_) else None,
            stop_pct=variant.stop_pct,
            timeout_days=variant.timeout_days,
            as_of=as_of,
        )
        for sig in signals:
            d = pd.Timestamp(sig["signal_date"])
            p = sig["entry_price"]

            if variant.require_positive_momentum:
                m = mom.at[d, ticker] if (d in mom.index and ticker in mom.columns) else np.nan
                if not np.isfinite(m) or m <= 0:
                    continue
            if variant.require_positive_theme:
                tm_series = theme_mom.get(theme_map.get(ticker, "Other"))
                tm = tm_series.get(d, np.nan) if tm_series is not None else np.nan
                if not np.isfinite(tm) or tm <= 0:
                    continue
            if variant.min_rr > 0:
                if not pd.notna(exit_) or float(exit_) <= 0:
                    continue
                rr = (float(exit_) - p) / (p * variant.stop_pct)
                if rr < variant.min_rr:
                    continue
            rows.append({**sig, "variant": variant.name})

    return pd.DataFrame(rows)


def compare_variants(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    variants: tuple[SignalVariant, ...] = DEFAULT_VARIANTS,
    *,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Run every variant over the same data; one summary row per variant.

    Columns: variant, n_signals, n_closed, win_rate, avg_return_pct,
    median_return_pct, avg_days_held, plus the walk-forward split
    (n/avg for train = first half of the date range, test = second).
    """
    prices = _prices_frame(price_history)
    if prices.empty:
        return pd.DataFrame()
    d0, d1 = prices.index.min(), prices.index.max()
    midpoint = (d0 + (d1 - d0) / 2)

    out: list[dict] = []
    for v in variants:
        sigs = run_variant(watchlist, price_history, v, as_of=as_of)
        if sigs.empty:
            out.append({
                "variant": v.name, "n_signals": 0, "n_closed": 0,
                "win_rate": np.nan, "avg_return_pct": np.nan,
                "median_return_pct": np.nan, "avg_days_held": np.nan,
                "n_train": 0, "avg_train_pct": np.nan,
                "n_test": 0, "avg_test_pct": np.nan,
            })
            continue
        closed = sigs[~sigs["open"]]
        sig_dates = pd.to_datetime(sigs["signal_date"])
        train = sigs[sig_dates <= midpoint]
        test = sigs[sig_dates > midpoint]
        out.append({
            "variant": v.name,
            "n_signals": len(sigs),
            "n_closed": len(closed),
            "win_rate": (
                float((closed["return_pct"] > 0).mean()) if len(closed) else np.nan
            ),
            "avg_return_pct": (
                float(closed["return_pct"].mean()) if len(closed) else np.nan
            ),
            "median_return_pct": (
                float(closed["return_pct"].median()) if len(closed) else np.nan
            ),
            "avg_days_held": (
                float(closed["days_held"].mean()) if len(closed) else np.nan
            ),
            "n_train": len(train),
            "avg_train_pct": (
                float(train["return_pct"].mean()) if len(train) else np.nan
            ),
            "n_test": len(test),
            "avg_test_pct": (
                float(test["return_pct"].mean()) if len(test) else np.nan
            ),
        })
    df = pd.DataFrame(out)
    return df.sort_values(
        "avg_return_pct", ascending=False, na_position="last",
    ).reset_index(drop=True)
