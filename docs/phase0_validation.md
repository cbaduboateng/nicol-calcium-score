# Phase 0 validation — real-data backtest

- Window: **2018-01-01 → 2026-05-26**
- Top-N filtered: **50**
- Slippage assumption: **25.0 bps** round-trip
- Total raw trades: **85,174**
- Filtered candidates surviving asymmetric filter: **50**

## Horizon results

| Days | n filtered | n baseline | CAR filtered | CAR baseline | **Delta** | 95% CI on delta | Hit (F) | Hit (B) |
|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 30 | 50 | 85174 | -0.98% | +0.13% | **-1.11%** | [-2.80%, +0.70%] | +40.00% | +50.87% |
| 60 | 50 | 85174 | -0.50% | +0.02% | **-0.52%** | [-3.85%, +2.91%] | +46.00% | +49.63% |
| 90 | 50 | 85174 | -1.26% | +0.08% | **-1.34%** | [-5.18%, +3.12%] | +52.00% | +49.30% |
| 180 | 50 | 85174 | -0.75% | +0.61% | **-1.36%** | [-7.61%, +5.12%] | +44.00% | +50.04% |
| 365 | 50 | 85174 | +4.96% | +2.86% | **+2.10%** | [-7.21%, +12.74%] | +58.00% | +52.17% |

## Decision gate

Primary horizon: **90 days**. Threshold: filter must beat baseline by **≥2%** mean CAR with the 95% bootstrap CI of the delta not crossing zero.

- Observed delta: **-1.34%**
- Delta 95% CI: [-5.18%, +3.12%]

## Verdict: **KILL**

The asymmetric filter does not clear the decision gate. Before spending on Apple Developer / Railway / a native app, revisit filter weights, look at per-actor / per-sector breakdowns, and consider whether the layered Phase 1 signals (insider + momentum + earnings revisions) would change the picture.
