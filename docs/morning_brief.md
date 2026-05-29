# Morning brief — what happened while you slept

Read order: this file → the diagnostic report once you've triggered it → the recommendations at the bottom.

## State of play

**Phase 0 verdict: KILL.** The single-signal asymmetric filter on
congressional trades alone underperformed the naive baseline at every
horizon under a year, at 90 days by **-1.34%** mean CAR with a CI
that crossed zero.

That's a real result, but it's **not** a death sentence for the project.
It's a falsification of the *single-signal* hypothesis. Three reasons
not to give up yet:

1. n=50 candidates is tiny. CIs are too wide to be conclusive.
2. The 365-day delta was actually **+2.10%** — slower than 90 days but
   directional. There may be a real long-horizon signal buried in the
   noise.
3. The multi-signal hypothesis hasn't been tested. Combining the
   congressional signal with insider buying, momentum and quality could
   produce composite alpha even where any single layer fails.

## Built overnight (commits b2843b6 → 925714d)

### Phase 0 diagnostic workflow ready to run

`icarus diagnose` + `.github/workflows/diagnose.yml`. Slices the 85k
trade tape on **every dimension we have** and reports per-slice mean
CAR, hit rate, and delta-vs-in-group-baseline at 90 days:

- Chamber, party, direction, sector, market-cap bucket
- Disclosure speed (0-7 / 8-14 / 15-30 / 31-45 / >45 days)
- Trade size bracket, cluster size bucket, catalyst-pending boolean
- Per-actor top-20 and bottom-20 by mean CAR (baseline, n≥20)
- Per-signal-type breakdown (which actual filter triggers add value)

**Trigger it the same way as Phase 0:** Actions tab → "Phase 0
diagnostic" → Run workflow → branch `icarus-extract`.

Runs in ~6-10 min. Output lands at `docs/phase0_diagnostic.md` on
the branch.

### Phase 1 scoring layers (Lakonishok-Lee, Jegadeesh-Titman, AQR)

Three new pure scoring modules in `src/icarus/scoring/`:

- **`insider.py`** — clustered insider buying. Composite of (1) distinct
  buyer cluster, (2) C-suite / chairman / founder share, (3) net buying
  ratio. Default weights 50/25/25.
- **`momentum.py`** — 12-1 month Jegadeesh-Titman relative strength.
  Logistic-mapped to 0-1.
- **`quality.py`** — AQR-style quality factor. Six sub-scores: revenue
  growth, revenue acceleration, gross margin level, gross margin trend,
  leverage, ROE.

All are pure `(inputs) -> Score` functions with monotonicity tests.

### Composite multi-signal scorer

`scoring/combined.py` — `score_composite()` takes per-layer sub-scores
and returns a single composite. Default weights:

- Congressional asymmetry: 25%
- Insider buying:          25%
- Momentum:                20%
- Quality:                 15%
- Catalyst-residual:       15%

Tunable; the right starting weights will come from re-validating with
each weight perturbed.

### Insider data ingest (OpenInsider)

`ingest/insider.py` — scrapes the OpenInsider screener for recent open-
market Form 4 transactions, normalises to the `InsiderTransaction`
schema. Fragile (HTML scraping) but free; long-term we'd switch to the
official SEC EDGAR Form 4 XML feed.

### Tests

54 → 59 passing. Every new scoring layer has monotonicity tests:
"increasing X should never lower the X-sub-score, holding others
fixed."

## Recommended morning sequence

In priority order:

1. **Trigger the diagnostic workflow.** ~10 min wall-clock.
   Read the report. The numbers tell us whether to:
   - Restrict the filter to a viable sub-population (e.g. "Senate fast
     disclosures in defence with cluster ≥3") and re-validate, or
   - Abandon the single-signal hypothesis entirely and pivot to
     multi-signal.

2. **Read the per-actor breakdown.** If a small set of members
   (10-20 names) consistently produces positive CAR, *they* might be
   the actual edge. The filter might be picking the wrong trades from
   the wrong members.

3. **Read the per-signal-type breakdown.** Which of `fast disclosure`,
   `large vs personal history`, `committee jurisdiction`, `options
   purchase` etc. actually adds CAR? Reweight the filter to emphasise
   the winners.

4. **Decide on Phase 1.** Two paths:
   - **Conservative**: if the diagnostic finds a viable sub-population,
     tighten the filter, re-run Phase 0, see if the verdict flips.
   - **Aggressive**: skip the tighten-and-revalidate dance, build out
     the multi-signal Phase 1 pipeline using the new
     insider/momentum/quality layers, then validate composite.

5. **Don't spend on Apple Developer / Render Starter yet.** The Phase 0
   verdict is binding on that decision until we have a re-validated
   PROCEED.

## What is *not* built

- **Phase 1 validation harness.** Like Phase 0, but for the composite
  scorer. Skipped because the right weights to test depend on what the
  diagnostic surfaces. Will be ~50 LOC once we know the starting point.
- **Insider data in the live dashboard.** The OpenInsider ingest exists
  but isn't wired into the bootstrap. Could be added in ~30 min — but
  the dashboard already does its job; this is for the validation step.
- **Earnings revisions (FMP) layer.** Holds for £14/mo and another
  ingest layer. Worth doing only after composite-without-it is
  validated.

## Open questions for you

1. **The 365d positive result.** Worth a focused experiment — re-run
   Phase 0 with `--horizon-days 365` only, top-N=200 to tighten CIs.
   Either it confirms a slow signal worth building around, or noise.
2. **Diagnostic verdict.** Once you've read the report, tell me what
   you see — I'll suggest the targeted next experiment.
3. **Where the strategy actually lives.** Hypotheses to consider:
   - "Senate buys in mid-caps with fast disclosure" (information edge)
   - "House Armed Services + Senate Armed Services in defence small/mid
     caps" (committee jurisdiction edge)
   - "Cluster ≥3 + pending catalyst across any sector" (consensus edge)
   - "Specific 10-15 members historically profitable" (skill edge)

Each is testable in the diagnostic output.

---

Current commit: 925714d on branch `icarus-extract`.
Tests: 59 passing.
Dashboard URL: <https://icarus.onrender.com>
