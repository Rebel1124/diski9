# Phase 8 CP1: pre-registered evaluation and selection procedure

*Recorded 26 Nov 2026 **before any CP1 result was computed**. This is research only.*

**What this research does not touch:**
- Goal Model 1.0 stays the accepted production baseline, unchanged;
- no production module, dependency or lockfile is modified;
- no provider calls;
- no PostgreSQL database.

**Inputs** (read-only):
- `data/diski9.sqlite`;
- `data/research_crossleague.sqlite`;
- the committed odds-trial captures.

Outputs go to `docs/research/phase8_cp1/`.

**What this exercise is:** a **pre-registered re-analysis of previously examined seasons.**
- Every season used here was already examined in earlier research (`docs/goal_distribution_research.md`, `docs/goal_model_crossleague_validation.md`).
- **It is not an untouched holdout.**
- Genuinely new evidence will come only from forecasts made after launch.

## 1. Data

| Group | Competitions | Store | Seasons evaluated |
|---|---|---|---|
| Domestic, development leagues | EPL 39, Championship 40, PSL 288, PSL 1st Division 289 | `data/diski9.sqlite` | 2023/24–2026/27 |
| Domestic, validation leagues | La Liga 140, Ligue 1 61, Bundesliga 78, Serie A 135 | `data/research_crossleague.sqlite` (2022/23 supplies the previous season for C0) | 2023/24–2026/27 |
| European | Champions League 2, Europa League 3 | `data/research_crossleague.sqlite` | 2023/24–2026/27 |

- 2026/27 is partial: the stores end mid-November 2026.
- **Domestic statistics:** regular-season matches only, under production eligibility rules (`stats_exclusion_reason IS NULL`).
- **European statistics:** main-stage matches only (§4).

## 2. Chronological integrity

- **Availability lag.** A completed match counts towards any feature (team records, competition averages) only if it kicked off **at least 3 hours before** the forecast fixture's kickoff.
  - 3 hours covers 90 minutes, half-time, stoppage time, extra time and penalties.
  - This stops an overlapping or just-finished match leaking into a forecast.
  - Production is not exposed to this: it reads only matches already final at the cutoff. The research store, by contrast, holds every result.
- **Previous season:** C0's previous-season competition average uses only a season that has finished.
- **No future seasons** are used at all.
- **Team identity:** global provider team IDs. Team records are always the **current season, current competition** only. There is no carry-over, no Elo and no cross-league strength.

## 3. Candidates

**Parameters:** k_s and k_t are 12 and 96 unless stated otherwise.

| ID | Competition averages | Availability |
|---|---|---|
| **C0** | Goal Model 1.0: current season + 30 pseudo-matches at the previous season's average. With no previous season stored, current season only, from 30 matches (production rule). | as production (no team minimum) |
| **C0-k** | as C0 | both teams have ≥ k eligible completed matches |
| **C1-k-L** | **current season only** (m0 = 0) | both teams ≥ k **and** competition ≥ L completed eligible matches |
| **C1-k-L-T** | as C1-k-L, with k_s ∈ {6, 8, 12} and k_t ∈ {24, 48, 96} | as C1-k-L |

**Grid:** k ∈ {2, 3, 4, 5} and L ∈ {20, 30, 40}.

**About C0-k:** it is C0 restricted to fewer fixtures, so its predictions on the fixtures it covers are identical to C0's. It is reported for **coverage** and to isolate the effect of gating, for example through D4 against the baseline.

**When C1-k-L-T is evaluated:** only if every C1-k-L combination that passes D1, D2 and D4 on the selection seasons fails D3 (calibration).
- Tuning is by mean scoreline log-likelihood on the selection seasons' available fixtures.
- The tuned values are then frozen.

## 4. UEFA stage classification

| Label | Treatment |
|---|---|
| Matches `qualifying`, `preliminary`, or exactly `Play-offs` (the August qualifying play-off in every stored season) | qualifying: excluded |
| `Group X - n`, `Group Stage - n` | group stage, matchday n |
| `League Stage - n` | league phase, matchday n |
| `Knockout Round Play-offs`, `Round of 32`, `Round of 16`, `Quarter-finals`, `Semi-finals` | knockout |
| `Final` | final: excluded (neutral venue) |
| **Any other label** | **the run stops** |

**Date guard:** if any knockout fixture kicks off before the season's first group or league-phase fixture, the run stops.

Only group, league-phase and knockout matches feed statistics and evaluation. Results use the 90-minute score.

## 5. Periods

- **Selection:** 2023/24 and 2024/25. All choices are made here: k, L and any C1-k-L-T parameters.
- **Confirmation:** 2025/26 and 2026/27 to date. These are evaluated **once** with the frozen choice. Nothing is tuned on them.

## 6. Metrics and comparisons

- **Metrics:** for 1X2, BTTS and O/U 2.5: log loss, Brier score, expected calibration error and calibration slope (home win for 1X2). Plus coverage.
- **Identical fixtures:** head-to-head comparisons score both models on the **same fixtures**, the intersection of the two models' availability.
- **Withheld fixtures** are reported separately:
  - their number and share;
  - C0's performance on them;
  - the competition-frequency baseline on them.
- **Intervals:** 95% paired bootstrap, resampling whole ISO weeks, 2,000 replicates, the fixed seed in `diski9.research.evaluation`.
- **Baselines (D4, E1, E2):** the competition's frequencies before kickoff for home win, draw, away win, BTTS and over 2.5.
  - C0 uses frequencies blended with the previous season (the existing definition).
  - C1 uses current-season frequencies only.
- **Breakdowns:**
  - pooled, **and per league**;
  - by the smaller of the two teams' match counts: k–5, 6–9, 10+;
  - for CL and EL, by league-phase or group matchday and knockout.
- **Coverage:** per league and season, with full seasons (2023/24–2025/26) and the partial season (2026/27) reported separately. Plus a coverage trade-off table for every k and L.

**Verdict for each non-inferiority criterion (D1, D2):**
- **pass:** the CI upper bound is within the margin;
- **inconclusive:** the upper bound exceeds the margin but the lower bound is ≤ 0 (deterioration can't be ruled out, but isn't shown);
- **deterioration demonstrated:** the lower bound is > 0 and the upper bound exceeds the margin.

**Material per-league deterioration** (flagged, not a criterion): a league's C1 − C0 1X2 log loss with a lower bound > 0, or a point estimate > +0.010.

## 7. Criteria (fixed; not to be relaxed after results)

**Domestic: C1 against C0 on identical fixtures, pooled over the 8 leagues**

| # | Criterion |
|---|---|
| D1 | 1X2 log-loss Δ: CI upper bound ≤ +0.005 |
| D2 | BTTS and O/U log-loss Δ: CI upper bound ≤ +0.003 (each) |
| D3 | Home-win calibration slope within 0.8–1.25, **and** home-win ECE ≤ C0's ECE on the same fixtures + 0.01 |
| D4 | In the k–5 band, 1X2 log loss beats the current-season competition-frequency baseline (CI entirely below 0) |
| D5 | Coverage target: 85% of season fixtures per league. **A target, not a rejection threshold.** Reported per league and season. |

**Selection procedure (domestic):**
1. On the selection seasons, find the C1-k-L combinations passing D1–D4.
2. Choose the **smallest k**, then the **smallest L**, among them. D5 is reported alongside.
3. If none pass, apply the C1-k-L-T rule (§3). If still none pass, report that C1 is not supported.
4. Evaluate the frozen choice once on the confirmation seasons and report each criterion as pass, inconclusive or deterioration.
5. Present C0-k (same k) and retaining Goal Model 1.0 as alternatives.
6. **Nothing is adopted automatically.** The owner decides.

**Champions League** (the Europa League uses the same procedure and criteria, with no bespoke work):

| # | Criterion |
|---|---|
| E1 | On available fixtures, 1X2 log loss beats the competition-frequency baseline (CI entirely below 0) |
| E2 | BTTS and O/U against that baseline: CI upper bound ≤ +0.005 |
| E3 | Home-win calibration slope within 0.75–1.35 |
| E4 | At least 250 available fixtures in the confirmation seasons |
| E5 | Use the domestic k unless it fails E1–E3 on the selection seasons. Then the smallest k passing E1–E3 is reported as a separate CL threshold. |

C0 and C1 are both reported for CL.

**If the sample cannot support a conclusion, the report says so.**

## 8. Market-implied estimated goals (fit quality only)

**Data:**
- the local store's cached odds (`odds_fixture_observations`, 107 fixtures);
- plus the committed odds-trial captures (EPL and PSL) where they add snapshots.

**Method:**
- evaluated at each stored retrieval time before kickoff, using `odds.display.display_consensus`.
- **Rules (R-3):**
  - 1X2 plus at least one goals market;
  - every market used must be fresh and meet the Challenge consensus rule (at least 3 independent bookmaker groups, quotes ≤ 24 h);
  - good fits accepted, approximate fits accepted with labelling;
  - poor, invalid, insufficient or stale fits rejected.
- **The fitter** is the existing prototype `diski9.research.market_implied_xg.fit`, unchanged.

**Reported:**
- unique fixtures, leagues and snapshots;
- statuses, residuals, identification and convergence;
- consensus against reconstructed probabilities;
- fitter latency;
- the numpy and scipy footprint.

**This is not outcome validation.**

## 9. Weekly Challenge season-start feasibility

Historical odds were never stored, so this is a **fixture-availability** analysis:
- real fixture schedules;
- each round's weekend window (Friday 00:00 to Tuesday 00:00 UTC);
- the leagues with provider odds (the PSL and PSL 1st Division have none).

For each early-season window, eligible fixtures and leagues are counted under these treatments:
- (a) Goal Model required, under C0, C0-k and the chosen C1;
- (b) no model required.

The counts are compared with the opening rule (≥ 15 fixtures, ≥ 3 leagues). Bucket feasibility uses the composition observed in the real 17 Nov 2026 strict-consensus snapshot (`docs/research/weekly_challenge_risk/`).

**Assumption, stated as a limitation:** every fixture in those six leagues would have been fully priced.
