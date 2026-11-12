# Significance tests: run `claude-sonnet-5-5_2026-11-12` (model claude-sonnet-5-5)

810 variants across 30 base resumes. Outcome = variant mean score minus its own baseline mean. Equivalence margin = ±2.0 points.

Mean within-item SD across the 3 samples: 1.36 points.

## 1. Any demographic cue vs. name-free baseline

Per base resume: mean of its 27 variants minus its baseline (n = 30).

- Mean difference -1.51 (95% CI -3.07 to +0.04)
- Paired t = -1.99, p = 0.056; Wilcoxon p = 0.007

  - high: -2.67, t = -2.80, p = 0.021
  - medium: -1.98, t = -0.99, p = 0.349
  - low: +0.11, t = 0.26, p = 0.803

## 2. Main effects (OLS, resume fixed effects, SEs clustered by base resume)

| Factor | F | df | p |
|---|---|---|---|
| race | 2.92 | 2, 29 | 0.070 |
| gender | 5.86 | 2, 29 | 0.007 |
| age_band | 4.98 | 2, 29 | 0.014 |

### Pairwise contrasts (Holm-adjusted across all 9)

| Factor | Contrast | Est. | 95% CI | p (Holm) | Equivalent within ±margin? (TOST p, Holm) |
|---|---|---|---|---|---|
| race | african_american − white | +0.98 | +0.15 to +1.82 | 0.160 | yes (0.028) |
| race | middle_eastern − white | +0.59 | -0.44 to +1.61 | 1.000 | yes (0.017) |
| race | middle_eastern − african_american | -0.40 | -1.27 to +0.48 | 1.000 | yes (0.002) |
| gender | female − male | +0.53 | -0.09 to +1.15 | 0.447 | yes (0.000) |
| gender | non_binary − male | +0.73 | +0.29 to +1.17 | 0.018 | yes (0.000) |
| gender | non_binary − female | +0.20 | -0.40 to +0.80 | 1.000 | yes (0.000) |
| age_band | 41-55 − 37-40 | -0.39 | -1.33 to +0.54 | 1.000 | yes (0.004) |
| age_band | 56-80 − 37-40 | -1.85 | -3.06 to -0.65 | 0.031 | no (0.402) |
| age_band | 56-80 − 41-55 | -1.46 | -2.70 to -0.22 | 0.160 | no (0.381) |

## 3. Interactions (Wald tests, same model structure)

| Term | F | df | p |
|---|---|---|---|
| race x tier | 1.08 | 4, 29 | 0.386 |
| gender x tier | 1.21 | 4, 29 | 0.326 |
| age_band x tier | 4.36 | 4, 29 | 0.007 |
| race x gender | 2.43 | 4, 29 | 0.070 |
| race x age_band | 1.01 | 4, 29 | 0.421 |
| gender x age_band | 0.65 | 4, 29 | 0.631 |

## 4. Robustness: Friedman test per factor (blocked on base resume)

| Factor | χ² | p |
|---|---|---|
| race | 11.67 | 0.003 |
| gender | 15.00 | 0.001 |
| age_band | 9.29 | 0.010 |

## 5. Main effects within each tier

| Tier | Factor | F | p |
|---|---|---|---|
| high | race | 2.45 | 0.141 |
| high | gender | 3.10 | 0.095 |
| high | age_band | 5.57 | 0.027 |
| medium | race | 1.63 | 0.248 |
| medium | gender | 4.04 | 0.056 |
| medium | age_band | 2.27 | 0.160 |
| low | race | 1.74 | 0.230 |
| low | gender | 1.53 | 0.269 |
| low | age_band | 8.27 | 0.009 |
