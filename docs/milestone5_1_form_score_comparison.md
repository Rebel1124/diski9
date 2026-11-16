# Milestone 5.1 — Form Score: banded (A) versus continuous (B)

*16 November 2026. Research only: the production Form Score (Method A, engine
2.0.0) is unchanged.*

**Reproduce:**

```
uv run python scripts/research_form_score.py
```

The code is in `src/diski9/research/form_score_comparison.py`. Outputs are in
`docs/research/`: `form_score_summary.json`,
`form_score_distribution_by_league_season.csv`,
`form_score_outcomes_by_band.csv` and `form_score_stability.csv`.

## 1. Methods

Both methods use the last five eligible matches (venue-specific or overall),
the production point-in-time rules (cutoff = kickoff) and the same three
bonuses.

| | Method A (production) | Method B (candidate) |
|---|---|---|
| Points | bands: 0–2 → 0 … 15 → 2.5 | P = 2.5 × points ÷ 15 |
| Goal difference | bands: ≤ 0 → 0 … ≥ +9 → 2.5 | G = 2.5 × min(max(GD, 0) ÷ 9, 1) |
| Bonuses | +0.5 each: won last 3; scored ≥ 11; conceded ≤ 2 | identical |
| Score | raw × 5 ÷ 6.5 | (P + G + B) × 5 ÷ 6.5 |

**Partial windows.** Method B uses the production policy unchanged:
* It uses the actual points and goal difference of the matches available,
  with no prorating.
* Won-last-3 needs at least 3 matches; conceded ≤ 2 needs 5.

For example, two 2–0 wins give P = 2.5 × 6 ÷ 15 = 1.0 and G = 2.5 × 4 ÷ 9 =
1.11, with no bonus. Partial windows are only 5.5% of fixtures, so no
alternative partial rule was evaluated.

**Exploratory Method C** (diagnostic only, not a proposal). This is Method B
with a symmetric goal-difference component, G = 1.25 + 1.25 × clip(GD ÷ 9, −1,
1). It was added to test *why* scores cluster (see section 4).

## 2. Data

* 3,237 completed, eligible fixtures from 2024/25, 2025/26 and 2026/27 to
  date: EPL 860, Championship 1,284, PSL 534, PSL 1st Division 559. Each is
  scored on both bases (6,474 fixture-basis rows).
* Outcomes: home 1,389 (42.9%), draw 902 (27.9%), away 946 (29.2%).
* Windows come from the production `MatchStore`. A unit test confirms that
  rebuilding a row from a store truncated at kickoff gives identical scores,
  so no later results leak in.

## 3. Distributions (venue basis, team scores; n = 6,436)

| | A | B | C (exploratory) |
|---|---|---|---|
| Mean / median | 1.20 / 0.77 | 1.31 / 0.90 | 1.92 / 1.84 |
| Standard deviation | 1.07 | 1.07 | 1.00 |
| Distinct values | 14 | 94 | 188 |
| Most common value | 0.38 (1,672 = **26%**) | 0.64 (624 = 10%) | 1.50 (200 = 3%) |
| Share at or below 1.0 (lowest 20% of scale) | **54%** | 53% | 17% |
| Home team (home window): mean / ≤ 1.0 | 1.52 / 40% | 1.63 / 40% | — |
| Away team (away window): mean / ≤ 1.0 | 0.88 / 68% | 1.00 / 67% | — |

* B removes the spikes; A's single value 0.38 holds 26% of all scores.
* B does **not** move the mass: 53% are still in the bottom fifth of the
  scale, because both methods give every goal difference ≤ 0 the same zero.
  That covers 55% of team windows.
* The overall basis looks the same: A has 14 distinct values with 54% ≤ 1.0;
  B has 94 with 53%.
* By league and season (CSV): the pattern is the same everywhere. B's
  standard deviation stays within ±0.02 of A's in every competition-season.

## 4. Ranking discrimination

These use Screener-like lists: every fixture kicking off in the same ISO week
across all four leagues. That is 86 weeks with at least 10 fixtures.

| Venue basis (overall basis similar) | A | B |
|---|---|---|
| Fixtures whose Form Difference ties with another in the list | **85%** | **31%** |
| Distinct differences ÷ fixtures | 0.39 | 0.82 |
| Rank correlation A vs B | 0.987 | |
| Top-5 / top-10 home-advantage overlap | 89% / 94% | |
| Top-5 / top-10 away-advantage overlap | 90% / 92% | |
| Top-5 / top-10 most-evenly-matched overlap | 69% / 82% | |

B orders fixtures almost exactly as A does. Its practical effect is to break
A's many ties, especially in the "most evenly matched" list, where A's ties at
exactly 0.00 are frequent.

## 5. Relationship to outcomes (venue basis, quintiles of Form Difference)

| Quintile | A: home / draw / away | B: home / draw / away |
|---|---|---|
| Q1 (strongest away) | 33.6% / 24.4% / 42.0% | 34.8% / 23.7% / 41.4% |
| Q2 | 39.2% / 31.7% / 29.1% | 37.7% / 31.9% / 30.5% |
| Q3 | 41.3% / 27.6% / 31.0% | 40.9% / 28.7% / 30.4% |
| Q4 | 45.8% / 29.4% / 24.8% | 47.0% / 28.3% / 24.7% |
| Q5 (strongest home) | 53.2% / 26.7% / 20.1% | 52.7% / 27.1% / 20.1% |

* Both are monotonic in home-win and away-win rates, with almost identical
  spreads.
* Stability (Q5 − Q1 home-win rate per league-season): mean 0.15 for A and
  0.16 for B.
  * Strong in the EPL (0.30 in 2024, 0.17 in 2025) and the PSL (0.29–0.33).
  * Weak in the Championship (0.08–0.15).
  * Absent in the PSL 1st Division in 2024 (−0.05 / −0.12).
  * This holds for both methods, so it is a property of recent form as a
    signal, not of the scoring scheme.
* Neither score is a calibrated probability.

## 6. Out-of-sample diagnostic (not production)

* **Model:** multinomial logistic regression of outcome (H/D/A) on Form
  Difference, fitted on earlier seasons and scored on later ones
  (chronological splits only).
* **Baselines:** training-period outcome frequencies, overall and per league.

| Split / basis | Baseline (overall rates) | A | B | C (exploratory) | B − A log loss (paired bootstrap 95% CI) |
|---|---|---|---|---|---|
| Train 2024 → test 2025–26, venue (n = 1,822) | 1.0827 | 1.0672 | 1.0667 | 1.0661 | −0.0005 [−0.0015, +0.0006] |
| Same, overall (n = 1,833) | 1.0822 | 1.0653 | 1.0649 | 1.0625 | −0.0004 [−0.0014, +0.0006] |
| Train 2024–25 → test 2026, venue (n = 425) | 1.0872 | 1.0637 | 1.0625 | 1.0618 | −0.0011 [−0.0032, +0.0010] |
| Same, overall (n = 429) | 1.0870 | 1.0593 | 1.0586 | 1.0579 | −0.0008 [−0.0027, +0.0012] |

Brier scores rank the same way; for example, in the first split the baseline
is 0.656, A 0.645 and B 0.645. Per-league baselines are slightly *worse* than
overall rates.

* **Recent form carries real but modest information.** Both methods beat the
  baselines by about 0.015–0.028 in log loss.
* **B is not meaningfully better than A.** Its improvement is about 0.0005 in
  log loss, and every confidence interval includes zero.
* **C is consistently slightly better** (by 0.001–0.003), which supports the
  diagnosis in section 3. It is still small, and no significance test was
  run.

## 7. Sensitivity and robustness

* **Complete vs partial windows:** 94.5% of venue rows have complete windows.
  On complete windows only, the results are unchanged (A 1.0652, B 1.0647).
  Partial windows (178 rows) are too few to evaluate separately.
* **Promoted clubs:** 8.2% of rows involve a window reaching into another
  division. Excluding them changes nothing (A 1.0650, B 1.0648).
* **Bonus triggers** (venue, team windows): won last 3 in 6.5%, scored ≥ 11
  in 8.6%, conceded ≤ 2 in 8.0%. They are rare, so they mainly separate the
  top of the scale.
* **Goal-difference outliers:** only 3.2% of windows reach GD ≥ +9, where the
  cap binds. The cap is not the issue. The issue is the 55% with GD ≤ 0,
  which neither A nor B distinguishes.
* **Venue vs overall:** the conclusions are the same on both. Overall form
  has a slightly lower log loss than venue form for every method.

## 8. Limitations

* Three seasons and four competitions. The current season is partial (EPL
  100 fixtures).
* The outcome model is a one-feature diagnostic. It was not tuned, and it
  says nothing about bookmaker-relative value.
* Bootstrap intervals are for the B − A difference only. C was not tested
  formally.
* The analysis is in-sample with respect to scheme design: Method C was
  suggested by looking at this data.

## 9. Recommendation

**Retain Method A for now. Do not adopt Method B for predictive reasons.**
* B is equally transparent and gives the same ordering (ρ = 0.987).
* It does not improve the relationship with outcomes beyond noise.
* Its only clear benefit is presentational: far fewer ties (85% → 31% of
  fixtures tied in a weekly list).

If tie-breaking in the rankings matters to users, B is a safe like-for-like
swap.

**The more promising direction** is to stop scoring every goal difference of
0 or worse as zero. That is the root cause of the clustering, and the
exploratory symmetric variant (C) shows a small, consistent gain. A proper
follow-up would:
1. fix a candidate rule *before* looking at new data
2. evaluate it on the remaining 2026/27 fixtures as they complete
3. require a bootstrap interval that excludes zero before adoption

No production change has been made.
