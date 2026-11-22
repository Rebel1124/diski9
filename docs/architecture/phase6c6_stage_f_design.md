# Phase 6C.6 Stage F — Integration and Genuine Beta-Week Validation: design and readiness assessment

**Status:** **architecture approved by the owner (22 Nov 2026)** with the decisions and
qualifications in §16; **F1 (architecture and readiness) accepted**; **F2
implementation planning authorised and delivered**
([`phase6c6_stage_f2_plan.md`](phase6c6_stage_f2_plan.md)); **F2 implemented, awaiting
owner acceptance** ([`phase6c6_implementation.md`](phase6c6_implementation.md) §12);
F3–F6 and Stage G not authorised. No provider, region, Supabase project or spending limit is
chosen. Original status: design and readiness assessment for owner review (authorised
22 Nov 2026); not implemented.

**Baseline verified (22 Nov 2026):** branch `feature/phase-6c6-operations` at
`77f22ad` (E.1b closure; documentation CI run 111 passed); E.1b application commit
`4394485` (CI run 109: 1,908 passed, 0 failed, 0 skipped, 13 browser tests); migration
head `app_0007`; quantitative fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4` (recomputed);
`broad60-432-v1`; `points-150-75-v2`. Automated refresh **off** by default and refused
by configuration until the 24-hour cap is explicitly set to ≥ 450 (D-1). Official
**disabled** (not configurable; D-38). Publication requires an authenticated operator
(S-07; ADP-16). Stages A–E and E.1a–E.1b of Phase 6C.6 are closed; Phase 6C.6 as a
whole is **not** complete.

**Labels.** **[Approved]** an existing owner decision or accepted behaviour (with its
ID); **[Code]** confirmed in the repository; **[Observed]** measured or recorded;
**[Price ✓]** a list price found on or attributed to the provider's own pricing page on
22 Nov 2026 (still to be re-checked before purchase); **[Estimate]** not confirmed;
**[Proposal]** new, needs approval.

**Contents.** §1 current-state operational architecture · §2 Stage F checkpoints ·
§3 hosting (Q-07) · §4 database and D-39 · §5 API-Football activation · §6 lifecycle
validation · §7 security and authentication · §8 backup and recovery · §9 pre-Beta
dependencies · §10 monitoring · §11 testing and acceptance · §12 costs · §13 SF
decision register · §14 risks and open questions · §15 recommended next checkpoint ·
Appendix A dependency matrix.

---

## 1. Current-state operational architecture

### 1.1 Components [Code]

| Component | Technology | State |
|---|---|---|
| Web app (Screener, Match Lab, Weekly Challenge, leaderboards, accounts) | Dash/Flask; `diski9 serve` runs the **development server** (`app.run`) | multi-worker operation measured with `gunicorn -w 4` via `tools/f3_wsgi.py` (F3: 4 workers, 213 req/s, 0 errors) — **no packaged production WSGI entry point, no `/healthz`** (Q-10 deferred to hosting) |
| Competition database | PostgreSQL (schema `app`, head `app_0007`), SQLAlchemy 2, psycopg 3 | tested on PostgreSQL 16/17 locally and in CI; **no hosted database exists** |
| Authentication | Supabase Auth (GoTrue); local harness / Supabase CLI; server-side sessions; S-07 interactive operator authentication | **no hosted Supabase project exists** (`docs/authentication.md` §2.4; one CI-covered test skips locally); hosted Supabase acceptance is an open gate ("before hosting", Phase 10) |
| Football store | SQLite (`DISKI9_DATABASE_URL`, WAL, `foreign_keys=ON`, 5 s busy timeout); 37 MB; 16 tables | D-39: stays SQLite throughout Phase 6C |
| Scheduler | `diski9 jobs tick` every ~5 min from an external trigger; session advisory lock on a direct/session PostgreSQL connection; lifecycle (lock, results, settle, finalise) + E.1a draft/readiness + E.1b refresh | everything **off** by default; provider calls off; refresh off |
| Monitoring | `ops status/check/jobs`, `jobs status`, `jobs tick --dry-run`, `round readiness/inspect`, `audit list` | webhook implemented, **off** (Q-08) |
| Provider | API-Football Pro (sole provider, ADP-22); key via environment or network proxy | caps 10/tick, 100/24 h by default; E.1b safety (classes, reserve, pacing, cooldown, floor) |

### 1.2 Process topology implied by the code

```
              ┌──────────────── one host (same filesystem) ────────────────┐
 browser ──►  │ reverse proxy (TLS) ─► WSGI workers (Dash app) ──read──┐     │
              │                                                        ▼     │
              │ timer (5 min) ─► jobs tick ──write (E.1b)──► SQLite football │
              │                     │                          store (WAL)   │
              └─────────────────────┼───────────────────────────────────────┘
                                    ▼
                    PostgreSQL (competition, job_runs)  ◄── web app (sessions, entries)
                    Supabase Auth (identity)            ◄── web app, operator CLI
                    API-Football                        ◄── jobs tick (and manual CLI)
```

The SQLite store must be on the **same machine** as both its writer (scheduler) and
its readers (web app, `round readiness/publish`): WAL uses a shared-memory index and
network file systems are unsafe (E.1b design §8). PostgreSQL and Supabase Auth can be
remote; the tick lock needs a direct or session-mode connection (Stage D R2).

### 1.3 Other consumers of the API-Football key [Observed]

The approved D-29b research collection runs as scheduled tasks on the same key:
capture **Fridays 08:00 SAST (06:00 UTC — the publication target)**, results daily
09:15 SAST (≈ 40–50 requests a week, D-29b proposal); two approved one-off PSL odds
checks remain scheduled (25 and 27 Nov). The D-29 odds trial has ended and is not
restarted. Manual CLI commands (`setup` ≈ 400, `refresh-data` ≈ 28) also share it.

---

## 2. Stage F checkpoints

### 2.1 Assessment of the proposed five checkpoints

The proposed F1–F5 cover the right ground, but two gaps make them hard to gate:

1. **No offline hardening step.** Hosting needs small code and tooling changes that
   do not exist yet (production WSGI entry point and `/healthz` — Q-10; SQLite
   online-backup and restore commands; a backup-health check; host trigger/service
   units). Folding them into "environment" mixes code acceptance (CI) with
   infrastructure acceptance (drills).
2. **One checkpoint for two different risk levels.** "Genuine Beta-week validation"
   with operator-controlled accounts and with invited real participants are different
   approval levels: real participants trigger the ML-01, D-36 and hosted-Supabase gates
   [Approved: G-3, D-36, 6C.5 gates]. Also, a **competitive** Beta round needs ≥ 5 valid
   entries (D-28) and Beta championship rounds are permanent (insert-only, never
   deleted; D-30): competitive test rounds with fake participants would permanently
   form part of Beta Championship 1.

### 2.2 Proposed structure (SF-01) — six checkpoints, four risk levels

| Checkpoint | Risk level | Content | Main deliverables | Approval gate before it starts |
|---|---|---|---|---|
| **F1 Architecture and readiness** | design | this document; owner rulings on SF decisions | approved decisions; F2 plan | — (current) |
| **F2 Deployment readiness (offline)** | local / CI | WSGI entry point and `/healthz` (Q-10); SQLite online backup + verified restore commands; backup-health `ops check` finding; host service/timer templates and hardening guide; secrets template; local restore drill (Q-12); scripted local full-week rehearsal on PostgreSQL with mocked provider | code + tests + docs; local drill evidence | F1 approval; implementation authorisation |
| **F3 Environment and recovery** | supervised, private host, no participants | provision the approved host and Supabase project; deploy; scheduler trigger; backups; restore drills; hosted Supabase acceptance (open gate); monitoring checklist | environment record; drill evidence; hosted auth acceptance | host (SF-02), database (SF-03/04) and budget approvals; F2 accepted |
| **F4 Supervised live integration** | live provider, operator only | subscription verification; first controlled live calls; refresh activation with explicit caps; draft, readiness, human publication; **one supervised genuine week** as a practice round (operator accounts, < 5 entries) through real-clock finalisation | live-activation record; provider accounting; genuine-week evidence (timing rule, refresh, results, settlement, corrections drill, finalisation) | SF-05 activation authorisation; F3 accepted |
| **F5 Private Beta with invited participants** | real participants | invited private Beta weeks until a competitive round (≥ 5 entries) completes and a championship progresses; incidents and recovery | competitive lifecycle and championship evidence; incident log | ML-01 fixed; D-36 minimum workflow; hosted Supabase acceptance; participant scope (SF-06) approved |
| **F6 Regression, handover, Stage G readiness** | — | full regression, security review, performance, operational handover, risk register, Stage F acceptance recommendation | handover record | F5 (or owner decision to close Stage F after F4) |

Local integration (F2) is never evidence of production readiness; F3–F5 evidence is
private Beta evidence only, not public-launch readiness (G-4 [Approved]).

### 2.3 Per checkpoint: dependencies, tests, acceptance

| | Dependencies | Tests and evidence | Acceptance criteria |
|---|---|---|---|
| F1 | — | — | owner rulings recorded |
| F2 | SF-01, SF-08, SF-09 | Level 1/2/3 incl. 13 browser tests; restore drill reproduces standings, fingerprint and `competition verify` clean; full-week rehearsal | CI green; no regression; fingerprint/head unchanged; drill evidence |
| F3 | SF-02, SF-03, SF-04, SF-10, budget | connectivity (TLS, PostgreSQL direct/session, Supabase Auth); `jobs tick` on the host with provider calls off; backup + restore drills on the host; failure-injection drills (§8.4) | all drills passed; `ops check` clean; hosted Supabase acceptance passed; no public exposure |
| F4 | SF-05, SF-07 | first live calls within the authorised budget; refresh sweeps; provider ledger = provider headers ± lag; one supervised week | §6.3 evidence complete; budgets never exceeded; no automated publication |
| F5 | SF-06, ML-01, D-36, F4 | competitive round lifecycle, championship assignment and standings; corrections where they occur | §6.3 evidence for a competitive round; championship integrity verified |
| F6 | F5 or owner closure | full regression; security sweep; restore drill re-run | Stage F acceptance recommendation |

---

## 3. Hosting architecture (Q-07)

### 3.1 Requirements derived from the architecture

1. Web app, scheduler and SQLite store on **one host** with a **persistent local disk**
   (not NFS/EFS/network volumes shared between machines).
2. A trigger every 5 minutes that survives reboots (systemd timer, cron, launchd).
3. Outbound HTTPS to API-Football and Supabase; PostgreSQL over TLS on a **direct or
   session-mode** connection for the tick lock (port 6543 transaction pooler refused —
   [Code] `check_lock_url`).
4. TLS in front of the app (production settings require `https` site URL and secure
   cookies — [Code] `AuthSettings`).
5. Restricted exposure during F3/F4 (no public access): IP allowlist, private network
   (e.g. Tailscale/WireGuard) or an authenticated tunnel.
6. Backups of the SQLite store off the host; configuration and secrets outside the
   repository with restricted file permissions (`.env` readable only by the service
   account — [Approved] scheduler doc).
7. Single instance: no horizontal scaling while SQLite is the store.

### 3.2 Comparison

| Option | Fit to requirements | Advantages | Disadvantages | Indicative cost / month |
|---|---|---|---|---|
| **A. One small Linux VM** (e.g. Hetzner Cloud, DigitalOcean; 2 vCPU, 2–4 GB) + systemd timer + reverse proxy (Caddy) | all requirements directly; matches the documented cron/systemd examples | simplest mental model; full control; local disk; cheapest; easy SQLite backups; no platform constraints on the scheduler | OS patching, firewall and backups are ours; single point of failure | Hetzner ≈ €4–6 (entry; 2026 prices changed, re-check) to ≈ €8–12 for 4 GB [Estimate]; DigitalOcean 1 GB $6 / 2 GB $12 [Price ✓, secondary sources]; DO backups +20–30 % [Price ✓] |
| **B. Single-instance container platform with a volume** (e.g. Fly.io Machine + volume) | works if strictly one Machine and the scheduler runs **in the same Machine** (e.g. a supervisor running the web workers plus a cron loop) | managed TLS, deploys from a Dockerfile, volume snapshots | a volume belongs to one Machine; scheduled Machines are separate (cannot share the volume); restarts/migrations of the Machine need care; more moving parts than a VM | shared-cpu-1x 256 MB ≈ $2.19 (from Oct 2026) [Price ✓ per Fly 2026 update; not confirmed on the main page]; 1–2 GB RAM needed → more [Estimate ≈ $10–20]; volume $0.15/GB [Price ✓] |
| **C. Managed application platform** (e.g. Render web service + disk) | a persistent disk attaches to **one service**; a separate cron service cannot read it, so the scheduler must run inside the web service | managed TLS and deploys | awkward fit (in-process scheduler or sidecar loop); disk prevents zero-downtime deploys; platform limits on long requests | Starter ≈ $7 + disk $0.25/GB [Price ✓, secondary]; realistic 2 GB instance more [Estimate ≈ $25] |
| **D. Owner's always-on computer** (Mac with launchd; private access via Tailscale) | all requirements if it never sleeps and stays online | zero hosting cost; fastest to start; strictly D-39-compliant (not hosted) | home power/network/sleep risk; not evidence of hosted operation; personal machine holds production secrets | $0 + electricity |
| E. Hyperscaler VM (AWS Lightsail/EC2, Azure, GCP) | as A | familiar enterprise tooling | more configuration and IAM surface for no Beta benefit; AWS not required | similar to A for small instances [Estimate] |

### 3.3 Recommendation (SF-02)

**Option A — one small VM in the same region as the Supabase project**, private access
only during F3/F4 (Tailscale or IP allowlist + Caddy TLS), systemd services for the
WSGI app (2–4 workers) and a systemd timer for `jobs tick`, nightly SQLite online
backups shipped off the host, Supabase Pro for Auth + PostgreSQL. Option D is the
fallback if the owner rules (SF-04) that D-39 forbids any hosted environment before
migration. Size: start with 2 vCPU / 4 GB (each worker loads the Screener data; F3
measured 4 workers locally) and measure; scale vertically if needed. **No host is
selected or provisioned.**

---

## 4. Database strategy and D-39

### 4.1 Exact approved wording [Approved]

> **D-39 — Football store (approved):** the SQLite football database stays separate
> throughout Phase 6C; the competition backend consumes it through defined integration
> boundaries and copies required data into immutable round snapshots and result
> records; migration to PostgreSQL is a separate approved task before hosted deployment.

Related: D-03 recommends migrating the store to PostgreSQL "before hosted deployment
(database design §12; timing D-39)"; 6C.5 gates list "Hosted Supabase authentication
acceptance — before hosting (Phase 10)".

**Reading.** D-39 fixes SQLite *throughout Phase 6C* (Stage F is in Phase 6C) and
places the migration *before hosted deployment*. It does not define "hosted
deployment". The two clauses are only in tension if Stage F itself is a hosted
deployment. This document does **not** reinterpret or waive D-39; it asks for a ruling.

### 4.2 Scenarios

| | **A. Supervised local exercise, SQLite** (owner's computer) | **B. Single-host private Beta, SQLite** | **C. Hosted after migrating the store to PostgreSQL** |
|---|---|---|---|
| Compliance | compliant (not hosted) | **depends on the D-39 ruling**: compliant only if "hosted deployment" means the public/production deployment | compliant |
| Technical feasibility | proven locally | proven architecture (same host requirement satisfied) | needs a migration project |
| Data integrity | WAL, per-league atomic writes; published snapshots in PostgreSQL | same | single database; transactional across stores (not needed today) |
| Backup and recovery | local backups; manual off-site copy | SQLite online backup + off-host copies; PostgreSQL provider backups | provider backups for everything; simpler |
| Complexity | low | low–medium | medium–high (dialect-specific upsert, ISO-text timestamps, 16 tables, 14 SQLite-specific code sites, store migrations 0001–0004, data copy, test matrix) [Code] |
| Development effort | none | F2 hardening only | F2 + a dedicated migration stage (estimate 1–2 stages of implementation and verification) [Estimate] |
| Operating cost | $0 host | VM ≈ €5–15 [Estimate] | VM (still needed for app/scheduler) + larger database compute [Estimate] |
| Security | personal machine holds secrets; home network | dedicated host; firewall; private access | as B; one less file to protect |
| Risks | uptime (sleep, power, ISP); not hosted evidence | same-host constraint; disk loss (mitigated by backups) | migration defects in Screener/odds/consensus; schedule delay before any live evidence |
| Future migration | unchanged (still before launch) | unchanged (still before launch); Stage F evidence on SQLite remains valid for the competition backend | done |

### 4.3 Recommendation and owner ruling requested (SF-04)

**Recommended ruling (clarification, not a waiver):** "hosted deployment" in D-39 means
the **public or production deployment** (Phase 10 launch). A **private,
access-restricted, single-host supervised Beta environment within Phase 6C.6 Stage F**
may use the SQLite football store, provided it is not publicly exposed, has verified
off-host backups, and the PostgreSQL migration remains a mandatory gate before public
launch. Alternatives: **strict** — no hosted environment of any kind before the
migration (Stage F runs on Option D, or waits for a migration stage); **migrate now** —
scenario C inside Stage F (delays live evidence; recommended only if public launch is
imminent). The owner decides; until then F3 cannot start on a hosted machine.

---

## 5. API-Football live activation prerequisites

### 5.1 Evidence required before any automated refresh

| Item | Evidence | How (proposed) |
|---|---|---|
| Active Pro subscription; daily allowance; per-minute limit | dashboard screenshot by the owner **or** one authorised quota-free `/status` call (records plan, `limit_day`, `requests.current`) | F4 step 1 (live call needs SF-05) |
| Billing behaviour at the limit | provider terms/dashboard (hard stop vs overage) | owner confirms in writing |
| Shared-key usage | provider usage at a quiet time vs the scheduler ledger; schedule of D-29b, one-off checks and manual commands | F4 step 1–2 |
| Odds coverage now | one supervised sweep (≈ 23 requests) → `odds-coverage` | F4 step 3 |
| Provider update timing | provider `update` per league over ≥ 3 days (Tue–Fri sweeps) | F4 week |
| Remaining-quota observations | `scheduler.provider_quota` rows vs `/status` | F4 |
| Scheduler limits | the approved planning baseline configured explicitly (20/tick, 450/24 h, 300 non-essential, 150 results, 3 s, 30 s, floor 2,000; client reserve 500) | F4 configuration record |
| Results-import capacity | ledger rows of results imports during the F4/F5 weekends | F4/F5 |
| Floors and cooldowns | `ops check` quota findings; no cooldown in normal operation | F4 |

### 5.2 Controlled first-live-call procedure (proposal; each step needs the owner's go)

1. **Configuration review** (no calls): host `.env` with provider calls **off**,
   refresh **off**; `jobs tick --dry-run`; `ops check` clean.
2. **Quota-free status check:** one `/status` request (by a one-off read-only command
   or the scheduler's quota gate with every other step off). Expected: plan Pro,
   `limit_day` 7,500. Stop if the plan or limit differs.
3. **One supervised manual sweep:** `refresh-data --with-odds` (≈ 28 requests incl.
   standings) or one scheduler sweep with refresh on and caps 20/450. Expected: 8
   fixtures + ≈ 14 odds requests; PSL leagues empty. Check the ledger, headers and
   `odds-coverage`.
4. **Enable provider calls for results** (when a published round is live) and refresh
   for one week, caps as approved; watch `ops check` after every slot.
5. **Rollback** at any point: `DISKI9_JOBS_PREPARE_REFRESH=off` and/or
   `DISKI9_JOBS_PROVIDER_CALLS=off`, or the pause file; manual commands remain.
6. **Stop conditions:** any 429/cooldown, quota inconsistency > 10 %, a lower daily
   limit, requests above plan, or unexplained provider usage.

Live-call budget for F4 week 1 (proposal): ≤ 300 scheduler requests/day, ≤ 1,000 in the
week, plus ≤ 50 manual. No live call is made during design.

---

## 6. Competition lifecycle validation

### 6.1 The real week (UTC) [Approved schedule]

| When | Transition | Actor | Evidence |
|---|---|---|---|
| Tue 00:00 | draft created (`created (scheduled)`) | scheduler (SYSTEM, narrow) | audit `round.create` by system; `scheduler.prepare_draft` row |
| Tue–Thu 04:15 | daily refresh sweeps | scheduler | `prepare_refresh`/`prepare_screener` rows; ledger |
| every 30 min / after sweeps | readiness (advisory) | scheduler | `prepare_readiness` rows with `data=` |
| Fri 04:15, 05:15 | publication sweeps | scheduler | as above |
| Fri ≈ 06:00 (target) | **human publication** after `round readiness` | operator (S-07) | audit `round.publish` with fingerprint; snapshot row |
| Fri → first kickoff − 15 min | entries confirmed/replaced/withdrawn | participants | submissions, withdrawals |
| deadline | lock; designation (practice / competitive by D-28) | scheduler | audit `round.lock`; designation history |
| kickoffs → final | results imports (hourly per round) | scheduler | observations; ledger class `results` |
| after evidence | settlement versions; alerts | scheduler / operator | settlement versions; alerts |
| any time before final | corrections (operator) | operator | audit `results.correct`; correction window restart |
| **max(settlement cutoff, last material change) + 24 h** (S-02) | finalisation (real database clock) | scheduler | audit `round.finalise`; final settlement |
| after finalisation | weekly results published; championship assignment (competitive only) | services | weekly results revision; championship rows; `competition verify` |

### 6.2 What can be validated when

* **Immediately (F2, local):** every transition with mocked provider and the existing
  clock-injected tests; full-week rehearsal script; restore drills. Not evidence of
  real-clock finalisation (Q-14 [Approved]).
* **Needs elapsed calendar time (F4/F5):** the Tuesday–Friday cadence on the real
  clock, provider update timing, entry deadline under real kickoffs, results arriving
  over the weekend, the settlement cutoff (latest kickoff + 48 h) and S-02 finalisation
  ≥ 24 h later — at least **8–9 days** from draft creation to finalisation for one week.
  **No development time override may be used for this evidence.**
* **Needs real participants (F5):** a competitive round (≥ 5 valid entries), Beta
  championship assignment and standings.

### 6.3 Evidence pack per genuine week (proposal)
`round inspect` before publication, at lock, after each settlement and at finalisation;
`audit list --round CODE`; `ops jobs --round CODE`; ledger totals by class; `ops check`
snapshots at each stage; `competition verify` after finalisation; operator log of
manual actions and incidents. Stored in the repository (no personal data).

---

## 7. Security and authentication

| Area | Requirement for F3/F4 | Additional for F5 (real participants) |
|---|---|---|
| Supabase Auth | hosted project (Pro recommended: Free pauses after a week, no backups [Approved evidence, 19 Nov 2026]); hosted Supabase acceptance (open gate) | email confirmation and password reset flows verified; beta terms version |
| Privileged operators | S-07 interactive authentication from the host's terminal (passwords never as arguments/variables); owner + operator accounts only | same; least privilege; review with `account list-privileged` |
| Database roles | runtime role `diski9_app` without DDL; migrations by a separate admin role; RLS for Supabase roles [Approved app_0002] | same |
| Secrets | `.env` mode 0600 for the service user; never in the repository or logs; API key, database URLs, Supabase keys, webhook URL (unused) | rotation procedure documented |
| Sessions | server-side sessions; secure cookies over HTTPS | same |
| SYSTEM | narrow lifecycle + scheduled Beta draft only; never publication or administration [Approved] | same |
| Publication | typed-code confirmation + fingerprint [Approved Stage E] | same |
| Network | firewall: 443 (and SSH from allowlisted IPs or via private network); private access to the app | public HTTPS only with SF-06 approval; rate limiting as implemented |
| Audit | audit log + `job_runs` retained; backups include them | retention per D-36 |
| Emergency access | Q-03 deferred: documented manual procedure only (`authentication.md` §6.1); **no break-glass command** | same |
| Official | refused by configuration (D-38) | same |

---

## 8. Backup and recovery

### 8.1 What to protect

| Asset | Method (proposal) | Frequency | Retention | Location | RPO / RTO |
|---|---|---|---|---|---|
| SQLite football store | online backup API (`sqlite3 .backup` / `VACUUM INTO`, WAL-safe), then `PRAGMA integrity_check` on the copy, compress, checksum | daily 03:30 UTC (before Tue–Fri sweeps) and before any manual bulk command | 14 daily | off-host object storage or a second machine; encrypted | RPO 24 h (data re-fetchable); RTO 1 h (restore) or ≈ 2 h (rebuild via `setup`, ≈ 400 requests) |
| PostgreSQL competition DB | provider daily backups (Supabase Pro: 7-day retention [Price ✓]) **plus** an independent nightly `pg_dump` (custom format) verified by restore | daily | 14 | off-provider storage, encrypted | RPO 24 h (provider) / nightly dump; RTO 2 h |
| Configuration | versioned templates in the repository; host `.env` copied to an encrypted secrets store | on change | — | password manager / vault | — |
| Secrets | provider dashboards remain the source; rotation documented | on change | — | password manager | — |
| Scheduler and audit records | inside PostgreSQL (`job_runs`, `audit_log`) | with the database | with the database | — | — |

A backup counts only after a **restore** from it has been verified (row counts,
`competition verify`, standings hash, fingerprint unchanged for the quantitative
regression).

### 8.2 Restore procedure (outline)
Stop the timer → stop the app → restore the SQLite copy (integrity check) and/or
`pg_restore` into an empty database → run migrations check (head `app_0007`) → `ops
check --deep` and `competition verify` → start the app → `jobs tick --dry-run` → start
the timer.

### 8.3 Drills (F2 locally, F3 on the host)

| Drill | Injection | Pass criterion |
|---|---|---|
| Scheduler restart | kill `jobs tick` mid-step; reboot host | Stage D marks interrupted/abandoned steps; next tick resumes; no duplicate work |
| Provider outage | block outbound API-Football | retryable/back-off; results reserve untouched; `ops check` WARNING → recovery after unblock |
| Interrupted refresh | kill during a league write | league rolled back; sweep resumes or closes partial; readiness labelled |
| SQLite corruption | replace the store with a damaged file | refresh/readiness fail closed (blocking); restore from backup within RTO |
| PostgreSQL unavailable | stop network to the database | ticks report `unavailable` (exit 1); app degrades; no partial writes; recovery |
| Missed publication | operator does not publish | `prepare_ready_unpublished` → `target_missed`; week lapses inert |
| Interrupted results import | kill mid-import | ledger counted; rerun idempotent |
| Failed/delayed settlement | blocking alert | finalisation held; `settle resolve-alert` path |
| Full restore | restore both stores into a fresh environment | standings and fingerprint reproduced; `competition verify` clean |

---

## 9. Outstanding pre-Beta dependencies

| Item | Before supervised testing (no participants) | Before private Beta with real participants | Before public launch | Before Official | Note |
|---|---|---|---|---|---|
| ML-01 Match Lab stale-adjustment race | — | **required** (targeted fix + deterministic regression) [Approved G-3] | — | — | separate authorisation |
| D-36 deletion, retention, pseudonymisation | — | **required**: a working deletion workflow and an interim retention statement approved by the owner [Approved: "before hosting real participants"] | final policy + legal review | — | no policy drafted without approval |
| Hosted Supabase authentication acceptance | required for F3 (operators sign in on the host) | required | — | — | open gate; one CI-covered test skips locally |
| D-39 ruling | **required** for a hosted F3 | — | migration before public launch (per ruling) | — | SF-04 |
| Q-07 host | **required** for F3 | — | — | — | SF-02 |
| Q-10 `/healthz` + production WSGI entry point | required (F2) | — | — | — | small code change |
| Q-12 backup/restore drill | required (F2 local, F3 host) | — | — | — | |
| API-Football verification | required for F4 | — | — | — | SF-05 |
| Q-08 webhook | optional (deferred) | recommended | recommended | — | separate approval |
| Q-03 emergency owner recovery | — | — | recommended decision | required decision | deferred; no break-glass |
| D-29 real-pool validation | — | — | — | **required** (6–8 qualifying pools) | genuine Beta weeks and D-29b pools can contribute; the trial is not restarted |
| D-38 Official activation | — | — | — | required (owner) | disabled |
| Beta terms legal review | — | recommended | **required** | — | draft `beta-2026-11` |
| 6C.3/6D backlog (screener reload latency, direct fixture URL, Your View freeze T-21) | — | — | 6D | — | not Stage F |
| Accepted performance limitations (page load ~600–730 ms) | — | accepted | revisit | — | targets unchanged |

**D-29.** Each genuine competitive Beta week whose pool opens under D-28 is a real
weekly pool; together with the D-29b research pools (from 27 Nov 2026) it can count
toward the 6–8 pools needed before Official Championship 1. Practice rounds count as
pools for D-29's pool statistics but not as competitive-lifecycle evidence (Q-14).

---

## 10. Monitoring and operational readiness

Existing tools cover nearly everything; the gap is **backup health** (F2 adds it).
Minimum Beta-week checklist (twice daily; plus around publication and finalisation):

| Signal | Command | Healthy |
|---|---|---|
| Scheduler heartbeat, lock | `ops status`, `ops check` | last tick < 15 min; no `tick_lock_lost`/indeterminate |
| Refresh completion, store freshness | `ops status` (Preparation → data refresh), `round readiness` (data refresh line) | Friday sweeps complete by ≈ 05:30; `store_not_current` absent |
| Provider quota | `ops status` quota line; `ops check` provider findings | remaining ≥ 2,000; no cooldown |
| Draft readiness | `ops status`, `round readiness --code C` | READY before the target or a clear reason |
| Publication | `round inspect --code C` | `open` with fingerprint after approval |
| Entry deadline | `round inspect` | deadline as expected; lock on time |
| Results imports | `ops jobs --round C`, `ops check` | hourly while matches in play; no `provider_failing` |
| Settlement | `settle status --round C` | versions advancing; alerts handled |
| Finalisation eligibility | `round inspect` (earliest S-02 time) | finalised after max(cutoff, last change) + 24 h |
| Backup health (F2) | `ops check` (new finding) and backup log | last verified backup < 26 h |

Webhook notifications stay off unless Q-08 activation is approved (SF-10).

---

## 11. Testing and acceptance strategy

| Layer | Where | Pass criterion |
|---|---|---|
| Offline integration (existing + F2 additions) | CI | full suite green, 13 browser tests, 0 unexpected skips, fingerprint and head unchanged |
| Real Supabase Auth | CI (existing) + hosted acceptance (F3) | sign-up, confirm, sign-in, reset, session revocation, S-07 operator sign-in on the host |
| Hosted connectivity | F3 | TLS valid; PostgreSQL direct/session lock acquisition; `jobs tick` exit 0; `ops check` clean |
| Controlled live API-Football | F4 | §5.2 steps pass; requests within budget; ledger vs headers consistent |
| Browser end-to-end on the host | F3/F4 | the 12 F2 journeys against the hosted app (private) |
| Concurrency | F2 (existing) + F3 smoke | concurrent ticks: one runs; multi-worker app stable |
| Backup and restore drills | F2 local, F3 host | §8.3 all pass |
| Failure injection | F3 | §8.3 |
| Genuine calendar-time lifecycle | F4 (practice), F5 (competitive) | §6.3 evidence pack complete; S-02 time respected; no override |
| Security | F2/F6 | secrets scan clean; no `SYSTEM` escalation; S-07 checks; firewall review |
| Final regression | F6 | as offline integration |

Failed targets are reported as failed; assertions are never weakened.

---

## 12. Preliminary monthly cost comparison (USD unless stated; before tax)

| Item | A. VM | B. Container + volume | C. Managed platform | D. Owner's computer | Status |
|---|---|---|---|---|---|
| Compute | €5–12 (Hetzner) or $12–24 (DigitalOcean 2–4 GB) | ≈ $10–20 for 1–2 GB | ≈ $7–25 | $0 | [Estimate]; DO $6/$12 [Price ✓] |
| Storage / volume | included (local SSD) | ≈ $0.15 × 5 GB ≈ $1 | ≈ $0.25 × 5 GB ≈ $1.25 | $0 | [Price ✓] rates |
| Host backups | DO +20–30 % or object storage ≈ $1–5 | snapshots ≈ $1–3 | ≈ $1–3 | external disk / cloud | [Estimate] |
| PostgreSQL + Auth | Supabase Pro **$25** (incl. $10 compute credit, Micro; daily backups 7 days) | same | same | same | [Price ✓] |
| Supabase IPv4 / direct-connection add-on (if the session pooler is not used) | ≈ $4 | same | same | same | [Estimate, verify] |
| Monitoring | $0 (CLI checks; optional free uptime pinger) | $0 | $0 | $0 | [Estimate] |
| API-Football Pro | **$16** (advertised; verify active subscription) | same | same | same | [Price ✓ per ADP-20] |
| Domain + TLS | ≈ $1 (domain amortised); TLS free (Let's Encrypt) | included | included | n/a (private) | [Estimate] |
| **Total (indicative)** | **≈ $47–75** | ≈ $53–70 | ≈ $50–75 | **≈ $41** | |

Costs depending on choices: host and size (SF-02), PostgreSQL location (SF-03; an
alternative managed PostgreSQL would add its own price), backup storage (SF-09), and
API-Football (verification, SF-05). Nothing is purchased or provisioned.

---

## 13. SF decision register (all proposals)

| ID | Question | Options | Advantages / disadvantages | Recommendation | Evidence | Dependencies | Owner approval | Blocks |
|---|---|---|---|---|---|---|---|---|
| **SF-01** | Stage F structure | (a) proposed F1–F5; (b) six checkpoints with offline hardening and a separate participant gate | (a) mixes code with infra and two risk levels; (b) clean gates | **(b)** F1–F6 (§2.2) | §2.1; D-28; D-30; G-3; D-36 | — | yes | F2 |
| **SF-02** | Host (Q-07) | A VM / B container / C platform / D owner computer / E hyperscaler | §3.2 | **A**, private access; D as fallback | §3 | SF-04 | yes | F3 |
| **SF-03** | Competition PostgreSQL location | (a) Supabase Pro project (Auth + DB); (b) separate managed PostgreSQL; (c) self-hosted on the VM | (a) one provider, backups, tested pooler rules; (b) extra vendor; (c) more ops, weaker backups | **(a)** | auth comparison (19 Nov); `authentication.md` §2.4 | budget | yes | F3 |
| **SF-04** | D-39 interpretation | clarify "hosted deployment" = public/production; strict; migrate now | §4.2 | **clarification** with conditions (§4.3) | D-39, D-03 wording | — | **yes (ruling)** | F3 (hosted) |
| **SF-05** | Live API-Football activation | none; staged §5.2 with budgets; direct activation | staged is observable and reversible | **staged §5.2**, owner go per step | E.1b design §5–6 | F3 | yes | F4 |
| **SF-06** | Beta participant scope | (a) operator accounts only, practice rounds; (b) operator-controlled ≥ 5 accounts for a competitive round; (c) invited private Beta (≥ 5 real people) | (b) would permanently put fake participants into Beta Championship 1 (insert-only, D-30); (c) needs ML-01, D-36, hosted auth | **(a) in F4, then (c) in F5**; not (b) | D-28, D-30, Q-14 | ML-01, D-36 | yes | F5 |
| **SF-07** | ML-01 timing | before F4 / before F5 | not needed without participants | **before F5** (as G-3), authorised separately | G-3 | — | yes | F5 |
| **SF-08** | D-36 timing and minimum | full policy now; minimum workflow + interim statement before F5; defer | policy needs legal review | **minimum deletion workflow + owner-approved interim retention statement before F5**; final policy before launch | D-36 | legal | yes | F5 |
| **SF-09** | Backup and restore | §8 plan; provider backups only | provider-only is unverified | **§8** (independent verified backups, drills) | Q-12 | SF-02/03 | yes | F2, F3 |
| **SF-10** | Monitoring | CLI checklist; + webhook (Q-08); + external uptime pinger | webhook needs destination approval | **CLI checklist + backup-health finding**; webhook optional later | Stage D | — | yes (webhook separately) | F3 |
| **SF-11** | Genuine-week acceptance evidence | §6.3 pack; lighter | Q-14 requires real clock, no overrides | **§6.3 pack**; practice week for timing, competitive week for championship | Q-14, S-02 | SF-06 | yes | F4, F5 |
| **SF-12** | Release boundaries | Stage F = private supervised + invited Beta; public launch and Official outside Stage F | keeps G-4 boundary | **as stated**; no public exposure, no merge/tag/release in Stage F without separate approval | G-4, D-38 | — | yes | all |
| **SF-13** | Production WSGI entry point and `/healthz` | gunicorn (as F3 measured) / waitress / dev server | dev server unsuitable for hosting | **gunicorn entry module + `/healthz`** (Q-10) in F2 | F3 tooling | — | yes | F2 |
| **SF-14** | Shared API key schedule | keep D-29b Friday 06:00 UTC capture as is; move it; separate key | collides with the publication window (E.1b runbook rule) | **keep, account for it in the floor; consider moving capture to Friday 07:00+ UTC** (D-29b change needs approval) | D-29b, E.1b | — | yes | F4 |

---

## 14. Risks and open questions

| # | Risk / question | Mitigation |
|---|---|---|
| 1 | Stage F duration: one genuine week needs ≥ 8–9 days; a competitive week also needs ≥ 5 real entrants | plan F4 and F5 calendars; accept multiple weeks |
| 2 | Beta Championship 1 permanence | no fake competitive rounds (SF-06) |
| 3 | D-39 ruling may force migration first | Option D fallback or a migration stage |
| 4 | Hosted Supabase never tested | F3 acceptance before any participant |
| 5 | Supabase direct connections may need IPv6 or an add-on; session pooler on 5432 is accepted by the lock check | verify in F3 |
| 6 | Single host is a single point of failure | backups, RTO targets, documented restore |
| 7 | Shared API key (research capture at 06:00 UTC Friday) | floors, monitoring, SF-14 |
| 8 | Memory per WSGI worker unknown on the target host | measure in F3; vertical scaling |
| 9 | Provider limits/billing unverified | §5 |
| 10 | Personal data of real participants (South African and other privacy law) | D-36 minimum, terms legal review before launch |
| 11 | CI margin ≈ 12 min | keep F2 tests light |
| 12 | Owner availability at publication time each Friday (human approval) | operator rota; `prepare_ready_unpublished` escalation |

Open questions for the owner: SF-01 to SF-14; preferred region (Supabase region close
to the VM and to South African users); who acts as operator(s) besides the owner;
budget ceiling for the Beta environment.

---

## 15. Recommended next implementation checkpoint

**F2 — Deployment readiness (offline only)**, after approval of SF-01, SF-09, SF-13
(and ideally SF-02/SF-04 so templates target the right host): production WSGI entry
point and `/healthz`; SQLite online backup and verified restore commands; PostgreSQL
dump/restore runbook; backup-health `ops check` finding; systemd service/timer and
reverse-proxy templates with a host-hardening guide; secrets template; local full-week
rehearsal and restore drill (Q-12); full Level 1/2/3 verification. No infrastructure,
no live calls, no participants.

---

## Appendix A — Dependency matrix (decision → checkpoint it must precede)

| Decision / gate | F2 | F3 | F4 | F5 | F6 |
|---|---|---|---|---|---|
| SF-01 structure | ● | | | | |
| SF-13 WSGI/`/healthz` | ● | | | | |
| SF-09 backups | ● | ● | | | |
| SF-02 host (Q-07) | ○ | ● | | | |
| SF-03 PostgreSQL location | | ● | | | |
| SF-04 D-39 ruling | ○ | ● | | | |
| SF-10 monitoring | | ● | | | |
| Hosted Supabase acceptance | | ● | | | |
| Budget approval | | ● | | | |
| SF-05 live activation | | | ● | | |
| SF-14 shared key schedule | | | ● | | |
| SF-11 evidence pack | | | ● | ● | |
| SF-06 participant scope | | | | ● | |
| SF-07 ML-01 fix | | | | ● | |
| SF-08 D-36 minimum | | | | ● | |
| SF-12 release boundaries | ● | ● | ● | ● | ● |

● required before the checkpoint starts; ○ preferred (templates target the chosen host).

*Prepared under the Stage F design and readiness authorisation of 22 Nov 2026. No
application code, migration, infrastructure, live configuration, provider call,
hosting selection or activation changed. Stage G remains unauthorised.*

Price sources consulted (22 Nov 2026; re-check before purchase): Supabase pricing
(supabase.com/pricing), DigitalOcean droplet pricing (digitalocean.com/pricing),
Fly.io pricing and 2026 pricing update (fly.io/docs/about/pricing, fly.io/pricing-update),
Render pricing (render.com/pricing), Hetzner cloud pricing (hetzner.com/cloud; 2026
changes reported by secondary sources).

---

## 16. Owner decisions (22 Nov 2026)

The proposals in §13 are now decided as follows (owner wording summarised; the
qualifications are binding).

| ID | Decision |
|---|---|
| SF-01 | **Approved:** six checkpoints F1–F6; F1 approved by this decision; every implementation checkpoint needs separate authorisation and acceptance |
| SF-02 | **Target architecture approved:** one small Linux VM (≈ 2 vCPU / 4 GB), web app and scheduler on the same host, persistent local SQLite store, systemd timer, reverse proxy with TLS, private access during F3 and F4, encrypted verified off-host backups. **No provider chosen, nothing purchased or provisioned**; provider, region and monthly spending limit are separate owner decisions before F3 |
| SF-03 | **Approved direction:** Supabase-hosted Auth and PostgreSQL for competition data; no project created |
| SF-04 | **D-39a — new owner ruling (amendment), see the decision register:** "A private, access-restricted, single-host environment used exclusively for supervised Phase 6C.6 Stage F testing may retain the SQLite football store, provided the application and scheduler are co-located, verified off-host backups are maintained, and the environment is not publicly accessible. The PostgreSQL football-store migration remains mandatory before public or production deployment." Recorded as an amendment, **not** as a reading of the original D-39 wording; it neither authorises nor waives the migration for public launch |
| SF-05 | **Approved as a future plan:** (1) offline configuration review, (2) separately authorised `/status` check, (3) separately authorised supervised refresh, (4) separately authorised weekly automated refresh, (5) review of actual consumption and evidence; caps and safeguards retained; **no live calls or activation authorised** |
| SF-06 | **Approved:** F4 operator-only practice round (no manufactured competitive entries); F5 invited private Beta with genuine participants after all gates; no fake competitive rounds; Beta championship rules and records unchanged; F4 practice evidence is never presented as competitive championship evidence |
| SF-07 | **Approved timing:** ML-01 targeted fix with deterministic regression tests before F5; not authorised under F2 |
| SF-08 | **Approved timing:** functional account-deletion workflow and owner-approved retention statement before F5; needs a separate privacy and retention design review; not authorised under F2 |
| SF-09 | **Approved for F2 planning:** WAL-compatible SQLite online backup, integrity checks and checksums, encrypted off-host copies, verified restores, PostgreSQL dump/restore runbook, drills, backup-health monitoring. **The 24-hour PostgreSQL RPO is a provisional target for the operator-only exercise only**; before F5 evaluate a tighter RPO (point-in-time recovery or more frequent backups: cost, complexity, data-loss implications). Restore verification is mandatory; a successful backup command is not evidence |
| SF-10 | **Approved:** CLI-based monitoring plus a backup-health check; webhooks stay disabled; no external notification service without separate approval |
| SF-11 | **Approved:** the evidence pack, keeping offline rehearsal, hosted supervised operation, genuine real-clock practice week and competitive private Beta week distinct; S-02 tested on genuine elapsed calendar time; no clock overrides as substitute evidence |
| SF-12 | **Approved:** no public launch, Official activation, merge, tag or release; F3 and F4 private and access-restricted; F5 participant access needs its own approval |
| SF-13 | **Approved for F2 planning:** Gunicorn and a minimal `/healthz` (no secrets or internal configuration; liveness distinct from readiness; authentication behaviour unchanged; safe for private and future hosted operation); reuse of the existing WSGI tooling assessed in the F2 plan |
| SF-14 | **Deferred:** the D-29b capture schedule stays unchanged; before F4, analyse the contention between the Friday 06:00 UTC publication target, the D-29b capture at 06:00 UTC, the 05:15 refresh and other shared-key consumers, and recommend a schedule (e.g. capture at 07:00 UTC or later) for a separate decision; the expired D-29 trial is not restarted and no research task is altered during F2 |
