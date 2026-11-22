# Phase 6C.6 Stage F3 — Private Environment and Recovery: implementation plan

**Status:** **accepted in principle by the owner (22 Nov 2026), subject to the
refinements in §S**, which take precedence over earlier sections where they differ.
Planning authorised 22 Nov 2026. **F3 implementation, provisioning and purchasing are
not authorised.** Nothing in this plan has been provisioned,
purchased, created or deployed: no hosting account, VM, domain, hosted Supabase
project, off-host storage, live API-Football call or participant account. Every
provisioning and spending step below waits for the owner decisions in §R.

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

## C. Monthly cost estimate and proposed budget ceiling (no commitment; reconciled in §S.5)

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

## E. PostgreSQL connection modes and Stage D locking (refined in §S.3)

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

## F. VM hardening, firewall, TLS and private access (private access superseded by §S.2)

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

## J. Restore verification, RPO and RTO measurement (closes F3-R2 part 2; hosted evidence per §S.4)

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

## S. Planning-review refinements (owner review, 22 Nov 2026)

The owner accepted this plan **in principle** subject to the refinements below
(documentation and research only; no implementation, provisioning, account creation
or purchase). Where §S differs from A–R, §S applies. Labels used: **[V-owner]**
verified by the owner; **[V-doc]** stated in the provider's own documentation (still
to be re-confirmed at checkout); **[A]** assumption, not verified; **[T]** to be
tested on the host in F3.

### S.1 Hostinger KVM 2: verified terms and pre-purchase checks

| Item | Status | Value / finding |
|---|---|---|
| Plan | [V-owner] | KVM 2: 2 vCPU, 8 GB RAM, 100 GB NVMe |
| Promotional price | [V-owner] | $8.79/month equivalent; **$210.96 upfront for 24 months before taxes** |
| Renewal | [V-owner] | $14.99/month equivalent (renewal term length and whether it is billed upfront: **[A] to confirm**) |
| Promotion end | [V-owner] | advertised 14 Dec 2026 |
| German location | [V-doc] | Hostinger operates a **Frankfurt am Main** data centre for VPS (announced 2024); the list offered at setup is authoritative and the location cannot be changed after setup |
| IPv6 | **unverified** | each VPS has one dedicated IP and no add-on addresses; Hostinger documentation does not state IPv6 for the Frankfurt VPS. **Do not assume IPv6**: the design below works without it |
| Refund | [V-doc], with conflicts | help centre: KVM VPS purchases refundable within **30 days of the purchase date** (not for crypto payments; 180-day cool-down between VPS refunds); some regional legal pages describe different terms. **Confirm the terms that apply to a South African checkout** |
| Taxes | **unverified** | 15 % South African VAT on foreign electronic services is assumed [A]; Hostinger's practice for South African buyers is not confirmed |
| Card / currency charges | [A] | a ZAR card paying USD may add ≈ 2–3 % foreign-transaction fees |
| Billing start | [V-doc] | the term starts at purchase, not at setup |

**Pre-purchase checks** (by pre-sales chat and the checkout page, without buying): (1)
Frankfurt offered for KVM 2 at checkout; (2) IPv6 on that VPS (yes/no); (3) the exact
checkout total for a South African billing address, including VAT; (4) the refund terms
for that checkout; (5) renewal term and whether renewal is billed upfront. A "no" on (1)
or (4), or a total above the proposed $250 ceiling, moves the recommendation to
DigitalOcean.

### S.2 Private access: allowlist versus authenticated private network

| Option | Residential IP changes | Inbound exposure | TLS | Notes |
|---|---|---|---|---|
| (a) Provider firewall + Caddy IP allowlist (original F) | **must be edited every time the owner's IP changes** (common on South African fibre/LTE) | 443 (and 80 for certificates) open to the internet, filtered by IP | public ACME (HTTP-01 needs port 80) | simple; error-prone with dynamic IPs; a mis-edit exposes the app |
| (b) Self-hosted WireGuard | no edits | one UDP port (silent to unauthenticated packets) | private name; certificate via DNS-01 or an internal CA | no third party; key distribution and peer management by hand |
| **(c) Tailscale (WireGuard-based mesh)** | **no edits** | **no inbound ports at all** (outbound NAT traversal) | `tailscale cert` issues Let's Encrypt certificates for `<host>.<tailnet>.ts.net` | free Personal plan (up to 6 users, non-commercial use) [V-doc]; identity-provider MFA; ACLs; device approval; Tailscale SSH optional |
| (d) Cloudflare Tunnel + Access | no edits | none | Cloudflare edge certificate | Cloudflare terminates TLS and sees traffic; adds a dependency on Cloudflare identity |

**Recommendation (technical): (c) Tailscale**, with (b) self-hosted WireGuard as the
fallback if the owner prefers no third-party control plane or if Diski 9's use is not
"non-commercial" under the free plan (owner decision **F3-D6**; a paid Tailscale plan is
the alternative). Design:

* **Owner access from South Africa:** the owner's laptop/phone joins the tailnet; the
  VM is reachable only as `diski9-f3.<tailnet>.ts.net` (latency is the normal
  ~160–180 ms to Frankfurt; Tailscale uses a direct WireGuard path where possible).
* **Web:** Caddy binds to the **Tailscale interface only** and serves the `ts.net` name
  with the certificate obtained through Tailscale (Caddy's Tailscale certificate
  integration or `tailscale cert` with renewal by a timer). No public DNS record and no
  public web port. Certificate issuance publishes the machine and tailnet name in
  public Certificate Transparency logs [V-doc]: a name becomes known, but access still
  needs tailnet membership.
* **SSH:** OpenSSH listens only on the Tailscale interface (`ListenAddress`), keys only,
  no root, no passwords; or Tailscale SSH under ACLs. Public SSH closed.
* **Supabase Auth redirects:** Site URL and the redirect allow-list are set to
  `https://diski9-f3.<tailnet>.ts.net` only. Email links point to Supabase, which
  redirects the browser to that URL: this works because the operator's browser is on the
  tailnet. Supabase never needs to reach the VM (no webhooks); the VM calls Supabase
  outbound. `__Host-` cookies work because the site is HTTPS.
* **DNS / domain:** none needed (the `ts.net` name is provided). An owner domain is only
  needed later for the public architecture (S.5).
* **Firewall:** Hostinger hPanel firewall (or `ufw` if the panel firewall is limited
  [T]) **denies all inbound** except Tailscale's own needs (none inbound required); egress
  allowed to Supabase (5432/6543 blocked for the scheduler by code anyway), Tailscale,
  object storage, OS updates and PyPI; **egress to `v3.football.api-sports.io` blocked**
  (F3 has no provider calls; see K).
* **Credential hardening:** Tailscale admin account with MFA through the identity
  provider; device approval on; key expiry on (VM key renewed deliberately); ACL: owner
  devices → VM ports 443 and 22 only; operator (if any) → 443 only; no exit nodes, no
  subnet routing.
* **Recovery access if the VPN fails:** Hostinger's browser console / VNC from hPanel
  (protected by Hostinger account MFA) [T]; break-glass procedure: temporarily open SSH
  (22) in the hPanel firewall to the owner's **current** IP only, fix, close again,
  record it in the incident log. Tailscale control-plane outages do not drop existing
  connections; re-authentication waits for recovery.
* **Public endpoints:** **none are necessary in F3.** No public web, SSH, health or
  webhook endpoint. External uptime monitoring (F3-D12) is therefore replaced by an
  on-host timer plus a tailnet check from the owner's device.

### S.3 Supabase and PostgreSQL connectivity, TLS and locking

| Use | Endpoint | Mode | Requirement |
|---|---|---|---|
| Web app (`DISKI9_APP_DATABASE_URL`) | Supavisor **session pooler** `aws-…-eu-central-1.pooler.supabase.com:5432` | session, IPv4 | works without VPS IPv6 [V-doc] |
| Scheduler lock (`DISKI9_JOBS_DATABASE_URL`) | **direct** `db.<ref>.supabase.co:5432` if the VPS has working IPv6 [T]; otherwise the **session pooler**; otherwise the Supabase IPv4 add-on (≈ $4/month [V-doc]) for the direct endpoint | direct or session | Stage D session-scoped advisory lock; **transaction pooler (6543) prohibited** (refused by `locking.check_lock_url`) |
| `pg_dump` / `pg_restore` | direct (IPv6 or IPv4 add-on) preferred; session pooler acceptable [T] | session | client version ≥ server major version (install the matching `postgresql-client` from the PostgreSQL apt repository if Ubuntu's is older [T]) |

**Connection security (all connections):** `sslmode=verify-full` with
`sslrootcert=/etc/diski9/supabase-ca.crt` (the project CA downloaded from the
dashboard's SSL configuration; whether the pooler also presents a publicly trusted
certificate is reported inconsistently, so pin the Supabase CA and test both endpoints
[T]); **Supabase SSL enforcement turned on** so non-TLS connections are refused;
dedicated least-privilege application role (no superuser, no `service_role`);
separate read-only backup role for `pg_dump`; credentials only in
`/etc/diski9/diski9.env` and `~diski9/.pgpass` (0600) — never on command lines; existing
statement/lock timeouts kept; `connect_timeout=10` and TCP keepalives set for the
scheduler connection.

**Hosted locking tests (hard stop on any failure):** `tools/ops/scheduler_lock_probe.py`
against the chosen scheduler endpoint: two concurrent ticks (one runs, one `busy`);
holder termination and lock-loss detection; R1–R6 behaviours; a real `jobs tick` with
provider calls off; repeated over ≥ 72 hours (Q-6). If the session pooler does not keep
the advisory lock for the whole tick, or any probe result differs from the local
Stage D evidence, **F3 stops** and the owner decides (IPv4 add-on for the direct
endpoint, or a different host with IPv6). No Stage D code change is made in F3.

### S.4 Hosted recovery evidence (F3-R1 and F3-R2 remain acceptance gates)

* **Local versus hosted:** a restore into a local disposable PostgreSQL (as in the F2
  drill) proves the dump is restorable and measures a **local drill time only**; it is
  never reported as hosted Supabase recovery time.
* **Hosted recovery drill (recommended, affordable):** restore into a **temporary second
  Supabase project** in the same organisation — preferably via Supabase "restore to a new
  project" from a daily backup (paid plans; feature status beta [V-doc]), and also via
  `pg_restore` of the encrypted **off-host** dump retrieved on another machine (F3-R2).
  The temporary project's compute is billed hourly (Micro ≈ $0.0134/hour [V-doc]: a
  one-day drill costs well under $1 plus any disk/egress) and is deleted after the
  drill.
* **Realistic cutover rehearsal (on the temporary project):** pause file and stop units →
  record the restore with `backup record --kind postgres-restore` **and confirm the
  provider hold is active** (`ops status` shows `PROVIDER HOLD`; `ops check` shows
  `provider_hold_after_restore`) **before** the environment file is switched → switch
  `DISKI9_APP_DATABASE_URL` / `DISKI9_JOBS_DATABASE_URL` (and, for a whole-project
  restore, the Supabase Auth URL and publishable key) → restart units → `/readyz`,
  sign in with the existing operator account (proves Auth identities survived the
  restore together with `app.users`) → reconciliation checklist (rounds, publication,
  entries, settlement, ledger) → `ops provider-resume` rehearsed by the authenticated
  operator (provider calls stay **off** in F3 regardless) → switch back to the primary
  project and delete the temporary one.
* **Measured and reported separately:** hosted RTO (from "decision to restore" to
  "operator signed in and reconciliation complete"), retrieval/decrypt time, local drill
  time, achieved RPO. Targets as in J (hosted ≤ 2 h; store ≤ 30 min), all labelled real
  measurements on the F3 host.
* **Auth caveat:** restoring only the `app` schema into a different project would break
  the link to Supabase Auth identities; the hosted drill therefore restores the whole
  project database (or uses "restore to a new project"), and the evidence must show an
  existing account signing in afterwards.
* No API-Football key is present and no live provider call is made at any point.

### S.5 Budget reconciliation

Totals below include **[A] 15 % VAT** on every line (not verified for Hostinger or
Supabase; DigitalOcean documents South African VAT [V-doc]) and exclude card FX fees.
Common lines: Supabase Pro $25/month with Micro covered by the included credit [V-doc]
($28.75 with VAT); off-host encrypted storage ≈ $3/month [A]; private access $0
(Tailscale Personal, if eligible) [V-doc]; domain $0 (the `ts.net` name); optional Supabase
IPv4 add-on $4/month only if needed [V-doc]; optional external monitoring $0 (not used:
no public endpoint).

| Path | Upfront | 12 months | 24 months | 36 months | Early termination |
|---|---|---|---|---|---|
| **Hostinger KVM 2** | **$210.96 [V-owner] → ≈ $242.60 with VAT [A]** | ≈ $623.60 (incl. 12 prepaid months unused: ≈ $121.30 forfeited if stopped at 12) | ≈ **$1,004.60** | ≈ $1,592.46 (renewal 12 × $14.99 + VAT ≈ $206.86) | after the 30-day refund window, unused prepaid months are forfeited (stopping at month 6 forfeits ≈ $182 incl. VAT) |
| DigitalOcean Frankfurt ($24 + weekly backups) | none | ≈ $778.44 | ≈ $1,556.88 | ≈ $2,335.32 | none (billed while running) |
| Hetzner CX33 (+IPv4, backups; availability-limited) | none | ≈ $553.50 | ≈ $1,107.00 | ≈ $1,660.50 | none |
| Add if needed: Supabase IPv4 add-on | – | +$55.20 | +$110.40 | +$165.60 | – |

Monthly average on the Hostinger path over 24 months ≈ **$41.86** (within the proposed
$60 average / $75 cap).

**Where proposed limits could be exceeded:**
* Hostinger checkout: $242.60 incl. assumed VAT is under the proposed $250, but **≈ 3 %
  card FX fees would bring it to ≈ $249.9**, and any checkout add-on (daily backups,
  extra IP, panel licence) **would exceed $250**.
* Hostinger **renewal**: if renewal is billed upfront for another 24 months at
  $14.99/month, the charge would be **$359.76 (≈ $413.72 with VAT), above the $250
  prepayment proposal** — auto-renew should be off until a renewal decision is made.
* DigitalOcean path: within $75/month, but its 24-month total (≈ $1,557) exceeds the
  proposed ≈ $1,200 programme cap (as noted in A.2).
* PITR (≈ $100/month, requires Small compute [V-doc]) would exceed every F3 ceiling; it is
  not part of F3.

**Eventual public deployment (estimate, not planned or approved):** football store moved
to PostgreSQL (mandatory, D-39a); Supabase Small → Medium compute (+$5 to +$50/month);
PITR or more frequent dumps decided before F5 (PITR ≈ $100+/month); the VM (KVM 2's 8 GB
is adequate for a small Beta; redundancy would double it); an owner domain ≈ $15/year;
custom SMTP ≈ $0–15/month; CDN/WAF free tier; monitoring $0–10/month; API-Football $16
(existing). **Lean public ≈ $60–100/month without PITR; ≈ $160–220/month with 7-day
PITR** (before VAT).

These ceilings remain **proposals**: the $75 monthly and $250 Hostinger figures are not
approved spending limits.

### S.6 Prepayment decision (F3-D14): recommendation

* Buying in the sale secures $210.96 for 24 months versus an assumed ≈ $359.76 for a
  24-month term at the renewal-equivalent rate [A]: a saving of ≈ $149 before VAT.
  Each month the VPS sits idle before F3 implementation costs ≈ $8.79. The prepayment is
  therefore cheaper unless the VPS would stay idle for more than ≈ 17 months.
* But the **30-day refund window starts at purchase**: if F3 implementation is not
  authorised within that window, the technical checks that can only be done on the host
  (IPv6, firewall/console features, Supabase connectivity and locking) cannot be done
  while a refund is still possible.
* **Recommendation:** (1) complete the S.1 pre-purchase checks now (pre-sales chat,
  checkout page) without buying; (2) **buy before 14 Dec 2026 only if** the checks pass
  **and** the owner intends to authorise F3 implementation (at least the infrastructure
  checks) within ≈ 30 days of purchase; (3) otherwise **wait** and use DigitalOcean
  monthly when F3 is authorised. Buying a VPS **does not authorise** deploying the
  application, creating the Supabase project or any F3 implementation step; auto-renew
  stays off.

### S.7 Gates

**F3 implementation gates (before any provisioning):** owner approval of F3
implementation; F3-D1–D4, D6, D8 (and D14 if buying in the sale) approved in writing;
S.1 checks passed (or DigitalOcean chosen); billing alerts set; no API-Football key on
the host and provider egress blocked.

**F3 operational-acceptance gates:** Q-1–Q-15; S.3 hosted locking tests passed (hard
stop otherwise); **F3-R2:** encrypted off-host backups of both databases for ≥ 3 nights,
retrieval on another machine, and genuine off-host restore drills (store and hosted
PostgreSQL per S.4); **F3-R1 (procedure part):** the hold confirmed active before the
rehearsed database cutover; manual provider commands shown to fail closed on the F3 host.

**F4 live-provider gates:** F3 accepted; **F3-R1 fully resolved** — a fail-closed hosted
recovery procedure, explicit confirmation that the hold is active before database
cutover, and an assessment (and owner decision F3-D10/D11) of manual provider-command
bypasses; SF-14 shared-key schedule analysis; separate owner authorisation for provider
calls and caps; API-Football key provisioning approved.

**F5 participant and recovery gates:** tighter PostgreSQL RPO decided (the 24-hour RPO
stays restricted to operator-only testing); ML-01 fixed; D-36 deletion workflow and
retention statement approved (including EU data residency of Supabase); participant
access approved; public-architecture decisions (domain, public TLS, football-store
PostgreSQL migration per D-39a).

## R. Decision record: owner decisions required (none approved yet)

Every row is a **proposal**. "Status" is *open* until the owner records a decision; a
technical recommendation is not an owner decision.

| ID | Decision for the owner | Technical recommendation | Verified facts it rests on | Unverified assumptions | Status |
|---|---|---|---|---|---|
| F3-D1 | Hosting provider and plan | Hostinger KVM 2 (24-month promo, **Frankfurt**) if S.1 checks pass; else DigitalOcean Basic 2 vCPU/4 GB Frankfurt; Hetzner CX33 only if an account can create servers | KVM 2 specs and promo/renewal prices [V-owner]; Hostinger Frankfurt DC, 30-day VPS refund [V-doc] | IPv6; VAT; refund terms for a South African checkout; renewal billing | open |
| F3-D2 | Region | Frankfurt for Supabase and the VM | no Supabase African region; Hostinger/DigitalOcean Frankfurt [V-doc] | ZA page timings meet targets [T] | open |
| F3-D3 | Spending ceilings | proposals: ≤ $60/month average, $75 cap; one-off prepayment ≤ $250 incl. VAT and fees; 24-month programme ≈ $1,200 (≈ $1,600 on DigitalOcean) | Supabase Pro $25 incl. $10 credit [V-doc] | VAT, FX fees, storage cost | open (proposal only) |
| F3-D4 | Create the hosted Supabase project (owner action) | Pro, Micro, Frankfurt, SSL enforcement on, signups off after bootstrap | Pro/Micro pricing [V-doc] | – | open |
| F3-D5 | Database connection mode | app: session pooler; scheduler: direct over IPv6 if available, else session pooler; IPv4 add-on ($4/month) only if lock tests fail on the pooler | session pooler is IPv4; direct is IPv6 unless add-on [V-doc] | VPS IPv6 [T]; pooler keeps advisory locks [T] | open |
| F3-D6 | Private-access method | Tailscale (no inbound ports, `ts.net` HTTPS); fallback self-hosted WireGuard | Tailscale Personal free up to 6 users, non-commercial [V-doc] | eligibility under "non-commercial" for Diski 9 | open |
| F3-D7 | Domain | none in F3 (`ts.net` name); owner domain only for the later public architecture | – | – | open |
| F3-D8 | Off-host storage provider and key custody | EU object storage at a different provider, versioning/object lock; `age` private key held by the owner off the VM | – | storage price ≈ $3/month [A] | open |
| F3-D9 | Hosted PostgreSQL recovery drill | temporary second Supabase project (restore-to-new-project and off-host `pg_restore`), deleted afterwards; local disposable drill reported separately | hourly compute billing, restore-to-new-project on paid plans (beta) [V-doc] | drill cost < $5 [A] | open |
| F3-D10 | Automatic hold activation (before F4) | option (c): cutover check + rolled-back-database detection | F2 hold behaviour (accepted) | – | open |
| F3-D11 | Manual provider-command coverage (before F4) | extend the hold to the shared API-Football client factory | inventory in K | – | open |
| F3-D12 | External uptime monitor | not used in F3 (no public endpoint); on-host timer + tailnet check | – | – | open |
| F3-D13 | Accounts in F3 | owner plus at most one operator; no participants | – | – | open |
| F3-D14 | Buy the Hostinger promotion before F3 implementation is authorised | only if S.1 checks pass **and** F3 implementation will be authorised within ≈ 30 days of purchase; otherwise wait (S.6); auto-renew off | promo ends 14 Dec 2026; term starts at purchase [V-owner/V-doc] | non-promo 24-month price [A] | open |

Nothing is purchased, reserved or created until the relevant decisions are approved in
writing, and F3 implementation needs its own separate authorisation.

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
* Refinement sources (§S): [Hostinger Frankfurt data centre](https://www.hostinger.com/blog/frankfurt-data-center/),
  [Hostinger refund policy](https://www.hostinger.com/support/9088216-what-is-hostinger-refund-policy/),
  [Hostinger VPS IP address](https://www.hostinger.com/support/5139756-how-to-find-vps-ip/),
  [Supabase IPv4/IPv6 compatibility](https://supabase.com/docs/guides/troubleshooting/supabase--your-network-ipv4-and-ipv6-compatibility-cHe3BP),
  [Supabase IPv4 add-on](https://supabase.com/docs/guides/platform/ipv4-address),
  [Supabase SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement),
  [Supabase backups and PITR](https://supabase.com/docs/guides/platform/backups),
  [Supabase restore to a new project](https://supabase.com/docs/guides/platform/clone-project),
  [Tailscale pricing](https://tailscale.com/pricing/),
  [Tailscale HTTPS certificates](https://tailscale.com/kb/1153/enabling-https/).
