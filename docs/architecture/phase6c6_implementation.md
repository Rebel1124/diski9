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
