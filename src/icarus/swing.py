"""Swing module: short-horizon trades targeting a fixed +5% move.

A different game from the position engine: the watchlist's core signal
waits months for 2.8× analyst targets; a swing trade wants 5% in days
and gives it back fast when wrong. Same codebase disciplines apply —
pure functions, close-only honesty, walk-forward evidence before
anything is called validated.

Strategy candidates (all close-only, all falsifiable in the Lab):

  dip     — pullback ≥ ``dip_pct`` off the rolling 20-session high while
            the 50-session trend is up: buy weakness inside strength.
  oversold— RSI(14) below 30: buy panic, bet on reversion.
  breakout— close above the prior 20-session high in an uptrend: buy
            strength, bet on continuation.
  control — every uptrend session (cooldown-thinned): if a named
            strategy can't beat "just be long uptrends", it adds nothing.

Exit for every strategy: first of +``target_pct``, −``stop_pct``, or
``timeout_sessions`` — conservative stop-first tie-break on close data.

Cost honesty, surfaced everywhere: a 5% target pays ~20× less per trade
than the position engine's winners, so spread + slippage are a huge
fraction of the edge. Liquidity is therefore a hard gate for LIVE
candidates (min average dollar volume), and reported returns include a
configurable round-trip cost haircut. Close-only replays also fill at
the close AFTER the signal condition — no same-bar fills.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_TARGET_PCT = 5.0
DEFAULT_STOP_PCT = 3.0
DEFAULT_TIMEOUT_SESSIONS = 10
DEFAULT_COOLDOWN_SESSIONS = 10
DEFAULT_COST_PCT = 0.5          # round-trip spread+slippage haircut
MIN_DOLLAR_VOLUME = 1_000_000.0  # live-candidate liquidity floor (per day)
TREND_WINDOW = 50
DIP_LOOKBACK = 20
BREAKOUT_LOOKBACK = 20
RSI_WINDOW = 14
RSI_OVERSOLD = 30.0


@dataclass(frozen=True)
class SwingVariant:
    name: str
    strategy: str                    # 'dip' | 'oversold' | 'breakout' | 'control'
    target_pct: float = DEFAULT_TARGET_PCT
    stop_pct: float = DEFAULT_STOP_PCT
    timeout_sessions: int = DEFAULT_TIMEOUT_SESSIONS
    dip_pct: float = 5.0             # 'dip' only


DEFAULT_SWING_VARIANTS: tuple[SwingVariant, ...] = (
    SwingVariant("control: any uptrend session", "control"),
    SwingVariant("dip 5% in uptrend", "dip"),
    SwingVariant("dip 8% in uptrend", "dip", dip_pct=8.0),
    SwingVariant("oversold RSI<30", "oversold"),
    SwingVariant("breakout 20d high", "breakout"),
    SwingVariant("dip 5%, wider 5% stop", "dip", stop_pct=5.0),
    SwingVariant("dip 5%, 20-session patience", "dip", timeout_sessions=20),
)


def rsi(series: pd.Series, window: int = RSI_WINDOW) -> pd.Series:
    """Wilder's RSI on closes."""
    s = series.dropna().astype(float)
    if len(s) < window + 1:
        return pd.Series(dtype=float)
    delta = s.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1.0 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1.0 / window, adjust=False).mean()
    rs = gain / loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.fillna(100.0)


def _uptrend(s: pd.Series) -> pd.Series:
    sma = s.rolling(TREND_WINDOW).mean()
    return (s > sma) & (sma.diff(10) > 0)


def swing_setups(series: pd.Series, variant: SwingVariant) -> pd.Series:
    """Boolean series: the setup CONDITION holds on this session's close.

    Fills happen at the NEXT session's close (see ``replay_swing``), so a
    condition may use the current close without look-ahead.
    """
    s = series.dropna().astype(float)
    if len(s) < TREND_WINDOW + 15:
        return pd.Series(dtype=bool)
    up = _uptrend(s)
    if variant.strategy == "control":
        cond = up
    elif variant.strategy == "dip":
        high20 = s.rolling(DIP_LOOKBACK).max()
        drawdown = (high20 - s) / high20 * 100.0
        cond = up & (drawdown >= variant.dip_pct)
    elif variant.strategy == "oversold":
        r = rsi(s)
        cond = r.reindex(s.index) < RSI_OVERSOLD
    elif variant.strategy == "breakout":
        prior_high = s.rolling(BREAKOUT_LOOKBACK).max().shift(1)
        cond = up & (s >= prior_high)
    else:
        raise ValueError(f"unknown swing strategy: {variant.strategy}")
    return cond.fillna(False)


def replay_swing(
    ticker: str,
    series: pd.Series,
    variant: SwingVariant,
    *,
    cooldown_sessions: int = DEFAULT_COOLDOWN_SESSIONS,
    cost_pct: float = DEFAULT_COST_PCT,
    as_of: date | None = None,
) -> list[dict]:
    """Replay one variant over one ticker. Entry at the close AFTER the
    setup session; exit at first of target / stop / timeout; returns are
    net of ``cost_pct`` round-trip."""
    s = series.dropna().astype(float)
    cond = swing_setups(s, variant)
    if cond.empty:
        return []
    idx = s.index
    trades: list[dict] = []
    n = len(s)
    positions = np.flatnonzero(cond.to_numpy())
    last_exit_i = -1
    for ci in positions:
        entry_i = ci + 1                    # fill on the NEXT close
        if entry_i >= n or entry_i <= last_exit_i:
            continue
        if trades and entry_i - trades[-1]["entry_i"] < cooldown_sessions:
            continue
        entry = float(s.iloc[entry_i])
        if entry <= 0:
            continue
        target = entry * (1.0 + variant.target_pct / 100.0)
        stop = entry * (1.0 - variant.stop_pct / 100.0)
        exit_i, exit_px, reason = None, None, None
        for j in range(entry_i + 1, min(entry_i + 1 + variant.timeout_sessions, n)):
            px = float(s.iloc[j])
            if px <= stop:                  # conservative: stop first, and a
                exit_i, exit_px, reason = j, px, "stop"   # gap through the
                break                                     # stop fills at the
            if px >= target:                              # worse gap price
                # Conservative fill: a resting limit at the target fills at
                # the target (or better on a gap-up open — not credited).
                # Recording the gap CLOSE would inflate the mean with moves
                # nobody's limit order captures.
                exit_i, exit_px, reason = j, target, "target"
                break
        if reason is None:
            j = min(entry_i + variant.timeout_sessions, n - 1)
            if j > entry_i:
                exit_i, exit_px, reason = j, float(s.iloc[j]), "timeout"
            else:
                exit_i, exit_px, reason = n - 1, float(s.iloc[n - 1]), "open"
        gross = (exit_px - entry) / entry * 100.0
        d_entry = idx[entry_i]
        d_exit = idx[exit_i]
        trades.append({
            "ticker": ticker,
            "entry_i": entry_i,
            "signal_date": (d_entry.date() if hasattr(d_entry, "date") else d_entry),
            "entry_price": entry,
            "exit_price": exit_px,
            "close_reason": reason,
            "return_pct": gross - cost_pct,
            "days_held": int((d_exit - d_entry).days),
            "open": reason == "open",
        })
        last_exit_i = exit_i
    for tr in trades:
        tr.pop("entry_i", None)
    return trades


def compare_swing_variants(
    price_history: dict[str, pd.Series],
    variants: tuple[SwingVariant, ...] = DEFAULT_SWING_VARIANTS,
    *,
    cost_pct: float = DEFAULT_COST_PCT,
    as_of: date | None = None,
) -> pd.DataFrame:
    """One summary row per swing variant, walk-forward split included.

    Same evidence bar as every Lab: beat the control in BOTH halves at a
    real sample size before believing a strategy.
    """
    frames: dict[str, pd.Series] = {
        t: s.dropna() for t, s in price_history.items()
        if s is not None and not s.dropna().empty
    }
    if not frames:
        return pd.DataFrame()
    all_idx = pd.DatetimeIndex(
        sorted({ts for s in frames.values() for ts in s.index})
    )
    midpoint = all_idx.min() + (all_idx.max() - all_idx.min()) / 2

    out: list[dict] = []
    for v in variants:
        rows: list[dict] = []
        for t, s in frames.items():
            rows.extend(replay_swing(t, s, v, cost_pct=cost_pct, as_of=as_of))
        df = pd.DataFrame(rows)
        if df.empty:
            out.append({
                "variant": v.name, "n_signals": 0, "n_closed": 0,
                "win_rate": np.nan, "avg_return_pct": np.nan,
                "median_return_pct": np.nan, "avg_days_held": np.nan,
                "n_train": 0, "avg_train_pct": np.nan,
                "n_test": 0, "avg_test_pct": np.nan,
            })
            continue
        closed = df[~df["open"]]
        sd = pd.to_datetime(df["signal_date"])
        train, test = df[sd <= midpoint], df[sd > midpoint]
        out.append({
            "variant": v.name,
            "n_signals": len(df),
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
    return pd.DataFrame(out)


def todays_swing_candidates(
    price_history: dict[str, pd.Series],
    volume_history: dict[str, pd.Series] | None,
    variant: SwingVariant,
    *,
    min_dollar_volume: float = MIN_DOLLAR_VOLUME,
    cost_pct: float = DEFAULT_COST_PCT,
) -> pd.DataFrame:
    """Tickers whose LATEST session satisfies the setup, liquidity-gated.

    Returns entry (next close ≈ current), target, stop, plus the average
    dollar volume that justified inclusion. Liquidity is a HARD gate:
    without it a 5% target is a donation to the market maker's spread.
    """
    rows: list[dict] = []
    for t, s in price_history.items():
        s = s.dropna() if s is not None else pd.Series(dtype=float)
        if s.empty:
            continue
        cond = swing_setups(s, variant)
        if cond.empty or not bool(cond.iloc[-1]):
            continue
        px = float(s.iloc[-1])
        adv = np.nan
        if volume_history is not None:
            vs = volume_history.get(t)
            if vs is not None and not vs.dropna().empty:
                adv = float(vs.dropna().tail(20).mean()) * px
        if not np.isfinite(adv) or adv < min_dollar_volume:
            continue
        rows.append({
            "ticker": t,
            "live_price": px,
            "target_price": px * (1.0 + variant.target_pct / 100.0),
            "stop_price": px * (1.0 - variant.stop_pct / 100.0),
            "target_pct": variant.target_pct,
            "stop_pct": variant.stop_pct,
            "timeout_sessions": variant.timeout_sessions,
            "avg_dollar_volume": adv,
            "est_cost_pct": cost_pct,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("avg_dollar_volume", ascending=False).reset_index(drop=True)
