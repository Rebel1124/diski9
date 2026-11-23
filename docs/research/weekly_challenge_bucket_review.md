# Weekly Challenge probability buckets — research review (A, B, C, D, A2, A3)

**Status:** research record (read-only investigation, November 2026). The owner approved
**Scenario A3** (`a3-432-v1`) after independent review: Foundation 60–90%, Balanced 40–60%,
Challenger 10–40%, with 4/3/2 selections, 40/30/20/10 credits and D-31 unchanged. This
document preserves the evidence. It does not change the production configuration; the
implementation is planned in separate, separately authorised checkpoints.

* Reproduction tool: [`tools/research/weekly_challenge_buckets/`](../../tools/research/weekly_challenge_buckets/README.md)
* Aggregate outputs: [`weekly_challenge_buckets/summary.json`](weekly_challenge_buckets/summary.json)
  and [`weekly_challenge_buckets/weekly.csv`](weekly_challenge_buckets/weekly.csv)
* Earlier context: [Phase 6A.1 risk-structure research](weekly_challenge_risk_structure.md)

All figures below come from the committed `summary.json` (fixed seeds, 20 proxy draws).
**Real** means observed market data; **proxy** means a model-based estimate.

## 1. Question and outcome

The approved Broad-60 buckets (C-09: Foundation 60–95%, Balanced 40–60%, Challenger 20–40%)
were reviewed in three rounds:

1. **Availability (Scenarios A–D).** Would tighter bands (B: 70–90 / 50–70 / 30–50;
   C: 75–90 / 60–75 / 45–60) or a data-driven alternative (D: 60–90 / 45–60 / 30–45) still let
   users complete 4/3/2 every week?
2. **Difficulty and scoring (A, A2, D).** A2 lowers only the Foundation ceiling to 90%.
3. **Wider Challenger (A3).** A3 = A2 with Challenger widened to 10–40%.

**Outcome:** B and C fail availability, because Foundation's lower bound is the binding
constraint. D reverses the Balanced/Challenger difficulty order. A2 is equivalent to A. A3
keeps availability and the difficulty order, and the D-31 recovery gate makes extreme long
shots score *fewer* points. A3 was approved for its simple, symmetric ranges and the extra
underdog choice, together with Goal Model guidance and a 10–20% high-risk underdog warning.

## 2. Rules used (unchanged production rules)

| Rule | Source |
|---|---|
| Buckets by **margin-adjusted market probability** at full precision; lower bound inclusive, upper exclusive, Foundation's top inclusive | C-09; `challenge/config.py` |
| 4 Foundation, 3 Balanced, 2 Challenger on **9 distinct fixtures**; markets 1X2, BTTS, Over/Under 2.5 | C-01, C-10 |
| Strict consensus: ≥ 3 bookmaker groups, quotes ≤ 24 h, complete market | C-06 |
| Round opening: ≥ 15 eligible fixtures, ≥ 3 leagues, exact 4/3/2 matching | D-28 |
| Payout: fixed stake × product of the snapshot's reference odds; nine-fold 10 credits; D-15 rounding | C-11, `structured.evaluate_groups` |
| Points: recovery (gross ≥ 100) required; ranks 1–10 earn 150…90, other recoveries 75 | C-20, D-31 |
| Round window Fri 00:00 – Tue 00:00 UTC; publication Thursday | `weekend` schedule |

## 3. Data and limitations

| Source | Kind | Coverage |
|---|---|---|
| `weekly_challenge_risk/pool_fortnight.json` | **Real** strict-consensus market snapshot, 17 Nov 2026 22:00 UTC | 2 windows: 20–23 Nov (fully priced, 60 fixtures, 6 leagues) and 27–30 Nov (priced early, 29 fixtures, 3 leagues). PSL and PSL 1st Division had no qualifying odds |
| Historical odds | – | **Not available** (never backfilled) |
| Historical proxy | **Estimate.** Goal Model 1.0 rerun point-in-time for 5,012 completed fixtures (cutoff Thursday 06:00 UTC), mapped to market scale with a logit-linear calibration fitted on the real snapshot plus resampled real residuals; proxy odds = average market return ÷ probability | 49 weeks, Aug 2025 – Nov 2026, 6 European leagues (8-league variant as a sensitivity check) |
| Actual results | Real final scores of the proxy fixtures, used **only** to settle after selection | same 49 weeks |

**Limitations:**
* Real market evidence is one snapshot (about one and a half representative weeks).
  Everything across 49 weeks is an estimate, not observed betting markets.
* The calibration is fitted in-sample on that snapshot. Against actual results it overstates
  strong favourites and understates long shots (§8). Absolute completion rates are therefore
  less reliable than comparisons between scenarios.
* August 2025 failures partly reflect four leagues whose first stored season needs 30 matches
  before Goal Model forecasts exist. Early-season model shrinkage also depresses favourites.
* Bucket and nine-fold probabilities assume independence across fixtures (reasonable for
  distinct fixtures). Shared shocks would correlate legs; settlement on actual results captures
  real correlation, but only over about 44 weeks.
* Leaderboard players are simulated (30 conservative, 40 random, 30 aggressive, with logit
  noise). Real behaviour may differ. Champion shares rest on 32–100 championships per run and
  are noisy.
* No look-ahead: forecasts use only results before the round; selections use only pre-match
  probabilities.

## 4. Methodology

* **Feasibility** uses the production matching (`structured._match`) and the full D-28 rules.
* **Strategies:**
  * **Conservative:** the exact maximum of Σ log p over valid 4/3/2 portfolios on distinct
    fixtures (an assignment problem), so the highest probability that all nine win.
  * **Aggressive:** the exact minimum.
  * **Random:** uniform over valid portfolios at outcome level (rejection sampling).
  * Where a fixture has several outcomes in a bucket, the objective's best outcome is used;
    ties break on market and outcome name.
* **Exact portfolio figures** (bucket completion, all nine, recovery, expected gross) come from
  `structured.evaluate_groups` at market probabilities.
* **Leaderboard:** 100 players a round, production `scoring.score_round` (D-31), 10-round
  championships. Scenarios are **paired**: identical match outcomes and identical participant
  noise. Runs: real pool with simulated market-implied Poisson scorelines (5 × 200 rounds), and
  proxy weeks settled on actual results (8 × 40 rounds). Uncertainty is the standard error
  across replicates.

## 5. Investigation 1: weekly availability (A, B, C, D)

Unique fixtures per bucket per week (median, with p10 / p25), proxy, 6 leagues, 20 draws:

| Scenario | Foundation | Balanced | Challenger | Unplayable weeks (of 49) |
|---|---|---|---|---|
| A (60–95 / 40–60 / 20–40) | 26 (8 / 20) | 56 (22 / 46) | 55 (22 / 45) | **5.0** (all season-start or thin weeks) |
| B (70–90 / 50–70 / 30–50) | **5** (0 / 2) | 59 | 59 | **16.9** (range 15–19) |
| C (75–90 / 60–75 / 45–60) | **2** (0 / 0.8) | 25 | 54 | **38.5** (range 36–42) |
| D (60–90 / 45–60 / 30–45) | 26 (8 / 20) | 54 | 49 | 5.0 |

**Real weeks** (unique fixtures F / B / C; ✓ means 4/3/2 feasible):

| Scenario | 20–23 Nov | 27–30 Nov |
|---|---|---|
| A | 36 / 56 / 57 ✓ | 12 / 27 / 29 ✓ |
| B | 12 / 60 / 60 ✓ | 3 ✗ |
| C | 4 / 35 / 54 ✓ (zero Foundation choice) | 3 ✗ |
| D | 36 / 54 / 52 ✓ | 12 / 26 / 25 ✓ |

* **Foundation's lower bound is the only binding constraint.** In the investigation's grid
  search (Foundation floor 55–65%, Balanced 40–50%, Challenger 20–35%; an exploratory
  scratch run, not part of the committed outputs), only the Foundation floor changed
  feasibility. The proxy gave about 5 unplayable weeks at 55–60%, about 6 at 62% and about 7
  at 65%. The committed outputs give about 17 at 70% (B) and about 38 at 75% (C).
* Outcomes above 70–75% are almost all home wins by a few elite clubs, so B and C concentrate
  Foundation on the same handful of picks.
* Every fixture has at least one outcome between 45% and 90%, so Scenario C's **total**
  eligible fixtures equal every other scenario's (proxy 2,498; real 89). An earlier summary
  table showed 2,381 and 80, which were Challenger-bucket counts in the wrong row (corrected).

## 6. Investigation 2: difficulty, strategies and scoring (A, A2, D)

Completion probabilities, real week 20–23 Nov (exact; conservative / random / aggressive):

| Scenario | Foundation | Balanced | Challenger | All nine | Recovery |
|---|---|---|---|---|---|
| A = A2 | 42.9 / 19.7 / 13.1 % | 21.1 / 12.5 / 6.5 % | 15.9 / 8.9 / 4.1 % | 1.44 / 0.22 / 0.03 % | 33.6 / 35.9 / 22.0 % |
| D | 42.9 / 19.7 / 13.1 % | 21.1 / 13.8 / 9.2 % | **19.9 / 14.7 / 9.2 %** | 1.81 / 0.40 / 0.11 % | 27.9 / 39.5 / 28.3 % |

* **Difficulty order** (Foundation > Balanced > Challenger), in proxy weeks: A and A2 hold it
  in 439 of 439 weeks for random and aggressive, and **418 of 439 (95%) for conservative**. In
  the other weeks there are few strong favourites, so the best four-pick Foundation is slightly
  less likely than the best three-pick Balanced. That is a property of 4/3/2 with a 60% floor,
  not of any band change.
* **D reverses Balanced and Challenger.** The random strategy gives Challenger > Balanced in
  420 of 439 proxy weeks. A fixture bootstrap gives +0.81 points, 95% interval +0.07 to +1.50.
  The reversal is small but systematic.
* **Foundation ceiling 95% → 90% (A2):** no real outcome reached 90% (maximum 87.1%). The proxy
  has 5.3 outcomes between 90% and 95% per 49 weeks, all 1X2 home wins (mostly Bundesliga).
  Availability and the real-week figures are identical, and the conservative proxy Foundation
  differs by 0.14 points. **Negligible.**
* **Value:** payouts use reference odds. In the real pool, odds × market probability is about
  0.94 in every probability band, so expected gross is about 79–82 per 100 for every strategy:
  risk is priced fairly, minus the margin. Goal Model "value" on underdogs reflects the model's
  optimism about underdogs, not an edge.
* **D-31:** the 75 points for any recovery make recovery probability the main driver of
  average points, and the top-ten table rewards variance. The middle strategy earns the most
  points on average, and neither extreme dominates.

## 7. Investigation 3: Scenario A3 (Challenger 10–40%)

**New 10–20% outcomes:**

| | Real | Proxy |
|---|---|---|
| Added outcomes | 45 (36 in 20–23 Nov: Challenger 128 → 164) | median 22 a week (p10 5, p90 30) |
| Added Challenger fixtures | +3 (57 → 60) and +0 | median 55 → 59 |
| Types | draws 20, away 19, home 6 | away 45%, draws 37%, home 17% |
| Margin (odds × market probability) | 0.944, the same as 20–30% (0.945) | – |
| Quote depth (bookmaker groups, median) | 10 (minimum 6) | – |
| Goal Model minus market | **+5.3 pts (model ÷ market 1.35)**, versus 1.06–1.07 for 20–40% | – |
| D-28 opening | unchanged | unchanged (5.0 / 49 unplayable in A and A3) |

**Completion probabilities** (real week 20–23 Nov; conservative / random / aggressive):

| Scenario | Challenger | All nine | Recovery |
|---|---|---|---|
| A | 15.9 / 8.9 / 4.1 % | 1.44 / 0.22 / 0.03 % | 33.6 / 35.9 / 22.0 % |
| A3 | 15.9 / **7.3 / 1.1 %** | 1.44 / 0.18 / 0.01 % | 33.6 / 34.7 / 19.6 % |

* Foundation and Balanced are unchanged.
* Two Challenger picks near 10% complete about 1.1–1.2% of the time, against 4.1% near 20%.
* The difficulty order holds exactly as in A: 439/439 for random and aggressive, 418/439 for
  conservative.

**Paired leaderboard, A3 minus A** (points per round, ± standard error):

| Strategy | Real pool, simulated (100 championships) | Proxy weeks, actual results (32 championships) |
|---|---|---|
| Aggressive | **−2.87 ± 0.20** (recovery 26.1% → 23.5%) | **−3.94 ± 0.54** (25.4% → 21.9%) |
| Random | −0.61 ± 0.25 | +0.28 ± 0.37 |
| Conservative | +0.29 ± 0.02 | +0.81 ± 0.14 |

* **There is no incentive to chase extreme long shots.** Aggressive players still win about
  44–57% of weeks but score fewer points over time.
* **The cost is volatility and much larger rare payouts:**
  * P(gross ≥ 1,000) for aggressive players rises from about 0.1% to 1.3–1.5%;
  * the largest simulated gross rises from 13.8k to 45.8k;
  * the theoretical maximum rises from about 18k to about 70k (an estimate from odds of
    about 0.94 / p at each band's floor).
* D-31 caps any round at 150 points, so very large payouts cannot dominate a championship.
* Points concentration is essentially unchanged: Gini 0.272 → 0.285; top-10 players' share
  19.0% → 19.5%.

## 8. Calibration limitations (basis for the user guidance)

Predicted versus observed win rates on **actual results** (indicative; proxy weeks):

| Band | Proxy market probability: predicted → observed | Raw Goal Model: predicted → observed |
|---|---|---|
| 10–20% | 16.2% → 21.1% (n 4,956) | **16.7% → 14.0%** (n 520) |
| 20–30% | 25.2% → 27.4% | 25.1% → 25.2% |
| 30–40% | 35.1% → 36.8% | 35.4% → 36.4% |
| 60–90% | 65.7% → 60.0% | 65.0% → 64.1% |

* The raw Goal Model is close to calibrated between 20% and 40%. It **overestimated**
  10–20% outcomes, which matches the real snapshot, where the model rated 10–20% outcomes 35%
  above the market.
* This supports the approved warning ("In our testing, the Goal Model has sometimes
  overestimated the chances of underdogs in this range") and its 10% to below 20% trigger on
  the **market** probability.
* The proxy mapping itself is imperfect at the tails. That is a limitation of the proxy, not
  evidence that real markets misprice underdogs: whether real odds have a favourite–longshot
  bias needs settled real pools.

## 9. Evidence supporting the A3 decision

* Availability equals A's (5.0 / 49 unplayable, all in thin weeks), so the D-28 opening check
  is unaffected.
* The difficulty order is preserved for every strategy, as in A.
* Expected credits are unchanged, and extreme long shots score fewer points under D-31
  (paired, statistically clear).
* The ceiling change (95% → 90%) is measurably negligible and simplifies the message.
* Underdog choice widens (draws and away wins at 10–20%) with good quote depth and unchanged
  margins.
* **Accepted trade-offs:** higher volatility, much larger rare payouts, and a stronger
  Goal-Model-above-market gap in the new band. All three are addressed through communication
  (the guidance and the warning), not rule changes.

## 10. Evidence still needed

* Real weekly pools (D-29b), including settled results: quote coverage in the 10–20% band
  across leagues and fixture types, and the favourite–longshot question on real odds.
* Review of how very large gross values and long-shot buckets are displayed.

## 11. Reproduction

```bash
uv run python tools/research/weekly_challenge_buckets/bucket_study.py all
```

* The run needs the local football store (not committed) and the committed real pool. It
  takes about 5–6 minutes.
* It is deterministic: reruns give identical outputs.
* Scenario figures reported during the review conversation came from earlier scratch scripts
  with different seeds for some runs. The committed outputs match them within simulation
  noise, for example:
  * B unplayable 16.9 versus 16.2;
  * C unplayable 38.5 versus 37.8;
  * D random Challenger > Balanced in 420/439 versus 427/439 weeks.
  * The paired A3 leaderboard figures are identical.
