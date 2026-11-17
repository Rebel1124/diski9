# Diski 9 Weekly Challenge — Implementation Plan (Phase 5C)

Status: **plan for review**. Each phase is one feature branch from `main`, merged
only with approval, with the full suite green and Goal Model 1.0 unchanged.

## Phase 0: Decisions and prerequisites (before any code)

Resolve the blocking decisions in the [decision register](weekly_challenge_decisions.md):
* D-01 identity;
* D-02 hosting;
* D-03 database;
* D-08 settlement rules;
* D-09 season scoring;
* D-11 round calendar;
* D-12 PSL coverage expectations.

Also merge or cherry-pick the Phase 5B research branch, so its reference
implementation is available to the equivalence tests (research code only, never
imported by the app).

**Exit:** every "requires approval" item is decided and recorded.

## Phase 1: Portfolio calculation and 100-credit scaling

**Scope:**
* `diski9/challenge/portfolio.py`:
  * dependency-free;
  * `Allocation(30, 30, 30, 10, target=100)`;
  * partitions, eight-state evaluation, Pareto, recommendation;
  * exact decimal payouts;
  * `payout_distribution()` for "Your Payout Probability".

**Dependencies:** Phase 5B research code (for tests).

**Risks:**
* floating-point edge cases near the threshold, mitigated by exact payout
  comparison;
* silent divergence from the research code, mitigated by equivalence tests.

**Acceptance:**
* identical to the research module on all 17 slates at 5× scale;
* within 50 ms for the 280 evaluations;
* no numpy at runtime.

**Tests:**
* 280 unique, canonical, deterministic partitions;
* eight state probabilities sum to 1, and the nine-fold wins only in (1,1,1);
* E[R] identity, recovery, profit and loss probabilities, SD ≥ 0;
* exact-rational reference examples, scaled from Phase 5B: fair coins give
  E = 100 and recovery 169/512; p 0.8 at odds 1.20 gives recovery 0.5180;
* scaling invariants (below);
* Pareto dominance, ties, order invariance;
* recommendation always efficient, with deterministic tie-breaks;
* `hypothesis` property tests on random slates (bounded odds and
  probabilities);
* payout distribution:
  * exact merging of equal payouts;
  * probabilities sum to 1;
  * `at_least` non-increasing and starting at 1;
  * P(R ≥ 100) from the step function == `p_recover` exactly;
  * maximum outcome = all-win payout with probability P_A·P_B·P_C;
  * Σ gross·probability = E[R];
  * the R1 worked example (UX §4.3) reproduced to 0.01 credit and 0.001%;
  * identical-bucket slates merge to fewer outcomes.

**Scaling regression tests (required):**
1. For every Phase 5B slate and all 280 partitions, `p_recover₁₀₀ == p_recover₂₀`
   exactly (same exact threshold decisions).
2. `E₁₀₀ == 5·E₂₀`, `σ₁₀₀ == 5·σ₂₀`, `net₁₀₀ == 5·net₂₀`, and every state return
   satisfies `R₁₀₀(s) == 5·R₂₀(s)` (exact for payouts; relative error ≤ 1e-12 for
   expectations).
3. The efficient set (recovery vs expected) is identical at 20 and 100.
4. The recommended partition is identical at 20 and 100.
5. Property test: for random slates, the same four invariants hold.

## Phase 2: Challenge rounds and eligibility (the round sheet)

**Scope:**
* Alembic migration 0005: rounds, round fixtures, round offers, with insert-only
  triggers.
* `challenge publish | status | cancel` CLI.
* Deadline rule (Option A) and fixture-change detection.

**Dependencies:** D-11 calendar; existing `challenge_consensus` and the screener
cache.

**Risks:**
* too few eligible fixtures, for example in international breaks (the publish
  step refuses with a reason);
* odds staleness at publish (publish after the morning refresh).

**Acceptance:**
* a round sheet reproduces the existing consensus and model values exactly;
* it can't be modified after publishing;
* the deadline equals the earliest eligible kickoff minus the buffer.

**Tests:**
* eligibility (≥ 3 groups, fresh, model available; stale and incomplete markets
  excluded);
* window assignment and time-zone boundaries (UTC storage; SAST and Europe
  display);
* immutability triggers;
* migration up and down;
* the existing odds and EV tests are unchanged.

## Phase 3: Fixture selection and portfolio explorer (UI, no persistence)

**Scope:**
* routing (`/`, `/challenge`);
* header navigation;
* picker;
* slip store;
* explorer chart, list and details;
* "Your Payout Probability" chart (cumulative and exact views, table form, 100-credit
  and maximum markers);
* review step (Submit disabled until Phase 4).

**Dependencies:** Phases 1 and 2.

**Risks:**
* chart clarity on small screens, mitigated by the list alternative;
* Screener regression, mitigated by an untouched layout and a full UI suite.

**Acceptance:**
* the UX specification states are implemented;
* 280 points with correct styling;
* dominated points unselectable;
* recommended point preselected;
* the payout-probability chart updates on every selection, with its 100-credit
  label equal to the frontier recovery;
* no page overflow at 390, 900 and 1440 px.

**Tests:**
* callback unit tests (replace on the same fixture, 9-pick limit, the
  ineligible outcome is not selectable);
* chart figure tests (trace counts, `customdata`, tie markers);
* payout chart figure tests:
  * step vertices only, no spline;
  * x range from 0 to the maximum payout;
  * threshold marker at 100 with the exact probability;
  * stems in the exact view sum to 100%;
  * "at least" / "exactly" labels;
  * Goal Model caption present;
* Playwright at three widths (pick nine, explore, select an efficient point,
  click a dominated point to no effect, keyboard list, the payout chart redraws
  after selecting another efficient point, toggle between the at-least and
  exactly views);
* the existing Screener and Match Lab browser tests stay green.

## Phase 4: Identity and immutable submissions

**Scope:**
* identity integration (per D-01) and `challenge_users`;
* display names;
* migration 0006 (entries, submissions, selections, accumulators, with
  triggers);
* `ChallengeService.submit`;
* receipt;
* My Challenge (pre-settlement).

**Dependencies:** D-01, D-02, D-03, D-04, D-05, D-07.

**Risks:**
* concurrency on SQLite, mitigated by `BEGIN IMMEDIATE`, unique constraints and
  optimistic versions;
* trusting client state, mitigated by recalculating everything server-side.

**Acceptance:**
* only valid entries are stored;
* resubmission creates a new version;
* locked entries are immutable;
* duplicate clicks are idempotent.

**Tests:**
* validation matrix (8 or 10 picks, duplicate fixture, ineligible outcome,
  dominated partition, tampered client metrics, after the deadline);
* concurrency (two simultaneous submits give one success and one conflict; the
  same idempotency key returns the same submission);
* snapshot fidelity (stored values equal the round sheet; `inputs_hash` stable);
* immutability triggers;
* authentication required for writes.

## Phase 5: Settlement engine

**Scope:**
* migration 0007 (result observations, settlement runs, selection and entry
  settlements);
* rules engine (`settle/v1`);
* `challenge settle | finalise | reopen` CLI;
* scheduling guidance.

**Dependencies:** D-08 rules; existing fixture refresh.

**Risks:**
* result corrections and API delays, mitigated by the correction window,
  pending states and the cutoff;
* rounding disputes, mitigated by an exact computation rounded once per
  accumulator.

**Acceptance:**
* every market and void case settles as specified;
* reruns insert nothing new;
* the audit trail explains every value.

**Tests:**
* per-market truth tables (0–0, 1–1, 2–1, 3–0 …);
* extra time and penalties ignored;
* each void code V1–V5;
* void odds = 1.00 in buckets and the nine-fold (one void, all void, all nine
  void → 100);
* pending until the cutoff;
* corrections before and after finalisation;
* idempotency (second run: zero inserts);
* rounding.

## Phase 6: Leaderboards and history

**Scope:** weekly and season queries (per D-09), leaderboard page, My Challenge
history, privacy setting.

**Dependencies:** Phases 4 and 5; D-04 and D-09.

**Risks:** scoring disputes, mitigated by printing the rule and hand-checked test
fixtures.

**Acceptance:** tables match hand calculations, including ties, provisional
status, non-entrants and qualification.

**Tests:**
* ranking with ties (1, 2, 2, 4);
* skipped rounds;
* qualification thresholds;
* hidden users;
* provisional to final transitions;
* performance with 5,000 synthetic entries.

## Phase 7: End-to-end testing and release preparation

**Scope:**
* a full round simulated end to end on a test database (publish → submit by
  several users → lock → results incl. postponement → settle → finalise →
  leaderboards);
* deployment checklist;
* operator runbook;
* documentation;
* release notes.

**Acceptance:**
* the end-to-end suite passes;
* full regression green;
* Goal Model 1.0 checksum unchanged;
* odds and EV unchanged;
* manual review on desktop and mobile;
* the owner approves the release.

## Cross-cutting test strategy (summary)

| Requirement | Phase |
|---|---|
| 280 unique partitions; fixed 30/30/30/10; scaling invariants | 1 |
| Eight-state calculations, recovery, expected return, Pareto, recommendation, tie-breaks | 1 |
| Market and odds eligibility (≥ 3 groups, fresh); no duplicate fixtures; one outcome per fixture | 2, 3, 4 |
| Immutable round sheet and submissions; duplicate prevention; deadline enforcement | 2, 4 |
| Settlement per market; voids and postponements; idempotency | 5 |
| Leaderboards | 6 |
| Integration (database plus service), Playwright end to end, Screener and Match Lab regression, Goal Model unchanged | 3–7 |

## Indicative sequencing

| Order | Phases |
|---|---|
| First | 0 |
| Then | 1 and 2, in parallel |
| Then | 3 |
| Then | 4 |
| Then | 5 |
| Then | 6 |
| Last | 7 |

Phases 1–3 deliver a usable "explore only" preview without accounts. That
preview could be shown to users for feedback before identity and hosting are
settled.
