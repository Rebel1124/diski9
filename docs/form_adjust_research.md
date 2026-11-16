# Research: is six matches enough, and does a venue adjustment help?

*16 November 2026. Research only: production scores, benchmarks, rankings,
filters and UI are unchanged.*

**Reproduce:**

```
uv run python scripts/research_form_adjust.py
```

* Code: `src/diski9/research/form_adjust.py`.
* Tests: `tests/test_form_adjust_research.py`.
* Outputs: `docs/research/form_adjust/summary.json` and the CSV.
* Methods:
  * scores use the normalised Model D of the window study: points part
    2.5 × P/(3n); goal-difference part capped at ±1.8 per match
  * walk-forward with monthly refitting from August 2025
  * paired bootstrap clustered by ISO week

## Answers

| Question | Answer |
|---|---|
| 1. Is Overall-6 materially worse than Overall-8? | **Yes.** Overall-6 is no better than Overall-5. Overall-8 beats it by −0.0078 log loss [−0.0127, −0.0029]. The gain comes after the opening weeks. **In the first eight weeks all windows perform the same**, so the early-season concern about Overall-8 is not borne out. |
| 2. Does a venue adjustment improve on a simple Overall score? | **Not on Overall-8.** The best result is −0.0004 [−0.0025, +0.0019]. It helps Overall-6 slightly (about −0.0025, borderline), but Overall-6 with any adjustment remains worse than plain Overall-8. |
| 3. Is a league-relative adjustment more informative than a raw one? | **Marginally, and not meaningfully.** The differences are 0.0003–0.0007 log loss, within noise. |
| 4. Is any improvement worth the extra complexity? | **No.** |
| 5. Simplest defensible methodology? | **Overall-8 alone**, as the single headline score and comparison. No venue adjustment, no selector. |

## Data

* **Fixtures with every score:** 3,202 eligible league fixtures from 2024/25 to
  8 November 2026, across EPL, Championship, PSL and PSL 1st Division.
  35 fixtures were excluded for having no score.
* **Benchmarked sample:** 3,002 fixtures where every league benchmark exists
  (the same population as the earlier studies). This is the identical sample
  for all Question 2 comparisons. 200 fixtures in the opening weeks have no
  benchmark yet.
* **Early-season sample:** the first-eight-weeks analysis uses all 3,202
  fixtures, because the Form Difference itself needs no benchmark.
* **Out-of-sample tests:** 1,713 fixtures (benchmarked sample) and 1,822 (all
  fixtures), 9 August 2025 to 8 November 2026.

## Question 1 — Window length

### Out-of-sample performance

Multinomial model on the Form Difference; the benchmarked sample has 1,713 test
fixtures.

| Window | Log loss | Brier | Home-win AUC | Away-win AUC | − Overall-8 |
|---|---|---|---|---|---|
| Overall-5 | 1.0607 | 0.6410 | 0.591 | 0.620 | +0.0084 [+0.0030, +0.0135] ✔ |
| Overall-6 | 1.0601 | 0.6406 | 0.592 | 0.619 | **+0.0078 [+0.0029, +0.0127] ✔** |
| Overall-7 | 1.0559 | 0.6376 | 0.601 | 0.631 | +0.0035 [+0.0000, +0.0069] ✔ |
| **Overall-8** | **1.0523** | **0.6351** | **0.605** | **0.635** | — |

* Overall-6 against Overall-5: −0.0006 [−0.0027, +0.0038], **no gain**.
* Overall-7 against Overall-6: −0.0042, significant.
* The step from five to six matches adds nothing. The improvement starts at
  seven.
* All 1,822 fixtures with scores give the same picture: Overall-6 − Overall-8
  is +0.0073 [+0.0030, +0.0117].

### Early season against the rest of the season (1,822 test fixtures)

| Subset | n | Overall-5 | Overall-6 | Overall-7 | Overall-8 | Overall-6 − Overall-8 |
|---|---|---|---|---|---|---|
| First 8 weeks of the competition's season | 522 | 1.0865 | 1.0884 | 1.0875 | 1.0877 | +0.0007 [−0.0048, +0.0060] |
| After week 8 | 1,300 | 1.0548 | 1.0538 | 1.0486 | **1.0439** | **+0.0100 [+0.0049, +0.0151] ✔** |

* In the opening weeks **every window is equally weak**, about 1.088 against a
  baseline near 1.09.
* Overall-8 is **not worse** than Overall-6 early, even though most of its
  matches come from last season.
* After week 8 the longer window is clearly better.

### Responsiveness and provenance

| Window | Windows reaching an earlier season or division (all / first 8 weeks) | Median age of oldest match (all / first 8 weeks) | Mean change in score after each new match |
|---|---|---|---|
| Overall-5 | 15.8% / 65.4% | 38 / 113 days | 0.44 |
| Overall-6 | 19.1% / 78.4% | 47 / 126 days | 0.38 |
| Overall-7 | 22.3% / 87.8% | 56 / 133 days | 0.32 |
| Overall-8 | 25.6% / 92.8% | 64 / 140 days | 0.28 |

* **The trade-off is real but modest.**
  * Overall-8 reacts about a third less to each new result than Overall-5
    (0.28 against 0.44 points of score).
  * Its oldest match is typically two months old.
  * In the first eight weeks almost all of its windows include last season's
    or another division's matches. That is already true for 78% of Overall-6
    windows.
* **Even so, the slower, longer score predicts outcomes better.** Five or six
  matches are mostly noise.
* **Presentation:** if Overall-8 is adopted, the "Matches used" list will show
  more earlier-season matches in August and September. The existing season and
  division labels already cover this.

## Question 2 — Venue adjustment

**Definitions.** For base window *n*, the adjustment for each team is:
* **Raw:** venue form (home team's last 5 home matches; away team's last 5 away
  matches) − overall-*n* form.
* **League-relative:** (venue form − league venue average) − (overall-*n* form −
  league overall-*n* average).

The comparison then uses overall-*n* + *w* × adjustment, with the predeclared
weights *w* = 0, 0.25 and 0.5. As a diagnostic only, a model was also allowed
to fit the weight freely in each fold.

**Team level or match level?** For the Form Difference they are **mathematically
identical**: (h + w·a_h) − (a + w·a_a) = (h − a) + w·(a_h − a_a). This is tested.

* The choice is purely about presentation.
* Applying it at match level would leave each team's headline Form Score
  unchanged, which matches your preference. As the results show, it isn't
  needed.

### Out-of-sample performance (identical 1,713 test fixtures)

| Method | Log loss | Brier | − its own base |
|---|---|---|---|
| A. Overall-6 | 1.0601 | 0.6406 | — |
| C. Overall-6 + raw 0.25 | 1.0577 | 0.6390 | −0.0024 [−0.0046, −0.0001] ✔ |
| C. Overall-6 + raw 0.5 | 1.0577 | 0.6389 | −0.0024 [−0.0065, +0.0022] |
| E. Overall-6 + league-relative 0.25 | 1.0573 | 0.6387 | −0.0028 [−0.0050, −0.0004] ✔ |
| E. Overall-6 + league-relative 0.5 | 1.0566 | 0.6381 | −0.0035 [−0.0079, +0.0014] |
| **B. Overall-8** | **1.0523** | **0.6351** | — |
| D. Overall-8 + raw 0.25 | 1.0523 | 0.6352 | −0.0000 [−0.0020, +0.0021] |
| D. Overall-8 + raw 0.5 | 1.0549 | 0.6369 | +0.0026 [−0.0013, +0.0068] |
| F. Overall-8 + league-relative 0.25 | **1.0519** | **0.6349** | −0.0004 [−0.0025, +0.0019] |
| F. Overall-8 + league-relative 0.5 | 1.0538 | 0.6361 | +0.0015 [−0.0027, +0.0059] |
| *Diagnostic:* Overall-8 + free raw weight | 1.0531 | 0.6357 | +0.0008 |
| *Diagnostic:* Overall-8 + free league-relative weight | 1.0525 | 0.6353 | +0.0001 |

* **On Overall-6,** a venue adjustment recovers part of the gap. That is
  consistent with it simply adding more recent matches, the same effect found
  in the blend study.
* **On Overall-8 it adds nothing.** Even a freely fitted weight does not help.
* **Overall-8 alone (1.0523) beats every Overall-6 variant**; the best is 1.0566.

### Ranking measures (full benchmarked sample, 3,002 fixtures)

| Method | Home-win AUC | Away-win AUC |
|---|---|---|
| Overall-6 | 0.592 | 0.619 |
| Overall-6 + league-relative 0.25 | 0.599 | 0.627 |
| Overall-8 | 0.605 | 0.635 |
| Overall-8 + raw 0.25 | 0.607 | 0.636 |
| Overall-8 + league-relative 0.25 | 0.608 | 0.636 |

The adjustment adds at most +0.003 AUC to Overall-8, for both home and away
teams.

### Subsets

| Subset | n | Overall-6 | Overall-8 | Overall-8 + rel 0.25 | Overall-8 + rel 0.25 − Overall-8 | Overall-8 − Overall-6 |
|---|---|---|---|---|---|---|
| Venue and overall disagree | 732 | 1.0693 | **1.0539** | 1.0548 | +0.0009 [−0.0029, +0.0050] | **−0.0154 ✔** |
| They agree | 981 | 1.0532 | 1.0512 | **1.0497** | −0.0014 [−0.0035, +0.0007] | −0.0021 |
| Limited history (some window < 5) | 58 | **1.0975** | 1.1038 | 1.1067 | +0.0029 | +0.0064, not significant |

* When venue and overall form disagree, the venue adjustment does **not** help
  Overall-8. The longer window resolves the conflict best.
* The limited-history sample (58 fixtures) is too small to conclude anything.

### By competition and season (log loss)

| Subset | n | Overall-6 | Overall-8 | Overall-8 + raw 0.25 | Overall-8 + rel 0.25 | Overall-8 − Overall-6 | rel 0.25 − Overall-8 |
|---|---|---|---|---|---|---|---|
| EPL | 468 | 1.0639 | **1.0586** | 1.0602 | 1.0595 | −0.0053 [−0.0124, +0.0018] | +0.0008 |
| Championship | 710 | 1.0717 | 1.0626 | 1.0620 | **1.0619** | **−0.0091 ✔** | −0.0007 |
| PSL | 299 | 1.0442 | 1.0369 | 1.0348 | **1.0329** | −0.0073 | −0.0040 [−0.0087, +0.0013] |
| PSL 1st Division | 236 | 1.0378 | **1.0287** | 1.0297 | 1.0309 | −0.0091 | +0.0022 |
| 2025/26 | 1,312 | 1.0601 | 1.0524 | 1.0528 | 1.0527 | **−0.0078 ✔** | +0.0003 |
| 2026/27 to date | 401 | 1.0600 | 1.0521 | 1.0505 | **1.0494** | −0.0078 | −0.0027 [−0.0075, +0.0023] |

* **Overall-8 beats Overall-6 in every league and both seasons.**
* The venue adjustment's effect on Overall-8 changes sign between leagues. That
  is what noise looks like, not a stable effect.
* The PSL and the current season lean slightly favourable, but neither is
  significant.

### Properties of the adjustment

* The match-level adjustment (home adjustment − away adjustment) correlates
  negatively with the Overall-8 difference: r = −0.21 (raw) and −0.22
  (league-relative).
* That is mostly regression to the mean: teams whose recent overall run is
  extreme tend to have venue runs that are less extreme. It partly offsets
  noise in short windows, which is why it helps Overall-6 but not Overall-8.

## Recommendation (needs your approval)

**Adopt Overall-8 alone** as the single Diski Form Score for Match Result, with
the matching overall league average. Do not add a venue adjustment, a third
option or a Home Advantage Score.

* Six matches is not enough. It is no better than five, and clearly worse than
  eight after the opening weeks.
* Eight matches is not worse early in the season, though all windows are weak
  then.
* Venue information adds nothing measurable once the window is eight matches,
  whether raw or league-relative, team-level or match-level.
* The Venue/Overall selector can be removed for Match Result. For BTTS and
  Over/Under it remains a separate decision.

**If approved, a production change would include:**
* the normalised eight-match Model D (points 2.5 × P/24; goal difference capped
  at ±14.4)
* a new engine version and cache rebuild
* updated explanations
* removing the Match Result basis selector, if wanted
* a re-check on newly completed fixtures after a few weeks

## Limitations and multiple-comparison note

* **Multiple comparisons:** about 30 pairwise tests across the three studies.
  The individually "significant" venue-adjustment results on Overall-6
  (−0.0024 and −0.0028, intervals just excluding zero) would not survive a
  correction.
  * The Overall-8 versus Overall-6 result (−0.0078) is consistent across every
    league, season and sample, and would survive one.
  * The weights were predeclared (0, 0.25, 0.5). The free-weight diagnostic
    confirms that no other weight would have changed the conclusion.
* **Selection:** Overall-8 was chosen in the previous study from 5/7/8/10. This
  study re-tests it against 6 rather than tuning further.
* **Coverage:** 2.5 seasons of data and one out-of-sample period. The
  first-eight-weeks analysis has 522 fixtures, enough to show that no window
  is much better, not to rank them.
* **Gaps:** limited-history fixtures are too few (58) to evaluate. There are no
  historical bookmaker odds, so nothing here says whether form adds anything
  beyond the market. Form Scores are not probabilities; the outcome model is a
  diagnostic.
