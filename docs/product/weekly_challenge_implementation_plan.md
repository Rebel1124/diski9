# Diski 9 Weekly Challenge — Implementation Plan (revised, Phase 6A.2)

Status: **plan for review**. It supersedes the Phase 5C plan (`2e079ba`). Each
phase is one feature branch, merged only with the owner's approval, with:
* the full suite green;
* Goal Model 1.0 unchanged;
* odds collection, consensus and Edge/EV unchanged.

**What changed from Phase 5C:**
* No 280-grouping explorer, Pareto frontier or recommendation.
* Market-band buckets (`broad60-432-v1`: 4/3/2 picks, 40/30/20/10 credits).
* A bucket tracker, and Explore Your Bucket Risk.
* Exact round-opening checks.
* Recovery-gated weekly points and 10-round championships, replacing season
  scoring (old D-09).

**Phase 6A.3 (done, `feature/risk-structured-challenge-engine`):** the
generalised portfolio engine (`diski9.challenge.config`, `diski9.challenge.structured`)
and the pure scoring engine (`diski9.challenge.scoring`, `points-150-75-v2`),
covering the engine scope of Phase 6B, the pure checks of 6C and the pure
scoring logic of 6G. Persistence, UI, settlement and lifecycle remain. See
`docs/weekly_challenge_engine.md`.

**Phase 6B (done, `feature/weekly-challenge-ui`):** the interactive Dash
prototype (`/challenge`, `/challenge/me`, `/leaderboards`) on the 6A.3 engines:
frozen live/demo round snapshots, builder with tracker, Explore Your Bucket Risk,
market/model analysis and payout charts, prototype submission in the browser
session, demonstration leaderboards. This covers the UI scope of Phase 6D below.
No accounts, persistence or settlement. See `docs/weekly_challenge_ui.md`.

**Already done:**
* Phase 6A engine on `feature/weekly-challenge-engine` (`48392c1`): 3/3/3 picks,
  30/30/30/10 credits, the eight states, D-15 rounding, payout distribution. Not
  merged.
* Phase 6A.1 risk-structure research (`197e8ae`).
* Phase 6A.2 championship research (this branch).

## Phase 6B — Generalised engine (`broad60-432-v1`)

**Prerequisite:** the owner approves this revised spec and the open technical
decisions T-01 and T-02.

**Scope:**
* Extend the 6A engine with `ChallengeConfig`. Design §3.1 covers bands, sizes,
  stakes and the classification source. Store the config in code, versioned;
  never edited in place.
* `classify` at full precision; `validate_portfolio` (4/3/2 picks, distinct
  fixtures, derived buckets).
* `evaluate(..., source)` for market and model separately; `bucket_summary`.
* Delete the frontier, partition and recommendation code from the product path.
  It stays in git history.

**Tests:**
* the legacy 3/3/3 config reproduces every 6A vector exactly;
* `broad60-432-v1` matches `research.risk_structure.evaluate` on the real-pool
  portfolios;
* band boundaries at 0.20, 0.40, 0.60 and 0.95, plus 0.95 + ε and 0.20 − ε;
* the config invariants;
* the D-15 knife-edge cases (as in 6A);
* the payout-distribution invariants with unequal stakes;
* hypothesis: the bucket is always derived from the market probability, never
  from the client.

**Exit:** engine tests green; no UI, no schema change.

## Phase 6C — Round sheet and opening checks

**Scope:**
* Schema migration: rounds, fixtures, offers with `bucket`, and
  `config_version`.
* `challenge publish` copies the model probabilities and strict consensus
  (unchanged functions). It stores `market_prob` at full precision and `bucket`.
* **Opening checks** (design §5.4):
  * at least 15 eligible fixtures;
  * at least 3 leagues;
  * the max-flow strict 4/3/2 portfolio check.
  * A round that fails is postponed; it doesn't count toward a championship.

**Tests:**
* max-flow vs exact count on random sub-pools (port the research tests);
* "outcome counts alone are not enough";
* one league only → postponed;
* a 15-fixture boundary;
* an immutable sheet after publish.

**Exit:** a round sheet can be published and checked from the CLI.

## Phase 6D — Builder, review and Explore Your Bucket Risk (UI, no persistence)

**Scope** (UX §3–5):
* fixture pool with Mkt, D9, odds and bucket chip;
* auto-bucketing [+];
* tracker (Foundation X/4, Balanced X/3, Challenger X/2, Total X/9);
* bucket-full handling, and the "can't fill" warning (matching on unused
  fixtures);
* complete-bucket summaries before 9/9;
* portfolio analytics only at 9/9;
* the Market | Diski 9 estimate toggle;
* Your Payout Probability, kept from 5C with the 40/30/20/10 stakes;
* `/challenge/learn` with hypothetical inputs and fair odds, sharing no state with
  the builder.

**Tests:**
* callback unit tests;
* Playwright at 1280 px and 390 px: tracker counts, the full-bucket tooltip, no
  portfolio metrics before 9/9;
* the toggle names its source;
* the learn page never reads the round sheet;
* banned-words lint on the copy;
* Screener regression.

**Exit:** an "explore only" preview, usable without accounts.

## Phase 6E — Identity and immutable submissions

* Blocked on D-01, D-02 and D-03 (unchanged from 5C).
* Submission service as in design §6, with 4/3/2 validation from stored buckets.
* `states_json` stores the market and model distributions; insert-only triggers.
* **Tests:**
  * the deadline race;
  * idempotency;
  * optimistic version;
  * a tampered client bucket is rejected;
  * an incomplete portfolio is rejected.

## Phase 6F — Settlement

* As Phase 5C design §7, with these per-bucket stakes:
  * an all-void bucket returns 40, 30 or 20;
  * all nine void returns 100, which counts as a recovery.
* **Tests:**
  * every market;
  * void codes V1–V5;
  * the D-15 rounding agrees with the modelled states;
  * idempotent reruns.

## Phase 6G — Weekly points and championships

* `challenge_round_scores` (integer points), `challenge_championships`, and the
  round `designation` / `valid_entries` columns (design §12).
* Scoring `points-150-75-v2` (approved, D-31; pure logic done in Phase 6A.3):
  * 150/135/125/120/115/110/105/100/95/90 for ranks 1–10, else 75;
  * recovery-gated (gross ≥ 100.00);
  * standard competition ranking with full points for ties (D-26).
* Standings: points → recoveries → qualifying top-ten finishes → joint (D-27).
* Designation at the deadline: championship (≥ 5 valid entries), practice, void,
  postponed (D-28). Exactly 10 championship rounds; pause across breaks; reset;
  nothing carries forward (D-30).
* Re-score the whole round on any settlement correction. Championship standings
  are an aggregation, with a frozen snapshot at completion.
* **Tests:** port `tests/test_championship_scoring.py` (feasibility) and
  `tests/test_championship_refinement.py` (points, ties, series), plus:
  * re-scoring after a corrected score changes ranks;
  * practice, void and postponed rounds don't advance the counter;
  * resubmissions count once toward the 5-entry minimum;
  * the 11th championship round starts championship 2;
  * the frozen snapshot equals the aggregation.

## Phase 6H — End-to-end and release preparation

* A full lifecycle on a staging copy: publish → submit → lock → settle → points →
  standings.
* Playwright, accessibility checks, load smoke test, operator runbook.
* Goal Model checksum unchanged; odds and EV unchanged; the owner approves the
  release.

## Cross-cutting test strategy

| Requirement | Phase |
|---|---|
| Config invariants, band classification at full precision, 4/3/2 validation | 6B |
| Eight-state maths, D-15, market vs model kept separate, payout chart | 6B, 6D |
| Opening checks (15 fixtures, 3 leagues, max-flow) | 6C |
| Tracker, incomplete-portfolio handling, Explore Your Bucket Risk isolation | 6D |
| Immutable sheet and submissions; deadline; duplicates | 6C, 6E |
| Settlement and voids with unequal stakes | 6F |
| Weekly points, competition-ranked ties, designation, championship standings, re-scoring | 6G |
| Screener / Match Lab regression, Goal Model unchanged | every phase |

## Indicative sequencing

1. 6B and 6C can run in parallel.
2. Then 6D. The preview can be shown for feedback.
3. Then 6E (needs identity and hosting decisions).
4. Then 6F.
5. Then 6G.
6. Last, 6H.

**Empirical follow-up before the first official championship (D-29):** re-run
the Phase 6A.2 and 6A.2.1 simulations on 6–8 captured real weekly pools with
settled outcomes (the odds trial is producing them). This runs in parallel with
6B–6D; it does not block the engine or the Dash prototype.
