# Cross-league validation of the goal model (before Engine 3.0)

*16 November 2026. Research only: Engine 2.4.0, the Screener UI, the production
database, schema and cache are unchanged. No bookmaker data is used. Parameters
are frozen at k_s = 12, k_t = 96, m0 = 30, exactly as recommended in
[`goal_distribution_research.md`](goal_distribution_research.md).*

**Reproduce:**

1. Build the separate research database. This is a one-off, about 67 API
   requests:

   ```bash
   uv run diski9 --database-url sqlite:///data/research_crossleague.sqlite init-db
   ```

   ```bash
   uv run diski9 --database-url sqlite:///data/research_crossleague.sqlite sync-reference --competitions 140 61 78 135 2 3 --seasons 2022 2023 2024 2025 2026
   ```

   ```bash
   uv run diski9 --database-url sqlite:///data/research_crossleague.sqlite ingest-fixtures --competitions 140 61 78 135 2 3 --seasons 2022 2023 2024 2025 2026
   ```

2. Run the validation (no API requests):

   ```bash
   uv run python scripts/research_goal_crossleague.py
   ```

* Outputs: `docs/research/goal_model_crossleague/` (`summary.json`,
  `per_competition.csv`, `coverage.csv`, `calibration.svg`).
* Tests: `tests/test_goal_crossleague_research.py`.

## Summary

* **Domestic leagues: validated. Keep the shared parameters.**
  * On 4,515 new fixtures from La Liga, Ligue 1, the Bundesliga and Serie A, the
    frozen model beats each league's own baseline for Match Result by a wide
    margin. The 1X2 log loss falls by 0.052–0.078; the original leagues saw 0.039.
  * The gain holds in every league and at every stage of the season, and every
    interval excludes zero.
  * BTTS and Over/Under are slightly better than the league rate (pooled
    −0.003 and −0.006, both significant). They are honest and calibrated, but
    the gain is small, as in the original study.
* **Possible re-tuning: not worth it.**
  * Re-tuned on 2023/24–2024/25, the new leagues would prefer slightly less
    shrinkage (k_s 8, k_t 24).
  * On later seasons that gains only 0.003 in 1X2 log loss, about 5% of the
    model's advantage over the baseline. BTTS and Over/Under are unchanged.
  * The same setting does not help the original four leagues: it is no better
    for 1X2 and slightly worse for BTTS and Over/Under.
  * **There is no case for league-specific settings or a change now.**
* **Champions League and Europa League: work, but not good enough to show
  yet.**
  * The model beats the competition baseline overall (−0.030), but:
    * it has almost nothing to work with early on: the median team has played
      3 competition matches, and 13% of fixtures involve a team with none
    * it is too cautious (calibration slope 1.35)
    * at matchdays 1–2 it is no better than the competition average
  * In plain terms, at matchday 1 it cannot tell a European giant from a small
    national champion.
  * That needs cross-competition team information, which is a separate research
    question. **Recommendation: do not show UEFA probabilities in Engine 3.0.**

## 1. Data: what existed, what was fetched

* **Before this exercise:** the production database held only the EPL,
  Championship, PSL and PSL 1st Division. None of the six new competitions had
  any history.
* **Fetched into a separate research database** (`data/research_crossleague.sqlite`,
  ignored by git), using the existing ingestion commands:

  | Requests | What |
  |---|---|
  | 6 | Competition records |
  | 30 | Team lists (6 competitions × 5 seasons) |
  | 30 | Full-season fixture lists |
  | 1 | Bookmaker list (part of `sync-reference`, not used) |
  | **67** | **Total, under 1% of the daily quota** |

* Production data, the Screener and the odds trial were not touched.

| Competition | API id | Seasons | Holdout fixtures evaluated | Notes |
|---|---|---|---|---|
| La Liga | 140 | 2022/23–2026/27 | 1,259 | 20 teams |
| Ligue 1 | 61 | 2022/23–2026/27 | 1,007 | 18 teams from 2023/24; 1 awarded match excluded |
| Bundesliga | 78 | 2022/23–2026/27 | 999 | Relegation play-offs excluded |
| Serie A | 135 | 2022/23–2026/27 | 1,250 | 1 relegation play-off excluded |
| Champions League | 2 | 2022/23–2026/27 | 572 | Main competition only (below) |
| Europa League | 3 | 2022/23–2026/27 | 588 | Main competition only (below) |

**Holdout versus development data:**
* **All 5,675 evaluated fixtures are genuinely new evidence.** These
  competitions played no part in choosing k_s, k_t or m0.
* **Seasons evaluated:** 2023/24, 2024/25, 2025/26 and 2026/27 (to 8 November).
* **Opening rounds are included.** 2022/23 only provides the previous-season
  league average for 2023/24.
* The four original leagues are quoted only for comparison and are labelled as
  development data.

**UEFA match types:**
* **Included, both as team history and as fixtures evaluated:**
  * group stage (2022/23–2023/24 format), 6 matchdays
  * league phase (2024/25 onwards), 8 matchdays
  * two-legged knockout rounds: knockout play-offs, round of 16, quarter-finals,
    semi-finals
* **Excluded:**
  * qualifying and preliminary rounds (different, much weaker fields)
  * the single-venue final (no real home side)
* **Results:** 90-minute scores. Extra time and penalties are ignored, as for
  domestic leagues.
* **Never used:** domestic results. A team's UEFA statistics are its UEFA
  matches this season only, as required.
* **Stages reported:**
  * early: matchdays 1–2
  * mid: matchdays 3–4 (group) or 3–5 (league phase)
  * late: the remaining matchdays
  * knockout

**Domestic season stages:** early is under 25% of each team's season played, mid
is 25–75%, and late is over 75%.

## A. Cross-league validation report

**Log loss and Brier score: model / competition baseline** (lower is better):

| Competition | Fixtures | 1X2 log loss | 1X2 Brier | BTTS log loss | BTTS Brier | O/U log loss | O/U Brier |
|---|---|---|---|---|---|---|---|
| La Liga | 1,259 | **1.003** / 1.073 | **0.598** / 0.648 | **0.688** / 0.693 | 0.247 / 0.250 | **0.685** / 0.696 | 0.246 / 0.251 |
| Ligue 1 | 1,007 | **1.020** / 1.072 | **0.612** / 0.649 | 0.693 / 0.693 | 0.250 / 0.250 | 0.691 / 0.695 | 0.249 / 0.251 |
| Bundesliga | 999 | **1.016** / 1.082 | **0.608** / 0.655 | 0.673 / 0.675 | 0.240 / 0.241 | **0.656** / 0.664 | 0.232 / 0.235 |
| Serie A | 1,250 | **1.011** / 1.088 | **0.605** / 0.660 | 0.692 / 0.695 | 0.249 / 0.251 | 0.694 / 0.695 | 0.250 / 0.251 |
| **New domestic, pooled** | **4,515** | **1.012** / 1.079 | **0.605** / 0.653 | **0.687** / 0.690 | 0.247 / 0.248 | **0.682** / 0.688 | 0.245 / 0.247 |
| Champions League | 572 | **0.982** / 1.015 | 0.586 / 0.614 | 0.691 / 0.689 | 0.249 / 0.248 | 0.646 / 0.650 | 0.227 / 0.229 |
| Europa League | 588 | **1.014** / 1.040 | 0.607 / 0.627 | **0.691** / 0.696 | 0.249 / 0.251 | 0.687 / 0.690 | 0.247 / 0.248 |
| **UEFA, pooled** | **1,160** | **0.998** / 1.028 | 0.597 / 0.621 | 0.691 / 0.693 | 0.249 / 0.250 | **0.667** / 0.670 | 0.237 / 0.239 |
| *Development leagues (for reference)* | *3,237* | *1.045 / 1.084* | *0.630 / 0.656* | *0.688 / 0.688* | *0.247 / 0.247* | *0.676 / 0.677* | *0.242 / 0.242* |

Bold marks a log-loss difference whose 95% interval excludes zero.

**Model − baseline log loss, with 95% intervals** (bootstrap by ISO week):

| Competition | 1X2 | BTTS | Over/Under |
|---|---|---|---|
| La Liga | −0.070 [−0.084, −0.055] | −0.005 [−0.009, −0.001] | −0.011 [−0.016, −0.005] |
| Ligue 1 | −0.052 [−0.069, −0.036] | +0.000 [−0.006, +0.006] | −0.004 [−0.009, +0.002] |
| Bundesliga | −0.066 [−0.086, −0.046] | −0.003 [−0.008, +0.004] | −0.008 [−0.013, −0.003] |
| Serie A | −0.078 [−0.096, −0.059] | −0.003 [−0.006, +0.001] | −0.001 [−0.005, +0.004] |
| New domestic, pooled | **−0.067 [−0.076, −0.058]** | **−0.003 [−0.005, −0.000]** | **−0.006 [−0.008, −0.003]** |
| Champions League | −0.033 [−0.048, −0.019] | +0.002 [−0.009, +0.014] | −0.004 [−0.008, +0.000] |
| Europa League | −0.026 [−0.044, −0.010] | −0.005 [−0.010, −0.000] | −0.003 [−0.009, +0.003] |
| UEFA, pooled | **−0.030 [−0.042, −0.019]** | −0.001 [−0.008, +0.005] | **−0.003 [−0.007, −0.000]** |

**Match Result (1X2) log loss by stage: model / baseline:**

| Competition | Early | Mid | Late | Knockout |
|---|---|---|---|---|
| La Liga | 1.039 / 1.087 | 0.994 / 1.066 | 0.969 / 1.066 | – |
| Ligue 1 | 1.052 / 1.076 | 1.005 / 1.076 | 1.007 / 1.060 | – |
| Bundesliga | 1.016 / 1.064 | 1.009 / 1.087 | 1.028 / 1.098 | – |
| Serie A | 1.036 / 1.083 | 0.986 / 1.087 | 1.027 / 1.099 | – |
| Champions League | 1.026 / 1.026 | 0.973 / 1.004 | 0.934 / 0.989 | 1.001 / 1.050 |
| Europa League | 1.065 / 1.061 | 1.001 / 1.034 | 0.946 / 1.012 | 1.048 / 1.055 |

* **Domestic leagues:** the model is better at every stage; early-season
  intervals exclude zero in all four leagues.
* **UEFA:** the model is no better at matchdays 1–2. In the Europa League
  knockouts its 1X2 interval includes zero.
* BTTS and Over/Under by stage: model and baseline are within about ±0.01
  everywhere (`summary.json → per_competition → by_stage`).

### Calibration

**New domestic leagues (pooled):**
* **Home win calibration:**
  * error 0.025 against 0.017–0.021 in the development leagues
  * slope 1.21: the probabilities are slightly too cautious
* **Per league:**

  | League | Calibration slope | Error |
  |---|---|---|
  | La Liga | 1.45 | 0.05 |
  | Serie A | 1.27 | 0.05 |
  | Bundesliga | 1.10 | 0.05 |
  | Ligue 1 | 1.03 | 0.02 |

* **Why:** these leagues have a bigger gap between their best and worst
  teams, so the shrinkage pulls more real information towards the average.
  * The 10–20% home-win bin wins 8% of the time.
  * The 60–70% bin wins 67% of the time.
* **BTTS and Over/Under:** calibration error 0.011 and 0.015, the best
  of any group (development leagues: 0.024 and 0.013).
* **Per-league BTTS and Over/Under slopes are unreliable.** The forecasts are
  bunched within a few points of the league rate, so ECE is the better guide.

**UEFA (pooled):**
* **Home win:** calibration error 0.039, slope 1.35 (too cautious).
* **BTTS:** error 0.041; forecasts of 60–70% happened 58% of the time.
* **Over/Under:** error 0.036.

Reliability diagrams: `docs/research/goal_model_crossleague/calibration.svg`.

## B. Domestic versus European competitions

**Domestic leagues fit the model's assumptions:**
* a closed group of teams
* a balanced schedule
* 34–38 matches per team
* home advantage visible in the league's own home/away scoring

The same parameters work in all eight domestic leagues (four development and
four new).

**European competitions break these assumptions:**

1. **Very few competition matches.** Before a UEFA fixture, the team with less
   history has played a median of 3 main-stage matches. 13% of fixtures
   involve a team with none, and the maximum is 13. With k_s = 12, after six
   matches the league still supplies 67% of a team's strength.
2. **Huge quality gaps that the competition record cannot see early.** At
   matchday 1 every team looks average to the model. The model is no better than
   the competition average at matchdays 1–2 (CL 1.026 against 1.026, EL 1.065
   against 1.061).
3. **Strong shrinkage does lose information.** The calibration slope is 1.35
   overall and 1.43–2.03 in the group and league phase, so the model is too
   cautious.
   * Re-tuning on 2023/24–2024/25 UEFA data prefers much less shrinkage
     (k_s 6, k_t 48).
   * Evaluated on 2025/26–2026/27 (520 fixtures), that improves 1X2 log loss by
     only 0.008 [−0.016, +0.000].
   * **The loss is structural: the information is not in the competition's own
     record.** Re-tuning cannot fix it.
4. **Format effects.** Two-legged ties, second legs played to protect a lead,
   rotated squads in dead rubbers, a single-venue final, and changes in format
   (groups to a 36-team league phase in 2024/25) all violate "every match is
   played to win it".

**Conclusion:**
* **One common approach is right for domestic leagues.**
* **European competitions need separate treatment.** Their natural information
  source is each team's domestic strength, adjusted for league strength. That is
  a different model:
  * cross-competition team ratings
  * league-strength coefficients
  * possibly a carry-over from last season
* It brings new risks:
  * league-strength estimates come from few inter-league matches
  * a domestic form slump would feed into European estimates
  * user explanations become harder
* **Recommendation:** treat this as a separate research exercise ("European
  team strength from domestic data"). Do not add it to Engine 3.0.

## C. Parameter recommendation

**1. Retain the shared parameters (k_s 12, k_t 96, m0 30) for all eight
domestic leagues.** No league-specific settings.

* The frozen model is validated on 4,515 new fixtures.
* A best-case re-tune would gain at most:
  * in sample, 2023/24–2024/25, new leagues: 0.006 in scoreline log-likelihood
    per match (k_s 8, k_t 24)
  * out of sample, 2025/26–2026/27: 0.003 in 1X2 log loss [−0.006, −0.001];
    BTTS +0.001 and Over/Under −0.000 (both noise)
  * on the development leagues: no help (1X2 −0.001 [−0.002, +0.001], BTTS
    +0.002, Over/Under +0.002)
* Per league, the in-sample gaps (0.002–0.011) are too small to justify
  separate settings.

**2. Revisit k_s at the first annual review, pooled across all eight domestic
leagues.**
* The new leagues' calibration slope of 1.2 says strength may be shrunk a
  little too much where talent gaps are large.
* The evidence is not yet strong enough to change a validated setting.
* Do not overwrite the current settings now.

**3. European competitions: delay probabilities.**
* Show UEFA fixtures without model probabilities in Engine 3.0, for example
  with descriptive history and the bookmaker reference.
* Commission the separate research exercise in section B.
* **Fallback, if UEFA must appear at launch:** show estimates only from
  matchday 3, labelled "Based on this season's [competition] matches only —
  does not use domestic form". Expect them to understate favourites.

## D. User-facing methodology

### Short version (for the app)

> **How Diski 9 estimates a match**
>
> For every fixture we estimate how many goals each team is likely to score —
> its **estimated goals**. These come only from real results this season: goals
> scored and conceded, compared with what an average team in that league would
> score at home or away. From the two estimated-goal numbers we work out the
> chances of a home win, draw or away win, both teams scoring, and over or under
> 2.5 goals — all from the same calculation, so they always agree with each
> other.
>
> **Early in the season**, a few results can be misleading (one 4–0 win doesn't
> make a team world-beaters), so every team starts at the league average and
> moves towards its own record as it plays more games. Goal totals settle more
> slowly than team strength because they vary more from week to week.
>
> **We don't use betting odds** to build these numbers. Bookmaker odds are shown
> separately, for comparison.
>
> **Known limits:** the model doesn't know about injuries, suspensions,
> transfers or team news; it slightly underestimates draws; and its BTTS and
> Over/Under numbers usually stay close to the league average, because past
> goals tell us less about those markets. European competitions aren't covered
> yet.
>
> **How it's maintained:** results update after every match. The model's
> settings stay fixed during the season and are reviewed once a year. Any change
> is published with the evidence for it.

### Technical methodology (for advanced users)

1. **Estimated goals.**
   * H and A are the league's average home and away goals per match this season
     (before kickoff).
   * Each team has a **strength** s (how much it outscores the league, from
     goals scored and conceded) and a **goal tempo** t (how high-scoring its
     matches are).

     λ_home = H × (s_home ÷ s_away) × t_home × t_away  
     λ_away = A × (s_away ÷ s_home) × t_home × t_away

   * Goals are modelled as two independent Poisson distributions. All seven
     probabilities are exact sums over every scoreline.
2. **How results move strength and tempo.**
   * Goals scored and conceded are compared with the league rate for the venue
     each match was played at.
   * They are combined with k pseudo-matches of exactly average performance:

     attack = (goals scored + k·g) ÷ (expected scored + k·g)

     and likewise for defence (g is the league goals per team per match).
   * Strength uses k_s = 12 and tempo uses k_t = 96.
3. **Why shrink.**
   * After 3 matches the league average still provides 80% of strength; after
     12, 50%; after 38, 24%.
   * Without shrinkage, a team that has not yet scored would be given 0
     estimated goals.
   * Tempo is shrunk harder because, in the data, teams' goal totals regress
     strongly to the league mean.
4. **How the settings were chosen.**
   * Chosen once, by maximum likelihood of the actual scorelines, on earlier
     seasons only.
   * Tested out of sample on later seasons.
   * Stable across three tuning periods.
   * No betting odds used.
   * The league average starts the season with 30 pseudo-matches of the
     previous season's league-wide average (no team results). It is 50% current
     season after about three rounds.
5. **Data used.**
   * **Calibration:** EPL, Championship, PSL, PSL 1st Division, 2023/24–2025/26
     (tuning) and 2024/25–2026/27 (out-of-sample test, 3,237 fixtures).
   * **Independent validation:** La Liga, Ligue 1, Bundesliga, Serie A,
     2023/24–2026/27 (4,515 fixtures, never used for tuning).
   * The Champions League and Europa League were tested (1,160 fixtures) and are
     not yet supported.
6. **Known limitations.**
   * No team news.
   * No adjustment for opponent schedule.
   * Draws under-predicted by about 1–2 points.
   * Slightly cautious favourites in leagues with large talent gaps.
   * BTTS and Over/Under only marginally better than the league average.
   * Previous-season league average used in the first rounds.
7. **Review and versioning.**
   * Statistics update after every completed match. Parameters are fixed during
     the season.
   * Annual review after the European seasons end (July).
   * Every model version, parameter and supporting report is published.

### Assessment of the proposed policy

The proposed policy is sound. Refinements:

1. **Pre-commit the rule for changing parameters.**
   * At the annual review, re-tune on all completed seasons except the latest.
   * Evaluate on the latest season.
   * Change only if:
     * pooled 1X2 log loss improves by at least 0.005 with an interval
       excluding zero
     * no market and no league gets clearly worse
   * Otherwise keep the parameters. This prevents tinkering.
2. **Monitor in season without changing anything.**
   * Track calibration and log loss against the league baseline, by league and
     market, monthly.
   * Publish the figures.
   * Investigate only if a league falls behind its own baseline for two months.
3. **Snapshot every published estimate before kickoff.**
   * Keep the estimated goals, the probabilities and the model version as shown
     to users.
   * Results corrections then never rewrite history, and Diski 9 can publish an
     honest track record.
   * The current cache stores only the latest values.
4. **Validate before adding a competition.**
   * Show probabilities only after the model has been backtested on at least one
     full season (or 300 fixtures) of that competition, with frozen parameters.
5. **Version the model separately from the engine.**
   * e.g. "Goal model 1.0 (k_s 12, k_t 96, m0 30)", shown in "How it's
     calculated".
   * Keep a changelog linking each version to its evidence report.

## E. Engine 3.0 readiness

**No statistical blocker for the eight domestic leagues.** Items to settle or
build before the new Screener and Match Lab:

1. **Competitions in production.** Add La Liga, Ligue 1, Bundesliga and Serie A
   to the competition registry, then backfill:
   * 2025/26 is needed as the prior season, 2026/27 is the current season, and
     earlier seasons are optional
   * the same commands as here, against the production database
   * about 20–30 requests
   * also decide odds collection (`odds_enabled`)
2. **UEFA decision.** Confirm "no probabilities in 3.0" (recommended) or the
   labelled matchday-3 fallback. If UEFA fixtures appear at all, production
   needs explicit stage rules:
   * today every UEFA match is classed "non-regular round"
   * qualifying excluded
   * the final at a neutral venue
3. **Prediction snapshots** for the track record (policy point 3). This needs a
   storage decision; it is the only schema-level item.
4. **Previous-season prior.** Production must have the previous season of every
   supported league, or start that league "unavailable" until 30 matches have
   been played.
5. **Calibration monitoring job and published methodology page** (section D).
6. **Known limitations to state in the UI:**
   * draw under-prediction
   * cautious favourites in La Liga and Serie A
   * BTTS and Over/Under close to the league average
7. **Not blocking:**
   * Venue classification shows many "unknown" grounds in recent seasons of the
     new leagues. The goal model uses nominal home/away, so it is unaffected;
     only the legacy Venue Context depends on it.

## Limitations of this validation

* **2026/27 is partial** (about 10–12 rounds per league).
* **Only four seasons per competition.** For UEFA, the 2024/25 format change
  leaves about 2.5 seasons of the current format (720 league-phase fixtures across both competitions).
* **No comparison against bookmaker probabilities** was made, by design.
