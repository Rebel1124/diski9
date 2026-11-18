# Weekly Challenge — Championship Scoring Research (Phase 6A.2)

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

## 5. Tie rules (proposed)

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
