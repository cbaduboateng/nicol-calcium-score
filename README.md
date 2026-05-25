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
csig ingest --source synthetic --days 2555
csig score
csig rank --top 10
csig backtest --start 2018-01-01 --end 2024-12-31 --holding-period 90 \
  --filter-stack actor_quality,trade_signal,clustering
```

## Real data

Set `QUIVER_API_KEY` for the QuiverQuant adapter, or run
`csig ingest --source house_ptr --year 2024` to pull from the House Clerk
archive. `csig committees` populates actors from
`unitedstates/congress-legislators`.

## Dashboard

Local:

```bash
pip install -e ".[dashboard]"
csig-dashboard            # opens http://localhost:8501
# or:
streamlit run streamlit_app.py
```

Deploy to Streamlit Community Cloud:

1. Push this repository to GitHub.
2. Go to <https://share.streamlit.io/> → **New app**.
3. Pick the repo + branch, set **Main file path** to `streamlit_app.py`.
4. Click **Deploy**.

The app self-bootstraps a synthetic data tape on first run, so it works
without any secrets configured. Add `QUIVER_API_KEY`, `CONGRESS_API_KEY`
under **Settings → Secrets** for live data.

See `CLAUDE.md` for the full architecture and `RESULTS.md` for the
validation backtest output.
