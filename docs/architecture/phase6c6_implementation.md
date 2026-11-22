# Phase 6C.6 — Implementation record

Operational administration, scheduling and monitoring. Branch
`feature/phase-6c6-operations` (from the accepted 6C.5 closure `630e021`). Design:
[`phase6c6_design_proposal.md`](phase6c6_design_proposal.md) (approved with the
decisions in its §11). Decisions are also recorded in
[`../product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md).

## 1. Stage A: architecture review and design — closed (21 Nov 2026)

* **Deliverable:** the design proposal (`ee309d3`, CI run 83 passed): current-state
  assessment, S-07 remediation proposal, scheduler (reconciler) design, monitoring
  and recovery design, CLI-first administration, release-gate allocation, staged
  plan, risk register and decisions Q-01 to Q-14.
* **Baseline verified at closure:** 6C.5 closure `630e021` (CI run 82); proposal
  `ee309d3` (CI run 83); full regression baseline 1,682 passed, 0 failed, 0
  skipped; migration head `app_0007`; fingerprint
  `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
  `broad60-432-v1` and `points-150-75-v2` unchanged.
* **Owner decisions:** Q-01 to Q-14 as recorded in the design's §11 (Q-03 subject
  to a detailed security design; Q-04 phased, supervised publication in 6C.6; Q-07
  deferred to Stage F planning; Q-11 conditional).
* **Q-11 condition satisfied:** the terminology was reconciled (design §12). The
  implemented S-02 rule is authoritative and consistent across `settle/v1`, the
  6C.4 record, the 6C.5 specification and the code; "deadline + 24 h" in 6C.5
  summaries was imprecise wording, not a contradiction. Clarification notes were
  added to the living registers (Phase 6C plan outstanding-work table; Stage G
  handover §C.4). No rule changed.
* **Stage A closed** with the owner's approval of the design; Stage B (S-07) and a
  separate CI documentation-only work item are authorised; Stage C onwards is not.

## 2. Stage B: S-07 operator authentication remediation — **formally accepted (21 Nov 2026)**

Commit `8bf4d1a` (separate from the CI work item in §3). No competition rule,
settlement, scoring, configuration or migration change.

**Owner acceptance (21 Nov 2026).** Stage B is formally accepted on this evidence:
final application-code candidate `85b8608`, GitHub CI run 86 passed (1,731 passed,
0 failed, 0 skipped; all 13 browser tests ran; all 26 S-07 tests passed);
documentation-only head `607bf64`, CI run 87 passed in 26 s; migration head
`app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
`broad60-432-v1` and `points-150-75-v2`. Decisions at acceptance: **Q-03 remains
deferred** (no recovery command, secret, bypass or endpoint in Stage C; the manual
procedure in `docs/authentication.md` §6.1 stands); **CI timeout 40 minutes
ratified** (later changes outside an authorised scope need approval); the three
GitHub Actions Node-runtime warnings are a **separate maintenance item** (M-CI-1),
not part of Stage C. Stage C is authorised; Stages D–G are not.

### 2.1 What changed
| Command | Before (F2 finding) | After |
|---|---|---|
| `round create`, `round publish`, `round dev-open` | actor = the address in `--by-email`, no password; principal with no recency | `authenticate_operator` (password through Supabase Auth, roles from the database); the service authorises `round.publish` (T-12) before writing |
| `round lock` | `--by-email` actor, or `SYSTEM` when omitted | always an authenticated operator (`jobs.run`); **no `SYSTEM` path in the CLI** (Q-02: unattended locking only through the future scheduler) |
| `account grant-role`, `revoke-role` | actor UUID from `--by-email`; database owner check only; no T-12/T-14 | authenticated person; `authorize(roles.manage)` against the current database time (T-12 + **T-14 15 min**); database owner check kept |
| `account grant-feature`, `revoke-feature` | same | same with `entitlements.manage` (sensitive) |
| `account suspend`, `reinstate` | same; audit always recorded `operator` | same with `user.suspend` (sensitive); audit records the actor's real role (`owner`/`operator`) |
| `account bootstrap-owner` | no proof of control | refused before any prompt if an owner exists; otherwise the **target account's own password** is verified and must match `--email`; audit names the verified account (`actor_role = participant`, `verified: password`) |
| `--by-email` (all ten commands) | the identity | hidden option that only prints guidance ("use `--operator EMAIL`…") and exits 2 before any database access |

Related hardening found in the review:
* `permissions.authorize()` refuses any object that is not a `Principal`, so the
  `SYSTEM` actor can never satisfy a capability check (previously it would have
  failed with an attribute error rather than a deliberate refusal).
* `results.set_result_mode` (development result mode) accepted `SYSTEM`; it is a
  person's choice and outside the approved scheduler allowlist, so it is now
  person-only. All existing callers pass persons.
* `services.common.cli_principal` (a principal built from the database without a
  password) is no longer used by any product command; it is documented as a
  development/test helper and refused in the `production` environment. Remaining
  users are development tools on isolated databases.
* `settlement_cli.guarded()` gives every operator command the same handling:
  authentication/authorisation failures exit 3 with a user-safe message (no
  traceback — the F2 assessment noted a participant's refusal escaped as one),
  usage/refusals exit 2, nothing written.
* Reviewed and unaffected: every writing `results`, `settle`, `round
  finalise/finalise-check/reopen/invalidate`, `competition` and `dev` command
  already used `authenticate_operator`; read-only `round list/show`,
  `account list-privileged`, `dev scenarios`, `dev-championship presets/plan`
  need database access only.
* Services that accept `SYSTEM` explicitly after Stage B: `lock_round`,
  `import_results`, `settle_round`, `finalise_round` (each refusing time
  overrides for `SYSTEM`) — the approved Stage C allowlist. Corrections,
  withdrawal, alert resolution, invalidation and reopening refuse it.

### 2.2 Emergency owner recovery (Q-03): security analysis — **not implemented**
* **Threat model.** Assets: the owner role (roles, entitlements, reopening frozen
  championships). Adversaries: (a) someone with shell access to the application
  host and its environment (database URL, Supabase publishable key); (b) a
  compromised operator account; (c) someone who knows an owner's e-mail address.
  Recovery is needed only when **no active owner can act**: all owner accounts are
  suspended, deleted, or their provider accounts lost. A forgotten password is
  *not* a recovery case — Supabase's own password reset restores access without any
  application change.
* **Why a command cannot be both safe and useful today.** Any recovery command runs
  with the same credentials as adversary (a). An environment flag
  (`DISKI9_BREAK_GLASS=1`) is not authorisation — whoever can run the command can
  set it. Verifying the *target's* password stops impersonation of someone else
  (requirement met) but not self-escalation: adversary (a) with any onboarded
  account of their own could make themselves owner. That is a new privilege path
  beyond what the CLI offers today (although direct database writes by the
  application role remain possible for (a), as the F2 assessment recorded).
* **Design that would meet the requirements** (for owner decision): (1) recovery
  allowed only when **no active owner exists** (suspended owners do not count); (2)
  explicit authorisation by a **recovery secret** held offline by the owner: the
  host stores only its SHA-256 hash in the secret store
  (`DISKI9_OWNER_RECOVERY_SHA256`); the command asks for the secret at a hidden
  prompt (never arguments or environment), compares in constant time, and fails
  closed if no hash is configured; (3) the target's own password verified through
  Supabase Auth; (4) terminal only, `--confirm`, reason, one target; (5) a
  high-visibility audit record (`role.recovered_owner`) and, once monitoring
  exists (Stage D), a P1 alert; (6) after use, the owner rotates the secret. No
  migration is needed. Residual risk: a host administrator who also holds the
  offline secret can recover — which is the intended authority.
* **Status: deferred by the owner (Q-03 remains an open security decision).** No
  recovery command, recovery secret, authentication bypass, privileged endpoint or
  migration was introduced. Authenticated bootstrap (target's own password, refused
  once an owner exists) is retained.
* **Interim controls** (`docs/authentication.md` §6.1): ordered cases — password
  reset for a forgotten password; an active operator's authenticated `reinstate` for
  a suspended owner; `bootstrap-owner` when no owner role exists; and only otherwise
  a controlled manual database-administrator procedure: written owner authorisation
  and, where possible, two people; the target first proves control by signing in
  with their own password; a backup first; the administrator's own database account
  with the password at a hidden prompt or in a `0600` file (never on command lines,
  in shared environment variables, scripts, history, logs, chat or documents); the
  smallest change in one transaction with an `app.audit_log` row
  (`role.manual_recovery`, `procedure: manual_dba_recovery`); review afterwards and
  credential rotation if in doubt.
* **Safeguards a future recovery mechanism must provide** (for the owner's later
  decision): the six points above (no-active-owner restriction, offline recovery
  secret stored only as a hash and entered at a hidden prompt, target-password
  verification, terminal-only confirmation with a reason, a high-visibility audit
  record and P1 alert, secret rotation after use), plus rate limiting of failed
  attempts, tests that an environment flag alone never authorises, and no network
  or web route.

### 2.3 Tests (`tests/backend/test_backend_s07_remediation.py`, 26 tests)
The F2 characterisation tests were inverted into regression tests. Every case runs
the real CLI in a pseudo-terminal with real Supabase Auth passwords and real
PostgreSQL:
* former `--by-email` path for all ten commands → exit 2 with guidance, no password
  prompt, no row or audit change (10 parameterised cases);
* no terminal; wrong password; impersonation (another person's address with one's
  own password); a participant and an unknown address for round commands; an
  operator for owner-only role and entitlement changes; a suspended owner — all
  exit 3, nothing changed;
* valid owner grant/revoke role and entitlement (audit = verified owner, role
  `owner`); suspension by an operator and reinstatement by an owner (audit roles
  `operator`/`owner`); operator `dev-open` and `create` (audit = operator; beta
  series, never official); manual lock before the deadline refused, without an
  operator refused, after the deadline locked and attributed;
* `dev-open` refused in production and for non-`dev-` codes;
* bootstrap on an isolated database: `--confirm` required, wrong password refused,
  the target's password grants owner (audit = target, `verified: password`), then
  refused before any prompt once an owner exists;
* `SYSTEM`: locks through the service (audit `system`, no user); refused by
  `authorize` for **every** capability, by `create_round`, `set_result_mode`,
  `correct_result`, `reopen_round` and `invalidate_round`, with no row written;
* an unverified principal fails T-14 for every sensitive capability, and
  `cli_principal` is refused in production;
* a static sweep: neither command module uses `cli_principal`, an e-mail identity or
  the `SYSTEM` actor.

### 2.4 Documentation
`docs/backend.md`, `docs/authentication.md` and `docs/operator_settlement_cli.md`
describe the authenticated commands and the removed option;
`tools/e2e_6c5/README.md` notes that closed-stage scripts calling `--by-email`
non-interactively now stop at that step (no non-interactive password path exists by
design). Historical acceptance guides of closed phases are unchanged.

### 2.5 Verification
* **Level 1/2 (local, real PostgreSQL and the local Supabase Auth harness):** the
  S-07 file plus accounts, web authentication, authentication units, results,
  corrections and settlement-security suites — 199 passed; then every backend
  suite except the slow development-championship file — **619 passed**; then
  every app-level suite including the browser tests on the candidate commit
  `320e134` — **1,087 passed, 0 skipped** (7 min 55 s).
* **Level 3 (GitHub CI, exact candidate `320e134`, which contains `8bf4d1a`):**
  run 84 **passed** — **1,715 passed, 13 skipped** (22 min 09 s for the suite). The
  13 skips are browser tests (`playwright for node not available`); see §2.6.
* The S-07 commit message (`8bf4d1a`) says "25 tests"; the file has **26** (this
  record is correct; commit messages are not rewritten).
* Collected tests on the candidate: 1,728 = 1,682 (6C.5 baseline) − 6 (F2
  characterisation file, inverted) + 26 (S-07) + 26 (CI change scope).
* Lint and formatting clean; migration head `app_0007` (no migration);
  fingerprint `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`
  unchanged; no change under `src/diski9/challenge/` (rules, buckets, scoring) or
  `migrations_app/`.

### 2.6 Finding: GitHub CI did not run the browser tests (pre-existing; resolved in §2.8)
The CI job has never installed Node Playwright, so the 13 browser tests skip
there. Confirmed on the accepted 6C.5 closure run 82 (**1,669 passed, 13
skipped**), so this predates Stage B. Local full runs (with Node Playwright) have
always run them (6C.5 F4: 1,682 passed, 0 skipped). Consequence: "independent full
CI" has meant *full except browser tests*; the browser tests are evidenced locally.
For this candidate the app-level suites, browser tests included, were run locally
on `320e134`: 1,087 passed, 0 skipped. Every one of the 1,728 tests has therefore
passed on the candidate: the 13 browser tests locally, the development-championship
file (not run in the local Level 2 pass) on CI, and all others in both. Recommendation for owner approval:
install Node and the pinned Playwright Chromium in the CI job so Level 3 covers the
browser tests too (adds roughly 1–2 minutes; a CI change, not part of S-07).

### 2.8 Final verification (owner's Stage B acceptance gate, 21 Nov 2026)
* **Browser tests in GitHub CI (owner-approved), commit `85b8608`:**
  `package.json`/`package-lock.json` pin `playwright` 1.63.0 (the version the local
  runs use; test tooling, not an application dependency). In the full path only:
  `actions/setup-node` (Node 22, npm cache), `npm ci --ignore-scripts`, then
  `playwright install --with-deps --only-shell chromium` — the Chromium headless
  shell and its system libraries, nothing else. `DISKI9_REQUIRE_BROWSER=1` on the
  test step; `tests/test_browser_tooling.py` fails when the tooling is required but
  missing or Chromium cannot launch, so the browser tests cannot silently skip on
  CI. Package files always classify as full (two added change-scope cases).
  PostgreSQL, Supabase Auth, migration, lint and formatting steps unchanged; job
  name `checks` unchanged; no protection setting touched.
* **Timeout 30 → 40 min (measured):** the 13 browser tests take ~5 min locally and
  tooling setup ~1 min, on a job that took 22 min 50 s (run 84), leaving no margin
  at 30. Run 86 measured: tooling 45 s, test suite 22 min 58 s, job **24 min 34
  s**. 40 minutes ratified by the owner at acceptance.
* **Level 3 — GitHub CI run 86 on `85b8608` (the final application-code
  candidate): passed.** Scope step chose **full** ("6 non-documentation paths").
  **1,731 passed, 0 failed, 0 skipped** (1,731 collected): 1,728 previous + 2
  change-scope cases + 1 tooling guard. All 13 previously skipped browser tests ran
  and passed; PostgreSQL and real Supabase Auth integration suites, including the 26
  S-07 tests, passed; migration up/down/up and `app-db check`, lint and formatting
  passed.
* **Local (Level 2, working evidence):** the twelve browser-test files with the
  repository-pinned Playwright — 226 passed, 0 skipped; change-scope and tooling
  tests 29 passed; the guard fails as intended without Node.
* **S-07 verification outcome:** the eight acceptance points are covered by the
  S-07 suite (§2.3) and passed on CI: Supabase password authentication for all ten
  commands; `--by-email` changes nothing; T-12/T-14 enforced at the write against
  database time; roles and entitlements read from the database for the verified
  account; `SYSTEM` refused by every capability check and every human-only service;
  bootstrap needs the target's own password; audit attribution (actor and real
  role) checked; competition and settlement suites unchanged and passing.
* **Integrity:** migration head `app_0007`; fingerprint
  `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
  `broad60-432-v1` and `points-150-75-v2` unchanged (no change under
  `src/diski9/challenge/` or `migrations_app/` since `630e021`).
* The D-29 odds trial ended at its 15:00 UTC cutoff; its post-cutoff firing
  collected nothing and the scheduled task was disabled.

### 2.7 Residual risks and deferred items
* Emergency owner recovery is not implemented (§2.2): deferred by the owner; Q-03
  open; interim controls documented.
* **M-CI-1 (maintenance item, owner-recorded):** GitHub Actions warns that
  `actions/checkout@v4`, `setup-node@v4` and `setup-uv@v6` target the deprecated
  Node 20 runtime (forced to Node 24 today); updating action versions is separate
  from Stage C unless a compatibility or security blocker arises.
* Release gates remain open (no hosted deployment, Official activation, merge or
  release); Stage C onwards not authorised.
* `cli_principal` remains for development tools (non-production only).
* Closed-stage e2e scripts that used `--by-email` no longer run non-interactively.
* Direct database writes by anyone holding the application database credentials
  remain possible (unchanged by S-07; a hosting-phase concern: least-privilege
  roles and secret management).
* The CLI's T-14 check happens immediately after the password for account
  commands (no confirmation prompt), so the 15-minute window cannot lapse inside
  them; commands with a confirmation prompt re-check at the write (6C.4).

## 3. CI work item: documentation-only path and verification policy (separate)

Commit `320e134` (separate from S-07, owner-approved quick wins).
* `tools/ci/change_scope.py` decides from the **full change set** (push:
  `before..after`, every commit in the push; pull request: `base...head` since the
  merge base). Documentation-only = every changed path is Markdown outside code
  directories or a `docs/screenshots/` / `docs/benchmarks/` artefact, **and** none
  is read by code: `docs/legal/` (served by the app), `docs/research/` (app and
  test data) and `docs/methodology.md` (asserted by a test) always run the full
  suite. Mixed changes, new branches, manual runs and any detection failure are
  full. A guard test scans `src/` and `tests/` for `docs/` paths they open and
  fails if one is not excluded.
* `ci.yml`: full-history checkout; a scope step; on documentation-only changes
  the job runs lint, formatting and a relative-link check of the changed Markdown
  and skips the migration, Supabase Auth and test-suite steps (`if: scope !=
  'docs'`, so a missing value runs everything). The job name `checks` — the status
  check — is unchanged and always reports; no repository protection setting was
  touched.
* Tests: `tests/test_ci_change_scope.py` (26) — documentation and code examples,
  fail-safe events and git errors, real-history ranges (a known docs-only commit →
  docs; code and multi-commit pushes → full; a pull request judged since its merge
  base), the guard, and the link check.
* Verification: the workflow commit itself received the full suite (run 84: the
  scope step chose **full**; migration, Auth and test steps ran; link step
  skipped). The documentation-only path is demonstrated by the next
  documentation-only push (checkpoint report).
* `docs/development_testing.md`: Levels 1–3, escalation rules, the focused-test
  map and push discipline. Not done (separate approval): pytest parallelisation,
  per-worker databases, new dependencies, CI restructuring.

## 4. Stage C: scheduling and lifecycle orchestration — **formally accepted (21 Nov 2026)**

**Owner acceptance (21 Nov 2026).** Stage C is formally accepted on this evidence:
final application-code candidate `f89de9d`, GitHub CI run 89 passed (1,750 passed,
0 failed, 0 skipped; all 13 browser tests); documentation-only head `490f5e4`, CI
run 90 passed via the documentation-only path; migration head `app_0007`;
fingerprint `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
`broad60-432-v1` and `points-150-75-v2`. Decisions at acceptance: the provider
limits (10 per tick, 100 per rolling 24 hours, 60-minute refresh, 15–240-minute
back-off) are **accepted provisionally as defaults only** — not approved for live
Beta use; automated provider calls stay disabled until the subscription allowance,
account-wide consumption, competing workloads and a safety reserve are verified,
and caps may not be raised without approval. The advisory-lock approach is
accepted for now, but evidence of safe behaviour under realistic PostgreSQL
connection and timeout settings is required before hosted Beta (assessed in Stage
D, §5). Stage D is authorised; Stages E–G are not.

Authorised by the owner with Stage B's acceptance. Approach as approved in the
design (§3.2): a database-driven **reconciler** run by an external cron-style
trigger. Operator guide and configuration reference:
[`../operations_scheduler.md`](../operations_scheduler.md).

### 4.1 What was built
| Component | Purpose |
|---|---|
| `backend/jobs/config.py` | fail-closed environment configuration: off by default; explicit stream allowlist (`development`, `beta`); **`official` refused** by the parser and by `SchedulerConfig` itself (no setting can enable it); development refused in production; pause switch and pause file; provider calls a separate switch (off); per-tick and 24-hour request caps; refresh intervals; back-off bounds |
| `backend/jobs/reconciler.py` | `tick()` and `plan_tick()` (dry run). Per round, oldest deadline first, re-reading state after every step: lock → results → settle → (full re-check) → finalise, each through the existing service as `SYSTEM` |
| `backend/jobs/provider.py` | adapter over the existing API-Football client and by-ID fetch; the scheduler's allowance is set as the client's request budget |
| `jobs_cli.py` | `diski9 jobs tick [--dry-run]`, `diski9 jobs status`; exit codes 0 / 1 / 2 / 4; one line per step |
| `settlement.settle_round` | optional `job_run_id`, so scheduled settlement runs link to the scheduler's job record (no rule change) |

No migration (head `app_0007`), no new dependency, no daemon, no other database or
queue. Records use the existing `job_runs` (constrained by `app.run_guard`: only
status, finish time, request count and error change, so the outcome class is the
prefix of `error` for non-success rows) and `audit_log`.

### 4.2 Publication stays supervised
There is no publication or round-creation step and no configuration gate for one:
the scheduler package never references `publish_round`, `create_round` or
snapshot building (enforced by a static test). Draft rounds in an allowlisted
stream are reported as "awaiting operator publication". A future automatic
publication phase would add a new step behind its own approved gate; nothing
unused and reachable exists now.

### 4.3 System actor and authorisation
Lifecycle calls use the existing explicit `SYSTEM` actor only for `lock_round`,
`import_results`, `settle_round` and `finalise_round` (the approved allowlist; each
refuses time overrides for `SYSTEM`). The scheduler stores and uses no operator
password, Supabase session or token, never calls `authenticate_operator` or
`cli_principal`, and every other service still refuses `SYSTEM` (S-07 tests).
Audit records carry `actor_role = system` with no user; settlement runs carry
`trigger = scheduled` and the scheduler's `job_run_id`.

### 4.4 Lifecycle rules preserved
* **Lock:** only when the database clock has passed `deadline_at`; database
  triggers still refuse late entries; an already-locked round is a no-op.
* **Results:** only real rounds outside the development stream, only with provider
  calls on; the service's relevant-fixture, lead-time and stability rules
  unchanged; never invents results.
* **Settlement:** idempotent service; alerts raised by the service; blocking
  alerts never resolved automatically.
* **Finalisation:** only when `now ≥ earliest_finalisation` (S-02, unchanged) and
  no blocking alert; real rounds additionally need a full results re-check made
  after that time; `finalise_round` makes its final settlement run, refuses on any
  remaining condition and runs weekly publication and championship processing
  itself (no separate championship logic in the scheduler).
* **Missed ticks:** level-triggered; results that arrive after the settlement
  cutoff raise the existing late-notification alerts, which hold finalisation for
  an operator (demonstrated by test).

### 4.5 Concurrency, idempotency and failure handling
* One tick at a time: transaction-scoped advisory lock (`ops.try_job_lock`) held on
  a dedicated connection for the tick; a concurrent tick records `skipped` and
  exits 0. Services keep their own row locks and idempotency guards.
* Each service call is its own transaction; a crash leaves no half step. Steps left
  `running` are recorded as `failed (abandoned)` by the next tick.
* Failures: classified as retryable (provider/database errors), blocking (refused
  provider access, service refusals, blocking alerts) or deferred (budget, back-off,
  provider calls off). Exponential back-off per step and round from `job_runs`
  (15 → 240 min by default). A failure in one round never stops another; a failed
  lock, full re-check or final settlement stops that round for the tick.
* Exit status: 1 if anything retryable failed or the database was unavailable; 4 if
  only blocking conditions remain; 0 otherwise.

### 4.6 Provider budget (proposed limits for owner approval)
Per-tick cap 10, rolling 24-hour cap 100 (scheduler requests only), results refresh
60 min, settle refresh 60 min, back-off 15–240 min. An import that would exceed the
allowance is not started (`deferred: provider budget exhausted`); every request
sent, including failures and retries, is counted. The limits are conservative
proposals, not derived from a confirmed account quota (a round's import needs about
1–3 requests); they should be confirmed before the Beta round. No live provider
call was made in Stage C.

### 4.7 Tests (`tests/backend/test_backend_scheduler.py`, 19 tests)
Each test runs on its own freshly migrated database with mocked provider
responses and short real deadlines (frozen correction window 0 h where the test must
reach finalisation on the real clock; real rounds keep 24 h):
* configuration fails closed (default off, allowlist required, Official/unknown
  streams refused in the environment and in code, invalid numbers, development in
  production, pause switch and file); disabled and paused ticks change nothing;
* lock only after the real deadline, attributed to `SYSTEM`, never repeated;
* full lifecycle to final (lock, import, settle, full re-check before finalise,
  weekly results published, settlement runs linked to job runs), then repeated
  ticks with no duplicate effects;
* never before the S-02 earliest time (real 24-hour window); provider calls off
  hold real-round finalisation; a blocking alert holds finalisation (exit 4) and
  stays open;
* per-tick and 24-hour caps defer explicitly without sending requests; provider
  failure → retryable, back-off, recovery; refused access → blocking, with no
  provider text recorded;
* concurrent ticks (one runs, one skips); an interrupted tick is recorded as
  abandoned and resumes after back-off; missed ticks catch up in order, and an
  outage past the cutoff is held by late-notification alerts; a database error in
  one round does not affect another; database unavailable is reported (exit 1);
* Official and unlisted streams untouched; drafts stay drafts; a static check that
  the scheduler calls only the four approved services and never publication,
  creation, human-only services or operator sign-in; dry run writes nothing and
  calls no provider; CLI exit codes and cron output without credentials.

### 4.8 Verification
* Level 1/2 (local PostgreSQL and the local Supabase Auth harness): the scheduler
  file twice (19 passed each); then the scheduler, results, settlement (incl. ops
  and security), corrections, rounds, scenarios, S-07, operator CLI, migrations,
  authentication units, weekly results, championships, championship sequences,
  CI change-scope and championship-scoring suites — **329 passed, 0 skipped**.
* Lint and formatting clean; fingerprint
  `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`; migration
  head `app_0007`; no change under `src/diski9/challenge/` or `migrations_app/`.
* Level 3: see §4.10.

### 4.9 Outstanding risks and owner decisions (Stage C)
| Item | Note |
|---|---|
| Provider limits | defaults are proposals (§4.6); confirm against the account's daily allowance before enabling provider calls for the Beta round |
| Host (Q-07) | the trigger needs an always-on host for the genuine Beta week; examples documented for cron, systemd, launchd; decision before Stage F |
| Monitoring (Stage D) | exit codes and `job_runs` give the evidence; no notification yet, so a blocked round (exit 4) or repeated failures are visible only in logs and `jobs status` |
| Football store | the scheduler records competition evidence only; it does not refresh the analytics football store (the manual `--update-football-store` option remains) |
| Pending predictions | a round whose predictions stay pending after the cutoff is retried at the refresh interval (with a full re-check each time for real rounds), bounded by the request caps |
| Idle-in-transaction limits | the tick lock holds one connection in an open transaction for the tick; a hosted database with a short `idle_in_transaction_session_timeout` would need it raised above the longest tick (seconds today) |
| Database credential | anyone holding the application database credential can still write directly (unchanged; hosting phase) |

### 4.10 Level 3 (GitHub CI)
* **Final application-code candidate `f89de9d`, CI run 89: passed.** The scope step
  chose **full** (10 non-documentation paths). **1,750 passed, 0 failed, 0
  skipped** (1,731 at Stage B + 19 scheduler tests), all 13 browser tests included;
  migration up/down/up and `app-db check`, real Supabase Auth integration, lint and
  formatting passed. Test suite 24 min 32 s; job 26 min 0 s (within the ratified
  40-minute timeout).
* Documentation after the candidate (this record, plan status) uses the
  documentation-only path.

## 5. Stage D: operational monitoring, alerts and recovery — **formally accepted and closed (21 Nov 2026)**

**Closure (21 Nov 2026).** With the owner's acceptance of the scheduler-locking
remediation (§6), Stage D is closed for operational readiness. Monitoring
acceptance below is unchanged.

**Owner decision (21 Nov 2026).** The Stage D monitoring, alerting and recovery
deliverables are formally accepted on this evidence: final application-code commit
`45faeac`, GitHub CI run 92 passed (1,765 passed, 0 failed, 0 skipped; all 13
browser tests); documentation-only head `f4e0447`, CI run 93 passed; migration head
`app_0007`; fingerprint unchanged; `broad60-432-v1` and `points-150-75-v2`. Accepted
and to remain unchanged unless a directly related defect is found: `ops status`,
`ops check`, `ops jobs`, the severity thresholds, read-only monitoring, the
disabled-by-default webhook with de-duplication and retry, the runbook and the
performance safeguards. **Stage D is not closed for operational readiness until
the scheduler-locking defect (§5.5) is remediated**; the R1–R6 remediation is
authorised (§6), with crash- and concurrency-safe provider-budget accounting. Stage
E is not authorised.

Authorised with Stage C's acceptance. Reference:
[`../operations_monitoring.md`](../operations_monitoring.md); recovery runbook:
[`../operations_runbook.md`](../operations_runbook.md).

### 5.1 What was built
| Component | Purpose |
|---|---|
| `backend/ops/config.py` | thresholds (deadline-, cutoff- and S-02-relative) and notification settings from the environment; fail closed; webhook URL treated as a secret (never in `repr`, output or the database); https only (http only for localhost) |
| `backend/ops/snapshot.py` | one bounded, read-only snapshot: database (server, schema vs expected head, required tables, query time), scheduler heartbeat (last and last successful tick), failures, running and abandoned steps, per-step failure streaks, rounds with their lifecycle position, blocking alerts, settlement failures, provider use, light integrity (Official anomalies, final rounds without weekly results) |
| `backend/ops/checks.py` | `evaluate()`: findings with INFO / WARNING / CRITICAL and stable fingerprints; `deep_findings()`: the existing `inspect_stream` for every open stream (on demand only) |
| `backend/ops/notify.py` | one webhook, off by default; new / ongoing / resolved with de-duplication, escalation, re-notification and retry, using `job_runs` (`job = 'ops.notify'`) as the ledger — no migration |
| `backend/ops/history.py` | read-only recent job runs with outcome class and settlement-run links; a round's audit records |
| `ops_cli.py` | `diski9 ops status [--json]`, `ops check [--json] [--deep] [--notify]` (exit 0/1/2), `ops jobs [...]` |

No migration (head `app_0007`), no new dependency, no index added, no change to the
scheduler, the services or any rule. Monitoring is read-only apart from the
notification ledger and runs separately from `jobs tick`.

### 5.2 Severity model and thresholds
As documented in `operations_monitoring.md`: INFO for intended states (disabled or
paused automation, provider calls off, drafts awaiting publication, normal
progress); WARNING for delays and repeated retryable problems (tick 15 min late, 3
step failures in a row, stuck or abandoned steps, lock 15 min late, no settlement 6
h after the cutoff, eligible 6 h without finalisation, blocking alerts, budget ≥ 80
%); CRITICAL for integrity or blocked operations (no tick for 60 min while
automation should run, 6 failures in a row, lock 60 min late, settlement 24 h late,
eligible or blocked 24 h past the S-02 time, Official-stream activity, material
integrity finding, database unreachable or wrong head). All thresholds are
configurable; disabled or paused automation is never an outage.

### 5.3 Notifications
Disabled by default and inactive without an explicit `DISKI9_OPS_WEBHOOK_URL`; no
real destination configured (activation needs Q-08 approval). Tested only against
a local webhook on 127.0.0.1: INFO never sent; duplicates suppressed;
re-notification after the interval; escalation; resolved once; reappearance; HTTP
500 and refused connections recorded and retried after the interval; no secret in
payloads or ledger rows. The ledger lives in the database, so no notification is
sent while the database is unreachable (the check still exits 2; the trigger's own
failure reporting covers it).

### 5.4 Recovery
`operations_runbook.md`: scheduler not running, re-running a tick, pause/resume,
abandoned or stuck steps, blocking alerts, provider budget or failures, verifying
catch-up, rounds that need an operator, database problems, integrity findings. No
force-finalise, no automatic alert resolution, no privileged shortcut; every manual
competition action uses the existing authenticated commands.

### 5.5 Scheduler locking review (§9 of the authorisation) — **defect demonstrated**
Method: `tools/ops/scheduler_lock_probe.py` runs the **accepted, unchanged** Stage C
reconciler on a throw-away database with a fake provider of chosen latency.

| Question | Finding |
|---|---|
| How long is the lock transaction open? | The whole tick: measured 0.25 s (1 round), 0.76 s (5 rounds), 5.8 s (5 rounds, 1 s provider latency). Worst case from the client settings (30 s timeout, 3 retries, 2-4-8 s back-off, up to 10 requests per tick): about 134 s per request and over 20 minutes per tick, plus database lock and statement waits |
| Provider latency, retries, rounds | Duration grows linearly with provider calls; the holder connection sits *idle in transaction* throughout |
| `idle_in_transaction_session_timeout` | With 2 s and a 5 s provider call, PostgreSQL **terminated the holder connection while the tick was still working**. A second tick then acquired the lock and **ran concurrently**; it marked the first tick's live job rows as **abandoned**; the first tick then failed with an exception (`InternalError`) when completing its records. Competition data stayed correct (each service has its own row locks and idempotency), but job records, budget accounting and provider-request limits are not reliable under overlap, and a traceback escapes |
| Can the connection be terminated mid-work? | Yes (above); also by `pg_terminate_backend`, failover or network drops; the tick does not notice until it finishes |
| Session-level advisory lock | Held on a connection that is idle **outside** a transaction, it survived the same 2 s timeout and a second session could not acquire it |
| Connection pooling | The current transaction-scoped lock works through a transaction pooler (the transaction pins the server connection) but is exactly what idle-in-transaction limits kill. A session-level lock is **not** safe through a transaction pooler (Supabase transaction mode on port 6543, PgBouncer transaction mode): the server session can be reassigned. It needs a direct or session-mode connection |

**Remediation proposal (not implemented; owner approval requested before changing
the locking architecture):**
* **R1** Hold a session-level advisory lock (`pg_try_advisory_lock`) on a dedicated
  autocommit connection that is never in a transaction; release explicitly at the
  end (and implicitly if the connection dies). No database timeout needs weakening.
* **R2** Require a direct or session-mode connection for the scheduler: refuse to
  tick when `DISKI9_APP_POOLER_MODE=transaction` unless a separate session-mode
  `DISKI9_JOBS_DATABASE_URL` is configured.
* **R3** Detect lock loss: before each step (and before completing records) verify
  the lock is still held (`pg_locks` for the holder's backend); if not, stop starting
  work, record `lock lost`, exit 1. Enable TCP keepalives on the holder.
* **R4** Mark steps abandoned only when the tick that started them is provably gone:
  record the holder's backend PID in the tick row's arguments and treat a `running`
  step as abandoned only if that PID is no longer in `pg_stat_activity`.
* **R5** Bound a tick: a time budget after which no new step starts (for example
  4 minutes), and scheduler-specific provider client settings (shorter timeout,
  fewer retries) so one tick cannot run for tens of minutes.
* **R6** Make lock release and connection errors at the end of a tick non-fatal
  (reported, never a traceback).
* Alternative considered: a lease row with an expiry renewed by heartbeat (works
  through any pooler) — needs a migration and more moving parts; not recommended
  unless a transaction pooler must be used.
* Tests to accompany R1–R6: the probe's timeout scenario must show no overlap and no
  false abandonment; pooler refusal; lock loss stops the tick.

Current exposure: none locally (no idle-in-transaction limit; one trigger). Before
hosted Beta, R1–R6 (or the alternative) are needed, or hosted settings must be shown
to be safe; the owner has asked not to rely on weakening timeouts.

### 5.6 Performance
Light checks use indexed or time-bounded queries. Measured: 40–47 ms for
status/check and under 50 ms for job history with 150,000 `job_runs` rows (test);
read-only on the F4 datasets, light checks 31 ms (1,000 players, 11,401 entries)
and 22 ms (10,000 players, 110,750 entries); the deep inspection 1.2 s and 11.0 s —
hence on demand or daily, never per tick (a test fails if a light check runs it).
No index added; `settlement_runs (round_id)` and `audit_log (job_run_id)` lack
indexes for the per-round queries used, acceptable at current volumes.

### 5.7 Tests (`tests/backend/test_backend_ops.py`, 15 tests)
Synthetic-snapshot unit tests for the severity model (scheduler states and
heartbeat, lifecycle thresholds and categories, provider budget, integrity,
database head and tables, failure streaks) and configuration (off by default,
webhook hidden, invalid values refused); and on isolated PostgreSQL databases:
status reflecting a real lifecycle and staying read-only; failed, abandoned, stuck
and blocked rounds; deep integrity on demand only (light checks never inspect);
job history with settlement links and audit records; notifications disabled by
default, de-duplication, re-notification, escalation, resolution, delivery
failures; static check that monitoring performs no lifecycle or human-only action;
an interrupted tick visible to `ops check` and recovery that never finalises before
S-02; CLI status/check/jobs, JSON, deep, database unavailable (no traceback, no
password), invalid configuration; bounded timings with 150,000 job runs.

### 5.8 Verification
* Level 1/2 (local PostgreSQL and the local Supabase Auth harness): the ops file (15
  passed) and then ops, scheduler, results, settlement (incl. ops and security),
  corrections, rounds, S-07, operator CLI, migrations, authentication units, weekly
  results, championships, integrity and CI change-scope suites — **347 passed, 0
  skipped**.
* Lint and formatting clean; fingerprint
  `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`; migration
  head `app_0007`; no change under `src/diski9/challenge/`, `migrations_app/`, the
  scheduler (`backend/jobs/`) or the services.
* Level 3: §5.10.

### 5.9 Outstanding risks and owner decisions (Stage D)
| Item | Note |
|---|---|
| **Scheduler locking (defect, §5.5)** | demonstrated under `idle_in_transaction_session_timeout`; **remediated (R1–R6, §6) and accepted by the owner (21 Nov 2026)** |
| Notification destination (Q-08) | no real webhook configured; provider, destination and activation need approval |
| Database-down alerts | no webhook while the database is unreachable (ledger in the database); rely on the trigger's failure reporting, or approve a small file-based state for that one case |
| Provider limits | still provisional; live calls off (Stage C decision) |
| Host (Q-07) | the triggers for `jobs tick` and `ops check --notify` need an always-on host |
| Abandoned-step warnings | remain visible for 24 h after the event (history), by design |
| Index review | `settlement_runs (round_id)` and `audit_log (job_run_id)` unindexed for the queries used; fine now, review if volumes grow greatly |
| Database credential | direct writes by anyone holding it (unchanged; hosting phase) |

### 5.10 Level 3 (GitHub CI)
* **Final application-code candidate `45faeac`, CI run 92: passed.** Scope **full**
  (11 non-documentation paths). **1,765 passed, 0 failed, 0 skipped** (1,750 at
  Stage C + 15 ops tests), all 13 browser tests included; migration up/down/up and
  `app-db check`, real Supabase Auth integration, lint and formatting passed. Test
  suite 24 min 54 s; job 26 min 20 s (within the 40-minute timeout).
* Documentation after the candidate uses the documentation-only path.

## 6. Stage D remediation: scheduler locking (R1–R6) — **formally accepted (21 Nov 2026)**

**Owner acceptance (21 Nov 2026).** The remediation is formally accepted on this
evidence: final application-code commit `0f3c0b1`, GitHub CI run 95 passed (1,778
passed, 0 failed, 0 skipped; all 13 browser tests); documentation-only head
`f5458a3`, CI run 96 passed; migration head `app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`; `broad60-432-v1`
and `points-150-75-v2`. Accepted and not to be reopened without a material defect:
the session-level tick lock on a dedicated connection outside transactions; the
direct/session-mode connection requirement and transaction-pooler refusal; unique
tick ownership checks; safe lock-loss handling; conservative abandonment (young
uncertain work indeterminate, old work recoverable after 20 minutes); the 240-second
new-step budget; bounded provider timeout and retry; safe cleanup; and the pre-send
provider request ledger (crashes conservatively consume budget). **Standing
condition:** the 20-minute abandonment threshold must always exceed the maximum
possible in-flight duration (provider, database and cleanup waits); any change to
these limits requires review. Provider limits stay provisional, live calls off;
Q-07 and Q-08 remain open. **Stage D is closed.**

Authorised with the Stage D monitoring acceptance. Code: `backend/jobs/locking.py`
(new), `backend/jobs/reconciler.py`, `backend/jobs/provider.py`,
`backend/jobs/config.py`, `jobs_cli.py`; monitoring integration in
`backend/ops/snapshot.py`, `checks.py` and `ops_cli.py`. No migration, no lease
table, no new dependency; services, rules and S-02 unchanged.

### 6.1 Original defect and root cause
The Stage C tick held a **transaction-scoped** advisory lock on a connection whose
transaction stayed open for the whole tick, including provider calls. With
`idle_in_transaction_session_timeout = 2 s` and a 5 s provider call, PostgreSQL
terminated that connection mid-tick (§5.5): the lock vanished, a second tick ran
concurrently, marked the first tick's live steps abandoned (it treated every
`running` scheduler row as dead once it held the lock), and the first tick then
failed with an exception. Ownership was implied by the lock alone and was never
re-checked; abandonment had no evidence beyond "I hold the lock now".

### 6.2 Implemented fix
| | Implementation |
|---|---|
| **R1** session lock | `TickLock`: `pg_try_advisory_lock` (same key format as `ops.try_job_lock`) on a dedicated connection (`NullPool`, `AUTOCOMMIT`, never in a transaction, TCP keepalives, statement timeout); explicit `pg_advisory_unlock` at the end; released by PostgreSQL if the connection dies. No transaction is open while waiting for the provider. Single active tick preserved |
| **R2** connection mode | `lock_url()`: `DISKI9_JOBS_DATABASE_URL` (direct or session mode, `DISKI9_JOBS_DATABASE_MODE`) or else the application URL, refused when `DISKI9_APP_POOLER_MODE=transaction`; port 6543, `pgbouncer=true` and mode `transaction` refused (`unsafe_connection`, exit 2, nothing done, no URL in messages). Runtime validation: at acquisition and at every check the same server backend must hold the lock (catches unlabelled poolers); a manual validation procedure is documented. Application connectivity and timeouts unchanged |
| **R3** ownership | unique run token per tick (`application_name = diski9-tick:<token>`, stored in the tick row with the holder backend PID and OS PID); `TickLock.verify()` (same backend + lock visible in `pg_locks`) before every lifecycle step, before every provider request and before completing the tick record. On loss: `LockLost` → no further step or request, the in-flight step's record is completed, the tick row is recorded `lock lost`, status `lock_lost`, exit 1; never re-acquired in the same run. Services keep their own transactions, row locks and idempotency |
| **R4** abandonment | `classify_running()`: another tick's `running` rows are abandoned only when that tick started more than `abandon_after` (20 min) ago, which exceeds the maximum live tick duration (R5); younger → **indeterminate**: the new tick records `skipped: indeterminate …`, does no lifecycle work, exits 0, and monitoring reports it. A tick interrupted in-process records its own steps `abandoned: interrupted (…)`. A tick no longer marks rows merely because the previous lock connection disappeared |
| **R5** bounded duration | tick budget 240 s (no new step after it; remaining work next tick, `deferred`); scheduler provider client 10 s timeout, 1 retry; per-tick request cap 10 → one step ≤ 10 × 22 s; database statements bounded by 15 s statement and 5 s lock timeouts; worst case ≈ 8 min < 20 min abandonment threshold. A second invocation while a tick runs skips (`busy`) |
| **R6** cleanup | `TickLock.release()` never raises (a failure becomes a note; the closed connection releases the lock); bookkeeping after lock loss is best effort and never replaces the original outcome; an in-process interruption is recorded and re-raised; no traceback for lock loss, unavailability or unsafe connections |

### 6.3 Provider-budget accounting under concurrency
Advisory locking alone could not make accounting crash-safe (requests were summed
from step records written *after* the provider call). Now every request — retries
included — is recorded **before it is sent** as one `job_runs` row
(`job = 'scheduler.provider'`, `api_requests = 1`) in a short transaction that takes a
transaction-level advisory lock (`diski9:scheduler.provider_budget`) and re-checks
the per-tick and rolling 24-hour caps. The real client is hooked through its
pre-request rate-limiter call, so each attempt passes `reserve()` first; the fake
providers in tests do the same. Verified: concurrent callers cannot exceed a cap
(12 threads, cap 5 → exactly 5); a crash after sending keeps the count; failed and
retried requests are counted; abandoned or indeterminate steps do not make requests
"unused"; caps hold across ticks and crashes. Limitation (documented): the count is
conservative — a request recorded and then not sent (crash between) is counted.
Monitoring and `jobs status` read the ledger. Limits unchanged (10 per tick, 100 per
24 h, 60-minute refresh, 15–240-minute back-off); automated provider calls remain
off.

### 6.4 Reproduction and post-fix evidence (`tools/ops/scheduler_lock_probe.py`)
| Scenario | Before (Stage D, §5.5) | After |
|---|---|---|
| idle-in-transaction 2 s, provider 5 s, second tick meanwhile | second tick **completed** (overlap); first tick's live rows marked abandoned; first tick raised `InternalError` | second tick **busy**; first tick completed (exit 0); no abandonment; 1 results step; ledger 1 = requests sent 1 |
| lock holder terminated during a 3 s provider call, second tick meanwhile | (not run) | first tick `lock_lost` (exit 1, recorded); second tick `indeterminate` (exit 0, no work); no abandonment; 1 results step; ledger 1 = sent 1 |
| transaction-pooler URL (port 6543) | (accepted) | `unsafe_connection`, exit 2, no secret in the message |
| tick duration | 0.25 / 0.76 / 5.8 s | 0.27 / 0.87 / 5.9 s (1 round; 5 rounds; 5 rounds with 1 s provider latency) |

### 6.5 Tests (`tests/backend/test_backend_scheduler_locking.py`, 13 tests)
Session lock held on an idle connection outside any transaction and released;
the original defect scenario (2 s idle-in-transaction limit, 5 s gated provider,
second tick) with no overlap, no false abandonment, no duplicate step and correct
ledger; two and four competing ticks (one owner); lock-holder termination mid-tick
(controlled `lock_lost`, indeterminate second tick, in-flight step recorded, no
follow-on step, monitoring shows indeterminate then lock lost, a later tick
recovers); genuinely abandoned (old) versus uncertain (young) killed ticks; tick
budget exhaustion and continuation; configuration bounds; cleanup failure reported
not raised; transaction-pooler refusal, direct/session acceptance and backend-change
detection; concurrent reservations; requests surviving crashes, failures and
abandonment; real client retries each recorded before sending and nothing sent once
the cap is reached (mock transport); monitoring distinguishing a long tick from an
outage (tick active INFO, overrunning CRITICAL). The Stage C and Stage D suites were
updated only where semantics changed by design (provider `fetch(ids, reserve)`;
an in-process interruption now records its own steps as abandoned; budget seeded
through the ledger).

### 6.6 Verification
* Level 1: the locking file twice (13 passed each); scheduler and ops files (34
  passed) after the change.
* Level 2 (local PostgreSQL and Supabase Auth harness): locking, ops, scheduler,
  results, settlement (incl. ops and security), corrections, rounds, S-07, operator
  CLI, migrations, authentication units, weekly results, championships, integrity,
  concurrency, CI change-scope and API client suites — **399 passed, 0 skipped**.
* Probe re-run on the remediated code (§6.4). Lint and formatting clean;
  fingerprint `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
  migration head `app_0007`; no change under `src/diski9/challenge/`,
  `migrations_app/` or the services.
* Level 3: §6.8.

### 6.7 Remaining risks
| Item | Note |
|---|---|
| Unlabelled poolers | detected at runtime by the backend check, but only once a tick runs; validate by hand before relying on a new host (documented) |
| Conservative accounting | a crash between recording and sending counts an unsent request |
| Indeterminate window | after a killed process, lifecycle work waits up to 20 minutes (abandonment threshold); monitoring shows it |
| Abandonment threshold assumption | relies on the bounded tick (budget, provider timeout/retries, database timeouts); raising those bounds requires raising `DISKI9_JOBS_ABANDON_AFTER_MINUTES` |
| `idle_session_timeout` | a server-side idle-session limit shorter than a tick would end the lock connection: the tick then stops safely with `lock lost` (no overlap), but hosts should not set one below the tick budget |
| Provider limits, host, webhook destination | unchanged decisions (provisional limits, Q-07, Q-08) |

### 6.8 Level 3 (GitHub CI)
* **Final application-code candidate `0f3c0b1`, CI run 95: passed.** Scope **full**
  (13 non-documentation paths). **1,778 passed, 0 failed, 0 skipped** (1,765 at
  Stage D + 13 locking tests), all 13 browser tests included; migration up/down/up
  and `app-db check`, real Supabase Auth integration, lint and formatting passed.
  Test suite 28 min 35 s; job 29 min 34 s — within the ratified 40-minute timeout,
  but the margin has narrowed to about 10 minutes (the suite took 24 min 52 s in run
  92; runner speed varies). No timeout change is proposed now; the trend is noted
  for owner awareness.
* Documentation after the candidate uses the documentation-only path.

## 7. Stage E: operational administration and remaining backlog — **formally accepted and closed (21 Nov 2026)**

**Owner acceptance (21 Nov 2026).** Stage E is formally accepted on this evidence:
final application-code commit `c49de86`, GitHub CI run 99 passed (1,797 passed, 0
failed, 0 skipped; all 13 browser tests); documentation-only commit `8ed731b`, CI
run 100 passed; migration head `app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
`broad60-432-v1` and `points-150-75-v2`; no unauthorised change to competition
rules, security boundaries or scheduler behaviour. Confirmed: `round readiness`
stays password-free, including the candidate fixture-pool information, under the
verified data-exposure restrictions (§7.5a). The publication fingerprint safeguard
is accepted; **standing requirement: any future publication entry point must
publish exactly the validated and confirmed snapshot.** **Stage E is complete.**
Next: **Stage E.1 — Automated Draft Preparation**, beginning with a separately
authorised design (competition-week definition, fixture window, preparation
schedule, provider requirements, duplicate prevention, failure handling, human
publication approval). Stages E.1 (implementation), F and G are not authorised.

Authorised with the Stage D closure (decision register, 21 Nov 2026). Operator
guide: [`../operations_guide.md`](../operations_guide.md). Code:
`backend/services/rounds.py` (shared publication check, `publication_readiness`),
`backend/ops/inspect.py` and `backend/ops/audit.py` (new, read-only),
`admin_cli.py` (new, presentation and `audit list`), `cli.py` (`round readiness`,
`round inspect`, publish confirmation, argument checks), `settlement_cli.py`
(`guarded`: one-line configuration and connectivity errors). No migration, no new
dependency, no new privileged capability, no new kind of state change; services,
rules, S-02, the scheduler and its locking are unchanged.

### 7.1 Stage D closure
Confirmed before Stage E work: branch `feature/phase-6c6-operations` clean and equal
to the remote at `f5458a3`; closure recorded in `7c5d295` (documentation only: §5–§6
of this record, the decision register and the plan).

### 7.2 Scope matrix (backlog reconciliation)
| Area | Already implemented (reuse; document) | Gap addressed in Stage E | Deferred / needs approval |
|---|---|---|---|
| Round administration | `round list/show/create/publish/lock/dev-open`, `finalise-check/finalise/invalidate/reopen` (S-07 authenticated) | **`round readiness`** (read-only preview of every publication check plus pool, bucket, freshness and data-quality evidence); **publish shows the summary and requires typing the round code**; `--code` required with a clear message | automated draft creation (new state change by the scheduler: needs a design decision); web operator console (original 6C.6 plan; superseded by the CLI design, needs approval) |
| Investigation | `settle status`, `results show`, `settle alerts`, `ops jobs --round`, `competition status/verify` | **`round inspect`**: one report composing those sources plus entries, championship assignment and weekly-results revision | — |
| Recovery | `results import [--full]`, `settle run`, `settle resolve-alert`, `results correct/withdraw-correction`, `round finalise`, `competition repair/backfill`, `jobs tick [--dry-run]`, pause file, `ops check --deep` | documented in the operator guide; **no new state-changing command was needed** | force-finalise (excluded); automatic alert resolution (excluded) |
| Audit | audit records written by every service; per-round audit in `ops jobs --round` | **`audit list`** behind the existing, previously unused `audit.view` capability (the "audit list" item of the approved Stage A design) | acknowledgement table `ops_alerts` (M1, migration: Q-09) |
| Accounts (S-07) | bootstrap, grant/revoke role and feature, suspend/reinstate, `list-privileged` | arguments checked **before** the password prompt (`--role`, `--feature`, inapplicable options refused); message punctuation | emergency owner recovery (Q-03, deferred); account deletion (D-36) |
| CLI errors (6C.3 backlog) | `guarded` for service, auth and usage errors | missing/invalid database configuration and unreachable or busy database now give **one line** (never the URL or password) instead of a traceback | — |

### 7.3 Outstanding backlog classification
| Item | Classification | Owner / proposed stage | Note |
|---|---|---|---|
| CLI tracebacks for expected errors (6C.3) | **1 Required for Stage E — done** | — | §7.2 |
| Audit viewer (6C.6 design, Stage E) | **1 — done** (`audit list`) | — | read-only, `audit.view` |
| Publication readiness evidence | **1 — done** | — | reuses the existing checks |
| ML-01 Match Lab stale-adjustment race | **2 Required before private Beta** | owner authorisation of a focused fix; proposed Phase 6D (or a dedicated maintenance item) | not touched in Stage E |
| D-36 account deletion (retention, pseudonymisation) | **2** and **5 Requires approval** | owner: security and data-retention design first; before hosting real participants | not implemented |
| Hosted Supabase authentication acceptance | **4 Phase 10 / hosting** | — | one skipped hosted test |
| Host for triggers (Q-07); webhook destination (Q-08) | **5 Requires approval**; needed for Stage F's real week | owner | unchanged |
| Provider caps (provisional) and live provider calls | **5 Requires approval** | owner, after confirming the API-Football allowance | live calls off |
| Genuine Beta finalisation on the real clock (S-02) and backup/restore drill | **3 Stage F** | — | calendar time |
| D-29 real weekly pool validation | **2** (before the Official series) — evidence only | Stage F onwards, from real weeks | the trial is **not** restarted; `round readiness --json` can record each week's pool evidence without provider calls |
| D-38 Official activation | **5 Requires approval** | owner | Official stays disabled |
| Automated draft preparation (scheduler creating drafts) | **5 Requires approval — scheduled as Stage E.1 (owner, 21 Nov 2026)** | Stage E.1, after Stage E and before Stage F: approved design first (competition week, fixture window, scheduling, provider requirements, duplicate prevention), then separate implementation authorisation | goal: fully automated weekly operation with human publication approval during the initial Beta; readiness can serve as its validation step |
| Database-down notification without the database (file state) | **5 Requires approval** | owner (Stage D option) | trigger reporting meanwhile |
| `ops_alerts` acknowledgement table (M1) / per-stream automation settings in the database (M2) | **5** (migration) | owner | not proposed now |
| Index review (`settlement_runs.round_id`, `audit_log.job_run_id`) | **4 Phase 6D** | — | fine at current volumes |
| CI runtime margin (~10 min under the 40-minute timeout) | **4 Phase 6D** watch item | owner if a change is needed | no change made |
| `settle run` without `--confirm`; development time override only for settle/finalise | documented limitations (6C.4) | — | unchanged |
| Screener reload latency; direct fixture URL; freezing Your View (D-41) | **4 Phase 6D / later decision** | — | unrelated to administration |

### 7.4 New and changed commands
| Command | Auth | Writes | Notes |
|---|---|---|---|
| `round readiness --code C [--json]` | none (like `round show`; reads the football store and the round) | nothing | real draft rounds only; exit 0 ready, 1 not ready, 2 usage |
| `round publish --code C --operator E` | password (`round.publish`), unchanged | as before | builds the snapshot once, prints its readiness summary, requires typing the round code and publishes exactly that snapshot (`expected_fingerprint`); a NOT READY snapshot goes straight to the service, which refuses and records the attempt as before |
| `round inspect --code C --operator E` | password, `jobs.run` (as `settle status`); **refuses `SYSTEM`** | nothing | settlement figures computed in a rolled-back transaction |
| `audit list [--round C] [--action-prefix P] [--since T] [--limit N] [--json] --operator E` | password, `audit.view`; **refuses `SYSTEM`** | nothing | usernames or `SYSTEM`, round codes; no emails, payloads or request IDs; ≤ 200 rows |
| `account grant-role/…/reinstate` | unchanged | unchanged | argument checks moved before the password prompt |
| all `guarded` commands | unchanged | unchanged | one-line errors: database URL missing/invalid (exit 2), unreachable or busy (exit 1); `--code` required (exit 2) |

`publish_round` and `publication_readiness` share one function
(`_evaluate_publication`) for every check, in the original order, so the preview
cannot disagree with publication (tested for the ready case and three refusals).

### 7.5 Security and audit verification
* No new capability: `round inspect` uses `jobs.run` (as the existing settlement
  reports), `audit list` the existing `audit.view`; both refuse the scheduler's
  `SYSTEM` actor explicitly (the shared `actor_id` helper would otherwise accept it)
  and participants. `round readiness` reads only what `round show` and the football
  store already expose and writes nothing.
* Password authentication, current database roles, recency rules and audit
  attribution unchanged; `--by-email` still refused with guidance (also on `audit`).
* Publication: the human approval step is stronger (explicit confirmation of the
  exact snapshot); refusals are still recorded; the audit record of a CLI
  publication names the verified operator (tested).
* Error messages never contain the database URL or password (tested with a
  password-bearing URL).

### 7.5a Owner decisions at review (21 Nov 2026) and their verification
**Publish confirmation — approved**, on condition that the validated snapshot is
exactly the snapshot published (no time-of-check/time-of-use gap). How this holds:
* `round publish` builds the snapshot **once**; the same object is validated
  (`publication_readiness`), shown, confirmed and passed to `publish_round`. It is
  never rebuilt (tested: the builder is called exactly once and the service
  receives that very object).
* `RoundSnapshot`, `RoundFixture` and `ChallengeOutcome` are frozen dataclasses
  holding tuples, so the approved object cannot change between check and use.
* The CLI also passes the approved fingerprint (`expected_fingerprint`, added in
  this review); `publish_round` refuses any other snapshot ("The snapshot differs
  from the one approved; nothing was published", recorded as a refused attempt;
  tested). The fingerprint covers every outcome's price, probabilities, bookmaker
  groups and quote time; the object identity above covers the remaining fields.
* Everything that can change while the operator reads the summary — the round's
  status, the database clock against the snapshot-age limit and the deadline — is
  re-checked by `publish_round` under the round's row lock in the publishing
  transaction (tested: another operator publishing during the confirmation makes
  this publish refuse with "already open").

**Readiness without a password — approved conditionally**: it must expose nothing
sensitive beyond `round show`. Verification (code review and a test pinning the
exact output fields):
* Round fields shown are those `round show` already prints (code, status,
  development flag, stream) plus nothing from entries, accounts or audit.
* Everything else is derived from the football store's fixtures and odds — the
  same upcoming fixtures and market data the public Screener displays — and the
  competition configuration (bucket sizes, the 24-hour quote rule, the snapshot-age
  limit): counts, kickoff times, deadline, cutoff and the content fingerprint.
* It contains no participant, account, entry, audit, provider-credential or
  database-connection data (tested: no `@`, user ID, database URL or password in
  the JSON output); it reads with the application database credential the operator
  already needs for `round show`, and writes nothing.
* Difference to note: readiness shows the *candidate* pool before publication,
  which `round show` cannot (a draft has no snapshot). That pool is public football
  data, not competition-sensitive information; if the owner prefers, the command
  can require `--operator` without any other change.

**Automated draft creation — deferred from Stage E** and then scheduled by the
owner as **Stage E.1 — Automated Draft Preparation**, immediately after Stage E and
before Stage F: a separately approved design (competition-week definition, fixture
window, scheduling, provider requirements, duplicate prevention) first, then a
separate implementation authorisation. Not started (§7.3, decision register).

### 7.6 Tests (`tests/backend/test_backend_stage_e_admin.py`, 19 tests)
Readiness writes nothing and matches publication (deadline, cutoff, fingerprint);
refusal parity for too few fixtures, a stale snapshot and a wrong source; unknown
round; inspection refused for a participant and `SYSTEM` (and `audit list` for
`SYSTEM`); inspection of draft and open rounds writes nothing; inspection of a
scheduler-settled round in its real 24-hour correction window shows the S-02
earliest finalisation and "cannot finalise" and changes nothing; audit attribution,
filters (prefix with literal wildcards, round, unknown round), `SYSTEM` attribution
of a scheduled lock and no email anywhere; CLI in-process: readiness exit codes and
JSON, publish confirmation (wrong answer changes nothing; the round code publishes
the shown snapshot, attributed to the operator), NOT READY publish refused and
recorded, inspect and audit output, one-line errors; CLI in a pseudo-terminal
against the local Supabase Auth harness: account arguments refused before any
password prompt, and `round inspect` / `audit list` refused for a participant and
allowed for an operator, password never echoed. Added at the owner review: a
snapshot other than the approved one is refused and nothing is stored; the CLI
builds the snapshot once and passes that object and its fingerprint, and a
concurrent publication during the confirmation is refused by the service;
readiness output limited to the pinned fields with no account or credential data.

### 7.7 Verification
* Level 1: the Stage E file (16 passed, no skips; pseudo-terminal tests ran
  against the local Supabase Auth harness); lint and formatting clean.
* Level 2 (local PostgreSQL and Supabase Auth harness): Stage E, rounds, S-07,
  operator CLI, scheduler, scheduler locking, ops, results, settlement (incl. ops
  and security), corrections, championships (incl. corrections, repair,
  backfill), integrity, concurrency, migrations, authentication units, weekly
  results, accounts, runtime role, scenarios and CI change-scope suites —
  **464 passed, 0 skipped** (11 min 33 s).
* Fingerprint `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
  migration head `app_0007`; no change under `src/diski9/challenge/`,
  `migrations_app/` or the scheduler; `publish_round` behaviour preserved (shared
  check, same order and messages).
* Level 3: §7.8.

### 7.8 Level 3 (GitHub CI)
* **First candidate `2f374da`, CI run 98: passed.** Scope full. **1,794 passed, 0
  failed, 0 skipped** (1,778 at the remediation + 16 Stage E tests), all 13 browser
  tests included; migration from an empty database, real Supabase Auth integration,
  lint and formatting passed. Test suite 28 min 20 s; job 29 min 47 s.
* **Final application-code candidate `c49de86`, CI run 99: passed.** Scope full
  (owner-review additions: approved-fingerprint guard, three tests, decisions
  documentation including Stage E.1). **1,797 passed, 0 failed, 0 skipped** (1,794 +
  3), all 13 browser tests included (`DISKI9_REQUIRE_BROWSER=1`); migration from an
  empty database, real Supabase Auth integration, lint and formatting passed. Test
  suite 26 min 11 s; job 27 min 33 s, within the 40-minute timeout.
* Documentation after the candidate uses the documentation-only path.

## 8. Stage E.1a: automated draft creation, readiness and monitoring — **formally accepted and closed**

**Owner acceptance.** Stage E.1a is formally accepted on this evidence:
application commit `3ed0301`, GitHub CI run 104 passed (1,835 passed, 0 failed, 0
skipped; all 13 browser tests); documentation commit `67433d9`, CI run 105
passed; Level 1 passing twice; Level 2 529 passed; migration head `app_0007`;
fingerprint `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
`broad60-432-v1` and `points-150-75-v2`; no unauthorised provider call,
publication, Official activation or competition-rule change. The three deviations
in §8.6 are accepted: the preparation jobs in the Stage D interrupted-job recovery
registry; READY freshness of two readiness intervals plus five minutes; readiness
evaluations every 30 minutes from draft creation. **Stage E.1a is closed.** Next:
**Stage E.1b — Automated API-Football Data Refresh**, starting with a separately
authorised design refinement (ingestion functions, refresh timing against the
Friday target, the advertised 7,500/day allowance, internal budgets and
results-import reserve, pacing and rate limits, request reuse, locking and
accounting, football-store access and hosting, monitoring, tests). The advertised
allowance does not authorise raising internal scheduler limits. E.1b
implementation, Stage F and Stage G are not authorised.

Authorised by the owner on the approved plan
([`phase6c6_stage_e1a_plan.md`](phase6c6_stage_e1a_plan.md); design
[`phase6c6_stage_e1_design.md`](phase6c6_stage_e1_design.md)). Baseline `c47474f`
(documentation CI run 103). No migration, no new dependency, **no new provider
call**, no change to competition rules, settlement, results, corrections,
championships or authentication.

### 8.1 What was built
| Module | Change |
|---|---|
| `backend/jobs/prepare.py` (new) | week calculator (`week_at`, `publication_target`), preparation steps (`plan`, `run_preparation`, `_draft_step`, `_readiness_step`), readiness record (`encode`/`decode`, categories), derived status (`preparation_status`, `preparation_lines`), default football-store snapshot builder (fails closed, never creates the store) |
| `backend/services/rounds.py` | `create_scheduled_draft(engine, SYSTEM, *, iso_year, iso_week, job_run_id)`, `scheduled_code`; `create_round`, `publish_round`, `publication_readiness` unchanged |
| `backend/jobs/config.py` | `prepare`, `prepare_streams` (beta only), `prepare_create_lead`, `prepare_readiness_interval`, `prepare_grace`, `prepare_min_seconds`; `PREPARABLE_STREAMS`; validation |
| `backend/jobs/reconciler.py` | preparation after the lifecycle loop inside the same lock/budget handling; injectable `snapshot_builder`; attention notes; dry-run planning |
| `backend/jobs/locking.py` | the two preparation jobs added to its job list (see §8.6) |
| `backend/ops/{snapshot,checks,config,history}.py`, `ops_cli.py`, `jobs_cli.py` | preparation status in `ops status` (text and JSON) and `jobs status`; eight preparation findings; two thresholds; job history knows the new jobs |
| docs | scheduler, monitoring, runbook §11, operator guide, `.env.example` |

### 8.2 Security boundary
`create_scheduled_draft` refuses a `Principal` (`Forbidden`), accepts only the ISO
year and week (validated), derives code, window, schedule and series from the
active `weekend` schedule, refuses a non-beta series, inserts with `ON CONFLICT
(code) DO NOTHING` and writes the status history (`created (scheduled)`) and the
audit record (`round.create`, `actor_role = 'system'`, job link) in the same
transaction; an existing round of any status is returned untouched. The static
guard (`test_backend_scheduler.py`) still forbids `publish_round`, `create_round`,
operator sign-in and every human-only service in `backend/jobs`, and now asserts
that `build_live_snapshot` and `create_scheduled_draft` appear only in `prepare.py`
(approved ADP-06/07). Development and Official are refused by configuration and by
the service; production refuses nothing extra because only beta is preparable.

### 8.3 Owner safeguards (authorisation §3)
* **A. Tick budget:** an evaluation starts only with
  `max(DISKI9_JOBS_PREPARE_MIN_SECONDS (60), 2 × slowest of the last 10
  evaluations)` of tick time left; otherwise it is `deferred` (no job row, never
  READY). An evaluation slower than `(abandon_after − tick_budget) / 2` (480 s with
  the defaults) is refused as a blocking failure, so a tick can never approach the
  20-minute abandonment threshold through preparation. **Measured** on a copy of
  the real football store (read-only): 68 fixtures in the window, 60 eligible, 420
  outcomes — snapshot build and opening checks 0.11–0.16 s (76 fixtures, 29
  eligible: 0.09–0.13 s); in tests the full step takes under 0.1 s.
* **B. Cadence (reconciled):** read-only evaluations every 30 minutes from the
  moment the draft exists (the plan's cadence; the earlier design's "delay until
  the refresh period" is superseded). The interval counts from the last
  *successful* evaluation; failures retry on the normal back-off. Monitoring is
  quiet about a NOT READY draft until the attention window (3 h before the
  target): early NOT READY usually means the store has not been refreshed yet.

### 8.4 Tests
* `tests/test_prepare_week.py` (15, no database): week mapping across Tuesday
  00:00 UTC, every hour of seven weeks in exactly one week, ISO 2026-W53 →
  2027-W01 and 2027-W52, European DST, create-lead bounds, readiness categories
  from the validator's own results, record encoding within the column limit.
* `tests/backend/test_backend_prepare.py` (23): configuration fail-closed; service
  SYSTEM-only, schedule-derived, audited, idempotent, no caller-supplied code;
  existing and published rounds untouched; non-beta schedule refused; concurrent
  scheduled + manual creation → one round; disabled, paused and dry run write
  nothing; one draft across repeated ticks, readiness in the same tick, interval
  respected, no provider request (ledger unchanged); manual draft first evaluated,
  not recreated; four concurrent ticks → one draft; crash before and after the
  creation transaction; interrupted readiness recorded as abandoned and
  recovered; lock lost during readiness → `lock_lost`, no verdict; budget deferral
  and the safe-duration limit; football store missing → blocking, never created;
  default builder on a real (empty) SQLite store; states and findings through a
  week (quiet early NOT READY, INFO in the attention window, WARNING after the
  target, READY unpublished INFO → WARNING, target missed); stale evaluation;
  no-draft CRITICAL near the target; paused quiet; published and lapsed states;
  the scheduler never publishes even when READY; lifecycle steps run first and
  unchanged; `ops status --json`, `ops status`, `jobs status`, `ops jobs`; a
  scheduled draft goes live only through `round publish` with the typed code and
  the approved fingerprint, attributed to the operator.
* `tests/backend/test_backend_scheduler.py`: static guard updated (§8.2).

### 8.5 Verification
* Level 1: both new files twice (38 passed each time); lint and formatting clean.
* Level 2: recorded below (§8.7).
* Fingerprint `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
  migration head `app_0007`; no change under `src/diski9/challenge/` or
  `migrations_app/`.

### 8.6 Deviations and risks
| Item | Note |
|---|---|
| `backend/jobs/locking.py` changed (plan said no change) | its `SCHEDULER_JOBS` list drives interruption marking and abandonment classification; without the two preparation jobs an interrupted or lost preparation step would stay `running` forever. Two entries added; no logic changed; the Stage D suite passes |
| Plan's "READY within one interval" | implemented as within two intervals plus five minutes, so a verdict is not reported stale just before the next scheduled evaluation |
| Concurrent ticks may report `indeterminate` | pre-existing Stage D behaviour when a tick races another tick's short "busy" record; the owner of the next tick completes the work; never two drafts (tested) |
| Football store on the scheduler host | readiness needs it; missing → blocking failure and CRITICAL near the target (fail closed). Hosting remains Q-07 |
| Lapsed drafts | stay inert `draft` rows (ADP-04 A); reported for 7 days |

### 8.7 Level 2 and Level 3
* **Level 2** (local PostgreSQL + Supabase Auth harness): week calculator,
  preparation, Stage E admin, rounds, S-07, operator CLI, scheduler, scheduler
  locking, ops, results, settlement (incl. ops and security), corrections,
  championships (incl. corrections, repair, backfill), integrity, concurrency,
  migrations, authentication units, weekly results, accounts, runtime role,
  scenarios, CI change scope and the API client — **529 passed, 0 failed, 0
  skipped** (10 min 44 s).
* **Level 3 — application-code candidate `3ed0301`, CI run 104: passed.** Scope
  full. **1,835 passed, 0 failed, 0 skipped** (1,797 at Stage E + 38 E.1a tests),
  all 13 browser tests included (`DISKI9_REQUIRE_BROWSER=1`); migration from an
  empty database, real Supabase Auth integration, lint and formatting passed. Test
  suite 29 min 26 s; job 30 min 25 s — within the 40-minute timeout (margin about
  9.5 minutes; noted, no change proposed).
* Documentation after the candidate uses the documentation-only path.

## 9. Stage E.1b: automated API-Football data refresh — **design approved in principle; implementation plan prepared (not implemented)**

Design refinement authorised by the owner on 22 Nov 2026 (design only: no
application code, migration, provider-limit change, live provider call, hosting
selection, webhook or activation). Baseline `4612f46` (E.1a closed, CI run 106).
Proposal: [`phase6c6_stage_e1b_design.md`](phase6c6_stage_e1b_design.md),
decisions REF-01 to REF-17, awaiting owner approval. Main findings: a preparation
sweep costs about 22 requests (fixtures 8 + odds 14; standings are display-only);
the provider updates odds once a day at about 02:00–03:30 UTC, so the first
publication refresh should run after about 04:00 UTC (not 03:00); the existing
ingestion functions hold the SQLite write lock during provider requests (fetch,
then apply, proposed); an unbounded `Retry-After` wait is a pre-existing gap; no
migration and no Stage D locking change is needed. E.1b implementation, Stage F
and Stage G are not authorised.

**Owner review (22 Nov 2026).** Design approved in principle: REF-01 to REF-10,
REF-15, REF-16; limits (20/tick, 450/24 h, 300 non-essential, 150 results reserve,
3 s pacing, floor 2,000) a planning baseline only. Deferred: REF-11, REF-12 (hosting
Q-07 and D-39 open), REF-13, REF-14, REF-17. Clarifications A–D resolved in the
implementation plan [`phase6c6_stage_e1b_plan.md`](phase6c6_stage_e1b_plan.md) (no
migration; existing cap defaults kept until activation; about 87 offline tests;
decisions D-1 to D-3 requested with the authorisation). **E.1b implementation not
authorised**; Stage F and Stage G not authorised.

## 10. Stage E.1b: automated API-Football data refresh — **formally accepted and closed**

**Owner acceptance (22 Nov 2026).** Stage E.1b is formally accepted on this evidence:
application commit `4394485`, GitHub CI run 109 passed (1,908 passed, 0 failed, 0
skipped; all 13 browser tests); Level 1 243 passed twice (no failures or skips);
Level 2 916 passed, 0 failed, one known environment-specific skip covered by GitHub
CI; documentation evidence commit `27f7396`, documentation-only CI run 110 passed;
migration head `app_0007`, fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`,
`broad60-432-v1` and `points-150-75-v2` unchanged; no live API-Football call,
migration, deployment or activation. **Accepted:** Balanced refresh scheduling;
reuse of the existing fixture and odds ingestion; fetch-then-write SQLite
transactions; per-league resumable steps; complete and partial sweep tracking;
Screener cache and readiness coordination; class-aware provider budgets with
protected results capacity; cross-process pacing and persisted cooldowns; bounded
provider waits; quota observations and preparation floors; monitoring and operator
visibility; the read-only refresh line in `round readiness`; preservation of Stage D
locking and recovery; Beta-only scope with refresh disabled by default; preservation
of human-authenticated publication. **D-1, D-2 and D-3 accepted and implemented.**
**Accepted deviations (documented decisions, not failures):** (1) scheduler tests
use zero pacing with fake providers while dedicated tests verify real pacing and
concurrency; (2) the low-provider-quota CRITICAL threshold is fixed at 600 requests;
(3) a sweep uses three ticks under the unchanged default 10-request cap. **Carried
forward as activation gates (not closed):** verify the active API-Football
subscription, quotas and billing behaviour; confirm odds-update timing in a real Beta
week; measure actual results-import consumption; resolve hosting Q-07; resolve the
D-39 PostgreSQL interpretation before hosted deployment; establish SQLite backup and
recovery; validate shared API-key consumption and quota observations; a supervised
first live refresh; genuine Beta-week lifecycle and real-clock finalisation testing.
**Acceptance does not authorise live activation; refresh stays disabled.** **Stage
E.1b is closed.** Next: Stage F — integration and genuine Beta-week validation,
awaiting separate authorisation (scope, checkpoints and dependencies to be reviewed
first); Stage G not started.

Authorised on 22 Nov 2026 on the plan at `bda1b14` (CI run 108), with decisions
D-1 to D-3 and three mandatory safeguards. Implementation, offline tests,
documentation and CI only: **automated refresh stays off**, no live API-Football
call was made, no provider limit was changed in any environment, no hosting was
selected, no migration was added, and nothing was merged, tagged or deployed.

### 10.1 What was built
| Area | Change |
|---|---|
| Provider client (`api_football/client.py`, `ratelimit.py`, `errors.py`) | optional `max_wait_seconds` (scheduler only; CLI behaviour unchanged): a retry wait or minute-window wait above it raises `ApiFootballRateLimitError(retry_after=…)` instead of sleeping; optional per-minute floor as a share of the provider's minute limit |
| Ledger (`backend/jobs/locking.py`) | request class on every `scheduler.provider` row (`results` / `preparation`; unclassified rows count as results, D-2); class-aware caps (`Caps`: per tick, 24 h, non-essential, results reserve); **paced send slots** committed in the serialised reservation; persisted provider cooldowns (`scheduler.provider_cooldown`); quota observations (`scheduler.provider_quota`) usable only when fresh and from the current UTC day; refresh jobs in the Stage D recovery registry |
| Configuration (`backend/jobs/config.py`) | refresh switches and schedule, non-essential cap 300, results reserve 150, floor 2,000, 3 s interval, 30 s maximum wait, expected limit 7,500, observation age 30 min; existing caps keep 10/100 (D-1) and refresh is refused unless the 24-hour cap holds both shares; the longest possible tick is validated against the abandonment threshold |
| Ingestion (`ingestion/fixtures.py`, `odds/collect.py`) | behaviour-preserving split: `fetch_season_fixtures` / `apply_season_fixtures`, `fetch_odds_pages` / `reconcile_pages(started=…)`; the CLI functions now fetch before taking the store's write lock |
| Refresh (`backend/jobs/refresh.py`, new) | Balanced slots, current-slot-only planning, per-league steps (fetch → verify ownership → one short SQLite transaction), sweep state derived from job records, partial closing (supersession or 30 min), Screener step, quota gate with `/status` pre-flight, status and display lines |
| Preparation (`backend/jobs/prepare.py`) | refresh between draft creation and readiness; readiness deferred while a sweep is part-way, triggered when one closes, records `data=…`; refresh fields in the preparation status |
| Reconciler (`backend/jobs/reconciler.py`) | results imports use the same reservation hook (class `results`, pacing, cooldown, bounded waits, quota observations); new outcome classification; `tick(..., store_factory, sleep)` seams |
| Monitoring (`backend/ops/*`, `ops_cli`, `jobs_cli`) | 13 refresh/provider findings; refresh block in `ops status` / `jobs status`; dry run lists refresh steps; new jobs in history |
| `round readiness` (`cli.py`) | display-only "data refresh" line (D-3); validator, snapshot, fingerprint and publication unchanged |

### 10.2 Mandatory safeguards and how they are tested
1. **Pacing correctness.** `reserve()` computes the send slot inside the
   transaction that holds the budget advisory lock — `max(now, previous slot +
   interval)` from the ledger itself — and commits it **before** the caller sleeps,
   so a second caller (thread, tick or restarted process) is always placed after it.
   A crash after reserving leaves the slot used and counted. A slot further away
   than the maximum wait is refused without being recorded; a previous slot
   implausibly far in the future (database clock moved back) is treated as "now",
   keeping the wait bounded. Tests (`test_backend_refresh_budget.py`): sequential
   spacing; across ticks and a fresh engine; three concurrent threads × 3 receive 9
   distinct slots all ≥ the interval apart; a sleeping holder cannot be bypassed;
   future-slot queueing and backlog refusal; clock moved backwards.
2. **Retries and budgets.** Every attempt — retries and `/status` included — passes
   through the reservation hook, which re-checks per-tick, 24-hour, non-essential and
   results-reserve caps; the four-request pre-check is only an early stop. Writes
   happen after all of a league's requests, so a league that runs out part-way writes
   nothing and is not done. Tests: retries reserved and counted as preparation
   (ledger rows = HTTP requests); capacity exhausted mid-league (retry + three odds
   pages under a 5-request cap → deferred, exactly 5 reservations, store unchanged,
   league not done); preparation can never use the reserve; results succeed when
   preparation has used its whole share; per-tick cap counts every class.
3. **Partial sweep recovery.** A sweep is closed partial when superseded or 30
   minutes after its first league step (with at least one league done); a closed
   sweep is terminal for its slot, labelled `partial@slot(n/8)` and never complete;
   failures back off within the slot only, so the next slot always retries every
   league. Tests: Friday 04:15 sweep with a failing league → partial at 04:51 (7/8,
   readiness `data=partial@…(7/8)`, `refresh_partial`), nothing more for that slot,
   then the 05:15 sweep refreshes all eight and closes complete; supersession closes
   the old sweep partial and starts the new one.

### 10.3 Tests
New: `tests/test_client_waits.py` (8), `tests/test_ingest_split.py` (3),
`tests/test_refresh_slots.py` (22), `tests/backend/test_backend_refresh_budget.py`
(14), `tests/backend/test_backend_refresh.py` (26) — 73 offline tests (mock
transport, temporary SQLite stores, isolated PostgreSQL; the network is never
reached). Changed: the scheduler tests' shared configuration sets
`provider_min_interval=0.0` (their fake providers need no spacing; pacing is tested
with real timing in the budget file) — no assertion was weakened.

### 10.4 Verification
* **Level 1** (E.1b tests plus client, odds, fixtures, workflow, eight-league odds,
  week calculator, preparation, scheduler, scheduler locking, ops and Stage E admin):
  **243 passed** twice (about 5 minutes each), 0 failed, 0 skipped.
* **Level 2** (every backend suite on local PostgreSQL and the auth harness, plus the
  client, ingestion, workflow, CI change scope and migrations suites): **916 passed,
  0 failed, 1 skipped** (25 min). The skip is the known environmental one
  (`test_backend_supabase_db.py`: needs a database with a real Supabase auth schema;
  covered by GitHub CI's real Supabase integration).
* Migration head `app_0007` (no migration added); quantitative fingerprint
  `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
  `broad60-432-v1`, `points-150-75-v2` unchanged.
* **Performance (expected in production):** a typical sweep is about 23 requests
  (`/status` 1, fixtures 8, odds 14); at 3 s pacing about 70 s of waiting plus a few
  seconds of responses and SQLite writes, over two ticks at 20 per tick; Screener
  cache 1.2–1.4 s (measured on a scratchpad copy of the real store); readiness
  0.1–0.2 s. Longest possible tick with the activation values: 240 s + 20 × (10 s +
  3 s) + 30 s = 530 s, below the 20-minute abandonment threshold (validated).
* **Level 3 — application-code candidate `4394485`, CI run 109: passed.** Scope
  full. **1,908 passed, 0 failed, 0 skipped** (1,835 at E.1a + 73 E.1b tests), all
  13 browser tests included (`DISKI9_REQUIRE_BROWSER=1`); lint, formatting, migration
  from an empty database and real Supabase Auth integration passed. Test suite
  26 min 45 s; job 28 min 1 s — within the 40-minute timeout (margin about 12
  minutes; the previous run was 30 min 25 s, so no CI time was added).

### 10.5 Deviations and risks
| Item | Note |
|---|---|
| Scheduler tests' shared configuration | `provider_min_interval=0.0` so fake-provider lifecycle tests do not sleep; pacing is covered with real timing in the budget tests |
| Pre-check of 4 requests per league | under a 10-request cap a tick runs two leagues after `/status` (9 → 6 → 3 left), so a sweep takes three ticks at the default cap (as planned) |
| Back-off of a failing league | counted within the slot (so the next slot always retries), as planned; uses the existing retry base/maximum |
| `provider_quota_low` CRITICAL threshold | fixed at 600 (client reserve 500 + 100) rather than "500 + projected results need" — simpler and conservative |
| Carried forward (activation gates) | active subscription limits and at-limit billing unverified (activation gate); provider update time measured on few days; results-import volume estimated; same-host SQLite requirement with Q-07 and D-39 open; other users of the key visible only through lagging observations; CI margin about 12 minutes (run 109) |

## 11. Stage F: integration and genuine Beta-week validation — **architecture approved; F1 accepted; F2 implemented, awaiting owner acceptance (§12)**

Authorised on 22 Nov 2026 as design and readiness assessment only (baseline `77f22ad`,
CI run 111). Proposal: [`phase6c6_stage_f_design.md`](phase6c6_stage_f_design.md),
decisions SF-01 to SF-14, awaiting owner approval. Main findings: the web app has no
packaged production WSGI entry point or `/healthz` (Q-10); no hosted Supabase project
or database exists yet (hosted Supabase acceptance remains an open gate); the SQLite
store requires the web app and scheduler on one host; D-39 needs an owner ruling on
"hosted deployment" before any hosted Stage F environment; a competitive Beta round
needs ≥ 5 real entrants and Beta championship rounds are permanent, so the
operator-only supervised week is proposed as a practice round, with competitive and
championship evidence from an invited private Beta after ML-01 and a minimum D-36
workflow; the D-29b research capture uses the same API key at the Friday publication
target. Stage F implementation and Stage G are not authorised.

**Owner review (22 Nov 2026).** Stage F architecture approved; **F1 (architecture and
readiness) accepted**; SF-01 to SF-14 recorded with qualifications (design §16);
**D-39a** ruling recorded (private, access-restricted, single-host supervised Stage F
environment may retain SQLite; migration mandatory before public or production
deployment). **F2 implementation planning authorised and delivered:**
[`phase6c6_stage_f2_plan.md`](phase6c6_stage_f2_plan.md) — production WSGI entry point
reusing the F3 tooling, `/healthz` and `/readyz`, SQLite online backup with verification
and guarded restore, PostgreSQL dump/restore runbook, backup-health findings,
provider-neutral systemd/reverse-proxy/environment templates, host-hardening guide,
offline full-week rehearsal on an isolated database, local restore drills, security
tests; no migration. **F2 implementation not authorised**; F3–F6 and Stage G not
authorised.

## 12. Stage F2: offline deployment readiness — **implemented, awaiting owner acceptance**

Authorised on 22 Nov 2026 (plan [`phase6c6_stage_f2_plan.md`](phase6c6_stage_f2_plan.md),
commit `fa80245`, CI run 113) with four additional mandatory safeguards (A–D below).
Application commit `c7630fe` (full CI run 114: passed — 1,987 tests, 0 skipped, all 13 browser tests enforced (DISKI9_REQUIRE_BROWSER=1); suite 27 min 07 s, job 28 min 30 s, margin ≈ 11.5 min within the unchanged 40-minute timeout (application baseline run 109: 1,908 tests)). **Not accepted or
closed**: awaiting independent owner review. No hosting, infrastructure, Supabase
project, live provider call, refresh activation, participant account, D-29b change,
webhook, Official activation, merge, tag, release or deployment. No migration (head
`app_0007`); fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`, `broad60-432-v1`
and `points-150-75-v2` unchanged.

### 12.1 What was built
| Area | Implementation |
|---|---|
| Shared app factory | `src/diski9/app/factory.py` `build_app()`: the one construction used by `diski9 serve`, `diski9.wsgi` and `tools/f3_wsgi.py` (now a thin import of `diski9.wsgi`) |
| Production WSGI | `src/diski9/wsgi.py` (`gunicorn diski9.wsgi:server`); no `chdir`; refuses a relative SQLite store in production. Gunicorn `26.2.0` pinned as the optional `server` extra (default install unchanged; CI installs the extra) |
| Health | `src/diski9/app/health.py`: `/healthz` (liveness) and `/readyz` (competition DB `SELECT 1` with a 2 s statement timeout when accounts are configured; football store present with its tables, never created by the probe) served by a WSGI middleware in front of Flask/Dash: no cookies, no session/CSRF hooks, no Dash first-request layout build, fixed words only, `no-store`, GET/HEAD only |
| Backup | `src/diski9/backup/store.py`, `diski9 backup store|verify`: SQLite online backup from a read-only connection (one consistent snapshot), single-file journal mode, `0600`, `fsync`, integrity + foreign keys + 17 tables + version `0004`, SHA-256 manifest, prune of own files only; a failed copy is deleted |
| Restore | `src/diski9/backup/restore.py`, `diski9 restore store --purpose recovery|drill`: new, unused paths only (safeguard A) |
| Evidence records | `src/diski9/backup/records.py`, `diski9 backup record --kind postgres|offhost-copy|postgres-drill|postgres-restore`: completed `job_runs` rows (`ops.backup_*`, `ops.restore_*`, `ops.provider_resume`), insert-only |
| Monitoring | `src/diski9/backend/ops/backups.py`: four evidence levels in `ops status`; backup findings in `ops check` (off by default); `ops jobs` lists the records |
| Provider hold | after a recorded PostgreSQL restore every tick runs with provider calls and refresh off; `diski9 ops provider-resume` (operator, password, checklist, typed `RESUME`, audited) lifts it |
| Refresh consistency | `refresh.py`: sweeps that started before the latest recovery restore of the football store no longer count (`data=none`; the slot is swept again) |
| Templates | `deploy/`: systemd web/tick/backup units and timers, off-host copy hook placeholder, Caddy reverse proxy, environment template (safe defaults) |
| Documentation | new [`../operations_hosting.md`](../operations_hosting.md) (hardening, install, health, backups, evidence levels, restore and offline switch, PostgreSQL runbook and recovery gate, drills, never-do list); runbook §13; monitoring, scheduler and operator guides; `.env.example` |
| Rehearsal and drill | `src/diski9/backup/isolation.py` (disposable targets), `tests/backend/test_backend_f2_rehearsal.py`, `tools/f2_restore_drill.py` |

### 12.2 Mandatory safeguards and their tests
| Safeguard | Implementation | Tests / evidence |
|---|---|---|
| **A. SQLite live-restore safety** | A reliable, fail-closed proof that every consumer has stopped needs the host's service manager, so **live replacement is disabled in F2**: `--replace-live` is always refused; the configured store, its `-wal`/`-shm`/`-journal` files, symlinks, hard links and path aliases can never be a target; existing targets and side files are refused; the source must verify; temporary copy, checksum, `os.link` (never overwrites), verification in place; the previous store and its WAL/SHM stay untouched; recorded. The manual offline switch for F3 is documented (hosting §6). | `test_f2_backup_restore.py`: `test_replace_live_is_always_refused`, `test_restore_refuses_the_live_store_and_every_alias`, `…existing_targets_side_files_and_bad_folders`, `…unverified_sources`, `test_restore_into_a_new_path_verifies_and_preserves_the_previous_store` (byte-identical store, WAL and SHM) |
| **B. Backup evidence** | Four levels kept apart; the backup establishes levels 1–2 only; level 3 is *reported* by the host hook; level 4 requires a drill whose content matches a recorded backup checksum, with origin always "operator-declared"; monitoring off by default | `test_backend_f2_backup.py`: `test_cli_records_each_evidence_level_truthfully`, `test_a_drill_not_matching_any_recorded_backup_is_not_restore_evidence`, `test_monitoring_on_with_nothing_recorded_reports_every_gap`, `test_backup_monitoring_is_off_by_default`, `test_stale_and_failed_backups` |
| **C. Rehearsal isolation** | Disposable PostgreSQL created by the harness under a random name (never adopts an existing DB), empty at creation, random marker token re-checked before every destructive step and at teardown; loopback servers only; production, protected and configured databases refused; temporary football store with its own marker, live store and repository `data` refused; network blocked except loopback; mock transports; evidence labelled simulated | `test_backend_f2_rehearsal.py`: the rehearsal plus `test_production_is_refused…`, `test_protected_configured_and_foreign_targets_are_refused`, `test_an_existing_database_is_never_adopted_or_dropped`, `test_a_created_target_is_unique_marked_and_dropped`, `test_store_isolation_refuses_the_live_store`, `test_no_network_allows_only_loopback_and_mock_transports` |
| **D. PostgreSQL restore recovery** | Runbook (hosting §8) lists every loss (ledger, cooldowns, quota observations, job history, audit, competition changes) and the procedure; a recorded restore places a database-held provider hold that survives scheduler restarts and overrides `DISKI9_JOBS_PROVIDER_CALLS`/refresh; only an authenticated operator lifts it after the checklist; `ops check` WARNING while held; templates default to provider calls and refresh off. No change to Stage D locking or provider accounting (the hold only switches provider work off for the tick). | `test_backend_f2_backup.py`: `test_provider_hold_after_restore_survives_scheduler_restarts` (3 ticks, no provider call, no ledger row, refresh also held), `test_only_an_authenticated_operator_lifts_the_hold`, `test_resume_lets_the_scheduler_use_the_provider_again`, `test_restored_dump_with_interrupted_steps_recovers_under_stage_d_rules`; local drill |

### 12.3 Tests
79 new tests in six files (the plan estimated 35–45; the safeguards added the
refusal matrices): `tests/test_f2_wsgi_health.py` (20), `tests/test_f2_backup_restore.py`
(18), `tests/test_f2_deploy_templates.py` (17), `tests/backend/test_backend_f2_health.py`
(4), `tests/backend/test_backend_f2_backup.py` (13), `tests/backend/test_backend_f2_rehearsal.py`
(7). No existing test changed or weakened.

### 12.4 Verification
* **Level 1** (new tests plus auth web, ops, refresh, scheduler, scheduler locking,
  prepare and app suites; 251 tests): passed twice (339.8 s, 333.9 s).
* **Level 2** (full local suite on PostgreSQL 16 and the local Supabase Auth harness):
  1,987 passed, 0 skipped (32 min 50 s); the 1,908-test baseline plus the 79 new tests.
* **Level 3** (full GitHub CI): run 114 on `c7630fe`: passed — 1,987 tests, 0 skipped, all 13 browser tests enforced (DISKI9_REQUIRE_BROWSER=1); suite 27 min 07 s, job 28 min 30 s, margin ≈ 11.5 min within the unchanged 40-minute timeout (application baseline run 109: 1,908 tests).
* **Local drill** ([`phase6c6_stage_f2_drill_report.md`](phase6c6_stage_f2_drill_report.md)):
  PASSED — 44 tables identical by content hash and count after `pg_dump`/`pg_restore`
  (PostgreSQL 16.15), head `app_0007` before/after, `competition verify` consistent
  before/after, football store tables and checksum equal, fingerprint unchanged,
  provider hold active with no provider call; failure drills (store corruption →
  restore, database unavailable, scheduler killed mid-step) passed; interrupted refresh
  covered by the E.1b CI tests.
* **Measurements:** online backup of the 36.8 MB local store 0.18–0.26 s including
  verification; CLI restore 0.16–0.28 s; drill `pg_dump` 0.16 s, `pg_restore` 0.48 s
  (0.32 MB dump); rehearsal ≈ 16 s; the source store's checksum was unchanged by every
  backup.
* Migration head `app_0007`; fingerprint recomputed and unchanged; configurations
  unchanged.

### 12.5 Deviations, limitations and risks
* **Live football-store replacement disabled** (safeguard A, as the owner allowed):
  restore to a new path plus an offline, supervised configuration switch; an in-place,
  host-verified procedure may be designed in F3 with the chosen service manager.
* **Health checks are WSGI middleware**, not Flask routes (the plan said "registered on
  the Flask server"): Dash builds its layout from the football store on the first
  request to any Flask route, which would make probes fail with 500 on a fresh worker
  with a missing store, and the middleware keeps probes outside the session hooks.
* **Provider hold** (database record, operator resume command) goes beyond the
  documentation-only minimum allowed for safeguard D; it adds no migration, table or
  change to locking or accounting.
* **`restore store --purpose`** is required (recovery vs drill), so drills never make
  refresh data stale; recovery restores make refresh labels conservative even before
  the switch.
* **Gunicorn 26.2.0** pinned (latest release older than two weeks at implementation;
  the plan named no version); CI installs the `server` extra (`uv sync --frozen
  --extra server`), the only workflow change; timeout unchanged.
* **79 tests** instead of 35–45; CI time impact recorded in §12.4.
* **Limitations:** PostgreSQL dump/restore runs only in the local drill (CI has no
  `pg_dump`); off-host copy and off-host restore (levels 3–4) cannot be evidenced until
  a host exists; the hold depends on the operator recording the restore (runbook step
  3) and covers the scheduler only, not manual provider commands; the 24-hour
  PostgreSQL recovery point stays provisional (tighter-RPO evaluation before F5).
* Gates carried forward: before F3 provider/region/spending selection and hosted
  Supabase acceptance; before F4 the SF-14 analysis; before F5 tighter RPO, ML-01 and
  D-36.
