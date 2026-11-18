# Weekly Challenge engines (Phase 6A.3)

**Status:** production-ready pure-Python engines on branch
`feature/risk-structured-challenge-engine`. They aren't yet used by the Dash app;
the UI, rounds, submissions and settlement come in later phases.

* **Specification:** `docs/product/weekly_challenge_prd.md`, the design in
  `docs/architecture/weekly_challenge_design.md`, and the decisions in
  `docs/product/weekly_challenge_decisions.md` (D-26 to D-31).
* **Research:** `docs/research/weekly_challenge_risk_structure.md` and
  `docs/research/weekly_challenge_championship_scoring.md`.

## 1. Module architecture

| Module | Role | Imports |
|---|---|---|
| `diski9.challenge.config` | `ChallengeConfig`: versioned, immutable, validated portfolio configuration; `BROAD60_432_V1`; registry | stdlib, `api_football.markets` (enums only) |
| `diski9.challenge.structured` | Round-sheet outcome contract, eligibility, classification, partial progress, exact feasibility, round-opening checks, generalised exact evaluation, payout distribution | stdlib, `config`, `portfolio` (rounding only) |
| `diski9.challenge.scoring` | `ScoringConfig` (`points-150-75-v2`), round classification, weekly ranking and points, championship aggregation | stdlib, `config` (`ConfigError`) |
| `diski9.challenge.portfolio` | Phase 6A legacy 3/3/3 engine (280 partitions, frontier, recommendation): research and regression baseline, **unchanged** | stdlib |

The modules have no Dash, database, network or API dependency (a test enforces
the import list). Scoring is independent of portfolio evaluation: it consumes
settled gross payouts only.

## 2. Configuration and versioning

### Portfolio configuration: `broad60-432-v1`

| Bucket | Name | Market probability band | Picks | Credits |
|---|---|---|---:|---:|
| A | Foundation | [0.60, 0.95] | 4 | 40 |
| B | Balanced | [0.40, 0.60) | 3 | 30 |
| C | Challenger | [0.20, 0.40) | 2 | 20 |
| NINE | The Diski 9 | all nine picks | 9 | 10 |

`ChallengeConfig` validates on construction:
* non-overlapping bands, with explicit inclusive and exclusive boundaries;
* positive integer bucket sizes and credits;
* sizes summing to exactly nine;
* credits plus the nine-fold totalling exactly 100;
* a recovery target of 100.00;
* market classification, from the supported sources (market, model);
* known markets.

It also carries the snapshot odds requirements (≥ 3 independent bookmaker
groups, quotes verified within 24 hours, equal to the existing
`ConsensusRules` defaults) and the opening thresholds (≥ 15 fixtures, ≥ 3
leagues).

**Versioning rules:**
* Configurations are frozen.
* `get_config(version)` is the only way production code obtains one, so
  participants can never supply or change it.
* `register_config` refuses a second, different configuration under an existing
  version; `fingerprint()` is a SHA-256 of the canonical content.
* Future approved changes become a new version with no engine change: bands,
  sizes, stakes and even the number of buckets are data.

### Scoring configuration: `points-150-75-v2`

The scoring configuration is versioned separately (`ScoringConfig`,
`get_scoring_config`):
* ranks 1–10 earn 150/135/125/120/115/110/105/100/95/90;
* any other recovery earns 75;
* without recovery, 0;
* recovery target 100.00;
* maximum 150 per round and 1,500 per championship;
* 10 rounds per championship;
* 5 valid entries for a competitive round.

Validation enforces non-increasing integer points, the recovery award at or below
the tenth-place award, and the maximum.

## 3. Probability sources and odds

`ChallengeOutcome` (built by `make_outcome`) carries three numbers that are never
mixed:

| Field | Used for |
|---|---|
| `market_probability` | eligibility and bucket assignment; market-based risk estimate |
| `model_probability` | model-based risk estimate only (may be `None` if Goal Model 1.0 has no forecast; a model evaluation then raises) |
| `reference_odds` | payouts only (exact `Decimal`, within the existing 1.01–1000 sanity bounds; floats are refused) |

Also carried: `fixture_id`, `market` / `outcome` (validated against the API-Football
market map), `league_id`, `bookmaker_groups` and `latest_observation_at`
(timezone-aware).

**The snapshot boundary:** `assess_outcome(outcome, snapshot_at)` applies the odds
requirements against the metadata on the outcome. Market completeness,
bookmaker independence and pre-kickoff rules stay in the existing consensus layer
(`challenge_consensus`), which builds the round sheet; the engine performs no I/O.

## 4. Bucket assignment

`config.classify(p)` and `classify_probability(p)` compare the full-precision
float with float bounds (the doubles nearest 0.20, 0.40, 0.60 and 0.95):

| Probability | Bucket |
|---|---|
| 0.95 | A (inclusive top) |
| next double above 0.95 | ineligible |
| 0.60 | A |
| next double below 0.60 | B |
| 0.40 | B |
| 0.20 | C |
| next double below 0.20 | ineligible |

A value displayed as "60.0%" (for example 0.59996) is Balanced. Buckets are always
**derived**; callers never assign them.

## 5. Partial portfolio validation

`portfolio_progress(selections, snapshot_at, config, pool=None)` returns
`PortfolioProgress`:
* `selected`, `required` and `remaining` per bucket;
* `total_selected` and `total_required`;
* `is_complete` and `is_valid`;
* `can_complete` (when a round sheet is supplied);
* structured `issues`.

Each issue is a `ValidationIssue(code, message, fixture_id, selection, bucket)`
whose code is an `IssueCode`:

| Code | Meaning |
|---|---|
| `duplicate_fixture` / `duplicate_outcome` | more than one pick on a fixture / the same outcome twice |
| `bucket_over_capacity` | more picks in a bucket than allowed |
| `probability_below_range` / `probability_above_range` | market probability below 20% / above 95% |
| `odds_too_few_groups` / `odds_stale` / `odds_missing_timestamp` | fails the snapshot odds rules |
| `unsupported_market`, `not_in_pool` | market not offered / pick not on (or different from) the round sheet |
| `incomplete` | buckets still to fill (the only non-blocking issue) |
| `cannot_complete` | valid so far, but the remaining fixtures cannot fill the remaining slots |

`validate_portfolio(...)` returns a `StructuredPortfolio` only when complete and
valid; otherwise it raises `PortfolioValidationError` with every issue.
`evaluate_portfolio` accepts only a `StructuredPortfolio`, so incomplete or
invalid portfolios can't reach the evaluation pathway.

## 6. Exact feasibility

`portfolio_feasible(pool, snapshot_at, config, fixed=())` and the completability
check use exact bipartite matching (augmenting paths):
* required slots (4 A, 3 B, 2 C, minus those already filled) on one side;
* unused fixtures with an eligible outcome in the slot's band on the other.

A fixture holding outcomes in several bands fills at most one slot. Counting
outcomes per bucket is not enough (a test shows six fixtures each with A, B and C
outcomes cannot host a portfolio). Results are cross-checked against an
exhaustive count on random real sub-pools.

`round_opening_report(pool, snapshot_at)` returns:
* eligible outcomes, in total and per bucket;
* eligible fixtures and leagues;
* the three D-28 checks (≥ 15 fixtures, ≥ 3 leagues, feasibility);
* `opens`.

Nothing recommends outcomes or portfolios.

## 7. Mathematics, precision and the payout distribution

`evaluate_groups(groups, stakes, nine_stake, ...)` is the configuration-free
evaluator. `evaluate_portfolio(portfolio, source)` and
`evaluate_market_and_model(portfolio)` wrap it.

**Assumptions:**
* fixtures are independent, and the buckets are disjoint;
* results are conditional on the supplied probabilities, which are estimates;
* market and model estimates are separate objects with identical payouts.

**Mathematics:**
* a bucket wins with P = ∏ of its legs' probabilities;
* combined odds are the exact `Decimal` product of its legs' odds;
* 2^k joint states (8 for three buckets);
* the nine-fold pays only in the all-win state, never as an independent event.

**Precision (D-15):**
* each accumulator's payout is rounded half-up to 0.01 credit;
* a state's gross is the sum of its rounded payouts;
* recovery is gross ≥ `Decimal("100.00")`, inclusive;
* probabilities are full-precision floats.

**Outputs:**
* per accumulator: combined odds, win probability, payout and "recovers alone";
* the states;
* `p_recover`, `p_profit`, `p_zero`;
* expected gross and net, SD;
* `max_gross`;
* `p_all_win`.

**Payout distribution:**
* `payout_distribution` aggregates equal-payout states by exact `Decimal`
  equality;
* `probability_at_least(x)` returns exactly 1.0 at or below the smallest gross
  (0.00), includes payouts equal to the threshold, and at 100 credits is the
  reported recovery probability (same function, same state order);
* probabilities sum to 1 within 1e-12;
* floats and negative thresholds are refused.

## 8. Weekly ranking and points

`score_round(RoundResult, config)` returns `RoundScore` with a `WeeklyScore` per
entry: rank, points, `recovered`, `qualifying_top10`, `counts_for_championship`,
basis, `display_order` and a note.

**Ranking:**
* Rank = 1 + the number of championship-eligible entrants with strictly greater
  settled gross: standard competition ranking.
* Ties share the rank and each receives the full points; following ranks are
  skipped. More than ten entrants can receive top-ten points.
* Gross must be settled to exactly 0.01 credit.
* Participant identifiers only fix the display order among equal ranks.

**Points:**
* recovery (gross ≥ 100.00) is required for any points;
* points are integers and non-additive.

Example (from `scripts/example_weekly_challenge.py`):

| Rank | Name | Gross | Points |
|---:|---|---:|---:|
| 1 | Thandi | 412.80 | 150 |
| 2 | Lee | 231.00 | 135 |
| 2 | Sipho | 231.00 | 135 |
| 4 | Ana | 190.40 | 120 |
| 5 | Nomsa | 100.00 | 115 |
| 6 | Ben | 88.20 | 0 |
| 7 | Zola | 0.00 | 0 |

## 9. Championship aggregation and ties

`aggregate_championship(championship_id, rounds, config)` recomputes everything
from settled inputs:
* points;
* rounds entered;
* recoveries;
* qualifying top-ten finishes (rank ≤ 10, recovered, competitive round).

**Standings:** points → recoveries → qualifying top-ten finishes → shared rank
(standard competition ranking). Joint champions are allowed. Neither weekly wins
nor cumulative credits are tie-breakers.

**Validation:**
* duplicate rounds, rounds of another championship and more than ten competitive
  rounds are rejected;
* practice and void rounds may be passed in and are listed in
  `ignored_round_ids`.

**Status:**
* `is_complete` requires ten competitive rounds, all final;
* `champions` is empty until then (`leaders` shows the current rank 1);
* `provisional` is true if any competitive round is provisional.

**Corrections:** a corrected settlement is handled by recomputing; the result is
order-independent and reproducible.

## 10. Round and entry contracts

| Input | Contract |
|---|---|
| `RoundResult.classification` | `competitive` (≥ 5 entries, championship ID required), `practice` (< 5), `void` (cancelled or invalidated after the deadline). Inconsistent labels are rejected. `classify_round(valid_entries, cancelled)` gives the approved designation at the deadline |
| `RoundResult.entries` | The valid entries at the deadline, one per participant (resubmissions collapsed to the final version). Duplicates are rejected |
| `RoundResult.final` | `False` = provisional settlement; the championship is marked provisional |
| `EntryResult.gross` | Settled aggregate gross, a `Decimal` at 0.01. `None` = unsettled, which is rejected (settle provisionally first) |
| `EntryResult.championship_eligible` | `False`, with a reason, removes the entry from ranking and points without changing the round's classification |
| `EntryResult.basis` | `settled`, or `all_selections_void` (stakes returned; gross must be exactly 100.00) |

**Effects:**

| Round type | Leaderboard | Points | Counter |
|---|---|---|---|
| Practice | ranked | 0 | doesn't advance |
| Void | unranked, stakes returned | 0 | doesn't advance |

**All-void entries (outstanding decision D-33):**
* Under the literal approved rule ("exactly 100.00 recovers") an entry whose nine
  picks were all void would recover and earn points at its rank.
* `ScoringConfig.all_void_policy` makes this explicit:
  * `score_as_settled` (the default, as approved);
  * `no_points` (ranked, so others' ranks are unchanged, but no points, recovery
    or top-ten credit).
* Changing the policy needs an owner decision and a new scoring version.

**Partial voids (D-32):** they settle normally upstream; the engine just receives
the settled gross. There is no majority-void threshold.

## 11. Legacy compatibility

* `diski9.challenge.portfolio` is unchanged, with all its Phase 6A tests (280
  partitions, frontier, recommendation, Phase 5B regression).
* The revised production API exposes no partitions, frontier or recommendation;
  a test checks the `structured` module defines none.
* **Equivalence:** `evaluate_groups` with three groups of three, stakes
  30/30/30/10 and `nine_fold_legs` in selection order reproduces
  `portfolio.evaluate_partition` **bit for bit** on all 17 Phase 5B slates × 280
  partitions, in both precisions:
  * states, bucket and nine-fold values;
  * recovery, profit and zero probabilities;
  * expected gross;
  * maximum.

## 12. Future Dash integration

* **Builder callbacks:** call `portfolio_progress(selections, snapshot_at,
  pool=round_sheet)` on each change.
  * Render the tracker from `selected` and `required`.
  * Map `issues[].code` to copy.
  * Disable "Review" until `is_complete`.
  * Warn on `cannot_complete`.
* **Review:** `evaluate_market_and_model(validate_portfolio(...))` gives two
  `PortfolioEvaluation`s; feed `distribution()` to "Your Payout Probability".
* **Leaderboards:** `score_round` for the weekly table, and
  `aggregate_championship` over the stored round results for the championship
  table.
* **Errors:** every error is a typed exception with a readable message:
  * `ConfigError`;
  * `ChallengeInputError`;
  * `PortfolioValidationError` (with `.issues`);
  * `ScoringInputError`.

## 13. Worked example and benchmarks

Run the example; it prints the portfolio, both estimates, the distribution, a
scored week with a tie and a ten-round championship with joint champions:

```bash
uv run python scripts/example_weekly_challenge.py
```

Benchmarks: run the command below (real 60-fixture pool, single process, median
of repeats):

```bash
uv run python scripts/benchmark_challenge_engine.py
```

| Operation | Median |
|---|---:|
| Evaluate a portfolio, market + model | 0.08 ms |
| Payout distribution | 0.07 ms |
| Validate a complete portfolio against the sheet | 0.6 ms |
| Partial progress + completability (420 outcomes) | 0.6 ms |
| Full-pool feasibility / round-opening report | 0.6 ms |
| Weekly scoring, 25 / 100 / 500 / 1,000 entrants | 0.09 / 0.35 / 1.8 / 3.8 ms |
| Ten-round championship, 25 / 100 / 500 / 1,000 entrants | 1.2 / 4.5 / 24 / 49 ms |

## 14. Limitations

* Independence across fixtures is an assumption.
* The championship incentive evidence is simulated, using one real pool (D-29).

## Appendix — Legacy 3/3/3 engine (Phase 6A, unchanged)

**Module:** `src/diski9/challenge/portfolio.py`.
* Production code, pure and deterministic.
* Standard library only: no numpy, database, network or API access.
* Specification: Phase 5C documents on branch `design/weekly-challenge-phase-5c`.
* Mathematics: Phase 5B, on branch `research/weekly-challenge-optimisation`.
* Not yet used by the Dash app. The UI, rounds, submissions and settlement are
  later phases.

### What it does

| Function | Purpose |
|---|---|
| `make_selection`, `validate_selections` | Validates nine selections: unique IDs, nine distinct fixtures, probability in [0, 1], finite odds ≥ 1.00. Raises `PortfolioInputError` with an actionable message. |
| `partitions`, `partition_id`, `parse_partition_id`, `validate_partition` | The 280 canonical partitions and their IDs (`012\|345\|678` … `078\|156\|234`), identical to Phase 5B. |
| `evaluate_partition(selections, partition, precision)` | One grouping: buckets A, B and C plus the nine-fold (combined odds, win probability, payout, whether a bucket recovers 100 on its own), the eight states, and the summary probabilities and returns (listed under "Fixed allocation"). |
| `evaluate_all(selections, precision)` | All 280 groupings, efficiency flags, the recommended grouping (`PortfolioSet`). |
| `payout_distribution(result)` | Distinct gross payouts, each with P(exactly) and P(at least), and the states behind it. Feeds "Your Payout Probability". |
| `probability_at_least(result, x)`, `probability_exactly(result, x)` | Point queries, for example the 100-credit threshold. |

### Fixed allocation

The allocation is **30 / 30 / 30 / 10 credits**, 100 in total
(`ALLOCATION_VERSION = "30-30-30-10/v1"`). It is a module constant, not a
parameter: stakes cannot be adjusted.

Each evaluated grouping reports:

* **Recovery:** P(gross ≥ 100.00).
* **Profit:** P(gross > 100.00).
* **Zero payout:** P(gross = 0), meaning no bucket wins.
* **Returns:** expected gross, expected net (gross − 100), and SD (internal only).
* **Maximum gross:** the payout when all nine win, which includes the nine-fold.

### Mathematics

* **Probabilities:**
  * A bucket wins with P_j = ∏ of its three probabilities (independent fixtures).
  * The eight states (a, b, c) have probability ∏ P_j or (1 − P_j).
  * The nine-fold payout is added only in state (1, 1, 1).
  * There is no simulation.
* **Number types:** combined odds are exact `Decimal` products; probabilities are
  full-precision floats and are never rounded.
* **Efficiency:** Pareto efficiency on (recovery ↑, expected gross ↑).
  * Coordinates are snapped first: probability to 1e-12, credits to 5e-6 (Phase
    5B's 1e-6 at 20 credits, scaled by 5).
  * Points with identical coordinates never dominate each other.
  * An O(n log n) sweep is used, verified against brute force in the tests.
* **Recommendation:**
  * the efficient grouping with the highest recovery;
  * then the highest expected gross;
  * then the lowest canonical ID.
  * It is always efficient.

### Payout precision (D-15)

Two payout conventions:

* `Precision.SETTLEMENT` (default, the product convention):
  * each accumulator's payout = stake × exact combined odds, rounded half-up to
    0.01 credit;
  * a state's gross = the sum of its winning accumulators' rounded payouts;
  * recovery compares that gross with `Decimal("100.00")` exactly.
  * Example: R1's maximum is 116.58 + 176.83 + 100.70 + 768.81 = 1,162.92.
    Rounding the unrounded total would give 1,162.91.
* `Precision.EXACT` (verification only): unrounded payouts, the Phase 5B
  convention.

**Agreement guarantee:** `payout_distribution` computes each "at least" value as a
sum over the same states, in the same order, as `p_recover`. So the
distribution's value at 100 credits is **bitwise identical** to the frontier's
recovery probability.

### Verification against Phase 5B

**Fixture:** `tests/fixtures/challenge/phase5b_regression.json`.
* 17 slates: 13 synthetic, plus 4 real from the 17 Nov 2026 research snapshot.
* Each has all 280 partitions' recovery, expected return, SD, maximum, zero-payout
  probability, efficiency and recommendation.
* Generated by the research module at commit `6f5a2f9`, using 6/6/6/2 credits and
  a 20-credit target.

**`EXACT` convention** (the 100-credit engine should equal 5× the research
results):

| Check | Result |
|---|---|
| Partition IDs and order | identical |
| Recovery probabilities | equal, within 1.1 × 10⁻¹⁶ (floating-point summation order) |
| Expected gross, SD, maximum payout | exactly 5× (relative error ≤ 6 × 10⁻¹⁶) |
| Zero-payout probability | equal |
| Efficient sets | identical on all 17 slates |
| Recommendations | identical on all 17 slates |

**`SETTLEMENT` convention vs `EXACT`** (the effect of D-15 rounding):

| Check | Result |
|---|---|
| Recovery decisions changed | **0** of 38,080 state comparisons (17 × 280 × 8) |
| Largest change in expected gross | 0.007 credits |
| Recommendation changes | **0** |
| Efficiency flags changed | **8 of 4,760** groupings, all in three synthetic slates (S08: 4, S11: 2, S13: 2); none in the real slates |

**Why those 8 flags change:**
* In those slates, competing groupings have expected returns within fractions of
  a cent of each other (for example S08: 47.077192, 47.077362 and 47.077657
  credits).
* Rounding each accumulator to 0.01 shifts expected returns by up to about
  0.007 credits. That re-orders such near-ties on the expected-return axis and
  flips which one counts as dominated.
* Under the approved D-15 policy, the settlement-precision frontier is the
  authoritative one.
* The eight cases are pinned in the tests, so any future change in rounding
  behaviour is detected.

**Threshold edge cases tested:**
* 30 × 3.3332 = 99.996 settles at 100.00, so it recovers under D-15 (not when
  unrounded).
* 99.9939 settles at 99.99, so it does not recover.
* Two accumulators that each round up (50.005 → 50.01 and 49.992 → 49.99) sum to
  100.00 and recover. Their unrounded sum is 99.997.

### Performance

All 280 groupings, plus the frontier and recommendation, take about 15 ms in pure
Python on the development machine.
