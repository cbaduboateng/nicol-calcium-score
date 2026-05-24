# congress-signal

Asymmetric-winner identification from congressional and executive-branch
trading disclosures.

## Layout

```
src/congress_signal/
  schema.py              Pydantic v2 data contracts (the public interface)
  config.py              YAML + env-override config loader
  cli.py                 `csig` Click entry point
  ingest/
    synthetic.py         deterministic offline generator (fallback for every adapter)
    quiver.py            QuiverQuant API adapter
    house_ptr.py         House Clerk PTR archive adapter
    prices.py            yfinance + cache, falls back to synthetic prices
  scoring/
    actor.py             actor-quality composite score
    signal.py            per-trade signal-richness score
    cluster.py           multi-actor ticker clustering
    residual.py          catalyst-already-fired filter
  filters/
    asymmetric.py        re-rank toward OTM options, federal contractors, etc.
  backtest/
    engine.py            event-study CAR + portfolio Sharpe + bootstrap CI
  pipeline.py            orchestrator: returns ranked AsymmetricCandidates
tests/                   pytest suite
config/config.yaml       defaults; override via CONGRESS_SIGNAL_<DOTTED__KEY>
```

## Quick demo (no API keys, no network)

```bash
pip install -e .
csig ingest --source synthetic
csig score
csig rank --top 10
csig backtest --start 2024-01-01 --end 2024-12-31 --holding-period 60
```

The synthetic generator plants a 3-actor LMT defence cluster and an OTM
long-dated PLTR call so every asymmetric-filter branch fires and the backtest
produces non-zero CARs.

## Real data path

```bash
export QUIVER_API_KEY=...
csig ingest --source quiver --days 180
csig prices --since 2020-01-01
csig score
csig rank --top 20
csig backtest --start 2020-01-01 --holding-period 90
```

Any adapter falls back to synthetic data on failure (logged at WARNING) so the
pipeline never breaks mid-run.

## Architecture notes

- Every typed object in `schema.py` is `frozen=True`. Pass them around freely.
- Computed fields (`amount_midpoint_usd`, `disclosure_lag_days`, `is_option`,
  `days_to_expiry`) round-trip through parquet via `to_dict` / `from_records`.
- The asymmetric filter is a re-weighting on top of upstream layers, not a
  replacement. The mega-cap demotion is deliberate.
- `config.yaml` is the single source of truth. The CLI never hard-codes
  weights or thresholds.
- Synthetic ingest is the test harness *and* the offline demo. Keep it
  deterministic.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The default suite exercises the full pipeline on synthetic data and asserts
the planted LMT cluster and PLTR call surface in the top candidates.
