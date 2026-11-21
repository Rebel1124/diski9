# Phase 6C.6 — Operational administration, scheduling and monitoring: design proposal

> **Status: Stage A design APPROVED with decisions (21 Nov 2026) — see §11.** The
> owner's decisions on Q-01 to Q-14 (§11) take precedence over the recommendations
> in §1–§10 where they differ (notably Q-03, Q-04, Q-07). Stage B (S-07) is
> authorised; Stage C and later stages need separate approval. Prepared 21 Nov 2026
> on branch `feature/phase-6c6-operations`, created from the accepted 6C.5 closure
> commit `630e021` (proposal commit `ee309d3`, CI run 83).

Legend used throughout: **[Confirmed]** = verified in the repository (code, schema
or documents, with a reference); **[Recommendation]** = proposed design;
**[Assumption]** = stated, unverified.

---

## 0. Baseline and discrepancies

**Accepted baseline [Confirmed]:** `feature/phase-6c5-leaderboards` at `630e021`
(Phase 6C.5 Stage G closure; CI run 82 passed); full regression 1,682 passed, 0
failed, 0 skipped (F4); migration head `app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`; configuration
`broad60-432-v1`, scoring `points-150-75-v2`. `main` is at v4.2.0 (`06a9a6a`):
**6C.5 is accepted but not merged or released** (merge not authorised).

**Phase order [Confirmed]:** the Phase 6C plan roadmap lists 6C.5 complete → **6C.6
administration, scheduling and monitoring** → 6D integration testing and release →
… → 10 production deployment and private beta. 6C.6 is next; 6D is pending.

**Discrepancies found (not resolved; for the owner):**

| # | Finding | Where |
|---|---|---|
| D1 | **"Deadline + 24 h" is not the implemented rule.** Finalisation is allowed at **max(settlement cutoff, last material settlement change) + correction window (24 h)** (S-02), where the settlement cutoff = latest scheduled kickoff at publish + 48 h (`settle/v1` §2). For a Friday–Monday round this is typically Wednesday evening + 24 h ≈ Thursday evening, not deadline + 24 h. The code and `settle/v1` are authoritative; the phrase "deadline-plus-24-hour" used in 6C.5 records and briefs should be read as this rule. | `settlement.earliest_finalisation`; `docs/product/weekly_challenge_settle_v1.md` §2; 6C.5 records |
| D2 | The original 6C.6 plan section expected **operator console web pages**, a **health-check endpoint**, structured logs, a **backup and restore drill** and a scripted full-week lifecycle test. The current brief prefers a minimal CLI-first admin. This proposal keeps the CLI first (§5) and asks about the restore drill (Q-12). | `weekly_challenge_phase6c_plan.md` "6C.6" |
| D3 | The original plan said "database changes: none expected". This proposal needs **none for the core**; two optional migrations are identified (§7.3) for owner choice. | same |
| D4 | S-07's register entry already anticipates "human operator actions distinguished from future **explicitly authorised scheduled operations**". The service layer has an explicit `SYSTEM` actor, but **only `round lock` exposes it in the CLI**; settlement, finalisation and import accept it in services but not in any command. | `decisions.md` S-07; `services/rounds.py` `System`; `settlement_cli.py` |
| D5 | Two research automations run as Claude cloud scheduled tasks (D-29b weekly pool collector on `research/weekly-pools`; the odds trial ending today 15:00 UTC). They are **not** part of the application and not a precedent for the production scheduler. | `phase6c3_closure_handover.md` §7 |

## 1. Current-state operational architecture assessment

Status: **Implemented** / **Partial** / **Missing**. All [Confirmed] unless marked.

| Area | Status | What exists | Gap |
|---|---|---|---|
| Round creation | Partial | `diski9 round create --week YYYY-Www --by-email` → `rounds.create_round` (PUBLISH_ROUND); schedule rules in `app.round_schedules` (v2: window Fri 00:00 UTC–Tue 00:00 UTC; publish rule Fri 08:00 Africa/Johannesburg; deadline buffer 15 min; settle cutoff 48 h; correction window 24 h) | S-07 identity; no automation |
| Round publication | Partial | `round publish` builds a live snapshot from the football store (`build_live_snapshot`) and `publish_round` enforces D-28 thresholds, odds freshness (24 h) and snapshot construction age (`DISKI9_SNAPSHOT_MAX_AGE_MINUTES`, default 60); failed publications are recorded in `job_runs` | S-07; needs fresh fixtures/odds first (`refresh`/`collect-odds`, provider requests); `SYSTEM` not permitted (PUBLISH_ROUND needs a person) |
| Entry deadline | Implemented | Database triggers on drafts/submissions use the database clock (`app_0003` `draft_deadline_guard` etc.); entries cannot change after the deadline even if lock is late | — |
| Entry locking | Partial | `round lock --code` runs as `SYSTEM` when `--by-email` is omitted; idempotent ("already locked"); `job_runs` + audit | no scheduler invokes it |
| Results import | Partial | `results import` (by-ID provider fetch, ≤ 20 fixtures/request, relevant fixtures only, `--full` re-check); service accepts `SYSTEM`; provider client has a request budget and reads the daily-remaining header | CLI requires an interactive operator; no scheduler |
| Settlement | Partial | `settle preview/run/status/alerts/resolve-alert`; `settle_round` accepts `SYSTEM` (trigger `scheduled`), idempotent runs, alerts (blocking/non-blocking), V1/V4 voids after cutoff, post-final changes raise alerts, time override refused for `SYSTEM` | CLI operator-only; no scheduler |
| Finalisation + weekly publication | Partial | `round finalise-check` / `finalise`; `finalise_round` accepts `SYSTEM` (RUN_JOBS for persons); enforces S-02 earliest time, no blocking alerts, all resolved; a final settlement run first; publishes the weekly score set | CLI operator-only; no scheduler; 6C.4 note: run `results import --full` before finalising |
| Championship processing and rollover | Implemented | runs inside finalisation (`on_round_event` → `process_stream`) under the stream advisory lock; F3-1/F3-2 fixed; `competition status/verify/repair/backfill` | — (runs automatically with finalisation) |
| Corrections, reopening, re-finalisation | Implemented | `results correct/withdraw-correction`, `round reopen` (owner, S-06), `round invalidate`; refuse `SYSTEM` ("needs an authenticated person"); T-14 enforced via `refresh_clock` | — (human-only by design) |
| Operator authentication | Partial | `authenticate_operator` (terminal-only password via Supabase Auth, session verified then signed out, roles from DB, T-12/T-14 via `Principal`, fail closed, no bypass) on **every settlement/competition command** | **S-07**: `round create/publish/lock/dev-open` and `account grant-role/revoke-role/grant-feature/revoke-feature/suspend/reinstate` identify the actor by `--by-email` only (`cli.py` `cmd_round` `actor()`, `cmd_account`); `privileged.py` checks roles from the DB but has no `Principal`, so **no T-12/T-14** |
| Role management | Partial | `privileged.py`: owner-only role and entitlement changes, operators/owners for suspend; `bootstrap-owner` only when no owner exists and `--confirm` | S-07 identity and recency; bootstrap has no proof of account control |
| Audit and events | Implemented | `app.audit_log` (insert-only; actor_role ∈ participant/operator/owner/system; actor required unless system; `job_run_id` link); `domain_events`; `round_status_history`; settlement runs and versions | audit of scheduler runs needs a consistent job-run link (§3) |
| Background jobs / scheduler | **Missing** | `app.job_runs` table and `ops.try_job_lock` (transaction-scoped advisory lock), `start_job/finish_job` — used by publish and lock only | no scheduler, no job runner command, no retry policy |
| Locking, transactions, idempotency | Implemented | round change lock `FOR NO KEY UPDATE`; submissions `FOR SHARE`; stream advisory lock; idempotent lock/settle/finalise guards; REPEATABLE READ for official reads | reusable as-is |
| Integrity inspection | Implemented (on demand) | `competition verify` (`inspect_stream`); `tools/phase6c5_f4_integrity.py` (read-only, negative-controlled; development tool) | not scheduled; F4 tool lives in `tools/` |
| Monitoring and logging | **Missing / minimal** | `app-db check` (connectivity, migration head); settlement alerts table and `settle alerts`; plain `logging` (WARNING/INFO via `-v`) | no job health view, no stuck-round detection, no notifications, no HTTP health endpoint |
| Admin interfaces | Partial | CLI only (`round`, `results`, `settle`, `competition`, `account`, `app-db`, `dev`); no web admin by design | status/readiness overview; one-line errors (6C.3 backlog: tracebacks) |

## 2. S-07 security remediation proposal [Recommendation]

### 2.1 Affected commands [Confirmed]
* `diski9 round create | publish | dev-open` — actor from `--by-email` (`cli_principal`, `authenticated_at=now`, no password).
* `diski9 round lock --by-email` — same; without `--by-email` it is `SYSTEM` (legitimate unattended path).
* `diski9 account grant-role | revoke-role | grant-feature | revoke-feature | suspend | reinstate --by-email` — actor UUID only; no T-12/T-14.
* `diski9 account bootstrap-owner` — no actor; guarded only by "no owner exists" and `--confirm`.
* Read-only `account list-privileged`, `round list/show` — no identity needed (database access only); acceptable as read-only server tools [Recommendation: keep].
* No other privileged command lacks `authenticate_operator`: every writing `results`, `settle`, `round finalise/finalise-check/reopen/invalidate`, `competition` and `dev` action uses it; only read-only listings (`dev scenarios`, `dev-championship presets/plan`) do not [Confirmed by inspection of `settlement_cli.py`].

### 2.2 Design
1. **One human path.** Every privileged human command obtains its `Principal` from the existing `authenticate_operator` (terminal password → Supabase Auth → verified subject → active onboarded account → roles from the database). `--by-email` stops being an identity; it is replaced by an optional `--operator EMAIL` that is **only the login name** for the password prompt (prompted if absent), exactly as the settlement commands already work.
2. **Recency.** Authorisation goes through `permissions.authorize` with the freshly authenticated principal: PUBLISH_ROUND/RUN_JOBS satisfy T-12 (authenticated now); MANAGE_ROLES, MANAGE_ENTITLEMENTS and SUSPEND_USER are SENSITIVE and require the password within 15 minutes; before each write `refresh_clock` re-reads the database time so a slow confirmation is refused (T-14), as in 6C.4.
3. **No impersonation.** `privileged.py` functions take the authorised `Principal` (not a bare UUID) and keep their database role checks (`_require_owner` etc.) as defence in depth. Audit `actor_user_id` = the verified subject's account; `actor_role` = operator/owner from the database.
4. **Unattended actions are `SYSTEM`, never a person.** A separate command family (§3, `diski9 jobs …`) acts as the explicit `SYSTEM` actor: audit `actor_role='system'`, `actor_user_id` NULL, `job_run_id` set, `job_runs.host` set. An allowlist limits `SYSTEM` to deterministic, rule-guarded steps: lock, results import, settle, finalise (+ championship processing inside it), integrity checks; publication only if Q-04 approves. `SYSTEM` can never correct, reopen, invalidate, override time, manage roles or entitlements (already enforced in services; add explicit tests). Rationale: these steps produce the same outcome whoever triggers them and cannot advance any rule (database clock, S-02, D-28); they need host credentials, not operator authority.
5. **Bootstrap and emergency recovery (explicit, controlled).**
   * `account bootstrap-owner` remains available **only while no owner exists**, requires a terminal, `--confirm`, a reason, and **the target account's own password** (proof of control of an onboarded account; no impersonation of someone else). Audited with a dedicated action.
   * **Emergency owner recovery** (all owners lost or locked out) [Recommendation, Q-03]: a documented break-glass command `account recover-owner` that additionally requires (a) an explicit `DISKI9_BREAK_GLASS=1` environment flag on the host for that one invocation, (b) the target's password, (c) a reason and confirmation; it grants owner, writes a high-visibility audit record and raises a P1 monitoring alert. No silent path. Alternative: no command; recovery by documented manual SQL by the database administrator (still audited by a follow-up command). 
6. **Credentials.** Passwords only via `getpass` from a terminal (unchanged rule: never arguments, environment or pipes). The scheduler holds **no human credentials**; it needs the app database URL and (for imports/publication) the provider API key, from the host's secret store or an untracked `.env` (existing pattern), never in the database, logs or audit.
7. **Failure behaviour.** Fail closed: provider unavailable, wrong password, unknown/suspended account, missing role or expired recency → refused with a one-line message, no write. Scheduler jobs do not depend on Supabase availability.
8. **Compatibility.** No change to Supabase configuration, the web session model or RLS; same `AuthProvider` used by the web app; works against the local GoTrue harness and hosted Supabase.
9. **Non-interactive human operations** are deliberately unsupported (consistent with S-07). Anything that must run unattended is a `SYSTEM` job or is not automated.

### 2.3 Regression coverage
Real-CLI tests through a pseudo-terminal (existing 6C.4 pattern): each remediated command refuses without a terminal, with a wrong password, for a participant, a suspended account and an expired T-14 window; `--by-email` alone no longer authorises anything (the F2 characterisation tests in `test_backend_f2_s07_assessment.py` are inverted into regression tests); audit attribution equals the verified account; `SYSTEM` refused for every human-only service (corrections, reopen, invalidate, roles, entitlements, suspend, time override); bootstrap refused when an owner exists and without the target's password.

## 3. Scheduling and lifecycle orchestration design [Recommendation]

### 3.1 Options compared

| Option | Description | Pros | Cons | Verdict |
|---|---|---|---|---|
| A. **Reconciler + any cron-like trigger** | One idempotent command `diski9 jobs tick` run every 5 minutes by cron / systemd timer / launchd (local) or the host's scheduler (Phase 10). Each tick reads database state per stream and performs whatever lifecycle step is due. | No new dependency or service; missed runs self-heal (level-triggered); host-neutral; reuses services, advisory locks and `job_runs`; easy to test with an injectable clock | Needs a trigger on the host; 5-minute granularity | **Recommended** |
| B. In-process scheduler (APScheduler) in a long-running worker | Python scheduler daemon | Fine-grained timing | New dependency; a daemon to supervise; job store/persistence to manage; still needs the same reconciliation for missed runs | Not needed |
| C. PostgreSQL `pg_cron` | Database-side cron | Available on Supabase-hosted Postgres | Cannot run the Python services; would push logic into SQL | Rejected |
| D. Hosted platform cron (Render/Fly/GitHub Actions schedule) | External trigger of option A's command | Zero local supervision | External service; hosting decision belongs to Phase 10 | Compatible later as the trigger for A |
| E. Celery/Redis/queue | Distributed task queue | Scale | Unjustified infrastructure | Rejected |

### 3.2 The reconciler (option A)
* **Command:** `diski9 jobs tick [--stream beta|development] [--dry-run]` (plan only, writes nothing) and `diski9 jobs run <step> --round CODE` for a single step. Both act as `SYSTEM`.
* **Per stream, per round, in dependency order** (each step is an existing service; nothing in the rules changes):

| Step | Due when (database clock, UTC) | Service | Notes |
|---|---|---|---|
| prepare | the next ISO week has no round and the publish rule time minus lead time has passed | `create_round` (+ `schedule_window`) | needs Q-04 (`SYSTEM` creation) |
| refresh data | before publication | existing football `refresh` / `collect-odds` (provider requests) | budgeted; Q-05 |
| publish | publish rule time (Fri 08:00 Africa/Johannesburg, converted with `zoneinfo`) | `publish_round` (D-28, freshness, snapshot age unchanged) | refusal → alert, retried only while freshness can still be met; Q-04 |
| lock | `now ≥ deadline_at` and status open | `lock_round` | already `SYSTEM`-capable; idempotent |
| import results | status locked/settling and relevant fixtures unresolved; periodic (e.g. hourly) until resolved; a `--full` re-check before finalising (6C.4 note) | `import_results` | provider budget per tick and per day |
| settle | after each import that recorded new evidence, and after the cutoff | `settle_round` | idempotent; alerts raised by the service |
| finalise | `now ≥ earliest_finalisation` (S-02, D1) and `finalise-check` ready (no blocking alert, all resolved) | `finalise_round` (includes weekly publication and championship processing) | never early: the service enforces the clock; no time override for `SYSTEM` |

* **Idempotency and duplicates:** every step is already idempotent in its service; the runner additionally takes `ops.try_job_lock(job, scope)` (transaction-scoped advisory lock per step and round) and the existing stream lock; concurrent ticks or workers skip (recorded as `skipped`).
* **Transactions:** one service call = its existing transaction; the runner never wraps several steps in one transaction, so a crash leaves a consistent state and the next tick resumes.
* **Retries and backoff:** level-triggered retries (the next tick re-evaluates); per-step backoff from `job_runs` history (e.g. after 3 consecutive failures, wait 15 → 60 → 240 minutes) and a cap after which the step is left to an operator with a P1/P2 alert. Provider errors (HTTP 5xx, timeouts, 429) back off; data gaps (provider has no result yet) are normal "not ready" states, not failures.
* **Missed or delayed executions:** none are lost — a tick after downtime performs all overdue steps in order (lock first, then import/settle/finalise). Lock after a missed deadline is safe because the database already refused late entries.
* **Time zones:** all timestamps stored and compared in UTC; only the publish rule is local (Africa/Johannesburg, no DST) and is converted with `zoneinfo`, with tests in a DST zone to prove correctness.
* **Streams:** the runner processes only streams listed in its configuration (Q-06; default `development` and `beta`); **`official` is refused** until D-38 activation (and the series' `started_at` remains NULL). Development rounds keep their synthetic modes and never touch the provider.
* **Audit:** each run is a `job_runs` row (job, scope, args, host, status, api_requests, error); service writes carry `actor_role='system'` and the `job_run_id` where the service records audit.
* **Safe manual intervention:** operators keep every existing command; the runner skips a round whose step is held (e.g. an open blocking alert, a reopened round under review) and never undoes manual work; `--dry-run` shows what would happen; a per-stream pause switch (Q-06) stops automation instantly.

### 3.3 Where it runs [Assumption → Q-07]
Until Phase 10 there is no host. Genuine Beta finalisation (§6) needs the reconciler running reliably for at least one full real week. Options: the owner's Mac (launchd every 5 minutes, laptop awake), a small always-on machine, or a hosted cron later. A decision is needed before Stage F.

## 4. Monitoring, alerting and recovery design [Recommendation]

* **One read-only command:** `diski9 ops status` (human summary, `--json`, exit code 0/1/2 by worst severity) and `diski9 ops check` (run by each tick, after the steps).
* **Checks:**

| Check | Source | Severity |
|---|---|---|
| Scheduler heartbeat: last `tick` older than 30 min while any round is active | `job_runs` | P1 |
| Job failed / repeatedly retried / stuck `running` > 30 min | `job_runs` | P2 → P1 after cap |
| Round open past deadline (not locked) > 15 min | `rounds` | P1 |
| Results still pending after the settlement cutoff; provider import failing | settlement report, `job_runs` | P2 |
| Finalisation eligible but not finalised for > 6 h; blocking alert open | `round_report` | P2 |
| Round under review (reopened) > 48 h | rounds, versions | P2 |
| `inspect_stream` findings (material / repairable) | `championships.verify_stream` | P1 / P2 |
| F4 integrity checks (duplicates, ranks, stored standings vs hash, refunds/voids, audit attribution, streams, **Official not started**) | promoted from `tools/phase6c5_f4_integrity.py` into `src/` as a read-only service | P1 |
| Audit integrity: insert-only triggers present; every final score set has a finalise audit record | catalogue + audit | P1 |
| Database health and migration head | `check_health` | P1 |
| Provider daily budget low | client header | P3/P2 |

* **Notification [Q-08]:** default output to the log, `job_runs` and `ops status`; for unattended operation one optional outbound channel configured by environment — a single webhook (e.g. Slack/Telegram/ntfy) or e-mail via SMTP; `httpx` is already a dependency. Activating any external service needs owner approval.
* **De-duplication and escalation:** an alert is notified when it first appears, then re-notified every 6 h (P1) or 24 h (P2) while it persists, and a "resolved" message when it clears; state kept statelessly by recomputing each tick and recording notifications in `job_runs.args` (no migration), or in an `ops_alerts` table with acknowledgement (optional migration, Q-09).
* **Operator recovery runbook** (`docs/operator_runbook.md`): per alert — what it means, what to check (`ops status`, `round finalise-check`, `settle alerts`, `competition verify`), and the approved command to fix it (re-run a step, resolve an alert, correct/reopen with the owner, `competition repair`), plus "pause automation" and "resume".
* **HTTP health endpoint [Q-10]:** optional `/healthz` (database reachable, migration head) for a future host; small app change; not needed while CLI monitoring suffices.

## 5. Operational administration recommendation [Recommendation]

**Keep the MVP CLI-first; no web admin dashboard in 6C.6.** Rationale: one to two operators, all write operations already exist as audited CLI commands with operator authentication; a web admin would add an authenticated privileged web surface (CSRF, sessions, permission sweep) without operational need.

| Need | Tool |
|---|---|
| Create/publish rounds | `round create/publish` (after S-07) or the scheduler (Q-04) |
| Round and job status | **new** `ops status`, `jobs list` |
| Settlement and finalisation readiness | existing `settle status`, `round finalise-check`; summarised in `ops status` |
| Failed imports | `jobs list --failed`, `results show` |
| Reopen/correct/re-finalise | existing `round reopen`, `results correct`, `round finalise` |
| Championship integrity | existing `competition verify/repair`; `ops check` |
| Operators and roles | `account …` (after S-07), `account list-privileged` |
| Audit history | **new** read-only `audit list` (filters: action, actor, target, since) |
| Recovery | runbook + `jobs run <step>`, `jobs pause/resume` |

Backlog included: one-line operator errors instead of tracebacks (6C.3); consistent exit codes; `settle run` without `--confirm` stays as is (6C.4, documented); `results import --full` before finalising inside the scheduler (6C.4). A read-only web status page can be reconsidered in Phase 10 if hosting makes the CLI inconvenient.

## 6. Release-gate and backlog allocation matrix [Recommendation]

| Item | 6C.6 | Prepare in 6C.6, implement later | Later phase | Dependencies | Acceptance evidence |
|---|---|---|---|---|---|
| **S-07** | **Implement (Stage B)** | — | — | `authenticate_operator` (exists) | pty tests; F2 assessment tests inverted; audit attribution |
| Production scheduling | **Implement (C)** | — | hosted trigger in Phase 10 | S-07 (`SYSTEM` vs person separation) | clock-injected lifecycle tests; overlap tests; a real development week |
| Monitoring / alerting | **Implement (D)** | external channel activation (Q-08) | hosted alerting in Phase 10 | scheduler | check tests with seeded faults |
| Operational admin + 6C.3/6C.4 CLI backlog | **Implement (E)** | — | web status page (Phase 10, optional) | B | CLI tests |
| **Genuine Beta finalisation (S-02 rule, real clock)** | **Demonstrate (F)** | — | — | scheduler running on a chosen host for ≥ 1 real week (Q-07), D-28-feasible real pool | a real Beta round published, locked, settled and finalised by the clock with no override; audit and `job_runs` evidence |
| D-29 real pool validation | — | reporting helper from the research collector data (optional) | before Official (requires 6–8 pools from 27 Nov 2026 onward) | D-29b collector | validation report |
| D-36 deletion and retention | — | design note (optional) | before hosting real participants (Phase 10) | hosting, legal review | deletion workflow tests |
| D-38 Official activation | — | activation checklist document | at launch approval | D-29, S-07, hosting | owner approval |
| Hosted Supabase acceptance | — | test plan | Phase 10 | hosting | hosted test run |
| ML-01 Match Lab race | — (separate authorisation) | — | before private beta | — | regression test of late responses |
| Backup and restore drill | Q-12 (local drill) | runbook | hosted backups in Phase 10 | — | restore reproduces standings and fingerprint |
| Accepted 6C.5 limitations / deferred improvements | — | — | as recorded | — | — |

## 7. Proposed Phase 6C.6 architecture [Recommendation]

### 7.1 Components (existing in plain text, **proposed in bold**)

```
            human operator (terminal)                    host trigger (cron/systemd/launchd;
                    │ password (getpass)                  later the hosting platform)
                    ▼                                                  │ every 5 min
        authenticate_operator ──► Supabase Auth                         ▼
                    │ Principal (DB roles, T-12/T-14)        **diski9 jobs tick** (SYSTEM actor)
                    ▼                                                  │ allowlisted steps,
   CLI: round / results / settle / competition /                       │ advisory locks,
        **account (S-07)**, **ops status**, **audit list**,            │ backoff, stream config
        **jobs run|list|pause|resume**                                 │
                    │                                                  │
                    └──────────────┬───────────────────────────────────┘
                                   ▼
      services (unchanged rules): rounds (create/publish/lock) · results.import ·
      settlement · corrections.finalise → competition publication → championships
                                   │                    │
                                   ▼                    ▼
       PostgreSQL app schema: rounds, entries, results, settlement, score sets,
       championships, audit_log (insert-only), job_runs, domain_events
                                   │
                                   ▼
        **ops check**: job health · stuck rounds · readiness · inspect_stream ·
        **integrity service (from F4 tool)** · audit integrity · db health
                                   │
                                   ▼
        log + job_runs + **optional notifier (webhook or e-mail)** → operator → runbook
```

Provider (API-Football) is called only by results import and the pre-publication
refresh, within the existing budget; the Dash app is unchanged (reads only).

### 7.2 Integration and trade-offs
* **Python/CLI:** new modules `backend/jobs/` (runner, steps, policy) and `backend/ops/` (checks, notifier, integrity), CLI subcommands in the existing parsers.
* **Dash:** untouched (optionally `/healthz`, Q-10).
* **PostgreSQL:** existing tables; locking via existing advisory locks; no new database.
* **Supabase:** used only for human authentication (unchanged).
* **Security:** smaller attack surface than a web admin; `SYSTEM` cannot exceed rule-guarded steps; human actions always authenticated.
* **Complexity/cost:** one command plus a host trigger; no new infrastructure; no new runtime dependency.
* **Reliability:** level-triggered reconciliation tolerates missed runs and restarts; idempotent services.
* **Deployment:** host-neutral; the trigger is the only host-specific piece (examples for cron, systemd and launchd as documentation).

### 7.3 Changes needing separate approval
* **Migrations: none required for the core.** Optional: (M1) `ops_alerts` with acknowledgement (Q-09); (M2) per-stream automation settings in the database instead of environment configuration (Q-06). Either would move the head to `app_0008`.
* **New dependencies:** none.
* **External services:** notification channel (Q-08); any always-on host for the Beta week (Q-07).
* **Fingerprint:** unaffected (no engine, rule or configuration change).

## 8. Proposed staged implementation plan [Recommendation]

The owner's A–G structure is retained with one adjustment: **operational administration items that S-07 and the scheduler need (one-line errors, `jobs` and `ops` commands) move into the stage that needs them**, leaving Stage E small. Genuine Beta finalisation needs calendar time, so Stage F starts with the real week as soon as C–D are accepted.

| Stage | Scope (exclusions) | Reuse | Changes | Tests and acceptance | Risks | Decisions | Complexity |
|---|---|---|---|---|---|---|---|
| **A** Design (this) | proposal only | — | docs | owner approval | — | all of §9 | — |
| **B** S-07 | remediate the 10 commands + bootstrap/recovery; one-line errors for them (no scheduler) | `authenticate_operator`, `authorize`, pty test harness | `cli.py` round/account, `privileged.py` signatures, docs | pty tests per command, inverted F2 tests, audit attribution, full regression, CI | breaking operator habits; scripts using `--by-email` | Q-01–Q-03 | Medium |
| **C** Scheduler | `jobs tick/run/list/pause/resume`, lock/import/settle/finalise steps, policy, backoff, stream allowlist; publication only if Q-04 (no notifications yet) | services, `job_runs`, advisory locks | `backend/jobs/`, CLI, host trigger examples | clock-injected lifecycle tests (whole week), overlap/concurrency tests in separate processes, crash-resume, missed-run catch-up, DST tests, provider failure mocks, no Official; full regression | scheduler acting on wrong stream; provider budget | Q-04–Q-07 | High |
| **D** Monitoring | `ops status/check`, integrity service, audit integrity, notifier (if approved), runbook | `inspect_stream`, F4 tool, `round_report` | `backend/ops/`, CLI, docs | seeded-fault tests for every check (negative controls), notification dedupe tests | alert fatigue; false positives | Q-08–Q-10 | Medium |
| **E** Admin + backlog | `audit list`, remaining one-line errors, operator guide updates | existing CLI | small CLI changes, docs | CLI tests | low | — | Low |
| **F** Integration and Beta acceptance | full lifecycle integration on PostgreSQL; security sweep (no `SYSTEM` escalation, no `--by-email`); reliability (kill/restart mid-tick); **genuine Beta finalisation on a real round** by the clock; optional restore drill | all | none expected | real-week evidence; full regression; CI | calendar dependency; host uptime | Q-07, Q-11, Q-12 | Medium (elapsed ≥ 1 week) |
| **G** Acceptance | handover, release-gate status | — | docs | owner acceptance | — | merge/release (separate) | Low |

## 9. Risk register [Recommendation]

| ID | Risk | Category | Likelihood / impact | Mitigation |
|---|---|---|---|---|
| R1 | Operator impersonation via `--by-email` persists until Stage B | Security | Medium / High before hosting | B first; no hosting or Official before B (gate) |
| R2 | Scheduler escalates beyond lifecycle steps | Security | Low / High | allowlist; services refuse `SYSTEM`; tests per human-only service |
| R3 | Lockout of all owners | Security/ops | Low / High | bootstrap/recovery design (Q-03), audited |
| R4 | Premature finalisation | Integrity | Very low / High | service enforces S-02 on the database clock; no override for `SYSTEM`; tests |
| R5 | Duplicate or concurrent runs | Integrity | Medium / Medium | advisory locks, idempotent services, F3 concurrency fixes, overlap tests |
| R6 | Provider outage or missing results | Operations | Medium / Medium | backoff, cutoff voids per `settle/v1`, alerts, `--full` re-check |
| R7 | Provider budget exhaustion | Operations | Low / Medium | per-tick and daily caps; budget check |
| R8 | Missed ticks (host asleep/down) | Operations | Medium / Medium | level-triggered catch-up; heartbeat alert; DB deadline guards |
| R9 | Official stream touched before D-38 | Integrity/compliance | Very low / High | stream allowlist refuses official; integrity check for `started_at` |
| R10 | Alert noise hides real issues | Operations | Medium / Low | severities, dedupe, re-notify intervals |
| R11 | Secrets exposure (API key, DB URL, webhook) | Security | Low / High | host secret store/.env, never logged or audited |
| R12 | Genuine Beta week fails (no feasible pool, host unavailable) | Delivery | Medium / Medium | start early in F; D-28 refusal is a valid outcome to retry next week |
| R13 | Regression of accepted 6C.5 behaviour | Integrity | Low / High | full regression each stage; fingerprint and head checks |
| R14 | Deployment assumptions baked in early | Deployment | Medium / Medium | host-neutral trigger; hosting choices deferred to Phase 10 |

## 10. Decisions requiring owner approval

| ID | Decision | Recommendation |
|---|---|---|
| Q-01 | Remove `--by-email` entirely (clear error pointing to `--operator`) rather than deprecate | Remove |
| Q-02 | `round lock` by a person also requires password authentication; unattended lock only via `jobs` (`SYSTEM`) | Yes |
| Q-03 | Bootstrap requires the target's password; add audited break-glass `account recover-owner` (host flag + target password) vs manual SQL only | Add the command |
| Q-04 | May the scheduler **create and publish** rounds as `SYSTEM` (Beta/development), or does publication stay a weekly human action? | Allow for beta/development, behind the stream allowlist; human publication remains possible |
| Q-05 | Provider budget for automation (pre-publication refresh and hourly result imports) | Caps per tick and per day, set in configuration |
| Q-06 | Stream automation and pause control via environment configuration (no migration) vs a database setting (migration M2) | Environment configuration |
| Q-07 | Where the reconciler runs for the genuine Beta week (owner's Mac with launchd, an always-on machine, or a hosted cron) | Decide before Stage F |
| Q-08 | Notification channel (none / webhook / e-mail) and its activation | One webhook, owner-approved, activated in Stage D |
| Q-09 | Alert state statelessly in `job_runs` vs an `ops_alerts` table with acknowledgement (migration M1) | Stateless first |
| Q-10 | Add `/healthz` now or in Phase 10 | Phase 10 |
| Q-11 | Accept the D1 interpretation: "deadline + 24 h" = S-02 earliest finalisation as implemented | Accept (no rule change) |
| Q-12 | Include a local backup/restore drill in Stage F (from the original 6C.6 plan) | Yes (local, small) |
| Q-13 | Branching: continue 6C.6 on `feature/phase-6c6-operations` from `630e021`, or merge/release 6C.5 to `main` first | Owner's choice; merging first gives a clean base |
| Q-14 | Use Beta for the genuine-finalisation demonstration with real entrants; if fewer than 5 entrants the round is practice (D-32b) — acceptable as evidence of the finalisation rule, with championship processing evidenced separately | Accept |

## 11. Owner decisions at Stage A (21 Nov 2026) — approved design

| ID | Decision |
|---|---|
| Q-01 | **Approved.** `--by-email` is removed as a means of identifying privileged human operators; `authenticate_operator` and the verified identity are used; clear guidance for the former syntax. |
| Q-02 | **Approved.** Manual locking requires an authenticated operator; unattended locking only through the future scheduler as `SYSTEM`, within the approved allowlist. |
| Q-03 | **Approved in principle, subject to a detailed security design.** Bootstrap-owner must verify control of the target account. An emergency owner-recovery mechanism may be provided only if it requires explicit recovery authorisation, verifies the target account's credentials, is restricted to a secured host environment, is fully audited, fails closed and prevents arbitrary owner impersonation or privilege escalation; its threat model, authorisation mechanism and safeguards must be documented first, and if they cannot be met without a new vulnerability, the owner decides before implementation. |
| Q-04 | **Approved with a phased rollout.** Phase 1 (6C.6): supervised automation — prepare and validate weekly challenges automatically, **authenticated operator approval before publishing**, automate lock, results import, settlement, finalisation and championship processing. Phase 2: automatic publication only after several reliable weekly cycles and separate authorisation, fail-closed on eligibility, freshness, provider limits, integrity and every mandatory check. Phase 3: autonomous operation with monitoring and secure intervention. 6C.6 designs for automatic publication **without enabling it**; no autonomous publication pathway in Stage B. |
| Q-05 | **Approved in principle.** Configurable per-tick and daily provider limits, fail-closed when exhausted. Current provider budgets unchanged; no automated provider calls in Stage B; exact limits and refresh frequency proposed for Stage C approval. |
| Q-06 | **Approved.** Environment-based configuration (no migration) with explicit stream allowlisting, safe defaults and an emergency pause; Official automation disabled. |
| Q-07 | **Deferred to Stage F planning.** Host-neutral architecture; before Stage F a recommendation comparing the owner's Mac, an always-on machine and a hosted scheduler (a sleeping laptop is not assumed reliable). |
| Q-08 | **Approved in principle.** One configurable channel, preferably a webhook, with secrets handling and failure isolation; provider, destination and activation approved separately in Stage D. |
| Q-09 | **Approved.** Start with `job_runs` and existing operational records; no alerts table unless acknowledgements prove necessary. |
| Q-10 | **Approved with qualification.** The public `/healthz` endpoint is deferred to hosting, provided 6C.6 delivers adequate internal health and scheduler-status checks. The original 6C.6 roadmap listed a health-check endpoint; it is deferred because no host exists yet and the CLI `ops status`/`app-db check` cover operator needs until then. |
| Q-11 | **Conditional approval; reconciled (§12).** The implemented S-02 rule is preserved unchanged. |
| Q-12 | **Approved.** A limited local backup-and-restore drill in Stage F on isolated databases. |
| Q-13 | **Approved.** Continue on `feature/phase-6c6-operations`; no merge of 6C.5 or 6C.6 into `main` yet; merge, tag and release are separate decisions. |
| Q-14 | **Approved with qualification.** A genuine Beta round on the real database clock demonstrates finalisation eligibility; a practice round (fewer than five entries) may demonstrate the timing rule but is **not** evidence of the competitive championship lifecycle, which needs separate evidence; no time override may be used to claim genuine Beta finalisation. |

## 12. Q-11 reconciliation: entry deadline, settlement cutoff and earliest finalisation

**Finding: imprecise wording, not a contradiction.** No competition rule is changed.

* **Authoritative decision:** **S-02** (decision register; approved in 6C.4 as owner
  question Q-2): *earliest finalisation = max(fixed cutoff, last material settlement
  change) + 24 hours (database clock)*, and only with every relevant prediction
  resolved, no unresolved settlement-blocking alert and all settlement and
  round-validity checks complete. It resolved the 6C.4 conflict between three
  readings of R-14 ("24-hour correction window before a round is final") recorded
  in `phase6c4_implementation.md` §8. `settle/v1` §2 (worked example: cutoff
  Wednesday 19:00 UTC, finalisation Thursday evening), 6C.4 §8 and the 6C.5
  specification §4.3 all state the same rule.
* **The three times:**

| Term | Definition | Fixed when | Effect |
|---|---|---|---|
| **Entry deadline** (`deadline_at`) | first scheduled kickoff of the round sheet minus the schedule's deadline buffer (15 min) | at publication | drafts and submissions refused by database triggers after it; the round can then be locked |
| **Settlement cutoff** (`settle_cutoff_at`) | latest scheduled kickoff at publication + 48 h (`settle/v1` §2) | at publication; never moves | decides postponement/abandonment voids (V1/V4); results completed after it do not count |
| **Earliest finalisation** | `max(settle_cutoff_at, last material settlement change) + correction_window_hours (24)` | computed (`settlement.earliest_finalisation`) | finalisation refused before it |

* **Changes after the cutoff:** a material settlement change after the cutoff moves
  the start of the 24-hour window to that change (the `max`); the final settlement
  run made inside `finalise_round` also refuses and restarts the window if it finds
  a material change. Non-material changes (for example a score correction that
  changes no verdict, metadata, repeated identical observations) never restart it.
* **Consistent enforcement:** `corrections.finalise_round` is the only code that
  sets a round `final` (`rounds_repo.set_status(..., "final")`); the CLI `round
  finalise`, the development runner and any future scheduler call it. The time
  comes from the database clock; the development-only `as_of` override is refused
  for real rounds, in production and for the `SYSTEM` actor
  (`settlement.evaluation_time`), so scheduled finalisation cannot be earlier than
  manual finalisation.
* **Wording to read as S-02:** "deadline + 24 h", "deadline-plus-24-hour rule" and
  "real 24-hour window" in 6C.5 F-stage records, the Stage G handover and the Phase
  6C plan's outstanding-work register mean the S-02 earliest finalisation above
  (not entry deadline + 24 h). Those living registers carry a clarification note;
  historical records are not rewritten.
