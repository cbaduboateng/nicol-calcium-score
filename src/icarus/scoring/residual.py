"""Residual-opportunity filter.

For each trade, look at the price move from the transaction date through today
(or the most recent close). If the move already exceeds the catalyst threshold,
the catalyst is considered "fired" — entering now offers little residual
asymmetry. Otherwise the catalyst is still pending and the trade is a live
opportunity.
"""

from __future__ import annotations

import pandas as pd

from ..schema import ResidualVerdict, Trade


def compute_residuals(
    trades: list[Trade],
    prices: pd.DataFrame,
    *,
    catalyst_threshold_pct: float = 5.0,
) -> list[ResidualVerdict]:
    """Compute per-trade residual verdicts. Trades on tickers absent from the
    price frame produce a neutral verdict (catalyst neither fired nor pending).
    """
    verdicts: list[ResidualVerdict] = []
    if prices.empty:
        return verdicts
    last_date = prices.index[-1]

    for t in trades:
        if t.ticker not in prices.columns:
            verdicts.append(ResidualVerdict(
                trade_id=t.trade_id,
                ticker=t.ticker,
                transaction_date=t.transaction_date,
                price_move_since_pct=0.0,
                catalyst_fired=False,
                residual_opportunity=False,
                rationale="no price data",
            ))
            continue

        ts = pd.Timestamp(t.transaction_date)
        idx = prices.index
        pos = idx.searchsorted(ts)
        if pos >= len(idx):
            verdicts.append(ResidualVerdict(
                trade_id=t.trade_id,
                ticker=t.ticker,
                transaction_date=t.transaction_date,
                price_move_since_pct=0.0,
                catalyst_fired=False,
                residual_opportunity=True,
                rationale="trade after last available price",
            ))
            continue

        entry_price = float(prices.iloc[pos][t.ticker])
        last_price = float(prices.iloc[-1][t.ticker])
        if entry_price <= 0:
            move = 0.0
        else:
            move = (last_price / entry_price - 1.0) * 100.0
        fired = abs(move) >= catalyst_threshold_pct
        verdicts.append(ResidualVerdict(
            trade_id=t.trade_id,
            ticker=t.ticker,
            transaction_date=t.transaction_date,
            price_move_since_pct=float(move),
            catalyst_fired=fired,
            residual_opportunity=not fired,
            rationale=(
                f"move {move:+.1f}% since entry vs threshold {catalyst_threshold_pct:.1f}% "
                f"(last close {last_date.date()})"
            ),
        ))
    return verdicts
