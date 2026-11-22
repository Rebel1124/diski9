# Phase 6C.6 Stage F3 — Private Environment and Recovery: implementation plan

**Status:** implementation plan for owner review (planning authorised 22 Nov 2026).
**F3 implementation is not authorised.** Nothing in this plan has been provisioned,
purchased, created or deployed: no hosting account, VM, domain, hosted Supabase
project, off-host storage, live API-Football call or participant account. Every
provisioning and spending step below waits for the owner decisions in §18.

Baseline: Stage F2 **formally accepted and closed** (application `c7630fe`, full CI
run 114: 1,987 passed, 0 skipped, 13 browser tests; evidence `0c46526`, documentation
CI run 115); migration head `app_0007`; fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`; `broad60-432-v1`;
`points-150-75-v2`. Design: [`phase6c6_stage_f_design.md`](phase6c6_stage_f_design.md)
(SF-01 to SF-14, D-39a). F2 record: [`phase6c6_implementation.md`](phase6c6_implementation.md)
§12. Runbook: [`../operations_hosting.md`](../operations_hosting.md). Templates:
[`../../deploy/`](../../deploy/README.md).

**F3 purpose.** Stand up one private, access-restricted, single-host environment
(D-39a) with hosted Supabase Auth and PostgreSQL, prove it is secure, recoverable and
operable **with provider calls and refresh off**, and close the two carried recovery
risks F3-R1 and F3-R2. F3 is **not** live activation (F4), not an invited Beta (F5),
and not evidence of real-clock competitive validation.

**Boundaries kept throughout F3:** D-39a SQLite exception (private, co-located,
verified off-host backups, not public); human-only publication; Stage D locking and
provider safeguards unchanged; `DISKI9_JOBS_PROVIDER_CALLS=off`;
`DISKI9_JOBS_PREPARE_REFRESH=off`; Official disabled; D-29b schedule unchanged; no
participant accounts (owner/operator accounts only); no public exposure; no merge, tag
or release; **no live API-Football call of any kind** (the environment holds no
API-Football key).

---

## A. Hosting-provider comparison and recommended configuration

Workload (measured, Phase 6C.5 F3 and F2): one Gunicorn app with 2–4 workers (each
loads the Screener data: ~300–500 MB RSS per worker observed locally), the 5-minute
tick, a 37 MB SQLite store, nightly backups. Requirement: **2 vCPU, 4 GB RAM, ≥ 40 GB
SSD**, a static IPv4 (or working IPv6 to Supabase), snapshots, a firewall, and a
region close to the Supabase database (B).

| Option | Location | Indicative price (verify at selection) | For | Against |
|---|---|---|---|---|
| **1. Hetzner Cloud** (shared vCPU, e.g. CX33/CPX-class 2–4 vCPU / 4–8 GB) | Germany (Nuremberg, Falkenstein), Finland | ≈ €6–€15/month after the June 2026 price adjustment; snapshots/backups extra (~20 %) | lowest cost; EU data centre close to AWS Frankfurt (< 10 ms); simple firewall and snapshots | pricing and plan availability changed in 2026 (some CX plans unavailable); EU account verification |
| **2. DigitalOcean** (Basic Droplet 2 vCPU / 4 GB) | Frankfurt (FRA1), London (LON1) | ≈ $24/month + backups ≈ $5 | mature tooling, managed firewall, predictable billing; same metro as AWS eu-central-1 / eu-west-2 | ~2× Hetzner |
| **3. Vultr** (Cloud Compute 2 vCPU / 4 GB) | Johannesburg **or** Frankfurt/London | ≈ $20/month (Johannesburg listing, Nov 2026) + backups | the only mainstream option with a South African location | a Johannesburg VM sits ~160–180 ms from the European Supabase database (see B) |
| 4. Hyperscaler VM (AWS Lightsail/EC2, Azure, GCP) | EU or South Africa (AWS Cape Town, Azure/GCP Johannesburg) | ≈ $20–$45/month for 2 vCPU / 4 GB + egress | enterprise controls; same cloud as Supabase (AWS) | more configuration, egress charges, higher cost |
| 5. Local South African VPS (e.g. ZA hosts) | Johannesburg / Cape Town | ≈ R260–R320/month (VAT incl.) | local billing, lowest user latency | same database-latency problem as option 3; variable snapshot/support quality |

**Recommendation:** see **A.2** (owner-requested addendum, 22 Nov 2026), which adds
Hostinger and the Black Friday / Cyber Monday 2026 promotions and supersedes the
earlier DigitalOcean-first recommendation. Final choice is owner decision **F3-D1**.

### A.2 Addendum: Hostinger, Hetzner and DigitalOcean with 2026 promotions

Research and planning only: nothing has been purchased, reserved or provisioned.
Researched 22 Nov 2026 from provider pages and third-party price listings; promotional
figures in particular came from deal sites that disagree with each other, so **every
price, term and date must be re-checked at checkout** before the owner approves a
purchase. USD unless stated; exchange rate assumed €1 ≈ $1.16.

**Like-for-like specification and terms**

| | **Hostinger KVM 2** | **Hetzner CX33** (cost-optimised, shared) | **DigitalOcean Basic** 2 vCPU / 4 GB |
|---|---|---|---|
| CPU / RAM | 2 vCPU (shared) / **8 GB** | 4 vCPU (shared) / 8 GB | 2 vCPU (shared) / 4 GB |
| Storage / transfer | 100 GB NVMe / 8 TB | 80 GB SSD / 20 TB (EU) | 80 GB SSD / 4 TB |
| Virtualisation | KVM, full root | KVM, full root | KVM, full root |
| Regions relevant to Diski 9 | Europe: France, Germany, Lithuania, UK (Netherlands also listed by a third party); **no Africa**; location **cannot be changed after setup** (reinstall to move) | Germany (Nuremberg, Falkenstein), Finland; no Africa | **Frankfurt, London**, Amsterdam; no Africa |
| Latency to the Supabase database (Frankfurt/London) | low if the data centre is in Germany or the UK (city to confirm at setup) | < 10 ms (Germany ↔ AWS Frankfurt) | ≈ 1–2 ms (same metro) |
| Latency to South African users | ≈ 160–180 ms per HTTP request from any EU site (the app must sit next to the database; see B) | same | same |
| Backups / snapshots | **weekly automatic backups included**; manual snapshot(s) included (one per third party); daily backups a paid add-on | paid backups (≈ 20 % of the server price; unverified for 2026) and paid snapshots | weekly backups **+20 %** ($4.80); daily +30 %; snapshots per GB |
| Firewall | hPanel VPS firewall + `ufw` (hPanel feature to be confirmed) | Hetzner Cloud Firewall (free) + `ufw` | DigitalOcean Cloud Firewall (free) + `ufw` |
| Billing model | **prepaid term**; promotional price applies to the first term only; billing starts **at purchase**, not at setup | monthly, billed hourly; no prepayment | monthly cap, per-second billing from 2026; no prepayment |
| Promotion (Black Friday / Cyber Monday 2026) | **Live:** KVM 2 ≈ **$8.79/month on a 24-month prepay** ($210.96 upfront; some listings show $8.99), renews at **$14.99/month**; sale reported to run **19 Oct – 14 Dec 2026**; a 12-month promotional price was not confirmed | **none found**; a 15 % price cut for Helsinki cloud servers from 10 Nov 2026 is standing, not a sale; **"limited availability of cloud instances" for some new customers since 26 Jun 2026** | **none announced** (third parties expect something 27–30 Nov; unconfirmed); new-account credit offers exist but were not verified |
| Regular / renewal price | $14.99/month after the promo term | €8.49/month + IPv4 (≈ €0.60) — June 2026 list price (+31 %) | $24/month |
| Reliability signal | large shared-hosting provider; VPS track record less established for production workloads; SLA terms to be read | solid hardware; 2026 price waves and capacity limits | mature cloud, 99.99 % Droplet SLA advertised |
| Tax (South African buyer) | 15 % SA VAT expected on foreign electronic services (Hostinger's practice not confirmed) | VAT treatment for a South African customer to be confirmed | DigitalOcean documents South African VAT on its invoices |

**Total cost of the server alone** (excluding Supabase, storage and domain; "+VAT" adds 15 %)

| Horizon | Hostinger KVM 2 (24-month promo, then renewal) | Hetzner CX33 + IPv4 + backups (≈ €10.80 ≈ $12.50/month) | DigitalOcean $24 + weekly backups ($28.80/month) |
|---|---|---|---|
| Upfront payment | **$210.96** (+VAT ≈ $242.60) | none | none |
| 12 months | $210.96 already paid for 24 months (no refund after the money-back window); a monthly plan without the promo ≈ $179.88 | ≈ $150 (+VAT ≈ $173) | $345.60 (+VAT ≈ $397) |
| 24 months | **$210.96** (+VAT ≈ $243) | ≈ $300 (+VAT ≈ $345) | $691.20 (+VAT ≈ $795) |
| 36 months | $210.96 + 12 × $14.99 = **$390.84** (+VAT ≈ $449) | ≈ $450 (+VAT ≈ $518) | $1,036.80 (+VAT ≈ $1,192) |

Common costs for every option: Supabase Pro ≈ $25/month (Micro compute covered by the
included credit; $300 / $600 / $900 over 12 / 24 / 36 months before any VAT),
off-host encrypted storage ≈ $1–5/month, domain ≈ $15/year.

**Is Hostinger KVM 2 technically suitable for Diski 9's single-host design?** Yes,
subject to four checks before purchase.

| Requirement | Assessment |
|---|---|
| Gunicorn (2–4 workers at ~300–500 MB each) | ✅ 8 GB RAM is ample (twice DigitalOcean's 4 GB); 2 shared vCPUs match the F3 load profile |
| systemd units and timers (web, 5-minute tick, nightly backup) | ✅ full-root KVM with Ubuntu 24.04 templates |
| Caddy with automatic TLS, IP allowlist | ✅ ports 80/443 available; private access via `ufw`/hPanel firewall plus the Caddy allowlist |
| SQLite in WAL mode | ✅ local NVMe block storage under KVM (not a network or container filesystem) |
| Scheduled jobs and Stage D locking to Supabase | ✅ outbound PostgreSQL; ⚠ **confirm IPv6** for the Supabase direct endpoint, otherwise use the session pooler (E) |
| Encrypted off-host backups (`age` + object storage) | ✅ outbound HTTPS; the included weekly Hostinger backup is an extra convenience, not the verified backup |
| Data-centre location | ⚠ choose **Germany or the UK** at setup (cannot be changed later); confirm the city before buying |
| Commercial | ⚠ 24-month prepayment and renewal at ~1.7× the promo price; shared-vCPU contention; less mature VPS support than DigitalOcean |

Pre-purchase checks: (1) the German/UK data-centre city and a test of latency to the
Supabase region; (2) IPv6 availability; (3) the money-back/refund terms for VPS; (4)
the exact checkout total including VAT and the renewal price.

**Can the discount be secured without provisioning or activating a server?** Partly.
Hostinger lets a VPS order be paid and **set up later** (Billing → Subscriptions →
Set up), so no server needs to exist on day one. **But the billing term starts at the
purchase date, whatever the setup date**, so the 24-month clock (and any money-back
window) runs from purchase. Buying in the sale window (reported to end **14 Dec
2026**; Black Friday 27 Nov, Cyber Monday 30 Nov) costs ≈ $8.79 for each idle month
before F3 implementation is authorised. Hetzner and DigitalOcean need no early
purchase: they bill only while a server exists.

**Ranked recommendation (for F3-D1)**

1. **Hostinger KVM 2, 24-month promotional term, data centre in Germany or the UK**:
   lowest cost over 24–36 months and the most memory, technically suitable. This holds
   only if the four pre-purchase checks pass and the owner accepts a ≈ $243 prepayment
   (incl. VAT), the renewal step-up and less mature VPS support. Buy only after F3
   implementation is authorised, or with the explicit acceptance that the term starts
   immediately.
2. **DigitalOcean Basic 2 vCPU / 4 GB, Frankfurt**: the best fallback and the right
   choice if F3 may be short-lived, if the checks fail, or if no prepayment is wanted.
   No lock-in, mature networking/firewall/backups, same metro as Supabase; ≈ 2–3× the
   server cost.
3. **Hetzner CX33, Germany**: best monthly value with no prepayment, but new-customer
   cloud availability has been restricted since June 2026 and prices changed twice in
   2026. Treat it as an opportunistic alternative only if an account can create servers.

**Proposed spending ceiling (for F3-D3):**
* monthly run-rate (Supabase + storage + domain, plus the server where billed monthly)
  ≤ **US $60 average**, hard alert at $60, absolute cap **$75/month**;
* **one-off prepayment ≤ US $250 incl. VAT**, and only for the Hostinger option;
* **24-month programme cap ≈ US $1,200 incl. VAT** for F3 infrastructure (Hostinger
  ≈ $243 + Supabase ≈ $690 incl. VAT + storage and domain ≈ $100 leaves headroom; the
  DigitalOcean path ≈ $795 + $690 + $100 ≈ $1,585 would need the cap raised to
  ≈ $1,600);
* no annual prepayment to Supabase or the storage provider, and no purchase before
  explicit owner approval.

## B. Region selection, Supabase connectivity and South African latency

* **Supabase offers no African region** (a South Africa option existed only in its
  early alpha and is no longer available). The nearest hosted regions are European
  (Frankfurt `eu-central-1`, London `eu-west-2`, Ireland `eu-west-1`); Mumbai is
  further from South Africa in practice.
* Each page view makes several database round trips (session resolution, round,
  entries, leaderboard). The **app must therefore sit next to the database**, not next
  to the users: a Johannesburg VM with a Frankfurt database would add ~160–180 ms per
  query, i.e. seconds per page. A Frankfurt VM with a Frankfurt database adds
  ~1–10 ms per query; users in South Africa then see one ~160–180 ms round trip per
  HTTP request (plus TLS set-up), which the F3 load measurements (≈ 213 req/s locally,
  Screener cached) easily absorb.
* **Proposed:** Supabase **Frankfurt (`eu-central-1`)**, VM in **Frankfurt**
  (DigitalOcean FRA1) or **Germany** (Hetzner). London is the equivalent alternative
  (similar latency to South Africa). Decision **F3-D2**.
* **Measured in F3 (N):** RTT VM→database (target p95 < 10 ms), and page timings from
  a South African vantage point (the owner's own connection) for the Screener, Weekly
  Challenge, My Challenge and leaderboards (targets: p95 TTFB < 800 ms cached; full
  page < 3 s on a typical ZA fibre/LTE connection). If targets are missed, a CDN for
  static assets is the first lever, never moving the app away from the database.
* Data residency: participant data would be stored in the EU (Supabase) — to be noted
  in the F5 privacy/retention statement (D-36); no participant data exists in F3.

## C. Monthly cost estimate and proposed budget ceiling (no commitment)

| Item | Low (Hetzner) | Default (DigitalOcean) | Notes |
|---|---|---|---|
| VM 2 vCPU / 4 GB | ≈ $8–$16 | ≈ $24 | Hetzner prices in EUR after the June 2026 adjustment |
| VM snapshots/backups | ≈ $2–$3 | ≈ $5 | provider snapshots are a convenience, not the verified backup |
| Supabase Pro organisation | $25 | $25 | includes $10 compute credit (covers Micro) |
| Supabase compute Micro (1 GB) → Small (2 GB) | $0 → +$5 | $0 → +$5 | start Micro; Small only if measurements need it |
| Supabase IPv4 add-on (only if the VM cannot reach the IPv6 direct endpoint and the session pooler is unsuitable) | $0–$4 | $0–$4 | see E |
| Off-host encrypted backup storage (≤ 10 GB) | ≈ $1–$5 | ≈ $1–$5 | object storage in a **different provider/region** from the VM |
| Domain name (if none is available) | ≈ $1–$2 | ≈ $1–$2 | annual fee spread monthly |
| API-Football Pro (existing subscription) | ($16) | ($16) | already paid; **no F3 calls** — not an F3 cost |
| **Estimated F3 total (new spend)** | **≈ $37–$55** | **≈ $56–$66** | excludes the existing API-Football plan |

**Proposed budget ceiling for F3: US $75 per month** of new spend (superseded in
detail by A.2: ≤ $60 average, $75 cap, one-off prepayment ≤ $250, 24-month cap) (≈ R1,400 at the
current rate; to be re-checked), with a hard alert at $60 and no annual prepayments.
Provider billing alerts are configured before anything is created. Decision **F3-D3**.
All prices are indicative (third-party listings and provider pages, Nov 2026) and must
be re-verified on the providers' own pages at selection.

## D. Hosted Supabase Auth and PostgreSQL configuration

* One **new** Supabase project in the chosen region (owner creates it; decision
  **F3-D4**), Pro plan, Micro compute, organisation MFA on, owner as the only org
  member (plus the operator if approved).
* **Auth:** email/password only; email confirmation on; site URL and redirect
  allow-list set to the private site name only; signups **disabled** after the owner
  and operator accounts exist (no participant accounts in F3); leaked-password
  protection and minimum password length per [`../authentication.md`](../authentication.md);
  SMTP: Supabase's built-in sender is acceptable for ≤ 2 operator accounts (custom SMTP
  is an F5 decision). Rate limits left at defaults.
* **Database:** `diski9 app-db upgrade` to `app_0007`, `app-db check`; application
  role per [`../backend.md`](../backend.md) (least privilege, no `service_role` key on
  the VM); Data API exposure of `app` schema **off** (the hardening checks in the
  Supabase acceptance suite apply); PITR not purchased in F3 (24-hour RPO provisional,
  §J).
* The app's publishable key and URLs go into `/etc/diski9/diski9.env` only. The
  service-role key and database owner password stay in the owner's password manager,
  never on the VM except the application connection string.
* **Hosted Supabase acceptance (L)** runs before anything else touches the project.

## E. PostgreSQL connection modes and Stage D locking

Stage D requires a **session-scoped** advisory lock on a connection that stays the
same server session for the whole tick (direct connection or a session-mode pooler;
the transaction pooler on port 6543 is refused by `locking.check_lock_url`).

| Endpoint | Mode | Stage D lock | Web app | Notes |
|---|---|---|---|---|
| Direct `db.<ref>.supabase.co:5432` | direct | ✅ (preferred) | ✅ | Supabase direct connections are IPv6-only unless the IPv4 add-on is bought; the VM must have working IPv6 |
| Supavisor session pooler `…pooler.supabase.com:5432` | session | ✅ expected (connection pinned per client session) | ✅ | IPv4; F3 verifies the lock probe end to end |
| Supavisor transaction pooler `…:6543` | transaction | ❌ refused by code | possible but not used | never configured for the tick |

F3 verification: `tools/ops/scheduler_lock_probe.py` (existing) against the chosen
endpoint — two concurrent ticks, holder termination, lock-loss detection, the R1–R6
remediation behaviours — plus `jobs tick --dry-run` and a real tick with provider calls
off. `DISKI9_JOBS_DATABASE_URL` uses the direct endpoint if IPv6 works, otherwise the
session pooler; `DISKI9_APP_DATABASE_URL` may use the session pooler. Decision **F3-D5**
(IPv6 direct vs session pooler vs IPv4 add-on). No change to Stage D code is planned;
any incompatibility is a stop condition reported to the owner.

## F. VM hardening, firewall, TLS and private access

Per [`../operations_hosting.md`](../operations_hosting.md) §1, applied and evidenced:

* Ubuntu 24.04 LTS; unattended security upgrades; `diski9` system user; `/etc/diski9`
  `0700`, env file `0600`; `/var/lib/diski9` `0750`; journald size limits; chrony.
* SSH: keys only, no root login, no passwords; **provider firewall + `ufw`**: SSH and
  443 only from the owner's/operator's allowlisted addresses (or SSH only via the
  provider's console/VPN if addresses are dynamic — decision **F3-D6**); 80 only if
  needed for certificate issuance; everything else closed; Gunicorn on 127.0.0.1.
* **TLS:** Caddy with automatic certificates for a private sub-domain the owner
  controls (decision **F3-D7**: domain/sub-domain); HSTS and security headers from the
  template; `/readyz` host-only.
* **Private access (SF-12, D-39a):** Caddy `remote_ip` allowlist for every path, plus
  the provider firewall; no public DNS listing beyond the sub-domain itself; robots
  disallow; signups off. Alternative if addresses are dynamic: an authenticated tunnel
  (e.g. WireGuard to the VM) instead of an IP allowlist — decision **F3-D6**.
* Evidence: `ss -tlnp`, `ufw status`, an external port scan from a non-allowlisted
  address (only refused/filtered), TLS grade check, response headers, SSH config dump
  (no secrets).

## G. Production WSGI and scheduler systemd integration

* Install exactly the accepted commit (`c7630fe` or the F3-accepted successor) into
  `/opt/diski9`; `uv sync --frozen --extra server`; record `git rev-parse HEAD` and
  `uv.lock` hash in the evidence pack.
* Units from `deploy/systemd/`: `diski9-web` (Gunicorn 2 workers, raise to 3–4 only
  if memory measurements allow), `diski9-tick.timer` (5 min, oneshot),
  `diski9-backup.timer` (03:30 UTC); environment from the template with **provider
  calls off, refresh off, caps 10/100, `DISKI9_JOBS_PREPARE=off`** (draft preparation
  stays off in F3 unless the owner enables it for F4 rehearsal), notifications off.
* Checks: `/healthz`, `/readyz`, `ops status`, `ops check`, `jobs tick` exit codes,
  restart behaviour (`systemctl kill` of a worker → restarted; reboot → all units back,
  timer catches up with `Persistent=true`).

## H. SQLite persistent storage and safe offline recovery

* Store at `/var/lib/diski9/diski9.sqlite` on the VM's local SSD (not network
  storage; SQLite WAL requires a local filesystem). Absolute path (enforced by
  `diski9.wsgi`).
* **Seeding:** the store is created on the VM by `diski9 init-db` and populated from a
  verified backup of the local development store (`backup store` locally →
  encrypted transfer → `restore store --purpose recovery --to …` on the VM → offline
  switch), because F3 makes **no** API-Football calls. The data are therefore as old
  as the copy; readiness will report stale odds, which is correct for F3.
* **Recovery:** live replacement stays disabled (accepted F2 decision). F3 rehearses
  the documented **offline switch** on the real host with systemd: pause file → stop
  units → `systemctl is-active` all inactive → `fuser`/`lsof` empty → repoint
  `DISKI9_DATABASE_URL` → start → `/readyz` + `ops check`. F3 evaluates (design only,
  for owner decision) whether a host-verified in-place procedure using systemd state
  plus `fuser` is safe enough to implement later; F3 does not implement it.

## I. Encrypted off-host backups for both databases (closes F3-R2 part 1)

* **Football store:** nightly `diski9 backup store` (levels 1–2), then the
  `deploy/bin/diski9-offhost-copy` hook: `age`-encrypt (recipient public key on the
  VM; **private key held off the VM** by the owner) the backup and manifest, upload to
  object storage at a **different provider and region** (decision **F3-D8**: e.g.
  Backblaze B2 / Cloudflare R2 / another provider's object storage, EU), with an
  upload-only, bucket-scoped credential; then `backup record --kind offhost-copy`
  (level 3, reported).
* **PostgreSQL:** nightly `pg_dump --format=custom --no-owner` on the VM via the
  service user's `pgpass` (0600) with a **read-only backup role** (decision: create
  role in D); `backup record --kind postgres`; same encryption and upload; level 3.
* Retention: 14 daily + 8 weekly copies off-host (lifecycle rule); object lock /
  versioning if the storage supports it, so the VM's credential cannot delete history.
* Supabase's own daily backups remain a baseline, **not** verified recovery.

## J. Restore verification, RPO and RTO measurement (closes F3-R2 part 2)

* **Retrieval:** from a machine other than the VM (owner's machine), download the
  latest encrypted copies, decrypt with the off-VM private key, verify the manifest
  checksums.
* **Football-store drill:** `restore store --purpose drill --source-origin offhost`
  into a new path on a scratch location → verifies against the manifest; recorded as
  level 4 (matches a recorded backup).
* **PostgreSQL drill:** restore the decrypted dump into a **new empty database**
  (a second, temporary Supabase project, or a local disposable PostgreSQL with
  `tools/f2_restore_drill.py`-style comparison; decision **F3-D9**), check head
  `app_0007`, `competition verify`, `ops check --deep`, per-table counts/hashes vs the
  source at dump time; `backup record --kind postgres-drill --source-origin offhost`.
* **Measured:** RPO actually achieved (time between the last committed change and the
  dump used; target ≤ 24 h, provisional, operator-only); RTO for (a) football store:
  retrieval + decrypt + restore + offline switch + readiness (target ≤ 30 min);
  (b) PostgreSQL to a new database including reconciliation checklist (target ≤ 2 h).
* The tighter-RPO evaluation (PITR add-on vs more frequent dumps: cost, complexity,
  data loss) is **prepared** in F3 as a short decision note for F5; no PITR purchase.

## K. Provider-hold safeguards and manual provider commands (closes F3-R1 analysis)

Current behaviour (accepted F2): the hold is placed by `backup record --kind
postgres-restore`; it covers the scheduler only.

F3 plan:
1. **Fail-closed hosted recovery procedure** (runbook update, no code in planning):
   the restore checklist makes "record the restore and **confirm the hold is active**
   (`ops status` shows `PROVIDER HOLD`, `ops check` shows
   `provider_hold_after_restore`)" a precondition **before** the environment file is
   switched to the restored database (cutover). Rehearsed in the J drill on the
   temporary database.
2. **Design options for automatic activation** (for owner decision before F4,
   **F3-D10**; none implemented in F3 without approval):
   (a) cutover helper `diski9 ops cutover-check` that refuses to print the go-ahead
   unless the target database carries an `ops.restore_postgres` record;
   (b) a restored-database fingerprint: the tick compares the newest `job_runs` id/time
   with a host-local marker file written after every successful tick and enters the
   hold automatically when the database is older than the host marker (detects a
   rolled-back database without operator action);
   (c) both. Recommendation: (c), implemented in F4-prep after approval.
3. **Manual provider-command exposure assessment:** inventory every command that can
   call API-Football (`setup`, `sync-reference`, `ingest-fixtures`, `collect-odds`,
   `sync-standings`, `refresh-data`, `monitor-odds`, `results import`/settlement paths
   via the provider, the D-29b collector) and record for each: whether it reserves in
   the scheduler ledger, whether the hold applies, whether it can run on the F3 host.
   In F3 the host has **no API-Football key and no proxy**, so every such command fails
   closed by construction; this is verified (each command run once with
   `DISKI9_API_FOOTBALL_KEY` unset → refused without a request; outbound to
   `v3.football.api-sports.io` blocked by the VM's egress firewall). Options for F4
   (owner decision **F3-D11**): extend the hold check to the shared API-Football client
   factory used by manual commands, or require `--i-understand-hold` style overrides
   that are audited.

## L. Hosted Supabase authentication acceptance

Run the existing Supabase integration suite against the **hosted** project (owner
supplies credentials through the environment/credential store; never in chat or the
repository): sign-up disabled except bootstrap, owner bootstrap (`account
bootstrap-owner`), operator grant, sign-in/sign-out, session rotation, password reset
email delivery, re-authentication windows (T-12/T-14), suspension, CSRF/origin checks
over HTTPS with the real cookie prefix `__Host-`, JWT issuer/audience, clock skew, Data
API exposure checks. Evidence: test report plus screenshots of the account pages (no
personal data beyond the owner/operator usernames). Any failure is a stop condition.

## M. Scheduler recovery, failure injection and monitoring

On the host, provider calls off:
* tick every 5 minutes for ≥ 72 hours with `ops status` heartbeat healthy; `ops
  check` clean except expected INFO (provider calls off, refresh off, backup
  monitoring then **on** once I is running).
* Failure injection (each with expected outcome recorded): kill `diski9-tick` mid-run
  (abandonment after 20 min, Stage D); stop the web unit (health 502 at the proxy,
  `/healthz` restored on restart); database unreachable (block egress to Supabase for
  10 min → tick `unavailable`, exit code, no partial writes, recovery after unblock);
  disk nearly full (backup fails → `backup_failed`, app keeps serving); store
  corruption on a **copy** (verify detects) and the offline switch rehearsal (H);
  reboot.
* Monitoring: `ops check` run by a systemd timer every 15 min writing to the journal;
  notifications stay **off** (webhooks not approved); the owner reviews `ops status`
  daily during F3. Optional: provider uptime check on `/healthz` from an allowlisted
  monitor (decision **F3-D12**).

## N. Hosted browser smoke tests and performance

* Playwright smoke suite (existing journeys, read-mostly) run **from the owner's or a
  CI-like machine against the private URL** (allowlisted address), as owner/operator:
  Screener, Match Lab, Weekly Challenge (development/practice round only), My
  Challenge, leaderboards, account pages, at desktop/tablet/mobile widths.
* Performance: page timings from South Africa (B), VM→DB RTT, Gunicorn worker memory,
  CPU at idle and during a 60-second `phase6c5_f3_load.py`-style read load at
  ≤ 20 req/s (no write load against hosted data), backup and restore durations.
* A development/practice round (no championship effect) may be opened and settled
  with **synthetic** results (dev stream) to exercise the hosted lifecycle; no Beta
  competitive round is created (SF-06).

## O. Security and secrets

* Secrets inventory: application DB URL, scheduler DB URL, Supabase publishable key,
  app secret key, token encryption key, backup DB role password (pgpass), off-host
  storage credential, `age` recipient public key (not secret). Not on the host: the
  API-Football key, Supabase service-role key, `age` private key, owner passwords.
* Storage: `/etc/diski9/diski9.env` (0600), `~diski9/.pgpass` (0600), storage
  credential in a root-only file used by the hook; password manager for the owner
  copies. Never in the repository, unit files, shell history, tickets or chat.
* Rotation drill: rotate the app secret key and the storage credential once in F3;
  confirm sessions invalidate as designed.
* Scans: `ops` outputs, logs, manifests and evidence pack grepped for the planted and
  real secret patterns before anything is committed; the repository secret-scanning
  check before every push.
* Access: owner and (if approved) one operator; SSH keys per person; provider and
  Supabase accounts with MFA.

## P. Rollback and incident response

* **Application rollback:** reinstall the previous accepted commit (`git checkout`,
  `uv sync --frozen --extra server`, restart); no migration in F3, so no database
  rollback is needed.
* **Environment rollback:** destroy the VM and Supabase project (owner action) —
  nothing depends on them; the local development environment remains the reference.
* **Incidents:** severity table (secret exposure → rotate immediately and stop; public
  exposure → firewall closed and stop; unexpected provider call → stop, verify ledger
  and provider dashboard, report; data loss → restore drill procedure and incident
  record). Every incident is written to the F3 evidence pack and reported to the owner
  before F3 continues.

## Q. Acceptance checklist and evidence requirements

| # | Criterion | Evidence |
|---|---|---|
| 1 | Provider, region, budget and Supabase project approved before creation | owner decision records F3-D1–D4 |
| 2 | Host hardened; only allowlisted access; TLS and headers | §F evidence set; external scan |
| 3 | Hosted Supabase acceptance passed | §L test report |
| 4 | Stage D lock verified on the chosen connection mode | lock-probe report |
| 5 | App and tick running from the accepted commit; health and readiness green | commit hash, unit status, `/readyz`, `ops status` |
| 6 | ≥ 72 h of healthy ticks with provider calls and refresh off; ledger shows **zero** provider requests | `ops status`, `ops jobs`, `job_runs` count, provider dashboard unchanged |
| 7 | Encrypted off-host backups of both databases for ≥ 3 consecutive nights | levels 1–3 in `ops status`; storage listing (names/sizes only) |
| 8 | Off-host retrieval and restore drills for both databases passed; RPO/RTO measured | level 4 records; drill reports |
| 9 | Hold confirmed active before cutover in the PostgreSQL drill; manual-command exposure assessed and failing closed | drill log; command inventory with results |
| 10 | Offline football-store switch rehearsed on the host | runbook log |
| 11 | Failure-injection results as expected | §M table |
| 12 | Hosted browser smoke and performance within targets (or explained) | report, screenshots |
| 13 | Secrets inventory, rotation drill, scans clean | §O checklist |
| 14 | No live API-Football call, no participant account, no public exposure, no Official, D-29b unchanged, no merge/tag/release | ledger, Supabase user list (owner/operator only), firewall, decision register |
| 15 | Monthly spend within the approved ceiling | provider invoices/estimates |

Evidence pack: one directory in the repository (`docs/architecture/f3_evidence/`) with
reports and redacted outputs only — no secrets, no IP addresses of personal
connections, no connection strings — plus the implementation record section.
Real-time items are labelled as such; anything compressed or synthetic is labelled
simulated.

## R. Owner decisions and spending approvals required before provisioning

| ID | Decision | Recommendation |
|---|---|---|
| F3-D1 | Hosting provider and plan | ranked in A.2: Hostinger KVM 2 (24-month promo, DE/UK) if the pre-purchase checks pass; else DigitalOcean Basic 2 vCPU / 4 GB Frankfurt; Hetzner CX33 opportunistically |
| F3-D2 | Region | Frankfurt for both Supabase and the VM (London equivalent) |
| F3-D3 | Budget ceiling and billing alerts | ≤ $60/month average, $75 cap; one-off prepayment ≤ $250 incl. VAT (Hostinger only); 24-month cap ≈ $1,200 (≈ $1,600 on the DigitalOcean path) |
| F3-D4 | Create the hosted Supabase project (owner action) and plan/compute | Pro, Micro, Frankfurt, signups disabled after bootstrap |
| F3-D5 | Database connection mode | direct IPv6 if available, else session pooler; IPv4 add-on only if both fail |
| F3-D6 | Private-access method | provider firewall + Caddy allowlist; WireGuard if addresses are dynamic |
| F3-D7 | Domain / sub-domain for TLS | an owner-controlled private sub-domain |
| F3-D8 | Off-host storage provider and key custody | EU object storage at a different provider; `age` private key held by the owner off the VM |
| F3-D9 | Where the PostgreSQL restore drill runs | temporary second Supabase project (measures hosted RTO) or local disposable database |
| F3-D10 | Automatic hold activation design (for F4-prep) | option (c): cutover check + rolled-back-database detection |
| F3-D11 | Manual provider-command coverage (for F4) | extend the hold to the shared client factory |
| F3-D12 | External uptime monitor | optional; free tier on `/healthz` only |
| F3-D13 | Operator account in F3 | owner plus at most one operator; no participants |
| F3-D14 | Whether to buy a promotional prepaid term before F3 implementation is authorised (Hostinger sale reported to end 14 Dec 2026; the term starts at purchase) | owner's call; recommended only if F3 implementation is expected within weeks |

Nothing is purchased or created until D1–D4 (and D6–D8 for the host build) are
approved. F3 implementation itself needs separate authorisation after this plan.

## Risks carried forward

* **F3-R1** (from F2): provider-hold activation depends on recording the restore;
  manual provider commands are not covered. **Before F4:** a fail-closed hosted
  recovery procedure, explicit confirmation that the hold is active before database
  cutover, and an assessment of manual provider-command bypasses (§K).
* **F3-R2** (from F2): encrypted off-host backups, successful retrieval and genuine
  off-host restore drills have not been demonstrated. **F3 must verify them on the
  selected private host before operational acceptance** (§I, §J).
* The 24-hour PostgreSQL RPO stays provisional and limited to operator-only testing; a
  tighter RPO is a gate before F5.
* Before F4: SF-14 shared-key schedule analysis; before F5: tighter RPO, ML-01, D-36
  workflow and retention statement, participant-access approval.

## Sources for A–C and A.2 (consulted 22 Nov 2026; re-verify before purchase)

* Supabase: [regions](https://supabase.com/docs/guides/platform/regions),
  [South Africa region removal](https://www.github.com/supabase/supabase/discussions/3515),
  [pricing](https://supabase.com/pricing),
  [compute usage](https://supabase.com/docs/guides/platform/manage-your-usage/compute).
* Hostinger: [VPS plans](https://www.hostinger.com/vps-hosting.md),
  [server locations](https://www.hostinger.com/support/1583267-where-are-hostinger-servers-located/),
  [setting up orders (billing starts at purchase)](https://www.hostinger.com/support/4598546-how-to-set-up-orders-at-hostinger/),
  [purchasing a VPS](https://www.hostinger.com/support/1583582-how-and-why-to-purchase-vps-hosting-at-hostinger/),
  [Black Friday VPS deals](https://www.hostinger.com/ae/black-friday-vps-deals);
  third-party promo listings: [CriticNest](https://criticnest.com/hostinger-vps-coupon-code),
  [gauravtiwari.org](https://gauravtiwari.org/deal/vps-black-friday-deals/),
  [Findstack](https://findstack.com/resources/hostinger-black-friday-2026),
  [VPSBenchmarks](https://www.vpsbenchmarks.com/hosters/hostinger).
* Hetzner: [price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/),
  [Helsinki price reduction](https://www.hetzner.com/pressroom/price-reduction-cloud-servers-in-helsinki-now-15-percent-cheaper/),
  [Black Friday baseline](https://findstack.com/resources/black-friday-vps-deals-2026),
  [2026 pricing summary](https://www.bitdoze.com/hetzner-cloud-cost-optimized-plans/).
* DigitalOcean: [Droplet pricing](https://www.digitalocean.com/pricing/droplets),
  [backups pricing](https://docs.digitalocean.com/products/backups/details/pricing/),
  [South Africa tax](https://docs.digitalocean.com/products/billing/taxes/zaf).
* South African VAT on foreign electronic services:
  [SARS FAQ](https://www.sars.gov.za/lapd-vat-g16-vat-faqs-supplies-of-electronic-services).
* Johannesburg VPS listings (Vultr, local hosts): [valebyte](https://valebyte.com/en/vps/south-africa/?provider=vultr).
