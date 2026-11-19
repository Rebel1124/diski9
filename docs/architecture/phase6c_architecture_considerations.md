# Phase 6C — Technical architecture (finalised direction)

**Status:** architecture direction confirmed by the owner at the Phase 6C
architecture finalisation (modular monolith, PostgreSQL, SQLAlchemy 2, Alembic,
pytest, managed OIDC, scheduled CLI jobs). Items still needing approval are
listed in §9. Nothing here is implemented. Companion documents:
* [Proposed database design](phase6c_database_design.md) (schema, diagram,
  constraints, corrections);
* [Authentication provider comparison](auth_provider_comparison.md) (D-01);
* [Phase 6C staged implementation plan](../product/weekly_challenge_phase6c_plan.md);
* [`settle/v1` definitions](../product/weekly_challenge_settle_v1.md) (D-08);
* [D-29 weekly research collection proposal](../research/weekly_pool_collection_proposal.md).

This document supersedes the Phase 6C discussion paper previously at this path.

## 1. Shape of the system

```
 browser ──HTTPS──▶ Gunicorn (N workers)
                     └─ Flask app
                         ├─ auth blueprint: /auth/login, /auth/callback, /auth/logout (OIDC, PKCE)
                         ├─ session middleware: cookie → app_sessions → current user, roles, entitlements
                         └─ Dash app (accepted Phase 6B pages, unchanged layouts)
                              └─ callbacks ──▶ service layer (diski9.backend.services)
                                                 ├─ pure engines (unchanged): challenge.structured,
                                                 │   analysis, scoring, roundsheet maths
                                                 └─ repositories (SQLAlchemy 2 Core) ──▶ PostgreSQL "app"

 scheduler (platform cron; locally: manual or cron) ──▶ diski9 CLI jobs
     publish · lock · results · settle · finalise · purge-sessions
         ├─ read football store (SQLite during 6C) ── copy into snapshots / result observations
         └─ write PostgreSQL "app" through the same service layer

 research collection (D-29) ──▶ its own SQLite file and git files only (no competition access)
```

* **Modular monolith:** one Python package, one deployable container, one
  competition database. No microservices, message queues or separate frontend.
* **New package `diski9.backend`:**
  * `db/` (engine, metadata, migrations helpers), `repositories/` (one module per
    aggregate: accounts, rounds, portfolios, results, settlement, championships,
    audit, jobs);
  * `services/` (transactions and rules: accounts, rounds, portfolios,
    settlement, championships, admin);
  * `auth/` (OIDC client, session store, permission checks);
  * `jobs/` (CLI job implementations).
* **Existing packages stay as they are:** `diski9.challenge` engines, `diski9.app`
  layouts, `diski9.odds`, `diski9.ingestion`, `diski9.screener`, the Goal Model.

## 2. Database and storage

* **PostgreSQL** for the competition backend, locally through **Docker Compose**
  (one `postgres` service with a named volume, plus an optional throw-away test
  database) and in production on a managed host chosen in Phase 10 (D-02).
* **SQLAlchemy 2 Core** (tables and typed queries, no ORM session magic) and
  **Alembic** with a **separate migration environment** for the competition
  schema (`migrations_app/`), so the football store's migrations 0001–0004 are
  untouched.
* **Football store:** stays SQLite during Phase 6C and is migrated to PostgreSQL
  (schema `football`) before hosted deployment; see the database design §12.
* **Testing:** the competition test suite runs against **real PostgreSQL**
  (Docker Compose locally; a PostgreSQL service in continuous integration). Each
  test runs in a transaction or a fresh schema. Concurrency tests open several
  real connections. SQLite is not used for competition tests. Existing tests keep
  their current setup.

## 3. Authentication and sessions (D-01)

* Managed OpenID Connect provider; **recommended: Supabase Auth** (comparison
  document). Authorization code flow with PKCE, ID-token validation, then
  Diski 9's own server-side session (`app_sessions`) in a `__Host-` cookie.
* Session lifetime (proposed): 14 days idle, 30 days absolute; operator and owner
  actions require a sign-in within the last 12 hours.
* CSRF: SameSite=Lax cookie plus an Origin check on every POST (Dash callbacks
  are POST requests).
* No provider tokens are stored after sign-in. Logout revokes the session row and
  calls the provider's logout endpoint.
* Local development and tests use an OIDC test double; end-to-end sign-in tests
  can use the provider's local stack.

## 4. Roles, permissions and entitlements (D-34)

* **Identity** (`users`, `user_identities`), **roles** (`user_roles`:
  participant implicit, operator, owner) and **entitlements**
  (`features`, `entitlement_grants`) are separate tables.
* **Capabilities** are a fixed map in code:

| Capability | Participant | Operator | Owner |
|---|---|---|---|
| Submit, replace, withdraw own entry; edit own profile and Your View | yes | yes | yes |
| Publish or postpone a round; run jobs manually | | yes | yes |
| Correct a result (D-35); void a round (D-32b exceptional) | | yes | yes |
| Rename a user; view audit log | | yes | yes |
| Reopen a finalised round or frozen championship | | | yes |
| Grant or revoke roles and entitlements | | | yes (server CLI for owner) |

* **Entitlements** gate features independently of roles: `lucy.research`,
  `lucy.voice`, `lucy.presenter` are defined, granted initially only to the
  owner. A future premium participant could hold `lucy.research` without any
  operator or owner capability.
* **Enforcement:** one service-layer function per check (`require(user,
  capability)`, `require_feature(user, feature)`), called by every service method
  and by every callback that returns restricted data. Hiding a button is never the
  control; tests call the callbacks and services directly as an unauthorised user.

## 5. Server-authoritative rounds and the portfolio lifecycle

* Rounds come from versioned **round schedules** (D-11): weekend rounds,
  Thursday 08:00 SAST publication, 15-minute deadline buffer (D-06), 48-hour
  cutoff (D-08), 24-hour correction window (R-14), eligible leagues and series
  (beta or official, D-38). Midweek and European schedules are new schedule
  versions, not code changes.
* **Publish** builds the snapshot with the existing round-sheet code (copying
  model probabilities, strict consensus and buckets), runs the opening checks,
  and writes the snapshot and the round in one transaction.
* **Portfolio lifecycle:** draft (optional, server-side convenience) → confirm →
  replace (new version) → withdraw (T-09) → lock at the deadline. Every step is
  one transaction with the protections in the database design §9.
* **Your View** is stored per user (T-10), private, never used in competition
  calculations.
* The prototype's in-memory pinned snapshot, `sessionStorage` submissions and
  `state.reconcile` authority are replaced by server reads; browser storage keeps
  only preferences and unsaved drafts.

## 6. Scheduled jobs and settlement

* Jobs are idempotent `diski9` CLI commands run by the platform scheduler
  (locally by hand or cron). Each takes an advisory lock on `(job, scope)` and
  records a `job_runs` row.

| Job | Default timing (SAST) | Effect |
|---|---|---|
| `refresh-data --with-odds` (existing) | Thursday 07:15 | Football store refreshed before publish |
| `challenge publish` | Thursday 08:00 | Snapshot, opening checks, round opened or postponed |
| `challenge lock` | Every 5 minutes; acts after a deadline | Round locked, locked set stamped, base designation written |
| `challenge results` | Hourly during match windows; daily until the cutoff | Result observations copied in |
| `challenge settle` | After each results run | Verdicts, settlements, D-32b, scores |
| `challenge finalise` | Hourly; acts 24 hours after the last change once nothing is pending | Round final; championship freeze when the tenth round is final |
| `purge-sessions` | Daily | Expired sessions removed |

* Deadlines are enforced inside write transactions by the database clock; the
  lock job only records what has already become true.
* Settlement uses the approved rules: `settle/v1` verdicts (D-08, pending final
  approval of the exact definitions), D-32 payouts with D-15 rounding, D-33
  refunds, D-32b round evaluation (competitive rounds: majority played and five
  ranked entries; practice rounds: majority played only, D-32b-Q1), scoring with
  `challenge.scoring` (`points-150-75-v2`, D-26).

## 7. Championships, history, audit and corrections

* Designations (T-07, T-11) and score sets are insert-only; championship
  membership, numbering, the counter and standings are derived; a freeze is
  written when a championship completes (database design §7, §10).
* Every operator action writes an `audit_log` record with actor, reason, before
  and after. Result corrections (D-35) store the original and corrected values.
* Corrections re-run settlement for the whole round (T-06), including D-32b; a
  frozen championship needs the audited reopen path.

## 8. Extensibility boundaries (not implemented in Phase 6C)

| Future phase | Integration boundary prepared in 6C |
|---|---|
| **Phase 7 — Lucy** (qualitative research, private workspace, validated tools, LiveKit voice, YouTube presenter mode) | A future `diski9.lucy` module behind `require_feature('lucy.*')`; its own tables (workspace, notes, tool-call audit) in a separate schema; read-only access to rounds, snapshots and analysis through service-layer query functions ("validated tools"), never direct writes to competition tables; model-provider and LiveKit credentials server-side only; voice and presenter mode as separate entitlements and, if needed, a separate process using the same database and auth |
| **Phase 8 — Champions League, optional Europa League** | New competitions in the league registry, a midweek round schedule version, and a configuration version if the structure changes; snapshots already store competition IDs |
| **Phase 9 — badges and achievements** | `domain_events` written in Phase 6C; achievements derived later from events and history without changing competition tables |
| **Premium features** | `entitlement_grants.source = 'subscription'` and validity periods; a future billing integration writes grants only; no payment code in 6C |

## 9. Decisions still needed for the architecture

| Item | Recommendation | Needed by |
|---|---|---|
| D-01 provider | Supabase Auth | Start of 6C.2 |
| D-08 exact definitions | Approve `settle/v1` as written (cutoff from the latest scheduled kickoff at publish + 48 h) | Start of 6C.4 |
| Session lifetimes | 14 days idle, 30 days absolute, 12-hour re-authentication for operator actions | 6C.2 |
| Continuous integration | Add a CI workflow with a PostgreSQL service (the repository has none today) | 6C.1 |
| Football-store migration timing | Before hosted deployment (late 6D or Phase 10), separately approved | Before Phase 10 |
| D-29 collection activation | Branch, schedules and the collector task (proposal §11) | Before 26 November |

## 10. Implementation decisions taken in Phase 6C.1

| Topic | Decision |
|---|---|
| PostgreSQL version | 17 locally (Docker Compose) and in CI; schema compatible with 13+ (tested on 16 as well) |
| Driver | psycopg 3 (`postgresql+psycopg://`); other URLs are rejected |
| Migrations | Separate Alembic environment `migrations_app/`; version table `public.app_alembic_version` (survives a schema drop); revisions written as explicit SQL; the SQLAlchemy mirror `diski9.backend.db.schema` is checked against the migrated database by a test |
| Package layout | `diski9.backend.db` (settings, engine, transactions, migrate, schema) and `diski9.backend.repositories` (plain functions over an open connection); services, auth and jobs packages are added in later stages |
| Sessions | UTC, statement timeout 15 s, lock timeout 5 s, pre-ping, pool 5 + 5 per process |
| Deadline foundation | Insert trigger on submissions (open status and `transaction_timestamp() < deadline_at`); `FOR SHARE` on the round for submissions, `FOR UPDATE` for status changes |
| Job overlap | Transaction-scoped advisory locks on `(job, scope)` |
| Privileges | Runtime role `diski9_app`: SELECT and INSERT on history, narrow UPDATE on guarded tables, full DML on projections, no TRUNCATE; created outside migrations |
| Credentials | Environment or untracked `.env`; never logged (URLs rendered without passwords, validation errors hide input) |
| Tests | `tests/backend` on real PostgreSQL; skipped locally without `DISKI9_APP_TEST_DATABASE_URL`, mandatory in CI (`DISKI9_REQUIRE_POSTGRES=1`) |

## 11. Implementation decisions taken in Phase 6C.2

| Topic | Decision |
|---|---|
| Identity provider integration | Supabase Auth via the official `supabase-auth` Python client, server-side only, behind the provider-neutral `AuthProvider` adapter |
| Email links | token_hash links to `/auth/confirm` verified with `verify_otp` (works across devices), behind a confirm button |
| Token verification | `get_claims` with a cached JWKS (ES256/RS256), plus issuer, audience, role, subject and algorithm checks |
| Sessions | Diski 9 server-side sessions (hashed opaque tokens; 14-day idle; 30-day absolute; rotation; revocation); provider tokens encrypted at rest and refreshed under a row lock |
| Authorisation | `Principal` loaded per request from the database; deny-by-default capabilities; independent entitlements; 12-hour operator recency; 15-minute re-authentication for sensitive operations (T-14, approved) |
| Web protections | CSRF tokens on forms; Origin checks on every cookie-bearing state change including Dash callbacks; safe relative redirects; strict CSP and no-store on account pages |
| Supabase database | Row-level security on every `app` table, access only for `diski9_app`; `app` not exposed to `anon`/`authenticated`; direct or session-pooler connections recommended; transaction-pooler mode supported (`DISKI9_APP_POOLER_MODE=transaction`) |
| Local development | Supabase CLI stack on a Mac (`supabase/config.toml`), or the Docker-free harness `tools/local_auth` (real Supabase Auth server) |
