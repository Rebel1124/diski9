# Diski 9 Weekly Challenge — Outstanding Decision Review (Phase 6C preparation)

> **Update (Phase 6C architecture finalisation):** the owner has since decided
> most items reviewed here (D-02 deferred; D-03, D-04, D-05, D-06, D-11, D-12,
> D-32b-Q1, D-34, D-35, D-37, D-38, T-09–T-11 approved; D-36 in principle; D-29
> collection approved). The [decision register](weekly_challenge_decisions.md) is
> authoritative; this review is kept as the record of options and trade-offs.
> D-01 is now covered by the [auth comparison](../architecture/auth_provider_comparison.md)
> and D-08 by [`settle/v1`](weekly_challenge_settle_v1.md).

**Status:** review for the product owner. Every item below is still **outstanding**
unless the register says otherwise. A recommendation is not an approval. Approved
items stay in the [decision register](weekly_challenge_decisions.md), which remains
the source of truth.

**Sources reviewed:** the decision register (Phase 6B close-out), the PRD, the UX
specification, the technical design, the engine and UI documentation, the
implementation plan, and the D-32b note.

**Phase naming.** The register's older "Blocking" column used the original 6C–6H
lettering (6E identity, 6F settlement, 6G points). The owner has since confirmed
a new Phase 6C that contains all of those backend items, so most of them now
block the new Phase 6C.

## Summary

| ID | Title | Status | Superseded? | Recommendation (short) | Needed |
|---|---|---|---|---|---|
| D-01 | Identity and sign-in | Outstanding | No | In-app OpenID Connect sign-in with a managed provider | **Before 6C** |
| D-02 | Hosting | Outstanding | No | One small managed host (container), same region as the database | 6C needs only the constraints; the provider by Phase 10 |
| D-03 | Database | Outstanding | No | PostgreSQL as the production target; SQLite kept for local work and tests | **Before 6C** |
| D-04 | Leaderboard privacy | Outstanding | No | Public display names; opt-out shown as "Private participant" | Default before 6C; final wording before Phase 10 |
| D-05 | Display-name policy | Outstanding | No | 3–24 characters, unique, blocklist, limited changes, name history | **Before 6C** |
| D-06 | Deadline buffer | Outstanding (in use) | Effectively by R-01 | Approve 15 minutes, stored per round | **Before 6C** |
| D-08 | Settlement and void rules `settle/v1` | Outstanding (payout part resolved) | Partly, by D-32, D-33, D-32b | Accept V1–V5 and the 48-hour cutoff | **Before 6C settlement** |
| D-11 | Round calendar | Outstanding | No | Weekend rounds; publish Thursday 06:00 UTC; postpone on failed checks | **Before 6C** (defaults) |
| D-12 | PSL coverage | Outstanding | No | Accept for the MVP; disclose in the UI | Deferrable (6D copy) |
| D-29 | Championship validation | Approach approved; validation open | No | Continue; now includes D-32b; needs a weekly full-pool capture after the trial | Before the first official championship |
| D-32b-Q1 | D-32b in practice rounds | Outstanding (new) | No | Apply the same test | Deferrable |
| D-34 | Roles and permissions | Outstanding (new) | No | Participant, operator, owner; capability checks server-side | **Before 6C** |
| D-35 | Result corrections and operator overrides | Outstanding (new) | No | Provider results by default; audited operator override | **Before 6C settlement** |
| D-36 | Account deletion and data retention | Outstanding (new) | No | Pseudonymise on deletion; keep settlement records | Schema before 6C; policy before Phase 10 |
| D-37 | Eligibility, terms and responsible engagement | Outstanding (new) | No | 18+ self-declaration, terms acceptance stored | Before Phase 10 (record field in 6C) |
| D-38 | Start of the first official championship | Outstanding (new) | No | Beta rounds unofficial; championship 1 starts after D-29 | Before Phase 10 |
| T-09 | Server-side withdrawal | Proposed (technical, new) | — | Before the deadline only; audited; no entry counted | Adopted unless you object |
| T-10 | Your View storage | Proposed (technical, new) | — | Private per user; context-stamped; never used in scoring | Adopted unless you object |
| T-11 | Designation history and derived counters | Proposed (technical, new) | Refines T-05, T-07 | Insert-only designation records; counters derived | Adopted unless you object |

## Existing outstanding decisions

### D-01 — Identity and sign-in

1. **Question:** how do participants create accounts and sign in?
2. **Current status:** outstanding. The register recommended an authenticating
   reverse proxy, blocking the old Phase 6E.
3. **Resolved or superseded?** No. The owner-confirmed Phase 6C now includes
   authentication, so it blocks 6C.
4. **Options:**
   * **A. Authenticating reverse proxy** (for example oauth2-proxy in front of
     the app). The app reads a trusted identity header.
   * **B. In-app OpenID Connect (OIDC)** with a managed identity provider (for
     example Google sign-in, or a hosted service offering Google, Apple and email
     links). The Flask server behind Dash handles the redirect and a signed
     session cookie.
   * **C. Own username and password accounts** (password hashing, resets,
     email verification).
   * **D. Email magic links only**, built in-house.
5. **Recommendation: B, in-app OIDC with a managed provider.** Store only the
   provider's stable subject identifier, plus an email address held privately for
   account recovery if the provider gives one. This **revises** the earlier
   proxy recommendation: public read pages, optional sign-in, account deletion,
   roles (D-34) and future premium entitlements are all easier when the app owns
   the session. No passwords are stored by Diski 9.
6. **Trade-offs:** B adds one small dependency (an OIDC client library) and a
   provider account; it ties sign-in availability to that provider. A keeps the
   app simpler but makes mixed public and signed-in pages and in-app roles
   awkward. C and D put password or email security and deliverability on Diski 9.
   **Implications:** a `users` table keyed by an internal ID with a separate
   identity link table (so a second provider can be added later); sign-in routes
   on the Flask server; every write callback checks the session server-side.
   Which provider to use is a sub-decision that can follow the approach.
7. **Needed:** before Phase 6C (the approach); the provider can be chosen early
   in 6C.

### D-02 — Hosting

1. **Question:** where does the hosted application run?
2. **Current status:** outstanding; recommendation "a single hosted server".
3. **Resolved or superseded?** No.
4. **Options:** A. a virtual private server you manage (operating system,
   updates, backups); B. a managed container platform (one web service plus
   scheduled jobs); C. a serverless platform; D. a full cloud provider stack.
5. **Recommendation: B**, one small container service running Gunicorn with
   the Dash app, platform-scheduled CLI jobs, and a managed PostgreSQL database in
   the same region. Choose a region with good latency to South Africa and, later,
   Europe. Keep everything configured through environment variables so the host
   can change without code changes.
6. **Trade-offs:** B costs a little more than a bare server but removes operating
   system maintenance and gives backups. C fits Dash and long-running jobs
   poorly. D is unnecessary complexity for launch. **Implications for 6C:** the
   code must not depend on the host: configuration from the environment, no local
   file state that matters, jobs as idempotent CLI commands, health check
   endpoint.
7. **Needed:** 6C needs only these constraints. The provider choice can wait until
   Phase 10 (deployment), unless you want a staging environment during 6C.

### D-03 — Database for hosted use

1. **Question:** which database serves the hosted, multi-user application?
2. **Current status:** outstanding; recommendation "SQLite (WAL) first;
   PostgreSQL before multiple workers".
3. **Resolved or superseded?** No, but Phase 6B changed the evidence: the builder
   render takes about 2.5–3 seconds, so more than one web worker is likely at
   launch, which is exactly the point where the earlier recommendation moves to
   PostgreSQL.
4. **Options:** A. SQLite in WAL mode on a persistent volume; B. PostgreSQL in
   production, SQLite locally; C. PostgreSQL everywhere.
5. **Recommendation: B.** Write the Phase 6C schema and queries in SQLAlchemy
   Core with Alembic migrations that run on both, use PostgreSQL row locking in
   production, and add a PostgreSQL test run for the transaction, locking and
   trigger tests. Keep the existing research and odds tables in the same database
   so settlement can read fixtures and results in one transaction.
6. **Trade-offs:** B adds a managed database cost and a second database in tests.
   A is simplest but serialises writers, fits one process only and makes backups
   and failover manual. C is cleanest but makes local research work heavier.
   **Implications:** immutability triggers must be written for both engines (or
   enforced in the service layer with tests); `BEGIN IMMEDIATE` (SQLite) and
   `SELECT … FOR UPDATE` (PostgreSQL) behind one service function; the existing
   odds-trial and research tooling keeps working on SQLite.
7. **Needed:** before Phase 6C, because locking, triggers and migrations depend
   on it.

### D-04 — Leaderboard privacy

1. **Question:** what is shown about participants on public leaderboards?
2. **Current status:** outstanding; recommendation "public display names with an
   opt-out".
3. **Resolved or superseded?** No.
4. **Options:** A. public display names, no opt-out; B. public display names with
   an opt-out; C. leaderboards visible only to signed-in participants; D. private
   by default.
5. **Recommendation: B.** An opted-out participant still occupies their rank
   (so the ranking stays checkable) but is shown as "Private participant". No
   email addresses or provider details ever appear. Signed-in participants always
   see their own row.
6. **Trade-offs:** B keeps the competition social and transparent; hidden names
   make rank gaps visible but explained. C reduces sharing and YouTube use. D
   undermines the competition. **Implications:** one `leaderboard_public` flag
   (already in the design), applied in the leaderboard query.
7. **Needed:** the default (B) before 6C so the schema includes it; final wording
   and policy before Phase 10.

### D-05 — Display-name policy

1. **Question:** rules for public display names.
2. **Current status:** outstanding; recommendation "3–24 characters; unique;
   blocklist".
3. **Resolved or superseded?** No.
4. **Options:** A. free text; B. the earlier rules; C. the earlier rules plus a
   change limit and history.
5. **Recommendation: C.** 3–24 characters (letters, digits, spaces, `-_.`),
   unique ignoring case, a basic blocklist, and no names that imitate staff or
   "Diski 9". At most one change every 30 days; every name kept in a history table
   so historical leaderboards and reports can be audited. Operator can rename with
   a reason.
6. **Trade-offs:** history adds one table; a change limit prevents abuse but can
   frustrate. **Implications:** chosen at first sign-in; rename and report
   functions for the operator (D-34).
7. **Needed:** before Phase 6C (account creation).

### D-06 — Deadline buffer

1. **Question:** how long before the earliest eligible kickoff does the round
   lock?
2. **Current status:** outstanding, recommendation 15 minutes. In practice 15
   minutes is already used everywhere (R-01, FR-R3, the prototype and the
   engine's round sheet).
3. **Resolved or superseded?** Effectively settled by R-01 and FR-R3, but never
   formally approved.
4. **Options:** 0, 15, 30 or 60 minutes.
5. **Recommendation: approve 15 minutes**, stored on each round at publish (so a
   later change never alters a published round).
6. **Trade-offs:** longer buffers reduce the risk from early kickoffs and clock
   drift but cut decision time; 15 minutes plus the V3 rule (kickoff moved before
   the deadline is void) covers the risk.
7. **Needed:** before Phase 6C (server-side deadlines).

### D-08 — Settlement and void rules `settle/v1`

1. **Question:** the settlement rules: 90-minute result, void codes V1–V5, and the
   settlement cutoff.
2. **Current status:** outstanding; "accept as specified".
3. **Resolved or superseded?** **Partly.** The payout treatment of voids is
   decided by D-32 (partial voids), D-33 (fully void entries) and D-32b (whole
   rounds). What remains is the classification of results:
   * 90-minute score only; `AET` and `PEN` settle on the 90-minute score;
   * V1 postponed and not completed by the cutoff; V2 cancelled, awarded or
     walkover; V3 kickoff moved before the deadline, or started before it; V4
     abandoned, suspended or interrupted and not completed by the cutoff; V5 a
     match completed by the cutoff after a postponement or suspension settles
     normally;
   * cutoff `settle_cutoff_at` = round window end + 48 hours;
   * a final status with a missing score stays pending and is flagged.
4. **Options:** A. accept as specified; B. a longer cutoff (for example 7 days)
   to let more rearranged matches count; C. settle awarded matches on the
   awarded score.
5. **Recommendation: A.** The 48-hour cutoff keeps settlement within the week
   and before the next round; rearranged matches usually move by more than a
   week, so a longer cutoff mostly delays results. Awarded results are not a
   genuine 90-minute result and should stay void.
6. **Trade-offs:** a short cutoff voids more rearranged matches, which feeds the
   D-32b share; the D-29 pools will show how often. **Implications:** the cutoff
   also bounds how long a round can wait before D-32b is evaluated.
7. **Needed:** before Phase 6C settlement design.

### D-11 — Round calendar

1. **Question:** when rounds run, when they are published, and what happens when
   a week cannot open.
2. **Current status:** outstanding; recommendation "weekend window; publish
   Thursday 06:00 UTC; postpone when the opening checks fail".
3. **Resolved or superseded?** Postponement is approved (D-28, D-30); the window
   and publish time are not.
4. **Options:** A. weekend rounds only (Friday 00:00 to Monday 23:59 UTC); B.
   weekend plus midweek rounds; C. rolling rounds.
5. **Recommendation: A for the MVP.** Publish Thursday 06:00 UTC, after the
   provider's overnight update (about 02:00–03:30 UTC) and an odds refresh; round
   code by ISO week (as in the prototype). Midweek rounds are deferred; they would
   double the operational load and shorten championships to five weeks.
6. **Trade-offs:** a single weekly round is simple and fits YouTube content; the
   earliest Friday kickoff sets an early deadline for Monday matches (accepted in
   design §5.2). **Implications:** scheduled jobs for refresh, publish, settle and
   finalise; the calendar is configuration, not code.
7. **Needed:** the defaults before Phase 6C (round management and jobs).

### D-12 — PSL coverage

1. **Question:** how to handle the PSL, which has no qualifying consensus odds.
2. **Current status:** outstanding; recommendation "accept for the MVP and state
   it in the UI". The odds trial confirms it: every capture so far has returned 0
   PSL fixtures with odds.
3. **Resolved or superseded?** No.
4. **Options:** A. accept and disclose; B. remove the PSL from the Weekly
   Challenge universe entirely; C. relax consensus rules for the PSL (conflicts
   with the approved C-06); D. add another odds source (a new provider, needs
   separate approval).
5. **Recommendation: A.** The PSL stays in the Match Lab (model analysis), and the
   Weekly Challenge explains that PSL fixtures appear only when at least three
   bookmaker groups price them. Revisit D with a future data-source review.
6. **Trade-offs:** for a South African audience the absence is noticeable; C would
   weaken the market methodology. **Implications:** copy only.
7. **Needed:** deferrable to Phase 6D (copy); does not block 6C.

### D-29 — Championship scoring validation (approach approved)

* **Status:** approach approved; the validation itself is open. Not a blocker for
  development; required before the first official public championship.
* **Change in this update:** the D-29 validation now also covers the approved
  D-32b rule: how often it would have fired on the observed voids of each real
  pool, and on simulated cancellation patterns, reported separately.
* **Evidence so far:** one complete real weekly pool (17 Nov 2026: 60 fixtures,
  six leagues). The scheduled odds trial has run every three hours since
  15 November (30 captures by 18 November), but it covers only the EPL and the
  PSL (EPL priced, PSL 0 fixtures) and ends on 21 November.
* **Dependency to resolve:** six to eight *full* weekly pools (all eight leagues,
  frozen at a Thursday publish time), plus their settled results, are still
  needed. The current trial cannot supply them on its own. Recommendation: after
  the trial ends, capture one complete weekly pool per week (one odds refresh at
  the proposed publish time, about 14 requests, plus results after the weekend)
  until six to eight pools exist. This needs your approval because it is a new
  scheduled process; nothing has been changed.

## New items identified during Phases 6A and 6B

### D-32b-Q1 — D-32b in practice rounds

Covered in the [D-32b note](weekly_challenge_d32_round_invalidation.md) §8.
Recommendation: apply the same test, so heavily voided practice results are
refunded too. Deferrable; the default (practice rounds settle normally) is safe.

### D-34 — Roles and permissions

1. **Question:** who can do what? D-32b requires an operator permission for
   exceptional invalidation, and Lucy (Phase 7) must be owner-only.
2. **Status:** outstanding (new).
3. **Superseded?** No.
4. **Options:** A. a single admin flag; B. a small fixed set of roles mapped to
   capabilities in code; C. a configurable permissions system.
5. **Recommendation: B.** Roles `participant`, `operator` and `owner`.
   Capabilities are checked server-side in the service layer, never in the
   browser. The operator can publish, postpone, void a round, override results
   (D-35), reopen a finalised round and rename users, each with a reason and an
   audit record. The owner has every operator capability plus private features
   (Lucy, internal reports). Premium access is **not** a role: it is a separate
   entitlement (see the architecture note), so commercial plans never grant
   operator powers.
6. **Trade-offs:** B is simple and testable; C is unnecessary at launch.
   **Implications:** a role column or role table; an audit log table; owner role
   assigned only by a CLI command on the server, never through the web.
7. **Needed:** before Phase 6C.

### D-35 — Result corrections and operator overrides

1. **Question:** API-Football is the result source. What happens when it is late,
   wrong or contradicts the official result?
2. **Status:** outstanding (new). The design covers corrections from the provider
   (T-06, R-14) but not a human override.
3. **Superseded?** No.
4. **Options:** A. provider results only; B. provider by default, with an audited
   operator override; C. two-source reconciliation.
5. **Recommendation: B.** An override is stored as a new result observation with
   source `operator`, a reason and the actor; it takes precedence until the
   provider agrees or the operator withdraws it. Settlement, D-32b and scoring
   re-run from it like any other correction.
6. **Trade-offs:** B adds an operator task and a responsibility; A risks leaving a
   known-wrong result in place. **Implications:** part of the settlement audit
   design; requires D-34.
7. **Needed:** before Phase 6C settlement design.

### D-36 — Account deletion and data retention

1. **Question:** what happens to leaderboards and settlement history when a
   participant deletes their account? (South Africa's POPIA applies at launch;
   the GDPR becomes relevant with the European expansion.)
2. **Status:** outstanding (new).
3. **Superseded?** No.
4. **Options:** A. hard delete everything; B. pseudonymise: remove identity and
   personal data, keep settlement records under "Former participant"; C. keep
   everything.
5. **Recommendation: B.** Historical rankings and championship results stay
   consistent, which the audit requirements need, while the person is no longer
   identifiable. Your View estimates and notes are deleted.
6. **Trade-offs:** B needs a separation between the person (identity, email,
   display-name history) and the participant record used by results. A breaks
   historical rankings. C conflicts with privacy law. Legal review is advisable
   before launch.
7. **Needed:** the separation in the 6C schema; the written policy before Phase
   10.

### D-37 — Eligibility, terms and responsible engagement

1. **Question:** minimum age, terms acceptance and responsible-engagement
   messaging for a free, virtual-credit product that shows bookmaker reference
   odds.
2. **Status:** outstanding (new).
3. **Superseded?** No.
4. **Options:** A. no restriction; B. 18+ self-declaration and terms acceptance at
   sign-up; C. verified age.
5. **Recommendation: B.** Even without money, the product presents odds and
   accumulators; an 18+ declaration plus the existing communication rules (no
   staking advice, banned words, "credits have no value") is proportionate.
6. **Trade-offs:** C is intrusive and costly; A risks reputational issues.
   **Implications:** store the accepted terms version and timestamp per user.
7. **Needed:** before Phase 10 (public beta); the record fields in 6C.

### D-38 — Start of the first official championship

1. **Question:** which round is round 1 of championship 1?
2. **Status:** outstanding (new). D-29 must complete before the first official
   public championship.
3. **Superseded?** No.
4. **Options:** A. the first round after launch; B. beta rounds run as an
   unofficial "beta championship", and championship 1 starts at a date you
   announce after D-29.
5. **Recommendation: B.**
6. **Trade-offs:** B delays official titles but protects them from launch issues.
   **Implications:** championships carry an `official` flag.
7. **Needed:** before Phase 10.

## New technical proposals (adopted unless you object)

| ID | Proposal | Rationale |
|---|---|---|
| T-09 | **Server-side withdrawal:** allowed only before the deadline; recorded as an insert-only withdrawal event with time and user; a withdrawn entry is not in the locked set (it does not count toward D-28 or D-32b); the participant may submit again before the deadline | The prototype withdrawal is a browser note only; Phase 6C needs an authoritative record |
| T-10 | **Your View storage:** private to the user; stored per user and fixture with the model-context stamp introduced in Phase 6B.3; never used for submission, settlement or scoring; deleted with the account (D-36) | Keeps Your View educational and separate from the competition |
| T-11 | **Designation history and derived counters:** round designations (`championship`, `practice`, `postponed`, `void`) are insert-only records with a basis (`deadline`, `d32b`, `operator`) and reason; the current designation is the latest. Championship round numbers, the counter, points and standings are derived from current designations and settlements | Corrections and D-32b reassessments never duplicate points or advance the counter twice |
