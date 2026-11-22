# Deployment templates (Phase 6C.6 Stage F2)

Provider-neutral templates for the approved Stage F target (SF-02, D-39a): one small
Linux host running the web app (Gunicorn), the scheduler tick and the SQLite football
store together, with the competition database and Auth hosted separately. **Nothing
here is deployed, and no hosting provider, region, domain or account is chosen.**
Read [`docs/operations_hosting.md`](../docs/operations_hosting.md) before using any of it.

| File | Purpose |
|---|---|
| `systemd/diski9-web.service` | Gunicorn serving `diski9.wsgi:server` on 127.0.0.1:8050 |
| `systemd/diski9-tick.service` + `.timer` | `diski9 jobs tick` every 5 minutes (oneshot: never overlaps itself) |
| `systemd/diski9-backup.service` + `.timer` | nightly verified football-store backup, then the host's off-host copy hook |
| `bin/diski9-offhost-copy.example` | placeholder for the host's encrypted off-host copy (records the copy only if it succeeded) |
| `caddy/Caddyfile.example` | TLS reverse proxy, private-access allowlist, security headers |
| `env/diski9.env.example` | every environment variable, with placeholders only |

Safe defaults: provider calls **off**, automated refresh **off**, caps **10 per tick /
100 per 24 h** (D-1), notifications **off**, backup monitoring off until an operator
enables it. Placeholders look like `<...>`; a test refuses anything secret-like.
