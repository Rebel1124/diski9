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

**Phase 6B.1 (done, `feature/weekly-challenge-ux-refinement`):** the
playtesting refinement:
* the compact builder and live tracker;
* the 512-state analysis;
* Screener / Match Lab integration with one shared portfolio and Your View;
* the two-step journey;
* frozen confirmed submissions, a pinned round snapshot and draft revalidation;
* My Challenge and Leaderboard visuals.

See `docs/weekly_challenge_ui.md`.

**Phase 6B.2 (done, `feature/weekly-challenge-playtest-refinement`):** the second
playtesting refinement: the submission-restoration fix (eager state reconciliation,
one source of truth, demo/live isolation), compact Screener filters without the
odds-only toggle, one table presentation using frozen snapshot values, Match Lab
outcome cards, How to play guidance, calculation explanations, a combined
correct-predictions chart, submission withdrawal, the My Challenge layout, rank
icons and no emojis. See `docs/weekly_challenge_ui.md`.

**Phase 6B.3 (done, `feature/weekly-challenge-final-polish`):** final polish: Match
Lab naming and standard headings, readable filters, symmetrical My Challenge cards,
compact How to play, frozen probability ranking and filtering for the Weekly
Challenge universe, Your View in session storage with model-context stamps, and a
fix for taps swallowed during the builder's mount. See `docs/weekly_challenge_ui.md`.

## Next phases (owner-confirmed at the Phase 6B close-out)

The original 6C–6H lettering below describes the full build-out and is kept for
reference. The owner has confirmed the next two phases and their backlog:

**Phase 6C — production foundations (requirements and acceptance criteria
updated at the Phase 6C preparation review).** The staged delivery (6C.1
PostgreSQL foundation to 6C.6 administration and integration testing), with
deliverables, dependencies, files, tests, risks and review points per stage, is
in the [Phase 6C staged plan](weekly_challenge_phase6c_plan.md). Direction
confirmed at the architecture finalisation: modular monolith, PostgreSQL with
Docker Compose locally, SQLAlchemy 2, Alembic, pytest on real PostgreSQL, managed
OIDC, scheduled CLI jobs.

*Dependencies (must be decided before implementation starts):* D-01 identity,
D-03 database, D-05 display names, D-06 deadline buffer, D-11 calendar defaults
and D-34 roles; before settlement work: D-08 void codes and cutoff, and D-35
result overrides. D-02 constraints (host-agnostic code) apply throughout. See the
[outstanding decision review](weekly_challenge_phase6c_decision_review.md) and
[architecture considerations](../architecture/phase6c_architecture_considerations.md).

*Requirements:*
1. **Accounts and access:** sign-in, a user record keyed by an internal ID,
   display names (D-05), roles and capabilities checked server-side (D-34),
   separation of identity from participant records (D-36), terms-version field
   (D-37).
2. **Persistent storage:** challenge tables in a new migration; immutability of
   round sheets, submissions, results and settlement history.
3. **Server-authoritative rounds:** publish with the frozen round sheet and
   opening checks (D-28); deadline stored per round (D-06) and enforced by the
   server clock in every write; a restart changes nothing.
4. **Portfolio lifecycle:** submission, replacement and withdrawal (T-09) with
   full history; idempotent submits; the locked entry set stamped at the deadline.
5. **Your View storage** per user (T-10), private and context-stamped.
6. **Settlement:** result observations (provider, plus audited operator overrides
   under D-35); verdicts under `settle/v1` (D-08); payouts under D-32 with D-15
   rounding; fully void entries under D-33; the **D-32b** round-invalidation rule
   with its clarifications; the 24-hour correction window (R-14); idempotent,
   recorded settlement runs.
7. **Designations and championships:** designation fixed at the deadline (D-28,
   T-07); D-32b and operator voids as insert-only designation entries (T-11);
   points via `challenge.scoring` (D-31, D-26); standings (D-27); ten-round
   championships that pause (D-30); counter and standings derived, with a frozen
   snapshot at completion.
8. **Leaderboards:** weekly and championship tables from current settlements,
   honouring the privacy flag (D-04).
9. **Audit:** an audit record for every operator action (publish, postpone, void,
   override, reopen, rename) with actor and reason.
10. **Scheduled jobs:** idempotent CLI jobs (refresh, publish, lock, settle,
    finalise) with an overlap lock and run records.
11. **Integration:** the accepted Phase 6B UI reads from the server; browser
    storage keeps drafts and preferences only.

*Acceptance criteria:*
* Only an authenticated participant can submit, replace or withdraw, and only
  before the server-side deadline, including through direct callback calls.
* A submitted portfolio, its history and the round sheet survive a server
  restart unchanged; duplicate clicks create one submission; simultaneous edits
  are rejected with a conflict, not lost.
* A withdrawn entry is excluded from the locked set and from the D-28 and D-32b
  counts.
* Settlement reproduces the engine's D-15 payouts for every void code; partial
  voids follow D-32; all-void entries are "Void — Refunded" (D-33); a rerun with
  no new information inserts nothing but the run record.
* **D-32b:** the rule is evaluated over the locked entry set by prediction
  instance; played means won or lost; `2 × played > total` and at least five
  ranked entries keep the round competitive; exactly 50% voids it; pending
  predictions never trigger it; the outcome is provisional during the correction
  window; a void round returns 100 credits to every confirmed participant with no
  points, recoveries, top-ten finishes, competitive ranking or counter step; all
  submissions, results, provisional calculations and the reason are retained.
* A correction that moves a round across the D-32b threshold (either way) is
  recorded as an audited reassessment, and championship points and the counter
  are identical to a from-scratch recomputation (no duplication).
* An operator round void requires the operator capability and a reason, and is
  audited; a participant cannot perform it.
* Weekly points and championship standings match the engine's worked examples;
  practice, postponed and void rounds never advance the counter.
* Goal Model 1.0, odds ingestion, consensus, forecast snapshots and the accepted
  UI behaviour are unchanged.

**Phase 6D — quality, performance and integration:**
* initial page-render performance (the builder's ~2.5–3 s first-render pause);
* clicks that can be ignored while Dash mounts a page (mitigated in Phase 6B.3;
  a tap in the exact instant of mounting can still be dropped);
* a clear distinction between frozen Weekly Challenge probabilities and the live
  Match Lab analysis (for example labelling the live analysis when opened from
  the Weekly Challenge universe);
* end-to-end integration testing.

**Open decisions (after the architecture finalisation):** D-01 provider, D-08
exact definitions, D-29 validation and D-29b collection activation, D-36 final
retention policy, D-39 football-store migration timing, D-40 merge and tag of
Phase 6B, T-12 session lifetimes and T-13 continuous integration. See the decision
register.

**Phase 6C must still add:**
* server-side published round records with deadlines;
* persistent submissions;
* snapshot republication and correction handling;
* settlement, including D-32 and D-33;
* persistent submission history and withdrawal records (the prototype withdrawal
  only clears the browser-tab entry; a real one needs an audit trail, the deadline
  enforced server-side and a resubmission record);
* a stable round snapshot that survives a server restart (the prototype pins it in
  process memory and reconciles drafts when it is rebuilt).

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
  * partially voided portfolios follow D-32 (void legs 1.00, payouts recalculated
    with D-15 rounding);
  * all nine void returns 100.00 as "Void — Refunded": unranked, 0 points, not a
    recovery (D-33).
  * a round fails the approved D-32b test (half or fewer of the locked
    predictions played, or fewer than five ranked entries) → void round (T-08).
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

**Championship scoring validation (D-29, approach approved):** keep collecting
real weekly fixture pools and reference odds through the scheduled odds trial, then
validate the approved scoring (D-31) on six to eight real weekly pools: fixture
availability, round feasibility, scoring fairness, recovery rates, participant
behaviour and the effect of growing competition size. The scoring is retained
unless the evidence is compelling. Not a blocker for development; must be complete
before the first official public championship. The same pools are used to validate
the approved D-32b rule, reporting observed voids separately from simulated
cancellation scenarios. The scheduled odds trial covers only the EPL and PSL and
ends on 21 November, so full eight-league weekly pools need a weekly capture after
it (awaiting approval).
