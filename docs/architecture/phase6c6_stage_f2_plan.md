# Phase 6C.6 Stage F2 — Offline Deployment Readiness: implementation plan

**Status:** implementation plan for owner review (planning authorised 22 Nov 2026).
**F2 implementation is not authorised.** No application code, migration, dependency,
infrastructure, hosting choice, Supabase project, live provider call, refresh
activation, D-29b schedule change, participant account, webhook or deployment is part
of this plan. Design: [`phase6c6_stage_f_design.md`](phase6c6_stage_f_design.md) (approved
architecture; SF-01 to SF-14 recorded with the owner's qualifications; D-39a).

Baseline: branch `feature/phase-6c6-operations` at `0953375` (Stage F design, CI run
112); application baseline `4394485` (CI run 109: 1,908 passed, 0 skipped, 13 browser
tests); head `app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`;
`broad60-432-v1`; `points-150-75-v2`.

**F2 principle.** Everything is offline and provider-neutral: code, tests,
templates and local drills. Nothing names, configures or contacts a hosting provider,
Supabase project or API-Football. No migration is needed.

---

## 1. Modules and files

| File | Change |
|---|---|
| `src/diski9/app/factory.py` (new, small) | `build_app(ttl_seconds=300, tz="Africa/Johannesburg")`: the construction currently inside `cli.cmd_serve` and duplicated in `tools/f3_wsgi.py` (football store, optional competition backend and Supabase Auth from the environment) — one place |
| `src/diski9/wsgi.py` (new) | the production WSGI entry point: `server = build_app().server`; no `os.chdir`; refuses a relative SQLite path when `DISKI9_APP_ENVIRONMENT=production` (the store location must be explicit on a host) |
| `src/diski9/cli.py` | `cmd_serve` uses `build_app` (behaviour unchanged; still the development server); new `backup` and `restore` command groups (§4–§6) |
| `tools/f3_wsgi.py` | reduced to importing `diski9.wsgi` (reuse, not a parallel entry point); the F3 load tool keeps working |
| `src/diski9/app/health.py` (new) | `/healthz` and `/readyz` registered on the Flask server (§3) |
| `src/diski9/app/app.py` | one call to register the health routes in `create_app` |
| `src/diski9/backup/` (new package: `store.py`, `manifest.py`, `restore.py`) | SQLite online backup, verification, manifest and guarded restore (§4–§6); no network access |
| `src/diski9/backend/ops/checks.py`, `ops/snapshot.py`, `ops/config.py` | backup-health findings and thresholds (§8) |
| `src/diski9/backend/jobs/refresh.py` | sweeps closed **before the latest football-store restore** no longer count as current (consistency safeguard §6.3); readiness `data=` then reports `none` until a new sweep |
| `pyproject.toml`, `uv.lock` | optional dependency group `server = ["gunicorn==<pinned>"]` (SF-13); not installed by default; CI installs it for the WSGI test |
| `deploy/` (new) | provider-neutral templates: `systemd/diski9-web.service`, `systemd/diski9-tick.service` + `.timer`, `systemd/diski9-backup.service` + `.timer`, `caddy/Caddyfile.example`, `env/diski9.env.example` (§9–§11) |
| `docs/operations_hosting.md` (new) | host-hardening guide, deployment steps, PostgreSQL backup/restore runbook, restore drills (§7, §12) |
| `docs/operations_runbook.md`, `operations_monitoring.md`, `operations_guide.md`, `.env.example` | backup, restore and health sections |
| Tests (§15) | new test files; existing tests unchanged |

Not changed: competition services, settlement, corrections, championships,
authentication behaviour, publication, scheduler locking, migrations, quantitative
models, E.1b provider safety.

## 2. Production WSGI entry point (SF-13)

* `gunicorn diski9.wsgi:server --workers 2 --bind 127.0.0.1:8050 --timeout 60` behind
  the reverse proxy (template in §9). Workers 2–4, measured in F3 (each worker loads the
  Screener data; F3 local measurement: 4 workers, 213 req/s, 0 errors).
* Reuse: the F3 tool's construction moves into `build_app`; `tools/f3_wsgi.py`,
  `diski9 serve` and `diski9.wsgi` all call it.
* Gunicorn is optional (`uv sync --extra server` on the host); the default install is
  unchanged.

## 3. Health endpoints (SF-13)

| Path | Purpose | Checks | Response |
|---|---|---|---|
| `GET /healthz` | process liveness | none (the worker answers) | `200 {"status": "ok"}` |
| `GET /readyz` | dependency readiness | competition database `SELECT 1` (2 s timeout, only when accounts are configured); football store file present with required tables (read-only open) | `200` or `503` with `{"status": "ready" \| "not_ready", "checks": {"database": "ok" \| "unavailable" \| "not_configured", "football_store": "ok" \| "unavailable"}}` |

Safeguards: no version, host name, path, URL, exception text or counts in responses;
`Cache-Control: no-store`; GET/HEAD only; no session cookie read or set (the auth hook
only resolves a session when a cookie is present and only checks origin/CSRF on unsafe
methods — [Code] `auth/web.py::_before_request` — so authentication behaviour is
unchanged); `/readyz` is restricted to the host by the reverse-proxy template; errors
are logged by type only. Tests prove all of these.

## 4. SQLite online backup

`diski9 backup store --out DIR [--keep 14]`:

1. Opens the live store **read-only** and uses Python's `sqlite3.Connection.backup()`
   (SQLite online backup API: consistent snapshot, WAL-safe, concurrent readers and the
   scheduler keep working; a writer is never blocked for long — pages copied in steps).
2. Writes `diski9-store-<UTC timestamp>.sqlite` via a temporary file in `DIR`, `fsync`,
   then renames atomically; file mode `0600`.
3. Runs `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on the copy; checks the
   required tables and the store migration version (`alembic_version` = `0004`).
4. Computes SHA-256 and writes `…sqlite.manifest.json` (§5).
5. Prunes copies beyond `--keep` (only files matching its own naming pattern).
6. Records a completed `job_runs` row `ops.backup_store` (args: file name, size, SHA-256
   prefix, table row counts, verified true/false) when the competition database is
   configured; exits non-zero if verification fails (the failed copy is deleted).

Encryption and off-host copies are the host's job (provider-neutral guide: e.g. `age`
or `restic` to any object store or second machine); the command never handles keys.

## 5. Integrity and checksum verification

`diski9 backup verify FILE`: recomputes SHA-256 against the manifest, re-runs the
integrity, foreign-key, table and version checks, and prints a one-line verdict.

Manifest (`schema: diski9-store-backup/1`): created_at (UTC), file name, size, SHA-256,
store migration version, row counts per table, newest `odds_fetches.finished_at` and
`ingestion_runs.finished_at` (data age), application version, git commit if available.
**Never** a path outside the backup directory, a database URL, a host name or any
credential.

## 6. Restore tooling and safeguards

`diski9 restore store --from FILE --to PATH [--replace-live]`:

| Safeguard | Rule |
|---|---|
| Explicit target | `--to` is required; there is no default |
| Verified source | the file must pass `backup verify` (checksum, integrity, version) first |
| Live store protection | if `--to` resolves to the configured `DISKI9_DATABASE_URL` file, `--replace-live` is required **and** the scheduler must be paused (pause file present or `DISKI9_JOBS_PAUSED`) **and** an exclusive lock must be obtainable within 5 s (no other writer or long reader) **and** the operator types the target file name to confirm (interactive terminal only) |
| No silent overwrite | an existing target is moved to `<target>.pre-restore-<UTC>` (never deleted); the restore is copied to a temporary file, verified, then renamed atomically; WAL/SHM side files of the old store are moved with it |
| Non-store files | a target that exists but is not a Diski 9 football store is refused |
| Record | a completed `job_runs` row `ops.restore_store` (source file name, SHA-256 prefix, manifest created_at) |
| Output | file names only; never URLs or credentials |

PostgreSQL restore stays a documented, manual runbook (§7): always into a **new empty
database**; switching the application to it is an explicit configuration change. No
command restores over the live competition database.

### 6.1 Consistency between the two stores
The stores are related but not mutually dependent: published rounds keep their
immutable snapshots, results observations and settlement in PostgreSQL; the football
store is the source for future snapshots, readiness and the Screener.

| Situation | Effect | Safeguard |
|---|---|---|
| Older football store, current PostgreSQL | older fixtures/odds; published rounds unaffected | refresh repopulates; sweeps closed before the restore no longer count (`refresh.py` change), so readiness says `data=none` and `store_not_current` fires near the target until a new sweep or a manual `refresh-data` |
| Older PostgreSQL, current football store | competition state, `job_runs` (ledger, sweeps, quota observations, cooldowns) and audit roll back; football data newer | runbook: restore only with the scheduler paused; keep it paused until an operator has reviewed `ops check`, `round inspect` of open rounds and the provider position; see §6.2 |
| Both restored from different days | combination of the two above | restore both from the **same backup set** when possible (backup timer runs both within minutes); the restore record lists both manifests |

### 6.2 Scheduler recovery after a PostgreSQL restore
* **Job history and Stage D:** `running` rows captured in the dump belong to ticks
  that no longer exist; the next tick classifies them by age (older than 20 minutes →
  abandoned; younger → indeterminate, no lifecycle work until they age out). Stage D
  guarantees are unchanged.
* **Provider ledger:** requests sent after the dump are no longer counted, so the
  rolling 24-hour caps would under-count. Runbook rule: after a PostgreSQL restore keep
  provider calls **off for 24 hours**, or until the provider-reported remaining
  (headers/`/status`) has been reviewed and the caps temporarily reduced; the
  preparation floor (provider-reported remaining) still applies.
* **Cooldowns and quota observations:** lost; the next request re-observes headers; a
  cooldown that should still apply is re-learnt from a 429 (bounded by the 30 s wait).
* **Audit:** records written after the dump are lost — the restore is an incident:
  the evidence pack and operator log record it; audit exports taken for evidence packs
  survive outside the database.
* **Competition state:** entries/publications after the dump are lost. Acceptable for
  the operator-only F3/F4 exercise (provisional 24-hour RPO); **not yet approved for
  real participants** — the tighter-RPO evaluation (point-in-time recovery or more
  frequent dumps: cost, complexity, data-loss implications) is a gate before F5.

## 7. PostgreSQL backup and restore documentation

`docs/operations_hosting.md` §PostgreSQL:
* provider backups are a baseline, not verified recovery;
* nightly independent `pg_dump --format=custom` with credentials from a `pgpass` file
  (mode 0600) or the environment of the service user — never on the command line or in
  logs; checksum and manifest written next to it; encrypted before leaving the host;
* restore drill: `pg_restore` into an empty database, migration head check
  (`app_0007`), `competition verify`, `ops check --deep`, standings hash and counts
  compared with the source;
* `diski9 backup record --kind postgres --file DUMP` (no network, no binaries) records
  checksum, size and time as `ops.backup_postgres` for backup-health monitoring.

## 8. Backup-health monitoring

New `ops check` findings (off unless `DISKI9_OPS_BACKUP_EXPECTED=on`; INFO
`backup_monitoring_off` otherwise):

| Finding | Severity | Condition |
|---|---|---|
| `backup_store_stale` | WARNING > 26 h; CRITICAL > 50 h | last verified `ops.backup_store` |
| `backup_postgres_stale` | WARNING > 26 h; CRITICAL > 50 h | last `ops.backup_postgres` |
| `backup_failed` | WARNING | the latest backup attempt failed verification |
| `store_restored` | INFO (WARNING if within 2 h of a publication target) | a restore in the last 7 days |

`ops status` shows the last backup of each kind with its age; `ops jobs` lists the new
jobs. Thresholds configurable (`DISKI9_OPS_BACKUP_WARNING_HOURS` / `_CRITICAL_HOURS`).
A restore drill result is recorded in the evidence pack, not inferred from a backup.

## 9. Systemd templates (provider-neutral)

| Unit | Content |
|---|---|
| `diski9-web.service` | `User=diski9`, `EnvironmentFile=/etc/diski9/diski9.env` (0600), `ExecStart=.../gunicorn diski9.wsgi:server --workers 2 --bind 127.0.0.1:8050`, `Restart=on-failure`, sandboxing (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths=/var/lib/diski9`, `PrivateTmp`, `ProtectHome`) |
| `diski9-tick.service` + `.timer` | `Type=oneshot`, `ExecStart=.../diski9 jobs tick`; timer `OnCalendar=*:0/5`, `Persistent=true`, `AccuracySec=10s`; a oneshot never overlaps itself; the Stage D lock still protects against manual ticks |
| `diski9-backup.service` + `.timer` | `diski9 backup store --out /var/lib/diski9/backups` then the host's off-host copy hook; `OnCalendar=*-*-* 03:30:00 UTC`, `Persistent=true` |

Provider calls and refresh stay **off** in the environment template.

## 10. Reverse-proxy template

`deploy/caddy/Caddyfile.example`: automatic TLS; `reverse_proxy 127.0.0.1:8050`;
**private access** block (`remote_ip` allowlist placeholder, or bind only to a private
network interface) for F3/F4; `/readyz` answered only to the host itself; security
headers (HSTS, `X-Content-Type-Options`, `Referrer-Policy`, frame-ancestors none);
request size limit; access logs without query strings. No domain, IP or credential in
the template.

## 11. Secrets and environment templates

`deploy/env/diski9.env.example`: every variable the host needs with placeholders and
comments: `DISKI9_APP_ENVIRONMENT=production`, absolute `DISKI9_DATABASE_URL`, app and
scheduler database URLs (direct or session mode, port 5432), Supabase URL and
publishable key, cookie and site settings, scheduler switches (enabled with Beta;
`PROVIDER_CALLS=off`, `PREPARE_REFRESH=off`, caps 10/100 — D-1), backup settings,
API-Football key placeholder (or proxy note). Never real values. A test asserts no
template contains anything that looks like a secret.

## 12. Host-hardening guide

`docs/operations_hosting.md`: dedicated `diski9` user; SSH keys only, no root login;
firewall (443 and SSH from allowlisted sources or a private network); automatic
security updates; time synchronisation (chrony/systemd-timesyncd — the database clock
decides lifecycle times, but host logs and timers need correct time); file permissions
(`/etc/diski9` 0700, env 0600, `/var/lib/diski9` 0750); log rotation; disk-space
alerting via `ops check` and the host; off-host encrypted backups; restore drill
cadence; secrets rotation; what never to do (copy a live SQLite file without the backup
command, restore over the live competition database, run bulk store commands on
Friday mornings with refresh on).

## 13. Offline full-week rehearsal

`tests/backend/test_backend_f2_rehearsal.py` (runs in CI) — an end-to-end rehearsal on
an **isolated, freshly created PostgreSQL database** and a **temporary football store**,
with the mock API-Football transport from E.1b:

1. **Preparation** (week clock seam, as the E.1a/E.1b tests): Tuesday draft creation
   (SYSTEM), daily sweeps, Friday sweeps, readiness `data=complete@…`.
2. **Human publication** by an authenticated test operator principal through the
   publication service with the typed-confirmation fingerprint path (never SYSTEM).
3. **Lifecycle** on a compressed settlement world (existing scheduler fixtures:
   deadline and cutoff seconds ahead, correction window 0): entries, lock, results
   import (mock), settlement, S-02 finalisation, weekly results, championship check
   (`competition verify`).
4. **Evidence:** the same evidence-pack commands as §6.3 of the design, written to the
   test's temporary directory.

Isolation: the database is created by the test harness with a unique `_test` name and
dropped afterwards; the rehearsal refuses (a) `DISKI9_APP_ENVIRONMENT=production`,
(b) any database name in the protected list (`diski9`, `diski9_6c5_acceptance`,
`diski9_f1_e2e`, `diski9_f2_e2e`, `diski9_f2_e2e_nochamp`) and (c) the configured
`DISKI9_DATABASE_URL` store. It is labelled **offline rehearsal** — never evidence of
real-clock finalisation (Q-14).

## 14. Local restore drills (Q-12)

`tools/f2_restore_drill.py` (local only; needs `pg_dump`/`pg_restore` on the machine;
refuses protected database names and production):

1. Create an isolated source database and football store; populate with the
   development championship runner (dev stream) and a refresh sweep from recorded data.
2. Record standings hash, `competition verify`, row counts, quantitative fingerprint.
3. `backup store` + `pg_dump`; `backup verify`.
4. Restore into a **new** database and a **new** store path; repeat step 2; compare.
5. Failure drills (§8.3 of the design, local versions): interrupted refresh, store
   corruption → restore, database unavailable, interrupted results import, scheduler
   kill mid-step.
6. Write a drill report (no secrets) for the F2 checkpoint.

## 15. Security tests (in CI)

* Health responses contain no secrets/paths/versions; `/readyz` 503 with component
  names only when dependencies fail; no `Set-Cookie`; POST refused.
* Authentication behaviour unchanged: the existing auth and browser suites pass;
  health routes do not bypass CSRF/origin checks for account routes.
* Backup/restore: manifests and outputs contain no URL, password or key (fixture
  credentials planted and searched for); restore refuses the live store without pause +
  `--replace-live` + typed confirmation; refuses non-store targets; keeps the previous
  file; atomic swap; checksum mismatch and corrupt copies rejected.
* Templates: no secret-like strings; provider calls and refresh off; caps 10/100.
* WSGI: `diski9.wsgi` imports without network access; production refuses a relative
  store path.

## 16. Verification

* **Level 1:** new tests plus app/auth, ops, refresh and scheduler suites — twice.
* **Level 2:** every backend suite plus client, ingestion, workflow, CI-scope and
  migration suites on local PostgreSQL and the auth harness (known Supabase-schema
  skip only).
* **Level 3:** full GitHub CI with all 13 browser tests and no skips; migration head
  and fingerprint unchanged.
* **Local drills:** §14 report.

## 17. Performance and CI impact

About 35–45 new tests (Flask test client, temporary SQLite files, isolated
PostgreSQL; one rehearsal of ~30–60 s); estimated **≤ 2 minutes** added to a 26 min 45 s
suite (job 28 min, margin ≈ 12 min → ≈ 10 min). Health endpoints add no load to normal
pages. Online backup of the 37 MB store takes seconds (to be measured in the drill).

## 18. Rollback

All changes are additive: templates and commands are unused until a host exists;
health routes are read-only; the refresh change only makes data labels more
conservative. Rollback = revert the F2 commit; no migration, no data change. The
optional `server` dependency group does not affect the default install.

## 19. Acceptance checklist

1. `diski9.wsgi:server` serves the app under Gunicorn locally; `tools/f3_wsgi.py` and
   `diski9 serve` use the same factory; default install unchanged.
2. `/healthz` and `/readyz` behave as §3; no secrets; auth behaviour unchanged (all
   auth and browser tests pass).
3. `backup store` produces a verified, checksummed, `0600` copy while the store is in
   use; `backup verify` detects corruption and checksum mismatch.
4. `restore store` refuses every unsafe case in §6 and restores safely otherwise;
   previous files preserved.
5. Sweeps closed before a store restore are not reported as current.
6. Backup-health findings as §8; off by default.
7. Templates and hardening guide present, provider-neutral, secret-free, with
   provider calls and refresh off and caps 10/100.
8. Rehearsal passes in CI on an isolated database; refuses protected targets.
9. Local restore drill report: standings, verify, counts and fingerprint reproduced.
10. Level 1 (twice), Level 2, full CI with 13 browser tests, no unexpected skips;
    head `app_0007`, fingerprint and configurations unchanged.
11. No live provider call, infrastructure, Supabase project, D-29b change, participant
    account or webhook.

## 20. Blockers and open items

* **None blocking F2 implementation** once authorised.
* Pinning a Gunicorn version adds an optional dependency (approved in principle by
  SF-13); confirmed at implementation.
* CI has no `pg_dump`; PostgreSQL dump/restore is therefore a local drill and a
  runbook, not a CI test (the SQLite parts are tested in CI).
* Before F3 (not F2): provider and region selection, monthly spending limit, hosted
  Supabase project, hosted Supabase acceptance.
* Before F4: SF-14 shared-key analysis (D-29b capture at Friday 06:00 UTC vs refresh at
  05:15 and the publication target) with a schedule recommendation; no change until
  approved.
* Before F5: tighter PostgreSQL RPO evaluation; ML-01; D-36 minimum workflow and
  retention statement (separate privacy design review); participant access approval.
