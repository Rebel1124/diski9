# Milestone 5.2 — Market-implied goal expectations: Poisson vs Dixon–Coles

*16 November 2026. Research only (Layer 3). Nothing here reaches the app,
rankings or the Challenge. These are **market-implied goal expectations**:
average goals implied by betting prices under an explicit model. They are not
shot-based xG.*

**Reproduce:**

```
uv run python scripts/research_m52_goals.py
```

```
uv run python scripts/research_m52_goal_models.py
```

* Run the goals script first: it supplies the historical ρ.
* Code: `src/diski9/research/goal_models.py` (models, inversion, diagnostics)
  and `src/diski9/research/result_validation.py` (results pipeline).
* Tests: `tests/test_m52_goal_models.py` and `tests/test_m52_evaluation.py`.
* Outputs: `docs/research/m52/goal_models_*`. `goal_models_fits.csv` holds
  every snapshot × configuration × model with full diagnostics.

## Summary

1. **Home and away goal expectations can be inferred reliably from the current
   odds when a goals market is included.**
   * All 180 snapshots (20 EPL fixtures) fit, every one is identified, and a
     1% price change moves λ by at most 0.007.
   * With 1X2 odds alone the inversion is weakly conditioned. Under independent
     Poisson it is also biased: λ is about 0.17 too low.
2. **Dixon–Coles with one shared ρ ≈ −0.07 removes the Poisson draw bias.**
   * The mean draw error falls from −1.55 to −0.07 percentage points, and the
     median worst error from 1.6 to 0.4 pp.
   * In leave-one-fixture-out tests it improves all 20 fixtures.
   * Fitted to 1X2 alone, it predicts the unseen BTTS and O/U markets within
     about 1.5 pp on average, against 6.5–7.4 pp for Poisson.
3. **A free ρ per fixture is identifiable only with all three markets.** Even
   then it adds little over the shared ρ and moves by up to 0.009 for a 1%
   price change. A **shared ρ, calibrated separately, is the more stable
   design.**
4. **The market ρ (−0.07) does not match the ρ estimated from historical
   results** (−0.03 to +0.02 by league), and Dixon–Coles does not improve
   predictions of real results in our historical model.
   * So the market's extra draw weight may partly be bookmaker draw pricing
     rather than football.
   * **Fitting the market better is not the same as predicting results
     better.**
5. **No real-result validation is possible yet.** 0 settled fixtures have saved
   pre-kickoff odds; the earliest captured fixtures kick off on 21 November.
   The pipeline is built and rerunnable. At least 150 settled fixtures are
   needed for calibration and 400 across two or more leagues for model
   comparisons.

**Recommendation:**
* Keep this as research.
* Adopt "Dixon–Coles with a shared, separately calibrated ρ, fitted to 1X2 +
  at least one goals market" as the candidate method.
* Revisit for display only after result validation.

## 1. Baseline reproduced (Milestone 5.1)

The 5.1 script was rerun on 16 November and gave byte-identical outputs. The
new 5.2 implementation reproduces the same findings independently:

| Finding | 5.1 | 5.2 |
|---|---|---|
| Poisson, all three markets: good / approximate | 126 / 54 | 126 / 54 |
| Mean draw residual | −1.55 pp | −1.55 pp |
| Median worst error | 1.55 pp | 1.55 pp |
| λ shift, 1X2-only vs all three (median) | 0.17 | 0.17 |

## 2. Data

* **Odds trial:** 9 captures, 15 Nov 11:13 to 16 Nov 06:15 UTC. They are
  replayed into a scratch copy of the database; production data is untouched.
* **Fixtures:** 20 EPL fixtures for 21–29 November, giving 180 fixture snapshots.
  * Every snapshot has all three markets Fresh, from one coherent consensus.
  * No PSL fixture had odds in these captures.
* **Bookmakers per 1X2 consensus:** 10 (90 snapshots), 8 (9), 7 (11), 6 (70).
* **Timestamps:** each row keeps Diski 9's retrieval time (`snapshot_at`) and
  the provider's feed timestamp (`provider_updated_at`) separately. The
  provider updated prices only on 15 Nov 03:24 and 16 Nov 03:00 and 03:25 UTC.
* **Margin removal:** the production proportional method.
* **Freshness:** only fixtures that had not kicked off at each capture are used.
  Stale markets are excluded.

## 3. Models

**Independent Poisson.** Home goals ~ Poisson(λ_H) and away goals ~
Poisson(λ_A), independent. The 1X2, BTTS and Over/Under 2.5 probabilities are
sums over the scoreline grid.

**Dixon–Coles.** Each scoreline probability is P(h, a) = τ(h, a) · Pois(h; λ_H)
· Pois(a; λ_A), where:

| Score | τ |
|---|---|
| 0-0 | 1 − λ_H λ_A ρ |
| 0-1 | 1 + λ_H ρ |
| 1-0 | 1 + λ_A ρ |
| 1-1 | 1 − ρ |
| all others | 1 |

* **Dependence parameter ρ.** Negative ρ moves probability into 0-0 and 1-1
  (more draws) out of 1-0 and 0-1.
* **Mass.** The four adjustments cancel exactly: −λλρ + λλρ + λλρ − λλρ = 0,
  times e^−(λ_H+λ_A). So the distribution needs no renormalisation beyond grid
  truncation. This is verified in tests.
* **Validity.** Every τ must be ≥ 0, which requires max(−1/λ_H, −1/λ_A) ≤ ρ ≤
  min(1/(λ_H λ_A), 1). Values outside this range are rejected. Inside the
  optimiser, a quadratic penalty keeps the search valid.
* **Bounds.** λ ∈ [0.05, 6] and ρ ∈ [−0.3, 0.3].
* **Grid.** The grid is truncated where both Poisson tails are below 1e-12,
  then renormalised. Omitted mass is under 1e-11 in tests.

**Variants:**
* `poisson`
* `dc_fixed(ρ)`, with ρ supplied from a separate calibration
* `dc_free`, with ρ estimated per fixture

## 4. Odds inversion

**Objectives.** Each market enters once, with equal weight, so the
three-outcome 1X2 market cannot dominate just by having more outcomes:
* **KL (primary):** Σ_markets KL(market ‖ model). This is the expected excess
  log loss and is scale-aware.
* **Squared error:** Σ_markets mean_outcomes (p − q)². This is the
  probability-space alternative.

**Optimiser.**
* Bounded L-BFGS-B from a fixed grid of starting points: 7 for two-parameter
  models, 21 for `dc_free`. It is deterministic.
* Convergence, the objective value and the spread between near-optimal starts
  are all recorded.

**Constraints and identification.**
* Constraint counts: 1X2 gives 2 independent constraints, BTTS 1, O/U 2.5 1.
* A fit is attempted only if constraints ≥ parameters.
* Identification uses the singular values of the constraint Jacobian.
  "Unidentified" means smallest ÷ largest < 10⁻³, or near-optimal starts
  disagreeing by more than 0.05.

**Fit categories** (as Milestone 5.1):

| Status | Rule |
|---|---|
| good | worst absolute error ≤ 2 pp |
| approximate | ≤ 4 pp |
| poor | otherwise, or a parameter at its bound |

**Exactly identified fits** have no spare constraint and are labelled as such.

## 5. Identifiability

| Configuration | Constraints | Poisson / DC fixed (2 parameters) | DC free (3 parameters) |
|---|---|---|---|
| 1X2 only | 2 | exactly identified; conditioning (σ_min/σ_max) 0.12 | **not identified** (insufficient) |
| 1X2 + O/U | 3 | over-identified; 0.76 | exactly identified; 0.35 |
| 1X2 + BTTS | 3 | over-identified; 0.54 | exactly identified; 0.35 |
| 1X2 + BTTS + O/U | 4 | over-identified; 0.79 | over-identified; 0.37 |
| O/U only | 1 | only the total λ_H + λ_A | — |
| BTTS only | 1 | not identified (a curve of solutions) | — |

* No snapshot was flagged unidentified, and near-optimal starts always agreed
  (spread 0.000).
* **Fit with ρ free:** with ρ free per fixture (all three markets), the
  objective profile is flat within 10⁻⁵ over a ρ interval about 0.01 wide.
  The best ρ ranges from −0.10 to −0.04 across fixtures.
* **Synthetic recovery (tests).** Known (λ_H, λ_A) are recovered to within
  2e-4 for every configuration. Known (λ_H, λ_A, ρ) = (1.5, 1.2, −0.1) are
  recovered by `dc_free` to within 0.005.

## 6. Fit diagnostics (180 snapshots)

| Configuration × model | Good / approx. | Median worst error | Mean draw error | Mean BTTS error | Mean Over error |
|---|---|---|---|---|---|
| 1X2 + BTTS + O/U, Poisson (KL) | 126 / 54 | 1.55 pp | −1.55 | −0.53 | −0.03 |
| same, Poisson (squared error) | 126 / 54 | 1.55 pp | −1.54 | −0.35 | +0.12 |
| same, DC ρ = −0.027 (historical EPL) | 180 / 0 | 0.95 pp | −0.97 | −0.29 | −0.06 |
| same, **DC ρ = −0.07 (pooled market)** | **180 / 0** | **0.40 pp** | **−0.07** | +0.10 | −0.09 |
| same, DC ρ free | 180 / 0 | 0.11 pp | −0.05 | +0.11 | −0.10 |
| 1X2 + O/U, Poisson | 135 / 45 | 1.52 pp | −1.49 | — | — |
| 1X2 + O/U, DC ρ = −0.07 | 180 / 0 | 0.35 pp | −0.08 | — | — |
| 1X2 + BTTS, Poisson | 126 / 54 | 1.52 pp | −1.54 | — | — |
| 1X2 + BTTS, DC ρ = −0.07 | 180 / 0 | 0.37 pp | −0.04 | — | — |

The full per-snapshot data (market probabilities, model probabilities, absolute
errors, worst and mean errors, λs, total, ρ, convergence, singular values,
bookmaker count and both timestamps) is in `goal_models_fits.csv`.

**Fitted goal expectations** (all three markets, DC ρ = −0.07):
* λ_H median 1.64, range 0.94–2.33
* λ_A median 1.23, range 0.93–2.04
* The KL and squared-error objectives give λ within about 0.01 of each other

## 7. Sensitivity and stability

**Effect of the market configuration:** largest |Δλ| against the Poisson fit
on all three markets, at the same snapshot.

| Fit | Median | p90 |
|---|---|---|
| Poisson, 1X2 only | 0.17 | 0.20 |
| DC ρ = −0.027, 1X2 only | 0.11 | 0.14 |
| **DC ρ = −0.07, 1X2 only** | **0.04** | **0.07** |
| Any fit including a goals market | 0.002–0.010 | ≤ 0.018 |

**Cross-market check (1X2 only).** Fit on 1X2 alone, then predict the BTTS and
O/U markets that the fit never saw:

| Model | BTTS: mean error | BTTS: worst | O/U: mean error | O/U: worst |
|---|---|---|---|---|
| Poisson | 6.5 pp | 9.0 | 7.4 pp | 10.4 |
| DC ρ = −0.027 | 3.9 pp | 6.4 | 4.6 pp | 7.6 |
| **DC ρ = −0.07** | **1.4 pp** | 2.6 | **1.7 pp** | 3.3 |

* So Dixon–Coles with the pooled ρ makes the three markets **mutually
  consistent**. Poisson cannot.
* Caveat: the pooled ρ was estimated from the same fixtures' full markets. The
  leave-one-out ρ was −0.07 for every fixture, so this contamination is
  negligible.

**A 1% move in any single price**, latest snapshot per fixture, refitted:

| Fit | Largest Δλ, median | Largest Δλ, maximum | Largest Δρ, maximum |
|---|---|---|---|
| 1X2 only, Poisson / DC fixed | 0.018 / 0.020 | 0.022 / 0.024 | — |
| 1X2 + O/U, Poisson / DC fixed | 0.006 / 0.006 | 0.007 / 0.007 | — |
| 1X2 + BTTS, Poisson / DC fixed | 0.007 / 0.007 | 0.010 / 0.010 | — |
| All three, Poisson / DC fixed | 0.005 / 0.005 | 0.006 / 0.006 | — |
| All three, DC free | 0.005 | 0.006 | **0.0075** |
| 1X2 + O/U, DC free (exactly identified) | 0.006 | 0.007 | 0.0089 |

**Across captures:** λ for a fixture moves by at most 0.007 between captures.
Prices changed only at the daily provider update.

## 8. Is Dixon–Coles a genuine improvement or just more flexibility?

* **Leave-one-fixture-out pooled ρ.** ρ was estimated on 19 fixtures and
  applied to the 20th:
  * the leave-one-out ρ is −0.07 every time
  * DC beats Poisson on the held-out fixture in **20 of 20** cases
  * median worst error: 1.59 pp (Poisson) against 0.40 pp (DC)
  * mean KL: 0.00088 against 0.00007
* **One parameter for all fixtures,** not one per fixture, removes a
  systematic error across every fixture. That is evidence of a structural
  improvement **in describing the market**, not overfitting.
* **Profile of the pooled objective over ρ** (lower is better):

  | ρ | −0.15 | −0.10 | −0.05 | 0 | +0.05 |
  |---|---|---|---|---|---|
  | Objective | 0.019 | 0.0036 | 0.0028 | 0.0176 | 0.048 |

  The minimum is at −0.07 and well defined.

**Against real results (historical, from Milestone 5.2 goals research):**
* ρ estimated by maximum likelihood from 2023–24 results, given the historical
  goal-rate model: EPL −0.027, Championship +0.020, PSL −0.017, PSL 1st Division
  −0.027. Walk-forward estimates pooled across leagues range from −0.03 to
  +0.006.
* On 3,121 test fixtures, DC − Poisson 1X2 log loss is −0.0002 [−0.0006,
  +0.0002]: no improvement. DC's draw probability (26.6%) is slightly closer to
  the observed 27.9% than Poisson's (26.4%).
* **Interpretation.**
  * Bookmaker prices imply more low-score dependence (−0.07) than results
    suggest (about −0.02).
  * Part of the market's draw "excess" may come from how bookmakers price
    draws, or from proportional margin removal. Some may be genuine football
    dependence that our simple historical model cannot detect.
  * **Only settled fixtures with saved odds can decide this.**

## 9. Validation against actual results

**The pipeline** (`result_validation.py`) works as follows:
1. Take every final, eligible fixture (not awarded, abandoned or a play-off)
   with saved odds.
2. Take its latest snapshot retrieved strictly before kickoff, using only the
   markets that were Fresh at that snapshot.
3. Fit each model and configuration.
4. Score it against the result, next to the market-implied baseline:
   * 1X2 log loss and Brier
   * BTTS and O/U Brier, plus 3-bin calibration
   * mean predicted against observed home, away and total goals
   * the total-goals distribution

Tests cover in-play prices being ignored, postponed and awarded fixtures,
picking the latest snapshot, one record per fixture, and missing markets.

**Current result:** 0 records (trial replay 0, main database 0). The first
captured fixtures kick off on 21 November.

**Minimum evidence before a production recommendation:**

| Purpose | Settled fixtures | Why |
|---|---|---|
| Sanity / calibration | ≥ 150 | 3-bin calibration with about ±8 pp intervals |
| Model vs market, Poisson vs DC on results | ≥ 400 across ≥ 2 leagues | per-fixture log-loss differences between near-identical forecasts are tiny; about 400 are needed to resolve 0.003 |
| Cross-league claims | PSL and 1st Division coverage | PSL had no captured odds in this trial |

At about 10 EPL fixtures a week plus on-demand captures, 150 settled fixtures
takes roughly 3–4 months. Reaching 400 needs regular captures across more
leagues. **Rerun:** `refresh-data` (to store the results), then
`uv run python scripts/research_m52_goal_models.py`.

## 10. Qualitative adjustments (design only; not built)

**Workflow:** market goal expectations → explicit adjustment → revised (λ_H,
λ_A) → recomputed score grid → coherent 1X2, BTTS and O/U probabilities.

**Feasibility:** yes. The model is a two-number summary, so any change to λ
gives a **coherent** set of probabilities.

**Worked example: Aston Villa v Sunderland, 21 Nov** (DC, ρ = −0.07, all
three markets):
* market λ = 1.77 / 1.04
* market 1X2 = 53.7 / 25.0 / 21.3%
* model at those λ = 53.7 / 24.9 / 21.4%; BTTS 54.5%; Over 2.5 53.4%
* Suppose a key Villa forward is ruled out, and an analyst lowers λ_H by 10%
  to 1.59. Recomputing gives 49.4 / 26.7 / 23.9%, BTTS 52.4% and Over 2.5
  49.1%, all moving consistently. Every change is visible and reversible.
* The 10% is purely illustrative: there is no evidence yet for how large such
  an adjustment should be.

**Adjustment size must not be invented.**
* An honest framework would express adjustments in goals (for example "−0.15
  home goals"), cap them, and show them next to the market.
* Its effect sizes would be calibrated later, from settled fixtures where the
  factor was present: injuries to listed key players, rest-day differences,
  managerial changes. This needs line-up and injury data that Diski 9 does not
  yet store.
* Until then, any adjustment is the analyst's opinion and must be labelled as
  such.

**Goal expectations versus Form Scores as the foundation:**

| | Adjust market goal expectations | Adjust Form Scores |
|---|---|---|
| Units | goals, which fans understand | an abstract 0–5 score |
| Coherence | one change updates every market consistently | no link to any market or probability |
| Starting point | the market (best available summary) | five past results |
| Calibration | possible against outcomes | no outcome scale to calibrate against |

**Recommendation:** use market goal expectations as the foundation for
transparent YouTube analysis. Keep Form Scores as descriptive history.

## 11. Limitations

* One league, one matchweek, 20 fixtures and near-static prices. The pooled ρ
  could differ in other leagues or as kickoff nears.
* There is no outcome validation yet.
* Proportional margin removal assigns margin evenly. If bookmakers load extra
  margin on the draw, the implied draw probability and hence ρ are overstated.
  The power or Shin methods are worth testing once results exist.
* The historical ρ comes from a simple attack × defence model whose λ are
  over-dispersed. A better-specified historical model could estimate ρ
  differently.

## 12. Recommendation

| Candidate | Decision |
|---|---|
| Independent Poisson inversion | **Keep as the documented baseline.** It is not suitable for display: −1.55 pp draw bias, and 1X2-only λ too low by 0.17. |
| Dixon–Coles, shared ρ, fitted to 1X2 + at least one goals market | **Consider** as the method for a future research display. **More data needed** (result validation) before any production use. |
| Dixon–Coles with ρ free per fixture | **Reject for production.** It is only identified with all three markets and only marginally better than a shared ρ. |
| 1X2-only inversion | **Reject for display.** It is weakly conditioned, and λ depends on the assumed ρ. |
| Goal expectations in the UI | **More data needed.** Earliest review: after 150 settled fixtures. |
| Qualitative adjustment interface | **More data needed.** Design only; it needs line-up and injury data and an effect-size calibration. |
