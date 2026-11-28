# CP3A-R item 7: Goal Model calibration sensitivity (pre-registered protocol)

*Recorded 28 Nov 2026, **before any result was computed**, and committed before the run. Research only: Goal Model 1.1 stays the production model; no production module, parameter, model version or stored record is changed.*

## 1. Parameter labels (correction)

The request labels the current baseline "strength 96, tempo 12". In the code (`src/diski9/screener/goal_model.py`, `GoalModelParams`) the values are the other way round:

| Parameter | Meaning | Value |
|---|---|---|
| `k_s` | strength shrinkage, in pseudo-matches | **12** |
| `k_t` | tempo shrinkage, in pseudo-matches | **96** |

The proposal is read as changing **the 96 parameter to 90** and **the 12 parameter to 18**, i.e. by value, not by label. So the four configurations are:

| Config | Request label | `k_s` (strength) | `k_t` (tempo) | Isolates |
|---|---|---|---|---|
| **A** | baseline | 12 | 96 | Goal Model 1.1 |
| **B** | "strength 90, tempo 12" | 12 | **90** | the 96 → 90 change (tempo shrinkage) |
| **C** | "tempo 18, strength 96" | **18** | 96 | the 12 → 18 change (strength shrinkage) |
| **D** | proposed "90 / 18" | **18** | **90** | both |

A literal reading of the labels (`k_s` 90, `k_t` 18) would be a very different model, not a small adjustment. It is computed once as a **label check only** (row "L"), so the owner can see that it was not what was intended. It is not a candidate and cannot be recommended.

No other combination is evaluated, before or after the results.

## 2. Prior evidence (already on record)

- `k_s` and `k_t` were chosen in `docs/goal_distribution_research.md` from a grid that already spanned these values: `k_s` 0.5 to 32 and `k_t` 8 to ∞. The search chose `k_s` = 12 every season and `k_t` = 128, 96, 96.
- Phase 8 CP1 kept 12/96 for Goal Model 1.1 (C1-2-20).
- So every season used here has been examined before. **There is no untouched holdout.** Genuinely unseen evidence will come only from forecasts made after launch.

## 3. Data and method (all unchanged from Goal Model 1.1 and CP1)

**Harness**
- Reuses the CP1 research harness, `scripts/research_phase8_cp1.py`:
  - `load_matches`, `build_rows` and `predict`;
  - the same stores, `data/diski9.sqlite` and `data/research_crossleague.sqlite`, each copied to a temporary directory first.

**Fixtures**
- The eight domestic leagues: EPL, Championship, PSL, PSL 1st Division, La Liga, Ligue 1, Bundesliga and Serie A.
- Regular-season matches that are statistically eligible.
- Seasons 2023/24 to 2026/27. 2026/27 is partial and ends mid-November 2026.

**Model rules, identical to Goal Model 1.1**
- Availability: both teams have at least 2 current-season matches, and the competition has at least 20.
- Competition averages come from the current season only.
- Exposure is venue-normalised.
- Strength and tempo use the same formulas as production. Goals are independent Poisson.
- 3-hour availability lag.
- Only `k_s` and `k_t` differ between configurations.

**Paired comparison**
- Availability does not depend on `k_s` or `k_t`, so every configuration is scored on **exactly the same fixtures**.

**Periods**
- Reported separately for:
  - the CP1 selection seasons (2023/24 and 2024/25);
  - the CP1 confirmation seasons (2025/26 and 2026/27 to date);
  - all seasons combined.
- **The primary result** is all seasons combined, labelled as previously examined data.

**Metrics**
- Log loss and Brier score for 1X2, BTTS and Over/Under 2.5.
- Home-win calibration slope and expected calibration error.

**Intervals**
- 95% paired bootstrap of the per-fixture differences (config − A).
- Resamples whole ISO weeks: 2,000 replicates, with the fixed seed in `diski9.research.evaluation`.

**Breakdowns**
- Each of the eight leagues.
- Season stage, by the smaller of the two teams' match counts: 2–5, 6–9, 10–19 and 20+.
- Calendar month of the season.

**Stability and size of change**
- The spread (standard deviation) of estimated home, away and total goals.
- Round-to-round volatility: the mean absolute change in a team's estimated goals between its consecutive forecasts.
- The distribution of probability changes against A, for home win, BTTS yes and over 2.5: median, 90th percentile, maximum, and the share of changes above 1 and 3 percentage points.

**Worked examples**
- Three real fixtures, computed with the production formula (`strength_tempo` and `estimate` logic) under A and D.

## 4. Decision criteria (fixed before the run; not relaxed afterwards)

D (or B or C) is recommended over A only if **all** of the following hold. Each is measured against A, pooled over all seasons.

| # | Criterion |
|---|---|
| G1 | **Meaningful improvement:** 1X2 log-loss Δ ≤ −0.002, with the 95% CI upper bound < 0 |
| G2 | **Consistency:** the 1X2 Δ point estimate is negative in both the selection and the confirmation periods |
| G3 | **No deterioration elsewhere:** BTTS and O/U log-loss Δ CI upper bound ≤ +0.002 each |
| G4 | **Calibration:** home-win slope within 0.8–1.25, and ECE ≤ A's ECE + 0.005 |
| G5 | **No material league deterioration:** no league has a 1X2 Δ with CI lower bound > 0, or a point estimate > +0.005 |
| G6 | **Early season:** in the 2–5 band, the 1X2 Δ CI upper bound ≤ +0.003 |

**Outcomes**
- If **D** fails any criterion, **A is retained**.
- B and C are diagnostic, to separate the two effects. If B or C passes and D does not, that is reported, but the recommendation remains **retain A**, unless the owner chooses to consider that single change. No new combination is tested.
- A pass is a recommendation only. Nothing is adopted automatically, and the owner decides.

**Why the threshold is −0.002:** a judgement fixed in advance. It is about 0.2% of a typical 1X2 log loss (around 1.0), and 40% of the 0.005 margin CP1 used for non-inferiority. Below it, a change is too small to justify a new model version with its migration and history obligations.

## 5. What a change would require (if ever approved)

- A new model version, Goal Model 1.2, with its own `GoalModelParams` and `params_hash`.
- An evidence report and a changelog entry in `docs/model_changelog.md`.
- 1.1 stays identifiable for stored forecasts, cache rows, round snapshots and Your View identities. Those identities include the model version, so a version change makes existing Your View adjustments inapplicable to new estimates, which is expected behaviour.
- Historical rounds are not recomputed.

## 6. Reproduction

```bash
uv run python tools/research/cp3ar/goal_model_sensitivity.py
```

Outputs go to `docs/research/phase8_cp3ar/goal_model_sensitivity.json`.
