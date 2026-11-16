# Research: is the 50/50 blend's advantage just a longer window?

*16 November 2026. Research only: production Form Scores, benchmarks, rankings,
defaults and dropdown options are unchanged.*

**Reproduce:**

```
uv run python scripts/research_form_windows.py
```

* Code: `src/diski9/research/form_blend.py`, specifically `score_n`,
  `window_benchmark` and `build_window_rows`.
* Tests: `tests/test_form_blend_research.py`.
* Outputs: `docs/research/form_windows/`.

## Summary

* **The blend's advantage over the five-match scores comes from history
  length, not from mixing venue and overall information.** Out-of-sample
  performance improves steadily as the overall window grows: 5 → 7 → 8 → 10.
* **Overall-8 matches or slightly beats the 50/50 blend** in every league and
  in both seasons:
  * log loss −0.0048, 95% interval [−0.0095, −0.00004]
  * the interval only just excludes zero, so this is a borderline result
* **Recommendation: Overall-8**, if a production change is approved.
  * It is the simplest option: one window, one league average, no venue
    choice.
  * It is at least as good as the blend.
  * It was named as the follow-up candidate before this run.
* **Overall-10 is not clearly better than Overall-8** (difference −0.0007).
  It is staler, and draws on earlier seasons more often.

## Approaches and the revised formula

| Approach | Window | League benchmark |
|---|---|---|
| Venue | last 5 home (home team) / away (away team) matches | home-form / away-form average |
| Overall-5 | last 5 matches (production) | overall average |
| 50/50 blend | 0.5 × Venue + 0.5 × Overall-5 | 0.5 × venue average + 0.5 × overall average |
| Overall-7 / -8 / -10 | last 7 / 8 / 10 matches | overall average of the same window length |

**Model D generalised to *n* matches** (`score_n`), on the same 0–5 scale and
with the same per-match scaling:

```
points part = 2.5 × P / (3n)                         (P = points, 3n = maximum)
GD part     = 2.5 × (clip(GD, −c, +c) + c) / (2c),   c = 1.8 × n
score       = points part + GD part
```

* The goal-difference cap is production's ±9 over five matches, i.e. **1.8 per
  match**:
  * ±12.6 over seven matches
  * ±14.4 over eight
  * ±18 over ten
* A level goal difference is always worth 1.25. All draws always score 2.08,
  whatever *n* is.
* With *n* = 5 this is exactly production Model D, tested on 2,000 random
  windows.
* **Partial windows:** actual totals over the *n*-match denominator, with no
  prorating, as in production.

**Rules carried over from production:**
* windows may reach earlier seasons or other divisions
* every input is known at kickoff
* each league benchmark uses the production population: point-in-time league
  members, full *n*-match windows only, and at least 12 teams and 80% of
  members

## Data

* **Identical fixture set for all six approaches:** 3,002 fixtures, the same
  population as the blend study.
* **Excluded:** 35 fixtures with a missing score and 200 with no benchmark yet.
* **Out-of-sample test:** walk-forward with monthly refitting, giving 1,713 test
  fixtures from 9 August 2025 to 8 November 2026.
* **Incomplete windows** (a team has fewer than *n* matches):

  | Venue | Overall-5 | Overall-7 | Overall-8 | Overall-10 |
  |---|---|---|---|---|
  | 2.8% | 0.9% | 1.6% | 1.9% | 2.7% |

## Comparison (out of sample, 1,713 fixtures)

Multinomial home/draw/away model on the Form Difference. Lower log loss and
Brier are better. The last column is the paired difference against the 50/50
blend, with a 95% interval clustered by ISO week.

| Approach | Log loss | Brier | − 50/50 blend |
|---|---|---|---|
| Venue | 1.0640 | 0.6428 | +0.0068 [+0.0026, +0.0110] ✔ worse |
| Overall-5 | 1.0607 | 0.6410 | +0.0036 [−0.0010, +0.0079] |
| **50/50 blend** | 1.0572 | 0.6385 | — |
| Overall-7 | 1.0559 | 0.6376 | −0.0013 [−0.0056, +0.0031] |
| **Overall-8** | **1.0523** | **0.6351** | **−0.0048 [−0.0095, −0.00004] ✔ better** |
| Overall-10 | 1.0517 | 0.6347 | −0.0055 [−0.0108, +0.0001] |

**Benchmark-relative framing** (each team minus its league average, as the app
shows):

| Approach | Log loss | − blend |
|---|---|---|
| 50/50 blend | 1.0569 | — |
| Overall-7 | 1.0573 | +0.0004 |
| Overall-8 | 1.0533 | −0.0036 [−0.0089, +0.0018] |
| Overall-10 | 1.0526 | −0.0043 [−0.0099, +0.0015] |
| Venue | 1.0622 | +0.0053 ✔ worse |

**Ranking measures** (full sample, no fitting):

| Approach | Home-win AUC (Form Difference) | Away-win AUC (−Form Difference) | Home-win gap, above − below average | Away-win gap, above − below |
|---|---|---|---|---|
| Venue | 0.589 | 0.611 | 9.8 pts | 7.2 pts |
| Overall-5 | 0.591 | 0.620 | 7.6 pts | 8.0 pts |
| 50/50 blend | 0.599 | 0.628 | 9.6 pts | 10.1 pts |
| Overall-7 | 0.601 | 0.631 | 10.7 pts | 8.9 pts |
| **Overall-8** | **0.605** | **0.635** | **10.8 pts** | **10.2 pts** |
| Overall-10 | 0.609 | 0.640 | 12.3 pts | 9.8 pts |

## By competition and season (out-of-sample log loss)

| Subset | n | Venue | O-5 | Blend | O-7 | O-8 | O-10 | O-8 − Blend |
|---|---|---|---|---|---|---|---|---|
| EPL | 468 | 1.0728 | 1.0609 | 1.0623 | 1.0607 | 1.0586 | **1.0569** | −0.0037 [−0.0141, +0.0068] |
| Championship | 710 | 1.0690 | 1.0732 | 1.0678 | 1.0667 | **1.0626** | 1.0629 | −0.0052 [−0.0137, +0.0031] |
| PSL | 299 | 1.0517 | 1.0490 | 1.0404 | 1.0390 | 1.0369 | **1.0317** | −0.0036 [−0.0147, +0.0068] |
| PSL 1st Division | 236 | 1.0470 | 1.0377 | 1.0363 | 1.0350 | **1.0287** | 1.0330 | −0.0076 [−0.0194, +0.0047] |
| 2025/26 | 1,312 | 1.0650 | 1.0619 | 1.0589 | 1.0555 | 1.0524 | **1.0518** | −0.0065 [−0.0121, −0.0009] ✔ |
| 2026/27 to date | 401 | 1.0606 | 1.0570 | 1.0515 | 1.0571 | 1.0521 | **1.0512** | +0.0007 [−0.0082, +0.0101] |

* Overall-8 beats the blend in all four leagues. None of those differences is
  significant on its own, but they all point the same way.
* In the current season (401 fixtures) the two are level.

## Subsets

* **When venue and overall disagree** (855 test fixtures):

  | Approach | Log loss |
  |---|---|
  | Venue | 1.0720 (significantly worse than the blend) |
  | Overall-5 | 1.0704 |
  | Blend | 1.0645 |
  | Overall-8 | **1.0605** (−0.0040, not significant) |
  | Overall-10 | 1.0656 |

  A longer overall window resolves the conflict at least as well as averaging
  the two.
* **When they agree** (858 fixtures): Overall-10 1.0378 is significantly better
  than the blend at 1.0499. Overall-8 1.0442 is −0.0057, not significant.
* **Home against away teams:**
  * Overall-8 separates home-team outcomes better than Venue or the blend (gap
    10.8 points, against 9.8 and 9.6). So venue form adds no visible advantage
    even for home teams.
  * For away teams it equals the blend (10.2 against 10.1 points).
* **Limited history:** only 58 test fixtures have any incomplete five-match
  window, and only 58 have an incomplete ten-match window. Every interval is
  wide. **No conclusion is possible.**

## Overlap and correlation

* Overall-8 and the blend are highly correlated (r = 0.88 for home-team
  scores).
* Overall-8 correlates with Venue at only 0.72.
* The blend effectively covers 7–8 distinct recent matches, counting the
  overlapping at-venue matches twice. Overall-8 covers 8 distinct matches
  without double counting. That is consistent with the two performing alike.

## Recommendation (needs your approval)

1. **Prefer Overall-8 over the 50/50 blend.**
   * It performs at least as well: slightly better overall, better in every
     league, and level in the current season.
   * It is simpler: one window, one league average, and one plain explanation
     ("last eight matches").
2. **Do not choose Overall-10.** It isn't distinguishable from Overall-8,
   reaches further into earlier seasons, and choosing it would mean picking
   the numerically best of three candidates.
3. **Removing the Venue/Overall selector for Match Result is supported.**
   * Venue-only was significantly worse than every longer-window option.
   * Venue information did not add value even for home teams.
   * With Overall-8 the comparison would use one average, and the selector
     would no longer serve a purpose there.
4. **For BTTS and Over/Under** the selector is a separate question. Milestone
   5.2 found Overall better than or equal to Venue there too, so it could be
   removed app-wide. That needs its own decision.

**If approved, a production change would need:**
* Model D generalised to 8 matches (the formula above)
* a new engine version and cache rebuild
* updated explanations: "last eight matches", GD cap ±14.4
* removal of the selector, if wanted
* a re-check of this evaluation on newly completed fixtures after a few weeks

## Limitations and overfitting concerns

* **Selection:** three longer windows were tested and the shortest
  well-performing one is recommended. Overall-8 was proposed as the follow-up
  candidate in the blend report before this run. The improvement over the
  blend is borderline (upper limit −0.00004), so treat it as "**at least as
  good**", not "better".
* **Small effects:** the differences are about 0.3–0.5% in log loss. The case
  for Overall-8 rests mainly on simplicity plus non-inferiority.
* **Period:** 2.5 seasons of data and one out-of-sample period (August 2025 to
  November 2026). The current season shows no difference yet.
* **Early season:** fixtures without a benchmark (the first weeks of a season)
  are excluded. Longer windows also lean more on previous-season and
  previous-division matches in the early weeks; this was not evaluated
  separately.
* **No bookmaker comparison**, and Form Scores are not probabilities. The
  multinomial model is only a diagnostic.
