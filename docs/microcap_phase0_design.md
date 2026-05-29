# Microcap Phase 0 design

**Goal**: validate whether a deep-value microcap strategy with insider-buying
and catalyst overlay produces capturable alpha vs the IWC (iShares Microcap
ETF) benchmark. Strict Phase 0 decision gate before any product spend.

**Underlying thesis**: NASDAQ-listed microcaps in the $1–$10 price band are
*structurally* mispriced because of mechanical pressures unrelated to
fundamentals:

- Index funds and many institutional mandates can't hold sub-$5 stocks.
- Russell 2000 inclusion / exclusion forces non-informational buying and
  selling at threshold price points.
- Analyst coverage drops sharply below ~$1B market cap.
- Companies on NASDAQ deficiency notices (≥30 days < $1 bid) face forced
  delisting unless they reverse-split or recover, creating asymmetric
  outcomes.

Unlike congressional-trading edge (which is *informational* and may have been
arbed away post-Quiver), the microcap edge is *mechanical / regulatory* and
persists by design. Walter Schloss compounded at ~15% annual for 50 years
running this style; Greenblatt's "special situations" framework targets it
explicitly.

This document specifies the signal stack, universe, data sources, and
Phase 0 validation harness needed to test the hypothesis on real data.

---

## Universe filter

A trade is in-universe if all of the following hold at the trade date:

| Filter | Threshold | Reason |
|---|---|---|
| Exchange | NASDAQ Capital Market or Global Market | Excludes pink sheets / OTC pump-and-dumps |
| Common stock | not ETF / preferred / warrant / unit | Singles only |
| Closing price | $1.00 ≤ p ≤ $10.00 | Captures both deep-value and pre-uplist names |
| Market cap | $30M ≤ mc ≤ $1B | Excludes nano-caps (manipulation) and small-caps (no structural premium) |
| Listing age | ≥ 2 years on NASDAQ | Excludes recent SPACs / IPO pops |
| 90-day average dollar volume | ≥ $200k | Filters out untradeable names |
| Has filed 10-K and 10-Q in last 12 months | required | Excludes shell / non-reporting issuers |

Expected universe size at any given date: ~600–1,000 names. With the
quality / signal filters below, we expect ~30–80 candidates per quarter.

---

## Quality / safety filters (binary — must pass all)

A name is eligible only if:

| Filter | Threshold | Reason |
|---|---|---|
| Cash / total debt | ≥ 0.5 | Floor for solvency |
| Current ratio | ≥ 1.5 | Near-term liquidity headroom |
| Positive book value | book equity > 0 | Excludes underwater balance sheets |
| Altman Z-score | ≥ 1.8 (grey/safe zone) | Bankruptcy filter |
| 8-K filings for "going concern" | none in last 12 months | Explicit auditor red flag |

These are deliberately conservative. The strategy depends on the
balance-sheet being real; the whole thesis fails if we trade on accounting
illusions.

---

## Signal stack (each a 0–1 score, combined via weighted average)

### 1. Listing-pressure score (35%)

Tracks the "mechanical mispricing" thesis directly:

- **Hard deficiency**: stock currently on NASDAQ deficiency notice (≥30 consecutive days < $1, or market-cap below $35M minimum). Score = 1.0 if the company has the cash to survive a reverse split *and* still meets fundamental quality filters. Score = 0 otherwise.
- **Soft deficiency**: 10-day average price in [$0.75, $1.50]. Score = 0.7 if quality filters pass.
- **Sub-$5 uplist candidate**: 30-day average price ≥ $4, currently sub-$5, recent S-1 amendment or NASDAQ listing application visible in EDGAR. Score = 0.6.
- Otherwise: score = 0.

### 2. Insider-buying score (25%)

Reuses `scoring/insider.py` (already built):

- Composite of cluster, senior-role share, and net-buy ratio.
- Source: OpenInsider (`ingest/insider.py`) for SEC Form 4 transactions.
- Window: 90 days trailing the candidate date.
- Min threshold: at least one C-suite ($50k+ open-market buy) in the window.

### 3. Catalyst score (20%)

Composite of:

- **Earnings upcoming**: within next 60 days, weight 0.5.
- **FDA / PDUFA date**: within next 180 days, weight 0.8 (only for biotech / pharma SIC codes).
- **Federal contract decision pending**: USAspending recent award or pending RFP. Already in our codebase.
- **Recent positive press release** (8-K filing classified as material event in last 30 days).

### 4. Quality score (15%)

Reuses `scoring/quality.py` (already built). Six sub-scores: revenue
growth, revenue acceleration, margin level, margin trend, leverage, ROE.
Default weights from existing module.

### 5. Momentum score (5%)

Reuses `scoring/momentum.py`. 12-1 month relative strength.

Low weight because the thesis is *contrarian* (we want stocks that *haven't*
moved up yet — the catalyst is the move). High momentum is actually a slight
negative for this strategy. Could be inverted if backtest shows it.

---

## Combined composite + ranking

`composite = 0.35 * listing + 0.25 * insider + 0.20 * catalyst + 0.15 * quality + 0.05 * momentum`

Universe is filtered down to ~30–80 candidates per quarter passing the hard
quality filters. The composite ranks them. Top-50 monthly is our test
portfolio.

---

## Data sources (with cost / quality trade-offs)

| Source | What it gives | Cost | Notes |
|---|---|---|---|
| **yfinance** | Daily prices, basic fundamentals | Free | Rate-limited, no delisted-name history |
| **SimFin** | Quarterly balance sheets, US-listed | Free tier (~5 years) | Decent coverage; bulk download API |
| **SEC EDGAR XBRL** | Everything, raw | Free | Slow to parse, need our own pipeline |
| **OpenInsider** | Form 4 transactions | Free, scrape | Already built |
| **NASDAQ.com listing alerts** | Deficiency notices | Free, scrape | Need to build |
| **SEC 8-K filings (item 3.01)** | Deficiency disclosures | Free, EDGAR API | Reliable; canonical source |
| **Polygon Stocks Starter** | Survivorship-clean historical | $29/mo | The gold standard for serious backtests |
| **Norgate Data** | Survivorship-clean US equity | £300/yr | Better for personal use |

### Survivorship bias is the gating data issue

If we backtest only on currently-listed names, the result will be 5–10
percentage points too good — every microcap that *should* have appeared in
the universe but got delisted is silently excluded. That's the classic
trap that makes academic microcap papers look better than reality.

**Phase 0 plan**: do the MVP backtest on yfinance/OpenInsider/EDGAR (all
free) but acknowledge the bias. If the MVP shows ≥7% delta (above the
gate by a safety margin), spend the £30/mo on Polygon Starter for a clean
backtest before any further commitment.

---

## Phase 0 decision gate

Stricter than the congressional Phase 0 because:

- Microcaps have wider bid-ask spreads (assume 100 bps slippage round-trip vs 25 bps for liquid mega-caps).
- Survivorship bias inflates expected returns by ~5%.
- The strategy needs to clear a meaningful margin to be worth the operational hassle.

| Metric | Threshold |
|---|---|
| Mean CAR at 365d vs IWC | ≥ +5% net of slippage |
| 95% bootstrap CI on the delta | lower bound > 0 |
| Hit rate at 365d | ≥ 55% |
| Sharpe (long-only portfolio rebalanced monthly) | ≥ 0.7 |
| Max drawdown | ≥ -35% (acceptable for the asset class) |

If **all five** clear: PROCEED. Otherwise: KILL or iterate.

---

## Phase 0 implementation plan

Estimated effort: **3–5 working days** to first validation run.

### Day 1: Universe + fundamentals ingest

- `src/icarus/microcap/universe.py` — point-in-time universe
  builder (price, mkt cap, listing age, exchange filter).
- `src/icarus/ingest/fundamentals.py` — SimFin bulk download +
  parser. Output: parquet of (ticker, date, cash, debt, current_ratio, book
  value, etc.).
- Universe assembly across 2018-01-01 → today, monthly snapshots.

### Day 2: Listing-pressure detection

- `src/icarus/microcap/listing_pressure.py` — universe of names
  with deficiency notices (from SEC 8-K item 3.01 filings).
- EDGAR full-text search + filing parser.
- Output: parquet of (ticker, deficiency_date, deficiency_type).

### Day 3: Signal composition + backtest harness

- `src/icarus/microcap/scoring.py` — composite of the five
  layers above. Pure function.
- `src/icarus/microcap/validation.py` — like `validation_v2.py`
  but for the microcap strategy. Monthly rebalance, top-50 hold, 365-day
  forward returns vs IWC benchmark.

### Day 4: Decision-gate report

- Markdown report with horizon table, per-signal-layer breakdown, top
  holdings, drawdown chart description, Sharpe.
- `.github/workflows/microcap_phase0.yml` — same dispatch pattern as
  congressional Phase 0.

### Day 5: Sanity checks + sensitivity

- Drop each signal layer one at a time; verify composite ≥ best single
  layer.
- Run on 2018-2022 (in-sample) and 2023-2025 (out-of-sample) separately
  to check stability.
- Per-year breakdown of returns.

---

## What's reusable from icarus

| Component | Reuse status |
|---|---|
| `backtest/engine.py` (event returns, bootstrap CIs) | ✅ As-is |
| `scoring/insider.py` | ✅ As-is |
| `scoring/quality.py` | ✅ As-is |
| `scoring/momentum.py` | ✅ As-is |
| `scoring/combined.py` | ✅ As-is, with microcap weights |
| `ingest/insider.py` (OpenInsider) | ✅ As-is |
| Phase 0 harness skeleton | ✅ Pattern reused |
| GitHub Actions workflow pattern | ✅ Pattern reused |
| Dashboard | ⚠️ Needs separate microcap tab eventually |
| Asymmetric filter for congress trades | ❌ Specific to congress |

About 70% of the codebase carries straight over. The new layers are
universe-builder, fundamentals ingest, and listing-pressure detector.

---

## Risks we should commit to flagging in the report

1. **Survivorship bias**: free-data Phase 0 will overstate returns by
   ~5–10%. If we PROCEED, immediately spend on Polygon Starter for clean
   re-validation.
2. **Liquidity / slippage realism**: we're assuming 100 bps round-trip;
   real-world for sub-$2 stocks can be 200–400 bps on bad days.
3. **Sample size**: at 50 names / month over 7 years, we'd have ~4,000
   trade-events. CI should be tight, unlike the congressional runs.
4. **Concentration**: a basket of 50 micro-cap names is meaningfully more
   volatile than 50 mega-caps. Drawdowns of -40% within 6 months are
   normal. Position-sizing recommendations matter.
5. **Regulatory / accounting risk**: small companies have worse disclosure;
   our balance-sheet filters help but don't eliminate this.

---

## Decision points to confirm before building

1. **Hold period**: 365 days fits the catalyst-realisation timeline but
   ties up capital for a year. Alternative: 180 days. Faster turnover,
   probably noisier signal. Default in this design: 365.
2. **Rebalance frequency**: monthly (default) vs quarterly. Monthly catches
   freshly-eligible names faster; quarterly reduces transaction costs.
3. **Position weighting**: equal-weight (simplest) vs composite-score-weight
   (more conviction). Default: equal-weight for the Phase 0 test.
4. **Universe price band**: $1–$10 captures the structural mispricing.
   Could narrow to $1–$5 (pure deep-value) or extend to $1–$20 (lighter
   pressure). Default: $1–$10.

These should all be parameters on the validation script. Sensible defaults
above.

---

## Estimated all-in cost to PROCEED

| Item | Cost |
|---|---|
| MVP (free-data Phase 0) | 3–5 days dev, £0 |
| Polygon Stocks Starter (if MVP clears the gate) | £29/mo |
| Continued Quiver subscription (for the secondary congressional signal) | £10/mo |
| Render hosting | £0 (free tier) |
| Total monthly to operate post-Phase 0 | **£39/mo** |

Same order of magnitude as the congressional product. Lower data cost than
serious quant operations.

---

## Path from PROCEED → product

If Phase 0 validates:

1. **Re-validate on Polygon clean data**. Critical sanity check.
2. **Add the microcap tab to the dashboard.** Reuse existing UI; new
   columns for listing status, balance-sheet metrics, insider buying.
3. **Daily picks email or push.** When a name newly enters the top-50,
   notify the user.
4. **Re-evaluate Apple Developer / iOS app spend.** This strategy has
   better unit economics than congressional — fewer signals per month,
   higher conviction per signal, longer hold = lower transaction cost.

If Phase 0 does *not* validate cleanly, we have a different conversation
about whether either of the strategies we've explored is worth shipping.
