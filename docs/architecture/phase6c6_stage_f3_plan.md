# Phase 6C.6 Stage F3 — Private Environment and Recovery: implementation plan

**Status:** **accepted in principle by the owner (22 Nov 2026), subject to the
refinements in §S**; a Lean MVP cost assessment is in §T and the **current
quality-first provider assessment is in §U; the **owner's preferred hosting
configuration (Hostinger KVM 2 monthly in Germany + Supabase Pro from the start,
DigitalOcean as fallback) is in §V** — a preference, not purchase or implementation
authorisation, which take precedence over earlier sections where they differ.
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
loads the Screener data; originally estimated at ~300–500 MB RSS per worker — **measured
≈ 94 MB per warm worker on 22 Nov 2026, see §T.1**), the 5-minute
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
* **PostgreSQL:** nightly dump, encrypted and uploaded as above; level 3. **Scope
  superseded by §S.8:** the off-host dump must include the `auth` schema and roles
  through Supabase's supported CLI dump, plus an encrypted export of the project
  configuration; an `app`-schema-only `pg_dump` is partial recovery.
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
* **Methods, Auth scope and ordering:** see §S.8 (what each restore method preserves,
  supported fallback for the beta feature, operator sign-in test) and §S.9 (hold
  recorded and verified in the restored target before any scheduler or
  provider-capable process connects). Where they differ, S.8/S.9 apply.
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
PostgreSQL per S.4); **F3-R1 (procedure part):** the hold recorded and verified **in the restored target**
before any scheduler or provider-capable process connected (S.9 ordering evidence);
manual provider commands shown to fail closed on the F3 host; **Auth recovery:** an
existing operator signed in after M1 and after M3 (S.8), otherwise the method is
partial recovery and an F3 blocker.

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

### S.8 Supabase Auth recovery: scope, methods and the acceptance test

Supabase stores Auth **users and identities** (including password hashes) in the
`auth` schema of the project database, but Auth **settings** (site URL, redirect
allow-list, signup switch, password policy, email templates/SMTP), **API keys and
JWT signing configuration**, the **project ref/URL**, Storage objects and Edge
Functions live **outside** the database [V-doc]. Diski 9 links its accounts to
Supabase identities by subject (`auth.users.id`) in `app.users`; operator sign-in
needs (i) the `auth` identity with its password hash, (ii) the matching `app.users`
and role rows, and (iii) a project whose Auth settings and keys match the app's
environment (`DISKI9_SUPABASE_AUTH_URL`, publishable key, JWT issuer). Server-side
Diski 9 sessions do not survive a move to a different project (new signing keys), so
everyone signs in again; that is acceptable.

**Backup scope (replaces the PostgreSQL bullet of §I):**

| Item | How it is backed up | Notes |
|---|---|---|
| Project database: `app` **and** `auth` schemas, roles | Supabase's supported CLI path (`supabase db dump` for roles, schema and data, as in Supabase's backup-and-restore guide), encrypted off-host nightly | a raw `pg_dump --no-owner` of the `app` schema alone does **not** recreate identities; raw `pg_dump` of the whole database is discouraged by Supabase (internal objects, permission errors) [V-doc]; the CLI dump needs the database owner password → held in `~diski9/.pgpass` (0600) on the VM, or the dump is run from the owner's machine (decision **F3-D15**) |
| Project configuration | exported after every change with the Management API (Auth config: site URL, redirect URLs, signup disabled, password policy, email templates/SMTP; SSL enforcement; network restrictions) to a JSON file kept **encrypted off-host**; secrets in it redacted and held in the password manager | not in any database backup |
| Keys and secrets | password manager (owner): database owner password, publishable key, app secret/encryption keys | new project ⇒ new publishable key and URL; app environment updated at cutover |
| Supabase-native daily backups | automatic (Pro, 7 days) [V-doc] | contain the whole database incl. `auth`; restore in place keeps project settings |

**Recovery methods and what each actually restores:**

| Method | Status | Restores | Operator sign-in after recovery | Classification |
|---|---|---|---|---|
| **M1** Supabase daily backup restored **in place** (same project) | supported (Pro) [V-doc] | whole database as of the backup, incl. `auth`; project ref, URL, keys and Auth settings unchanged (they are not part of the restore) | expected without config changes; **must be demonstrated** | full recovery if demonstrated; destructive to newer data and the project is unavailable while it runs |
| **M2** Supabase "restore to a new project" | **beta** [V-doc] | whole database (binary) incl. `auth`, encryption root key; **not** Auth settings, API keys, Realtime/Storage/Edge Functions; new ref and URL | only after re-applying the exported Auth configuration and switching the app to the new URL/key | full recovery if demonstrated; **never the only path** (beta) |
| **M3** off-host CLI dump (roles + schema + data incl. `auth`) restored into a **new** project with `psql`, then the exported configuration re-applied | supported CLI path [V-doc] | database incl. `auth.users` and hashes; configuration from the export; new keys/URL | yes, after config re-apply and app switch; **must be demonstrated** | **the supported fallback for M2**; full recovery if demonstrated |
| **M4** off-host dump restored into a **local** PostgreSQL | local drill | application data only (no Supabase Auth service) | no | **partial recovery** — data verification and local timing only |
| app-schema-only `pg_dump`/`pg_restore` into a Supabase project | not used | `app` data without identities | no (identities missing) | **partial recovery**; gap would be a blocker |

**Hosted recovery acceptance test (Auth):** for the method(s) drilled, an **existing**
operator account (created before the backup) signs in with its password on the web
app and authenticates the operator CLI (S-07 path, e.g. `ops provider-resume` in the
rehearsal) against the recovered target. If a method cannot achieve this, it is
recorded as **partial recovery** and the gap stays an **F3 blocker**.

**Drill plan (affordable):** a dedicated temporary **drill project** (Micro, billed
hourly, deleted afterwards) seeded from the F3 schema with the owner/operator accounts:
(1) wait for one Supabase daily backup, change data, run **M1** in place on the drill
project and test sign-in; (2) run **M3** from the encrypted off-host CLI dump into a
second temporary project, re-apply the exported configuration, switch a staging copy
of the app environment and test sign-in; (3) optionally run **M2** for comparison.
The primary F3 project is never restored in place during a drill. Estimated cost: a
few dollars of hourly compute [A].

### S.9 Provider-hold sequencing: the restored target first

The hold lives in the database the scheduler will use. **The original database's hold
state is irrelevant**: what matters is that the restored **target** carries an
`ops.restore_postgres` record, newer than any `ops.provider_resume`, **before any
scheduler or provider-capable process connects to it**.

Ordered procedure (runbook [`../operations_hosting.md`](../operations_hosting.md) §8):

1. **Freeze the host:** create the pause file; `systemctl disable --now
   diski9-tick.timer diski9-backup.timer` and `systemctl stop diski9-tick.service
   diski9-web`; `systemctl is-active` reports `inactive` for all; confirm no
   `diski9` process remains (`pgrep -u diski9`). The environment file still points at
   the old database and is **not** edited yet.
2. **Restore the target** (M1, M2 or M3). For M1 the target is the same project:
   the units are already stopped, so the rule is unchanged.
3. **Operator-only connection to the target:** write the target's connection settings
   to a temporary file `/etc/diski9/restore-target.env` (0600, never on a command line)
   containing the target `DISKI9_APP_DATABASE_URL` plus `DISKI9_JOBS_ENABLED=off`,
   `DISKI9_JOBS_PROVIDER_CALLS=off`, `DISKI9_JOBS_PREPARE_REFRESH=off`; run commands as
   the `diski9` user in a subshell that loads only that file. No unit, timer or
   provider-capable command is run in this step (the F3 host has no API-Football key
   and blocked provider egress in any case).
4. **Record the restore in the target:** `diski9 app-db check` (head `app_0007`), then
   `diski9 backup record --kind postgres-restore --file <dump, or a restore-note file
   naming the Supabase backup timestamp for M1/M2>`.
5. **Verify the hold in the target**, still through the temporary file: `diski9 ops
   status` shows `PROVIDER HOLD`; `diski9 ops check` reports
   `provider_hold_after_restore`; the evidence records the restore record's job-run id
   and time. **If the hold is not visible, stop**: no cutover.
6. **Reconcile against the target** (`competition verify`, `ops check --deep`, round
   inspection, ledger review) through the same temporary file.
7. **Cutover:** only now edit `/etc/diski9/diski9.env` to the target (and, for a new
   project, the Supabase Auth URL and publishable key), keeping provider calls and
   refresh off; start `diski9-web`; check `/readyz` and the operator sign-in (S.8); then
   remove the pause file and re-enable the timers. Delete the temporary file.
8. **Evidence of ordering:** in the target, the `ops.restore_postgres` job-run id is
   lower than the id of every `scheduler.tick` row written after the restore, and no
   `scheduler.provider` row exists after it; both queries are part of the drill report.

The hosted drill (S.4, S.8) performs and records exactly this sequence. Manual
provider commands remain outside the hold; their bypass must be addressed before F4
(F3-D11, F3-R1).

## T. Lean MVP hosting and cost-optimisation assessment (owner request, 22 Nov 2026)

Assessment only: nothing approved, purchased, provisioned or created. **No earlier
decision is superseded**: every change below is a proposal for owner approval (§T.8).
Labels as in §S ([V-doc], [A], [T]); [M] = measured in this repository.

### T.1 Minimum practical server size (measured)

| Measurement [M] (22 Nov 2026, Gunicorn 26.2.0, real 36.8 MB football store copy, guest mode) | Result |
|---|---|
| Gunicorn master | 26 MB RSS |
| Each worker after serving the Screener page (data loaded) | **≈ 94 MB RSS** |
| Master + 2 warm workers | **≈ 214 MB** |
| First (cold) page / warm page / `/readyz` | 0.58 s / < 0.01 s / 1 ms |
| Competition database size (local synthetic datasets) | ≈ 20 MB (100 users), ≈ 128 MB (1,000), ≈ 948 MB (10,000) |

This corrects the earlier planning estimate of "~300–500 MB per worker" (§A), which
was conservative. Allowing for accounts mode, the 5-minute `jobs tick` (a short-lived
process), nightly backups (`backup store`, CLI dump, `age`), Caddy, Tailscale and the
OS:

* **Minimum:** 1 vCPU, **2 GB RAM**, 20 GB disk (operator-only F3).
* **Recommended:** 2 vCPU, 2–4 GB RAM, 40 GB disk (headroom for 3–4 workers and an
  invited Beta).
* Disk budget: OS ≈ 5 GB, virtualenv ≈ 1–2 GB, store 37 MB, 14 local backups
  ≈ 0.6 GB, logs ≈ 1 GB.

8 GB (Hostinger KVM 2) is far more than Diski 9 needs at MVP scale.

### T.2 Monthly-billed VPS candidates (Frankfurt/Germany)

| Server | vCPU / RAM / disk | Price (ex VAT) | Availability | IPv4 / IPv6 | Backups |
|---|---|---|---|---|---|
| **Hetzner CX23** (cost-optimised) | 2 / 4 GB / 40 GB | **€5.49 + €0.50 IPv4 ≈ €5.99** (June 2026 list) | **orders reported blocked** at every check since Sept 2026 (capacity notice since 26 Jun) — check the console on the day | IPv4 paid, **IPv6 /64 included** | +20 % (daily, 7 kept) ≈ €1.10 |
| Hetzner CX33 | 4 / 8 GB / 80 GB | €8.49 + IPv4 | same block as CX23 | as above | +20 % |
| Hetzner CPX22 (regular) | 2 / 4 GB | ≈ €19.49 | unclear | as above | +20 % |
| **DigitalOcean Basic** 1 vCPU / 2 GB | 1 / 2 GB / 50 GB | ≈ $12 (FRA1) | available | IPv4 + IPv6 | weekly +20 % |
| DigitalOcean Basic 2 vCPU / 2 GB | 2 / 2 GB / 60 GB | ≈ $18 (FRA1, listing) | available | IPv4 + IPv6 | weekly +20 % |
| **Vultr** 1 vCPU / 2 GB (Frankfurt) | 1 / 2 GB | ≈ $12–14 (listing) | available | IPv4 + IPv6 | ≈ +20 % |
| Hostinger KVM 1 / KVM 2, **1-month term** | 1/4 GB, 2/8 GB | ≈ $19.49 / $24.49 (third-party listing; first month discounted) | available; Frankfurt | one IP; IPv6 unconfirmed | weekly included |

Prices are listings and documentation as of November 2026 and must be re-checked at
order time. All candidates are in or next to Frankfurt (< 10 ms to AWS
`eu-central-1`); South African latency is the same for all (§B).

### T.3 Supabase Free against Diski 9's requirements

| Requirement | Supabase Free | Pro | Consequence for F3 |
|---|---|---|---|
| Database size | 500 MB [V-doc] | 8 GB included | ✅ ample for operator-only and a small Beta (≈ 20–130 MB measured) |
| Connections | small instance; limits not confirmed for Free [A] | Micro and above documented | ✅ expected: app pool ≈ 2 × 10 + scheduler; verify [T] |
| Auth (GoTrue), password hashing, sessions, JWT/issuer validation | same service | same | ✅ the app's session management and JWT validation are unchanged |
| Leaked-password protection (HaveIBeenPwned) | **not available** (Pro feature, to re-confirm) [A] | available | ⚠ minimum-length/complexity rules still apply; HIBP check missing |
| Project pausing | **pauses after ~7 days without sufficient database activity** [V-doc]; restore from the dashboard | never paused | ⚠ the 5-minute tick keeps it active in practice, but a host outage > 7 days pauses the project (manual restore); no guarantee |
| Automatic backups | **none** [V-doc] | daily, 7 days | ❌ M1 (in-place restore) impossible |
| Restore to a new project | **not available** (paid plans) [V-doc] | beta | ❌ M2 impossible |
| Off-host CLI dump incl. `auth` (M3) | ✅ supported path; Supabase itself recommends regular CLI exports on Free [V-doc] | ✅ | ✅ M3 and the Auth-identity sign-in test can be demonstrated on Free (2 active projects allow primary + drill project) |
| Direct PostgreSQL (IPv6) / session pooler (IPv4) | ✅ both | ✅ | ✅ Stage D advisory-lock tests can run unchanged |
| IPv4 add-on for the direct endpoint | **not available** | ≈ $4/month | ⚠ if the VPS lacks IPv6 **and** the pooler fails the lock tests, Free has no fallback (Hetzner, DigitalOcean and Vultr all provide IPv6) |
| SSL enforcement, `verify-full` with the project CA | ✅ | ✅ | ✅ |
| PITR | no | add-on | n/a for F3 (gate before F5) |
| Hosted acceptance suite (§L) | expected to pass **unchanged** except any test relying on leaked-password protection [T] | ✅ | run unchanged; any Free-only failure is reported, not waived |
| Operator identity recovery | via M3 only | M1, M2, M3 | see T.4 |

### T.4 F3 acceptance requirements that cannot be met on Supabase Free

1. **S.8 M1:** demonstrating an in-place restore from a Supabase daily backup with
   operator sign-in. There are no backups on Free.
2. **S.8 M2 comparison** (optional): restore-to-new-project needs a paid plan.
3. **§I baseline:** Supabase-native daily backups do not exist (the off-host CLI dump
   becomes the only database backup, i.e. a single recovery path).
4. **F3-D5 fallback:** the IPv4 add-on is unavailable.
5. **No-pause guarantee:** pausing after inactivity is a residual availability risk
   (not an acceptance item today, but relevant to M-series monitoring).
6. **Leaked-password protection** (if it is required by the §D Auth configuration):
   unavailable.

Everything else in Q-1–Q-15, S.3 (locking, TLS), S.4/S.9 (provider hold in the target
first), F3-R2 (encrypted off-host backups, retrieval, off-host restore drill via M3)
and the Auth sign-in test via M3 **can** be met on Free. F3-R1 and F3-R2 remain
acceptance gates in every option.

**Not proposed:** silently dropping M1 from S.8. If the owner wants F3 accepted on Free
throughout, that is a separate decision (F3-D18) that accepts a single recovery path
(off-host dump only) for the operator-only stage, with the consequences listed in T.8.

### T.5 Options and costs

Assumptions: 15 % VAT on every line [A] (verified only for DigitalOcean); off-host
encrypted storage ≈ $2/month [A]; Tailscale Personal $0 (if eligible); domain $0
(`ts.net`); monitoring $0 (on-host); €1 ≈ $1.16. Hetzner CX23 total ≈ €7.09 ≈ $8.23
(incl. IPv4 and backups); DigitalOcean 1 vCPU / 2 GB $12 + 20 % backups = $14.40.

| Option | Monthly (incl. VAT) | Upfront | 3 months | 6 months | 12 months | 24 months |
|---|---|---|---|---|---|---|
| **A — Lean:** Hetzner CX23 + Supabase Free | ≈ $11.76 | none | ≈ $35 | ≈ $71 | ≈ $141 | ≈ $282 |
| A (if CX23 unavailable): DigitalOcean 2 GB + Supabase Free | ≈ $18.86 | none | ≈ $57 | ≈ $113 | ≈ $226 | ≈ $453 |
| **B — Balanced:** Hetzner CX23 + Supabase Pro | ≈ $40.51 | none | ≈ $122 | ≈ $243 | ≈ $486 | ≈ $972 |
| B: DigitalOcean 2 GB + Supabase Pro | ≈ $47.61 | none | ≈ $143 | ≈ $286 | ≈ $571 | ≈ $1,143 |
| **C — Hostinger KVM 2 (24-month promo) + Supabase Pro** | ≈ $31.05 after the upfront | **≈ $242.60** | ≈ $336 | ≈ $429 | ≈ $615 | ≈ $988 |
| **A→B staged (recommended):** Hetzner CX23, Supabase Free for the first 2 months of F3 build and soak, then Pro | $11.76 → $40.51 | none | ≈ $64 | ≈ $186 | ≈ $429 | ≈ $915 |
| A→B staged with DigitalOcean 2 GB | $18.86 → $47.61 | none | ≈ $85 | ≈ $228 | ≈ $514 | ≈ $1,085 |

Observations: option C becomes cheaper than B only after ≈ 15 months (against the
DigitalOcean B) or ≈ 26 months (against the Hetzner B), and carries
a sunk ≈ $243 that is lost if Diski 9 changes direction (refund only within 30 days),
for 8 GB RAM that the measurements show is not needed. A and the staged option keep
every cost cancellable monthly. Optional add-ons (if needed): Supabase IPv4 add-on
+$4.60/month incl. VAT (Pro only); Supabase Small compute +$5.75.

### T.6 Can Supabase Free be used for F3, and when is Pro needed?

* **F3 build, hardening, lock tests, 72-hour soak, private-access and backup set-up:**
  yes, on Free, with the off-host CLI dump running from day one and the 5-minute tick
  keeping the project active.
* **F3 hosted recovery drills and F3 operational acceptance:** upgrade to **Pro**
  (monthly; a drill project in a Pro organisation is billed hourly) so M1 can be
  demonstrated and daily backups exist alongside the off-host dump — unless the owner
  approves F3-D18 (accept M3-only for the operator-only stage).
* **Before F4 (live provider calls):** Pro **required** (no pausing, daily backups,
  IPv4 fallback available, support), in addition to the F3-R1 resolution and SF-14.
* **Before F5 (participants):** Pro required, plus the tighter-RPO decision (PITR or
  more frequent dumps), leaked-password protection on, ML-01 and D-36.

### T.7 Recommendation and upgrade path

**Lowest-cost technically sound setup: the staged A→B option.**

1. A **monthly-billed** 2 vCPU / 4 GB server in Germany: **Hetzner CX23 if it can be
   ordered** on the day (≈ €5.99/month incl. IPv4, IPv6 included); otherwise
   **DigitalOcean or Vultr 1–2 vCPU / 2 GB in Frankfurt** (≈ $12–18/month). No
   prepayment.
2. **Supabase Free** in Frankfurt for the F3 build and soak, with the off-host CLI dump
   (incl. `auth`), Tailscale private access, TLS `verify-full`, the provider hold and
   all S.3/S.8/S.9 rules exactly as planned.
3. **Upgrade to Supabase Pro** before the hosted recovery drills and F3 acceptance (no
   relaxation of S.8), and keep Pro for F4/F5.
4. **Growth path:** resize the server in place (Hetzner rescale / DigitalOcean resize)
   to 4–8 GB when worker count or users require it; Supabase Pro → Small compute when
   connection or CPU metrics require; PITR or more frequent dumps decided before F5;
   the football store migrates to PostgreSQL before any public deployment (D-39a); a
   domain and public TLS only at public launch.

Hostinger C stays the reference case: worth reconsidering only if the owner wants a
2-year commitment for a larger server; it is **not** the lowest-cost sound option for
an MVP with a small number of users.

### T.8 Owner decisions proposed (all open; none supersedes an earlier decision)

| ID | Decision | Recommendation | Risk / consequence |
|---|---|---|---|
| F3-D16 | Supabase plan per phase | Free for F3 build and soak; Pro before the hosted recovery drills and F3 acceptance; Pro mandatory before F4 and F5 | Free: pausing risk, single recovery path until the upgrade, no IPv4 fallback, no leaked-password check |
| F3-D17 | Hosting commitment model | monthly-billed 2 vCPU / 4 GB (min 2 GB) server in Germany; no 24-month prepayment at MVP stage (replaces the Hostinger-first ranking in F3-D1 **only if approved**) | costs more than C only after ≈ 15 months (DigitalOcean) or ≈ 26 months (Hetzner); full flexibility |
| F3-D18 | Accept M3-only Auth recovery for F3 operator-only acceptance on Free (would amend S.8) | **not recommended**; if approved, M1 must be demonstrated before F4 | F3 accepted with one recovery path (off-host dump); no Supabase-native backup during F3 |
| F3-D19 | Leaked-password protection requirement | required from F5 (participants); optional in F3 (owner/operator only, strong unique passwords and MFA on the Supabase dashboard) | if required in F3, Pro is needed from the start |

F3-D1 (provider), F3-D3 (ceilings) and F3-D14 (Hostinger prepayment) remain open; if
F3-D17 is approved, the proposed ceilings shrink to ≈ $15/month (Free phase) and
≈ $50/month (Pro phase), with no prepayment.

## U. Hosting quality and final provider selection (owner request, 22 Nov 2026)

Owner direction: quality first — reliability, performance, security, operational
simplicity and scalability outweigh savings of ≈ $10–15/month; **Supabase Pro from the
start of F3**; **monthly VPS billing**; Hostinger reconsidered on its merits. Research
and planning only: nothing purchased, subscribed, provisioned or deployed. §T stays as
the cost record; where §U differs, §U is the current proposal (still subject to owner
approval).

### U.1 Scope: VPS products only

Only full-root **KVM virtual servers** qualify: the architecture needs root, systemd
units and timers, Caddy, Tailscale/WireGuard, a local filesystem for SQLite WAL and a
long-running Gunicorn process. **Hostinger's website-hosting plans (including the
"Unlimited" plan at $18.99/month seen in the owner's checkout) are shared web hosting,
not VPS: they cannot run this architecture and are excluded.** Hostinger's VPS line is
the "KVM 1/2/4/8" family.

### U.2 Quality comparison (2 vCPU / 4–8 GB class, Frankfurt/Germany)

| Criterion | **DigitalOcean** Basic 2 vCPU / 4 GB (FRA1) | **Hostinger** KVM 2 (2 vCPU / 8 GB / 100 GB NVMe), KVM 1 (1 vCPU / 4 GB / 50 GB) — Frankfurt | **Vultr** Cloud Compute 2 vCPU / 4 GB (Frankfurt) | **Hetzner** (CX23/CX33 cost-optimised; CPX22 regular) |
|---|---|---|---|---|
| Virtualisation / root | KVM, full root [V-doc] | KVM on all VPS plans, full root [V-doc] | KVM, full root | KVM, full root |
| Published uptime commitment | **99.99 % per Droplet, credited** (5-minute intervals, maintenance excluded) [V-doc] | **none found** in Hostinger's documents; third-party reviews cite "99.9 %" and observed ≈ 99.97 % [A] | **100 % host-node and network** availability with tiered credits (infrastructure only) [V-doc] | cloud SLA with credits when monthly availability falls below 99.9 % [V-doc] |
| Performance evidence | mature, consistent shared vCPU (regular Intel/AMD; "Premium" tiers available) | VPSBenchmarks: KVM 2 **"A" for performance stability**, AMD EPYC 9355P in the Oct 2026 trial; overall scores vary between trials (≈ 35–63) [V-doc, third party] | consistency score 62 (VPSBenchmarks) [third party] | best price/performance in Europe; capacity-constrained in 2026 |
| Billing | monthly cap, per-second billing; no commitment | **1-, 12- or 24-month terms, paid upfront; no hourly billing** [V-doc] | hourly, monthly cap | hourly, monthly cap |
| Backups | weekly +20 %, daily +30 %; snapshots per GB | **weekly backups included**; manual snapshot included; daily backups paid | automatic backups ≈ +20 %; snapshots | daily (7 kept) +20 %; snapshots per GB |
| Firewall | Cloud Firewall (free) + `ufw` | hPanel VPS firewall + `ufw` | firewall groups + `ufw` | Cloud Firewall (free) + `ufw` |
| IPv6 | yes [V-doc] | **unconfirmed**; one dedicated IP per VPS [V-doc] | yes | yes (/64) |
| Resize / scale | in-place resize to larger plans; block storage; load balancers; managed services in the same region | upgrade to a larger KVM plan; location fixed after setup | in-place resize; block storage | rescale; volumes |
| Console / recovery access | web console, recovery ISO | browser terminal / VNC in hPanel | web console | web console, rescue system |
| API / automation | mature API, Terraform | Hostinger API available (newer) | API, Terraform | API, Terraform |
| Support | ticket support included; paid tiers | 24/7 chat | ticket support | ticket support |
| Availability now | available | available | available | **CX orders reported blocked** since Sept 2026; CPX availability unclear |
| Fit with Diski 9 | ✅ no changes | ✅ no changes (IPv6 check pending; pooler fallback works without it) | ✅ no changes | ✅ no changes (if orderable) |

Measured need (§T.1): ≈ 214 MB for Gunicorn master + 2 workers. **4 GB with 2 vCPU** is
the recommended class (headroom for 3–4 workers, the tick, backups, Tailscale and an
invited Beta); 8 GB is comfortable but not needed; **1 vCPU (Hostinger KVM 1) works for
operator-only F3** but leaves little CPU headroom when a tick, a backup/encryption job
and page requests coincide.

### U.3 Monthly prices (verify at checkout)

| Item | Price | Status |
|---|---|---|
| DigitalOcean Basic 2 vCPU / 4 GB | $24.00 + weekly backups $4.80 | [V-doc] |
| Hostinger KVM 2, **1-month term** | ≈ **$24.49** (first month sometimes discounted, e.g. $13.99) | **[A] third-party listing; Hostinger's own one-month checkout price not confirmed**; weekly backups included |
| Hostinger KVM 1, 1-month term | ≈ $19.49 (first month e.g. $9.99) | **[A]** as above |
| Hostinger renewal (24-month promo terms) | KVM 1 ≈ $11.99, KVM 2 ≈ $14.99/month equivalent, billed for the renewal term | [V-owner] for KVM 2; KVM 1 [A] |
| Vultr Cloud Compute 2 vCPU / 4 GB | ≈ $20.00 + backups ≈ $4.00 | [A] listing |
| Hetzner CPX22 (2 vCPU / 4 GB) / CX23 | ≈ €19.49 / €5.49 + €0.50 IPv4, backups +20 % | [V-doc] prices; availability [A] |
| Supabase Pro (Micro covered by credit) | $25.00 | [V-doc] |
| Off-host encrypted storage | ≈ $2.00 | [A] |
| Tailscale Personal / domain / monitoring | $0 | [V-doc] / ts.net / on-host |
| Optional: Supabase IPv4 add-on; Small compute | +$4.00; +$5.00 | [V-doc]; only if needed |
| Taxes | 15 % South African VAT assumed on every line | verified for DigitalOcean only |

**Total monthly cost (Supabase Pro + storage + server with backups), incl. assumed VAT:**

| Configuration | ex VAT | incl. 15 % VAT |
|---|---|---|
| DigitalOcean 2 vCPU / 4 GB + weekly backups | $55.80 | **≈ $64.17** |
| Hostinger KVM 2, 1-month term (backups included) | ≈ $51.49 | **≈ $59.21** |
| Hostinger KVM 1, 1-month term | ≈ $46.49 | ≈ $53.46 |
| Vultr 2 vCPU / 4 GB + backups | ≈ $51.00 | ≈ $58.65 |
| Hetzner CPX22 + IPv4 + backups | ≈ $54.71 | ≈ $62.92 |
| Hetzner CX23 (if orderable) | ≈ $35.23 | ≈ $40.51 |

All quality-class options fall within ≈ $53–64/month; the spread between the top
candidates is ≈ $5/month, so the choice can rest on quality and operations.

### U.4 Final ranked recommendation (for F3-D1)

1. **DigitalOcean Basic 2 vCPU / 4 GB, Frankfurt (FRA1), monthly, weekly backups on —
   ≈ $64/month all-in.** Strongest *published* reliability commitment (99.99 % per
   Droplet with credits), per-second billing with no commitment, in-place resize and a
   broad managed-service ecosystem for scaling, documented IPv6, free cloud firewall,
   mature API and console. No architecture change. Upgrade path: resize to 4 vCPU /
   8 GB (≈ $48) in place; add block storage; later a second Droplet/load balancer for the
   public phase.
2. **Hostinger KVM 2, Frankfurt, 1-month term — ≈ $59/month all-in, conditional.**
   Good measured stability (VPSBenchmarks "A"), AMD EPYC, 8 GB RAM and weekly backups
   included, at a similar price. It ranks second, not first, because (a) the one-month
   price is not confirmed from Hostinger itself, (b) no credit-backed uptime commitment
   was found, (c) IPv6 is unconfirmed, (d) terms are paid upfront per period with no
   hourly billing, and (e) the location is fixed after setup. **It becomes a co-equal
   first choice if pre-sales confirm**: a one-month KVM 2 price ≤ $25 before VAT and its
   renewal terms; IPv6 on the Frankfurt VPS; the written uptime/compensation terms; and
   the refund terms for a South African checkout. KVM 1 is acceptable only for
   operator-only F3 (1 vCPU).
3. **Vultr Cloud Compute 2 vCPU / 4 GB, Frankfurt — ≈ $59/month all-in.** Solid,
   hourly-billed, infrastructure SLA; fewer managed services than DigitalOcean.
4. **Hetzner** — excellent price/performance and a published SLA, but new cloud orders
   have been blocked since September 2026; only if an account can create the server.

Not recommended now: Hostinger's 24-month promotional prepayment (owner preference for
monthly billing; see F3-D14).

### U.5 Effect of Supabase Pro from the start

* Daily backups exist from day one, so **M1, M2 and M3 can all be drilled** (S.8) and
  F3-D18 (M3-only acceptance on Free) is **withdrawn**.
* No inactivity pausing; the IPv4 add-on is available as the F3-D5 fallback.
* Leaked-password protection can be **enabled from the start** (recommended, F3-D19).
* §T's staged Free→Pro option is no longer proposed.

All F3 safeguards remain unchanged: Tailscale/WireGuard private access with no public
endpoint, TLS `verify-full`, session-mode or direct connections only (transaction
pooling prohibited, lock-test failure a hard stop), the provider hold recorded and
verified in the restored target before any scheduler or provider-capable process
connects (S.9), the Auth sign-in recovery test (S.8), F3-R1 and F3-R2 as acceptance
gates, D-39a, human-only publication, provider calls, refresh and Official off, D-29b
unchanged, no live API-Football calls.

### U.6 Updated proposed decisions (all open)

| ID | Proposal |
|---|---|
| F3-D1 | DigitalOcean 2 vCPU / 4 GB FRA1 (rank 1); Hostinger KVM 2 Frankfurt 1-month term co-equal if the four pre-sales checks pass; Vultr; Hetzner if orderable |
| F3-D3 | ceiling ≤ **$75/month all-in incl. VAT**, alert at $65; **no prepayment** |
| F3-D14 | decline the Hostinger 24-month promotion (monthly billing preferred) |
| F3-D16 | **Supabase Pro from the start of F3** (owner preference) |
| F3-D17 | monthly-billed VPS, 2 vCPU / 4 GB minimum class for F3 and the invited Beta |
| F3-D18 | withdrawn (Pro from the start) |
| F3-D19 | leaked-password protection **on from the start** |

## V. Owner hosting direction (22 Nov 2026)

**Owner-preferred F3 configuration (a preference, not authorisation to purchase,
provision or begin F3): Hostinger KVM 2 VPS on monthly billing, in Germany, with
Supabase Pro from the beginning.** DigitalOcean Basic 2 vCPU / 4 GB in Frankfurt is
retained as the fallback if any material technical or operational requirement cannot
be met. This supersedes the §U.4 ranking as the current proposal; §U remains the
evidence record.

### V.1 Checkout terms verified by the owner [V-owner]

| Item | Verified |
|---|---|
| Product | **KVM 2 VPS** (2 vCPU, 8 GB RAM, 100 GB NVMe) — not shared website hosting |
| Billing | **one-month term** |
| Price | **$13.99 first month; renewal $24.49/month** |
| Location | Germany available at the same price |
| Taxes | displayed as **$0** at checkout (to be confirmed on the final invoice) |
| Daily automatic backups | optional **$6/month**, not selected (weekly backups included per Hostinger documentation [V-doc]) |

### V.2 Remaining checks before any purchase

| # | Check | Current evidence | How to confirm (without buying) | If it fails |
|---|---|---|---|---|
| 1 | **IPv6** on the Germany KVM 2 VPS | not stated in Hostinger documentation; one dedicated IP per VPS [V-doc] | pre-sales chat (written answer) | not a blocker by itself: the app uses the Supabase **session pooler (IPv4)**; the scheduler uses the pooler if it passes the hosted lock tests, otherwise the **Supabase IPv4 add-on** (≈ $4/month) for the direct endpoint. If neither path passes the lock tests → **DigitalOcean fallback** (hard stop rule unchanged) |
| 2 | **Frankfurt** as the provisioned data centre | Hostinger's German VPS data centre is in Frankfurt am Main [V-doc]; the location list shown at setup is authoritative and cannot be changed later | pre-sales chat; confirm "Germany" = Frankfurt; choose it at setup | another German/EU site with higher latency to Supabase `eu-central-1` → re-measure (§B targets); if targets are missed → DigitalOcean FRA1 |
| 3a | **Uptime terms** | no published credit-backed uptime commitment found for VPS [A] | ask for the written VPS uptime/compensation terms | accepted as a known difference from DigitalOcean (99.99 % per Droplet) if the owner agrees; recorded as a residual risk, monitored through F3's 72-hour soak and `ops status` |
| 3b | **Backup terms** | weekly automatic backups and a manual snapshot included; daily backups $6/month optional [V-owner/V-doc] | confirm retention and restore procedure in writing | the verified recovery path does **not** depend on Hostinger backups: Diski 9's own encrypted off-host backups (§I, §S.8) remain mandatory; Hostinger backups are a convenience only, so daily backups are optional |
| 3c | **Refund terms** | help centre: KVM VPS refundable within 30 days of purchase (not crypto payments; 180-day cool-down); some regional legal pages differ [V-doc] | confirm the terms for a South African checkout in writing | with monthly billing the exposure is one month ($13.99 first month) |

### V.3 Monthly cost (proposed ceiling $75 all-in, subject to approval)

| Line | Month 1 | From month 2 |
|---|---|---|
| Hostinger KVM 2 (one-month term, tax displayed $0) | $13.99 | $24.49 |
| Supabase Pro (Micro covered by the included credit) | $25.00 | $25.00 |
| Off-host encrypted storage | ≈ $2.00 | ≈ $2.00 |
| Tailscale / domain / monitoring | $0 | $0 |
| **Total ex VAT** | **≈ $40.99** | **≈ $51.49** |
| With 15 % VAT assumed on Supabase and storage only [A] | ≈ $45.04 | ≈ $55.54 |
| Optional: Hostinger daily backups | +$6.00 | +$6.00 |
| Optional: Supabase IPv4 add-on (only if needed, check 1) | +$4.00 | +$4.00 |
| **Worst case with both optional items and assumed VAT** | – | **≈ $66.14** |

All cases stay within the proposed **$75/month** ceiling; the DigitalOcean fallback is
≈ $64/month incl. assumed VAT. No prepayment; the Hostinger 24-month promotion is
declined.

### V.4 Unchanged

Technical fit as assessed in §U (full-root KVM: Linux, Gunicorn, systemd, Caddy, SQLite
WAL, scheduler, Supabase connectivity, Tailscale/WireGuard, encrypted off-host backups
— no architecture change). All F3 safeguards stay exactly as planned: private access
with no public endpoint (S.2), TLS `verify-full` and session/direct connections only
with transaction pooling prohibited and lock-test failure a hard stop (S.3), the Auth
recovery scope and operator sign-in test (S.8), the provider hold recorded and verified
in the restored target before any scheduler or provider-capable process connects (S.9),
F3-R1 and F3-R2 as acceptance gates, D-39a, human-only publication, provider calls,
refresh and Official off, D-29b unchanged, no live API-Football calls, no participant
accounts.

## R. Decision record: owner decisions required (none approved yet)

Every row is a **proposal**. "Status" is *open* until the owner records a decision; a
technical recommendation is not an owner decision.

| ID | Decision for the owner | Technical recommendation | Verified facts it rests on | Unverified assumptions | Status |
|---|---|---|---|---|---|
| F3-D1 | Hosting provider and plan | **§V (owner preference):** Hostinger KVM 2, one-month billing, Germany/Frankfurt, subject to the §V.2 checks (IPv6, Frankfurt, uptime/backup/refund terms); fallback DigitalOcean Basic 2 vCPU/4 GB FRA1 | KVM 2 specs and promo/renewal prices [V-owner]; Hostinger Frankfurt DC, 30-day VPS refund [V-doc] | IPv6; VAT; refund terms for a South African checkout; renewal billing | open |
| F3-D2 | Region | Frankfurt for Supabase and the VM | no Supabase African region; Hostinger/DigitalOcean Frankfurt [V-doc] | ZA page timings meet targets [T] | open |
| F3-D3 | Spending ceilings | **§V.3 (owner proposal):** ≤ $75/month all-in, subject to final approval; alert at $65; no prepayment | Supabase Pro $25 incl. $10 credit [V-doc] | VAT, FX fees, storage cost | open (proposal only) |
| F3-D4 | Create the hosted Supabase project (owner action) | Pro, Micro, Frankfurt, SSL enforcement on, signups off after bootstrap | Pro/Micro pricing [V-doc] | – | open |
| F3-D5 | Database connection mode | app: session pooler; scheduler: direct over IPv6 if available, else session pooler; IPv4 add-on ($4/month) only if lock tests fail on the pooler | session pooler is IPv4; direct is IPv6 unless add-on [V-doc] | VPS IPv6 [T]; pooler keeps advisory locks [T] | open |
| F3-D6 | Private-access method | Tailscale (no inbound ports, `ts.net` HTTPS); fallback self-hosted WireGuard | Tailscale Personal free up to 6 users, non-commercial [V-doc] | eligibility under "non-commercial" for Diski 9 | open |
| F3-D7 | Domain | none in F3 (`ts.net` name); owner domain only for the later public architecture | – | – | open |
| F3-D8 | Off-host storage provider and key custody | EU object storage at a different provider, versioning/object lock; `age` private key held by the owner off the VM | – | storage price ≈ $3/month [A] | open |
| F3-D9 | Hosted PostgreSQL recovery drill | temporary drill project(s), deleted afterwards: M1 in place on the drill project and M3 from the off-host CLI dump with configuration re-applied (M2 optional, beta); local M4 reported separately as partial | hourly compute billing, restore-to-new-project on paid plans (beta) [V-doc] | drill cost < $5 [A] | open |
| F3-D10 | Automatic hold activation (before F4) | option (c): cutover check + rolled-back-database detection | F2 hold behaviour (accepted) | – | open |
| F3-D11 | Manual provider-command coverage (before F4) | extend the hold to the shared API-Football client factory | inventory in K | – | open |
| F3-D12 | External uptime monitor | not used in F3 (no public endpoint); on-host timer + tailnet check | – | – | open |
| F3-D13 | Accounts in F3 | owner plus at most one operator; no participants | – | – | open |
| F3-D15 | Where the off-host CLI dump (incl. `auth`) runs and who holds the database owner password | on the VM with the owner password in `~diski9/.pgpass` (0600) and encrypted upload, or from the owner's machine; recommendation: VM, with the credential scoped and rotated after F3 | Supabase CLI backup path includes `auth.users` [V-doc] | – | open |
| F3-D16 | Supabase plan (§T, §U, §V) | **Supabase Pro from the beginning of F3** (owner preference); Pro mandatory for F4/F5 | Free: no backups, pausing, no IPv4 add-on [V-doc] | Free connection limits; leaked-password feature tier | open |
| F3-D17 | Hosting commitment model (§T, §U, §V) | **monthly VPS billing only** (owner preference); 2 vCPU class (Hostinger KVM 2: 2 vCPU / 8 GB) | measured ≈ 94 MB per worker [M]; Hetzner CX23 price [V-doc] | CX23 orderable on the day | open |
| F3-D18 | Accept M3-only Auth recovery for F3 on Free (amends S.8) | **withdrawn** (Supabase Pro from the start) | Free has no daily backups [V-doc] | – | open |
| F3-D19 | Leaked-password protection requirement | **on from the start of F3** (available on Pro) |
| F3-D20 | Hostinger daily automatic backups ($6/month) | optional; not required, because Diski 9's encrypted off-host backups are the verified recovery path | – | – | open |
| F3-D21 | Accept the absence of a published credit-backed VPS uptime commitment (if pre-sales confirms none) | owner's call; residual risk monitored during F3; DigitalOcean fallback otherwise | DigitalOcean 99.99 % per Droplet [V-doc] | Hostinger terms [A] | open | – | Free-tier availability | open |
| F3-D14 | Buy the Hostinger promotion before F3 implementation is authorised | **declined per owner preference** (monthly billing only; no 24-month prepayment) | promo ends 14 Dec 2026; term starts at purchase [V-owner/V-doc] | non-promo 24-month price [A] | open |

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
* Auth-recovery sources (§S.8): [Supabase backup and restore using the CLI](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore),
  [migrating Auth users between projects](https://supabase.com/docs/guides/troubleshooting/migrating-auth-users-between-projects),
  [restore to a new project (what is not copied)](https://supabase.com/docs/guides/platform/clone-project),
  [database backups (Storage objects excluded; in-place restore replaces data)](https://supabase.com/docs/guides/platform/backups).
* Lean MVP sources (§T): [Supabase pricing and Free limits](https://supabase.com/pricing),
  [Supabase project pausing](https://supabase.com/docs/guides/platform/free-project-pausing),
  [Hetzner price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/),
  [Hetzner billing FAQ (backups 20 %, IPv4)](https://docs.hetzner.com/cloud/billing/faq/),
  [Hetzner CX availability 2026](https://www.bitdoze.com/hetzner-cloud-cost-optimized-plans/),
  [Frankfurt VPS listings](https://valebyte.com/en/vps/germany/?page=3),
  [Hostinger VPS pricing (terms)](https://www.hostinger.com/pricing/vps-hosting),
  [VPSBenchmarks Hostinger](https://www.vpsbenchmarks.com/hosters/hostinger).
* Hosting-quality sources (§U): [DigitalOcean Droplet SLA](https://docs.digitalocean.com/products/droplets/details/sla),
  [Vultr SLA](https://www.vultr.com/company/sla/),
  [Hetzner cloud SLA](https://docs.hetzner.com/general/company-and-policy/slas-cloud/),
  [Hostinger VPS (KVM)](https://www.hostinger.com/vps),
  [Hostinger VPS pricing and terms](https://www.hostinger.com/pricing/vps-hosting),
  [VPSBenchmarks: Hostinger KVM 2](https://www.vpsbenchmarks.com/hosters/hostinger/plans/1055),
  [VPSBenchmarks Hostinger trial Oct 2026](https://www.vpsbenchmarks.com/trials/hostinger_performance_trial_10Oct2026),
  [VPSBenchmarks Hostinger vs Vultr](https://www.vpsbenchmarks.com/compare/hostinger_vs_vultr),
  [third-party Hostinger renewal summary](https://www.techtransit.org/hostinger-vps-which-plan-to-buy/).
