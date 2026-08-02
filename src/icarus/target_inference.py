"""Reverse-engineer the analyst's target-setting pattern and apply it.

The watchlist has ~346 analyst buy targets and ~127 sell targets across
878 tickers. This module answers: *what rule generates those targets?*
— then applies the learned rule to fill the blanks.

Learning (``learn_target_pattern``):
  - Entry rule: for every row with an analyst entry AND price history,
    compute the entry as a ratio of three candidate anchors — the live
    price, the 52-week low, and the 52-week high. The anchor whose ratio
    distribution is TIGHTEST (lowest IQR/median dispersion) is the one
    the analyst most plausibly used; its median ratio becomes the rule.
  - Exit rule: median of exit/entry across rows with both (empirically
    ~2.5x, mode 2x — a "double-your-money-plus" convention). Absurd
    multiples (exit below entry, >20x) are excluded as mis-set rows.
  - Both rules get per-theme medians when a theme has enough samples,
    falling back to the global median otherwise.

Applying (``derive_targets``):
  - Missing entry  -> anchor_value x learned ratio, rounded to 3 s.f.
  - Missing exit   -> entry (analyst or derived) x learned multiple.
  - Analyst values are NEVER overwritten; provenance is recorded in
    ``entry_source`` / ``exit_source`` ("analyst" | "derived").

Honesty caveats, surfaced in the UI:
  - The entry ratios are computed against TODAY'S prices, but the
    analyst set their targets months ago at different price levels —
    price drift contaminates the learned ratio. The 52-week anchors
    are more drift-resistant than the live price, which is exactly why
    anchor selection is empirical rather than assumed.
  - Derived targets are for SCREENING only. The track record and the
    runbook backtest deliberately keep analyst-only targets — grading
    performance on targets derived from current prices would be
    circular (every stock would sit conveniently near its own entry).
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from .watchlist_alerts import map_theme

log = logging.getLogger(__name__)


MIN_LEARN_SAMPLES = 20     # below this, refuse to learn (too noisy)
MIN_THEME_SAMPLES = 8      # per-theme rule needs at least this many
MULT_MIN, MULT_MAX = 1.05, 20.0   # sane exit/entry multiples
RATIO_MIN, RATIO_MAX = 0.05, 3.0  # sane entry/anchor ratios
DEFAULT_EXIT_MULTIPLE = 2.0       # fallback when no exits to learn from


def _round_sig(x: float, sig: int = 3) -> float:
    """Round to significant figures so derived targets look like the
    analyst's hand-set round numbers, not float noise."""
    if x == 0 or not np.isfinite(x):
        return x
    return round(x, -int(math.floor(math.log10(abs(x)))) + (sig - 1))


def _anchors(hist: pd.Series) -> dict[str, float] | None:
    s = hist.dropna()
    if len(s) < 30:
        return None
    live = float(s.iloc[-1])
    low52 = float(s.min())
    high52 = float(s.max())
    if live <= 0 or low52 <= 0 or high52 <= 0:
        return None
    return {"live": live, "low52": low52, "high52": high52}


def learn_target_pattern(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    *,
    min_samples: int = MIN_LEARN_SAMPLES,
    min_theme_samples: int = MIN_THEME_SAMPLES,
) -> dict | None:
    """Learn the analyst's entry-anchor rule and exit-multiple rule.

    Returns None when there aren't enough analyst targets with price
    history to learn from. Otherwise a dict:
      anchor            'live' | 'low52' | 'high52' (tightest dispersion)
      entry_ratio       global median entry / anchor
      theme_entry_ratios  {theme: median} for themes with enough samples
      exit_multiple     global median exit / entry
      theme_exit_multiples {theme: median}
      dispersions       {anchor: IQR/median} for transparency
      n_entry, n_exit   sample sizes
    """
    if watchlist is None or watchlist.empty:
        return None

    ratio_rows: list[dict] = []
    mult_rows: list[dict] = []
    for _, row in watchlist.iterrows():
        ticker = str(row.get("ticker") or "").upper()
        entry = row.get("target_entry")
        exit_ = row.get("target_exit")
        theme = map_theme(row.get("description"))

        has_entry = pd.notna(entry) and float(entry) > 0
        if has_entry and pd.notna(exit_) and float(exit_) > 0:
            mult = float(exit_) / float(entry)
            if MULT_MIN <= mult <= MULT_MAX:
                mult_rows.append({"theme": theme, "mult": mult})

        if not has_entry:
            continue
        hist = price_history.get(ticker)
        if hist is None or len(hist) == 0:
            continue
        anch = _anchors(hist)
        if anch is None:
            continue
        rec: dict = {"theme": theme}
        ok = False
        for name, val in anch.items():
            r = float(entry) / val
            if RATIO_MIN <= r <= RATIO_MAX:
                rec[name] = r
                ok = True
        if ok:
            ratio_rows.append(rec)

    if len(ratio_rows) < min_samples:
        log.info(
            "target_inference: only %d usable analyst entries (<%d); not learning",
            len(ratio_rows), min_samples,
        )
        return None

    ratios = pd.DataFrame(ratio_rows)
    dispersions: dict[str, float] = {}
    for name in ("live", "low52", "high52"):
        if name not in ratios.columns:
            continue
        col = ratios[name].dropna()
        if len(col) < min_samples:
            continue
        med = float(col.median())
        iqr = float(col.quantile(0.75) - col.quantile(0.25))
        if med > 0:
            dispersions[name] = iqr / med
    if not dispersions:
        return None
    anchor = min(dispersions, key=dispersions.get)

    anchor_col = ratios[["theme", anchor]].dropna()
    entry_ratio = float(anchor_col[anchor].median())
    theme_entry_ratios = {
        t: float(g[anchor].median())
        for t, g in anchor_col.groupby("theme")
        if len(g) >= min_theme_samples
    }

    if mult_rows:
        mults = pd.DataFrame(mult_rows)
        exit_multiple = float(mults["mult"].median())
        theme_exit_multiples = {
            t: float(g["mult"].median())
            for t, g in mults.groupby("theme")
            if len(g) >= min_theme_samples
        }
    else:
        exit_multiple = DEFAULT_EXIT_MULTIPLE
        theme_exit_multiples = {}

    return {
        "anchor": anchor,
        "entry_ratio": entry_ratio,
        "theme_entry_ratios": theme_entry_ratios,
        "exit_multiple": exit_multiple,
        "theme_exit_multiples": theme_exit_multiples,
        "dispersions": dispersions,
        "n_entry": len(ratio_rows),
        "n_exit": len(mult_rows),
    }


def derive_targets(
    watchlist: pd.DataFrame,
    price_history: dict[str, pd.Series],
    pattern: dict,
) -> pd.DataFrame:
    """Fill missing targets using the learned pattern.

    Returns a copy of the watchlist with target_entry / target_exit
    filled where derivable, plus ``entry_source`` / ``exit_source``
    columns ("analyst" | "derived" | None). Analyst values are never
    modified.
    """
    out = watchlist.copy()
    out["entry_source"] = np.where(
        out["target_entry"].notna() & (out["target_entry"] > 0), "analyst", None,
    )
    out["exit_source"] = np.where(
        out["target_exit"].notna() & (out["target_exit"] > 0), "analyst", None,
    )

    anchor_name = pattern["anchor"]
    n_derived_entries = 0
    n_derived_exits = 0

    for idx, row in out.iterrows():
        ticker = str(row.get("ticker") or "").upper()
        theme = map_theme(row.get("description"))

        entry = row.get("target_entry")
        has_entry = pd.notna(entry) and float(entry) > 0

        if not has_entry:
            hist = price_history.get(ticker)
            anch = _anchors(hist) if hist is not None and len(hist) else None
            if anch is not None:
                ratio = pattern["theme_entry_ratios"].get(
                    theme, pattern["entry_ratio"],
                )
                derived_entry = _round_sig(anch[anchor_name] * ratio)
                if np.isfinite(derived_entry) and derived_entry > 0:
                    out.at[idx, "target_entry"] = derived_entry
                    out.at[idx, "entry_source"] = "derived"
                    entry = derived_entry
                    has_entry = True
                    n_derived_entries += 1

        exit_ = row.get("target_exit")
        has_exit = pd.notna(exit_) and float(exit_) > 0
        if has_entry and not has_exit:
            mult = pattern["theme_exit_multiples"].get(
                theme, pattern["exit_multiple"],
            )
            derived_exit = _round_sig(float(entry) * mult)
            if np.isfinite(derived_exit) and derived_exit > 0:
                out.at[idx, "target_exit"] = derived_exit
                out.at[idx, "exit_source"] = "derived"
                n_derived_exits += 1

    log.info(
        "target_inference: derived %d entries and %d exits (anchor=%s, "
        "ratio=%.2f, multiple=%.2fx)",
        n_derived_entries, n_derived_exits,
        anchor_name, pattern["entry_ratio"], pattern["exit_multiple"],
    )
    return out


def derive_exits_from_entries(
    watchlist: pd.DataFrame,
    *,
    multiple: float | None = None,
) -> tuple[pd.DataFrame, float]:
    """Fill missing EXIT targets as analyst_entry × the analyst's own
    exit multiple. Returns (filled_watchlist, multiple_used).

    Deliberately price-free and therefore non-circular: the multiple is
    the median exit/entry across rows where the analyst set both
    (mis-set rows excluded via the usual clip), and each fill anchors on
    the analyst's OWN entry level — market prices are never consulted,
    so a backtest over the filled universe isn't grading targets derived
    from the prices it replays. This is what makes the expanded Signal
    Lab sample legitimate, unlike price-anchored entry derivation which
    stays quarantined to screening.
    """
    out = watchlist.copy()
    has_entry = out["target_entry"].notna() & (out["target_entry"] > 0)
    has_exit = out["target_exit"].notna() & (out["target_exit"] > 0)

    if multiple is None:
        both = out[has_entry & has_exit]
        mults = (both["target_exit"] / both["target_entry"])
        mults = mults[(mults >= MULT_MIN) & (mults <= MULT_MAX)]
        multiple = float(mults.median()) if len(mults) else DEFAULT_EXIT_MULTIPLE

    out["exit_source"] = np.where(has_exit, "analyst", None)
    fill = has_entry & ~has_exit
    out.loc[fill, "target_exit"] = (
        out.loc[fill, "target_entry"] * multiple
    ).apply(_round_sig)
    out.loc[fill, "exit_source"] = "derived"
    return out, multiple


def describe_pattern(pattern: dict) -> str:
    """One-line human-readable summary of the learned rule for the UI."""
    anchor_label = {
        "live": "the current price",
        "low52": "the 52-week low",
        "high52": "the 52-week high",
    }.get(pattern["anchor"], pattern["anchor"])
    return (
        f"Learned from {pattern['n_entry']} analyst entries / "
        f"{pattern['n_exit']} exits: buy target ≈ "
        f"{pattern['entry_ratio']:.0%} of {anchor_label}, "
        f"sell target ≈ {pattern['exit_multiple']:.1f}× the buy target"
        f" (dispersion per anchor: "
        + ", ".join(f"{k}={v:.2f}" for k, v in sorted(pattern["dispersions"].items()))
        + " — lowest wins)"
    )
