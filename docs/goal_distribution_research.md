# Research: one goal-distribution model for 1X2, BTTS and Over/Under 2.5

*16 November 2026. Research only: Engine 2.4.0, the Screener UI, the Form Score,
the database schema and the production cache are unchanged. No bookmaker prices,
implied probabilities or consensus enter any model, tuning step or selection.*

**Reproduce:**

```
uv run python scripts/research_goal_distribution.py
```

* Code: `src/diski9/research/goal_distribution.py` (models, maths, dataset) and
  `scripts/research_goal_distribution.py` (walk-forward backtest).
* Tests: `tests/test_goal_distribution_research.py`.
* Outputs: `docs/research/goal_model/` (`summary.json`, `overall_metrics.csv`,
  `segments.csv`, `tuning_surface.csv`, `poisson_scorelines.csv`, `coverage.csv`,
  `calibration.svg`). Reruns are identical apart from the timestamp.

## A. Executive summary

1. **The approach is viable, with one honest caveat.** A single pair of estimated
   goals gives credible, well-calibrated probabilities for all three markets
   on 3,237 out-of-sample fixtures:
   * **Match Result:** clearly better than the league baseline. Log loss falls
     from 1.084 to 1.045, and the 95% interval for the gain excludes zero. It
     also beats a calibrated version of today's Form Score (by 0.009, interval
     excludes zero). Its calibration slope is 1.00, meaning the probabilities
     are neither too extreme nor too timid.
   * **BTTS and Over/Under:** as good as quoting the league's own rate, and
     not meaningfully better. Within a league, past goals say very little about
     how many goals a particular fixture will have. The model is honest about
     this: its BTTS and Over/Under estimates stay close to the league average
     (almost all between 30% and 70%).
2. **Most promising model:** a **season-to-date Poisson model with shrinkage
   towards the league average**. Team quality is split into two parts:
   * **strength** (who tends to win), shrunk moderately
   * **goal tempo** (how many goals a team's games have), shrunk heavily

   This "strength/tempo" version beat every other candidate on all three
   markets. It has two smoothing constants, and the walk-forward tuning chose
   the same values every season (12 and about 96).
3. **Season-to-date beats rolling windows.** The last 8 or last 10 matches were
   significantly worse for Match Result (1X2), particularly mid- and late-season,
   and their estimates jumped about two to three times as much between fixtures.
   A recency-weighted version tuned itself to a 20-match half-life, which is
   effectively season-to-date, and was no better.
4. **Home advantage works best through the league's home and away scoring
   rates, not team-specific home and away records.** Given free choice, the
   tuning shrank team venue records almost completely away (k_v = 192). Raw
   venue-specific rates were the worst candidates tested.
5. **Early-season smoothing works.** Raw rates produce absurd estimates. A team
   that has not yet scored gets 0 estimated goals, and 16% of fixtures get a
   favourite above 75% that wins only 52% of the time. The smoothed model ranges
   from 0.45 to 3.25 estimated goals and is calibrated from round one. It still
   beats the league baseline for Match Result in the early-season third.
6. **One model can reasonably support all three markets.** Changing either
   estimated goal value recomputes all seven probabilities consistently (example
   in section E2).

**Recommendation:** adopt the simple Poisson strength/tempo goal model as the
candidate for the next Screener, with the caveats in section E. Confidence is
**high** for Match Result and **moderate** for BTTS and Over/Under, which are
honest but little better than the league average.

## 1. Data

* **Competitions:** EPL, Championship, PSL, PSL 1st Division.
* **Seasons:** 2023/24 to 2026/27, up to 8 November 2026.
* **Eligible completed league fixtures: 4,649.** Goals are available for every
  one.
* **Venue:** nominal home and away from the fixture. No confirmed neutral-venue
  league matches.
* **Fixtures not used** (by status):
  * not started: 972
  * cancelled: 20
  * play-off rounds: 17
  * promotion rounds: 10
  * postponed: 7
  * relegation rounds: 6
  * awarded: 1

| League | 2023/24 (tuning only) | 2024/25 | 2025/26 | 2026/27 |
|---|---|---|---|---|
| EPL | 380 (350 predictable) | 380 | 380 | 100 |
| Championship | 552 (517) | 552 | 552 | 180 |
| PSL | 240 (210) | 221 | 240 | 73 |
| PSL 1st Division | 240 (210) | 240 | 239 | 80 |

* **Out-of-sample predictions: 3,237.** That is every completed fixture of the
  three test seasons, including the opening rounds. **No test fixture is
  excluded.**
* The only unpredictable fixtures are 125 opening-round matches of 2023/24. No
  2022/23 season is stored, so no league prior exists for them. 2023/24 is used
  only for tuning.
* **Team statistics** use the current season and current competition only, and
  only matches that kicked off before the fixture. Earlier seasons and other
  divisions never enter a team's numbers.

## 2. Evaluation protocol

* **Expanding window by season.**
  * 2024/25 is predicted with settings tuned on 2023/24.
  * 2025/26 with settings tuned on 2023/24–2024/25.
  * 2026/27 with settings tuned on 2023/24–2025/26.
* **Tuning criterion:** the mean log-probability of the actual scoreline. This
  is the model's own likelihood, one criterion for all three markets, and
  involves no odds.
* **Metrics** for each market:
  * log loss and Brier score (lower is better)
  * calibration error (ECE)
  * calibration slope (1 = right spread; below 1 = too extreme; above 1 = too
    timid)
* **Paired differences:** 95% bootstrap intervals, resampling whole ISO weeks
  (89 clusters).
* **Identical fixture set:** all candidates are scored on the same 3,237
  fixtures.
* **League baseline:** the competition's current-season home win / draw / away
  win, BTTS and Over 2.5 frequencies before kickoff. These are blended with 30
  pseudo-matches at the previous season's league-level rate, the same prior the
  models use.

## B. Methodology

### B1. League baselines

H and A are league home and away goals per match before kickoff:

    H = (home goals in current-season league matches + m0 × previous-season home goals per match)
        ÷ (current-season league matches + m0),   m0 = 30

* A is computed the same way from away goals.
* The prior is **league-level only**: the same competition's previous-season
  average, with no team results.
* After 30 current-season matches (about three rounds) the current season
  carries half the weight; after 300 it carries 91%.
* **Strict alternative:** without the prior, estimates are **unavailable**
  until 30 current-season matches exist. That makes 382 of the 3,237 test
  fixtures (12%) unavailable (see B6).
* **Future seasons are never used.** The prior is the season that has already
  finished. The current-season sums include only matches before kickoff.

### B2. Team attack and defence (the denominators)

For a team with n_h home and n_a away matches so far:

    expected goals scored at league rates     E_for = n_h × H + n_a × A
    expected goals conceded at league rates   E_ag  = n_h × A + n_a × H

    attack  a = (goals scored   + k × g) ÷ (E_for + k × g)
    defence d = (goals conceded + k × g) ÷ (E_ag  + k × g),    g = (H + A) ÷ 2

* Each match is measured against the league rate **for the venue it was played
  at**:
  * home goals scored against H, away goals scored against A
  * goals conceded at home against A, conceded away against H
* So a team that played more home games is not flattered. This is the venue
  bookkeeping the brief asked for, applied to the team's whole record.
* `k` is a number of pseudo-matches at exactly league-average performance
  (factor 1). This is the shrinkage.
* With k > 0, a team that has not scored never gets a zero factor. That removes
  the multiplicative model's zero instability.

### B3. Strength and goal tempo (the recommended refinement)

    strength s = √(a_s ÷ d_s)      from a, d computed with k = k_s
    tempo    t = √(a_t × d_t)      from a, d computed with k = k_t

* `strength` above 1 means the team outscores the league; `tempo` above 1 means
  its games have more goals than average.
* With a single k (k_s = k_t) this is exactly the plain attack × defence model.

### B4. Estimated goals

    estimated home goals  λ_home = H × (s_home ÷ s_away) × t_home × t_away
    estimated away goals  λ_away = A × (s_away ÷ s_home) × t_home × t_away

* This is the multiplicative model λ_home = H × attack(home) × defence(away) in
  a different parameterisation. It satisfies the denominator rules in the brief:
  the home side is measured against H and the away side against A.
* **Home advantage** comes entirely from H > A in the current league data. There
  is no separate adjustment.
* **Optional venue-specific factors** (tested; not recommended):
  * home attack = (home goals scored + k_v × H × a) ÷ (H × (n_h + k_v))
  * defined likewise for home defence, away attack and away defence
  * team venue records are shrunk towards the team's own overall factor

### B5. Shrinkage strengths: selection and influence

**Selection.**
* Grid search, by season, on earlier seasons only:
  * k_s ∈ {0.5 … 32}
  * k_t ∈ {8 … 256, ∞}
  * k_v ∈ {1 … 192, ∞}
* Chosen:
  * k_s = 12 every season
  * k_t = 128, then 96, then 96
* The surface is flat near the optimum. The full table is in
  `tuning_surface.csv`.

**Share of a team's factor that comes from the league average:**

| Matches played | 0 | 1 | 2 | 3 | 5 | 10 | 20 | 38 |
|---|---|---|---|---|---|---|---|---|
| Strength (k_s = 12) | 100% | 92% | 86% | 80% | 71% | 55% | 38% | 24% |
| Tempo (k_t = 96) | 100% | 99% | 98% | 97% | 95% | 91% | 83% | 72% |

* **Tempo is shrunk hard because, empirically, teams' goal totals regress
  strongly to the league mean.** Most of the difference in goal totals between
  teams over a season is noise.
* Strength is real and becomes the team's own record over a season.

**What each stage of the season does:**

* **0 matches:** λ_home = H and λ_away = A (pure league averages). This is
  neutral, and should be labelled "league average only" (B6).
* **1 match, e.g. a 4–0 home win:**
  * strength 1.107 and tempo 1.005
  * against an average team at home: λ = 1.67 v 1.09 (league: 1.50 v 1.20)
  * win probability 51% instead of 44%
  * raw rates would give an attack factor of 2.67, and every future opponent
    0 estimated goals
* **2–3 matches:** the league still provides 80–86% of strength.
* **Zero home or zero away matches:** no special case is needed. The
  recommended model uses the team's whole record, measured against venue-correct
  league rates.

**Where smoothing is applied:** to the attack and defence factors, as
pseudo-matches at factor 1 counted in expected-goal units. It is not applied to
raw goal rates (which would mix venue effects) or to the final λ.

### B6. Availability rule

* With the previous-season league prior, every fixture is predictable from
  round one.
* **Early-season log loss** with m0 = 10, 30 and 100:
  * 1X2: 1.065, 1.061, 1.059
  * Over/Under: 0.674, 0.673, 0.672
* Larger m0 is marginally better, but the differences are within noise, so
  m0 = 30 is kept, matching the production league baseline minimum.
* **Strict alternative:** no prior, and unavailable until 30 current-season
  matches exist. This hides 382 fixtures (12%) and gains nothing in accuracy.

**Recommendation:**
* Show estimates from round one. Label teams with no current-season matches as
  "League average only".
* Show an early-season note until both teams have about five matches.
* The league-level prior is historical football data, not a fabricated value.
  It reflects last season's composition, though: promoted and relegated clubs
  differ, so it is down-weighted as the season grows.

### B7. Goal distributions and market probabilities

* Home goals ~ Poisson(λ_home) and away goals ~ Poisson(λ_away), independent:
  P(i, j) = P_home(i) × P_away(j).
* **Grid.** Goals run from 0 to G − 1 with G = ⌈λ + 12√λ + 26⌉, so the tail
  beyond is below 10⁻¹⁵ (tested). The probabilities are:

      P(home win) = Σ_j P_away(j) × P(home goals > j)
      P(draw)     = Σ_j P_home(j) × P_away(j)
      P(away win) = 1 − P(home win) − P(draw)
      P(BTTS yes) = (1 − P_home(0)) × (1 − P_away(0))
      P(Under 2.5) = sum of the six scorelines with at most 2 goals
      complements:  BTTS No = 1 − Yes,  Over = 1 − Under

* Each market sums to 1 exactly.
* Tests check every value against independent closed forms: the Skellam
  distribution for the 1X2 probabilities, and the Poisson total-goals
  distribution for Under 2.5.

**Assumptions versus evidence:**
* *Assumed:* Poisson goal counts, independence between the two teams'
  goals, and the multiplicative structure.
* *Supported by the data:*
  * the goals are not over-dispersed (Pearson dispersion 0.96 home, 0.95 away)
  * total-goal frequencies are close to expected (table in D2)
  * the probabilities are calibrated (section C)
* *Not supported:* the draw rate is under-predicted (D2).

## C. Comparative results (3,237 out-of-sample fixtures)

| Candidate | 1X2 log loss | 1X2 Brier | BTTS log loss | BTTS Brier | O/U log loss | O/U Brier | Calibration slope 1X2 / BTTS / O/U | Interpretability |
|---|---|---|---|---|---|---|---|---|
| League baseline (frequencies) | 1.0840 | 0.6563 | 0.6879 | 0.2473 | 0.6773 | 0.2421 | – / 0.69 / 0.79 | very high |
| League Poisson (λ = H, A) | 1.0806 | 0.6544 | 0.6883 | 0.2476 | 0.6779 | 0.2425 | – / 0.73 / 0.89 | very high |
| Raw overall rates (no smoothing) | 1.5486 | 0.6651 | 1.2598 | 0.2722 | 0.8521 | 0.2650 | 0.09 / 0.03 / 0.08 | high, unusable |
| Raw venue rates (no smoothing) | 2.2814 | 0.7099 | 1.9633 | 0.2903 | 1.0310 | 0.2783 | 0.04 / 0.03 / 0.05 | high, unusable |
| A. Season-to-date, one k | 1.0478 | 0.6314 | 0.6900 | 0.2483 | 0.6799 | 0.2434 | 1.20 / 0.65 / 0.73 | high |
| A. Season-to-date, venue-specific | 1.0491 | 0.6323 | 0.6890 | 0.2479 | 0.6788 | 0.2429 | 1.25 / 0.68 / 0.76 | medium |
| **A. Season-to-date, strength/tempo** | **1.0452** | **0.6299** | **0.6875** | **0.2472** | **0.6764** | **0.2418** | **1.00 / 0.78 / 0.89** | high |
| B. Rolling 8 | 1.0561 | 0.6370 | 0.6906 | 0.2486 | 0.6824 | 0.2446 | 1.11 / 0.61 / 0.67 | high |
| C. Rolling 10 | 1.0537 | 0.6354 | 0.6909 | 0.2488 | 0.6833 | 0.2450 | 1.11 / 0.61 / 0.65 | high |
| D. Recency-weighted (half-life 20) | 1.0474 | 0.6311 | 0.6897 | 0.2482 | 0.6800 | 0.2434 | 1.22 / 0.66 / 0.72 | medium |
| Smoothed empirical distributions | 1.0693 | 0.6459 | 0.6879 | 0.2474 | 0.6772 | 0.2421 | 2.19 / 0.68 / 0.85 | medium |
| *Reference: Form Score (last 8) + fitted logistic, 1X2 only* | 1.0542 | 0.6361 | – | – | – | – | – | high |

Calibration error (ECE) of the strength/tempo model:

| Market | Model | League baseline |
|---|---|---|
| Home win | 0.017 | 0.021 |
| Draw | 0.021 | 0.023 |
| Away win | 0.015 | 0.025 |
| BTTS | 0.024 | 0.019 |
| O/U | 0.013 | 0.020 |

Reliability diagrams: `docs/research/goal_model/calibration.svg`.

**Paired log-loss differences** (negative = first candidate better, 95%
interval):

| Comparison | 1X2 | BTTS | O/U |
|---|---|---|---|
| Strength/tempo − league baseline | **−0.039 [−0.047, −0.030]** | −0.000 [−0.003, +0.003] | −0.001 [−0.004, +0.002] |
| Strength/tempo − season-to-date, one k | **−0.003 [−0.004, −0.001]** | **−0.002 [−0.005, −0.000]** | **−0.004 [−0.007, −0.000]** |
| Rolling 8 − strength/tempo | **+0.011 [+0.006, +0.016]** | **+0.003 [+0.001, +0.005]** | **+0.006 [+0.002, +0.010]** |
| Rolling 10 − strength/tempo | **+0.009 [+0.004, +0.013]** | **+0.003 [+0.001, +0.006]** | **+0.007 [+0.003, +0.011]** |
| Recency-weighted − strength/tempo | **+0.002 [+0.000, +0.004]** | **+0.002 [+0.000, +0.004]** | **+0.004 [+0.000, +0.007]** |
| Venue-specific − strength/tempo | **+0.004 [+0.002, +0.006]** | +0.001 [−0.000, +0.003] | +0.002 [−0.001, +0.006] |
| Empirical − strength/tempo | **+0.024 [+0.018, +0.030]** | +0.000 [−0.003, +0.004] | +0.001 [−0.001, +0.003] |
| Strength/tempo − Form Score reference | **−0.009 [−0.016, −0.003]** | – | – |

**Reading the size of these numbers:**
* A 1X2 log-loss gain of 0.039 is about 3.6% of the league baseline. In
  football that is a solid, real signal.
* The differences between the smoothed season-to-date variants are small
  (0.002–0.004). They are consistent across markets and seasons, but they are
  refinements, not breakthroughs.

### C1. By stage of season

* **Stages:** early is under 25% of each team's season played (1,113
  fixtures), mid is 25–75% (1,478) and late is over 75% (646).
* **Season progress:** the mean matches played by the two teams, divided by
  games per team.

| Stage | Log loss | League baseline | Strength/tempo | Rolling 10 |
|---|---|---|---|---|
| Early | 1X2 | 1.084 | **1.061** | 1.063 |
| Early | BTTS | 0.684 | 0.685 | 0.688 |
| Early | O/U | 0.670 | 0.673 | 0.677 |
| Mid | 1X2 | 1.082 | **1.034** | 1.046 |
| Mid | BTTS | 0.690 | 0.688 | 0.689 |
| Mid | O/U | 0.682 | 0.679 | 0.686 |
| Late | 1X2 | 1.087 | **1.043** | 1.056 |
| Late | BTTS | 0.691 | 0.692 | 0.699 |
| Late | O/U | 0.680 | 0.676 | 0.688 |

* **Early season:**
  * Every window is equivalent: the rolling windows are still the whole season.
  * The model beats the league baseline for 1X2 (−0.023, interval excludes
    zero).
  * For BTTS and O/U the league baseline is slightly better (+0.001 and +0.003,
    intervals include zero).
* **Mid and late season:** season-to-date pulls clearly ahead of the rolling
  windows. Extra history improves estimates more than it costs in
  responsiveness.

### C2. By competition, by history and extreme values

**1X2 log loss by competition (league baseline → model):**

| Competition | League baseline | Model |
|---|---|---|
| EPL | 1.087 | 1.034 |
| Championship | 1.080 | 1.050 |
| PSL | 1.092 | 1.034 |
| PSL 1st Division | 1.081 | 1.063 |

* The model is best in every league.
* The gain is smallest in the PSL 1st Division, the most even league.
* For BTTS and O/U the model and the league rate are within ±0.004 in each
  competition. The full table is in `segments.csv`.

**Limited venue history:** fixtures where the home team has 0, 1–2 or 3–5 home
matches, or the away team as few away matches, behave like the overall picture.
The recommended model does not use venue records, so thin venue history does
not destabilise it.

**Extreme values:**
* **Raw venue rates:**
  * 22% of fixtures have an estimated goal value below 0.4, and λ reaches
    10.35.
  * 16% of fixtures show a favourite above 75% that wins only 52% of the time
    (stated average 88%).
* **Strength/tempo model:**
  * λ ranges from 0.45 to 3.25 (1st–99th percentile 0.58–2.28).
  * 0.4% of fixtures have a favourite above 75%, and those favourites won 77%
    of the time (stated 80%).

**Stability:** the mean change in a team's attack plus defence factors between
its consecutive fixtures.

| Model | Early | Mid | Late |
|---|---|---|---|
| Raw season rates | 0.479 | 0.088 | 0.042 |
| Strength/tempo | 0.059 | 0.036 | 0.023 |
| Recency-weighted | 0.067 | 0.048 | 0.037 |
| Rolling 10 | 0.066 | 0.071 | 0.075 |
| Rolling 8 | 0.069 | 0.079 | 0.077 |

Rolling windows never settle. A match dropping out of the window moves the
estimate as much as a new one coming in.

## D. Research question findings

### D1. Which window? (Question A)

**Season-to-date.** It is significantly better than rolling 8 or 10 for 1X2,
BTTS and O/U, and two to three times more stable from mid-season on.
Recency weighting chose a long half-life (20 matches) and added nothing. There
is no evidence that recent matches deserve more weight than the season's
average once shrinkage is in place.

### D2. Home advantage and the Poisson assumption (Question B)

**Home advantage.**
* League home and away rates provide the home advantage, and team venue records
  add nothing.
* Allowed to, the tuning gave team-specific venue factors a near-zero weight
  (k_v = 192, so 9% weight even after 19 home matches).
* Even so, the venue-specific model was slightly worse for 1X2 (+0.004).
* This matches the earlier Form Score research.

**Zero goals.** A zero raw rate yields λ = 0, so impossible scorelines and
infinite log loss. Pseudo-match shrinkage removes this, so no special case or
floor is needed.

**Poisson fit (strength/tempo model, test fixtures):**

| | Observed | Expected |
|---|---|---|
| 0–0 | 267 | 279 |
| 1–1 | 442 | 388 |
| 2–2 | 171 | 147 |
| 2–0 | 224 | 258 |
| 2–1 | 309 | 267 |
| Total goals 0 | 267 | 279 |
| Total goals 1 | 651 | 665 |
| Total goals 2 | 825 | 811 |
| Total goals 3 | 723 | 675 |
| Total goals 4 | 442 | 430 |
| Total goals 5+ | 329 | 378 |
| **Draws** | **902 (27.9%)** | **843 (26.0%)** |

* **Goal totals:** the fit is good. The 5+ category is slightly
  over-predicted, which is why the Over 2.5 slope is 0.89.
* **Draws:** under-predicted by about 1.8 percentage points, in every league.
  The excess sits in score draws (1–1, 2–2), not in 0–0.
* **Dixon–Coles:**
  * A single ρ fitted on earlier seasons came out at about zero (+0.003,
    +0.004, −0.027).
  * It changed nothing: 1X2 log loss differed by −0.00001 [−0.0002, +0.0002].
  * Dixon–Coles raises (or lowers) 0–0 and 1–1 together, but the data has too
    few 0–0s and too many 1–1s, so it cannot fix this pattern.
* **Not implemented.** A specific alternative is worth investigating later if
  the draw deficit matters: diagonal inflation or a bivariate Poisson with a
  shared component.

### D3. Early-season smoothing (Question C)

* **Shrinkage works and is essential.**
  * The raw versions lose 0.17–1.28 in log loss against the league baseline.
  * The smoothed model is calibrated from round one: early-season 1X2 log loss
    1.061 against 1.084 for the league baseline.
* **The constants are not arbitrary.**
  * Each is a pseudo-match count chosen on earlier seasons only.
  * It is stable across three tuning sets.
  * It has a clear meaning: k_s = 12 means "after 12 matches, half the team's
    strength is its own record".
* **Fixtures before any current-season data exist:** handled by the
  league-level prior (B6).

### D4. Empirical distributions versus Poisson (Question D)

**The fair version built:**
* Each team's 0/1/2/3+ scoring distribution at the venue is shrunk to its
  all-venue distribution, which is shrunk to the league's distribution for that
  venue.
* The same is done for conceding.
* Home goals = average of (home team scoring at home, away team conceding away),
  and likewise for away goals.
* The 3+ category is split into exact goals (3–10) using the league's own
  current-season distribution of 3+ goals for that side, so 1X2 score
  differences are exact.

**Result:**
* It matches the league baseline on BTTS and O/U, but only because the tuning
  shrank it almost entirely to the league (k = 32 and 48).
* It is much worse on 1X2 (+0.024 against Poisson). Its 1X2 calibration slope
  of 2.19 means far too timid.

**Why Poisson wins:**
* It needs one number per team per side.
* It combines attack and defence multiplicatively, which is how opponent
  quality actually works.
* It borrows the shape of the distribution from theory.

The empirical method needs three free probabilities per team per side and has
no principled way to combine two teams' views, so it is either noisy or, once
smoothed, uninformative. **Poisson's one-parameter structure is a real
advantage here.**

## E. Recommendation

**Adopt a simple Poisson goal model: season-to-date, strength/tempo shrinkage,
league home/away rates for home advantage. Do not retain Form Score as the
headline Match Result statistic.**

**Trade-offs and confidence:**
* **Match Result (1X2): high confidence.**
  * The gain is large and significant over the league baseline, and over a
    fitted Form Score.
  * It holds across three seasons, four leagues and all stages of the season.
  * Calibration is excellent.
* **BTTS and Over/Under: moderate confidence.**
  * The probabilities are calibrated and consistent with the 1X2 numbers.
  * They are not demonstrably better than the league's own rate.
  * Users should see them as "about the league average, nudged by the teams",
    and the product should not over-sell them. The current descriptive "Last
    10" frequencies were worse than the league rate when read as probabilities
    (Milestone 5.2), so the model is still an improvement in honesty.
* **Draws** are slightly under-predicted (26.0% stated, 27.9% observed). This is
  a known limitation of independent Poisson. It is acceptable for a first
  version and worth revisiting.
* **Not yet compared against bookmaker probabilities.** A post-selection
  comparison is worth doing for context once the odds-trial fixtures have
  settled. It would tell users how much the market knows beyond goals data. It
  must stay out of tuning and selection; it needs separate approval.

### E1. Role of Form Score: the double-counting risk

**The overlap.**
* The goal model already contains every result a Form Score is built from.
* Form Score's eight matches are part of the season-to-date record, and points
  and goal difference are close proxies of goals for and against.

**The risk.** If a user nudges estimated goals up because "form is good", they
partly count the same matches twice. The evidence that recent form deserves
extra weight is weak: rolling windows and recency weighting both lost to
season-to-date.

**Recommendation.** If Form Score moves to a qualitative section:
* label it "Already reflected in the estimated goals"
* suggest adjustments only for information the model cannot see, such as
  injuries, suspensions, fatigue, scheduling, managerial change or squad
  rotation

### E2. Qualitative adjustment example (Question E)

| | Home estimated goals | Away estimated goals | Home win | Draw | Away win | BTTS Yes | BTTS No | Over 2.5 | Under 2.5 |
|---|---|---|---|---|---|---|---|---|---|
| Baseline | 1.80 | 1.10 | 53.8% | 23.1% | 23.1% | 55.7% | 44.3% | 55.4% | 44.6% |
| Adjusted | 1.55 | 1.10 | 47.7% | 25.3% | 27.0% | 52.6% | 47.4% | 49.4% | 50.6% |

Lowering the home estimate by 0.25 goals moves every market coherently:
* the home win is less likely, and the draw and away win more likely
* fewer goals means BTTS and Over less likely

Nothing else has to change. The model supports
"baseline → adjust estimated goals → recalculate" directly. Adjustments
should be applied to λ, never to the probabilities.

## D (deliverable). Worked example: Aston Villa v Nottingham Forest

*EPL, 3 January 2026, 12:30 UTC, fixture 1379159. Settings were chosen on
2023/24–2024/25 only (k_s = 12, k_t = 96, m0 = 30). All numbers are reproduced by
the script (`summary.json → worked_example`), and the hand calculation is checked
against the vectorised code.*

**1. League averages available at kickoff:**
* 190 current-season EPL matches: 296 home goals and 230 away goals.
* Previous season: 1.5132 home and 1.4211 away goals per match (380 matches).
* H = (296 + 30 × 1.5132) ÷ (190 + 30) = **1.5518**
* A = (230 + 30 × 1.4211) ÷ 220 = **1.2392**

**2. Team records available at kickoff (current season only):**

| | Home P | Home GF | Home GA | Away P | Away GF | Away GA | Expected GF | Expected GA |
|---|---|---|---|---|---|---|---|---|
| Aston Villa | 9 | 15 | 7 | 10 | 15 | 16 | 26.36 | 26.67 |
| Nottingham Forest | 10 | 12 | 17 | 9 | 6 | 13 | 26.67 | 26.36 |

* Expected goals scored at league rates: Villa 9 × H + 10 × A = 26.36.

**3. Attack and defence factors (smoothed values are the parameters):**

| | Raw attack | Raw defence | Attack (k_s) | Defence (k_s) | Attack (k_t) | Defence (k_t) | Strength | Tempo |
|---|---|---|---|---|---|---|---|---|
| Aston Villa | 1.138 | 0.862 | 1.085 | 0.915 | 1.023 | 0.977 | **1.088** | **1.000** |
| Nottingham Forest | 0.675 | 1.138 | 0.800 | 1.085 | 0.946 | 1.023 | **0.859** | **0.984** |

* Villa attack (k_s) = (30 + 12 × 1.3955) ÷ (26.358 + 12 × 1.3955) = 1.085.
* Villa strength = √(1.085 ÷ 0.915) = 1.088.
* Villa tempo = √(1.023 × 0.977) = 1.000.

**4. Estimated goals:**
* Villa: 1.5518 × (1.088 ÷ 0.859) × 1.000 × 0.984 = **1.93**
* Forest: 1.2392 × (0.859 ÷ 1.088) × 1.000 × 0.984 = **0.96**

**5. Goal distributions:**

| Goals | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| Aston Villa | 14.5% | 28.0% | 27.0% | 17.4% | 8.4% | 3.3% | 1.0% | 0.3% |
| Nottingham Forest | 38.2% | 36.8% | 17.7% | 5.7% | 1.4% | 0.3% | 0.0% | 0.0% |

**6. Pre-match probabilities:**

| Market | Probabilities |
|---|---|
| Match Result | Home 60.1% · Draw 21.7% · Away 18.2% |
| BTTS | Yes 52.8% · No 47.2% |
| Over/Under 2.5 | Over 55.3% · Under 44.7% |

**7. Actual result (after the match, not used above): Aston Villa 3–1
Nottingham Forest.** This was a home win, BTTS Yes and Over 2.5.

## F. Implementation considerations (not implemented)

**Minimal production components:**
* `goal_model.py`:
  * league rates with the previous-season prior
  * team strength and tempo
  * λ
  * exact Poisson market probabilities, reusing the tested functions here
* `k_s`, `k_t` and `m0` held in `ScreenerConfig`, with the values documented.
* Engine output adds `estimated_goals` (home, away) and the seven
  probabilities, plus the inputs needed for an "How it's calculated" panel:
  * H and A
  * each team's played, scored and conceded counts
  * strength and tempo

**Data dependencies:**
* Existing tables only (fixtures, teams).
* `MatchStore.team_window` (current season, current competition) and
  `league_matches`.
* The previous season's league matches for the prior: all four leagues have
  2023/24 onwards stored.
* No new API requests and no schema change.

**Cache and versioning:**
* A new engine version (e.g. 3.0.0) retires 2.4.0 rows automatically through
  the existing `screener_results` versioning.
* Refresh after every results update, as now.

**Early-season availability:**
* From round one. A team with no current-season matches is labelled "League
  average only".
* An early-season note shows until both teams have five or more matches.
* Unavailable only if neither a previous-season prior nor 30 current-season
  league matches exists (for example, a newly added competition).

**Tests:**
* Unit tests:
  * market maths against closed forms
  * normalisation and tail
  * zero history equals league rates
  * shrinkage weights
  * the strength/tempo identity
  * point in time (later results, same-kickoff, previous-season and
    other-division exclusion)
  * the prior blend
  * the availability rule
* Integration tests:
  * the cache round trip
  * the version banner
  * the worked example reproduced through the engine
  * UI rendering on mobile and desktop
* A scheduled check that the chosen constants still hold, by refitting on the
  latest completed season (report only; no automatic change).

**Coexistence with Engine 2.4.0:**
* Compute the goal model in parallel as a research or "beta" payload, without
  displaying it.
* Compare it live on settled fixtures for a few weeks: calibration and log loss
  against the league baseline, and, after selection, against bookmaker odds if
  approved.
* Then switch the Match Analysis card in one engine release. Form Score and
  Venue Context could move to a secondary section.

## Limitations and open questions

* **Opponent strength is not adjusted iteratively.** Each team's factors use raw
  goals against whoever it has played, with no schedule correction. Shrinkage
  limits the early-season effect, and by mid-season schedules even out. A
  penalised Poisson regression would correct it, but would cost
  interpretability; not tested.
* **Draw under-prediction (≈1.8 percentage points):** unresolved; see D2.
* **League prior in promoted-heavy seasons:** last season's league average may
  differ from this season's league. It is down-weighted quickly (50% after
  about three rounds).
* **Small 2026/27 sample** (433 fixtures). Results are consistent with the two
  full seasons.
* **No bookmaker comparison** has been made, by design. The model's absolute
  quality relative to the market is unknown.
* **The tuning grid's upper edge for k_v** (192) was chosen; this means the
  tuning wanted no venue-specific team effect.
