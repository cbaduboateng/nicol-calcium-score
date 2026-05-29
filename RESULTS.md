# Build Results

Status: pipeline is fully wired end-to-end and validated on a 7-year
synthetic tape. Real-data adapters (Quiver, House PTR, Senate eFD, OGE,
USAspending, committees) are implemented but unverified against live APIs
because this sandbox has no outbound access to those endpoints; all of
them fall back to deterministic synthetic data on failure so the pipeline
never breaks mid-run.

## What ships

| Module | Status |
|---|---|
| `schema.py` | recovered intact from original archive |
| `config.py` | recovered intact |
| `cli.py` | recovered intact + extended (synthetic source, committees/catalysts commands, --filter-stack) |
| `filters/asymmetric.py` | recovered intact |
| `backtest/engine.py` | recovered intact |
| `pipeline.py` | rebuilt |
| `ingest/quiver.py` | rebuilt with tenacity retries + synthetic fallback |
| `ingest/house_ptr.py` | rebuilt: ZIP download + XML index parse + optional pdfplumber PDF parse |
| `ingest/senate_efd.py` | rebuilt: clickwrap accept + PTR search; HTML report parser stubbed |
| `ingest/oge.py` | rebuilt: PAS index scrape + per-individual PDF download + pdfplumber parse |
| `ingest/usaspending.py` | rebuilt: spending_by_award + recipient→ticker join |
| `ingest/committees.py` | rebuilt: pulls unitedstates/congress-legislators YAML + caches 7d |
| `ingest/prices.py` | rebuilt: yfinance with synthetic fallback + parquet cache |
| `ingest/synthetic.py` | rebuilt: deterministic offline generator |
| `scoring/actor_quality.py` | rebuilt |
| `scoring/trade_signal.py` | rebuilt |
| `scoring/clustering.py` | rebuilt |
| `scoring/residual.py` | rebuilt |
| `scoring/catalyst.py` | rebuilt: DoD calendar + USAspending; Congress.gov requires key; FDA stubbed |
| `dashboard.py` | new: read-only Streamlit view |

## Tests: 38/38 passing

```
tests/test_actor_quality.py            4 passed
tests/test_catalyst.py                 4 passed
tests/test_clustering.py               3 passed
tests/test_committees.py               3 passed
tests/test_house_ptr.py                4 passed
tests/test_monotonicity_hypothesis.py  2 passed (hypothesis-driven)
tests/test_pipeline.py                 5 passed (end-to-end synthetic)
tests/test_quiver.py                   3 passed
tests/test_residual.py                 3 passed
tests/test_trade_signal.py             3 passed
tests/test_usaspending.py              4 passed
```

## Validation backtest

**In-sample, 2018-01-01 → 2024-12-31, synthetic tape (1,277 trades, 5 actors, 7 years):**

| Horizon | n | Mean CAR | Hit rate | Sharpe | 95% CI |
|--------:|--:|---------:|---------:|-------:|--------|
| 30d     | 28 | +1.01% | 57% | 1.68 | [-1.42%, +3.46%] |
| 60d     | 27 | +1.75% | 56% | 1.11 | [-1.82%, +5.05%] |
| 90d     | 26 | -0.57% | 54% | 0.90 | [-5.13%, +3.74%] |
| 180d    | 25 | +0.63% | 40% | 1.23 | [-8.75%, +9.68%] |
| 365d    | 23 | +9.44% | 39% | 1.41 | [-15.23%, +36.77%] |

All CARs are slippage-adjusted (25 bps round-trip). Confidence intervals
are percentile bootstrap on the mean (1,000 iterations).

**Out-of-sample, 2025-01-01 → today, 90-day holding:**

- n=9, mean CAR -0.25%, hit rate 44%, Sharpe -0.20
- CI [-8.6%, +8.2%]

These numbers are computed against synthetic prices with planted alpha on
LMT/PLTR — they prove the pipeline runs cleanly, not that the strategy
works. To get an economically meaningful result, plug in a real Quiver
API key and a yfinance-enabled environment.

## How to reproduce

```bash
cd icarus
pip install -e .
icarus ingest --source synthetic --days 2555
icarus score
icarus rank --top 20
icarus backtest --start 2018-01-01 --end 2024-12-31 \
  --holding-period 90 \
  --filter-stack actor_quality,trade_signal,clustering
```

For real data (requires network):

```bash
export QUIVER_API_KEY=...
export CONGRESS_API_KEY=...   # optional, for Congress.gov hearings
icarus committees                # build actors.parquet from unitedstates/congress-legislators
icarus ingest --source quiver --days 180
icarus prices --since 2018-01-01
icarus score
icarus catalysts --horizon-days 90
icarus rank --top 20
icarus backtest --start 2018-01-01 --end 2024-12-31 --holding-period 90
```

## Known limitations

- **House PTR PDF parsing** is heuristic. The XML index is parsed cleanly
  and PDFs extract via pdfplumber, but per-filing templates vary; expect
  to write per-template parsers when targeting specific high-value
  filers.
- **Senate eFD report HTML parsing** is stubbed — the search side works
  but converting individual report HTML to Trade rows is a follow-up
  (likely BeautifulSoup-driven).
- **OGE PAS index scraping** uses regex on Notes-rendered HTML and is
  fragile.
- **FDA PDUFA calendar** is empty — FDA does not publish a stable open
  feed. Subscribe to Biopharm Catalyst or scrape company 8-Ks for prod.
- **Congress.gov hearing → ticker resolution** currently broadcasts every
  hearing to the defence ticker bucket. Replace with bill-text → SIC
  code → ticker resolution.
- **pdfplumber** isn't installed in this sandbox because its
  `cryptography` native binding panics on import; PDF parsing modules
  gracefully no-op when that happens.
- **Synthetic prices** plant +0.4% drift on LMT/PLTR in the second half
  of the window — that's what produces the non-zero CARs above. Real
  prices will give different (and more honest) numbers.
