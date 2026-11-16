# Milestone 5.2 — predeclared research plan

*Written 16 November 2026, before any Milestone 5.2 evaluation was run. Results
are reported against this plan; deviations are listed in the reports.*

## Form Score candidates (fixed before evaluation)

All models use the production windows (last five eligible matches, venue or
overall, cutoff = kickoff), the production partial-window policy (actual totals
of the matches available, no prorating) and return *unavailable* (None) when a
team has no eligible match. pts = points in window, GD = goals for − against.

| Model | Formula (score on 0–5) |
|---|---|
| A | production banded score (unchanged) |
| B | 5/6.5 × [2.5·pts/15 + 2.5·min(max(GD,0)/9, 1) + bonuses] |
| C | 5/6.5 × [2.5·pts/15 + 1.25 + 1.25·clip(GD/9, −1, 1) + bonuses] |
| D | 2.5·pts/15 + 2.5·(clip(GD, −9, 9) + 9)/18  (no bonuses) |

Bonuses as production: +0.5 won last three (≥3 matches), +0.5 scored ≥11,
+0.5 conceded ≤2 (full window only). Weights: points and goal difference keep
production's equal 2.5/2.5 split; ±9 is production's existing GD cap (1.8 per
match). No coefficient is fitted to outcomes. D equals C without bonuses, so the
C-vs-D comparison measures what the bonuses add.

## Evaluation (fixed)

* Fixtures: eligible completed league fixtures, EPL / Championship / PSL / PSL
  1st Division, seasons 2024/25–2026/27 to date (2023/24 used only as history).
* Rolling-origin (walk-forward) monthly folds from August 2025: for each
  calendar month, fit on every fixture that kicked off before the month, score
  that month. Secondary model: multinomial logistic regression of H/D/A on the
  feature(s); it is not the Form Score.
* Benchmarks: training outcome frequencies; last-5 PPG difference; last-5 GD
  difference; PPG + GD (two features); season-to-date venue PPG difference.
  Common sample: fixtures where every feature exists.
* Metrics: log loss (primary), Brier, calibration (10 bins, ECE). Uncertainty:
  paired bootstrap clustered by ISO week, 2,000 replicates, seed 52.
* Decision rule: a candidate is "better" only if its 95% interval for the
  log-loss difference against A excludes zero.
* Predefined Form Difference bands: (−5,−2], (−2,−1], (−1,−0.25], (−0.25,0.25),
  [0.25,1), [1,2), [2,5).

## Goals-market indicators (fixed)

* Production indicator (current season, current competition, up to 10 matches
  per team, mean of the two team rates), overall and venue.
* Shrinkage candidate: each team rate shrunk to the league rate with k = 5
  pseudo-matches: (hits + 5·league)/(n + 5). League rate = current-season
  league matches before kickoff; when fewer than 30, blended with the previous
  season of the same competition by weight n/30 (league-level prior only).
* Historical goal-rate model (research only): λ_home = league home average ×
  home attack × away defence, team ratios shrunk with k = 5, current season and
  competition only, same league prior. Poisson and Dixon–Coles (ρ fitted by
  maximum likelihood on the training folds only).
* Sample-size bands: smaller team sample 1–2, 3–5, 6–9, 10.

## Market inversion (fixed)

* Objectives: KL (equal market weights, primary) and mean squared probability
  error (equal market weights).
* Models: independent Poisson; Dixon–Coles with ρ fixed from a separate
  calibration; Dixon–Coles with ρ free per fixture (only reported where the
  constraint count allows).
* Bounds: λ ∈ [0.05, 6]; ρ ∈ [−0.3, 0.3] intersected with τ ≥ 0.
* Sensitivity: each quoted price moved by ±1% (one at a time), deterministic
  multi-start spread, objective profile over ρ.
* Fit categories as Milestone 5.1 (good ≤ 2 pp, approximate ≤ 4 pp).
