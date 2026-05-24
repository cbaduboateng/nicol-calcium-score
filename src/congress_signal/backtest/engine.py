"""Layer 7: Event-study backtest engine.

Validates the filter stack on historical data. The core method is a standard
event-study: for each flagged trade, compute cumulative abnormal return (CAR)
over the holding period relative to a benchmark, then aggregate.

We also support:
- Slippage adjustment (round-trip cost in bps)
- Bootstrap confidence intervals on the mean CAR
- Hit-rate (% of trades with positive CAR at the horizon)
- Sharpe of a long-only strategy holding the top-N flagged trades equally
  weighted, with monthly rebalancing
- Max drawdown of that strategy
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ..schema import AsymmetricCandidate, BacktestResult, Trade


@dataclass
class EventReturn:
    trade_id: str
    ticker: str
    entry_date: date
    exit_date: date
    stock_return: float
    benchmark_return: float
    car: float                 # cumulative abnormal return
    car_net_of_slippage: float


def _compound(series: pd.Series) -> float:
    return float((1 + series).prod() - 1)


def compute_event_returns(
    trades: list[Trade],
    price_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    *,
    holding_period_days: int,
    slippage_bps: float,
) -> list[EventReturn]:
    """Compute per-trade event returns over `holding_period_days` calendar days."""
    results: list[EventReturn] = []
    slippage = slippage_bps / 10_000.0
    for t in trades:
        if t.ticker not in price_returns.columns:
            continue
        entry = pd.Timestamp(t.transaction_date)
        exit_ = entry + pd.Timedelta(days=holding_period_days)
        if exit_ > price_returns.index[-1]:
            continue
        # Use the next available trading day if exact date is missing.
        idx = price_returns.index
        entry_pos = idx.searchsorted(entry)
        exit_pos = idx.searchsorted(exit_, side="right") - 1
        if entry_pos >= len(idx) or exit_pos < 0 or entry_pos > exit_pos:
            continue

        window = price_returns.iloc[entry_pos:exit_pos + 1][t.ticker].dropna()
        bench = benchmark_returns.iloc[entry_pos:exit_pos + 1].dropna()
        if len(window) < 5 or len(bench) < 5:
            continue

        stock_ret = _compound(window)
        bench_ret = _compound(bench)
        car = stock_ret - bench_ret
        car_net = car - slippage  # subtract round-trip cost

        results.append(EventReturn(
            trade_id=t.trade_id,
            ticker=t.ticker,
            entry_date=idx[entry_pos].date(),
            exit_date=idx[exit_pos].date(),
            stock_return=stock_ret,
            benchmark_return=bench_ret,
            car=car,
            car_net_of_slippage=car_net,
        ))
    return results


def bootstrap_mean_ci(
    values: np.ndarray,
    *,
    iterations: int = 1000,
    alpha: float = 0.05,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Percentile bootstrap CI on the mean."""
    if len(values) == 0:
        return float("nan"), float("nan")
    rng = rng or np.random.default_rng(42)
    n = len(values)
    means = np.empty(iterations)
    for i in range(iterations):
        sample = rng.choice(values, size=n, replace=True)
        means[i] = sample.mean()
    lower = float(np.quantile(means, alpha / 2))
    upper = float(np.quantile(means, 1 - alpha / 2))
    return lower, upper


def _max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min())


def _portfolio_sharpe(
    event_returns: list[EventReturn],
    price_returns: pd.DataFrame,
    holding_period_days: int,
    risk_free_rate: float = 0.0,
) -> tuple[float, float]:
    """Build a long-only equally-weighted portfolio holding each flagged trade
    for `holding_period_days`, daily-rebalanced. Returns (Sharpe, max drawdown).
    """
    if not event_returns:
        return float("nan"), float("nan")

    # For each calendar day, find all positions held that day and average their
    # daily returns.
    positions: dict[pd.Timestamp, list[str]] = {}
    for er in event_returns:
        entry = pd.Timestamp(er.entry_date)
        exit_ = pd.Timestamp(er.exit_date)
        for d in pd.date_range(entry, exit_, freq="B"):
            positions.setdefault(d, []).append(er.ticker)

    daily_returns = []
    for d, tickers in sorted(positions.items()):
        if d not in price_returns.index:
            continue
        rets = price_returns.loc[d, [t for t in tickers if t in price_returns.columns]]
        rets = rets.dropna()
        if len(rets) == 0:
            continue
        daily_returns.append((d, float(rets.mean())))

    if not daily_returns:
        return float("nan"), float("nan")

    s = pd.Series([r for _, r in daily_returns], index=[d for d, _ in daily_returns])
    excess = s - risk_free_rate / 252
    sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else float("nan")
    equity_curve = (1 + s).cumprod()
    mdd = _max_drawdown(equity_curve)
    return sharpe, mdd


def run_backtest(
    trades: list[Trade],
    candidates: list[AsymmetricCandidate],
    price_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    *,
    start: date,
    end: date,
    holding_period_days: int,
    slippage_bps: float = 25.0,
    bootstrap_iterations: int = 1000,
) -> BacktestResult:
    """Run the backtest on the trades that survived the filter stack.

    Args:
        trades: All raw trades (used to look up trade objects).
        candidates: Subset that survived the asymmetric filter.
        price_returns: DataFrame indexed by date, ticker columns, daily returns.
        benchmark_returns: Daily benchmark returns indexed by date.
        start, end: Date window for in-sample.
        holding_period_days: Calendar days from entry to exit.
        slippage_bps: Round-trip transaction cost in basis points.
    """
    trade_lookup = {t.trade_id: t for t in trades}
    in_window = [
        trade_lookup[c.trade_id]
        for c in candidates
        if c.trade_id in trade_lookup
        and start <= trade_lookup[c.trade_id].transaction_date <= end
    ]

    event_returns = compute_event_returns(
        in_window,
        price_returns,
        benchmark_returns,
        holding_period_days=holding_period_days,
        slippage_bps=slippage_bps,
    )

    if not event_returns:
        return BacktestResult(
            start=start, end=end,
            holding_period_days=holding_period_days,
            n_trades=0,
            mean_car=float("nan"), median_car=float("nan"),
            hit_rate=float("nan"), sharpe=float("nan"),
            max_drawdown=float("nan"),
            car_ci_lower=float("nan"), car_ci_upper=float("nan"),
            slippage_bps=slippage_bps,
            notes="no trades fell within the backtest window with usable price data",
        )

    cars = np.array([er.car_net_of_slippage for er in event_returns])
    hit_rate = float((cars > 0).mean())
    mean_car = float(cars.mean())
    median_car = float(np.median(cars))
    ci_lower, ci_upper = bootstrap_mean_ci(
        cars, iterations=bootstrap_iterations,
    )
    sharpe, mdd = _portfolio_sharpe(
        event_returns, price_returns, holding_period_days,
    )

    return BacktestResult(
        start=start, end=end,
        holding_period_days=holding_period_days,
        n_trades=len(event_returns),
        mean_car=mean_car,
        median_car=median_car,
        hit_rate=hit_rate,
        sharpe=sharpe,
        max_drawdown=mdd,
        car_ci_lower=ci_lower,
        car_ci_upper=ci_upper,
        slippage_bps=slippage_bps,
        notes=f"{len(event_returns)} of {len(in_window)} in-window candidates had usable price windows",
    )
