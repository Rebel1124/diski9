# Research: venue-specific, overall or blended Diski Form Score?

*16 November 2026. Research only: production Form Scores, rankings, defaults
and dropdown options are unchanged.*

**Reproduce:**

```
uv run python scripts/research_form_blend.py
```

* Code: `src/diski9/research/form_blend.py`.
* Tests: `tests/test_form_blend_research.py`.
* Outputs: `docs/research/form_blend/`.
* The run reuses the Milestone 5.2 evaluation tools: walk-forward folds,
  multinomial model and week-clustered paired bootstrap.

## Question

Manchester City v Fulham is the example. City's home Form Score is 3.81, above
the league home average of 2.72. Its overall score is 2.25, below the league
overall average of 2.41. Which signal is more informative, and would a blend
be better?

## Approaches

These were fixed in the brief before the run:

| Name | Team score | Benchmark (same weight) |
|---|---|---|
| Venue | venue score (home team: home window; away team: away window) | home-form / away-form average |
| 75/25 | 0.75 × venue + 0.25 × overall | 0.75 × venue average + 0.25 × overall average |
| 50/50 | 0.5 × venue + 0.5 × overall | likewise |
| 25/75 | 0.25 × venue + 0.75 × overall | likewise |
| Overall | overall score | overall average |

**Common to all approaches:**
* Production Model D scores.
* Production windows, which may reach earlier seasons or divisions.
* Production league benchmarks (engine 2.3.0).
* Everything as known at kickoff.

## Data

* **Fixtures:** 3,002 eligible completed league fixtures from 2024/25 to 8
  November 2026, where all four scores and all three benchmarks exist.

  | League | Fixtures |
  |---|---|
  | Championship | 1,249 |
  | EPL | 842 |
  | PSL | 512 |
  | PSL 1st Division | 399 |

* **Outcomes:** home 1,283, draw 841, away 878.
* **Excluded:** 35 fixtures with no score for a team, and 200 with no benchmark
  yet (mostly the first weeks of a season).
* **Complete windows:** 97.2% of fixtures have all four windows at five
  matches.
* **Out-of-sample test:** walk-forward monthly from August 2025. Each month's
  model is fitted only on earlier fixtures. That gives 1,713 test fixtures from
  9 August 2025 to 8 November 2026.

## The overlap between the two windows

The venue and overall windows are **not independent**:
* A team's venue window and overall window share **2.26 of their 5 matches on
  average**. In 66% of cases it is exactly 2, and in 29% it is 3.
* The two scores correlate at r = 0.60, both for home and for away teams.

So a blend is not "two separate opinions". It is a score drawn from about 7–8
distinct recent matches, with the most recent at-venue matches counted twice.
Part of any gain from blending is therefore simply **a longer effective window**.

## Results

### Out-of-sample prediction of match outcomes

This uses a multinomial model of home/draw/away on the Form Difference. Log
loss and Brier are lower-is-better; 1,713 test fixtures.

| Approach | Log loss | Brier |
|---|---|---|
| Baseline (outcome frequencies) | 1.0820 | 0.6552 |
| Venue | 1.0640 | 0.6428 |
| 75/25 | 1.0597 | 0.6400 |
| **50/50** | **1.0572** | **0.6385** |
| 25/75 | 1.0577 | 0.6390 |
| Overall | 1.0607 | 0.6410 |
| Venue + overall as two free features | 1.0576 | 0.6388 |

**Paired log-loss differences**, with a 95% interval clustered by ISO week
(✔ means the interval excludes zero):

| Comparison | Difference |
|---|---|
| Venue − Overall | +0.0033 [−0.0039, +0.0112], **no significant difference** |
| 50/50 − Venue | **−0.0068 [−0.0110, −0.0026] ✔** |
| 50/50 − Overall | −0.0036 [−0.0079, +0.0010] |
| 25/75 − Overall | **−0.0030 [−0.0052, −0.0007] ✔** |
| 75/25 − Venue | **−0.0043 [−0.0064, −0.0023] ✔** |
| Two free features − Overall | −0.0031 [−0.0073, +0.0013] |
| Overall − Baseline | −0.0213 [−0.0301, −0.0128] ✔ |

**The benchmark-relative version** feeds the model each team's score minus its
league average, which is exactly what the app shows. It gives the same
ordering: 50/50 1.0569, Venue 1.0622, Overall 1.0614. Here 50/50 − Venue is
−0.0053, with an interval that excludes zero.

**Fitting free weights** to the venue and overall Form Differences does no
better than a fixed 50/50 split. The data points to a roughly even blend, and
nothing is gained by tuning the weight.

### The above/below indicator itself

This is the full sample of 3,002 fixtures, using the indicator exactly as the
app displays it.

| Approach | Home win, home team above | Home win, home team below | Away win, away team above | Away win, away team below | AUC (home win) | AUC (away win) |
|---|---|---|---|---|---|---|
| Venue | 47.7% (1,492) | 37.8% (1,506) | 33.1% (1,422) | 25.9% | 0.572 | 0.571 |
| 75/25 | 47.8% | 37.9% | 33.6% | 25.1% | 0.576 | 0.578 |
| **50/50** | 47.7% | 38.1% | **34.4%** | **24.3%** | **0.577** | **0.580** |
| 25/75 | 47.4% | 38.5% | 33.5% | 24.8% | 0.574 | 0.578 |
| Overall | 46.6% | 39.1% | 33.2% | 25.2% | 0.569 | 0.573 |

AUC measures the benchmark-relative score as a ranking of the team's own win;
0.5 means no information. The differences between approaches are small, about
0.01 in AUC.

### Disagreement

* **How often:** the venue and overall indicators disagree for **30.7% of home
  teams** and **29.3% of away teams**. In **51.1% of fixtures** at least one
  team has conflicting indicators.

**Home team's win rate** (n, 95% interval):

| Venue | Overall | Win rate |
|---|---|---|
| above | above | **50.0%** (1,008) [46.9, 53.1] |
| above | below | 42.8% (484) [38.4, 47.2] |
| below | above | 38.9% (437) [34.3, 43.5] |
| below | below | **37.5%** (1,073) [34.6, 40.4] |

**Away team's win rate:**

| Venue | Overall | Win rate |
|---|---|---|
| above | above | **34.5%** (1,036) [31.6, 37.4] |
| above | below | 29.3% (386) [24.7, 33.8] |
| below | above | 30.4% (493) [26.4, 34.5] |
| below | below | **23.7%** (1,087) [21.2, 26.3] |

When the two disagree, results fall **between** the agree-above and
agree-below groups, and **neither signal clearly wins**:
* For home teams, venue-above / overall-below is slightly better (42.8% against
  38.9%), but the intervals overlap.
* For away teams it is the reverse (29.3% against 30.4%).

That is the pattern you would expect if both carry part of the information,
which is why averaging them helps. Out of sample, on the 855 test fixtures with
a disagreement, 50/50 again does best (1.0645), against Venue 1.0720 and
Overall 1.0704. No difference is significant on this subset.

### Home and away teams

* For **home teams**, venue form separates outcomes as well as the blends do:
  the gap between "above" and "below" is about 10 points for Venue, 75/25 and
  50/50.
* For **away teams**, overall information adds more: the gap grows from 7.2
  points for Venue to 10.1 points for 50/50. Away-only windows are noisier.

### Limited history

Only 58 test fixtures have a team with fewer than five matches in any window.
Overall does best there (1.099, against Venue 1.129), but the intervals are wide
(Venue − Overall +0.030 [−0.016, +0.078]). **Insufficient evidence.**

### Competitions and periods

Out-of-sample log loss:

| Subset | n | Venue | 75/25 | 50/50 | 25/75 | Overall |
|---|---|---|---|---|---|---|
| EPL | 468 | 1.0728 | 1.0671 | 1.0623 | **1.0602** | 1.0609 |
| Championship | 710 | 1.0690 | **1.0676** | 1.0678 | 1.0700 | 1.0732 |
| PSL | 299 | 1.0517 | 1.0442 | **1.0404** | 1.0425 | 1.0490 |
| PSL 1st Division | 236 | 1.0470 | 1.0409 | 1.0363 | **1.0353** | 1.0377 |
| 2025/26 | 1,312 | 1.0650 | 1.0612 | **1.0589** | 1.0593 | 1.0619 |
| 2026/27 to date | 401 | 1.0606 | 1.0547 | **1.0515** | 1.0526 | 1.0570 |

* In every league and in both periods, **a blend beats both pure options**.
  The best weight is between 25/75 and 75/25.
* Venue against Overall varies: Overall is better in the EPL and 1st Division,
  Venue in the Championship. No league-level difference is significant.

## Conclusions

1. **Best approach:** an equal blend (50/50) of venue and overall Form Score.
   * It has the best log loss overall and in both periods.
   * It is best or near-best in every league.
   * It matches a model that fits the weights freely, so it is not an
     overfitted weight.
2. **Do blends improve on the pure options?**
   * Against **Venue-only: yes, significantly** (−0.0068 log loss; the interval
     excludes zero).
   * Against **Overall-only: modestly**. 50/50 gives −0.0036, borderline. 25/75
     gives −0.0030, with an interval that excludes zero.
3. **Venue against Overall:** no significant difference between the two.
4. **Disagreement is common** (half of fixtures) and neither signal dominates.
   Averaging them is the natural resolution.
5. **Effect size:** the gains are real but small, about 0.3–0.6% in log loss.
   Most of the benefit comes from using more recent matches (about 7–8 distinct
   matches instead of 5).

**Recommendation (research only; approval needed for any change):**
* The evidence supports a **blended approach** over either pure option, most
  clearly over Venue-only.
* If adopted, the simplest user-facing form is a single "Diski Form Score"
  shown as the 50/50 blend, with the same blended league average. The Overall
  or Venue-specific choice would then not be needed for the Match Result
  comparison.
* Because the gain is largely a longer-window effect, a fair alternative to
  test first is a single **overall window of 8 matches**. It may be equally
  good and easier to explain. This was not tested here.

## Limitations

* About 2.5 seasons and four leagues. The out-of-sample test is 1,713 fixtures,
  and the differences are small relative to match noise.
* Many comparisons were made (about 20 pairs). Only the blend-versus-Venue
  result is robust across framings. The blend-versus-Overall result is
  borderline.
* The benchmark exists only once 12 teams and 80% of the league have full
  windows, so the opening weeks of each season are excluded (200 fixtures).
  Conclusions do not cover early-season fixtures.
* The two windows overlap, so the approaches are strongly correlated (r = 0.6).
  The "disagreement" groups are defined by thresholds on correlated scores.
* No bookmaker odds are available historically, so nothing here says whether
  any Form Score adds information beyond the market.
* Form Scores are not probabilities. The multinomial model is a diagnostic,
  not a Diski 9 forecast.
