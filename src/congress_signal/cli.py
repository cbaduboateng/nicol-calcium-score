"""Command-line interface for congress-signal.

Entry point: `csig` (declared in pyproject.toml).

Commands:
    csig ingest --source {quiver,house_ptr} --days 90
    csig prices --since 2020-01-01
    csig score --output data/processed/signals.parquet
    csig rank --top 20
    csig backtest --start 2018-01-01 --end 2024-12-31 --holding-period 90
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import load_config

console = Console()


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def _clean_record(record: dict) -> dict:
    """Strip parquet NaN sentinels so pydantic can rehydrate Optional fields.

    Also drops computed fields that pydantic would otherwise reject as inputs.
    """
    computed = {"amount_midpoint_usd", "disclosure_lag_days", "days_to_expiry", "is_option"}
    out = {}
    for k, v in record.items():
        if k in computed:
            continue
        if v is None:
            out[k] = None
            continue
        try:
            import math
            if isinstance(v, float) and math.isnan(v):
                out[k] = None
                continue
        except TypeError:
            pass
        out[k] = v
    return out


@click.group()
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--log-level", default="INFO")
@click.pass_context
def main(ctx: click.Context, config_path: str | None, log_level: str) -> None:
    """congress-signal: asymmetric-winner identification from disclosures."""
    _setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


@main.command()
@click.option("--source", type=click.Choice(["quiver", "house_ptr", "synthetic"]), default="quiver")
@click.option("--days", type=int, default=90)
@click.option("--year", type=int, default=None, help="House PTR only: which year to fetch.")
@click.option("--output", type=click.Path(), default="data/processed/trades.parquet")
@click.option("--actors-output", type=click.Path(), default="data/processed/actors.parquet",
              help="Where to write synthetic actors (only used by --source synthetic).")
@click.pass_context
def ingest(
    ctx: click.Context,
    source: str,
    days: int,
    year: int | None,
    output: str,
    actors_output: str,
) -> None:
    """Fetch trades from the chosen source and persist as Parquet."""
    import pandas as pd

    cfg = ctx.obj["config"]
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    actors: list = []

    if source == "quiver":
        from .ingest.quiver import QuiverClient
        client = QuiverClient()
        since = date.today() - timedelta(days=days)
        trades = client.congress_trades(since=since)
        console.print(f"[green]Fetched {len(trades)} trades from Quiver since {since}[/]")
    elif source == "house_ptr":
        from .ingest.house_ptr import ingest_year
        cache_dir = Path(cfg["paths"]["cache"]) / "house"
        target_year = year or date.today().year
        trades = list(ingest_year(target_year, cache_dir))
        console.print(f"[green]Extracted {len(trades)} trades from House PTRs for {target_year}[/]")
    elif source == "synthetic":
        from .ingest.synthetic import synthetic_actors, synthetic_trades
        # `--days` controls how far back the synthetic tape spans; we also bump
        # n_trades proportionally so longer windows have enough events to score.
        n = max(80, days // 2)
        trades = synthetic_trades(end=date.today(), span_days=days, n_trades=n)
        actors = synthetic_actors()
        console.print(
            f"[green]Generated {len(trades)} synthetic trades and {len(actors)} actors "
            f"over {days} days[/]"
        )
    else:
        raise click.UsageError(f"Unknown source: {source}")

    df = pd.DataFrame([t.model_dump() for t in trades])
    df.to_parquet(out_path)
    console.print(f"[green]Wrote {len(df)} rows to {out_path}[/]")

    if actors:
        actors_path = Path(actors_output)
        actors_path.parent.mkdir(parents=True, exist_ok=True)
        actors_df = pd.DataFrame([a.model_dump() for a in actors])
        actors_df.to_parquet(actors_path)
        console.print(f"[green]Wrote {len(actors_df)} actors to {actors_path}[/]")


@main.command()
@click.option("--since", "since_str", type=str, default="2020-01-01")
@click.option("--trades", "trades_path", type=click.Path(exists=True),
              default="data/processed/trades.parquet")
@click.pass_context
def prices(ctx: click.Context, since_str: str, trades_path: str) -> None:
    """Fetch and cache price history for all tickers seen in the trades file."""
    import pandas as pd
    from .ingest.prices import fetch_prices

    cfg = ctx.obj["config"]
    since_dt = datetime.strptime(since_str, "%Y-%m-%d").date()
    df = pd.read_parquet(trades_path)
    tickers = sorted(set(df["ticker"].dropna().str.upper()))
    cache_dir = Path(cfg["paths"]["cache"])
    p, r, bench = fetch_prices(
        tickers, since_dt, date.today(), cache_dir=cache_dir,
        benchmark=cfg["backtest"]["benchmark"],
    )
    console.print(f"[green]Cached prices for {p.shape[1]} tickers over {p.shape[0]} trading days[/]")


@main.command()
@click.option("--trades", "trades_path", type=click.Path(exists=True),
              default="data/processed/trades.parquet")
@click.option("--actors", "actors_path", type=click.Path(),
              default="data/processed/actors.parquet")
@click.option("--output", type=click.Path(), default="data/processed/candidates.parquet")
@click.pass_context
def score(ctx: click.Context, trades_path: str, actors_path: str, output: str) -> None:
    """Run the full scoring pipeline and persist candidates."""
    import pandas as pd
    from .pipeline import run_full_pipeline
    from .schema import Actor, Trade

    cfg = ctx.obj["config"]

    trade_records = pd.read_parquet(trades_path).to_dict(orient="records")
    trades = [Trade(**_clean_record(r)) for r in trade_records]

    if Path(actors_path).exists():
        actor_records = pd.read_parquet(actors_path).to_dict(orient="records")
        actors = [Actor(**_clean_record(r)) for r in actor_records]
    else:
        console.print(
            "[yellow]No actors file found; deriving minimal actors from trades. "
            "Build ingest/committees.py to populate properly.[/]"
        )
        seen = {t.actor_id for t in trades}
        actors = [
            Actor(actor_id=a, name=a, chamber="house")  # type: ignore[arg-type]
            for a in seen
        ]

    result = run_full_pipeline(cfg, trades, actors)

    cand_df = pd.DataFrame([c.model_dump() for c in result.candidates])
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    cand_df.to_parquet(output)
    console.print(f"[green]Wrote {len(cand_df)} candidates to {output}[/]")


@main.command()
@click.option("--candidates", "cand_path", type=click.Path(exists=True),
              default="data/processed/candidates.parquet")
@click.option("--top", type=int, default=20)
def rank(cand_path: str, top: int) -> None:
    """Show the top-N asymmetric candidates in a console table."""
    import pandas as pd
    df = pd.read_parquet(cand_path).sort_values("asymmetry_score", ascending=False).head(top)
    table = Table(title=f"Top {top} asymmetric candidates")
    table.add_column("Ticker", style="bold cyan")
    table.add_column("Actor")
    table.add_column("Score", justify="right")
    table.add_column("Signals")
    table.add_column("Cluster", justify="right")
    table.add_column("Catalyst pending")
    table.add_column("Rationale", overflow="fold")
    for _, row in df.iterrows():
        signals = row["signal_types"]
        if isinstance(signals, list):
            signals = ", ".join(signals)
        elif hasattr(signals, "tolist"):
            signals = ", ".join(signals.tolist())
        table.add_row(
            str(row["ticker"]),
            str(row["actor_id"])[:30],
            f"{row['asymmetry_score']:.2f}",
            str(signals),
            str(row["cluster_size"]),
            "✓" if row["catalyst_pending"] else "✗",
            str(row["rationale"])[:80],
        )
    console.print(table)


@main.command()
@click.option("--start", type=str, default="2020-01-01")
@click.option("--end", type=str, default=None)
@click.option("--holding-period", type=int, default=90)
@click.option("--trades", "trades_path", type=click.Path(exists=True),
              default="data/processed/trades.parquet")
@click.option("--candidates", "cand_path", type=click.Path(exists=True),
              default="data/processed/candidates.parquet")
@click.option("--filter-stack", "filter_stack", type=str,
              default="actor_quality,trade_signal,clustering",
              help="Comma-separated filter labels (metadata only, recorded in notes).")
@click.pass_context
def backtest(
    ctx: click.Context,
    start: str,
    end: str | None,
    holding_period: int,
    trades_path: str,
    cand_path: str,
    filter_stack: str,
) -> None:
    """Run the event-study backtest on flagged candidates."""
    import pandas as pd
    from .backtest.engine import run_backtest
    from .ingest.prices import fetch_prices
    from .schema import AsymmetricCandidate, Trade

    cfg = ctx.obj["config"]
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()

    trades = [Trade(**_clean_record(r)) for r in pd.read_parquet(trades_path).to_dict(orient="records")]
    candidates = [
        AsymmetricCandidate(**_clean_record(r))
        for r in pd.read_parquet(cand_path).to_dict(orient="records")
    ]

    tickers = sorted({t.ticker for t in trades})
    cache_dir = Path(cfg["paths"]["cache"])
    _, returns, bench = fetch_prices(
        tickers, start_d, end_d,
        cache_dir=cache_dir,
        benchmark=cfg["backtest"]["benchmark"],
    )

    result = run_backtest(
        trades, candidates, returns, bench,
        start=start_d, end=end_d,
        holding_period_days=holding_period,
        slippage_bps=cfg["backtest"]["slippage_bps"],
        bootstrap_iterations=cfg["backtest"]["bootstrap_iterations"],
    )
    payload = result.model_dump()
    payload["notes"] = f"filter_stack={filter_stack}; " + payload.get("notes", "")
    console.print_json(json.dumps(payload, default=str))


@main.command()
@click.option("--output", type=click.Path(), default="data/processed/actors.parquet")
@click.pass_context
def committees(ctx: click.Context, output: str) -> None:
    """Populate actors.parquet from unitedstates/congress-legislators."""
    import pandas as pd
    from .ingest.committees import load_committee_actors

    cfg = ctx.obj["config"]
    cache_dir = Path(cfg["paths"]["cache"])
    actors = load_committee_actors(cache_dir)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([a.model_dump() for a in actors]).to_parquet(out_path)
    console.print(f"[green]Wrote {len(actors)} actors to {out_path}[/]")


@main.command()
@click.option("--horizon-days", type=int, default=90)
@click.option("--output", type=click.Path(), default="data/processed/catalysts.parquet")
def catalysts(horizon_days: int, output: str) -> None:
    """Build the forward catalyst calendar."""
    import pandas as pd
    from .scoring.catalyst import build_calendar

    events = build_calendar(horizon_days=horizon_days)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([{
        "event_date": e.event_date,
        "ticker": e.ticker,
        "category": e.category,
        "source": e.source,
        "rationale": e.rationale,
    } for e in events])
    df.to_parquet(out_path)
    console.print(f"[green]Wrote {len(df)} catalyst events to {out_path}[/]")


@main.command()
@click.option("--start", type=str, default="2018-01-01",
              help="Backtest start date (inclusive).")
@click.option("--end", type=str, default=None,
              help="Backtest end date (inclusive). Defaults to today.")
@click.option("--top-n", type=int, default=50,
              help="Top-N candidates kept by asymmetry_score.")
@click.option("--slippage-bps", type=float, default=25.0)
@click.option("--output-dir", type=click.Path(), default="docs")
def phase0(start: str, end: str | None, top_n: int,
           slippage_bps: float, output_dir: str) -> None:
    """Run the Phase 0 real-data validation. Requires QUIVER_API_KEY."""
    from datetime import date as _date
    from .validation import run_phase0_validation

    start_d = _date.fromisoformat(start)
    end_d = _date.fromisoformat(end) if end else None
    summary = run_phase0_validation(
        start=start_d, end=end_d,
        top_n=top_n, slippage_bps=slippage_bps,
        output_dir=output_dir,
    )
    p = summary["primary"]
    console.print(
        f"[bold]Verdict:[/] [{'green' if summary['verdict'] == 'PROCEED' else 'red'}]"
        f"{summary['verdict']}[/]\n"
        f"Primary horizon ({p.horizon_days}d): delta CAR = {p.delta_car * 100:+.2f}%, "
        f"95% CI [{p.delta_ci_lower * 100:+.2f}%, {p.delta_ci_upper * 100:+.2f}%]\n"
        f"Filtered n={p.n_filtered}, Baseline n={p.n_baseline}\n"
        f"Report: {summary['report_path']}"
    )


if __name__ == "__main__":
    main(obj={})
