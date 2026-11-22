# Phase 6C — Staged implementation plan

**Status:** 6C.0, 6C.1 and 6C.2 implemented; 6C.3 implemented (Stages A–G and post-G refinements), formally accepted by the owner on 19 Nov 2026 and released as v4.1.0 (closure: `docs/architecture/phase6c3_closure_handover.md`; release notes: `docs/releases/v4.1.0.md`); 6C.4 Stage A approved (decisions S-01 to S-11), Stages B–D implemented and accepted at the owner checkpoint, and Stages E–G implemented; **6C.4 formally accepted by the owner on 20 Nov 2026 and released as v4.2.0** (closure: `docs/architecture/phase6c4_closure_handover.md`; release notes: `docs/releases/v4.2.0.md`); **6C.5 (leaderboards and championships): Stage A approved by the owner on 20 Nov 2026 (decisions CH-01 to CH-12, D-30a); Stage B approved (20 Nov 2026, `ccd7c4e`); Stage C complete and approved (20 Nov 2026, `3999974`); Stage D complete, owner-approved and formally closed (20 Nov 2026, `65a1440`; local acceptance Checkpoints 1–4 passed, 5–6 owner-waived); Stage E complete, owner-approved and formally closed (21 Nov 2026, `e820790`; closure: `docs/architecture/phase6c5_stage_e_closure_handover.md`); Stage F authorised as four checkpoints (F1 development tooling, F2 integration and security, F3 performance and concurrency, F4 regression and Stage G handover); F1 implemented, owner-approved and formally closed (21 Nov 2026, `8379606`); F2 implemented, owner-approved and formally closed (21 Nov 2026, `7afc03b`); F3 implemented, owner-approved and formally closed (21 Nov 2026, `c2583c3`; signed-in page-load miss accepted as a documented limitation); F4 (final regression, stability and handover) implemented, owner-approved and formally closed (21 Nov 2026, `f0ac3c2`, CI run 81); **Stage G owner acceptance recorded and Phase 6C.5 complete (21 Nov 2026)** (acceptance record: `docs/architecture/phase6c5_stage_g_handover.md`); not merged, tagged or released; release gates remain open; **6C.6 (operations): Stage A design approved and closed (21 Nov 2026, decisions Q-01 to Q-14; `docs/architecture/phase6c6_design_proposal.md` §11); Stage B (S-07 remediation) formally accepted (21 Nov 2026, `85b8608`, CI run 86; `docs/architecture/phase6c6_implementation.md` §2; Q-03 recovery deferred; browser tests in GitHub CI); Stage C (scheduler, supervised publication) formally accepted (21 Nov 2026, `f89de9d`, CI run 89; `docs/architecture/phase6c6_implementation.md` §4; provider limits provisional, live calls disabled); Stage D monitoring, alerts and recovery formally accepted (21 Nov 2026, `45faeac`, CI run 92); scheduler-locking remediation (R1–R6) formally accepted (21 Nov 2026, `0f3c0b1`, CI run 95) and **Stage D closed** (`docs/architecture/phase6c6_implementation.md` §5–§6); Stage E (operational administration and remaining backlog) formally accepted and **complete** (21 Nov 2026, `c49de86`, CI run 99; `docs/architecture/phase6c6_implementation.md` §7); **Stage E.1 (automated draft preparation): design approved in principle** (21 Nov 2026; `docs/architecture/phase6c6_stage_e1_design.md`; API-Football the sole provider); **E.1a (draft creation, readiness, monitoring; no provider calls) formally accepted and closed** (`3ed0301`, CI run 104; `docs/architecture/phase6c6_implementation.md` §8); **next: E.1b (automated API-Football data refresh)**: design approved in principle (22 Nov 2026; `docs/architecture/phase6c6_stage_e1b_design.md`; REF-01–REF-10, REF-15, REF-16) and implementation plan (`docs/architecture/phase6c6_stage_e1b_plan.md`); implemented and **formally accepted and closed** (22 Nov 2026; `4394485`, CI run 109; refresh disabled, not activated; `docs/architecture/phase6c6_implementation.md` §10); **next: Stage F (integration and genuine Beta-week validation), awaiting separate authorisation; Stage G not started**; E.1b implementation, F and G not authorised** ([`../architecture/phase6c5_design_specification.md`](../architecture/phase6c5_design_specification.md)); Stages C–G each need owner approval. Original status: plan for owner review. Each stage is a separate
branch from the agreed base (§0), reviewed and approved by the owner before the
next begins. Every stage keeps:
* the deterministic engines unchanged (`challenge.structured`, `analysis`,
  `scoring`, the round-sheet maths, Goal Model 1.0 at k_s 12, k_t 96, m0 30);
* odds ingestion, consensus, forecast snapshots and the football schema
  unchanged;
* the accepted Phase 6B UI unchanged in layout and behaviour (only its data
  source changes);
* the full existing test suite green, plus the new PostgreSQL tests.

References: [technical architecture](../architecture/phase6c_architecture_considerations.md),
[database design](../architecture/phase6c_database_design.md),
[auth comparison](../architecture/auth_provider_comparison.md),
[`settle/v1`](weekly_challenge_settle_v1.md),
[decision register](weekly_challenge_decisions.md).

## 0. Starting point (recommended)

1. **Merge decision first:** Phase 6B (`feature/weekly-challenge-final-polish`,
   which contains all 6B work and these documents) is accepted but unmerged.
   Recommended: merge it to `main` and tag it (for example `v0.6b`) when you
   instruct, so Phase 6C branches start from the accepted product.
2. **Then create** `feature/phase-6c1-postgres-foundation` from that point.
3. **First commit of 6C.1:** `docker-compose.yml` with PostgreSQL, the
   `diski9.backend.db` engine factory and settings (`DISKI9_APP_DATABASE_URL`),
   an empty `migrations_app/` Alembic environment, and a pytest fixture that
   provisions a disposable PostgreSQL database, plus one smoke test, plus a CI
   workflow running it.

## 6C.0 — Weekly research collector (separate, small; only if approved)

* **Objective:** implement the D-29 collector commands from the
  [proposal](../research/weekly_pool_collection_proposal.md).
* **Files:** `src/diski9/research/weekly_pool.py`, CLI commands
  `research-pool capture|results|replay|report`, `tests/test_weekly_pool.py`.
* **Database:** none in the competition database; its own SQLite file.
* **Acceptance:** replay reproduces the pool hash; isolation guard refuses
  PostgreSQL URLs; no engine, odds or UI code changed.
* **Stop:** owner confirms schedules and branch before activation.

## 6C.1 — PostgreSQL foundation

* **Objectives and deliverables:** local PostgreSQL through Docker Compose; the
  competition schema (all tables in the database design, created empty);
  insert-only and set-once triggers; database roles (`diski9_app` with INSERT and
  SELECT only on history tables, `diski9_migrator`); repository modules with typed
  queries; test infrastructure on real PostgreSQL; CI.
* **Dependencies:** D-03 (approved); the merge decision in §0.
* **Modules and files:** `docker-compose.yml`; `src/diski9/backend/db/`
  (`engine.py`, `metadata.py`, `roles.sql`); `migrations_app/` (env and
  `0001_competition_schema.py`); `src/diski9/backend/repositories/*.py`;
  `tests/backend/conftest.py`; `.github/workflows/ci.yml`; `docs/backend.md`.
* **Database changes:** competition schema version 0001 (all entities;
  configuration rows for `features`, the weekend round schedule and the beta
  series).
* **Acceptance criteria:**
  * `docker compose up -d` and one migration command create the schema from
    nothing; downgrade and upgrade round-trip cleanly;
  * the application role cannot UPDATE or DELETE any history table (tested);
  * set-once columns reject a second write; insert-only tables reject UPDATE and
    DELETE;
  * the football SQLite store, its migrations and all existing tests are
    unchanged.
* **Required tests:** migration round-trip; trigger and privilege tests per
  history table; constraint tests (unique, check, composite ownership keys,
  deferred keys); repository round-trips.
* **Known risks:** Docker availability on the owner's machine (mitigation:
  documented install steps); CI minutes; trigger logic drift (mitigation: one
  generic trigger function).
* **Stop for review:** schema walkthrough and test report.

## 6C.2 — Authentication, accounts, roles, profiles, entitlements

* **Objectives:** OIDC sign-in with the approved provider; server-side sessions;
  account creation (username D-05, 18+ declaration and terms acceptance D-37);
  privacy mode and anonymous alias (D-04); roles and capability checks (D-34);
  entitlement checks; profile page integration into the existing navigation;
  account deletion workflow (D-36, provider deletion included).
* **Dependencies:** D-01 provider approval; session lifetimes; a development
  project at the provider (free tier) and a custom SMTP decision before beta.
* **Modules and files:** `src/diski9/backend/auth/` (`oidc.py`, `sessions.py`,
  `permissions.py`), `services/accounts.py`, Flask blueprint registration in
  `app/__init__.py` (no layout changes to accepted pages), a minimal sign-in and
  profile page in the existing visual style, CLI `diski9 grant-role`,
  `diski9 grant-feature`.
* **Database changes:** none structural (tables exist from 6C.1); seed
  `terms_versions` 1.
* **Acceptance criteria:**
  * sign-in, sign-out, idle and absolute expiry work; a revoked session is
    rejected immediately;
  * every write service requires a session; capability and entitlement checks
    are enforced server-side, verified by calling services and callbacks
    directly as participant, operator and owner;
  * `lucy.*` features exist and only the owner holds them;
  * usernames: 3–24 characters, case-insensitive uniqueness, blocklist, 30-day
    rule, history recorded; anonymous mode shows only the alias;
  * deletion removes personal data and the provider account and keeps
    non-identifying records.
* **Required tests:** OIDC callback with a test double (state, nonce, signature,
  audience, expiry failures); session fixation and CSRF origin checks;
  permission matrix tests; username rules (including Unicode look-alikes);
  privacy history; deletion.
* **Known risks:** provider configuration differences between local and hosted;
  email deliverability; cookie behaviour behind proxies (mitigation: explicit
  proxy-header configuration and tests).
* **Stop for review:** sign-in demonstration and permission test report.

## 6C.3 — Rounds, snapshots, drafts, Your View, portfolio lifecycle

* **Objectives:** versioned round schedules; publish job writing immutable
  snapshots with opening checks; server-side deadlines; drafts; confirm,
  replace, withdraw (T-09) with history; lock job and base designation; Your View
  persistence (T-10: the current numerical adjustments only, per user and fixture,
  across devices; no notes or reasons and no adjustment history, D-41); connect the
  accepted Weekly Challenge, My Challenge and
  Match Lab pages to the backend.
* **Dependencies:** 6C.1, 6C.2; D-06 and D-11 (approved).
* **Modules and files:** `services/rounds.py`, `services/portfolios.py`,
  `jobs/publish.py`, `jobs/lock.py`; adapters in `app/challenge/` replacing the
  prototype `state.py` authority with service calls (the reducer logic for local
  interaction is kept); `app/lab.py` storage adapter for Your View.
* **Database changes:** none structural; possibly indexes found necessary by
  load tests (new migration).
* **Acceptance criteria:**
  * a published snapshot is identical (fingerprint) to the prototype's live
    snapshot for the same inputs and survives restarts;
  * only valid 4/3/2 portfolios from the snapshot can be confirmed, including
    through direct callback calls; client-supplied buckets or odds are ignored;
  * submissions after the deadline are rejected by the database clock, including
    in a race with the lock job;
  * duplicate clicks create one submission; two tabs produce a conflict, not a
    lost update; withdrawn entries are excluded from the locked set;
  * the Phase 6B pages look and behave as accepted (screenshot comparison).
* **Required tests:** concurrency tests on PostgreSQL (parallel confirms, confirm
  versus lock, replace versus withdraw); fingerprint equivalence; ownership
  attacks (another user's entry ID); deadline boundary tests; Playwright
  walkthroughs at desktop, tablet and phone sizes.
* **Known risks:** builder render time (Phase 6D item) may grow with server
  calls (mitigation: cache snapshots per process); replacing the prototype state
  without regressions (mitigation: keep the reducer and swap only persistence).
* **Stop for review:** playtest of the persistent lifecycle.

## 6C.4 — Settlement, voids, refunds, corrections, concurrency, audit

* **Objectives:** results job copying observations; `settle/v1` verdicts; D-32
  payouts with D-15 rounding; D-33 refunds; D-32b evaluation (competitive and
  practice variants); operator result corrections (D-35); operator round void;
  settlement runs; audit records.
* **Dependencies:** D-08 final approval; 6C.3.
* **Modules and files:** `services/settlement.py` (pure verdict and payout
  functions in `challenge/settle.py`, a new pure module reusing D-15 rounding),
  `jobs/results.py`, `jobs/settle.py`, `services/admin.py`.
* **Database changes:** none structural. *Stage A assessment (19 Nov 2026): a small
  additive migration is proposed (`app_0006`, §10 of
  `docs/architecture/phase6c4_implementation.md`) for evidence, synthetic-data
  isolation and frozen windows; awaiting owner approval.*
* **Acceptance criteria:** settlement payouts equal the engine's eight-state
  values for every verdict combination; void codes follow `settle/v1` exactly;
  reruns with no new information insert only a run record; D-32b examples
  (including exactly 50%, pending, five ranked entries, practice rounds) pass;
  corrections that cross the D-32b threshold in either direction are audited and
  produce no duplicate effects; overlapping settlement runs are impossible.
* **Required tests:** property tests (hypothesis) comparing settlement with the
  engine; table tests per status code and precedence; correction sequences;
  parallel settlement attempts; audit completeness.
* **Known risks:** provider status quirks (mitigation: unknown codes stay
  pending with alerts); late corrections after finalisation (reopen path).
* **Stop for review:** settlement report on replayed real results (D-29 pools if
  available, otherwise the 17 November pool with simulated outcomes, clearly
  labelled).

## 6C.5 — Leaderboards, championship progression, history

**Stage A (approved 20 Nov 2026):** the owner's business requirements
(L-01 to L-37), the verified settlement rules, the architecture, the `app_0007`
schema, the championship lifecycle, the correction methodology, the UI, privacy,
performance targets, the test strategy, the refined Stages B–G and the twelve owner
decisions (Q-1 to Q-12, resolved as CH-01 to CH-12 and D-30a) are in
[`../architecture/phase6c5_design_specification.md`](../architecture/phase6c5_design_specification.md).
That document supersedes the outline below where they differ. In particular,
championship membership is stored ("sticky", in deadline order) instead of the
derived `championship_rounds` view, and `championship_freezes` is replaced by
versioned standings. **Private mini-leagues are removed from the MVP roadmap**
(owner, 20 Nov 2026); they will be reconsidered only after launch, with active
users and concrete feedback.

*Original outline (Phase 6C planning):*

* **Objectives:** score sets via `challenge.scoring`; weekly leaderboards with
  privacy rules; derived championship membership and standings (D-27, D-30);
  championship freezes; beta and official series (D-38); history pages wired to
  the accepted Leaderboards and My Challenge views.
* **Dependencies:** 6C.4.
* **Modules and files:** `services/championships.py`, `jobs/finalise.py`,
  leaderboard queries in `repositories/championships.py`, adapters in
  `app/challenge/`.
* **Database changes:** the `championship_rounds` view (migration).
* **Acceptance criteria:** standings equal a from-scratch recomputation after any
  sequence of corrections; voiding round 5 of an open championship renumbers
  later rounds and changes the counter correctly; frozen championships change only
  through reopen; anonymous entries show aliases (and stay distinguishable);
  ties follow D-26 and D-27.
* **Required tests:** port the championship research tests; correction
  sequences; privacy rendering; ten-round boundary and the eleventh round.
* **Known risks:** query cost with many rounds (mitigation: indexes and a
  per-process cache invalidated after settlement).
* **Stop for review:** demonstration on a simulated beta series.

## 6C.6 — Administration, scheduled jobs, monitoring, integration testing

* **Objectives:** operator console pages (publish status, results corrections,
  round void, audit viewer) restricted by capability; job scheduling definitions
  (platform-neutral, cron syntax); health check endpoint; structured logs;
  alerts for failed or late jobs and pending results beyond the cutoff; backup
  and restore procedure; full lifecycle integration test.
* **Dependencies:** 6C.1–6C.5.
* **Modules and files:** `app/admin/` (minimal pages), `jobs/schedule.md` or
  `deploy/cron.example`, `src/diski9/backend/health.py`, `docs/operator_runbook.md`,
  `tests/backend/test_lifecycle.py`.
* **Database changes:** none expected.
* **Acceptance criteria:** a scripted full week (publish → submissions → lock →
  results → settle → corrections → finalise → leaderboards) passes on PostgreSQL;
  a participant cannot reach any admin function by any route; jobs are
  idempotent and non-overlapping; a restore from backup reproduces standings.
* **Required tests:** end-to-end lifecycle; permission sweep of every callback;
  job overlap; restore drill.
* **Known risks:** scope growth in the admin pages (keep them minimal);
  scheduler differences between hosts (cron syntax only).
* **Stop for review:** Phase 6C acceptance; then Phase 6D.

## Cross-stage acceptance (Phase 6C as a whole)

The Phase 6C acceptance criteria in the
[implementation plan](weekly_challenge_implementation_plan.md) (persistent
lifecycle, settlement, D-32b, corrections, permissions, unchanged engines and UI)
are met, and every new rule is tested against real PostgreSQL.

## Implementation notes (6C.0 and 6C.1)

**6C.0 — weekly research collector (done, branch `research/weekly-pools`).**
See the collection proposal §12 on that branch
(`docs/research/weekly_pool_collection_proposal.md`).
The schedules (Thursday 08:00 SAST capture from 26 November 2026; daily 09:15 SAST
results) fire into one dedicated collector session that has the repository
attached; a pre-activation check showed that sessions started fresh for each run
could not push to the repository.

**6C.1 — PostgreSQL foundation (done, branch `feature/phase-6c1-postgres-foundation`).**
* **Infrastructure:** `docker-compose.yml` (PostgreSQL 17, localhost-only port,
  named volume, health check), `docker/postgres/init/` (test database and the
  `diski9_app` role), `.env.example` entries, `diski9 app-db upgrade|downgrade|
  current|check`.
* **Access layer:** `diski9.backend.db` (`settings`, `engine` with `transaction`,
  `read_only`, `db_now`, `check_health`; `migrate`; `schema` mirror) and
  `diski9.backend.repositories` (`accounts`, `rounds`, `portfolios`, `ops`), using
  SQLAlchemy 2 Core and psycopg 3 (new production dependency `psycopg[binary]`).
* **Schema:** revision `app_0001` in a separate Alembic environment
  (`migrations_app/`, version table `public.app_alembic_version`), written as
  explicit SQL: 37 tables, history and guarded-table triggers, set-once columns,
  the submission deadline trigger, composite ownership keys, deferred keys,
  approved-rule CHECKs, runtime-role grants and seed configuration.
* **Tests:** `tests/backend/` (settings guards, migrations, integrity and
  privileges, multi-connection concurrency) against real PostgreSQL; CI workflow
  `.github/workflows/ci.yml`.
* **Deviations from the stage description:** the database role is created by the
  Docker init script (local) or by the operator (deployments), not by migrations,
  because roles are cluster-wide; repositories cover the foundation tables only
  (settlement, scoring and championship queries come with their stages).
* Details and commands: [`docs/backend.md`](../backend.md).

## Implementation notes (6C.2)

**6C.2 — authentication, accounts and permissions (done, branch
`feature/phase-6c2-authentication`).** Details: [`docs/authentication.md`](../authentication.md).
* **Flow:** Supabase Auth through the official Python client server-side; email and
  password; token_hash email links verified with `verify_otp` behind a confirm
  button; Diski 9's own server-side sessions; provider tokens encrypted and
  refreshed under a row lock.
* **Database:** migration `app_0002` (session provider columns, authentication
  rate-limit events, beta terms version, row-level security on every `app` table
  with access only for `diski9_app`; nothing for Supabase's browser roles).
* **Modules:** `diski9.backend.auth` (`settings`, `crypto`, `provider`, `sessions`,
  `accounts`, `usernames`, `permissions`, `privileged`, `ratelimit`, `web`,
  templates); account menu in `diski9.app.app`; `assets/account.css`,
  `assets/account.js`; CLI `diski9 account ...`; `tools/local_auth/` (local
  Supabase Auth harness); `supabase/config.toml` and email templates.
* **Deviations:** none from the brief. Google sign-in deferred as allowed. Sign-out
  from the Dash menu goes through a confirmation page (a POST with a CSRF token).
* **Tests:** unit, mocked-provider (real PostgreSQL), Supabase PostgreSQL
  compatibility, and genuine Supabase Auth integration (local server; CI uses the
  official image). Hosted Supabase not tested (needs an owner-created project).
* **Owner decisions (19 November 2026):** T-14 to T-17 approved (register). T-15
  in 6C.2: keep/discard choice for guest work in the tab at sign-in, clearing at
  sign-out and account switching. **Carried into 6C.3:** saving kept work to the
  account, no silent overwrite of a stored portfolio, revalidation against the
  current round and frozen snapshot, no automatic submission, server-side Your
  View storage. Local acceptance guide:
  [`phase6c2_local_acceptance_mac.md`](../phase6c2_local_acceptance_mac.md).

## Implementation notes (6C.3, Stages A–D)

**6C.3 checkpoint (branch `feature/phase-6c3-competition-persistence`).** Record:
[`phase6c3_implementation.md`](../architecture/phase6c3_implementation.md); handover:
[`phase6c3_implementation_handover.md`](../architecture/phase6c3_implementation_handover.md);
local acceptance: [`phase6c3_local_acceptance_mac.md`](../phase6c3_local_acceptance_mac.md).
* **Done:** services for rounds (create, publish with opening checks and a frozen,
  fingerprint-checked snapshot, lock with the `deadline` designation), drafts and
  Your View (private, versioned, validated server-side); development rounds from
  deterministic synthetic fixtures; `diski9 round ...`.
* **Database:** migration `app_0003` (additive: version columns, development flag,
  snapshot and draft guards). The stage description expected "none structural";
  the version columns are needed for the approved "two tabs produce a conflict"
  criterion, which the 6C.1 schema covered only for entries.
* **Module layout:** publish and lock live in `services/rounds.py` (run by the CLI or
  a scheduler) rather than separate `jobs/` modules; drafts and Your View have their
  own service modules.
* **Waiting for approval:** Stages E (confirm, replace, withdraw), F (pages) and G
  (acceptance); owner questions Owner-1, Owner-2 and ID-5.

## Implementation notes (6C.3, checkpoint refinements and Stages E–G)

Approved at the checkpoint (19 November 2026): Your View per analytical context
(live and each published snapshot), guest Your View adoption, the one-hour
snapshot construction age (separate from odds freshness), D-11 revised to Friday
08:00 SAST, frozen-versus-latest information in the pages, and competitive
classification kept separate from official championship membership. Then:
Stage E (confirm, replace, withdraw, re-entry with authoritative validation and
deadline checks after every lock), Stage F (pages connected; per-tab save
ordering, migration `app_0005`) and Stage G (real-browser journeys A–G,
regression, performance, documentation). Record:
[`phase6c3_implementation.md`](../architecture/phase6c3_implementation.md);
handover: [`phase6c3_implementation_handover.md`](../architecture/phase6c3_implementation_handover.md).

## Implementation notes (6C.4, Stages B–D)

Stage A approved with decisions S-01 to S-11 (completion-based cutoff, no grace
period). Stages B–D on `feature/phase-6c4-settlement`: migration `app_0006`
(evidence, development result modes, verdict rules, run manifests, settlement
versions, alerts), pure `settle/v1` resolution, provider by-ID fetch boundary,
round settlement through the unchanged engine, D-32b, corrections, alert
resolution, operator invalidation, finalisation and owner-only reopening.
**Database changes:** one additive migration (the plan's "none structural" was
revised by S-10). Record: `docs/architecture/phase6c4_implementation.md` §23.
Stages E (CLI), F (My Challenge) and G (acceptance) need separate authorisation.

## Implementation notes (6C.4, Stages E–G)

Authorised 20 Nov 2026 after the B–D checkpoint. **E:** operator commands with an
interactive Supabase password check per command (S-07), previews and typed or token
confirmation for material changes, read-only status and evidence reports,
development-only result modes, scenarios (a prompt timeline; `entry-all-void` added
so an individual D-33 refund can be seen in a valid round) and test entries
confirmed with each participant's own password. **F:** My Challenge shows the
participant's own settlement (status, credits, counts, recovery, the four
accumulators, each prediction's 90-minute score and verdict, correction, refund and
finalisation notices) in the existing cards; Portfolio Analysis unchanged. **G:**
full regression, genuine CLI tests in a pseudo-terminal, browser journeys, a
controlled live check of the by-ID fetch (3 provider requests), performance and the
owner's Mac guide. For 6C.6: the scheduled finalisation job should run a full
relevant-fixture re-check (`results import --full`) before finalising. Record:
`docs/architecture/phase6c4_implementation.md` §24. Accepted by the owner on 20 Nov
2026 (§25) and released as v4.2.0.

## Outstanding work accepted at the 6C.5 closure (21 Nov 2026)

Accepting Phase 6C.5 completes **none** of these items. Record:
`docs/architecture/phase6c5_stage_g_handover.md`.

**Known defect scheduled for remediation**

| ID | Item | Detail |
|---|---|---|
| ML-01 | Match Lab stale-adjustment race | **Failure scenario:** after a market change (or another input that rebuilds the match detail), the detail-rebuild callback (`update_detail`) is still in flight; the participant clicks **Reset to model** or edits a Section B, C or D adjustment; when the rebuild's response arrives last, it writes `lab-store` from the value it held when its request was sent and the rebuilt inputs restore the **earlier** adjustment, undoing the Reset or edit. Needs a slow server, network or device and an action inside that window (observed in F4 only with the CPUs saturated). **Severity:** low. **Impact:** browser-side what-if adjustments and the saved Your View only — no effect on entries, settlement, scoring, championships or leaderboards — but a participant can see an adjustment they removed reappear, which undermines confidence in the displayed what-if figures and can mislead their analysis. **Requirement:** a narrowly scoped fix to the callback writes (no redesign) with deterministic regression coverage of the late-response ordering (browser test that holds the rebuild response, plus a callback-level test). **Target:** completed **before private beta testing with real users** (before Phase 10). Not to be implemented in Stage G. |

**Accepted performance limitations (targets unchanged; results not reclassified)**

| Item | Detail |
|---|---|
| Signed-in Dash leaderboards page load | target ≤ 600 ms; measured 653 ms (F3), 704–727 ms (F4); cause: Dash page shell and Screener callbacks |
| Guest Dash leaderboards page load | target ≤ 600 ms; measured 594 ms (F3), 586–635 ms (F4): variability around the target |
| 10,000-participant stretch | uncached provisional page ~550 ms; History ~17–22 ms; reopening with nine corrections ~2 min; local single-machine evidence only; production scalability not established |

**Deferred optional improvements**

| Item | Target |
|---|---|
| History shared-rank count O(page) | only if needed |
| Screener callbacks not run on non-Screener pages (page-load limitation) | later, separately approved |
| `inspect_stream` also comparing stored standing rows with the version hash (the F4 integrity tool does) | 6C.6 monitoring candidate |
| Minus-sign consistency (U+2212 on leaderboards, hyphen-minus on result cards) | cosmetic |

**Mandatory security, operational, hosting and release gates (all open)**

| Gate | Target |
|---|---|
| **S-07** CLI operator-authentication remediation (`round create/publish/lock/dev-open`, `account grant-role/revoke-role/grant-feature/revoke-feature/suspend/reinstate`) | **mandatory in 6C.6**; before any hosted deployment or Official activation |
| Genuine Beta finalisation under the real S-02 rule (earliest finalisation = max(settlement cutoff, last material change) + 24 h, database clock; wording clarified at 6C.6 Stage A) | 6C.6 Stage F |
| D-29 real weekly pool validation | before the Official series |
| D-36 account deletion workflow (retention and pseudonymisation) | before hosting real participants |
| D-38 Official activation requirements | before Official activation (**no Official stream is authorised**) |
| Hosted Supabase authentication acceptance | before hosting (Phase 10) |
| Relevant 6C.3 / 6C.4 backlog items (above and below) | as listed |

## Deferred backlog accepted at the 6C.4 closure (20 Nov 2026)

| Item | Target |
|---|---|
| S-07 follow-up: password check for the 6C.3 `round create / publish / lock / dev-open` commands | 6C.6 |
| Production scheduling (publish, lock, `results import --full`, settle, finalise), monitoring, alerting, admin interface | 6C.6 |
| `settle run` without `--confirm` (deliberate, idempotent) | documented; revisit in 6C.6 if wanted |
| Development time override only for settle and finalise (database clock elsewhere) | documented limitation |
| Hosted Supabase acceptance | Phase 10 |
| Championship recalculation after an owner reopening (S-06) | 6C.5 |

## Deferred backlog accepted at the 6C.3 closure (19 Nov 2026)

| Item | Target |
|---|---|
| Full historical entry browsing (My Challenge shows the current round and the most recent locked entry only) | 6C.5 |
| Periodic Screener reload latency (one slower request per `--ttl`, unchanged since before 6C.3) | 6D |
| Direct fixture URL selection (`/?fixture=<id>` typed in the address bar) | 6D |
| CLI tracebacks for expected operational errors | 6C.6 |
| Hosted Supabase compatibility testing (one skipped test) | Phase 10 |
| Freezing Your View at confirmation (T-21 Option B; needs a D-41 decision) | later decision |

Outstanding requirements, not blocking 6C.4: D-29 (validation on 6–8 real pools,
before Official Championship 1) and D-36 (retention policy, before launch).

Roadmap (updated 21 Nov 2026): 6C.5 leaderboards and championships (**complete**: Stages A–E,
F1–F4 and Stage G owner acceptance closed on 21 Nov 2026; merge and release not yet authorised) → 6C.6 administration, scheduling and monitoring (Phase 6C.6 Stages A–E and E.1a–E.1b formally accepted and closed. Next: Stage F — Integration and genuine Beta-week validation: design and readiness assessment delivered (`docs/architecture/phase6c6_stage_f_design.md`, SF-01–SF-14), awaiting owner approval; implementation not authorised. Stage G — Final acceptance, not started.) → 6D integration
testing and release → 7 Lucy AI football analyst and LiveKit → 8 European
competition coverage → 9 community badges and achievements → 10 production
deployment and private beta → 11 public launch and YouTube → 12 advanced
quantitative enhancements → 13 commercialisation and monetisation. **Private
mini-leagues are not on the MVP roadmap** (removed by the owner on 20 Nov 2026);
they may be reconsidered after launch, based on active users and feedback.
