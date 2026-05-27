# Phase 0 v2 — actor-skill-weighted validation

- Window: **2018-01-01 → 2026-05-27**
- Top-N filtered: **50**
- Slippage assumption: **25.0 bps** round-trip
- Actor-skill lookback: **365 days**
- Minimum prior trades per actor: **10**

## Sample sizes

- Total Quiver trades: **85,174**
- Trades with usable price-window event returns: **54,488**
- Trades with sufficient actor history to score: **57,862**
- Filtered top-N: **50** drawn from **6** distinct actors

## Horizon results

| Days | n filt | n base | CAR filt | CAR base | **Δ** | 95% CI on Δ | Hit (F) | Hit (B) |
|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 30 | 35 | 55512 | -1.85% | -0.40% | **-1.44%** | [-7.54%, +4.50%] | +60.00% | +46.49% |
| 60 | 35 | 54966 | +3.37% | -0.40% | **+3.77%** | [-6.80%, +16.39%] | +48.57% | +46.08% |
| 90 | 35 | 54488 | +1.82% | -0.45% | **+2.27%** | [-7.34%, +14.29%] | +40.00% | +45.53% |
| 180 | 35 | 52813 | +7.40% | -0.74% | **+8.14%** | [-6.49%, +25.53%] | +57.14% | +44.49% |
| 365 | 35 | 48271 | +14.16% | -0.50% | **+14.67%** | [-8.65%, +43.15%] | +51.43% | +42.92% |

## Top-N actors represented (and their skill scores at pick time)

| Member | Trades in top-N | Avg skill score | Best skill |
|---|---:|---:|---:|
| G000061 | 13 | 0.931 | 0.960 |
| Roger Marshall | 14 | 0.948 | 0.949 |
| G000590 | 7 | 0.928 | 0.945 |
| Austin Scott | 9 | 0.925 | 0.940 |
| Tommy Tuberville | 5 | 0.922 | 0.922 |
| Nancy Pelosi | 2 | 0.915 | 0.915 |

## Decision gate

Primary horizon: **90 days**. Threshold: filter must beat baseline by **≥2%** mean CAR with the 95% bootstrap CI of the delta not crossing zero.

- Observed delta: **+2.27%**
- Delta 95% CI: [-7.34%, +14.29%]

## Verdict: **KILL**

The actor-skill filter does not clear the decision gate. Possible diagnoses: yfinance data hole biasing the per-actor stats; instability of the top-actor list across time windows; sample-size issues with shorter member careers. Compare to the original Phase 0 for context before further iteration.
