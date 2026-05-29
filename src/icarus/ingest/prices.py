"""Price fetcher.

Prefers yfinance when installed and network is reachable. Falls back to a
deterministic synthetic price tape so the pipeline runs in any sandbox.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from .synthetic import synthetic_prices

log = logging.getLogger(__name__)


def _cache_path(cache_dir: Path, key: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"prices-{key}.parquet"


def _fetch_yfinance(
    tickers: list[str],
    start: date,
    end: date,
    benchmark: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series] | None:
    try:
        import yfinance as yf
    except ImportError:
        log.info("yfinance not installed; using synthetic prices")
        return None

    universe = sorted(set(tickers) | {benchmark})
    try:
        raw = yf.download(
            tickers=universe,
            start=start.isoformat(),
            end=end.isoformat(),
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception as exc:
        log.warning("yfinance download failed (%s); using synthetic prices", exc)
        return None

    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" not in raw.columns.get_level_values(0):
            return None
        prices = raw["Close"].copy()
    else:
        prices = raw.to_frame(name=universe[0]) if len(universe) == 1 else raw

    prices = prices.dropna(how="all").ffill().dropna(how="any", axis=1)
    if benchmark not in prices.columns:
        log.warning("Benchmark %s missing from price data; using synthetic", benchmark)
        return None
    returns = prices.pct_change().dropna(how="all")
    benchmark_returns = returns[benchmark].copy()
    return prices, returns, benchmark_returns


def fetch_prices(
    tickers: list[str],
    start: date,
    end: date,
    *,
    cache_dir: Path | str = "data/cache",
    benchmark: str = "SPY",
    use_cache: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Return ``(prices, returns, benchmark_returns)``.

    Cached as a single parquet keyed by tickers + window.
    """
    cache_dir = Path(cache_dir)
    key = f"{benchmark}-{start}-{end}-{len(tickers)}-{abs(hash(tuple(sorted(set(tickers))))) % 10_000_000}"
    cache_file = _cache_path(cache_dir, key)
    if use_cache and cache_file.exists():
        try:
            prices = pd.read_parquet(cache_file)
            returns = prices.pct_change().dropna(how="all")
            benchmark_returns = returns[benchmark]
            return prices, returns, benchmark_returns
        except Exception as exc:
            log.warning("Cache read failed (%s); refetching", exc)

    result = _fetch_yfinance(tickers, start, end, benchmark)
    if result is None:
        result = synthetic_prices(tickers, start, end, benchmark=benchmark)

    prices, returns, benchmark_returns = result
    try:
        prices.to_parquet(cache_file)
    except Exception as exc:
        log.debug("Could not cache prices to %s (%s)", cache_file, exc)
    return prices, returns, benchmark_returns
