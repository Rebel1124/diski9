# Phase 8 CP1 supplementary: Goal Model simplification report

*27 Nov 2026. This is research only.*

**What was not done:**
- no production code, dependency or lockfile changes;
- no provider calls;
- no database access.

**Context and labels:**
- The protocol was pre-registered in [`supplementary_preregistration.md`](supplementary_preregistration.md) and committed as `3730a0d` **before any result.**
- **[V]** marks a computed result; **[R]** a recommendation.
- The confirmation seasons were examined before. **This is a pre-registered re-analysis, not an untouched holdout.**

**Reproduce:**

```bash
uv run python scripts/research_phase8_cp1b.py
```

```bash
uv run pytest tests/test_phase8_cp1b_research.py
```

- The run takes about 15 s.
- Outputs: `simplification_summary.json` and `simplification_comparison.csv`.

## Summary and recommendation

**[R] Retain Model A** (separate strength and tempo shrinkage, k_s 12 and k_t 96), the agreed C1-2-20 model. The rule's three outcomes:

| Model | Outcome |
|---|---|
| **Model C** (no shrinkage) | **Fails decisively.** In 60 confirmation fixtures it gave probability 0 to things that then happened, and it is far less accurate in every market. |
| **Model B** (one common parameter; k = 12 selected) | **Matches A exactly for match results.** It is significantly worse for BTTS and Over/Under, beyond the pre-registered margin. Its goals-market calibration error roughly doubles. |
| **Model A** | The heavier tempo shrinkage **earns its place**: it is what makes the goals markets reliable. |

So the second parameter is not decoration.
- **Strength:** k = 12 answers "who is better", and responds quickly.
- **Tempo:** k = 96 answers "how many goals", and moves slowly, because total goals are noisy.

That two-part story is also explainable to beginners (§F).

## 0. Equivalence (verified)

With k_s = k_t = k:

- **Strength:** s = √(a/d)
- **Tempo:** t = √(a·d)
- Therefore s·t = a and t/s = d.

So:
- λ_home = H · (s_h/s_a) · t_h · t_a = H · (s_h·t_h) · (t_a/s_a) = **H · a_home · d_away**
- λ_away = A · a_away · d_home, likewise.

This is exactly Model B whenever all factors are positive.

**Numerical check [V]:**
- across k ∈ {6, …, 96}, the largest difference over 8,474 fixtures is 1.8e-15;
- the research Model A reproduces the CP1 C1-2-20 values exactly (difference 0);
- unit tests enforce 1e-12.

**When a factor is 0** (k = 0 and no goals scored or conceded), the ratio form s_h/s_a is undefined, but the direct form still works. Model C was therefore evaluated in the direct form, with **no safeguards.**

## A. Overall predictive performance

**[V]** Confirmation 2025/26–2026/27: 3,269 identical fixtures.

- Availability is the same for all models (C1-2-20). No fixture is excluded beyond the agreed gate: 8,474 of 9,164 are available over all seasons.
- **Selection of B's k:** by scoreline log-likelihood on the selection period. k = 12 scored −2.8845, best in the grid; the others were k = 6 −2.8920, k = 24 −2.8896, k = 48 −2.9046, k = 96 −2.9227. For comparison, A scored −2.8808, better than every B.

| | A (12 / 96) | B (k = 12) | C (k = 0) |
|---|---|---|---|
| 1X2 log loss | 1.0300 | **1.0296** | 1.1943 |
| BTTS log loss | **0.6880** | 0.6931 | 1.0671 |
| O/U 2.5 log loss | **0.6828** | 0.6880 | 0.7613 |
| 1X2 Brier | 0.6186 | **0.6183** | 0.6378 |
| Home-win slope / ECE | 1.08 / 0.010 | 1.08 / 0.009 | 0.35 / 0.075 |
| BTTS slope / ECE | **0.63 / 0.025** | 0.47 / 0.047 | −0.02 / 0.113 |
| O/U slope / ECE | **0.76 / 0.021** | 0.60 / 0.045 | 0.17 / 0.100 |

A slope below 1 means the probabilities are too extreme. B's goals-market probabilities are more extreme, and worse calibrated, than A's.

**Paired differences against A, with criteria:**

| Criterion | B (k = 12) | C |
|---|---|---|
| S1: 1X2 Δ (≤ +0.005) | −0.0005 [−0.0018, +0.0009] **pass** | +0.164 [+0.060, +0.304] **deterioration** |
| S2: BTTS Δ (≤ +0.003) | **+0.0051 [+0.0022, +0.0079] deterioration** | +0.379 **deterioration** |
| S2: O/U Δ (≤ +0.003) | **+0.0053 [+0.0012, +0.0094] deterioration** | +0.078 **deterioration** |
| S3: home calibration | pass | **fail** (slope 0.35) |
| S4: 2–5 band against baseline | pass | **fail** (worse than baseline) |
| S5: robustness | pass (0 impossible events) | **fail** (60 impossible events) |
| **Result** | **fails S2** | **fails S1–S5** |

**Under the pre-registered rule:** C fails and B fails, so **retain A.**

**C sensitivity (secondary).** With the 48 fixtures containing impossible events removed, C is still significantly worse:

| Market | Δ against A |
|---|---|
| 1X2 | +0.029 [+0.015, +0.045] |
| BTTS | +0.043 |
| O/U | +0.047 |

## B. Early-season performance

**[V]** Δ against A by the smaller team's completed matches:

| Matches | n | B: 1X2 Δ | B: BTTS Δ | B: O/U Δ | C: 1X2 Δ |
|---|---|---|---|---|---|
| 2 | 113 | −0.001 | +0.009 | +0.013 | **+2.18** |
| 3 | 153 | −0.002 | +0.004 | −0.002 | +0.95 |
| 4 | 153 | −0.002 | +0.007 | −0.003 | +0.43 |
| 5 | 157 | −0.004 | +0.005 | +0.002 | +0.28 |
| 2–5 | 576 | −0.002 [−0.006, +0.001] | +0.006 | +0.002 [−0.003, +0.007] | +0.87 [+0.40, +1.46] |
| 6–9 | 589 | −0.000 | +0.006 | +0.007 | +0.033 |
| 10+ | 2,104 | −0.000 | +0.005 | **+0.006 [+0.001, +0.010]** | +0.008 |

**Reading it:**
- **B:** its slight early 1X2 edge is within noise (single-count bands of about 150 fixtures are noisy). Its BTTS cost is consistent across every band, and its O/U cost is significant at 10+ matches. So the tempo benefit is not just an early-season effect.
- **C:** catastrophic early (2–5 matches). It approaches A only after 10 or more matches.

## C. Competition-level performance (B against A)

**[V]**
- **1X2:** B shows no material deterioration in any league. The largest Δ is EPL +0.0009 and Serie A +0.0011.
- **Goals markets:** B's losses concentrate in:
  - EPL: BTTS +0.008, O/U +0.013;
  - PSL 1st Division: +0.008 and +0.011;
  - Serie A: +0.007 and +0.011;
  - Championship: +0.004 and +0.007.
- **C** is flagged with material deterioration in **all 8 leagues.**

No league-specific parameters were considered.

## D. Robustness and extreme predictions

**[V]** Confirmation, 3,269 fixtures:

| | A | B (12) | C |
|---|---|---|---|
| Undefined or non-finite λ | 0 | 0 | 0 (direct form) |
| Fixtures with λ = 0 | 0 | 0 | **61** |
| λ < 0.2 / λ > 4 | 0 / 0 | 0 / 1 | 101 / 49 |
| Total λ: min, p1, median, p99, max | 1.60, 1.82, 2.69, 3.83, 4.67 | 1.30, 1.61, 2.62, 3.95, 5.12 | 0.00, 0.74, 2.55, 5.18, **8.17** |
| Any 1X2 > 95% / < 1% | 0 / 0 | 0 / 0 | 35 / 88 |
| **Realised outcome at probability 0** | 0 | 0 | **60** |
| Realised outcome < 0.1% | 0 | 0 | 50 fixtures (1.5%) |
| Change per extra match, median / p95 / max, at 2–5 matches | 0.027 / 0.085 / 0.152 | 0.056 / 0.115 / 0.249 | 0.229 / 0.712 / **1.557** |
| The same, at 10+ matches | 0.016 / 0.045 / 0.094 | 0.026 / 0.062 / 0.161 | 0.041 / 0.123 / 0.473 |
| The same, after a ≥ 5-goal match | 0.060 / 0.111 / 0.152 | 0.091 / 0.178 / 0.249 | 0.159 / 0.788 / 1.557 |
| Changes involving a zero factor | 0 | 0 | 65 (log undefined) |

**How to read the stability rows:** the change is |Δ log factor|. A value of 0.1 means about a 10% move in a team's attack or defence after one more match; 1.56 means a factor of about 4.8.

The selection period shows the same pattern for C: 65 fixtures with λ = 0 and 46 impossible events.

**Separating C's problems:**

| Type | Finding |
|---|---|
| Mathematically valid zeros | λ = 0 is the correct output of C's formula after a clean sheet or a scoreless run, which is common after 2 matches |
| Undefined calculations | none in the direct form. The strength-tempo ratio form *would* be undefined (division by 0). |
| Overconfident probabilities | 0% BTTS, 0% away win, and 1X2 probabilities above 95% in 35 fixtures |
| Metric problems | log loss is infinite for impossible events. The harness's existing evaluation-only clip (1e-12) caps each at 27.6 nats. This is disclosed, and the predictions themselves were never altered. |
| Availability limits | none. The gate is the same for every model. |

**Disclosed evaluation-only safeguards:** the log-loss clip at 1e-12, and the slope's probability clip at 1e-6. Neither changes any prediction.

## E. What separate strength and tempo achieve

**[V]** A against B (k = 12) differ *only* in tempo shrinkage (96 against 12):

| Question | Answer |
|---|---|
| Improves goals markets? | **Yes:** BTTS −0.0051 [−0.0079, −0.0022] and O/U −0.0053 [−0.0094, −0.0012], both significant |
| Improves calibration? | **Yes, for goals:** BTTS ECE 0.025 against 0.047, O/U 0.021 against 0.045. Slopes are closer to 1 (0.63 against 0.47; 0.76 against 0.60). Home-win calibration is unchanged. |
| Reduces extreme totals? | **Yes:** total λ p99 3.83 against 3.95, maximum 4.67 against 5.12. The lowest total rises from 1.30 to 1.60. |
| Steadier estimates? | **Yes:** team factors move about half as much per match (median 0.027 against 0.056 early) |
| Cost to match results? | **None measurable:** 1X2 +0.0005 [−0.0009, +0.0018] |

**In plain terms:** "who wins" information builds up quickly, so 12 imaginary average matches is enough. "How many goals" is much noisier, so it needs about 96 before a team's own scoring is trusted. One common value must compromise: either the goals markets get noisy (k = 12) or the match results become too timid (k = 96 scored worst in selection).

## F. Educational comparison (real confirmation fixtures)

### F1. A typical fixture, step by step

**QPR v Birmingham** (Championship, 9 Dec 2025; actual 2-1).
- League rates: H = 1.4027 home goals and A = 1.2522 away goals per match, so g = 1.3274.
- Both teams have played 19 (9 home, 10 away).

**Observed records:**

| Team | Scored | Conceded |
|---|---|---|
| QPR | 25 (expected 25.15) | 29 (expected 25.30) |
| Birmingham | 28 (expected 25.15) | 23 (expected 25.30) |

Expected scored = 9 × H + 10 × A = 25.15; expected conceded = 9 × A + 10 × H = 25.30.

**Model C** (raw ratios):
- QPR attack 25/25.15 = 0.994, defence 29/25.30 = 1.146.
- Birmingham attack 1.114, defence 0.909.
- λ_home = 1.4027 × 0.994 × 0.909 = **1.27**
- λ_away = 1.2522 × 1.114 × 1.146 = **1.60**

**Model B** (add 12 average matches, 12 × g = 15.93 goals, to both sides of each ratio):
- QPR attack (25 + 15.93) / (25.15 + 15.93) = 0.996, defence 1.090.
- Birmingham attack 1.070, defence 0.944.
- λ = **1.32 / 1.46**

**Model A:**
- **Strength** (from the k = 12 factors): √(attack/defence). QPR 0.956, Birmingham 1.064.
- **Tempo** (from k = 96 factors, about 127 extra goals): √(attack × defence). QPR 1.012, Birmingham 1.002.
- λ_home = 1.4027 × (0.956 / 1.064) × 1.012 × 1.002 = **1.28**
- λ_away = 1.2522 × (1.064 / 0.956) × 1.012 × 1.002 = **1.41**

**Results:**

| | λ home / away | Home / Draw / Away | BTTS Yes | Over 2.5 |
|---|---|---|---|---|
| A | 1.28 / 1.41 | 34.0 / 25.8 / 40.2 | 54.6 | 50.4 |
| B (12) | 1.32 / 1.46 | 34.2 / 25.3 / 40.5 | 56.3 | 52.6 |
| C | 1.27 / 1.60 | 30.3 / 24.6 / 45.1 | 57.3 | 54.6 |

### F2. Other examples (λ home / away → Home / Draw / Away %, BTTS %, Over 2.5 %)

**Early season, extreme results:** AS Roma v Atalanta (Serie A, 5 Sep 2026; actual 2-1).
- Roma: 2 played, 8-0 aggregate. Atalanta: 2 played, 3-1.

| Model | λ | Probabilities |
|---|---|---|
| A | 1.31 / 1.28 | 37.4 / 26.5 / 36.2; BTTS 52.7; Over 47.8 |
| B | 1.32 / 1.30 | 37.5 / 26.3 / 36.3; BTTS 53.3; Over 48.7 |
| C | 1.21 / **0.00** | 70.1 / 29.9 / **0.0**; BTTS **0.0**; Over 12.2 |

Atalanta scored, so C assigned **probability 0** to what happened. A and B show the strong pull back to average after only 2 matches.

**Zero goals conceded:** Charlton v Leicester (Championship, 23 Aug 2025; actual 0-1).
- Charlton: 2 played, scored 1, conceded 0.

| Model | λ | Probabilities |
|---|---|---|
| A | 1.26 / 1.38 | 34.2 / 26.1 / 39.7; BTTS 53.6; Over 49.1 |
| B | 1.15 / 1.26 | 33.6 / 27.6 / 38.8; BTTS 48.8; Over 43.1 |
| C | 0.52 / **0.00** | 40.4 / 59.6 / **0.0** (away win impossible; it happened); Over 1.6 |

**Two high-scoring teams:** Barcelona v Real Madrid (La Liga, 25 Oct 2026; actual 1-2).
- 9 played each: Barcelona 39-9, Real Madrid 23-9.

| Model | λ | Probabilities |
|---|---|---|
| A | 2.18 / 1.19 | 59.8 / 20.1 / 20.1; BTTS 61.8; Over 65.5 |
| B | 2.65 / 1.45 | 63.1 / 17.5 / 19.4; BTTS 71.1; Over 77.6 |
| C | 3.32 / 1.44 | 73.6 / 13.4 / 13.0; BTTS 73.6; Over 85.3 |

**Two low-scoring teams:** Leicesterfield v Highbury (PSL 1st Division, 17 Oct 2025; actual 2-1).
- 6 played each: 3-2 and 6-3; league g = 0.92.

| Model | λ | Probabilities |
|---|---|---|
| A | 0.94 / 0.82 | 36.8 / 33.3 / 30.0; BTTS 34.0; Over 25.8 |
| B | 0.75 / 0.65 | 33.8 / 38.3 / 27.9; BTTS 25.2; Over 16.6 |
| C | 0.31 / 0.31 | 20.1 / 59.1 / 20.8; BTTS 7.1; Over 2.5 |

**Pattern:** B and especially C chase short-run goal totals (Barcelona 85% Over, PSL1 2.5% Over). A keeps totals near the league's rate until the evidence is substantial.

### F3. Communicating each model to a beginner

| Model | Beginner explanation | Problem |
|---|---|---|
| **C** | "Goals scored and conceded compared with average." Simplest. | Shows users 0% outcomes that then happen. Not defensible. |
| **B** | "Same, but every team starts with 12 average matches, so early results don't swing the numbers." One idea. | Good for match results, noisier for goals. |
| **A** | "Two dials. **Strength:** how much better one team is than the other; it learns quickly, after about 12 games' worth of evidence. **Tempo:** whether a team's matches are high or low scoring; it learns slowly, because goal totals jump around." | One more concept, but it maps onto two questions users already ask: *who wins?* and *how many goals?* The maths (two shrunk ratios, square roots) is behind the "detailed maths" toggle. |

## Implications

**CP2 (backend):**
- **No change from the agreed plan.** Model A is the existing Goal Model formula with the approved C1-2-20 data rules (m0 removed, gates added).
- B or C would not have reduced CP2 effort materially. The formula is a few lines either way.

**CP3 (education):**
- Present A as the "two dials" story, with the step-by-step numbers as in F1.
- One extra explanatory panel (strength against tempo, and why tempo learns slowly): about +1 hour inside the existing CP3 estimate.
- Worked examples can reuse the payload values that already exist (attack and defence at k_s and k_t, strength, tempo).

**Estimates:** CP2–CP4 stay at **about 52–72 active hours.**

**Actual research effort:** about **2 active hours** (protocol, script, tests, runs, report).

## Limitations

| # | Item |
|---|---|
| 1 | A re-analysis of previously examined seasons, not an untouched holdout. |
| 2 | B's k was chosen by scoreline log-likelihood. A 1X2-focused choice could favour a different k, but B's goals-market deficit against A comes from compromising on one value; no single k avoids it (k = 96 has the least goals noise but scored worst overall in selection). |
| 3 | 2026/27 is partial. Single-match-count bands (about 110–160 fixtures) are noisy. |
| 4 | Even A's goals-market slopes are below 1 (0.63 and 0.76): those probabilities are somewhat too extreme. This is a pre-existing, accepted limitation, and no further model work is planned for the MVP. |
| 5 | The worked examples were chosen by fixed rules (typical, largest early swing, first zero-goals case, highest and lowest scoring), not hand-picked. |
