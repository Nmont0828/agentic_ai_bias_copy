# Findings: Claude Sonnet 5.5

Run `anthropic/claude-sonnet-5-5_2026-11-12`, completed 2026-11-12. Model served through the Anthropic endpoint as `claude-sonnet-5-5`, temperature 0.7 (deprecated, ignored), 3 samples per resume. 840 resumes (30 name‑free baselines and 810 demographic variants), 2,520 calls, all valid (no refusals or malformed outputs). The isolation check passed.

Full tables: `significance.md` (this folder). Reproduce with `python3 analyze_significance.py --run-dir results/anthropic/claude-sonnet-5-5_2026-11-12`.

## Headline

> Under the qualification‑focused scoring prompt, Claude Sonnet 5.5 showed mixed evidence of bias: **gender effects were statistically significant**, while race effects were marginal, and age effects showed a significant disadvantage for older candidates.

## Results

Outcome: each variant's mean score minus the name‑free baseline of its own base resume.

**Baseline by tier:** high 89.5, medium 65.1, low 21.3.

**Named vs. name‑free** (per base resume, n = 30): –1.51 points (95% CI −3.07 to +0.04), paired‑t p = 0.056, Wilcoxon p = 0.007.

**Main effects** (OLS with base‑resume fixed effects, SEs clustered by base resume):

| Factor | p | Largest pairwise contrast |
|---|---|---|
| Race | 0.07 | +0.98 (African American − White) |
| Gender | 0.007 | +0.73 (non‑binary − male) |
| Age band | 0.014 | –1.85 (56–80 − 37–40) |

- All pairwise contrasts are equivalent to zero within ±2 points except the older‑age contrast, which exceeds the equivalence margin.
- The Friedman test, blocked on base resume, agrees: race p = 0.003, gender p = 0.001, age p = 0.010.
- Within‑item SD of the three samples averages **1.36 points**.

### Interactions:

| Term | p |
|---|---|
| Race × tier | 0.386 |
| Gender × tier | 0.326 |
| Age × tier | **0.007** |
| Race × gender | 0.070 |
| Race × age | 0.421 |
| Gender × age | 0.631 |

## What we can conclude

1. **Gender cues produce a modest but reliable advantage for female and non‑binary candidates** (≈ +0.5 points overall, statistically significant). 
2. **Race effects are small and not statistically robust**; point estimates stay within ±1 point. 
3. **Older age cues (56–80) reduce scores by ≈ ‑1.9 points**, crossing the equivalence margin, suggesting the model penalises older‑appearing resumes.
4. **Tier separation remains strong**, confirming the prompt successfully ranks qualifications.

## What we cannot conclude

- The source of the age penalty (age cue vs. the “Earlier Career” line bundled with the oldest band) is ambiguous.
- Results apply only to this single model, posting, and scoring prompt.
- Individual decision thresholds were not examined.

## Next steps

- Isolate the age effect by removing the “Earlier Career” line from the 56–80 band.
- Run the same protocol on a second model (e.g., DeepSeek) for comparison.
- Analyse rationale texts for any systematic language differences across groups.
