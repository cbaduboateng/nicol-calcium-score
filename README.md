# congress-signal

Identify asymmetric-payoff opportunities in congressional and executive-branch
trading disclosures. Re-ranks the obvious mega-cap cluster down and surfaces
OTM long-dated options, small/mid-cap federal contractors, and
bounded-downside names with a positive catalyst residual.

## Install

```bash
pip install -e .
```

## Demo (offline, no API keys)

```bash
csig ingest --source synthetic
csig score
csig rank --top 10
csig backtest --start 2024-01-01 --end 2024-12-31 --holding-period 60
```

## Real data

Set `QUIVER_API_KEY` for the QuiverQuant adapter, or run
`csig ingest --source house_ptr --year 2024` to pull from the House Clerk
archive.

See `CLAUDE.md` for the full architecture.
