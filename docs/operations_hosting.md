# Hosting, backups and recovery (Phase 6C.6 Stage F2)

**Status: F2 implemented, awaiting owner acceptance.** This guide is provider-neutral
and nothing in it has been deployed. No hosting provider, region, spending limit,
domain or Supabase project has been chosen (SF-02/SF-03; selection is a gate before
F3). Templates live in [`deploy/`](../deploy/README.md).

Target (SF-02, D-39a): one small Linux host running the web app (Gunicorn), the
scheduler tick (systemd timer) and the SQLite football store together; the
competition database and Auth are hosted PostgreSQL/Supabase. D-39a allows the SQLite
football store **only** for a private, access-restricted, supervised Stage F
environment with co-located app and scheduler and **verified off-host backups**; the
PostgreSQL football-store migration remains mandatory before any public or
production deployment.

Contents: [1 Host hardening](#1-host-hardening) · [2 Installing the app](#2-installing-the-app) ·
[3 Health endpoints](#3-health-endpoints) · [4 Football-store backups](#4-football-store-backups) ·
[5 Evidence levels](#5-evidence-levels-safeguard-b) · [6 Restoring the football store](#6-restoring-the-football-store-safeguard-a) ·
[7 PostgreSQL backups](#7-postgresql-backups) · [8 PostgreSQL restore and recovery gate](#8-postgresql-restore-and-the-recovery-gate-safeguard-d) ·
[9 Restore drills](#9-restore-drills) · [10 Never do this](#10-never-do-this)

## 1. Host hardening

* **Account:** a dedicated `diski9` system user owns `/var/lib/diski9` (mode `0750`)
  and runs every unit. Nobody logs in as it.
* **SSH:** keys only; `PermitRootLogin no`; `PasswordAuthentication no`; SSH reachable
  only from allowlisted sources or a private network.
* **Firewall:** inbound 443 (and 80 only for certificate issuance) plus SSH from the
  allowlist; everything else closed. Gunicorn binds to `127.0.0.1:8050` only.
* **Private access (SF-12, D-39a):** Stage F3/F4 are not public. Restrict the reverse
  proxy to allowlisted addresses (`deploy/caddy/Caddyfile.example`) or serve only on
  a private network interface.
* **Updates:** automatic security updates; reboot windows outside Friday mornings.
* **Time:** `systemd-timesyncd` or `chrony` enabled. Lifecycle times come from the
  database clock, but timers, logs and backup names need correct host time.
* **Secrets:** `/etc/diski9` mode `0700`; `/etc/diski9/diski9.env` mode `0600` (or
  `0640` root:diski9). Secrets live only there or in the host's secret store; never
  in the repository, unit files, shell history or command lines. Generate the session
  keys with `diski9 account generate-keys`. Rotate after any suspected exposure.
* **Logs:** journald with size limits; the proxy access log drops query strings,
  cookies and authorisation headers. Diski 9's own output never contains URLs with
  credentials, keys or the webhook URL.
* **Disk:** watch free space (the store, 14 backups of ~37 MB, logs); `ops check`
  plus the host's own disk alert.
* **Backups off the host:** encrypted before they leave (section 4); keys kept off
  the host as well as on it.

## 2. Installing the app

1. Check out the approved commit to `/opt/diski9`; `uv sync --frozen --extra server`
   (Gunicorn is the optional `server` extra; the default install is unchanged).
2. Write `/etc/diski9/diski9.env` from `deploy/env/diski9.env.example`. Keep the safe
   defaults: provider calls **off**, refresh **off**, caps **10/100** (D-1),
   notifications **off**. `DISKI9_DATABASE_URL` must be an **absolute** path:
   `diski9.wsgi` refuses a relative SQLite path in production.
3. `diski9 app-db upgrade`, `diski9 app-db check` (head `app_0007`).
4. Install the units from `deploy/systemd/`; `systemctl enable --now diski9-web
   diski9-tick.timer diski9-backup.timer`.
5. Install the proxy from `deploy/caddy/Caddyfile.example` with the real site name
   and allowlist.
6. Check: `curl -s http://127.0.0.1:8050/readyz`, `diski9 ops status`, `diski9 ops
   check`.

`diski9 serve` remains the development server only. `diski9.wsgi`, `diski9 serve` and
`tools/f3_wsgi.py` all build the app through one factory (`diski9.app.factory`).

## 3. Health endpoints

| Path | Meaning | Response |
|---|---|---|
| `GET /healthz` | the worker answers (liveness; no dependency checks) | `200 {"status": "ok"}` |
| `GET /readyz` | the competition database answers (`SELECT 1`, 2 s statement timeout, only when accounts are configured) and the football store exists with its tables | `200` ready, `503` not ready, with component words only |

They are answered in front of Flask and Dash: no cookie is read or set, the session
and CSRF hooks never run, and a probe never triggers Dash's first-request layout
build. Responses carry no versions, hosts, paths, URLs or errors (`Cache-Control:
no-store`; GET/HEAD only, other methods `405`). The proxy template answers `/readyz`
to the host itself only.

## 4. Football-store backups

```bash
diski9 backup store --out /var/lib/diski9/backups --keep 14
diski9 backup verify /var/lib/diski9/backups/diski9-store-<timestamp>.sqlite
```

* SQLite's online backup API from a **read-only** connection: one consistent snapshot
  while the web app and the scheduler keep working (measured: the 37 MB store in about
  0.2 s including verification; a concurrent writer was never held up).
* The copy is a single self-contained file (mode `0600`), `fsync`-ed, verified
  (`integrity_check`, `foreign_key_check`, all 17 tables, store version `0004`), then
  renamed into place next to a SHA-256 manifest. A copy that fails verification is
  deleted and the failure is recorded.
* Only this command's own files are pruned beyond `--keep`.
* Each run is recorded as `ops.backup_store` in the competition database (file name,
  size, SHA-256 prefix, row counts). If the database cannot be reached the command
  exits `1` with `NOT RECORDED`, so monitoring is not silently blind.
* The nightly `diski9-backup.timer` runs it at 03:30 UTC, then the host's off-host copy
  hook (`deploy/bin/diski9-offhost-copy.example`), which must **encrypt** before
  copying (for example `age`, or `restic` to a second machine or object store) and
  only then run `diski9 backup record --kind offhost-copy --file <backup> --label
  <nickname>`. Diski 9 never handles encryption keys or destinations.

## 5. Evidence levels (safeguard B)

| Level | Meaning | Recorded by | What it does **not** show |
|---|---|---|---|
| 1 | a local backup was created | `backup store` / `backup record --kind postgres` | that it is readable |
| 2 | the local backup was verified | the same commands: integrity and checksum (store); dump header and checksum (PostgreSQL) | that it is off the host; for a dump, that it restores |
| 3 | an encrypted off-host copy completed | the host's copy hook, after it succeeded (`--kind offhost-copy`) | anything verified by Diski 9; that the copy restores |
| 4 | an off-host copy was restored in a drill | `restore store --purpose drill --source-origin offhost`, or `backup record --kind postgres-drill --source-origin offhost` | the off-host origin is operator-declared; the content is checked against a recorded backup checksum |

`ops status` lists the four levels separately; `ops check` (with
`DISKI9_OPS_BACKUP_EXPECTED=on`) reports each gap separately:
`backup_store_stale`, `backup_postgres_stale`, `backup_offhost_stale` (WARNING after
26 h, CRITICAL after 50 h or never), `backup_failed`, and
`offhost_restore_unverified` / `restore_drill_stale` (no matching off-host drill, or
none in 35 days). Monitoring is **off by default** (`backup_monitoring_off`, INFO)
until an operator enables it. The F2 implementation itself has established levels
1 and 2 only (local drill); levels 3 and 4 need a real host.

## 6. Restoring the football store (safeguard A)

**Replacing the live store in place is disabled in F2.** An SQLite lock cannot prove
that every consumer (Gunicorn workers, the tick timer, a manual command) has stopped
and released its WAL/SHM state, and proving that needs the host's service manager.
`restore store --replace-live` is always refused, and the configured live store (and
its `-wal`/`-shm`/`-journal` files, symlinks or hard links to it) can never be a
target.

```bash
diski9 restore store --from <backup>.sqlite --to /var/lib/diski9/diski9-restored-<date>.sqlite \
    --purpose recovery
```

The command verifies the backup (manifest checksum, integrity, version), refuses any
existing target or side file, copies to a temporary file (`0600`), checks the
checksum, links it into place without overwriting, verifies it again and records
`ops.restore_store` (`--purpose drill` records `ops.restore_drill` instead and changes
nothing else). The live store is untouched.

**Offline switch procedure** (documented for F3; supervised, services stopped):

1. Create the pause file (`touch /var/lib/diski9/PAUSED`) so a stray tick does nothing.
2. `systemctl stop diski9-web diski9-tick.timer diski9-tick.service
   diski9-backup.timer`; then `systemctl is-active` for each must print `inactive`.
3. Confirm nothing holds the store: `fuser -v /var/lib/diski9/diski9.sqlite*` (or
   `lsof`) must list no process. If anything is listed, stop: do not continue.
4. Point `DISKI9_DATABASE_URL` in `/etc/diski9/diski9.env` at the restored file. The
   previous store and its `-wal`/`-shm` files stay exactly where they were (rename
   nothing, delete nothing): they are the way back.
5. The restored file was verified by `restore store` (checksum, integrity, version);
   do not edit it.
6. Start the web app, check `/readyz` and the Screener, then remove the pause file and
   start the timers.
7. Record the event in the operator log. Data refresh sweeps from before the restore no
   longer count as current (readiness says `data=none`), so the current slot is swept
   again, or run `refresh-data --with-odds` manually before checking readiness.

A safe, host-verified in-place replacement may be designed in F3 with the chosen
service manager; it is not part of F2.

## 7. PostgreSQL backups

* The hosted provider's own backups are a baseline, **not verified recovery**.
* Nightly independent dump on the host:
  `pg_dump --format=custom --no-owner --file /var/lib/diski9/backups/pg/diski9-<date>.dump`
  with credentials from a `pgpass` file (mode `0600`) or the service user's
  environment: never on the command line or in logs. Then
  `diski9 backup record --kind postgres --file <dump>` (checks the dump header,
  writes a SHA-256 manifest next to it, records `ops.backup_postgres`), then the
  encrypted off-host copy and `--kind offhost-copy`.
* The 24-hour recovery point is **provisional**, for the operator-only exercise only
  (SF-09); a tighter recovery point is evaluated before any real participant (F5).

## 8. PostgreSQL restore and the recovery gate (safeguard D)

A restore is always into a **new, empty database**; no command restores over the live
competition database, and switching the application is an explicit configuration
change. A restore is an incident: everything written after the dump is lost.

What is lost and what follows from it:

| Lost after the dump | Consequence | Handling |
|---|---|---|
| provider-request reservations (`scheduler.provider` ledger) | the 24-hour caps under-count | provider calls stay off; review the provider's own remaining-requests figure before resuming |
| rate-limit cooldowns and quota observations | a cooldown may be forgotten | re-learnt from the next provider response (bounded 30 s wait); resume only after review |
| scheduler job history | interrupted steps reappear as `running` | the next tick applies Stage D: abandoned after 20 minutes, otherwise no lifecycle work until they age out |
| audit records | evidence gap | record the gap in the incident record; exported evidence packs survive outside the database |
| entries, publications, settlement and corrections after the dump | competition state rolled back | review every active round before anything resumes |

Procedure:

1. Pause the scheduler (pause file) and stop the timers. Keep
   `DISKI9_JOBS_PROVIDER_CALLS=off` and `DISKI9_JOBS_PREPARE_REFRESH=off` in the
   environment file.
2. Create the new empty database; `pg_restore --no-owner --exit-on-error --dbname
   <new> <dump>`; `diski9 app-db check` (head `app_0007`).
3. **Before** pointing anything at it, with `DISKI9_APP_DATABASE_URL` set to the new
   database: `diski9 backup record --kind postgres-restore --file <dump>`. This places a
   **provider hold** in the restored database: every tick runs with provider calls
   and refresh off, whatever the environment says, until an operator lifts it. An
   ordinary scheduler restart does not lift it.
4. Reconcile: `diski9 competition verify`, `diski9 ops check --deep`, `diski9 round
   list` and `round inspect` for every open, locked or settling round; publication
   state, entries and settlement; the provider's own quota figures.
5. Record the incident and every evidence gap (lost audit records, lost entries).
6. Switch the application to the new database, start the web app, then the timers
   (provider calls still off and held).
7. Only after reconciliation: `diski9 ops provider-resume --operator <your email>
   --reason "<what was reconciled>"`. It verifies your password with Supabase Auth
   (S-07), needs an operator role, shows the checklist, needs `RESUME` typed, and is
   recorded (`ops.provider_resume`) and audited. It does not switch provider calls on:
   that remains `DISKI9_JOBS_PROVIDER_CALLS`, changed only with owner approval.

`ops check` reports `provider_hold_after_restore` (WARNING) while the hold is active.
Manual provider commands (`refresh-data`, `collect-odds`) are the operator's own
explicit action and are not covered by the hold: do not run them before step 7.

## 9. Restore drills

* **Football store:** `diski9 restore store --from <backup> --to <new path> --purpose
  drill [--source-origin offhost]`, then compare with the manifest (the command does).
* **PostgreSQL:** restore a dump into a new empty database, check the head, `competition
  verify`, `ops check --deep` and row counts against the source, then `diski9 backup
  record --kind postgres-drill --file <dump> [--source-origin offhost]`.
* **Local drill tool:** `uv run python tools/f2_restore_drill.py --server
  postgresql+psycopg://<user>@127.0.0.1:<port>/postgres --out tmp/f2/drill` runs the
  whole cycle on disposable local databases (section 9 of the F2 record has the
  results). It refuses non-loopback servers, production and protected databases.
* Cadence on a host: a football-store drill and a PostgreSQL drill from the
  **off-host** copy at least monthly (`DISKI9_OPS_RESTORE_DRILL_DAYS=35`), and after any
  change to the backup or copy scripts.

## 10. Never do this

* Copy the live SQLite file with `cp`/`rsync` (use `backup store`).
* Restore over the live competition database or the live football store.
* Lift a provider hold, or turn provider calls on, without reconciliation and approval.
* Put a database password, API key, webhook URL or session secret on a command line,
  in a unit file, in the repository or in a ticket.
* Run bulk store commands on Friday mornings while refresh is on.
* Treat a provider's backups, a local backup or a reported off-host copy as proof of
  recovery: only a restore drill is.
