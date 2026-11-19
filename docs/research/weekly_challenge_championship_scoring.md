# Weekly Challenge — Championship Scoring Research (Phase 6A.2 and 6A.2.1)

> **Phase 6A.2.1 update.** Part II (§9 onward) validates the revised schedule
> (150/135/125/120/115/110/105/100/95/90, 75 for other recoveries) and standard
> competition ranking for ties. It **supersedes** the average-points tie proposal
> in §5 and the 50-point floor discussed in §3–§4. Part I is kept as the record of
> the Phase 6A.2 evidence.

# Part I — Phase 6A.2

Status: **research only**. No production code, schema, Goal Model, odds or UI
was changed.
* Code: `src/diski9/research/championship.py`,
  `scripts/research_championship_scoring.py`.
* Tests: `tests/test_championship_scoring.py`.
* Results: `docs/research/weekly_challenge_championship/results.json`.

**Evidence status:** every championship figure below is **synthetic**. Rounds are
bootstrapped from **one** real weekend pool (17 Nov 2026: 60 fixtures, 420
eligible outcomes, 6 leagues), and scorelines are simulated. Findings are
**provisional** until repeated on 6–8 captured real pools with settled results.

## 1. Question

Under the approved structure (`broad60-432-v1`: Broad-60 market-probability
buckets, 4/3/2 picks, 40/30/20/10 credits) and the approved points rule
(150/135/120/110/100/95/90/85/80/75 for the top ten, 50 outside the top ten,
**only if gross ≥ 100**; otherwise 0), does a 10-round championship reward the
intended behaviour, which is getting your 100 credits back consistently? How does
it compare with the alternatives? What tie rules, edge cases and minimum field
size follow?

## 2. Method

**Rounds.** Each simulated round draws 60 fixtures with replacement from the real
weekend pool (renamed, so a fixture can appear twice as distinct events).
Buckets are assigned by margin-adjusted **market** probability at full
precision.

**One common scoreline per fixture.** Each fixture gets a single simulated
90-minute score, shared by every participant. The score is drawn from
independent Poisson goals, with rates from either:
* **"market truth"** (primary): λ fitted to the market's 1X2 / O/U probabilities
  (`lambda_market` in the pool); or
* **"model truth"** (sensitivity): Goal Model 1.0's λ (`lambda_model`).

All outcomes (1X2, BTTS, O/U 2.5) of a fixture settle from the same score, so
correlations between participants who share fixtures are real, not assumed away.

**Settlement:** D-15 (each accumulator rounded half-up to 0.01), and recovery
when gross ≥ 100.00.

**Behaviours** (diagnostic only, never advice). Every behaviour builds a strict
4/3/2 portfolio on nine distinct fixtures.

| Behaviour | Roster share | Rule |
|---|---:|---|
| random | 30% | uniformly random eligible outcome per slot |
| higher-in-band | 20% | prefers the highest market probability inside each band (with noise) |
| lower-in-band | 20% | prefers the lowest market probability inside each band (with noise) |
| recovery-focused | 15% | best market-estimated recovery probability among 7 candidate portfolios |
| model-vs-market disagreement | 15% | prefers outcomes where Goal Model 1.0 rates higher than the market |

**Per-entry profile** (market probabilities, 300 rounds):

| Behaviour | P(recover) market | P(recover) model | E[gross] | SD | P(nothing) | Mean max payout |
|---|---:|---:|---:|---:|---:|---:|
| random | 0.359 | 0.315 | 79.6 | 188 | 0.640 | 3,693 |
| higher-in-band | 0.338 | 0.317 | 80.1 | 109 | 0.415 | 854 |
| lower-in-band | 0.242 | 0.229 | 79.7 | 319 | 0.758 | 13,285 |
| recovery-focused | 0.416 | 0.358 | 79.6 | 158 | 0.584 | 2,306 |
| disagreement | 0.307 | 0.475 | 79.7 | 219 | 0.693 | 5,384 |

Expected return is about 80 credits for every behaviour at market prices (the
margin), so behaviours differ in **shape**, not in average.

**Championships.** 10 rounds each.
* Participant counts: 5, 10, 25 and 100 (2,000 / 2,000 / 1,000 / 300
  championships), with market truth.
* Model truth: 10 and 25 participants.
* A **realistic participation** variant (25 participants): each player misses any
  round with 20% probability, and 20% of players join at round 4.

**Scoring systems compared:**
* **proposed** (approved);
* **cumulative net** (the earlier baseline);
* **F1-style** 25/18/15/12/10/8/6/4/2/1 (no recovery requirement);
* **percentile** 100 × (N − rank)/(N − 1).

Floors of 25, 50 and 75 were also tested for the proposed rule.

**Seed** 62002; `--quick` runs 10% of the volume. Full run: about 7.5 minutes,
single process.

## 3. Findings

### 3.1 Who wins the championship?

The table shows each behaviour's share of championships divided by its roster
share. 1.00 means it wins in proportion to its numbers; joint wins are split.
Market truth, full participation.

| N | System | random | higher | lower | recovery | disagree |
|---:|---|---:|---:|---:|---:|---:|
| 5 | **proposed** | 0.75 | 0.83 | 0.45 | **2.31** | 1.14 |
| 5 | cumulative net | 0.58 | 0.98 | 1.14 | 1.24 | 1.45 |
| 10 | **proposed** | 0.80 | 0.86 | 0.41 | **2.42** | 0.96 |
| 10 | cumulative net | 0.60 | 0.99 | 1.30 | 1.20 | 1.21 |
| 10 | F1 | 0.60 | 1.31 | 0.92 | 1.35 | 1.13 |
| 10 | percentile | 0.57 | **1.97** | 0.50 | 1.38 | 0.86 |
| 25 | **proposed** | 1.16 | 0.58 | 0.66 | **1.69** | 0.99 |
| 25 | cumulative net | 0.94 | 0.88 | 1.24 | 1.09 | 0.86 |
| 25 | F1 | 0.92 | 0.39 | **1.79** | 0.74 | 1.19 |
| 25 | percentile | 0.84 | **1.86** | 0.36 | 1.17 | 0.86 |
| 100 | **proposed** | 1.04 | 0.17 | **1.94** | 1.02 | 0.75 |
| 100 | cumulative net | 1.38 | 0.50 | 0.88 | 1.11 | 0.95 |
| 100 | F1 | 0.48 | 0.11 | **3.68** | 0.15 | 0.49 |
| 100 | percentile | 1.11 | 1.58 | 0.55 | 0.85 | 0.75 |

* **Up to 25 participants, the proposed rule rewards the intended behaviour.**
  Recovery-focused players win 1.7–2.4× their share. Lower-in-band (the
  lottery-ticket approach) wins 0.4–0.7×.
* **Cumulative net** is close to a lottery: behaviour barely matters, and
  lower-in-band does relatively well. The champion's best single round is
  typically **≥ 95% of their total** (medians 0.96–1.14). One big week decides it.
* **F1-style** (no recovery gate) increasingly rewards variance as the field grows.
  At N = 100, lower-in-band wins 3.7× its share and 37% of players finish on zero.
* **Percentile** rewards higher-in-band (low variance, frequent mid-table finishes
  without recovering). That fits "beat others", not "get your 100 back".
* **At N = 100, the proposed rule also starts to reward variance** (lower-in-band
  1.94×). This is the main unintended incentive (§4).

### 3.2 Consistency and concentration (proposed rule)

| Metric | N=5 | N=10 | N=25 | N=100 | N=25 realistic |
|---|---:|---:|---:|---:|---:|
| Spearman(points, recoveries) | 0.954 | 0.960 | 0.931 | 0.861 | 0.957 |
| Spearman(points, mean portfolio SD) | −0.17 | −0.17 | −0.08 | −0.01 | −0.09 |
| Spearman(points, expected return) | −0.07 | −0.03 | −0.05 | −0.05 | −0.04 |
| Champion's best round / total (median) | 0.21 | 0.20 | 0.20 | 0.25 | 0.22 |
| Players finishing on 0 points | 2.4% | 2.4% | 2.2% | 2.4% | 6.8% |
| Gini of championship points | 0.22 | 0.25 | 0.26 | 0.28 | 0.32 |
| Recovery-focused best finisher above lower-in-band best | 75% | 77% | 64% | 37% | 65% |
| Joint champions | 3.8% | 1.5% | 0.7% | 0.0% | 1.2% |
| Top two equal on points (tie-break needed) | 3.8% | 1.8% | 2.6% | 3.0% | 2.7% |

Under cumulative net, the same Spearman with recoveries is only 0.70–0.80.

**Mean points per round entered** still rank recovery-focused first at every field
size, including N = 100 (25.0 vs 21.6 for lower-in-band). The large-field reversal
is an **extreme-value effect**: the champion is the maximum of many totals, and
high-variance totals reach the maximum more often, even with a lower mean.

### 3.3 Floor sensitivity (50 retained)

Win ratios by floor:

| N | Floor | random | higher | lower | recovery | disagree | Spearman(points, recoveries) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 or 10 | 25 / 50 / 75 | identical | | | | | 0.95 / 0.96 |
| 25 | 25 | 1.20 | 0.54 | 0.72 | 1.56 | 1.01 | 0.914 |
| 25 | 50 | 1.17 | 0.57 | 0.68 | 1.67 | 0.99 | 0.931 |
| 25 | 75 | 1.15 | 0.60 | 0.62 | 1.75 | 0.97 | 0.943 |
| 100 | 25 | 0.67 | 0.06 | **3.03** | 0.50 | 0.69 | 0.640 |
| 100 | 50 | 1.03 | 0.17 | **1.94** | 1.02 | 0.77 | 0.861 |
| 100 | 75 | 1.22 | 0.55 | 0.83 | **1.90** | 0.49 | 0.956 |

* With 10 or fewer entrants, the floor never applies: at most 10 can recover, so
  every recoverer is in the top ten.
* At 25 entrants, about 9 recover on average, so the floor rarely applies and
  matters little.
* At 100 entrants (about 33 recoverers per round) the floor is decisive. 75
  restores the intended incentive; 25 makes it much worse.

### 3.4 Model truth (sensitivity)

If Goal Model 1.0 rather than the market were the true probability, the
disagreement behaviour would dominate under **every** system (about 4.2–4.6× its
share). That is an assumption about who is right, not a property of the
scoring. Under market truth, disagreement is unremarkable (0.75–1.14×). No
scoring rule can neutralise genuinely better information; the proposed rule
still ranks by recoveries (ρ ≈ 0.94–0.96).

### 3.5 Participation

Realistic participation (20% missed rounds, 20% late joiners):
* the conclusions at 25 entrants are unchanged (recovery-focused 1.73×);
* late joiners' mean relative position is 0.64, against 0.49 for full-time players
  (0 = top). That is the expected consequence of "all rounds count, missed rounds
  score 0", which is approved.
* Because points are never negative, **skipping a round can never help**. This
  fixes the old perverse incentive (cumulative net at about −20 credits per
  round).

### 3.6 Round feasibility

| Pool | A strict 4/3/2 portfolio exists | Round opens (≥ 15 fixtures, ≥ 3 leagues, exists) |
|---|---:|---:|
| 10 random real fixtures | 96.5% | 0% (fails the 15 minimum) |
| 15 | 99.75% | 99.75% |
| 20 / 30 | 100% | 100% |
| Real weekend pool | yes (60 fixtures, 6 leagues) | yes |

A test shows that per-bucket outcome counts can all look sufficient while no
portfolio exists (six fixtures, each with outcomes in all three bands). The
exact matching check is therefore required.

## 4. Unintended incentives

1. **Large fields reward variance.** With about 50–100+ entrants, the top-ten
   premium (75–150 against 50) rewards the low-probability, high-payout
   approach. That pulls against the product goal. Mitigations: a 75 floor
   (simulated: it fixes it at N = 100), or top-ten defined as a share of entrants
   (not simulated). This is not urgent for a small launch community, but it is
   an **outstanding decision** (D-31).
2. **Trailing late in a championship.** A player far behind can only catch up
   with top-ten finishes, so may switch to high variance in the last rounds. This
   is inherent to any position-based system, and milder here because the floor
   rewards plain recovery. Not simulated (behaviours are static).
3. **Herding into identical portfolios.** Higher-in-band players often pick the
   same outcomes. Exact gross ties then rise with field size: about 0.03 tie
   groups among recoverers per round at N = 10, 0.14 at N = 25 and **1.18 at
   N = 100**. Average-points sharing (D-26) handles this fairly, but it makes
   championship ties more likely, hence the D-27 hierarchy.
4. **Market vs model.** The disagreement behaviour is rewarded only if the model
   is right. The UI must keep presenting the two estimates neutrally (C-14), with
   no advice.
5. **No incentive to skip** (fixed, see §3.5). There is also no incentive to
   sandbag: points are monotonic in gross for recoverers.

## 5. Tie rules (Phase 6A.2 proposal — weekly rule superseded by §12)

**Weekly (D-26).**
* Identical gross shares the **average** of the values of the positions the group
  occupies, with positions 11+ valued at 50 for recoverers.
* Every recoverer ranks above every non-recoverer, so a tie group is wholly
  recovering or wholly not.

Worked examples (all in tests):
* two tied first: (150 + 135) / 2 = **142.50** each; the next player gets 120;
* three tied first: 135 each;
* tied 2nd–4th behind a winner: (135 + 120 + 110) / 3 = **121.67** (kept exactly as
  365/3);
* four tied 9th–12th: (80 + 75 + 50 + 50) / 4 = **63.75** each, never below the
  50 floor;
* twelve identical recoverers: (sum of the top ten + 2 × 50) / 12 each.

Total points awarded are unchanged by ties. There are no timestamp or ID
tie-breaks.

**Championship (D-27).** Total points → recoveries → qualifying top-ten finishes
→ joint position (joint winners allowed).
* Recoveries come first because they are the product goal.
* Top-ten finishes reward quality among equally consistent players.
* Cumulative credits are deliberately excluded (§3.1).
* In simulation the top two were level on points in 1.8–3.8% of championships.
  After the hierarchy, 0–3.8% still had joint champions (most often at N = 5).

**Edge cases** (all tested):
* exactly 100.00 recovers;
* 99.99 doesn't;
* nobody recovers → everyone scores 0, including the "winner";
* a single participant who recovers gets 150;
* with ≤ 10 entrants every recoverer is in the top ten;
* missed rounds score 0;
* mid-championship joiners keep earlier zeros;
* a round where every pick is void returns exactly 100.00, which is a recovery.

## 6. Minimum participants

* **Simulated:** 5, 10, 25 and 100 entrants. Below 5 was not simulated.
* **At 5 entrants:**
  * the rule still behaves as intended (recovery-focused 2.3×);
  * but joint champions are most frequent (3.8%);
  * every recoverer is top ten, so position matters only among a handful of
    players.
* **Proposal T-04:**
  * a round counts toward a championship only with **at least 5 entrants**;
  * smaller rounds still settle and show a weekly table as a practice round, and
    they don't advance the championship counter.
* **Alternative:** no minimum (simplest; championships can stall otherwise in a
  very small community). This is the owner's choice (D-28).

## 7. Limitations

* **One real pool**, bootstrapped. The leagues, band availability and odds shape
  of other weeks (international breaks, end of season) are not represented.
* **Poisson scorelines with independent goals:** no correlation between home and
  away goals, no draw inflation, no correlation between fixtures.
* **Behaviours are stylised and static.** No adaptation, learning or
  end-of-championship strategy. The roster mix is assumed.
* The "recovery-focused" builder uses market estimates. A real player could do
  better or worse.
* "Truth" is either the market or the model. The real world is neither.
* Large fields use fewer replications (300 at N = 100). Shares there carry
  roughly ±3 percentage points of Monte Carlo error.
* The participation model is simple (independent misses, one late-join round).

## 8. Reproducibility

```bash
uv run python scripts/research_championship_scoring.py
```

```bash
uv run python scripts/research_championship_scoring.py --quick
```

```bash
uv run pytest tests/test_championship_scoring.py -q
```

* The full run writes `results.json` deterministically (seed 62002).
* The `--quick` run is a 10%-volume smoke run.
* The test file has 17 tests: rules, ties, edge cases, standings, and feasibility
  vs exact count.

# Part II — Phase 6A.2.1 refinement

**Evidence status.** Real inputs: the fixtures, market probabilities and frozen
consensus odds of one weekend pool. Simulated: football results (Poisson
scorelines from market-implied rates), participant behaviours, and therefore
every championship outcome. Nothing here is evidence of real participant
performance (D-29).

## 9. Design

* Code: `scripts/research_championship_refinement.py` (reuses the Phase 6A.2
  round generator, scorelines, behaviours and D-15 settlement) and
  `diski9.research.championship` (`position_points`, `competition_ranks`,
  `final_points`, `ChampionshipSeries`).
* Results: `docs/research/weekly_challenge_championship/refinement_results.json`
  (seed 62102; 873 s on 4 processes).
* **Common random numbers.** Each championship's rounds, scorelines and every
  participant's portfolio are generated once from seeds derived from
  (seed, championship, round, participant). The settled gross matrix is then
  scored under all five scenarios. Scenario differences therefore come only from
  the scoring rules, and differences are reported as **paired** per-championship
  differences.
* **Win credit.** Joint champions receive 1/k each, so every championship
  distributes exactly 1 unit of credit; win shares are never inflated by ties.
  *Win ratio* = win share ÷ the behaviour's share of the roster (1.00 =
  proportional).
* **Intervals:** mean ± 95% half-width (1.96 × SD ÷ √championships).

| Scenario | Top-ten schedule | Floor | Weekly ties |
|---|---|---:|---|
| A (previous baseline) | 150/135/120/110/100/95/90/85/80/75 | 50 | average |
| B (floor sensitivity) | 150/135/120/110/100/95/90/85/80/75 | 75 | average |
| C (revised schedule) | 150/135/125/120/115/110/105/100/95/90 | 75 | average |
| **D (preferred)** | 150/135/125/120/115/110/105/100/95/90 | 75 | **competition, full points** |
| E (tie sensitivity) | 150/135/120/110/100/95/90/85/80/75 | 50 | competition, full points |

| Entrants | 5 | 10 | 25 | 50 | 100 | 250 | 500 | 1,000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Championships | 4,000 | 3,000 | 1,500 | 1,000 | 600 | 400 | 400 | 300 |
| Runtime (s, 4 processes) | 29 | 39 | 39 | 48 | 52 | 83 | 163 | 244 |

Roster: random 30%, higher-in-band 20%, lower-in-band 20%, recovery-focused 15%,
disagreement 15% (one of each at N = 5). Full participation, market truth.

## 10. High-variance incentive across field sizes

Win ratios of the two diagnostic extremes (lower-in-band = high variance;
recovery-focused = the product goal):

| N | A lower | A recovery | B lower | B recovery | C lower | C recovery | **D lower** | **D recovery** | E lower | E recovery |
|---:|---|---|---|---|---|---|---|---|---|---|
| 5 | 0.41 ± 0.04 | 1.75 ± 0.07 | 0.41 ± 0.04 | 1.75 ± 0.07 | 0.41 ± 0.04 | 1.76 ± 0.07 | **0.41 ± 0.04** | **1.76 ± 0.07** | 0.41 ± 0.04 | 1.75 ± 0.07 |
| 10 | 0.43 ± 0.05 | 1.84 ± 0.09 | 0.43 ± 0.05 | 1.84 ± 0.09 | 0.39 ± 0.05 | 1.90 ± 0.09 | **0.39 ± 0.05** | **1.90 ± 0.09** | 0.43 ± 0.05 | 1.84 ± 0.09 |
| 25 | 0.82 ± 0.09 | 1.60 ± 0.14 | 0.77 ± 0.09 | 1.70 ± 0.14 | 0.53 ± 0.08 | 1.91 ± 0.14 | **0.53 ± 0.08** | **1.89 ± 0.14** | 0.81 ± 0.09 | 1.59 ± 0.14 |
| 50 | 1.43 ± 0.14 | 1.12 ± 0.15 | 0.94 ± 0.12 | 1.64 ± 0.17 | 0.85 ± 0.12 | 1.57 ± 0.17 | **0.85 ± 0.12** | **1.56 ± 0.17** | 1.40 ± 0.14 | 1.10 ± 0.15 |
| 100 | 1.86 ± 0.19 | 0.96 ± 0.19 | 0.93 ± 0.16 | 1.70 ± 0.23 | 1.04 ± 0.16 | 1.61 ± 0.23 | **1.04 ± 0.16** | **1.59 ± 0.23** | 1.85 ± 0.19 | 0.92 ± 0.18 |
| 250 | 1.19 ± 0.21 | 1.50 ± 0.27 | 0.35 ± 0.12 | 2.59 ± 0.31 | 0.46 ± 0.14 | 2.46 ± 0.31 | **0.46 ± 0.14** | **2.46 ± 0.31** | 1.23 ± 0.21 | 1.46 ± 0.27 |
| 500 | 0.65 ± 0.17 | 1.91 ± 0.29 | 0.18 ± 0.09 | 2.90 ± 0.31 | 0.23 ± 0.10 | 2.78 ± 0.31 | **0.23 ± 0.10** | **2.78 ± 0.31** | 0.76 ± 0.18 | 1.85 ± 0.29 |
| 1,000 | 0.30 ± 0.13 | 2.70 ± 0.36 | 0.18 ± 0.11 | 3.00 ± 0.34 | 0.20 ± 0.11 | 2.98 ± 0.34 | **0.23 ± 0.12** | **2.97 ± 0.34** | 0.30 ± 0.13 | 2.69 ± 0.36 |

**Paired difference D − A in win ratio** (CRN; negative = less reward):

| N | 10 | 25 | 50 | 100 | 250 | 500 | 1,000 |
|---|---|---|---|---|---|---|---|
| lower-in-band | −0.04 ± 0.02 | −0.29 ± 0.06 | −0.58 ± 0.10 | −0.82 ± 0.15 | −0.73 ± 0.18 | −0.42 ± 0.14 | −0.07 ± 0.11 |
| recovery-focused | +0.05 ± 0.02 | +0.28 ± 0.08 | +0.44 ± 0.12 | +0.63 ± 0.19 | +0.96 ± 0.27 | +0.87 ± 0.26 | +0.27 ± 0.30 |

At N = 5 the scenarios are almost identical (paired differences < 0.01).

**Findings.**
1. Under the old baseline (A) the variance incentive is real and peaks at
   50–100 entrants (lower-in-band 1.43–1.86×; recovery-focused at or below
   proportional). It fades again at 250+, where ~80+ entrants recover each week,
   top-ten finishes become rare for everyone and the floor dominates.
2. **The preferred configuration (D) removes it at every field size tested.**
   Lower-in-band never exceeds proportional (worst 1.04 ± 0.16 at N = 100,
   statistically indistinguishable from 1.00), and recovery-focused is favoured
   everywhere (1.56–2.97×). Paired reductions are significant from 10 to 500
   entrants. At 1,000 both A and D already favour recovery and do not differ
   significantly.
3. **The cause is mainly the floor.** B (75 floor, old schedule) achieves most
   of the effect at 50+ entrants. The compressed top ten (C vs B) adds a further
   improvement at 10–25 entrants (lower 0.77 → 0.53 at N = 25), where most
   recoverers are in the top ten and the floor barely applies.
4. Under D the variance of a participant's portfolios is **negatively**
   correlated with championship points at every N (Spearman −0.07 to −0.24;
   under A it is +0.04 at N = 50). Expected return is uncorrelated (≈ −0.04),
   as expected at market prices.

## 11. Consistency and concentration (A vs D)

| N | ρ(points, recoveries) A → D | Best round ÷ champion total A → D | Zero-point finishers | Gini A → D | Median total A → D | P90 total A → D |
|---:|---|---|---:|---|---|---|
| 5 | 0.954 → 0.953 | 0.21 → 0.21 | 2.4% | 0.22 → 0.22 | 435 → 435 | 720 → 720 |
| 10 | 0.961 → 0.965 | 0.20 → 0.19 | 2.4% | 0.25 → 0.25 | 435 → 450 | 640 → 660 |
| 25 | 0.933 → 0.963 | 0.20 → 0.19 | 2.4% | 0.26 → 0.26 | 348 → 380 | 575 → 630 |
| 50 | 0.853 → 0.936 | 0.23 → 0.20 | 2.4% | 0.28 → 0.26 | 270 → 330 | 445 → 520 |
| 100 | 0.862 → 0.948 | 0.25 → 0.20 | 2.3% | 0.28 → 0.27 | 200 → 300 | 361 → 465 |
| 250 | 0.922 → 0.974 | 0.27 → 0.18 | 2.4% | 0.28 → 0.27 | 191 → 253 | 300 → 450 |
| 500 | 0.957 → 0.986 | 0.25 → 0.16 | 2.3% | 0.27 → 0.26 | 150 → 225 | 300 → 420 |
| 1,000 | 0.978 → 0.993 | 0.23 → 0.14 | 2.3% | 0.26 → 0.26 | 150 → 225 | 290 → 390 |

The share of entrants finishing with zero points (never recovering in ten rounds)
is a property of the portfolios, not the scoring (≈ 2.3–2.4% throughout).

## 12. Weekly ties and the full-points rule

| N | Rounds with a tie among recoverers | Tie groups per round | First-place tie | Tie crossing the top-ten boundary | Entrants receiving top-ten points per round (D) | Rounds with > 10 top-ten recipients (D) |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 0.1% | 0.00 | 0.06% | 0% | 1.7 | 0% |
| 10 | 3.1% | 0.03 | 1.1% | 0% | 3.3 | 0% |
| 25 | 13% | 0.14 | 1.1% | 0.5% | 7.8 | 0.5% |
| 50 | 34% | 0.43 | 1.1% | 4.2% | 10.0 | 4.2% |
| 100 | 65% | 1.21 | 1.3% | 5.8% | 10.1 | 5.8% |
| 250 | 96% | 4.58 | 0.9% | 6.0% | 10.1 | 6.0% |
| 500 | 100% | 11.9 | 0.5% | 11.2% | 10.2 | 11.2% |
| 1,000 | 100% | 29.0 | 0.2% | 11.4% | 10.2 | 11.4% |

**Effect of the tie rule on incentives: negligible.** E vs A and D vs C differ
by less than the Monte Carlo error at every N (paired E − A for lower-in-band:
−0.03 to +0.04 up to 250 entrants; +0.11 ± 0.07 at 500, borderline). Ties near
the top are too rare to steer a championship; most ties are among outside-top-ten
recoverers, who receive 75 under either rule.

**Joint champions** rise in very large fields under the 75 floor:

| N | 5 | 10 | 25 | 50 | 100 | 250 | 500 | 1,000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 4.4% | 1.4% | 0.8% | 0.3% | 0.8% | 1.3% | 5.8% | 10.3% |
| B | 4.4% | 1.4% | 0.8% | 0.0% | 0.7% | 5.8% | 20.8% | 29.0% |
| C | 3.3% | 1.5% | 1.1% | 0.5% | 0.5% | 5.0% | 19.0% | 27.7% |
| D | 3.3% | 1.5% | 1.4% | 0.7% | 0.8% | 4.8% | 19.0% | 27.3% |

The driver is the floor (B ≈ C ≈ D), not the tie rule (D ≈ C, E ≈ A). With
hundreds of entrants, the leaders are typically players with 8–10 recoveries
and a similar count of top-ten finishes, so the D-27 tie-breakers are also level.
Mean champions per championship under D: 1.07 at 250, 1.30 at 500, 1.67 at
1,000. Win credit is split, so this does not distort the incentive results. It
is a presentation cost in very large communities, not an incentive problem.

## 13. Popular and duplicated portfolios

A separate roster adds **herd** players (20%: every herd player enters the round's
single most popular portfolio, the highest-probability outcome in every slot,
so they are exact duplicates) and **correlated** players (10%: the same favourites
with tiny noise, heavily overlapping). Same seeds across scenarios.

| N (championships) | Scenario | herd win ratio | correlated | higher-in-band | recovery-focused | herd points/round | higher-in-band points/round |
|---|---|---|---|---|---|---:|---:|
| 25 (2,000) | A | 0.02 ± 0.01 | 0.41 ± 0.10 | 0.89 ± 0.10 | 2.14 ± 0.16 | 28.3 | 34.7 |
| 25 | D | 0.14 ± 0.04 | 0.58 ± 0.12 | 0.92 ± 0.10 | 2.36 ± 0.16 | 38.3 | 38.7 |
| 25 | E | 0.12 ± 0.03 | 0.46 ± 0.10 | 0.87 ± 0.09 | 2.08 ± 0.16 | 33.9 | 34.9 |
| 100 (800) | A | 0.00 | 0.06 ± 0.06 | 0.36 ± 0.11 | 1.41 ± 0.24 | 17.5 | 21.0 |
| 100 | D | 0.01 ± 0.02 | 0.20 ± 0.10 | 0.54 ± 0.13 | 2.38 ± 0.29 | 27.1 | 28.5 |
| 500 (200) | A | 0.00 | 0.31 ± 0.23 | 0.83 ± 0.31 | 1.67 ± 0.50 | 17.5 | 17.8 |
| 500 | D | 0.00 | 0.55 ± 0.31 | 0.54 ± 0.25 | 3.22 ± 0.60 | 26.3 | 26.1 |

* **Average-points ties penalise duplication:** herd players score clearly less
  per round than the similar, non-identical higher-in-band players (28.3 vs 34.7
  at N = 25), only because they share their points.
* **Full-points ties are duplication-neutral:** a duplicated portfolio earns
  exactly what the same portfolio would earn if entered once (38.3 vs 38.7). It
  is not rewarded *more* than an equivalent unique portfolio. This is the
  intended "equal recognition for identical results".
* Duplicated portfolios almost never win a championship under any rule
  (≤ 0.14×), because a herd shares one outcome stream and splits any joint win.
  Recovery-focused remains the most rewarded behaviour with herds present.
* Side effect: a herd pushes everyone below it down by its size. This is the same
  as if that many different players had beaten them, so it isn't a distortion.

## 14. Late-championship behaviour (unilateral switch)

After round 7, up to three randomly chosen **trailing** participants (outside the
top three under that scenario's standings) each, separately, switch to
lower-in-band for rounds 8–10. Everyone else's portfolios and all scorelines are
unchanged (CRN), so the paired difference isolates the effect of switching.

| N | Cases | A: win prob stay → switch (gain) | D: win prob stay → switch (gain) | D: top-three stay → switch |
|---:|---:|---|---|---|
| 10 | 9,000 | 1.50% → 1.08% (−0.42 ± 0.30 pp) | 1.64% → 1.02% (−0.63 ± 0.30 pp) | 11.5% → 8.6% |
| 25 | 4,500 | 1.04% → 0.82% (−0.22 ± 0.38) | 1.02% → 0.72% (−0.30 ± 0.36) | 5.5% → 4.2% |
| 50 | 3,000 | 0.57% → 0.83% (+0.27 ± 0.40) | 0.65% → 0.83% (+0.18 ± 0.40) | 3.0% → 2.9% |
| 100 | 1,800 | 0.06% → 0.83% (**+0.78 ± 0.43**) | 0.39% → 0.44% (+0.06 ± 0.39) | 1.2% → 1.2% |
| 250 | 1,200 | 0.08% → 0.17% (+0.08 ± 0.28) | 0.50% → 0.08% (−0.42 ± 0.43) | 1.4% → 0.6% |
| 500 | 1,200 | 0.08% → 0.33% (+0.25 ± 0.37) | 0.25% → 0.00% (−0.25 ± 0.28) | 0.7% → 0.0% |
| 1,000 | 900 | 0.11% → 0.00% (−0.11 ± 0.22) | 0.06% → 0.00% (−0.06 ± 0.11) | 0.6% → 0.3% |

Under A, a late switch to high variance paid off at 100 entrants (a significant
gain, from a very low base). **Under D no field size shows a significant gain**,
and switching usually costs final position (mean relative position worsens by
0.02–0.04 of the field). Static behaviours elsewhere are a simplification, but
the main adaptive incentive tested here does not appear under D.

## 15. Recommendation

**Recommend approval of scenario D** (`points-150-75-v2`: 150/135/125/120/115/
110/105/100/95/90, 75 for any other recovery, 0 without recovery; standard
competition ranking with full points for ties).

Against the evaluation criteria:

| Criterion | Evidence under D |
|---|---|
| Rewards capital recovery meaningfully | ρ(points, recoveries) 0.94–0.99; a recovery is worth half the maximum |
| Supports consistency over ten rounds | Recovery-focused 1.56–2.97× at every N |
| Limits exceptional payouts | Champion's best round 14–21% of their total (A: 20–27%) |
| Avoids favouring high variance | Lower-in-band ≤ 1.04× at every N; variance negatively correlated with points; no late-switch gain |
| Understandable | One table, one floor, everyone tied gets the same points |
| Scales with participants | Behaviour stable from 5 to 1,000; A's 50–100 peak removed |
| Treats identical results equally | Full points; duplication-neutral (§13) |

**Residual effects (not incentive problems):**
1. **Joint champions in very large fields** (19% at 500, 27% at 1,000; driven by
   the floor). Allowed under D-27.
2. At 50–100 entrants lower-in-band is roughly proportional (0.85–1.04×) rather
   than penalised. It is not favoured.

**Optional simple adjustments, not adopted** (only if you want to act on the
residuals):
1. **Add "most weekly first places" as a final championship tie-breaker** before
   declaring joint champions. It is simple, but it reintroduces a reward for
   exceptional weeks at the very end of the hierarchy. It was not simulated.
2. **None for incentives.** The evidence does not call for a further schedule
   change, percentile scoring or field-size-dependent rules.

## 16. Operational edge cases (D-28, D-30)

| Situation | Treatment |
|---|---|
| Fewer than 5 valid entries at the deadline | Practice round: settles, results and weekly table shown, no points, no tie-breaker effect, counter unchanged, kept separately |
| Participant resubmits several times | Counts once (the final locked submission) |
| Entry withdrawn or incomplete at the deadline | Not a valid entry (incomplete portfolios cannot be submitted) |
| Valid entries ≥ 5 at the deadline, later all of one entrant's picks void | Still a championship round; that entrant settles at exactly 100.00, a recovery (approved inclusive rule) |
| Whole round cancelled or invalidated after the deadline | Void round: stakes returned, no points, counter unchanged (T-08). Without this rule an all-void round would give every entrant 100.00, a shared rank 1 and 150 points |
| Most, but not all, fixtures void | Settles normally under `settle/v1`; a possible mass-void threshold is outstanding (D-32) |
| End of season / international break / no feasible pool | Championship pauses with points preserved; resumes with the next championship round; never shortened (D-30) |
| Correction after settlement | Whole round re-scored; designation unchanged (fixed at the deadline) |

## 17. Limitations (Part II)

* Same single real pool and Poisson scorelines as Part I. Market-truth only; the
  model-truth sensitivity of Part I is not repeated.
* Behaviours are stylised; the herd model is extreme (exact duplicates of one
  portfolio) to bound the effect.
* The late-switch test is unilateral and covers one switch pattern (to
  lower-in-band, rounds 8–10). Coordinated or partial switches were not tested.
* The large-field intervals are wide (±0.3 on recovery-focused ratios at 500–1,000
  entrants). Small differences there should not be read as effects.
* Full participation only in Part II; Part I's realistic-participation result
  (late joiners rank lower; skipping never helps) still applies, because points
  remain non-negative.

## 18. Reproducibility (Part II)

```bash
uv run python scripts/research_championship_refinement.py
```

```bash
uv run python scripts/research_championship_refinement.py --quick
```

```bash
uv run pytest tests/test_championship_refinement.py tests/test_championship_scoring.py -q
```

* Full run: about 15 minutes on 4 processes (`--workers` to change); it writes
  `refinement_results.json`.
* `--quick` runs 10% of the volume and writes `refinement_results_quick.json`.
* Results are deterministic for a given seed and do not depend on the worker
  count: seeds are derived per championship, round and participant.
