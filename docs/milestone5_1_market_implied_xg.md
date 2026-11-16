# Milestone 5.1 — Market-implied expected goals (research prototype)

*16 November 2026. This is a research prototype. It is not shown in the app,
it is not used in rankings or the Challenge, and it is not a prediction or
staking signal. It belongs to Layer 3 (future model estimates) and stays
separate from Layer 1 (historical indicators) and Layer 2 (market-implied
probabilities).*

**Reproduce:**

```
uv run python scripts/research_market_xg.py
```

The code is in `src/diski9/research/market_implied_xg.py`. The tests are in
`tests/test_market_implied_xg.py`. The outputs are
`docs/research/market_xg_fits.csv` and `docs/research/market_xg_summary.json`.

The script uses no API requests. It replays the committed odds-trial captures
into a scratch copy of the database.

## 1. Question

Given the overround-removed consensus market probabilities for Match Result,
BTTS and Over/Under 2.5, what pair of goal expectations (λ_home, λ_away) is
the market consistent with, and how well does a simple model reproduce the
market?

## 2. Model and assumptions

Home goals ~ Poisson(λ_H) and away goals ~ Poisson(λ_A), independent.

| Market | Model probability |
|---|---|
| Home / Draw / Away | Σ P(h)P(a) over h > a, h = a, h < a |
| BTTS Yes | (1 − e^(−λ_H)) (1 − e^(−λ_A)) |
| Over 2.5 | 1 − P(total ≤ 2), where total ~ Poisson(λ_H + λ_A) |

The score grid is truncated once the Poisson tail falls below 1e-12.

**Assumptions** (all known simplifications):
* Goals are independent.
* There is no draw inflation, which is what Dixon–Coles addresses (section 9).
* Scoring rates are constant through the match.
* The market consensus is a fair probability after proportional overround
  removal.

## 3. Inputs

* The input is `odds.display.display_consensus` at a given instant: the
  snapshot-coherent, overround-removed market-implied probabilities already
  shown in the app.
* By default **only Fresh markets** are used (`from_display(...,
  include_stale=False)`).
* Stale markets can be included only on explicit opt-in. Even then they are
  never retrieved at or after kickoff, which a test enforces.
* Inputs are validated (finite, each in (0, 1), and each market's outcomes
  summing to 1 within 1e-6). Invalid input returns `invalid_input`.
* The research script fits only fixtures that had **not yet kicked off** at
  evaluation time. It evaluates at the capture's last page `retrieved_at`.

## 4. Fitting objective

Minimise Σ over available markets of KL(market ‖ model) = Σ_i p_i ·
ln(p_i ÷ q_i), with equal weight per market. Why KL:
* **It is the natural divergence between probability distributions.** It is
  the expected log-loss penalty of using the model in place of the market.
* **It is scale-aware.** A one-point miss on a 10% outcome costs more than on
  a 60% outcome, unlike squared error.
* **It is zero exactly when the model reproduces the market.**
* **Equal market weights** stop the three-outcome 1X2 market from dominating
  the two-outcome markets merely by having more terms.

**Optimiser:** bounded L-BFGS-B on (λ_H, λ_A) ∈ [0.05, 6]², with a fixed grid
of starting points. It is deterministic. The best converged solution is kept.

## 5. Identifiability

* **O/U 2.5 alone** identifies only the total λ_H + λ_A. The prototype
  reports `lambda_total` via a one-dimensional fit and returns
  `insufficient_market_data` for the split.
* **BTTS alone** constrains only the product (1 − e^(−λ_H))(1 − e^(−λ_A)).
  That is a curve, not a point, so it returns `insufficient_market_data`.
* **1X2 alone** has two free probabilities for two parameters, so it is
  exactly identified but weakly conditioned. The smallest Jacobian singular
  value has a median of 0.056 on real data.
* **1X2 + O/U, 1X2 + BTTS, or all three** are over-identified and well
  conditioned (median smallest singular values 0.33, 0.25 and 0.38).
* The singular values of the residual Jacobian are reported for every fit as
  a conditioning diagnostic.

**Synthetic recovery** (tests): probabilities generated from known λ are
recovered to within 2e-4 for 1X2, 1X2 + O/U, 1X2 + BTTS and all three.
O/U alone returns the exact total (2.70 in the test). BTTS alone is correctly
flagged as not identified.

## 6. Diagnostics and fit categories

* Every fit reports per-outcome residuals (model − market), the maximum
  absolute residual, convergence, whether a bound was hit, and singular
  values.
* Fit categories:

| Status | Rule |
|---|---|
| `good_fit` | max \|residual\| ≤ 0.02 (2 percentage points) |
| `approximate_fit` | ≤ 0.04 |
| `poor_fit` | > 0.04, or the solution sits at a λ bound |
| `insufficient_market_data` | fewer constraints than parameters |
| `invalid_input` | validation failed |
| `optimization_failure` | no start converged |

Why these thresholds:
* Rounding of decimal odds to two places moves implied probabilities by only
  about 0.03–0.13 pp, so the observed residuals are model misspecification,
  not price noise.
* 2 pp is roughly the size of the independent-Poisson draw bias reported in
  the literature. It is the level at which the fitted λ still describe the
  market sensibly.
* Above 4 pp the model visibly fails to describe the market.

The thresholds are heuristics for a research tool, not statistical tests.

## 7. Results on cached odds

**Coverage:**
* 9 trial captures and 20 EPL fixtures (Matchweek 12), with 180 fixture
  snapshots that have all three markets Fresh.
* No PSL fixture qualified: none had Fresh pre-kickoff odds in the captures
  evaluated.

| Markets used | Status counts (180 snapshots) |
|---|---|
| 1X2 only | 180 exactly identified (reported as good) |
| O/U only / BTTS only | 180 insufficient |
| 1X2 + O/U | 135 good, 45 approximate |
| 1X2 + BTTS | 126 good, 54 approximate |
| All three | **126 good, 54 approximate, 0 poor** |

**Residuals (all three markets):**
* Max |residual| percentiles: p10 0.8 pp, median 1.6 pp, p75 2.1 pp, p90
  2.2 pp, max 2.3 pp.
* Mean residuals: draw **−1.55 pp** (the model systematically under-prices
  the draw), home +0.7 pp, BTTS Yes −0.5 pp, Over 2.5 −0.03 pp.

**Fitted values (all three markets):**

| | Min | Median | Max |
|---|---|---|---|
| λ_H | 0.95 | 1.64 | 2.32 |
| λ_A | 0.93 | 1.24 | 2.04 |
| Total | 2.65 | 2.90 | 3.28 |

**Sensitivity to the market combination** (max change in λ against the
all-three fit):

| Markets | Median change | p90 change |
|---|---|---|
| 1X2 only | 0.17 | 0.20 |
| 1X2 + O/U | 0.010 | — |
| 1X2 + BTTS | 0.006 | — |

* 1X2 alone systematically understates both λ. The draw bias is absorbed
  into lower scoring.
* So **a goals market should be required** before any λ is shown.

**Stability across captures:** the maximum λ range per fixture is 0.007. The
provider changed prices only once during the trial (16 Nov, about 03:25 UTC),
consistent with its daily refresh.

## 8. Worked examples (Fresh, 16 November)

| Fixture | Market H/D/A, BTTS Yes, Over | Model H/D/A, BTTS Yes, Over | λ_H / λ_A (total) | Max residual | 1X2-only λ |
|---|---|---|---|---|---|
| Man City v Fulham (1.40 / 5.00 / 7.08; BTTS 1.66 / 2.10; O/U 1.49 / 2.60) | 67.7 / 19.0 / 13.4; 55.9; 63.6 | 67.9 / 18.1 / 14.0; 55.5; 63.6 | 2.32 / 0.96 (3.28) | 0.8 pp | 2.17 / 0.85 |
| Liverpool v Man Utd | — | — | 2.00 / 1.24 (3.24) | 1.4 pp | 1.81 / 1.08 |
| Newcastle v Arsenal | — | — | 0.97 / 1.95 (2.92) | 1.0 pp | 0.87 / 1.82 |

The full table is in `docs/research/market_xg_fits.csv`.

## 9. Historical evaluation and Dixon–Coles assessment

**Outcome validation was not possible.**
* **0 fixtures** have both pre-kickoff odds and a final result.
* The trial began on 15 November and Matchweek 12 has not been played.
* Historical odds are deliberately not backfilled.
* At least about 100–200 settled fixtures are needed for any calibration
  statement. At current capture rates that means several EPL and PSL rounds.

**Dixon–Coles.**
* The consistent −1.55 pp draw residual is exactly the low-score dependence
  that Dixon–Coles corrects. It adjusts the 0-0, 1-0, 0-1 and 1-1
  probabilities with a parameter ρ.
* With all three markets there are 4 independent constraints for 3 parameters
  (λ_H, λ_A, ρ). So ρ is estimable per fixture, or more robustly as one ρ per
  league fitted across fixtures.
* **Recommendation:** prototype a pooled-ρ Dixon–Coles fit offline next. The
  test is whether it removes the draw bias and pulls the share of good fits
  from 70% towards 100%.
* Do **not** put it in production until outcome validation is possible.

## 10. Qualitative adjustment concept (not implemented)

A future Layer 3 could let a user see "market λ" next to a transparent,
documented adjustment, for example confirmed absences expressed as a capped
percentage change to one side's λ. The adjusted model probabilities would be
shown alongside, never replacing, the market. It would need:
* an explicit, auditable adjustment rule
* clear labelling as an estimate
* no EV, edge or staking language

This is a concept only and needs approval.

## 11. Limitations

* Twenty fixtures from one league and one matchweek, with near-static prices.
* No outcome validation.
* The independent-Poisson draw bias is present.
* Proportional overround removal is assumed. Shin or power methods would
  shift favourite–longshot probabilities slightly.
* λ is a market-implied scoring rate, not shot-based xG. It should never be
  labelled "xG" in the UI without that distinction.

## 12. Recommendation

* **Keep this as research.** The method is sound, deterministic and well
  conditioned when a goals market is present. It reproduces the market within
  about 2 pp. But:
  * it has a known draw bias
  * it has zero outcome validation
* **Do not add it to the UI yet.**
* Next steps:
  1. continue capturing odds so settled fixtures accumulate
  2. prototype pooled-ρ Dixon–Coles offline
  3. revisit display, which would require approval, only with outcome
     validation and a goals market required, labelled "market-implied goal
     expectation"
