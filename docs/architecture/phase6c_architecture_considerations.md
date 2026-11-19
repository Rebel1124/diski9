# Phase 6C — Architecture Considerations (for discussion)

**Status:** discussion paper, not an instruction to implement. It lists the
architectural decisions needed before Phase 6C, with a recommended default for
each. Product decisions referenced here (D-xx) are in the
[decision register](../product/weekly_challenge_decisions.md) and the
[outstanding decision review](../product/weekly_challenge_phase6c_decision_review.md).
Nothing here is approved until you say so. The detailed schema proposal remains
in the [technical design](weekly_challenge_design.md) §4.

## 1. Guiding approach

* **One application, one database, scheduled CLI jobs.** A modular monolith: the
  existing Python package and Dash app, a service layer for every write, and the
  existing CLI for jobs. No microservices, message queues or separate API service
  at launch.
* **The database is the authority.** Browser stores hold drafts and preferences
  only; every rule (deadline, 4/3/2, eligibility, settlement) is enforced on the
  server.
* **Insert-only history, derived standings.** Facts are appended; points,
  counters and standings are computed from current facts. Corrections and
  reassessments then never double-count.
* **Pure engines stay pure.** `challenge.structured`, `challenge.analysis` and
  `challenge.scoring` are reused unchanged; the new code wraps them with
  persistence.

```
 browser ──▶ Gunicorn ─▶ Flask + Dash app ──▶ service layer ──▶ pure engines
                         (sign-in routes,      (accounts, rounds,   (portfolio, analysis,
                          pages, callbacks)     submissions,         scoring; unchanged)
                                                settlement, audit)
                                                     │
                                                     ▼
                                            PostgreSQL (production) / SQLite (local)
                                                     ▲
 platform scheduler ──▶ diski9 CLI jobs ─────────────┘
   refresh-data · challenge publish · lock · settle · finalise
```

## 2. Decisions to make

### AD-01 Database and persistent storage (D-03)

* **Recommendation:** PostgreSQL in production; SQLite for local development, the
  research tooling and fast tests; SQLAlchemy Core and Alembic for both. One
  database holds the existing football data and the new challenge tables, so
  settlement reads results and writes settlements in one transaction.
* **Decide:** PostgreSQL target (yes or no); whether immutability is enforced by
  database triggers on both engines or by the service layer plus tests (triggers
  recommended where cheap, as in the existing `forecast_snapshots`).
* **Implications:** a PostgreSQL test job for locking and trigger tests; backups
  and point-in-time recovery from the managed database.

### AD-02 Authentication and user accounts (D-01, D-05, D-36, D-37)

* **Recommendation:** in-app OpenID Connect with a managed provider, signed
  session cookies from Flask, no passwords stored.
* **Data model:** `users` (internal ID, display name, role, terms version,
  created, deleted or pseudonymised), `user_identities` (provider, subject), a
  display-name history table. Results reference the internal user ID only, so
  pseudonymisation (D-36) never breaks history.
* **Decide:** approach and first provider; session lifetime; whether the Match Lab
  and leaderboards stay readable without sign-in (recommended: yes).

### AD-03 Roles and permissions (D-34)

* **Recommendation:** three roles (`participant`, `operator`, `owner`) mapped to
  named capabilities in code, checked in the service layer. Every operator action
  (publish, postpone, void round, result override, reopen, rename) requires a
  reason and writes an audit record.
* **Separate from roles:** an `entitlements` table (user, feature, source, valid
  from and to) for owner-only and future premium features. Lucy is gated by an
  entitlement initially granted only to the owner; premium plans later grant
  entitlements without touching roles.
* **Decide:** role set and capability list; owner assignment by server CLI only.

### AD-04 Server-authoritative round management (D-06, D-11, T-07)

* **Recommendation:** rounds are database records with status
  (`draft → open → locked → settling → final`, or `postponed`), a frozen round
  sheet (fixtures and offers, insert-only after publish), the deadline and
  configuration version stored at publish, and the opening checks recorded.
  Deadlines are enforced by the server clock inside each write transaction, so no
  job is needed for correctness.
* **Replaces:** the prototype's in-memory pinned snapshot; a restart no longer
  changes anything.
* **Decide:** publish schedule and window (D-11); how the operator corrects a
  publish mistake before the deadline (recommended: cancel and republish with a
  new round version only while no entries exist; otherwise void).

### AD-05 Scheduled jobs and automated settlement (D-08, D-32, D-33, D-32b, D-35)

* **Recommendation:** the platform scheduler runs CLI commands; each command is
  idempotent and takes a database lock (an advisory lock or a lock row) so two
  runs never overlap. A `job_runs` table records start, finish, outcome and
  counts. Jobs: odds and data refresh; publish (Thursday); lock stamp (after the
  deadline); settle (hourly in match windows); finalise (after the 24-hour
  correction window).
* **Settlement pipeline per run:** new result observations → selection verdicts
  (V1–V5) → entry settlements (D-32 payouts with D-15 rounding; D-33 refunds) →
  D-32b evaluation once nothing is pending → weekly ranking and points via
  `challenge.scoring` → championship aggregation. Each step writes only changed
  rows.
* **Decide:** scheduler (platform cron recommended over an in-process scheduler,
  which would run once per web worker); alerting on failed or late jobs.

### AD-06 Portfolio lifecycle and historical records (T-09, T-10)

* **Recommendation:** an entry per user and round; every submission version
  insert-only with the nine selections, copied offer values, eight-state summary
  and an inputs hash; withdrawal as an insert-only event (T-09); the locked set
  stamped at the deadline. Your View estimates stored per user and fixture with
  the model-context stamp, private, never used in scoring (T-10).
* **Decide:** whether to keep a full submission history visible to the
  participant (recommended: yes, read-only) and the retention period for
  superseded drafts (recommended: keep; they are small).

### AD-07 Championship progression and leaderboards (D-26 to D-31, D-38, T-11)

* **Recommendation:** designations as insert-only records (T-11); weekly scores
  stored per settlement run, latest current; championship membership, round
  numbers, the counter and standings derived by query from current designations
  and scores; a frozen snapshot written when a championship completes. Leaderboard
  queries cached per process for a few minutes and invalidated after settlement.
* **Decide:** whether championships carry an `official` flag (D-38); public
  visibility rules (D-04).

### AD-08 Idempotency, concurrency and transaction integrity

* **Recommendation:**
  * submissions: one transaction with a row lock on the entry, an optimistic
    `version`, a client idempotency key per Submit click, and unique constraints
    (one entry per user and round; one fixture per submission);
  * jobs: database lock per job and round; reruns insert nothing new when nothing
    changed;
  * derived values never stored as running totals.
* **Tests:** deadline race, duplicate click, simultaneous edits from two tabs,
  overlapping settlement runs, rerun with no new information.

### AD-09 Auditability and result corrections (R-14, T-06, D-35, D-32b)

* **Recommendation:** an `audit_log` (actor, action, target, reason, before and
  after, time) for every operator action; result observations insert-only with a
  source (`api-football` or `operator`); settlement runs recorded; a correction
  re-runs the whole round, including D-32b reassessment; after a championship is
  frozen, changes need the audited reopen path.
* **Decide:** operator override policy (D-35); who may reopen (recommended:
  owner only).

### AD-10 Integration with the existing Python and Dash application

* **Recommendation:**
  * keep Dash on Flask; add sign-in and sign-out routes and a session check;
    callbacks obtain the current user from the server session, never from a
    store;
  * every write callback calls the service layer; callbacks never write SQL
    directly;
  * replace the prototype's `sessionStorage` authority (`ch-session`, `state.reconcile`)
    with server reads; keep browser storage for drafts and preferences only;
  * run under Gunicorn with several workers; no shared in-process state that
    matters (caches are per process and safe to lose);
  * the accepted Phase 6B UI is kept; only its data source changes.
* **Decide:** whether drafts are server-side as well (recommended: no for 6C;
  the confirmed submission is what matters).

### AD-11 Future deployment requirements (D-02, Phase 10)

* **Recommendation:** a container image; configuration and secrets from the
  environment (the API-Football key stays server-side, as today); health check
  endpoint; structured logs; managed database backups; separate staging and
  production databases; database migrations run as a release step.
* **Decide:** the hosting provider and region (can wait until Phase 10 if 6C stays
  host-agnostic).

## 3. Accommodating later phases without rework

| Future need | What Phase 6C provides |
|---|---|
| **Lucy, AI portfolio assistant (Phase 7), owner-only at first** | An entitlement checked server-side on every Lucy route and callback; Lucy as its own module calling the language-model API from the server (keys in the environment); read access to rounds, portfolios and analysis through the service layer, never direct writes to competition data; a usage and audit log. Voice (LiveKit) and YouTube co-presenting are separate services added in Phase 7 behind the same entitlement |
| **Private owner-only functionality** | The `owner` role and owner entitlements; owner assignment only by server CLI |
| **Achievements and badges (Phase 9)** | Insert-only domain events (submission confirmed, round settled, recovery, top-ten finish, championship completed) written by the service layer; achievements can later be derived from events and history without changing the competition tables |
| **Premium subscriptions** | Entitlements with validity periods and a source (for example `manual` now, a payment provider later); no payment integration in 6C |
| **European expansion (Phase 8)** | Leagues are already data; round sheets record competition IDs; configuration versions allow a new structure without editing old rounds |

## 4. Suggested order of discussion

1. AD-01 and AD-02 (database and sign-in), since everything else depends on them.
2. AD-03 (roles and entitlements), needed for operator actions and Lucy.
3. AD-04, AD-05 and AD-09 (rounds, jobs, settlement, audit), which carry the
   approved D-32, D-33 and D-32b rules.
4. AD-06 to AD-08 and AD-10 (lifecycle, championships, integrity, Dash).
5. AD-11 (deployment), which can wait if 6C stays host-agnostic.
