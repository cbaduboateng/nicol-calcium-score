# Instructions for Claude Code

This project is a scaffold for a congressional-trading signal-extraction
pipeline. The architecture and contracts are fixed; your job is to flesh out
the working implementations and run the validation backtest.

## What is already done

- Project structure and Pydantic schema (`schema.py`)
- Actor-quality scoring (`scoring/actor_quality.py`)
- Trade-signal classification (`scoring/trade_signal.py`)
- Cross-actor clustering (`scoring/clustering.py`)
- Catalyst-residual filter (`scoring/residual.py`)
- Asymmetric-bias filter (`filters/asymmetric.py`)
- Event-study backtest skeleton (`backtest/engine.py`)
- Free-tier price ingest via yfinance (`ingest/prices.py`)
- USAspending.gov contract-award ingest (`ingest/usaspending.py`)
- Quiver Quantitative API wrapper skeleton (`ingest/quiver.py`)
- CLI entry point (`cli.py`)
- Pipeline orchestration (`pipeline.py`)

## What you need to build, in order

### 1. Complete the House PTR ingester (`ingest/house_ptr.py`)

The House Clerk publishes annual ZIP files of all PTR PDFs at:
  https://disclosures-clerk.house.gov/FinancialDisclosure

The index XML lives at e.g.:
  https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2025FD.zip

Each ZIP contains an XML index plus per-filing PDFs. Build a parser that:
- Downloads the ZIP for a given year, caches to `data/raw/house/`
- Parses the XML index for filer name, doc ID, filing date
- For each PDF, extracts trade rows using `pdfplumber`
- Normalises to the `Trade` schema in `schema.py`
- Handles the asset-type column (ST = stock, OP = options, etc.)
- Persists to `data/processed/trades.parquet`

The PDFs vary in format; expect to write per-template parsers and fall back to
fuzzy column detection. Quiver Quantitative is a much easier source if the user
has an API key — prefer that if available.

### 2. Complete the Senate eFD ingester (`ingest/senate_efd.py`)

Senate disclosures live at https://efdsearch.senate.gov/search/ behind a
clickwrap agreement. The flow:
- POST to `/search/home/` with the `csrf_token` from a fresh session and the
  agreement-accepted cookie
- GET `/search/report/` for individual reports
- Senate reports are HTML, not PDF — easier to scrape

### 3. Complete the OGE 278 / 278-T ingester (`ingest/oge.py`)

Executive-branch filings (the Trump portfolio source) are at
https://extapps2.oge.gov/Web/278eFile.nsf/PAS+Index. These are large PDFs
filed under names like "Trump, Donald J" — search by individual, download PDF,
parse with `pdfplumber`.

### 4. Add a committee-membership data source

Actor quality scoring depends on knowing which committee each member sits on.
The best free source is `unitedstates/congress-legislators` on GitHub:
  https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml

Plus committee assignments:
  https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committee-membership-current.yaml

Build `ingest/committees.py` that loads these into a lookup keyed by bioguide_id.

### 5. Wire the catalyst calendar (`scoring/catalyst.py`)

Currently stubbed. Pull from:
- Congress.gov API (committee hearings, bill schedules) — free with API key
- FDA Drug Approvals API (PDUFA dates)
- USAspending.gov (already implemented, just needs joining)
- DoD contract obligation cycles (quarterly, deterministic)

### 6. Run the validation backtest

After ingest is working, run:
  icarus backtest --start 2018-01-01 --end 2024-12-31 \\
                --holding-period 90 \\
                --filter-stack actor_quality,trade_signal,clustering

Then out-of-sample on 2025-01-01 to today. Report:
- Mean cumulative abnormal return (CAR) at 30/60/90/180/365 days
- Hit rate (% of trades with positive CAR at 90 days)
- Sharpe of a long-only strategy holding top-N flagged trades
- Bootstrap 95% CI on CAR
- Slippage-adjusted returns (assume 25bps round-trip)

### 7. Add a simple dashboard

Once the data flows, add a Streamlit or FastAPI + React dashboard:
- Current top-N flagged trades, with the filter score breakdown
- Actor leaderboard
- Cluster view (which tickers have ≥3 quality actors buying)
- Catalyst calendar overlay

Keep the dashboard read-only; never write back to `data/processed`.

## Conventions

- Python 3.11+, type hints everywhere, `list[str]` not `List[str]`
- Pydantic v2 for all data contracts
- Pandas for tabular work, polars optional for hot paths
- All datetimes timezone-aware UTC unless explicitly noted
- All money values in USD as float (precision is irrelevant — disclosures are
  bracketed ranges anyway)
- British English in prose docs, American English in code identifiers
- No global state; pass config explicitly via the `Config` object
- Cache aggressively in `data/cache/` keyed by source + date range
- All API clients use `tenacity` retries with exponential backoff
- All scoring functions are pure — `(inputs) -> Score`, no I/O

## Testing

Each module has a `tests/test_<module>.py` stub. The scoring logic in
particular needs synthetic-input unit tests because there is no ground truth.
Generate plausible trade fixtures with hypothesis-style strategies; validate
that scores are monotonic in the obvious dimensions (more committee relevance
→ higher score, etc.).

## Things to deliberately NOT build

- A live trading integration. This is a research tool, not an execution system.
- A recommendation API. The pipeline ranks; the user decides.
- Backtests over <3 years of data. The actor-quality estimates are unstable on
  short windows and you'll fool yourself with noise.
- Anything that auto-emails or auto-alerts on signals. Surveillance is a
  business decision; keep the engine pure.
