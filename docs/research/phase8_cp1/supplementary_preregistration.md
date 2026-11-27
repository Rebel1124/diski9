# Phase 8 CP1 supplementary: Goal Model simplification, pre-registered protocol

*Recorded 27 Nov 2026 **before any supplementary result was computed**. This is research only.*

**Context:**
- It extends [`preregistration.md`](preregistration.md) and reuses its data, the 3-hour availability lag, periods, metrics, bootstrap and helpers (`scripts/research_phase8_cp1.py`).
- The confirmation seasons were examined before. **This is a pre-registered re-analysis, not an untouched holdout.**

**Fixed across every candidate:**
- the 8 domestic leagues;
- current-season team and competition data only;
- available only when **both teams have ≥ 2** completed eligible matches **and the competition has ≥ 20**;
- the same venue-normalised expected goals;
- the same Poisson market maths.

Availability is identical for every candidate, so all comparisons use the same fixtures.

## 1. Candidates

Notation: H and A are the current-season competition home and away goals per match, and g = (H + A) / 2.

For a team with n_h home and n_a away matches:
- E_for = n_h·H + n_a·A
- E_ag = n_h·A + n_a·H

| Model | Definition |
|---|---|
| **A** (reference, not re-tuned) | C1-2-20 strength and tempo. s = √(a₁₂ / d₁₂) and t = √(a₉₆ · d₉₆), where a_k = (GF + k·g) / (E_for + k·g) and d_k = (GA + k·g) / (E_ag + k·g). Then λ_home = H · (s_h / s_a) · t_h · t_a and λ_away = A · (s_a / s_h) · t_h · t_a. |
| **B(k)** | Attack-defence with one common k. a = (GF + k·g) / (E_for + k·g) and d = (GA + k·g) / (E_ag + k·g). Then λ_home = H · a_home · d_away and λ_away = A · a_away · d_home. |
| **C** | B with k = 0: a = GF / E_for and d = GA / E_ag. **No smoothing, clipping or floor.** E_for and E_ag are > 0 whenever the gate passes (≥ 2 matches, H and A > 0). λ = 0 is a valid prediction when a team has scored 0, or its opponent conceded 0. |

**Equivalence (to be verified analytically and numerically):** when k_s = k_t = k and all factors are positive, A reduces to B(k). The research code must show this to within 1e-12.

**Grid for B:** k ∈ {6, 12, 24, 48, 96}, as proposed.
- It brackets A's two values (12 and 96).
- It includes the earlier re-tuned values (6–8).
- It doubles at each step, which suits a smoothing constant measured in pseudo-matches.

## 2. Periods and selection

- **Selection:** 2023/24–2024/25.
- **Confirmation:** 2025/26–2026/27 to date.
- **Choosing B's k:** use the selection period only, by **mean scoreline log-likelihood** (the criterion behind the original k_s and k_t). Ties within 0.0005 go to the larger k, which is more conservative. The choice is then frozen.
- **The confirmation period is evaluated once.**

## 3. Metrics and treatment of zeros

**Metrics:**
- 1X2, BTTS and O/U log loss and Brier score;
- ECE;
- calibration slope (home win, BTTS, O/U);
- coverage (identical by construction);
- paired 95% bootstrap CIs by ISO week.

**Model predictions are never altered.** Two *evaluation-only* safeguards already exist in the shared harness and are disclosed:
1. Log loss clips probabilities to [1e-12, 1 − 1e-12]. A realised outcome given probability 0 therefore costs 27.6 nats, not infinity.
2. The calibration slope clips probabilities to [1e-6, 1 − 1e-6] before taking logits.

**Reported for every model:**
- **impossible events:** realised outcomes assigned probability < 1e-12 (for example a home win when λ_home = 0);
- realised outcomes assigned < 0.1% and < 1%;
- fixtures with λ = 0, λ < 0.2 or λ > 4 for either side; total λ below the 1st percentile and above the 99th;
- fixtures with any 1X2 probability > 95% or < 1%;
- undefined or non-finite values;
- **stability:** the absolute change in a team's log attack and log defence factor between consecutive appearances (median, p95, maximum), by match-count band. For A, the effective factors are attack = s·t and defence = t/s.
- **large scorelines:** the same change after a match in which the team scored or conceded ≥ 5.
- **Sensitivity (secondary, labelled as such):** log loss with impossible-event rows excluded.

## 4. Criteria, each candidate against A on identical fixtures

The CP1 domestic criteria are reused, with A as the comparator instead of C0.

| # | Criterion |
|---|---|
| S1 | 1X2 log-loss Δ: CI upper bound ≤ +0.005 |
| S2 | BTTS and O/U log-loss Δ: CI upper bound ≤ +0.003 (each) |
| S3 | Home-win slope within 0.8–1.25, and home-win ECE ≤ A's + 0.01 |
| S4 | In the 2–5 band, 1X2 beats the current-season competition-frequency baseline (CI entirely below 0) |
| **S5** (new robustness criterion) | **Zero impossible events** in the confirmation period, and no more than A's count + 0.5% of fixtures with a realised outcome below 0.1% |

**Why S5 is added:** an unshrunk model can assign zero probability to outcomes that happen. Log loss alone, after the evaluation clip, would understate that. The S1–S3 verdicts use the same pass / inconclusive / deterioration rule as CP1.

**Per league:** the material-deterioration flag is the same as CP1 (lower bound > 0, or point estimate > +0.010). It is reported, not used as a criterion.

## 5. Recommendation rule (simplest acceptable model)

1. If **C** passes S1–S5 on confirmation, recommend C (no parameter).
2. Otherwise, if **B(k\*)** passes S1–S5, recommend B(k\*) (one parameter).
3. Otherwise, retain **A**.

**Also reported, to inform the owner:**
- what the separate tempo parameter adds over B(k\*), in goals markets, calibration and extreme totals;
- worked examples on real fixtures (typical, early extreme, zero goals, high or low scoring) for A, B(k\*) and C.

**Nothing is adopted automatically.**
