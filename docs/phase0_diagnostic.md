# Phase 0 diagnostic — why did the filter underperform?

- Window: **2018-01-01 → 2026-05-27**
- Primary horizon: **90 days**
- Top-N filter: **50**
- Slippage assumption: **25.0 bps** round-trip

## Headline

| | Filtered | Baseline (all) | Delta |
|---|---:|---:|---:|
| n | 50 | 85,174 | — |
| Mean CAR | +1.24% | +0.09% | **+1.15%** |
| Hit rate | +54.00% | +49.30% | — |

## Chamber

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| house | 44 | 81039 | +2.65% | +0.09% | +2.57% | +56.82% | +49.26% |
| senate | 6 | 4135 | -9.11% | +0.12% | -9.22% | +33.33% | +50.13% |

## Party

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| — | 24 | 14549 | +0.84% | -0.33% | +1.17% | +54.17% | +47.98% |
| Democrat | 13 | 42637 | +0.94% | +0.35% | +0.59% | +53.85% | +50.21% |
| Republican | 13 | 27929 | +2.27% | -0.09% | +2.37% | +53.85% | +48.58% |
| Independent | 0 | 59 | — | -0.49% | — | — | +52.54% |

## Direction

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| sell | 27 | 40325 | +3.05% | +0.02% | +3.03% | +59.26% | +49.15% |
| buy | 22 | 42808 | -1.65% | +0.19% | -1.84% | +45.45% | +49.49% |
| partial_sale | 1 | 1602 | +15.80% | -1.41% | +17.20% | +100.00% | +45.94% |
| exchange | 0 | 439 | — | +1.89% | — | — | +56.95% |

## Sector (top-level)

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| Other | 30 | 56941 | -2.47% | +0.03% | -2.50% | +43.33% | +49.04% |
| Tech / hardware | 4 | 1569 | +13.19% | -0.90% | +14.09% | +100.00% | +45.76% |
| Consumer | 3 | 3893 | +14.25% | -0.60% | +14.85% | +100.00% | +47.96% |
| Defence | 3 | 825 | +13.28% | +5.16% | +8.12% | +66.67% | +58.18% |
| Tech / software | 2 | 3181 | -2.91% | +1.80% | -4.72% | +50.00% | +54.39% |
| Semiconductors | 2 | 2609 | +0.23% | -0.62% | +0.85% | +50.00% | +47.30% |
| Industrial | 2 | 1121 | -0.44% | +0.11% | -0.55% | +50.00% | +48.80% |
| Pharma | 1 | 1742 | -2.48% | +0.97% | -3.46% | +0.00% | +53.62% |
| Logistics & transport | 1 | 1571 | +7.59% | +0.64% | +6.95% | +100.00% | +51.43% |
| Internet / media | 1 | 2202 | +2.47% | -1.48% | +3.95% | +100.00% | +45.73% |
| Health insurance | 1 | 791 | -0.65% | -0.27% | -0.38% | +0.00% | +45.89% |
| Biotech | 0 | 495 | — | -0.18% | — | — | +50.91% |
| Aerospace / defence | 0 | 257 | — | -1.86% | — | — | +42.80% |
| Energy | 0 | 930 | — | +0.16% | — | — | +48.60% |
| Financials | 0 | 4193 | — | +0.44% | — | — | +51.44% |
| Medical devices | 0 | 1325 | — | -1.21% | — | — | +45.13% |
| Real estate | 0 | 512 | — | +1.79% | — | — | +54.69% |
| Telecom | 0 | 746 | — | +0.85% | — | — | +51.74% |
| Utilities | 0 | 271 | — | +0.74% | — | — | +52.03% |

## Market-cap bucket

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| — | 22 | 54923 | -1.19% | +0.03% | -1.23% | +45.45% | +49.08% |
| mega | 14 | 8914 | +7.29% | +0.17% | +7.12% | +71.43% | +49.55% |
| large | 13 | 20749 | -1.65% | +0.16% | -1.81% | +46.15% | +49.64% |
| mid | 1 | 557 | +7.59% | +0.92% | +6.68% | +100.00% | +52.42% |
| small | 0 | 31 | — | +8.15% | — | — | +77.42% |

## Disclosure speed

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| 8-14 days (fast) | 28 | 10287 | +1.76% | +0.03% | +1.73% | +60.71% | +48.93% |
| 0-7 days (very fast) | 22 | 3904 | +0.58% | -1.05% | +1.63% | +45.45% | +46.21% |
| 15-30 days (normal) | 0 | 35597 | — | -0.25% | — | — | +48.59% |
| 31-45 days (slow, near limit) | 0 | 25398 | — | +0.52% | — | — | +50.66% |
| >45 days (late) | 0 | 9988 | — | +0.70% | — | — | +49.95% |

## Trade size bracket

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| $15k-$50k | 15 | 12915 | +1.18% | +0.54% | +0.63% | +46.67% | +50.90% |
| $250k-$1M | 15 | 957 | +2.68% | +0.12% | +2.56% | +73.33% | +52.66% |
| $100k-$250k | 11 | 2893 | -4.26% | -0.22% | -4.04% | +36.36% | +47.94% |
| $50k-$100k | 7 | 4425 | +5.26% | +0.40% | +4.86% | +57.14% | +50.17% |
| $1M-$5M | 1 | 174 | -1.15% | +1.42% | -2.57% | +0.00% | +52.30% |
| $1k-$15k | 1 | 63785 | +15.37% | -0.02% | +15.39% | +100.00% | +48.91% |
| >$5M | 0 | 25 | — | +0.61% | — | — | +68.00% |

## Cluster size

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5+ (large cluster) | 20 | 20 | +5.92% | +5.92% | +0.00% | +70.00% | +70.00% |
| 3-4 (small cluster) | 14 | 14 | -0.19% | -0.19% | +0.00% | +42.86% | +42.86% |
| 1 (solo) | 11 | 85135 | +2.32% | +0.09% | +2.24% | +45.45% | +49.30% |
| 2 (pair) | 5 | 5 | -15.84% | -15.84% | +0.00% | +40.00% | +40.00% |

## Catalyst pending

| Group | n filt | n base | CAR filt | CAR base | Δ (filt-base) | Hit filt | Hit base |
|---|---:|---:|---:|---:|---:|---:|---:|
| True | 48 | 48 | +0.02% | +0.02% | +0.00% | +52.08% | +52.08% |
| False | 2 | 85126 | +30.57% | +0.09% | +30.49% | +100.00% | +49.30% |

## Top 20 actors by mean CAR (≥20 trades, baseline)

| Member | Chamber | Party | Trades | In filter | Mean CAR | Hit rate |
|---|---|---|---:|---:|---:|---:|
| Sara Jacobs | house | Democrat | 54 | 0 | +11.47% | +96.30% |
| Sheri Biggs | house | Republican | 82 | 0 | +11.27% | +84.15% |
| M001186 | house | — | 276 | 0 | +11.07% | +89.49% |
| T000479 | house | — | 406 | 0 | +9.92% | +78.82% |
| Pete Ricketts | senate | Republican | 25 | 0 | +9.67% | +72.00% |
| Kelly Morrison | house | Democrat | 68 | 0 | +9.45% | +80.88% |
| Bruce Westerman | house | Republican | 208 | 0 | +8.67% | +78.37% |
| George Whitesides | house | Democrat | 35 | 0 | +8.40% | +74.29% |
| Patrick Fallon | house | Republican | 200 | 0 | +7.85% | +77.00% |
| William Keating | house | Democrat | 104 | 0 | +7.69% | +75.00% |
| Greg Stanton | house | Democrat | 188 | 0 | +7.24% | +74.47% |
| Michael Simpson | house | Republican | 48 | 0 | +6.89% | +75.00% |
| C. Franklin | house | Republican | 248 | 0 | +6.42% | +72.98% |
| N000192 | house | — | 298 | 0 | +6.41% | +73.49% |
| Ashley Moody | senate | Republican | 23 | 0 | +6.34% | +69.57% |
| Scott Peters | house | Democrat | 30 | 0 | +6.14% | +80.00% |
| Blake Moore | house | Republican | 149 | 0 | +5.82% | +64.43% |
| Brian Mast | house | Republican | 86 | 0 | +5.71% | +61.63% |
| Kathy Castor | house | Democrat | 44 | 1 | +5.64% | +63.64% |
| Greg Landsman | house | Democrat | 167 | 0 | +5.60% | +70.66% |

## Bottom 20 actors by mean CAR (≥20 trades, baseline)

| Member | Chamber | Party | Trades | In filter | Mean CAR | Hit rate |
|---|---|---|---:|---:|---:|---:|
| G000579 | house | — | 38 | 0 | -10.67% | +13.16% |
| John Larson | house | Democrat | 29 | 0 | -10.27% | +10.34% |
| Michael Guest | house | Republican | 68 | 0 | -9.55% | +23.53% |
| C000567 | house | — | 33 | 0 | -8.69% | +21.21% |
| Susan Collins | senate | Republican | 48 | 0 | -8.13% | +20.83% |
| Rudy Yakym | house | Republican | 29 | 0 | -7.19% | +27.59% |
| H001041 | house | — | 69 | 0 | -6.76% | +30.43% |
| T000475 | house | — | 60 | 0 | -6.28% | +20.00% |
| G000563 | house | — | 94 | 0 | -5.86% | +30.85% |
| M001193 | house | — | 490 | 0 | -5.60% | +29.59% |
| I000024 | house | — | 96 | 0 | -5.48% | +36.46% |
| S000583 | house | — | 143 | 0 | -5.42% | +32.87% |
| John Rose | house | Republican | 21 | 0 | -4.79% | +28.57% |
| Bill Hagerty | senate | Republican | 32 | 0 | -4.45% | +34.38% |
| C001062 | house | — | 394 | 0 | -4.43% | +37.31% |
| B001286 | house | — | 24 | 0 | -4.39% | +29.17% |
| John Rutherford | house | Republican | 221 | 0 | -4.37% | +33.03% |
| S001207 | house | — | 295 | 0 | -4.33% | +32.54% |
| Donald Beyer | house | Democrat | 659 | 2 | -4.22% | +35.36% |
| John James | house | Republican | 266 | 0 | -4.12% | +38.72% |

## Signal-type breakdown (filtered candidates only)

| Signal type | n | Mean CAR | Hit rate |
|---|---:|---:|---:|
| large vs personal history (z=4.0) | 1 | +54.36% | +100.00% |
| large vs personal history (z=1.7) | 1 | +26.09% | +100.00% |
| large vs personal history (z=1.6) | 1 | +23.22% | +100.00% |
| large vs personal history (z=3.0) | 1 | +17.50% | +100.00% |
| large vs personal history (z=1.9) | 1 | +8.27% | +100.00% |
| large vs personal history (z=1.2) | 2 | +8.11% | +100.00% |
| large vs personal history (z=3.3) | 1 | +7.59% | +100.00% |
| large vs personal history (z=2.5) | 1 | +6.23% | +100.00% |
| large vs personal history (z=2.3) | 7 | +6.18% | +71.43% |
| large vs personal history (z=1.0) | 2 | +6.17% | +100.00% |
| large vs personal history (z=1.1) | 7 | +3.36% | +57.14% |
| fast disclosure | 50 | +1.24% | +54.00% |
| large vs personal history (z=2.2) | 4 | +0.72% | +50.00% |
| large vs personal history (z=2.4) | 1 | -0.01% | +0.00% |
| large vs personal history (z=10.8) | 1 | -1.15% | +0.00% |
| large vs personal history (z=1.4) | 1 | -2.48% | +0.00% |
| large vs personal history (z=2.7) | 8 | -2.94% | +50.00% |
| large vs personal history (z=3.2) | 1 | -3.59% | +0.00% |
| large vs personal history (z=1.3) | 1 | -4.01% | +0.00% |
| large vs personal history (z=1.5) | 3 | -10.08% | +33.33% |
| large vs personal history (z=3.6) | 2 | -20.00% | +0.00% |
| large vs personal history (z=2.0) | 1 | -20.81% | +0.00% |
| large vs personal history (z=1.8) | 1 | -21.30% | +0.00% |
| large vs personal history (z=4.9) | 1 | -32.40% | +0.00% |

## Reading this report

- **Group**: the slice. **n filt / base**: number of trades in the filter top-N vs in the full baseline. **CAR**: mean cumulative abnormal return at the primary horizon, net of slippage. **Δ**: filtered minus baseline within the same group. **Hit rate**: share with positive CAR.

- A **positive Δ in a group** is the alpha pocket — the filter is genuinely picking winners within that slice. A consistently **negative Δ across all groups** means the filter is broken; a **bimodal Δ** (good in some slices, bad in others) means we can rescue it by restricting to the good slices and reweighting.
