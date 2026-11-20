# Competition backend: PostgreSQL foundation (Phase 6C.1)

The competition backend stores accounts, rounds, frozen snapshots, portfolios,
results, settlements, championships and audit records in **PostgreSQL**. It is
separate from the existing **SQLite football store** (`data/diski9.sqlite`,
migrations in `migrations/`), which is unchanged during Phase 6C (D-39).

Phase 6C.1 delivers the database foundation only: local infrastructure, settings,
engine and transactions, the full schema with its migrations and protections,
plain data-access functions, PostgreSQL tests and CI. It does **not** yet provide
sign-in (6C.2), portfolio workflows (6C.3), settlement (6C.4), leaderboards
(6C.5) or administration (6C.6), and the accepted Phase 6B UI still uses its
browser-session prototype.

## 1. Local setup

**PostgreSQL version:** 17 (in `docker-compose.yml` and CI). PostgreSQL 17 is
a current, supported major version (community support into 2029) available on
every managed provider considered for Phase 10. The schema uses nothing newer
than PostgreSQL 13 (`gen_random_uuid()`), and the test suite has also been run
against PostgreSQL 16.

Prerequisites: Docker with Docker Compose, and `uv`.

1. Create your local `.env` from the template and choose a local password:

```bash
cp .env.example .env
```

2. Start PostgreSQL (data persists in the Docker volume `diski9_pgdata`; the port
   is bound to 127.0.0.1 only):

```bash
docker compose up -d
```

3. Check that it is healthy:

```bash
docker compose ps
```

4. Create the competition schema:

```bash
uv run diski9 app-db upgrade
```

5. Check connectivity and the schema revision:

```bash
uv run diski9 app-db check
```

Stop PostgreSQL (data kept):

```bash
docker compose down
```

Reset everything (this permanently deletes all local competition data in the
volume; the next `up` recreates an empty database and the test database):

```bash
docker compose down --volumes
```

On first start, `docker/postgres/init/01-roles-and-test-database.sql` creates the
`diski9_test` database and the `diski9_app` runtime role.

## 2. Configuration

Settings use the prefix `DISKI9_APP_` (`diski9.backend.db.settings`); see
`.env.example`. Real credentials never go into git.

| Variable | Default | Meaning |
|---|---|---|
| `DISKI9_APP_DATABASE_URL` | none | `postgresql+psycopg://user:password@host:port/database` (psycopg 3 driver; anything else is rejected) |
| `DISKI9_APP_TEST_DATABASE_URL` | none | Test database; its name must end in `_test` |
| `DISKI9_APP_ENVIRONMENT` | `development` | `development`, `test` or `production`; production refuses `*_test` databases and `app-db downgrade` |
| `DISKI9_APP_POOL_SIZE` / `_MAX_OVERFLOW` | 5 / 5 | Connection pool per process |
| `DISKI9_APP_POOL_TIMEOUT_SECONDS` | 10 | Wait for a pooled connection |
| `DISKI9_APP_POOL_RECYCLE_SECONDS` | 1800 | Recycle connections |
| `DISKI9_APP_STATEMENT_TIMEOUT_MS` | 15000 | Per-statement limit |
| `DISKI9_APP_LOCK_TIMEOUT_MS` | 5000 | Maximum wait for a row lock |
| `DISKI9_PG_*` | see template | Used only by Docker Compose |

Every connection runs in UTC with the statement and lock timeouts. Passwords are
never logged: URLs are rendered with the password hidden, and validation errors
do not echo their input.

## 3. Migrations

The competition schema has its own Alembic environment in `migrations_app/`
(version table `public.app_alembic_version`), independent of the football
store's `migrations/`.

| Command | Effect |
|---|---|
| `uv run diski9 app-db upgrade` | Migrate to the latest revision (safe to repeat) |
| `uv run diski9 app-db upgrade --revision app_0001` | Migrate to a specific revision |
| `uv run diski9 app-db current` | Show the current and latest revision |
| `uv run diski9 app-db check` | Connectivity, server version, revision; exit code 1 if not up to date |
| `uv run diski9 app-db downgrade --revision base` | Remove the schema (not allowed in production) |

**Workflow for schema changes:** add a new revision under `migrations_app/versions/`
written as explicit SQL (constraints, partial indexes and triggers included),
update `diski9.backend.db.schema` to match, and run the tests;
`test_mirror_matches_migrated_schema` fails if the two disagree. Never edit a
released revision.

## 4. Schema structure

The full design, with the relationship diagram, is in
[`docs/architecture/phase6c_database_design.md`](architecture/phase6c_database_design.md).
Revision `app_0001` creates 37 tables in schema `app` (revision `app_0002`, Phase 6C.2, adds `auth_rate_events`, provider-linked session columns, the beta terms version and row-level security; see [`docs/authentication.md`](authentication.md)):

| Area | Tables |
|---|---|
| Identity and accounts | `users`, `user_identities`, `user_private`, `profiles`, `username_history`, `privacy_history`, `user_roles`, `features`, `entitlement_grants`, `terms_versions`, `terms_acceptances`, `app_sessions` |
| Configuration | `championship_series`, `round_schedules` |
| Rounds and snapshots | `rounds`, `round_status_history`, `round_snapshots`, `snapshot_fixtures`, `snapshot_offers` |
| Private analysis and drafts | `your_view_adjustments`, `portfolio_drafts` |
| Portfolios | `entries`, `submissions`, `submission_selections`, `entry_events` |
| Results and settlement | `result_observations`, `settlement_runs`, `selection_verdicts`, `entry_settlements`, `round_evaluations` |
| Designations and championships | `designations`, `score_sets`, `round_scores`, `championship_freezes` |
| Audit, jobs and events | `audit_log`, `job_runs`, `domain_events` |

Seed data: the features `lucy.research`, `lucy.voice` and `lucy.presenter`
(granted to nobody yet); the `beta` and `official` championship series
(`points-150-75-v2`, ten rounds); and the `weekend` round schedule (eight leagues,
15-minute deadline buffer, 48-hour settlement cutoff, 24-hour correction window,
`broad60-432-v1`, `settle/v1`, beta series). Version 2 (`app_0004`, the current
standard) publishes on **Friday 08:00 SAST** (D-11, revised 19 Nov 2026); version 1
(Thursday 08:00 SAST) is kept for rounds published under it.

**Numbers:** credits and payouts are `numeric(14,2)` and odds `numeric(8,2)`
(exact, matching D-15 rounding); probabilities and expected values are `double
precision` (as the engines compute them; nothing is rounded early). All times are
`timestamptz` in UTC.

## 5. Immutable history and current state

| Kind | Tables | Protection |
|---|---|---|
| **History (insert-only)** | `privacy_history`, `terms_acceptances`, `round_status_history`, `round_snapshots`, `snapshot_fixtures`, `snapshot_offers`, `submissions`, `submission_selections`, `entry_events`, `result_observations`, `selection_verdicts`, `entry_settlements`, `round_evaluations`, `designations`, `score_sets`, `round_scores`, `championship_freezes`, `audit_log`, `domain_events` | Trigger rejects UPDATE, DELETE and TRUNCATE for every role; the runtime role has only SELECT and INSERT |
| **Guarded** | `username_history` (only anonymisation to `[deleted]`, D-36), `entitlement_grants` (one revocation), `job_runs` and `settlement_runs` (a running record may be completed once) | Trigger allows exactly that change |
| **Set-once columns** | `rounds`: published time, deadline, cutoff, finalisation, configuration, rules, scoring and model versions; `entries`: lock time, locked submission, name and privacy mode at lock | Trigger rejects any change once set (a later kickoff change cannot move a published cutoff) |
| **Current-state projections** | `users`, `profiles`, `user_roles`, `rounds.status`, `entries` (current submission, version), drafts, Your View, sessions | Normal updates inside transactions; changes that matter are recorded in history tables |

**Account deletion (D-36)** can coexist with this: personal data lives in
mutable tables (`user_private`, `user_identities`, `profiles`, sessions, Your
View, drafts) that can be deleted or anonymised, and the only personal value in
history, a username, can be replaced by the tombstone. Competition history keeps
only the non-identifying user ID.

## 6. Transaction conventions

* Every write runs inside `diski9.backend.db.transaction(engine)`: one
  transaction, committed on success and rolled back on any exception.
* `read_only(engine)` opens a read-only transaction.
* Repositories (`diski9.backend.repositories.*`) are plain functions that take the
  open connection; they never commit.
* Deadlines use the **database clock** (`db_now`, `transaction_timestamp()`),
  never the application clock.
* Row locks are explicit: `lock_entry` (`FOR UPDATE`) serialises changes to one
  participant's entry; `lock_round_for_submission` (`FOR SHARE`) lets many
  submissions proceed together while blocking status changes;
  `lock_round_for_change` (`FOR UPDATE`) is used by jobs that change a round.
* Optimistic concurrency: `set_current_submission` succeeds only if the entry's
  `version` is unchanged.
* Jobs take a transaction-scoped advisory lock (`try_job_lock`) on `(job, scope)`.

## 7. Database-level protections delivered in 6C.1, and what comes later

| Protection | 6C.1 (database) | Later (service layer) |
|---|---|---|
| Unique identity and username | `UNIQUE (provider, subject)`; case-insensitive `username_key`; format CHECK | 30-day rename rule, blocklist, look-alike checks (6C.2) |
| Ownership | Composite foreign keys tie submissions to the owner's entry and the round's snapshot; selections to offers on that snapshot | User ID taken from the server session (6C.2) |
| One active entry | `UNIQUE (round_id, user_id)` and a single deferred-checked current-submission pointer | Confirm, replace and withdraw workflow (6C.3) |
| Deadlines | Insert trigger on submissions checks `open` status and the database clock; `FOR SHARE`/`FOR UPDATE` ordering with the lock job | Lock job and user messages (6C.3) |
| Idempotency | `UNIQUE (user_id, idempotency_key)` | Returning the existing receipt on a repeated click (6C.3) |
| Strict 4/3/2 | Bucket recorded per selection; nine positions; distinct fixtures | Composition and eligibility validation with the engine (6C.3) |
| Settlement | Revisions unique per entry; `net = gross - 100`; all-void refunds are 100.00; one running settlement per round | `settle/v1`, D-32, D-33 (6C.4) |
| D-32b | Pending predictions force `not_evaluated`; exactly 50% cannot pass; practice rounds have no ranked-entry rule | Evaluation and designation (6C.4) |
| Scoring | Points limited to the approved schedule; top-ten finishes require recovery | Ranking with `challenge.scoring` (6C.5) |
| Audit | Operator rows require actor and reason; audit records insert-only | Operator actions (6C.4, 6C.6) |

## 8. Database roles and permissions

* **Owner (migrator):** the user in `DISKI9_APP_DATABASE_URL` when running
  migrations; owns schema `app`.
* **`diski9_app` (runtime):** created outside migrations (cluster-wide). The
  migration grants it SELECT and INSERT on history tables, the narrow UPDATE on
  guarded tables, and full DML on projections. It has no TRUNCATE.
* For a deployment, create a login user and grant the role, for example:

```sql
CREATE ROLE diski9_web LOGIN PASSWORD '<from your secret store>' IN ROLE diski9_app;
```

  Then run the application with that user, and migrations with the owner.

## 9. Tests

* `tests/backend/` runs against **real PostgreSQL** (no SQLite substitute): schema
  and migration tests, integrity and privilege tests, and multi-connection
  concurrency tests.
* Set `DISKI9_APP_TEST_DATABASE_URL` (a database ending in `_test`). The session
  drops and re-migrates schema `app` in that database, so never point it at real
  data; the guard refuses names without `_test` and refuses production.
* Without the variable the PostgreSQL tests are skipped locally; CI sets
  `DISKI9_REQUIRE_POSTGRES=1`, which turns a missing database into a failure.

Run everything:

```bash
uv run pytest -q
```

Run only the PostgreSQL tests:

```bash
uv run pytest -q tests/backend
```

**CI** (`.github/workflows/ci.yml`): PostgreSQL 17 service, `uv sync --frozen`,
ruff lint and format checks, migration from an empty database (twice, then down
and up again), and the full test suite. No football-API credentials exist in CI
and the API base URL points at a closed port, so no allowance is spent.

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `DISKI9_APP_DATABASE_URL is not set` | Create `.env` from `.env.example` |
| `must be a PostgreSQL URL (postgresql+psycopg://...)` | Use the psycopg 3 driver prefix |
| `database unavailable at postgresql+psycopg://user:***@...` | PostgreSQL not running (`docker compose ps`), wrong port or password |
| `set DISKI9_PG_PASSWORD in .env` from Docker Compose | The password variable is missing |
| PostgreSQL tests skipped | `DISKI9_APP_TEST_DATABASE_URL` not set |
| `the test database name must end in '_test'` | Point tests at `diski9_test` |
| `role "diski9_app" does not exist` in privilege tests | Create it (the compose init script does; or `CREATE ROLE diski9_app NOLOGIN`) |
| `... is not allowed on an insert-only history table` | Expected: history cannot be changed; append a new revision instead |
| `could not obtain lock` / lock timeout | Another transaction holds the row; retry the operation |

## 11. Known limitations and deferred functionality

* No sign-in, sessions or permission checks yet (6C.2); the `app_sessions`,
  `user_roles` and `entitlement_grants` tables exist but nothing uses them.
* Repositories cover the foundation (accounts, rounds and snapshots, entries and
  submissions, jobs and audit); settlement, scoring and championship queries are
  added with their stages.
* The 4/3/2 composition, eligibility and analysis values of a submission are not
  validated by the database; the service layer in 6C.3 will use the existing
  engines for that.
* The UI is not connected to the backend yet (6C.3).
* The football store stays SQLite (D-39); its migration is a separate task.
* Docker could not be used in the Phase 6C.1 build environment; the tests were run
  against a local PostgreSQL 16 server there and against PostgreSQL 17 in CI.

## 12. Competition services and round commands (Phase 6C.3)

Business rules live in `diski9.backend.services` (`rounds`, `snapshots`, `drafts`,
`your_view`, `common`); repositories stay plain data access. Every service takes a
server-built `Principal`, checks a capability, writes in one transaction and uses
the database clock. Errors are typed with user-safe messages
(`services.common`). Details: [Phase 6C.3 record](architecture/phase6c3_implementation.md).

Round commands (server CLI; the acting operator is resolved by verified email, as
for `diski9 account`):

```bash
uv run diski9 round list
```

```bash
uv run diski9 round create --week 2026-W48 --by-email operator@example.test
```

```bash
uv run diski9 round publish --code 2026-W48-weekend --by-email operator@example.test
```

```bash
uv run diski9 round lock --code 2026-W48-weekend
```

```bash
uv run diski9 round dev-open --by-email operator@example.test --deadline-minutes 30
```

`publish` builds the snapshot read-only from the football store (no API request)
and refuses with the reason if the opening rules are not met. `lock` is refused
before the deadline and is idempotent. `dev-open` publishes a development round
from deterministic synthetic fixtures (refused when `DISKI9_APP_ENVIRONMENT` is
`production`). Migration `app_0003` adds draft and Your View versions, the
development flag and the snapshot and draft guards.

Since the checkpoint refinements and Stages E–F:

* services `entries` (confirm, replace, withdraw, re-enter) and `adoption`
  (guest work: plan, then one all-or-nothing transaction);
* migrations `app_0004` (Your View per context, weekend schedule v2 with Friday
  08:00 SAST publication, development rounds kept out of the official series) and
  `app_0005` (per-tab save ordering);
* `DISKI9_SNAPSHOT_MAX_AGE_MINUTES` (1–180, default 60): snapshot construction
  age at publication, in addition to the unchanged odds freshness rule;
* `DISKI9_SHOW_DEVELOPMENT_ROUNDS=1` (refused in production): let `serve` show
  development rounds;
* `round dev-open --mirror-upcoming`: real upcoming fixtures from the football
  store with synthetic odds (development round; nothing is written to the football
  store, no API request).

## Settlement (Phase 6C.4)

Migration `app_0006` adds settlement evidence, development result modes and
settlement versions. Services: `services/results.py` (by-ID provider import,
development result modes and synthetic evidence), `services/settlement.py`
(settlement runs, D-32b, personal results), `services/corrections.py` (corrections,
alert resolution, invalidation, finalisation, owner reopening). Rules:
`challenge/settle.py` (`settle/v1` as amended 19 Nov 2026).

Stage E adds the operator commands (`results`, `settle`, `round invalidate /
finalise / finalise-check / reopen`, development-only `dev-results`), each verifying
the acting person's Supabase password interactively (`backend/auth/operator_cli.py`,
`settlement_cli.py`, read-only reports in `services/settlement_ops.py`); reference:
`docs/operator_settlement_cli.md`. Stage F shows the participant's own results on My
Challenge (`services/participant_results.py`, `app/challenge/results_ui.py`).
Owner acceptance: `docs/phase6c4_local_acceptance_mac.md`. Record:
`docs/architecture/phase6c4_implementation.md` §23–§24.

