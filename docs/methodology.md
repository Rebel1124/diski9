# How Diski 9 Calculates Probabilities

*Goal Model 1.0 · Engine 3.0 · November 2026. The same content, in short, is in the
app under "How Diski 9 Calculates Probabilities".*

> We calculate the probabilities. You analyse the match. You make the call.

## 1. Model overview

For every fixture Diski 9 estimates how many goals each team is likely to score:
its **estimated goals**. A Poisson distribution then turns the two numbers into
the probability of every scoreline. Adding up the right scorelines gives all
seven outcomes:

* Match Result: home win, draw, away win
* Both Teams to Score: Yes, No
* Over/Under 2.5 goals: Over, Under

All three markets come from the same two numbers, so they always agree.

Estimated goals are model-based goal expectations calculated from match results.
They are **not shot-based xG**.

## 2. Input data

* **Current season, current competition:** completed regular-season league
  matches played before kickoff.
* **The previous season's league-wide averages** of home and away goals. This is
  league level only.

Never used:
* a team's results from earlier seasons or other divisions
* bookmaker odds
* team news

Cancelled, postponed, abandoned, awarded and play-off matches are excluded.

## 3. Estimated goals

In plain English:
* We measure how many goals each team has scored and conceded this season,
  compared with what an average team in that league would have scored and
  conceded at the same venues.
* **Strength** says how much a team outscores the league.
* **Goal tempo** says how high-scoring its matches are.
* Both start at the league average and move towards the team's own record as it
  plays more matches.
* Early in the season, teams have played relatively few matches, so we rely more
  on league averages. One 4–0 win does not make a team world-beaters.

**League averages before kickoff** (H home goals, A away goals per match):

```
H = (current-season home goals + 30 × last season's home goals per match)
    / (current-season matches + 30)                        (A likewise)
```

**For each team**, with n_h home and n_a away matches this season:

```
expected scored   E_for = n_h × H + n_a × A
expected conceded E_ag  = n_h × A + n_a × H
g = (H + A) / 2
attack(k)  = (goals scored   + k × g) / (E_for + k × g)
defence(k) = (goals conceded + k × g) / (E_ag  + k × g)
strength s = √(attack(12) / defence(12))
tempo    t = √(attack(96) × defence(96))
```

**Estimated goals:**

```
λ_home = H × (s_home / s_away) × t_home × t_away
λ_away = A × (s_away / s_home) × t_home × t_away
```

**Home advantage** comes from the league's own home and away scoring rates (H is
greater than A). There is no separate adjustment.

## 4. Poisson probabilities

* Home and away goals are treated as independent Poisson counts with means λ_home
  and λ_away.
* Each probability is an exact sum over every scoreline. The truncated tail is
  below 10⁻¹⁵.
* Complements are computed as 1 minus the rest, so each market adds up to exactly
  100%.

**Worked example** (estimated goals 1.93 and 0.96):

| Market | Probabilities |
|---|---|
| Match Result | Home 60.0% · Draw 21.7% · Away 18.2% |
| BTTS | Yes 52.8% · No 47.2% |
| Over/Under 2.5 | Over 55.2% · Under 44.8% |

Adjusting in The Match Lab: with estimated goals of 1.80 and 1.10, lowering the
home team to 1.55 recalculates every market:

| Outcome | 1.80 – 1.10 | 1.55 – 1.10 |
|---|---|---|
| Home win | 53.8% | 47.7% |
| Draw | 23.1% | 25.3% |
| Away win | 23.1% | 27.0% |
| BTTS Yes | 55.7% | 52.6% |
| Over 2.5 | 55.4% | 49.4% |

## 5. Parameter selection

| Setting | Value | Meaning |
|---|---|---|
| Strength smoothing `k_s` | 12 | After 12 matches, half of a team's strength comes from its own results |
| Goal tempo smoothing `k_t` | 96 | Goal totals vary a lot by chance, so they move towards a team's record slowly |
| League-average prior `m0` | 30 | Last season's league averages count as 30 matches at the start of a season |

**How they were chosen:**
* Once, by maximum likelihood of the actual scorelines.
* Using earlier seasons only, then tested on later unseen seasons.
* No betting odds were used.
* The values were stable across three tuning periods.

**What changes and what stays fixed:**
* **Dynamic match statistics** (league averages, goals scored and conceded, and so
  the estimated goals) update after every completed match.
* **Fixed model parameters** (the three settings above) do not change during a
  season.

**One shared set for all domestic leagues.** League-specific tuning gained at most
0.003 in Match Result log loss on held-out seasons, and did not help the original
leagues. That is too little to justify maintaining separate settings.

## 6. Historical validation

**Calibration (development):**
* EPL, Championship, PSL and PSL 1st Division.
* Tuned on 2023/24–2025/26, tested out of sample on 3,237 matches from
  2024/25–2026/27.
* Match Result log loss: 1.045, against 1.084 for the league-average baseline.
* Calibration slope: 1.00.

**Independent validation:** La Liga, Ligue 1, Bundesliga and Serie A, 4,515
matches from 2023/24–2026/27, with the frozen parameters.

| League | Model log loss | League baseline |
|---|---|---|
| La Liga | 1.003 | 1.073 |
| Ligue 1 | 1.020 | 1.072 |
| Bundesliga | 1.016 | 1.082 |
| Serie A | 1.011 | 1.088 |

* The model is better in every league and at every stage of the season.
* BTTS and Over/Under are slightly better than the league rate.

**UEFA Champions League and Europa League:**
* Tested on 1,160 matches and **not supported**.
* Teams play too few matches in these competitions for the model to tell clubs
  apart early on.
* No probabilities are shown for European competitions.

Not every competition was used to choose the parameters. Full reports:
[`goal_distribution_research.md`](goal_distribution_research.md) and
[`goal_model_crossleague_validation.md`](goal_model_crossleague_validation.md).

## 7. Known limitations

* No live team news: injuries, suspensions, line-ups, transfers.
* Draws have historically been slightly underestimated, by about 1–2 percentage
  points.
* Strong favourites may be estimated too cautiously in some leagues, such as La
  Liga and Serie A.
* BTTS and Over/Under probabilities usually stay close to league averages.
* Not validated for UEFA competitions.
* Probabilities are uncertain estimates. They do not guarantee outcomes or
  betting profitability.

## 8. Maintenance policy

1. Team and league statistics update after completed matches.
2. Model parameters stay fixed throughout the season.
3. **Monthly monitoring** (`uv run diski9 model-report`):
   * log loss, Brier score and calibration by competition, market, month and
     model version
   * compared with the league baseline
   * only **official pre-kickoff forecasts** are used
   * groups with fewer than 100 settled fixtures are marked preliminary
   * monitoring never changes parameters
4. **Annual review** after the domestic seasons end. A change needs all of:
   * at least **0.005** improvement in pooled 1X2 log loss on the designated
     held-out season
   * statistical support (an interval excluding zero)
   * no clearly material deterioration in any supported league or market

   Otherwise the parameters are kept.
5. **Versioning:**
   * Every change is a new model version (e.g. Goal Model 1.1) with its evidence
     report, recorded in [`model_changelog.md`](model_changelog.md).
   * Parameters are never changed in place.
   * There is no automatic retraining.

### Official forecasts

**Snapshots:**
* Each live refresh before kickoff stores the published baseline: estimated
  goals, all probabilities, model version, parameters and data cutoff.
* It stores the league baseline at the same cutoff too.
* Snapshots are insert-only; the database blocks updates and deletes.
* A new snapshot is written only when the forecast changes.

**Which forecast counts:**
* The **official forecast** is the latest snapshot recorded before the match
  actually kicked off.
* Your own Match Lab adjustments are never stored and never count.

## 9. Model version and changelog

**Current: Goal Model 1.0 (Engine 3.0).** See
[`model_changelog.md`](model_changelog.md).
