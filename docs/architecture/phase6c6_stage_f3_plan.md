# Phase 6C.6 Stage F3 — Private Environment and Recovery: implementation plan

**Status:** **accepted in principle by the owner (22 Nov 2026), subject to the
refinements in §S**; **the Düsseldorf VPS location amendment (F3-D1a/F3-D2a,
conditionally approved for Stage F3; final acceptance on IT-1 PASS) is in §Z**; a Lean MVP cost assessment is in §T and the **current
quality-first provider assessment is in §U; the **owner's preferred hosting
configuration (Hostinger KVM 2 monthly in Germany + Supabase Pro from the start,
DigitalOcean as fallback) is in §V**, the **Hostinger pre-sales findings are in §W**, and the **final owner decisions and the
implementation-authorisation package (ordered plan, owner actions, private access,
off-host backups) are in §X**, with the **final technical clarifications (private HTTPS,
Object Lock negative tests, backup least privilege) in §Y**; §Y and §X take precedence over earlier sections where they
differ. Provider selection closed by the owner on 22 Nov 2026.
Planning authorised 22 Nov 2026. **F3 implementation authorised by the owner on 22 Nov 2026**
(Stage F3 only; not F4, F5, public deployment, live API-Football calls, participant
onboarding or production release). Checkpoint 0 (owner setup sequence, scripts,
checklists): [`../operations_f3_owner_setup.md`](../operations_f3_owner_setup.md). All
purchases are made by the owner personally. Nothing in this plan has been provisioned,
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

*Superseded: the owner chose self-hosted WireGuard with no Tailscale (F3-D6) and no
domain (F3-D7); the origin is `https://10.88.0.1` with the IP-SAN certificate (§X.2,
§Y.1). Tailscale and `ts.net` mentions in §S–§V are kept only as the record of the
options compared.*

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

## W. Hostinger pre-sales verification and provider selection (22 Nov 2026)

Owner direction: **proceed with Hostinger KVM 2 as the preferred F3 VPS provider, with
Supabase Pro from the beginning**; DigitalOcean Frankfurt retained as the fallback if
Hostinger fails a material technical acceptance test. Recorded as owner preferences;
**not** authorisation to purchase, provision, subscribe or begin F3.

### W.1 Pre-sales findings: source and strength of evidence

Labels: **[C] contractual / checkout-verified** (seen by the owner in the actual
checkout or in Hostinger's published policy); **[AI] statement by Hostinger's AI
support agent** (useful, but not a contractual commitment); **[open]** still unknown.

| Topic | Finding | Strength | Consequence |
|---|---|---|---|
| Product and billing | KVM 2 VPS (not shared hosting), one-month billing, **$13.99 first month, $24.49/month renewal**, Germany available at the same price, taxes displayed **$0**, optional daily backups **$6/month** | **[C]** owner's checkout | basis of the cost estimate (§V.3); taxes to be confirmed on the first invoice |
| Location | German VPS data centre is in **Frankfurt** — *contradicted by provisioning: the VPS was provisioned in Düsseldorf (§Z)* | **[AI]**, consistent with Hostinger's published Frankfurt data-centre announcement [V-doc] | select Frankfurt at setup (cannot be changed later); measure latency to Supabase `eu-central-1` on day one (§B) |
| IPv6 | **outbound IPv6** available on KVM 2 when configured in the OS/network settings | **[AI]** | verify on the host on day one (`ip -6 addr`, `ping -6`, TCP to the Supabase direct endpoint); if absent, session pooler or the Supabase IPv4 add-on (§V.2); lock-test failure remains a hard stop |
| Uptime | VPS plans "include an uptime guarantee"; **percentage and compensation terms not provided**; checkout advertises an uptime guarantee | **[AI]** + checkout wording; **no verified credit-backed SLA** | owner accepts as a documented F3 residual risk (F3-D21); monitoring and recovery requirements unchanged |
| Backups | included backup frequency/retention **not confirmed** | **[open]** | irrelevant to acceptance: Diski 9's independent encrypted off-host backups (§I, §S.8) are mandatory; no Hostinger backup is relied on (F3-D20) |
| Refunds | South African customers qualify for the **30-day KVM VPS money-back guarantee**, subject to policy conditions and payment-method restrictions | **[AI]**, consistent with Hostinger's published refund policy (30 days, not crypto) [V-doc] | exposure limited to one month on monthly billing; pay by card (not crypto) to keep eligibility |

### W.2 What must be approved before purchasing or provisioning

*Superseded by §X.1 (22 Nov 2026); kept as the record of the earlier position.*

**Step 0 — F3 implementation authorisation** (separate owner instruction; nothing below
happens without it).

**Before any purchase or account creation (spending):**
* F3-D1 Hostinger KVM 2, monthly, Germany/Frankfurt — *owner-preferred; confirm as a
  formal approval*;
* F3-D3 ceiling ≤ $75/month all-in — *proposed; needs final approval*;
* F3-D14, F3-D16, F3-D17, F3-D20, F3-D21 — *owner-preferred; confirm as formal
  approvals*;
* F3-D2 region (Frankfurt for Supabase and the VPS) — *open*;
* F3-D4 owner creates the Supabase Pro project (Micro, Frankfurt, SSL enforcement on,
  signups off after bootstrap) — *open*.

**Before the host is built (day one of F3):**
* F3-D6 private access (Tailscale; WireGuard fallback; confirm Tailscale "non-commercial"
  eligibility or choose a paid plan/WireGuard) — *open*;
* F3-D7 no domain in F3 (origin `https://10.88.0.1` over WireGuard, §Y.1) — *open*;
* F3-D13 accounts: owner plus at most one operator — *open*;
* F3-D19 leaked-password protection on from the start — *open*;
* F3-D5 connection-mode decision rule (app: session pooler; scheduler: direct over IPv6,
  else pooler, else IPv4 add-on; failure = hard stop) — *open*.

**Before the first nightly backup:**
* F3-D8 off-host storage provider and `age` key custody — *open*;
* F3-D15 where the CLI dump (incl. `auth`) runs and who holds the owner password —
  *open*.

**Before the hosted recovery drills:** F3-D9 drill plan (M1 + M3; M2 optional) — *open*.

**Before F4 (not needed for F3 purchase):** F3-D10 automatic hold activation; F3-D11
manual provider-command coverage; SF-14 analysis. F3-D12 (no external monitor) can be
confirmed any time before acceptance. F3-D18 is withdrawn.

### W.3 Unchanged

DigitalOcean Basic 2 vCPU / 4 GB Frankfurt is the fallback if Hostinger fails a
material technical acceptance test (IPv6/pooler lock tests, Frankfurt latency targets,
private access, backups, failure injection, performance). All F3 safeguards remain as
planned (S.2, S.3, S.8, S.9, F3-R1, F3-R2, D-39a, human-only publication, provider
calls/refresh/Official off, D-29b unchanged, no live API-Football calls, no
participant accounts).

## X. Final owner decisions and implementation-authorisation package (22 Nov 2026)

Owner direction (22 Nov 2026): **the provider-selection phase is closed.** This section
records the owner's decisions and gives the concrete, ordered implementation plan.
It is **not** F3 implementation authorisation. Nothing has been purchased, subscribed,
created, provisioned or deployed. Every decision marked *approved* below takes effect
only when the owner gives the separate F3 implementation authorisation (Step 0). No
money is spent before that.

### X.1 Decisions: what can be recorded now and what still needs a check or an owner action

**(a) Recorded now as owner-approved** (effective with Step 0):

| ID | Decision approved by the owner |
|---|---|
| F3-D1 | Hostinger KVM 2, monthly billing, Germany/Frankfurt is the selected VPS. **DigitalOcean Basic 2 vCPU / 4 GB FRA1 is the fallback** if a material hosted acceptance test fails (X.4) |
| F3-D2 | Frankfurt for both the VPS and Supabase (`eu-central-1`) |
| F3-D3 | **Maximum recurring infrastructure budget: $75/month all-in, alert at $65.** No long-term hosting prepayment |
| F3-D4 | Supabase Pro project, smallest appropriate compute (Micro), Frankfurt, created by the owner (X.3 step O-4) |
| F3-D5 | The existing connection-mode rule is kept. App: session pooler. Scheduler: direct over IPv6, else session pooler, else the IPv4 add-on. Transaction pooling is prohibited. `verify-full` TLS. **Any hosted advisory-lock test failure is a hard stop** (§S.3) |
| F3-D7 | No public domain during F3 |
| F3-D9 | Hosted M1 and M3 recovery drills are retained, with target-database-first provider-hold verification (§S.9) and the operator sign-in acceptance test (§S.8). M2 is optional and never the only path |
| F3-D13 | Accounts are limited to the owner and at most one additional operator. No participants |
| F3-D14 | The 24-month Hostinger promotion is declined |
| F3-D16 | Supabase Pro from the beginning of F3 |
| F3-D17 | Monthly VPS billing only |
| F3-D19 | Leaked-password protection on from the start |
| F3-D20 | The optional $6/month Hostinger daily backups are declined for now. Independent encrypted off-host backups remain mandatory |
| F3-D21 | The lack of a verified credit-backed Hostinger uptime SLA is accepted as a documented F3 residual risk. Monitoring and recovery requirements are not relaxed |

All previously accepted Stage F safeguards are unchanged (X.6).

*(b) and (c) below were settled by the owner on 22 Nov 2026: see §Y.*

**(b) Approved as a rule; one owner statement still needed:**
* **F3-D6 private access.** The owner approved Tailscale **only if** the intended use
  complies with its licence and fits the budget, otherwise WireGuard. X.2 applies the
  rule. The outcome depends on whether Diski 9's F3 use is non-commercial. Only the
  owner can state that.

**(c) Recommended in this package; owner acceptance needed before the first backup:**
* **F3-D8** off-host storage provider, encryption-key custody and credentials (X.3).
* **F3-D15** where the full Supabase dump (including `auth`) runs, and custody of the
  database owner password (X.3.4).
* **F3-D22 (new): execution model.** Claude works in a cloud container that cannot reach
  the VPS, and credentials must never pass through the chat. The recommended model is
  this: Claude writes the scripts and runbooks in the repository; the owner runs them on
  the host and returns outputs that contain no secrets. Alternatively, the owner attaches
  their own computer to a session through Remote Control, approved each time. No cloud
  session ever holds Diski 9 production credentials.
* **F3-D12** no external uptime monitor in F3 (on-host timer plus a check from the
  owner's device). This can be confirmed any time before acceptance.

**(d) Checks at implementation time** (a check that fails triggers the stated action;
none of them can be settled on paper):

| Check | When | If it fails |
|---|---|---|
| IT-1 VPS really in Frankfurt (hPanel data centre; RTT to Supabase `eu-central-1` p95 < 10 ms) — *location clause replaced by F3-D1a/F3-D2a (conditionally approved, §Z); the latency requirement RTT p95 < 10 ms is unchanged* | day 1 | cancel within the refund window, then DigitalOcean FRA1 |
| IT-2 Outbound IPv6 works; direct database endpoint reachable | day 1 | session pooler, else IPv4 add-on (≈ $4) |
| IT-3 Hosted advisory-lock tests on the chosen scheduler endpoint | before the soak | **hard stop**; owner decides (IPv4 add-on or DigitalOcean) |
| IT-4 `verify-full` TLS with the pinned Supabase CA on both endpoints; SSL enforcement refuses plaintext | build | stop until fixed |
| IT-5 Page timings from South Africa (§B targets) | after install | static-asset caching first; never move the app away from the database |
| IT-6 Private access: WireGuard UDP reachable from the owner's fibre and mobile networks; no other public port open (scan from the owner's network) | build | change port, or use Tailscale under the licence rule |
| IT-7 Off-host storage: region is EU; the upload key **cannot** read, list or delete (recorded negative tests); Object Lock active | before the first backup | fix the key or bucket before any backup counts |
| IT-8 Taxes on the first Hostinger invoice and VAT on Supabase/storage; spend within $65 | first invoices | review the ceiling with the owner |
| IT-9 Hostinger browser console works (break-glass) | day 1 | must work before SSH is closed to the public |
| IT-10 Supabase settings: SSL enforcement, signups off after bootstrap, leaked-password protection, spend cap, IP Site URL and `token_hash` email templates | build | stop until set |
| IT-11 Minimum Supabase backup privileges (§Y.3) | before the first backup | isolated elevated credential (§Y.3 fallback) |

**Refund window:** IT-1, IT-2, IT-6 and IT-9 are scheduled for day 1, and IT-3 as soon
as the database is reachable. A fallback decision can then be made well inside
Hostinger's 30-day money-back period (owner decision by day 25; payment by card, not
crypto).

### X.2 Private access (F3-D6): licence check and recommendation

**Tailscale terms (pricing page and April 2026 pricing announcement):**
* The free Personal plan (6 users) is "for non-commercial use" and "only suitable for
  non-commercial use of Tailscale".
* The cheapest plan permitted for commercial use is **Standard at $8 per user per
  month** (no stated minimum).

**Licence assessment:** Diski 9 is being built towards an invited competition and later
public operation. Whether its F3 use is "non-commercial" is the owner's call. The
documents do not show that it is. Applying the owner's rule:
* **Tailscale Personal ($0):** acceptable **only** if the owner states in writing that
  Diski 9's F3 use is personal and non-commercial.
* **Tailscale Standard ($8/seat):** fits the budget for one seat (≈ $63.54 worst case).
  Adding the second operator would take the worst case to ≈ $71.54, above the $65 alert.
  It adds a third-party control plane at a recurring cost, for no security gain over
  WireGuard at this scale.
* **Recommendation: self-hosted WireGuard, $0.** Use Tailscale Personal instead only if
  the owner confirms non-commercial use and prefers it. Paid Tailscale is not
  recommended.

**WireGuard configuration (recommended):**

| Element | Setting |
|---|---|
| Interface | `wg0`, `10.88.0.1/24` on the VPS; one UDP listen port (a random high port, recorded in the host notes, not the default 51820). The interface private key is generated on the VPS (root, 0600) |
| Peers (at most 3) | owner laptop `10.88.0.2`, owner phone `10.88.0.3`, operator device `10.88.0.4` (only if F3-D13's operator exists). Each keypair is **generated on its own device** (private keys never leave it); a unique preshared key per peer; server `AllowedIPs` = the peer's `/32` only |
| Client side | `AllowedIPs = 10.88.0.1/32` (split tunnel: only the VPS goes through the tunnel); `Endpoint` = VPS public IP and port; `PersistentKeepalive = 25` (mobile NAT) |
| No routing | `net.ipv4.ip_forward = 0` and the IPv6 equivalent. Peers cannot reach each other, the internet or anything else through the VPS |
| Firewall (hPanel **and** host nftables/ufw, default deny inbound) | public interface: only the WireGuard UDP port. `wg0`: 443 for all peers; 22 for the owner peers only. Egress per §S.2, with API-Football blocked |
| Services | Caddy binds `10.88.0.1:443`; OpenSSH `ListenAddress 10.88.0.1` (keys only, no root, no passwords); Gunicorn `127.0.0.1:8050`; nothing listens on the public address except WireGuard |
| Name and TLS (no domain, F3-D7) | Canonical origin `https://10.88.0.1`. *Superseded by §Y.1 (one-shot private CA, IP-SAN certificate, CA key destroyed after signing; no name constraints relied on).* Supabase Site URL and redirect allow-list are set to that origin only; `__Host-` cookies work over HTTPS (checked in IT-6) |
| Keys | peer revoked by deleting its block + `wg syncconf` (lost device, operator leaves, end of F3); all keys rotated at the end of F3 |
| Break-glass | Hostinger browser console (hPanel MFA); temporary SSH to the owner's current IP only, recorded in the incident log and closed again |
| Monitoring | `wg show` latest-handshake in the on-host check; a failed tunnel never opens a public port automatically |

Compared with Tailscale: one silent UDP port instead of none; certificates and device
trust by hand; no third-party identity or control plane. These are acceptable for at
most three peers. §S.2's Tailscale design remains valid if Tailscale is chosen under the
licence rule.

### X.3 Off-host backups (F3-D8, F3-D15): provider, key custody, credentials

**X.3.1 Provider (recommended): Backblaze B2, EU Central region.**
* A company independent of both Hostinger and Supabase (AWS), on its own network.
* S3-compatible. **Object Lock at no extra cost** (governance and compliance modes;
  retention 1–3,000 days).
* Bucket-restricted application keys with individual capabilities; keys can expire.
* Pay-as-you-go **$6.95/TB/month**, first 10 GB free, no minimum storage duration,
  egress free up to 3× stored data. Diski 9's expected total (≈ 1–5 GB encrypted) is
  ≈ $0, and §V.3 keeps a $2 allowance.
* **Region note:** B2's region is chosen when the account is created. The owner must
  select EU Central at sign-up and confirm its data-centre location then (IT-7).
* B2 gives EU data residency, not EU-headquartered jurisdiction. If the owner wants an
  EU-headquartered provider, Scaleway Object Storage (Paris/Amsterdam) is the
  alternative. Its terms are not yet verified, so re-check them before choosing it.

**X.3.2 Bucket design**
* One private bucket (random suffix in the name). **Object Lock enabled at creation**,
  default retention **governance mode, 14 days**: the VPS credential cannot shorten or
  remove it; only the owner's master key can, in an emergency. *Superseded by §Y.2
  (30-day retention, 30-day hide-to-delete window, weekly owner inventory).*
* Unique, timestamped object names. Lifecycle rules: `daily/` hidden after 14 days,
  `weekly/` after 56 days (8 weekly copies), deleted 1 day after hiding (never before
  retention expires).
* No public access, no sharing links, no replication.

**X.3.3 Least-privilege credentials**

| Credential | Where it lives | Capabilities | Never |
|---|---|---|---|
| Backblaze account login + master key | owner only (password manager, MFA on the account) | everything | on the VPS, in the repository, in a chat or cloud session, in CI |
| **Upload key** | VPS `/etc/diski9/offhost.env` (root:diski9-backup, 0640), read only by the backup unit | restricted to the one bucket; `writeFiles` plus only what the upload tool proves it needs to locate the bucket (`listBuckets`) | `readFiles`, `listFiles`, `deleteFiles`, `bypassGovernance`, `writeFileRetentions`, `shareFiles`, key or bucket management |
| **Retrieval key** | not on the VPS; created by the owner per drill/recovery with an **expiry (≤ 7 days)**, then deleted | restricted to the bucket; `listBuckets`, `listFiles`, `readFiles` | write, delete, retention |

IT-7 records negative tests showing the upload key cannot list, read or delete.
* **Separate system user:** the backup unit runs as `diski9-backup`, not as the web user
  `diski9`. A compromise of the web process cannot read the upload key or the database
  owner password.

*§X.3.3 upload-key capabilities superseded by §Y.2.*

**X.3.4 Database dump (F3-D15, recommended; superseded by §Y.3).** The full Supabase CLI dump (roles, schema,
data including `auth`) runs nightly on the VPS as `diski9-backup`:
* The database owner password is held in `~diski9-backup/.pgpass` (0600) over
  `verify-full` TLS. It never appears on a command line, in the environment or in logs.
* The configuration export is encrypted with the dump.
* The owner keeps the master copy of the password in the password manager.
* The password is rotated at the end of F3 and after any suspected exposure.

**X.3.5 Encryption-key custody (`age`)**
* **Two key pairs are generated on the owner's own computer:** *primary* (kept in the
  owner's password manager) and *offline recovery* (printed or on an encrypted USB
  drive, stored in a separate physical place).
* Every backup and manifest is encrypted to **both** public recipients. Losing one
  private key never makes the backups unrecoverable.
* The VPS holds **only the two public recipients**. No private key ever lives on the
  VPS, in B2, in the repository, in CI, in a chat or in a cloud session.
* Decryption happens only on the drill/recovery machine. The F3 drills prove decryption
  **with each identity at least once**.
* If compromise is suspected, a new pair is generated and old copies are left to
  expire.
* The SHA-256 manifest checksum is recorded before encryption. Level-4 evidence
  requires the drill to match it (F2 safeguard B).

### X.4 Fallback triggers (DigitalOcean FRA1)

The provider is switched (owner decision, inside the refund window where possible) if
any of these occurs:
* IT-1 fails (not Frankfurt, or RTT target missed persistently).
* IT-3 fails and neither the IPv4 add-on nor the session pooler gives a passing lock
  test.
* IT-6 cannot be met.
* Repeated unexplained outages or performance below the §B targets during the 72-hour
  soak.
* The console/break-glass access (IT-9) is unusable.

DigitalOcean ≈ $64/month incl. assumed VAT stays within the $75 ceiling.

### X.5 Ordered F3 implementation plan

**Owner** = performed personally by the owner. **Claude** = prepared by Claude in the
repository and executed under F3-D22. Gates are hard stops.

| # | Step | Who | Gate / evidence |
|---|---|---|---|
| 0 | **Give the F3 implementation authorisation.** Confirm F3-D6 (commercial status → WireGuard or Tailscale Personal), F3-D8, F3-D15, F3-D22, F3-D12 | **Owner** | written instruction; register entry |
| O-1 | Prepare: password manager with MFA; authenticator app; the owner's computer ready for key generation | **Owner** | – |
| O-2 | Generate the two `age` key pairs and the one-shot private CA (§Y.1) on the owner's computer, using Claude's scripted instructions; store the private material as in X.3.5 / X.2 | **Owner** (Claude provides the script) | public recipients and CA certificate only are shared with the host |
| O-3 | **Buy Hostinger KVM 2:** account with MFA; 1-month term; **Germany/Frankfurt**; Ubuntu 24.04 LTS; **no daily backups**; pay by card; owner's SSH public key, password login disabled where offered | **Owner** | invoice (amount, tax), data-centre name recorded |
| O-4 | **Subscribe to Supabase Pro:** organisation with MFA; upgrade to Pro (card); spend cap left **on**; create project in **Frankfurt `eu-central-1`**, **Micro** compute; database password generated in the password manager; SSL enforcement on; download the CA certificate; leaked-password protection on | **Owner** | screenshots without keys; invoice |
| O-5 | **Backblaze B2:** account with MFA in **EU Central**; private bucket with Object Lock (governance, 14 days); lifecycle rules; create the **upload key** only (X.3.3) | **Owner** | key capability list recorded (not the key) |
| O-6 | Billing safeguards: Supabase usage notifications; calendar reminders for the Hostinger renewal date and the **day-25 refund decision**; monthly cost log against $65/$75 | **Owner** | cost log started |
| 1 | Day-1 verification script (read-only): data centre, OS, IPv6, RTT to Supabase, console access → IT-1, IT-2, IT-9 | Claude script, owner runs | **G1** pass, else X.4 |
| 2 | Host hardening (§F): updates, unattended security upgrades, users `diski9` and `diski9-backup`, SSH keys only, firewall default deny, time sync | Claude script, owner runs | config evidence |
| 3 | Private access (X.2 or §S.2), then close public SSH; external port scan from the owner's network | Claude + owner (device enrolment) | **G2**: only the WireGuard port (or none) public; IT-6 |
| 4 | Install the application at a recorded commit (no merge or tag); env file from `deploy/` with provider calls, refresh, notifications off and **no API-Football key**; egress to API-Football blocked; systemd units; Caddy with the private certificate | Claude script, owner runs | commit hash, unit status, `/healthz` over the tunnel |
| 5 | Supabase: apply existing migrations to head `app_0007` (no new migration); Auth settings (Site URL, redirects, signups off after the owner bootstraps the owner account; optional operator); app role and connection modes per F3-D5; TLS checks | Claude + **owner** (secrets typed only on the host) | IT-4, IT-10 |
| 6 | Hosted advisory-lock tests (`scheduler_lock_probe.py`, two concurrent ticks, holder termination, R1–R6, real `jobs tick` with provider calls off) | Claude script, owner runs | **G3 hard stop** (IT-3) |
| 7 | Backups: nightly football-store backup, full CLI dump incl. `auth` + configuration export, `age` to both recipients, upload, `backup record --kind offhost-copy`; upload-key negative tests N1–N9/P1 (§Y.2); restricted backup role (§Y.3) | Claude script, owner runs | **G4**: levels 1–3 in `ops status`; IT-7; IT-11 |
| 8 | Recovery drills with the retrieval key on temporary drill projects: **M1** and **M3**; target-first hold sequence (§S.9) with `PROVIDER HOLD` verified in the restored target **before** cutover; **operator sign-in after recovery**; SQLite restore to a new path + offline switch; decryption with each `age` identity; RPO/RTO measured; drill projects deleted | Claude + **owner** (creates/deletes drill projects, retrieval key) | **G5**: level 4 evidence; F3-R2 closed on the host; hosted part of F3-R1 demonstrated |
| 9 | Failure injection (§M), 72-hour scheduler soak with provider calls off, browser smoke and South African timings (§N) | Claude + owner | soak report; IT-5 |
| 10 | F3 acceptance report: hosted evidence labelled separately from local evidence; cost reconciliation; residual risks (F3-D21, F3-R1 manual-command part before F4) | Claude | **owner acceptance** (separate decision) |

Throughout: no secrets in the repository, chat, logs or command lines; no live
API-Football call; no participant accounts; no public endpoint; no merge, tag, release
or production deployment.

**After F3 (unchanged):**
* F4 requires its own authorisation, plus F3-D10, F3-D11 and the SF-14 analysis.
* F5 requires the tighter RPO, ML-01 and D-36.

### X.6 Unchanged safeguards
* Live SQLite replacement disabled (restore only to new paths, then an offline
  supervised switch).
* Provider calls off; refresh off; Official disabled; human-only publication.
* D-29b schedule unchanged.
* D-39a: app and scheduler co-located, verified off-host backups, no public access;
  football store to PostgreSQL before any public use.
* Stage D locking unchanged; the SYSTEM actor is never a bypass for privileged human
  operations.
* F2 evidence levels; disposable-target isolation.
* Provisional operator-only 24-hour PostgreSQL RPO.

### X.7 Budget with this package

| Line | From month 2 |
|---|---|
| Hostinger KVM 2 (monthly) | $24.49 |
| Supabase Pro (Micro within credit) | $25.00 |
| Backblaze B2 (≤ 10 GB free; allowance) | ≤ $2.00 |
| WireGuard / no domain / no external monitor | $0 |
| **Total ex VAT** | **≈ $51.49** |
| With 15 % VAT assumed on Supabase and storage | ≈ $55.54 |
| + IPv4 add-on if IT-2/IT-3 need it | ≈ $59.54 |
| + one-off drill-project compute in the drill month (estimate) | ≈ $64.54 (below the $65 alert) |

Month 1 is ≈ $45 (first Hostinger month $13.99).

## Y. Final technical clarifications before implementation authorisation (22 Nov 2026)

**Owner choices recorded (22 Nov 2026).** These complete the §X decisions. Like those,
they take effect only with the separate F3 implementation authorisation:
* **F3-D6:** self-hosted WireGuard. **No Tailscale** (neither Personal nor paid).
* **F3-D8:** Backblaze B2 EU Central as the independent off-host provider. Two
  owner-controlled `age` identities. **No private decryption key on the VPS.**
* **F3-D15:** the separate backup-user model is accepted, **subject to verifying the
  minimum database privileges** for a complete backup including Auth (Y.3).
* **F3-D22:** Claude prepares version-controlled scripts and runbooks. The owner runs
  them on the owner's computer or the server and returns secret-free evidence. **No
  production credential passes through chat.**
* **F3-D12:** no external uptime monitoring service in private F3. Internal and
  owner-device monitoring are kept.

Where Y differs from §X.2 or §X.3, Y takes precedence. In particular, **the IP
name-constrained CA of §X.2 is withdrawn**: it is not relied on, as Y.1 explains.

Evidence labels used in this section:
* **[L-PoC]** local proof of concept in the development container (22 Nov 2026). It is
  not hosted evidence and was not run on the owner's real devices.
* **[V-doc]** provider documentation.
* **[IT]** check performed at implementation time.

### Y.1 Private HTTPS for the WireGuard address

**Design: a one-shot private CA plus an IP-SAN server certificate.** No reliance on name
constraints.

| Item | Setting | Why |
|---|---|---|
| Root CA | generated **on the owner's computer**; EC P-256; `basicConstraints=critical,CA:TRUE,pathlen:0`; `keyUsage=critical,keyCertSign,cRLSign`; 180 days | used to sign exactly one server certificate |
| Server certificate | EC P-256; `basicConstraints=critical,CA:FALSE`; `keyUsage=critical,digitalSignature`; `extendedKeyUsage=serverAuth`; **`subjectAltName=IP:10.88.0.1`** (an iPAddress entry, not a DNS name); 180 days | browsers match an IP URL only against an iPAddress SAN and ignore the CN. 180 days is under the 398-day public limit and Apple's 825-day limit for user-installed roots |
| **CA private key** | **destroyed (`shred`) immediately after signing the server certificate** | nobody, including an attacker on the owner's computer or the VPS, can later issue another certificate under the trusted root. This replaces the name-constraint idea: X.509 does define iPAddress name constraints, but client enforcement for user-installed roots varies, so they are **not** used or relied on |
| What goes to the VPS | the server certificate and its key only (`/etc/diski9/tls/`, root:caddy, key 0640) | the root's public certificate goes to the peer devices only |
| Renewal / end of F3 | new root and certificate (F3 lasts weeks; 180 days is ample); remove the root from every device at the end of F3 or when a device is lost | no long-lived trust anchor |
| Caddy | site address `https://10.88.0.1`, `bind 10.88.0.1`, `tls /etc/diski9/tls/server.crt /etc/diski9/tls/server.key` (manual certificate, so no ACME attempt); reverse proxy to `127.0.0.1:8050` | the F3 Caddyfile replaces the template's allowlist with the WireGuard-only bind [IT] |
| HSTS | the template header is harmless. Browsers do not record HSTS for IP-address hosts (RFC 6797), so HSTS gives no protection here; the tunnel and the trusted certificate do | – |

**Browser trust on the peer devices (owner action, [IT] on each real device):**
* **macOS:** import into the login keychain and set "Always Trust" for SSL. Safari,
  Chrome and Edge use it.
* **Windows:** Trusted Root Certification Authorities (current user).
* **iOS/iPadOS:** install the profile, then turn on full trust in Settings → General →
  About → Certificate Trust Settings.
* **Android:** install it as a user CA certificate. Chrome trusts user CAs; some other
  apps do not.
* **Firefox:** uses its own store. Import the root there, or allow it to use the
  operating system's roots.

**Cookies and application settings:**
* `DISKI9_APP_ENVIRONMENT=production` and `DISKI9_APP_SITE_URL=https://10.88.0.1`.
  These satisfy the production rule that the site URL uses HTTPS, so cookies are Secure
  and the `__Host-` names are used (`settings.py`).
* `DISKI9_APP_TRUSTED_PROXIES=1` for Caddy.
* The Origin check compares against `https://10.88.0.1`. Browsers omit the default port,
  so the check matches.

**Supabase Auth: no browser redirect is involved.**
* Diski 9 does not use Supabase's redirect flow. Confirmation and recovery emails link
  straight to the app: `{{ .SiteURL }}/auth/confirm?token_hash=…&type=…`.
* The GET shows a confirmation page. The POST verifies the token server-side
  (`verify_otp`), as `provider.py` and `web.py` do.
* Supabase therefore never redirects to, or connects to, the VPS. Every Auth call is
  outbound from the VPS.

Settings (owner action):
* Site URL `https://10.88.0.1`.
* Redirect allow-list containing only that origin (unused by the flow, kept minimal).
* Confirm-signup and reset-password email templates edited to the `token_hash` link
  form.
* Signups off after the owner account is bootstrapped.

A link opened on a device that is not on the tunnel does not load, so it fails closed.
[IT] Supabase accepts the IP Site URL and the edited templates.

**Local proof of concept [L-PoC]** (OpenSSL 3.0.13, Chromium 153, test address
`10.88.0.1` added to the container's loopback and removed afterwards; CA key shredded
after signing):

| Test | Result |
|---|---|
| `openssl verify -verify_ip 10.88.0.1` on the IP-SAN certificate | OK. With `10.88.0.2` → "IP address mismatch" |
| Chromium with the root trusted in a dedicated NSS store, `https://10.88.0.1:8443` | loads with no certificate exception; `isSecureContext = true` |
| Same, with the root **not** trusted | `ERR_CERT_AUTHORITY_INVALID` |
| Certificate with the IP **only in the CN** (no SAN), same trusted root | Chromium `ERR_CERT_COMMON_NAME_INVALID`. **curl accepted it** (CN fallback), so curl is not a valid stand-in for browser checks |
| Cookies set exactly as Diski 9 does (`__Host-d9_session` Secure, HttpOnly, SameSite=Lax, Path=/; `__Host-d9_csrf` Strict) | both stored as host-only cookies for `10.88.0.1`; hidden from `document.cookie` |
| Same-origin POST | both cookies sent; `Origin: https://10.88.0.1:8443` (on port 443 this becomes `https://10.88.0.1`) |
| Top-level navigation from another site (as from an email link) | session cookie (Lax) sent; CSRF cookie (Strict) not sent, as designed |

### Y.2 Backblaze Object Lock against the VPS upload credential

**What the documentation establishes [V-doc]:**
* `b2_delete_file_version` requires `deleteFiles`. For a governance-locked version it
  also needs `bypassGovernance`, and locked versions return `access_denied`.
* Downloads require `readFiles`. Listing names or versions requires `listFiles`.
* `b2_update_file_retention` requires `writeFileRetentions`. Shortening or removing
  governance retention also requires `bypassGovernance`.
* Setting retention or legal hold at upload requires `writeFileRetentions` /
  `writeFileLegalHolds`.
* Lifecycle rules, bucket default retention and bucket settings need `writeBuckets`,
  which **bucket-restricted keys cannot have**.
* An upload with an existing name **creates a new version; the old version is kept**
  (and hidden).
* A lifecycle rule does not delete a version while its Object Lock retention is active.
* **Compliance** retention "cannot be removed by any user". **Governance** retention can
  be shortened or removed only by a key with `bypassGovernance`.

**The limitation found: hiding.**
* `b2_hide_file` requires only **`writeFiles`**, the capability any upload key must
  have. An S3 `DeleteObject` without a version ID (a delete marker) is presumably the
  same; the documentation does not state its capability.
* So the upload key **cannot delete or alter a stored version**, but it **can hide
  one**. A hidden version still exists and stays locked, but it is then subject to the
  lifecycle rule's "days from hiding to deleting" once the lock expires.
* The design must therefore guarantee a **detection window** longer than the time it
  takes to notice an attack.

**Revised bucket design (supersedes §X.3.2):**
* **Object Lock: governance mode, default retention 30 days.** Every version survives at
  least 30 days from upload whatever the VPS key does.
* **Lifecycle:** `daily/` hidden after 14 days and `weekly/` after 56 days.
  **`daysFromHidingToDeleting = 30`** for both. Any hidden version, whether hidden
  legitimately or by an attacker, persists at least 30 more days.
* Storage effect: about 44 days of dailies plus about 86 days of weeklies, still at
  most a few GB (≈ $0).
* **Weekly owner inventory:** a **list-only key** (`listBuckets`, `listFiles`; no read,
  write or delete) kept on the **owner's computer**, never on the VPS. It lists all
  versions and hide markers and compares them with the VPS's recorded uploads
  (`backup record`). Any unexpected hide marker, version or gap is an incident.
* Detection within 7 days, against a purge no earlier than 30 days after hiding.
* **Daily caps and alerts** on storage and Class A/B/C transactions (Class D cannot be
  capped [V-doc]). This limits a cost-abuse attack with the upload key.
* The upload key is restricted to the bucket **and to a name prefix** (`diski9/`).

**Upload key capabilities (supersedes §X.3.3):**
* `writeFiles` only, plus `listBuckets` **only if** the upload tool proves it needs it to
  resolve the bucket.
* No `readFiles`, `listFiles`, `deleteFiles`, `bypassGovernance`,
  `writeFileRetentions`, `writeFileLegalHolds`, `shareFiles`, `writeBuckets` or key
  capabilities.

**Governance-mode limitations (why governance is still chosen for F3):**

| Limitation | Effect | Mitigation |
|---|---|---|
| Any key with `bypassGovernance` can shorten or remove retention | owner-account compromise defeats the lock | no key with `bypassGovernance` is ever created; the master key is never stored on a device or service; account MFA |
| Retention is finite | after 30 days, a hidden version can be purged | 30-day hide-to-delete window plus the weekly inventory and the monthly restore drill |
| The hide operation is allowed to the upload key | an attacker can make backups invisible in normal listings | hidden versions remain listable and restorable with the owner's keys; inventory alarms |
| Compliance mode would resist even owner-account compromise | not chosen, because compliance data cannot be removed early by anyone, including after a mistaken upload. That later conflicts with D-36 deletion and retention duties | **revisit before F5** (participant data) |

**Negative tests (IT-7, upload key, on the VPS, against a canary object under
`diski9/canary/`; evidence = API name, HTTP status and error code only, never key
values):**

| # | Attempt with the upload key (native API **and** S3 API) | Required result |
|---|---|---|
| N1 | read: `b2_download_file_by_name`, `b2_download_file_by_id`, S3 `GetObject` | refused (401/403) |
| N2 | list: `b2_list_file_names`, `b2_list_file_versions`, S3 `ListObjectsV2`, `ListObjectVersions` | refused |
| N3 | delete: `b2_delete_file_version` (with and without `bypassGovernance=true`), S3 `DeleteObject` **with** a version ID | refused |
| N4 | overwrite: upload the same name with different content | accepted **as a new version**; with the owner's list key, the original version still exists with unchanged SHA-1/size and its retention date |
| N5 | hide: `b2_hide_file`, S3 `DeleteObject` without a version ID | **expected to succeed** (documented limitation); the owner's inventory shows the hide marker; the hidden version still exists and is locked |
| N6 | change retention or hold: `b2_update_file_retention` (shorten, remove, with `bypassGovernance`), S3 `PutObjectRetention`, `PutObjectLegalHold`; upload carrying a shorter retention or legal-hold header | refused. If a header upload is accepted, the owner verifies that object's retention is the bucket default (not shorter). Existing versions are unaffected either way, because upload headers apply only to the new object |
| N7 | bucket settings: `b2_update_bucket` (lifecycle, default retention), S3 `PutBucketLifecycleConfiguration`, `PutObjectLockConfiguration` | refused |
| N8 | key management: `b2_create_key`, `b2_list_keys`, `b2_delete_key` | refused |
| N9 | upload outside the prefix or to another bucket | refused |
| P1 | normal upload under `diski9/daily/` | accepted. The owner's list key shows governance retention ≈ upload + 30 days |

A failure of N1–N3 or N6–N9 stops backups from counting until the key is fixed. N5 is
the documented hide limitation covered by the design above.

**Verdict:** Object Lock retention cannot be bypassed with the VPS upload credential.
The credential cannot delete, read, list, shorten retention or change bucket rules.
Its one destructive-looking power, hiding, is bounded by the 30-day lock and the 30-day
hide-to-delete window and is detected by the weekly inventory.

### Y.3 Least privilege for a complete Supabase backup including Auth

**What the documentation establishes [V-doc]:**
* Supabase's backup guide runs `supabase db dump` three times (roles `--role-only`,
  schema, data `--data-only --use-copy`) as **`postgres`** with the database password.
* `postgres` "has admin privileges" but is **not a superuser**.
* The CLI "runs `pg_dump` in a container" and the guide's procedure starts by
  installing Docker.
* The default schema dump ignores managed schemas including `auth`, which a new project
  recreates.
* Since 21 April 2025, `postgres` can no longer create or drop objects in `auth`,
  `storage` and `realtime`, nor write their migration tables. Reading is not listed as
  restricted.
* Custom role passwords are never in backups and must be set again after a restore.
* The docs do **not** document a read-only backup role, `postgres`'s
  BYPASSRLS/CREATEROLE attributes, whether `postgres` can grant SELECT on `auth`
  tables, or whether `auth` tables have RLS enabled.

**Local PostgreSQL 16.15 test [L-PoC]** (disposable database `f3_privtest_*` created,
used and dropped; stand-in `auth` and `app` schemas; protected databases untouched):

| Test | Result | Consequence |
|---|---|---|
| SELECT-only role (no BYPASSRLS) runs `pg_dump --data-only` with an RLS-enabled table present | **fails**: "query would be affected by row-level security policy" | fails closed: never a silent partial dump |
| Same role with `--enable-row-security` | **succeeds but dumps zero rows** for the RLS table | **prohibited**: a silent incomplete backup. The script must never pass this flag |
| Role with `BYPASSRLS` (SELECT only, no write grants) | complete data dump | BYPASSRLS is needed **only if** dumped tables have RLS enabled |
| The backup role attempts a DELETE | refused by `default_transaction_read_only` | a guard only: a session can switch that setting off, so **the real control is having no write grants** |
| Roles dump (`pg_dumpall --roles-only`) as a non-superuser | fails on `pg_authid` | use `--no-role-passwords`: it **succeeds** from `pg_roles`. Passwords are never backed up anyway |
| A non-superuser with CREATEROLE but without BYPASSRLS creates a BYPASSRLS role | **refused** (PostgreSQL 16 rule) | whether `postgres` can create the backup role with BYPASSRLS depends on `postgres` itself having BYPASSRLS [IT] |

**Recommended design (F3-D15, revised):**
1. **Restricted role `diski9_backup`** for the nightly backup on the VPS, connecting over
   `verify-full`:
   * `LOGIN`, `NOINHERIT`, no write grants; `USAGE` on `app` and `auth`;
   * `SELECT` on all their tables and sequences;
   * `BYPASSRLS` **only if** a dumped table has RLS enabled;
   * `default_transaction_read_only = on` as a guard.
   * It produces:
     * the data dump (`pg_dump --data-only` of the `app` schema and the `auth` tables
       the CLI's data dump includes, with the CLI's exclusions);
     * the `app` schema dump (`--schema-only`, which needs only catalog access and
       SELECT);
     * the roles list (`pg_dumpall --roles-only --no-role-passwords`).
   * **The `postgres` password is then not on the VPS at all.**
2. **No Docker on the VPS.**
   * Native `pg_dump`/`pg_dumpall` from the PostgreSQL apt repository, with the client
     major version at least the server major version.
   * The exact flags and exclusions come from `supabase db dump --dry-run` (which prints
     the `pg_dump` script). This is generated once on the owner's computer, reviewed and
     committed as the backup script. Equivalence is proven by the M3 drill.
3. **The `postgres` credential (unavoidable, elevated) is used only by the owner, from
   the owner's computer:**
   * to create and grant `diski9_backup` once;
   * to perform M3 restores into new drill/recovery projects;
   * for any CLI dump that the restricted role is shown to be unable to make.
   * It is held in the owner's password manager.
   * Supabase **network restrictions** (database connections only from the VPS and the
     owner's current IP) are applied if available on the plan [IT].
   * It is rotated at the end of F3 and after any suspected exposure.

**Implementation check IT-11 (before the first backup; hard stop until resolved):**
* Read-only catalog queries as `postgres`:
  * `rolsuper`, `rolbypassrls`, `rolcreaterole` of `postgres`;
  * `relrowsecurity` of every `auth` and `app` table;
  * `has_table_privilege('postgres', 'auth.users', 'SELECT WITH GRANT OPTION')` for each
    `auth` table.
* Then create `diski9_backup` and prove that it can produce the three dumps.
* Then restore them into a temporary drill project (M3). Existing operators must be able
  to sign in, and the content must match.

**If IT-11 fails (fallback, documented and isolated):** if `postgres` cannot grant
SELECT on the needed `auth` tables, or cannot grant BYPASSRLS where RLS is enabled, the
complete dump needs the `postgres` credential. It then runs:
* on the VPS only as the dedicated `diski9-backup` system user (no shell, not in the
  `diski9` group);
* from a systemd unit with `LoadCredential=` (the password file root-owned 0600, exposed
  only to that unit), `ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges`, and no
  network beyond Supabase and B2;
* never in environment variables, command lines or logs;
* with Supabase network restrictions limiting the credential's use to the VPS and the
  owner;
* with rotation after F3.

The owner decides between this fallback and running the full dump from the owner's own
computer on a schedule. Either way, the residual risk is recorded.

### Y.4 Effect on §X

* §X.1(b)/(c): F3-D6, F3-D8, F3-D12, F3-D15 (conditional on IT-11) and F3-D22 are now
  **owner-approved**.
* §X.2 "Name and TLS": replaced by Y.1.
* §X.3.2–X.3.4: replaced by Y.2 and Y.3.
* §X.5 step O-2: the CA is the one-shot CA of Y.1.
* Step 7 adds IT-11 and the N1–N9/P1 matrix.
* New owner actions:
  * set B2 caps and alerts;
  * create the list-only inventory key on the owner's computer and run the weekly
    inventory;
  * edit the Supabase email templates;
  * install and later remove the root certificate on each peer device.

### Y.5 Remaining blockers before implementation authorisation

**None.** Every open question is now either answered by documentation and local
evidence, or is an implementation-time check with a defined stop rule and a fallback:

| Check | Stop rule | Fallback |
|---|---|---|
| IT-1/IT-2/IT-9 | Hostinger day-one checks | DigitalOcean |
| IT-3 | hosted locking: **hard stop** | IPv4 add-on or DigitalOcean |
| IT-6 | real-device certificate trust | – |
| IT-7 | B2 negative tests | – |
| IT-11 | Supabase privileges | isolated elevated credential |

None of them can be settled before purchase.

## Z. Amendment: Hostinger VPS in Düsseldorf (22 Nov 2026) — **conditionally approved for Stage F3**

**Status: CONDITIONALLY APPROVED IN PRINCIPLE** by the owner (22 Nov 2026), with
corrections, **for Stage F3 only**.
* F3-D1a and F3-D2a amend F3-D1 and F3-D2. The Frankfurt decision was never read as
  permitting Düsseldorf: the location is accepted only through this explicit amendment.
* **Final acceptance of the Düsseldorf location requires the hosted IT-1 measurement to
  pass**, with IT-1 exactly as originally approved (Z.5).
* Until IT-1 passes, the location is conditional. If IT-1 fails persistently, the
  existing DigitalOcean Frankfurt fallback and the refund-window decision process apply.
* No VPS or Supabase access was made in preparing this section. The public address,
  host name and credentials are not recorded in the repository.

### Z.1 What happened (owner-reported, Checkpoint 1)

| Item | Owner-reported fact | Evidence label |
|---|---|---|
| VPS | Hostinger KVM 2 (2 vCPU, 8 GB, 100 GB), Ubuntu 24.04 LTS, monthly, auto-renewal on, running, SSH public key supplied, root password in the password manager | [V-owner] |
| **Location** | **Düsseldorf, Germany.** The owner reports Düsseldorf appears to be Hostinger's only German VPS location | [V-owner] |
| Purchase | 22 Nov 2026; first payment **USD 12.64 including USD 1.65 tax**; expiry 22 Dec 2026 | [V-owner] invoice |
| Supabase | Pro project created in **Frankfurt (`eu-central-1`)**, Micro compute | [V-owner] |

Consequences for earlier evidence:
* The pre-sales **[AI]** statement "German VPS data centre is in Frankfurt" (§W.1) is
  **contradicted** by provisioning. The checkout's "taxes displayed $0" **[C]** is
  superseded by the invoice: tax is charged at about 15 % (1.65 / 10.99).
* This confirms why §W.1 kept AI statements apart from binding terms, and why IT-1
  measures instead of trusting a label.

### Z.2 Everything that depends on "Frankfurt" for the VPS

| Location | Text | Kind | Proposed change |
|---|---|---|---|
| §R F3-D1 (decision table) and §X.1(a) F3-D1 | "Hostinger KVM 2 … Germany/Frankfurt" | **approved decision** | superseded by **F3-D1a** if approved (row kept; status note) |
| §R F3-D2 and §X.1(a) F3-D2 | "Frankfurt for both the VPS and Supabase" | **approved decision** | superseded by **F3-D2a** (VPS Düsseldorf, Supabase Frankfurt) |
| §X.1(d) IT-1 | "VPS really in Frankfurt (hPanel data centre; RTT to Supabase `eu-central-1` p95 < 10 ms)" | **implementation-time check** | the location clause ("really in Frankfurt") is replaced by the approved Düsseldorf location; **the latency requirement is preserved exactly: VPS-to-Supabase database RTT p95 strictly below 10 ms** (Z.5) |
| §X.4 fallback trigger 1 | "IT-1 fails (not Frankfurt, or RTT target missed persistently)" | fallback rule | "IT-1 fails (RTT target missed persistently)" |
| §X.5 step O-3, §W.2, §V | "Germany/Frankfurt" purchase instructions | historical instructions | marked superseded by §Z |
| §B | "VM in Frankfurt … A Frankfurt VM with a Frankfurt database adds ~1–10 ms per query" | design rationale | **principle unchanged** (the app stays next to the database); Düsseldorf ~180 km away is expected to remain inside the 1–10 ms band, to be measured |
| §W.1 Location row | Frankfurt [AI] | evidence | annotated as contradicted by provisioning |
| §W.3, §X.4, F3-D1 fallback | "DigitalOcean … Frankfurt (FRA1)" | fallback | **unchanged**: still the fallback if Z.5 fails |
| `docs/operations_f3_owner_setup.md` §2 (G1 "IT-1 Frankfurt RTT"), §4 O-4 ("confirm that hPanel shows Frankfurt"), §8.2 ("Germany/Frankfurt") | runbook | owner instructions | reworded (Z.6) |
| `deploy/f3/host/f3_day1_check.py` | IT-1 evaluated as "median TCP connect ≤ 10 ms" over 10 samples (Checkpoint 0) | script | **corrected to the approved criterion**: RTT p95 strictly below 10 ms over 100 spaced samples per target and address family; methodology in Z.8 |
| `docs/architecture/phase6c6_implementation.md` §13 "Germany/Frankfurt" | record of the authorisation | historical record | unchanged (it records what was authorised); §13.3 records the discrepancy |
| `docs/product/weekly_challenge_decisions.md` F3 entries | register | historical record | unchanged; a new proposed-amendment entry |
| Supabase `eu-central-1` (F3-D4, §S.3, §Y.1, runbook O-3) | database region | approved | **unchanged** |

**Not location-dependent (verified by search):**
* No test, configuration validator, environment template, systemd unit, Caddy template
  or application code refers to Frankfurt or to the VPS location.
* `f3_day1_check.py` evaluates measured times only (no location).
* **Pre-existing discrepancy found:** the Checkpoint 0 script and runbook evaluated IT-1
  as a *median ≤ 10 ms* of 10 TCP connections, not the approved *p95 < 10 ms*. This is
  corrected here, before IT-1 has ever been run.
* `tests/test_f3_checkpoint0.py` and `tests/test_f2_deploy_templates.py` contain no
  location assumption.

### Z.3 Technical assessment: Düsseldorf VPS with a Frankfurt database

| Area | Assessment |
|---|---|
| Latency | The design rule (§B) is that the app sits next to the database because each page makes several database round trips. Düsseldorf–Frankfurt is ≈ 180 km straight line; typical metro-to-metro fibre round trips are a few milliseconds, against ≈ 1 ms inside one Frankfurt facility. **Expected** to stay below IT-1's 10 ms threshold, but **unmeasured** [T]. For a page with ~10–20 sequential queries, an extra ~3–5 ms per query adds ~30–100 ms server time, small against the ≈ 160–180 ms South Africa–Germany round trip each user already pays. The F3 page targets (§B, IT-5) remain the acceptance test |
| Advisory locking (Stage D) | The session-scoped lock is held over one connection, so distance changes timing, not semantics. The existing lock and statement timeouts are seconds, orders of magnitude above the added milliseconds. The hosted lock probe (IT-3, **G3b hard stop**) is unchanged and decides |
| Database TLS | `sslmode=verify-full` checks the **server's** certificate and host name (Supabase endpoints) against the pinned CA. The client's location plays no part. SSL enforcement still refuses plaintext. **Unchanged** (IT-4, G3a) |
| IPv6 / connection modes | The VPS location does not change the F3-D5 rule. IPv6 availability is a property of the Hostinger network and is measured by IT-2 as before |
| Private access (WireGuard, IP-SAN HTTPS) | WireGuard terminates on the VPS whatever city it is in. The tunnel address `10.88.0.1`, certificate, cookies and Supabase Auth flow are location-independent. **Unchanged** (G2) |
| Backups and recovery | B2 EU Central (Amsterdam) is a different provider and city from both the VPS and the database. Off-host independence is unchanged; the VPS is if anything slightly further from the database's failure domain. The drills (M1/M3, target-first hold, operator sign-in, completeness §Y.3/runbook §6) are unchanged |
| Data residency | VPS and database both in **Germany (EU)**, backups in the Netherlands (EU). No F3 constraint names a city; participant data does not exist in F3. The F5 privacy statement (D-36) must list Düsseldorf, Frankfurt and Amsterdam |
| Operational complexity | None added: same provider, same services, same scripts. One more fact to record (two cities) |
| Cost controls | The location has no cost effect. **The invoice shows Hostinger charges ≈ 15 % tax**, which §X.7 assumed was $0 — see Z.4 |
| Acceptance criteria | Unchanged. IT-1's latency requirement is preserved exactly (RTT p95 < 10 ms); only its location clause changes. No gate is relaxed |

### Z.4 Cost re-estimate (tax now evidenced on Hostinger)

| Line | From month 2 |
|---|---|
| Hostinger KVM 2 $24.49 + ≈ 15 % tax | ≈ $28.16 |
| Supabase Pro $25 + 15 % VAT assumed | ≈ $28.75 |
| Backblaze B2 allowance (+ VAT) | ≤ $2.30 |
| **Total** | **≈ $59.21** |
| + IPv4 add-on if needed (+ VAT) | ≈ $63.81 |
| + drill-month temporary project compute (estimate ≈ $5) | **≈ $68.81: above the $65 alert, below the $75 ceiling** |

* The ceiling holds in every case.
* The $65 alert would trigger only in a drill month **and** only if the IPv4 add-on is
  needed. The alert is doing its job; no spending control changes.
* Month 1 actual: Hostinger $12.64, plus the Supabase invoice.

### Z.5 Conditions of the amendment and hosted verification

No new service, cost or access is introduced; everything runs in the existing
checkpoints.
1. **IT-1, unchanged requirement (Checkpoint 1, O-5, gate G1):**
   * Requirement: **VPS-to-Supabase database RTT, p95 strictly below 10 ms**, to the
     Supabase `eu-central-1` endpoints the application uses (the session pooler and
     `db.<ref>.supabase.co`, port 5432).
   * Measured with `f3_day1_check.py` per the methodology in Z.8.
   * **Final acceptance of F3-D1a/F3-D2a requires IT-1 PASS.**
2. **Representative connection and query latency (Checkpoint 3, informational):**
   * Measure from the VPS: TLS connection set-up time and the `SELECT 1` round trip
     (≥ 100 samples, p50/p95) over `verify-full` with the application role.
   * Also measure a representative page's database time.
   * These are **reported, not an acceptance condition**. Connection set-up includes TLS
     and authentication and is not RTT.
   * Making any of them a gate would be a new requirement for explicit owner review.
   * The existing F3 page targets (§B, IT-5) remain as approved.
3. **TLS still enforced (Checkpoint 3, G3a, unchanged):**
   * `verify-full` succeeds with the pinned CA on every endpoint used.
   * `sslmode=disable` is refused.
   * A wrong CA or host name fails.
4. **Locking (Checkpoint 3, G3b, unchanged):** the hosted lock probe passes. This is a
   hard stop.
5. **Controls unchanged (Checkpoints 2–5):**
   * G2: only the WireGuard UDP port is public;
   * G4: backup credential restrictions, N1–N9/P1 and IT-11;
   * G5: recovery validation.
   * All evidence is labelled hosted.
6. **If IT-1 fails persistently** (repeated runs on different days and times), the
   existing §X.4 fallback applies: DigitalOcean Basic 2 vCPU / 4 GB **FRA1**.
   * The owner decides **before day 25 (17 Dec 2026)**, inside Hostinger's 30-day
     money-back period (ending about 22 Dec 2026).
   * Auto-renewal is on, so the decision must precede the 22 Dec renewal.

### Z.6 Decisions

| ID | Decision | Supersedes | Status |
|---|---|---|---|
| **F3-D1a** | The Stage F3 VPS is the provisioned **Hostinger KVM 2 in Düsseldorf, Germany** (monthly billing). DigitalOcean Basic 2 vCPU / 4 GB FRA1 remains the fallback | the location part of F3-D1 (provider, plan, billing unchanged) | **conditionally approved** (Stage F3 only; final acceptance on IT-1 PASS) |
| **F3-D2a** | Region split: **VPS Düsseldorf, Supabase Frankfurt (`eu-central-1`)**, backups Amsterdam (B2 EU Central), all in the EU. IT-1 is unchanged: VPS-to-Supabase database RTT p95 strictly below 10 ms; only the location clause "VPS really in Frankfurt" is replaced | the VPS part of F3-D2 (the Supabase region is unchanged) | **conditionally approved** (Stage F3 only; final acceptance on IT-1 PASS) |

What the approval covers:
* keeping the existing VPS;
* continuing Checkpoint 1 with IT-1 as approved;
* the documentation and script corrections in Z.2.

It changes none of the following:
* spending limits, services or the Supabase region;
* TLS, private-access, backup, recovery or scheduler-locking controls;
* gates, safeguards or Stage F3/F4/F5/F6 boundaries;
* provider calls, refresh, public access or participants;
* the D-29b schedule.

### Z.7 Recommendation (accepted by the owner, conditionally)
**Accept Düsseldorf, conditionally.**
* The architecture's real requirement is database proximity, not a city name. Düsseldorf
  to Frankfurt is very likely to meet the unchanged 10 ms criterion.
* Every security, TLS, private-access, backup and recovery control is
  location-independent.
* Changing provider now would add cost and delay for no expected technical gain.
* If the measurements fail, the pre-approved DigitalOcean FRA1 fallback applies inside
  the refund window.

### Z.8 IT-1 RTT measurement methodology (for explicit review)

This defines **how** the unchanged requirement is measured. It does not change what is
required.
* **What a sample is:**
  * one TCP handshake from the VPS to the target's port 5432;
  * `connect()` returns when the server's SYN-ACK arrives, so the elapsed time is one
    network round trip plus local kernel and scheduling overhead;
  * the connection is closed immediately;
  * no TLS, no PostgreSQL authentication, no query and no data are involved.
  * Each sample therefore slightly *overestimates* RTT, which is conservative.
* **Why not ICMP ping:** often filtered by cloud networks, and it does not travel the
  database port's path.
* **Why not a database connection:** it adds TLS and authentication round trips and is
  not RTT. The owner's instruction is that it must not be conflated with RTT.
* **Sampling:**
  * 100 samples per target and per address family that resolves (`--samples`, minimum
    20);
  * spaced 0.2 s apart (`--interval`), so that the run spans about 20 s per family and
    one burst does not dominate.
* **Statistic:**
  * p95 by the nearest-rank method (the ⌈0.95·n⌉-th smallest successful sample; no
    interpolation);
  * min, p50 and max are reported alongside.
* **Pass rule:**
  * for **every** Supabase target, every address family that connects has **p95 < 10 ms
    (strict)**;
  * at least 95 % of that family's samples succeed;
  * at least one family per target connects.
  * Otherwise IT-1 = FAIL, and an unreachable target fails.
* **Persistence:**
  * a single FAIL is investigated and repeated at a different time of day;
  * "fails persistently" means FAIL in runs on at least two different days.
  * Every run's JSON is kept as evidence.
* **For explicit review:**
  * using the TCP handshake as the RTT instrument;
  * the sample count and spacing;
  * nearest-rank p95;
  * the 95 % success floor;
  * the persistence definition.

  The original requirement did not specify these; they are a proposed measurement
  definition, not a change to the threshold or its strictness.

## R. Decision record

Status values (updated 22 Nov 2026, §X): **approved** = approved by the owner on 22 Nov 2026,
effective only with the separate F3 implementation authorisation (Step 0; no spending
before it); **approved (rule)** = the rule is approved and the outcome needs one owner
statement; **proposed** = recommended, needs owner acceptance; **open** = no owner
position yet; **withdrawn**.

| ID | Decision | Current position / recommendation | Verified facts it rests on | Unverified assumptions | Status |
|---|---|---|---|---|---|
| F3-D1 | Hosting provider and plan | Hostinger KVM 2 (2 vCPU / 8 GB / 100 GB NVMe), one-month billing, Germany/Frankfurt; fallback DigitalOcean Basic 2 vCPU / 4 GB FRA1 if Hostinger fails a material technical acceptance test | checkout: $13.99 first month, $24.49 renewal, Germany, taxes $0 [C]; Frankfurt data centre [V-doc] | Frankfurt location, IPv6 [AI] — verified on day one | approved |
| F3-D2 | Region | Frankfurt for Supabase and the VPS | no Supabase African region; Hostinger/DigitalOcean Frankfurt [V-doc] | South African page timings meet targets [T] | approved |
| F3-D3 | Spending ceiling | ≤ $75/month all-in recurring infrastructure, alert at $65; no long-term prepayment (estimate ≈ $51–56; worst case ≈ $60, ≈ $65 in a drill month; §X.7) | Supabase Pro $25 incl. $10 credit [V-doc]; Hostinger checkout [C] | VAT on Supabase/storage; storage ≈ $2 | approved |
| F3-D4 | Create the hosted Supabase project (owner action) | Pro, Micro, Frankfurt, SSL enforcement on, signups off after bootstrap | Pro/Micro pricing [V-doc] | – | approved |
| F3-D5 | Database connection-mode rule | app: session pooler; scheduler: direct over IPv6, else session pooler, else IPv4 add-on (≈ $4); any lock-test failure is a hard stop | session pooler IPv4; direct IPv6 unless add-on [V-doc] | VPS IPv6 [AI]; pooler keeps advisory locks [T] | approved |
| F3-D6 | Private-access method | **self-hosted WireGuard**; no Tailscale (Personal or paid); one-shot private CA with IP-SAN certificate (§Y.1) | Tailscale Personal "for non-commercial use" [V-doc]; local TLS/cookie PoC [L-PoC] | trust on the owner's real devices (IT-6) | approved |
| F3-D7 | Domain | none in F3: the canonical origin is `https://10.88.0.1` over WireGuard with the IP-SAN certificate (§Y.1); an owner domain only for the public architecture | – | – | approved |
| F3-D8 | Off-host storage and key custody | Backblaze B2 EU Central (Amsterdam); Object Lock governance 30 days; hide-to-delete 30 days; weekly owner inventory with a list-only key; bucket- and prefix-restricted `writeFiles` upload key on the VPS; expiring read-only retrieval key held by the owner; two owner-held `age` identities, no private key on the VPS (§X.3, §Y.2) | B2 capabilities, Object Lock, lifecycle, caps, region [V-doc] | negative tests N1–N9/P1 (IT-7) | approved |
| F3-D9 | Hosted recovery drill | temporary drill project(s), deleted afterwards: M1 in place and M3 from the off-host CLI dump with configuration re-applied; M2 optional (beta); local M4 reported separately as partial | hourly compute billing; restore-to-new-project beta [V-doc] | drill cost < $5 [A] | approved |
| F3-D10 | Automatic hold activation (before F4) | option (c): cutover check + rolled-back-database detection | accepted F2 hold behaviour | – | open (before F4) |
| F3-D11 | Manual provider-command coverage (before F4) | extend the hold to the shared API-Football client factory | inventory in K | – | open (before F4) |
| F3-D12 | External uptime monitor | none in private F3; on-host timer + owner-device check over WireGuard | – | – | approved |
| F3-D13 | Accounts in F3 | owner plus at most one operator; no participants | – | – | approved |
| F3-D14 | Hostinger 24-month promotional prepayment | declined; monthly billing only | promotion terms [V-owner] | – | approved |
| F3-D15 | Backup credential model | restricted `diski9_backup` role (SELECT, BYPASSRLS only if needed, no writes) for the nightly dump on the VPS as the `diski9-backup` user; native `pg_dump` with the CLI's flags (no Docker); `postgres` password used only by the owner from the owner's computer; isolated fallback if IT-11 fails (§Y.3) | Supabase backup guide, postgres not superuser, April 2025 restrictions [V-doc]; PG16 privilege tests [L-PoC] | `postgres` can grant SELECT on `auth` tables / BYPASSRLS (IT-11) | approved (subject to IT-11) |
| F3-D16 | Supabase plan | Supabase Pro from the beginning of F3; Pro mandatory for F4/F5 | Pro daily backups, no pausing, IPv4 add-on [V-doc] | – | approved |
| F3-D17 | Hosting commitment model | monthly VPS billing only | Hostinger one-month term [C] | – | approved |
| F3-D18 | Accept M3-only Auth recovery on Free (amends S.8) | withdrawn — Supabase Pro from the beginning | – | – | withdrawn |
| F3-D19 | Leaked-password protection | on from the start of F3 (Pro feature) | available on Pro [V-doc] | – | approved |
| F3-D20 | Hostinger optional daily backups ($6/month) | not purchased at this stage; Diski 9's independent encrypted off-host backups remain mandatory and are the verified recovery path | $6/month option [C] | included Hostinger backup frequency/retention [open] | approved |
| F3-D21 | No verified credit-backed VPS uptime SLA | accepted as a documented F3 residual risk; monitoring (72-hour soak, `ops status`/`ops check`, failure injection) and recovery requirements unchanged; DigitalOcean fallback if availability proves inadequate | uptime guarantee advertised at checkout [C]; percentage/compensation not provided [AI] | – | approved |
| F3-D22 | Execution model | Claude prepares version-controlled scripts and runbooks; the owner executes them on the owner's computer or the server and returns secret-free evidence; no production credential through chat | the cloud container cannot reach the VPS | – | approved |
| F3-D1a | VPS location (amends F3-D1) | the provisioned Hostinger KVM 2 in **Düsseldorf**, Germany; monthly; DigitalOcean FRA1 fallback unchanged (§Z) | VPS provisioned in Düsseldorf [V-owner]; Düsseldorf reported as Hostinger's only German location [V-owner] | VPS-to-Supabase RTT (IT-1) | **conditionally approved** (Stage F3; final on IT-1 PASS) |
| F3-D2a | Region split (amends the VPS part of F3-D2) | VPS Düsseldorf, Supabase Frankfurt `eu-central-1`, backups Amsterdam; IT-1 unchanged: VPS-to-Supabase database RTT p95 strictly below 10 ms (methodology §Z.8) | all EU/Germany [V-owner] | IT-1 [T] | **conditionally approved** (Stage F3; final on IT-1 PASS) |

Nothing is purchased, subscribed, provisioned or created until the owner gives the F3
implementation authorisation (§X.5 step 0). All F3 decisions needed before purchase are
now recorded (§X, §Y); F3-D10 and F3-D11 remain open for F4.

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
  [Tailscale HTTPS certificates](https://tailscale.com/kb/1153/enabling-https/),
  [Tailscale pricing v4 (Apr 2026)](https://tailscale.com/blog/pricing-v4),
  [Tailscale pricing FAQ](https://tailscale.com/kb/1251/pricing-faq).
* Clarification sources (§Y): [B2 hide file](https://www.backblaze.com/apidocs/b2-hide-file),
  [B2 delete file version](https://www.backblaze.com/apidocs/b2-delete-file-version),
  [B2 update file retention](https://www.backblaze.com/apidocs/b2-update-file-retention),
  [B2 upload file](https://www.backblaze.com/apidocs/b2-upload-file),
  [B2 lifecycle rules](https://www.backblaze.com/docs/cloud-storage-lifecycle-rules),
  [B2 file versions](https://www.backblaze.com/docs/cloud-storage-file-versions),
  [B2 caps and alerts](https://www.backblaze.com/docs/cloud-storage-data-caps-and-alerts),
  [B2 data regions](https://www.backblaze.com/docs/cloud-storage-data-regions),
  [Supabase roles](https://supabase.com/docs/guides/database/postgres/roles),
  [Supabase superuser access](https://supabase.com/docs/guides/database/postgres/roles-superuser),
  [Supabase CLI db dump](https://supabase.com/docs/reference/cli/supabase-db-dump),
  [April 2025 auth/storage/realtime restrictions](https://supabase.com/changelog/34270-restricting-access-on-auth-storage-and-realtime-schemas-on-april-21-2025),
  [PostgreSQL pg_dump (row security)](https://www.postgresql.org/docs/16/app-pgdump.html),
  [RFC 6797 (HSTS, IP hosts)](https://www.rfc-editor.org/rfc/rfc6797).
* Off-host storage sources (§X.3): [Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing),
  [B2 application keys](https://www.backblaze.com/docs/cloud-storage-application-keys),
  [B2 key capabilities](https://www.backblaze.com/docs/cloud-storage-application-key-capabilities),
  [B2 Object Lock](https://www.backblaze.com/docs/cloud-storage-object-lock).
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
