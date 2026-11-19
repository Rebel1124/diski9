# Phase 6C.3 — Persistent competition functionality: implementation record

**Branch:** `feature/phase-6c3-competition-persistence` (from `597ed70`, the
approved `feature/match-lab-guidance` baseline: 1,158 tests, CI green).
**Authorised so far:** Stages A–D (assessment, rounds and snapshots, drafts, Your
View). Stages E–G (confirmation lifecycle, page integration, final acceptance)
wait for the owner's checkpoint approval. The handover for the checkpoint is
[`phase6c3_implementation_handover.md`](phase6c3_implementation_handover.md).

Precedence: the decision register (D- and T-series) over this document; this
document records **implementation decisions within the approved scope** (marked
"ID-n") and lists anything that needs the owner (marked "Owner").

## 1. Stage A — assessment of the baseline

### 1.1 What already exists and is reused

| Area | Existing asset | Use in 6C.3 |
|---|---|---|
| Schema | `app_0001`: `rounds` (set-once publication fields), `round_status_history`, `round_snapshots` / `snapshot_fixtures` / `snapshot_offers` (insert-only), `portfolio_drafts`, `your_view_adjustments`, `entries` / `submissions` / `submission_selections` / `entry_events`, `designations` (one `deadline` row per round), the submission deadline trigger, `job_runs`, `audit_log` | Used as designed; no duplicate tables |
| Security | `app_0002`: row-level security on every `app` table, access only for `diski9_app`; nothing for browser roles | New objects follow the same pattern |
| Repositories | `repositories.rounds` (create, status change with history, `FOR SHARE` / `FOR UPDATE` round locks, snapshot insert), `repositories.portfolios` (entries, submissions, optimistic entry update), `repositories.ops` (job runs, advisory job locks, audit) | Extended, not replaced |
| Engine | `challenge.roundsheet` (`RoundSnapshot` with content fingerprint, `build_live_snapshot` from the football store, `assess_round`), `challenge.structured` (`assess_outcome`, `round_opening_report` with the exact 4/3/2 matching, `selection_blocks`, `validate_portfolio`, `evaluate_market_and_model`), `challenge.scoring.classify_round` (≥ 5 valid entries) | Called unchanged; no maths in services or callbacks |
| Auth | `Principal`, `authorize()`, capabilities `analysis.persist_own`, `challenge.submit`, `round.publish`, `jobs.run`; `accounts.lock_snapshot` (name and privacy at lock) | Every service checks the principal; identity only from the server session |
| Your View | `app.lab`: numeric state `{context, cats, manual}`, model-context stamp `goal-model|fixture|home|away`, legacy-note tolerance (D-41) | Same state and stamp stored server-side |
| Prototype state | `app.challenge.state` (browser `ch-session`, draft keys `fixture|market|outcome`, `migrate_draft`, `reconcile`) | Kept for guests; authenticated authority moves to services in Stage F |

### 1.2 Gaps found

1. No service layer for rounds, publication, lock, drafts or Your View
   (repositories only).
2. `portfolio_drafts` and `your_view_adjustments` have **no version column**, so
   an older tab could overwrite newer work (the database design only specifies
   optimistic concurrency for `entries`).
3. No way to tell development rounds from real ones in the database.
4. Snapshot child rows (`snapshot_fixtures`, `snapshot_offers`) are insert-only
   but could still be *added to* after publication.
5. Draft writes after the deadline are only prevented by convention.
6. No round CLI; the only round creation is in test factories.
7. No snapshot loader: a published round cannot yet be rebuilt into the
   engine's `RoundSnapshot`.

### 1.3 Database changes (migration `app_0003`, additive)

| Change | Reason |
|---|---|
| `portfolio_drafts.version int NOT NULL DEFAULT 0` | Optimistic concurrency for drafts (ID-3) |
| `your_view_adjustments.version int NOT NULL DEFAULT 0` | Same protection for Your View across tabs and devices (ID-9) |
| `rounds.is_development boolean NOT NULL DEFAULT false`, set once | Development rounds are distinguishable at the database level (ID-6) |
| Trigger: snapshot fixtures and offers can only be inserted while the round is `draft` | A published snapshot cannot gain rows (immutability) |
| Trigger: a draft can only be inserted or changed while its round is `open` and before `deadline_at` by the database clock | Defence in depth for the deadline (drafts stay readable afterwards) |
| New trigger functions: `EXECUTE` revoked from `PUBLIC`, granted to `diski9_app` | Same boundary as `app_0002` |

No changes to Supabase schemas, the football store, history tables or roles.

### 1.4 Transaction and concurrency boundaries

* **Publish:** one transaction; the round row `FOR UPDATE`; status must be
  `draft`; opening checks, snapshot rows, deadline, settlement cutoff and the
  `open` status are written together, or nothing is.
* **Lock:** one transaction; round `FOR UPDATE` (waits for in-flight
  submissions, which hold `FOR SHARE`); only at or after `deadline_at` by the
  database clock; locks every active confirmed entry, records `valid_entries`,
  the `deadline` designation (`championship` ≥ 5, else `practice`) and the
  status change. A second call finds `locked` and changes nothing.
* **Draft save:** one transaction; round `FOR SHARE`; deadline by
  `transaction_timestamp()`; optimistic version check (`UPDATE … WHERE version =
  expected`, or `INSERT … ON CONFLICT DO NOTHING` for the first save).
* **Your View save:** one transaction; optimistic version check as for drafts.
* The submission deadline trigger from `app_0001` already rejects late
  submissions regardless of when the lock job runs (Stage E builds on it).

### 1.5 Security risks considered

| Risk | Control |
|---|---|
| Client-supplied user ID, bucket, odds or probability | Services take a `Principal` built by the server; drafts store only outcome keys; every value is read from the frozen snapshot |
| Cross-account access | Every query is keyed by `principal.user_id`; no API accepts a user ID; tests attempt cross-account reads and writes |
| Suspended user mid-request | Mutations re-check `users.status = 'active'` inside the transaction |
| Late writes | Database clock in the write transaction; triggers as a second line |
| Development data mistaken for competition data | `is_development` flag, `dev-` code prefix, development commands refuse to run when `DISKI9_APP_ENVIRONMENT=production`, and development snapshots cannot be published into real rounds (and vice versa) |
| Error leakage | Services raise typed errors with user-safe messages; database exceptions are logged, not shown |
| Cross-account caching | Only published snapshots (immutable, shared) are cached per process; nothing private is cached |

### 1.6 Unresolved items

None blocks Stages B–D. Items for the owner at the checkpoint (§6):
frozen versus live Your View context (Owner-1), guest Your View adoption
(Owner-2), and the publication snapshot-age guard (ID-5, adopted unless the
owner objects).

## 2. Stage B — rounds and frozen snapshots

Modules: `diski9.backend.services.rounds`, `diski9.backend.services.snapshots`,
`diski9.backend.devdata`; CLI `diski9 round ...`.

* **ID-1 Round identity.** Live rounds use the code `YYYY-Www-<schedule>` (for
  example `2026-W48-weekend`); the window comes from the schedule's window rule
  (Friday 00:00 UTC to Tuesday 00:00 UTC). Development rounds use `dev-…`.
  The code is the `round_id` inside the snapshot fingerprint, so a published
  snapshot has the same fingerprint as the prototype's live snapshot built for
  the same code, time and inputs.
* **ID-2 Snapshot storage.** `snapshot_fixtures` and `snapshot_offers` hold every
  outcome of the `RoundSnapshot` at full precision (`double precision`
  probabilities; consensus odds are already quantised to 0.01 by the consensus
  layer, so `numeric(8,2)` is exact). `eligible`, `bucket` and
  `ineligible_reason` come from `assess_outcome` at the snapshot time.
  `round_snapshots.feasibility` keeps the opening report, the builder's
  diagnostics and the data source. Loading rebuilds the `RoundSnapshot` and
  **recomputes its fingerprint; a mismatch is refused** (integrity check).
* **Opening checks** are `round_opening_report` unchanged (≥ 15 eligible
  fixtures, ≥ 3 eligible leagues, exact 4/3/2 matching across overlapping
  fixtures, strict odds rules). A refusal leaves the round in `draft` and returns
  the reason from `assess_round` plus the report.
* **Deadline** = earliest kickoff in the published snapshot minus the schedule's
  buffer (15 minutes, D-06), the same rule as the prototype (`RoundSnapshot.deadline`).
  Every snapshot fixture carries a strict-consensus market, so this is never
  later than the earliest eligible kickoff. Publication is refused if the
  deadline is already past by the database clock.
* **Settlement cutoff** = latest kickoff in the snapshot + 48 hours (D-08),
  set once at publication.
* **ID-5 Publication snapshot age (adopted unless the owner objects).** A
  snapshot is published only if its time is no more than one hour before, and
  not after, the database clock. Odds freshness (24 hours) is evaluated at the
  snapshot time, so this keeps that check meaningful at publication. It is an
  operational guard, not a competition rule, and is a parameter.
* **Lock** as in §1.4. Validity at lock is re-checked in SQL (nine selections,
  nine distinct fixtures, 4/3/2 buckets); drafts and withdrawn entries never
  count. The classification uses `challenge.scoring.classify_round` and is
  stored once as the `deadline` designation (T-07, T-11). Settlement is not
  implemented.
* **ID-6 Development rounds.** `diski9 round dev-open` builds a deterministic
  synthetic snapshot (seeded, four leagues, labelled "Development fixtures") with
  kickoffs relative to the current time, creates a `dev-` round with
  `is_development = true` and publishes it through the normal path (all checks
  apply). The command refuses in production. A development snapshot cannot be
  published into a non-development round and vice versa. No live API requests.
* **Authorisation.** Create and publish need `round.publish`; lock needs
  `jobs.run` when a person runs it; the CLI resolves the acting operator by
  verified email (as `diski9 account` does) and the scheduled lock runs as a
  system job (no actor). Every publish and lock writes a `job_runs` row and an
  audit record.

## 3. Stage C — persistent drafts

Module: `diski9.backend.services.drafts`.

* **Ownership:** keyed by `(principal.user_id, round_id)`; capability
  `analysis.persist_own`; active account re-checked in the transaction.
* **Content:** an ordered list of outcome keys `{fixture_id, market, outcome}`
  plus the snapshot fingerprint. Nothing the client says about odds, buckets or
  probabilities is stored or trusted.
* **Validation (no silent changes):** each key must be an outcome of the round's
  frozen snapshot, eligible, on a fixture not already used, in a bucket with
  room, and must not make a 4/3/2 completion impossible
  (`structured.selection_blocks`, the builder's rule). Any failure rejects the
  whole save with per-selection reasons; nothing is truncated or replaced.
  Incomplete drafts (0–9 selections) are allowed.
* **ID-3 Stale-edit handling:** `version` starts at 1 on the first save and
  increases on every change. A save names the version it was based on; if the
  stored version differs, the save is refused with `DraftConflict` carrying the
  latest saved draft, so the page can offer "load the latest saved draft".
  Nothing is merged.
* **ID-4 Idempotency:** a save whose selections equal the stored selections
  writes nothing and returns the stored draft (repeated clicks, callback reruns
  and network retries cause no writes and no false conflicts).
* **Clearing** saves an empty selection list (the row and its version remain),
  so a version number is never reused (no ABA overwrite after a reset).
* **Round boundaries:** a draft belongs to one round; it is never read for
  another round and never carried forward. After the deadline drafts stay
  readable and cannot change (service and trigger); nothing is deleted.
* **Errors:** typed exceptions with short, user-safe messages; the caller keeps
  the participant's unsaved work and can retry.

## 4. Stage D — persistent Your View (D-41, T-10)

Module: `diski9.backend.services.your_view`.

* **Scope:** the current numeric state only — Section B `context`, Section C
  `cats` (squad, fitness, tactics, conditions), Section D `manual` — per
  `(user, fixture)`, with the model-context stamp. No notes, reasons, history or
  new tables. Legacy note fields are dropped on save; the numbers are unchanged.
* **Validation (server-side):** finite numbers within the existing limits
  (Section B ±1.00, each Section C factor ±2.00, manual within the range the
  Match Lab can produce), at most two decimals; unknown factors are refused.
  The limits are the Match Lab constants (a test keeps them identical).
* **Model context:** the caller passes the stamp it computed on the server
  (`app.lab.model_context` for the live Match Lab, or
  `your_view.frozen_context` from a published snapshot). A stored state is
  returned as `active` only when its stamp equals the requested one; otherwise it
  is reported as `incompatible` and **not** returned for use, and it is not
  rewritten by reading. A new adjustment saved in another context replaces it
  (the prototype behaviour), and only with the current version.
* **ID-9 Versioning:** as for drafts; a reset saves zeros (row kept).
* **Privacy:** read and written only for `principal.user_id`; never read by
  rounds, drafts, submission, settlement or leaderboards.
* **Owner-1 (for Stage F, not blocking):** the table holds **one** state per
  user and fixture. The Match Lab today always uses the live baseline; a
  published round has a frozen baseline (`snapshot_fixtures.estimated_goals_*`).
  When the two baselines agree (same rounded estimated goals) one adjustment
  serves both; when they differ, the adjustment applies only in the context it
  was made in, and the other context shows "made against a different model
  baseline" (the existing 6B.3 behaviour). Recommendation: keep one row (no
  schema change) for the MVP; revisit only if participants need separate frozen
  and live adjustments for the same fixture.
* **Owner-2 (for Stage F):** the approved decisions cover adopting a guest
  *portfolio* (T-15); they do not say whether a guest's tab-only Your View
  adjustments may be adopted into the account. Recommendation: offer it inside
  the same explicit keep/discard choice, per fixture, only where the model
  context still matches, never automatically.

## 5. Test coverage (Stages B–D)

Real PostgreSQL (`tests/backend/`): publication success and every refusal
(fixtures, leagues, bookmaker groups, stale odds, overlapping-eligibility
infeasibility, past deadline, wrong source, snapshot age), snapshot immutability
(update, delete, insert after publication), fingerprint equivalence with the
prototype builder and round-trip after a new engine and cleared cache,
full-precision values, deadline and cutoff arithmetic, lock before, at and after
the deadline, idempotent and concurrent lock, four versus five participants,
drafts and withdrawn entries excluded; drafts (create, edit, clear, incomplete,
invalid, duplicate fixture, wrong round, conflict, concurrent saves from two
connections, idempotent retries, after-deadline refusal by service and
trigger, cross-account isolation, suspended account, guest); Your View (round
trip, limits, legacy notes, context compatibility, conflicts, reset, account
isolation, separate engines as "devices"); migration up/down/up and privileges.

## 6. Decisions for the owner at the checkpoint

| ID | Question | Recommendation |
|---|---|---|
| Owner-1 | Frozen versus live Your View context with one row per fixture | Keep one row; apply only in the matching context (§4) |
| Owner-2 | Guest Your View adoption | Explicit, per fixture, matching context only (§4) |
| ID-5 | Publication snapshot-age guard (1 hour) | Keep |

## 7. Checkpoint refinements (approved 19 Nov 2026)

The owner accepted Stages A–D and decided the open items. Owner-1 was decided
the other way from the recommendation (separate contexts); Owner-2 and ID-5 were
approved. Register: D-11 (revised), D-28 (clarified), T-10 and T-15 (refined),
T-18, T-19.

### 7.1 Your View per analytical context (migration `app_0004`)

| Column | Meaning |
|---|---|
| `id bigint` identity | Surrogate primary key (replaces the old key `(user_id, fixture_id)`) |
| `context_kind` | `live` (All Upcoming Fixtures), `round` (a published round's frozen snapshot) or `unassigned` (saved before `app_0004`) |
| `snapshot_id` | Set exactly when `context_kind = 'round'`; foreign key `(snapshot_id, fixture_id)` → `snapshot_fixtures`, so a frozen state can only exist for a fixture on that snapshot |

* **Uniqueness:** `UNIQUE NULLS NOT DISTINCT (user_id, fixture_id, context_kind,
  snapshot_id)`: one live state per user and fixture, one frozen state per user,
  fixture and snapshot. Index `(user_id, snapshot_id)` for loading a round.
* **Server-side context:** `LiveContext(fixture_id, model_context)` takes the stamp
  the server computed from its current data; `RoundContext(round_id, fixture_id)`
  is resolved in the database (snapshot, frozen estimated goals, round model
  version). Nothing about the frozen context comes from the browser.
* **Not a history:** each context keeps only its current numbers; a refit of the
  live model does not create a row (the live stamp changes and the stored state is
  reported `incompatible` until the participant adjusts or resets, as before).
* **Existing data:** rows saved before `app_0004` cannot be told apart (the live
  and frozen stamps have the same format), so they are kept unchanged as
  `unassigned`, never applied and never overwritten (they coexist with new rows;
  deleted with the account). Before this revision no page wrote to the table, so
  in practice only development and test rows exist. **Downgrade** to `app_0003`
  removes frozen rows (that schema cannot hold them) and keeps the most recently
  updated row per user and fixture.
* Development rounds that reuse synthetic fixture IDs have different snapshots,
  so their frozen states never mix.

### 7.2 Guest-work adoption (`services.adoption`)

`plan_adoption` (read-only) classifies the guest draft and each guest Your View
state as `ready`, `same`, `conflict` or `rejected` (with a reason: round closed,
other or earlier round, invalid predictions, model baseline changed, unknown
match, values out of range) and records the account versions it saw. `adopt`
re-runs the checks and writes everything in **one transaction** with those
versions: conflicting account work is replaced only when the participant chose
"replace", otherwise kept; if the account changed in between (`AdoptionStale`) or
any write fails (`PersistenceFailed`), nothing is saved. No entry is ever
created or changed.

### 7.3 Snapshot construction age (T-18)

`DISKI9_SNAPSHOT_MAX_AGE_MINUTES` (server environment, 1–180, default 60;
invalid values are refused). Publication requires construction time ≤ database
time and age ≤ the limit (exactly the limit passes), **and** the unchanged odds
rules at the snapshot time (24 hours, three bookmaker groups) **and** every opening
rule. Loading a published snapshot applies no age rule.

### 7.4 D-11 revision

Schedule `weekend` version 2 (Friday 08:00 SAST) is added by `app_0004`; version
1 gets `active_to` and stays for rounds that reference it. New rounds use the
latest version. Window, deadline and cutoff rules are unchanged. **Scheduling
observation for the owner:** with Friday-evening fixtures (EPL, Bundesliga, La
Liga, PSL often kick off between 19:00 and 21:00 SAST), the common deadline
(earliest kickoff − 15 minutes) leaves roughly 10–13 hours between an 08:00 SAST
publication and the deadline in such weeks, compared with about 35 hours under
the Thursday target. No rule was changed; the observation is reported for review.

### 7.5 Competitive versus official (D-28 clarified, D-38)

The stored designation `championship` is the legacy name for a competitively
classified round. `RoundView.classification` returns `competitive`/`practice`;
`RoundView.counts_toward_official_championship` is always False in 6C.3. Rounds
belong to the `beta` series by default; official membership is derived in 6C.5
and needs the official series and a started Official Championship 1.
Development rounds cannot be placed in the official series (trigger).

### 7.6 Development-fixture isolation

Synthetic fixtures are never written to the football store; their IDs start at
9,000,000,000 (real API fixture IDs are far smaller); development rounds carry
`is_development`, `dev-` codes and a `development` snapshot source, are refused in
production, are hidden from the participant-facing current round unless the
server explicitly enables development rounds outside production, and cannot join
the official series.

## 8. Stage E — confirmed submission lifecycle (`services.entries`)

* **Confirm** turns the participant's **saved draft at the version the page
  showed** into an immutable submission. The server re-derives everything from the
  frozen snapshot: nine outcomes on nine fixtures, buckets 4/3/2
  (`structured.validate_portfolio`), odds, market and model probabilities, the
  fixed credits, and the engine evaluation (`evaluate_portfolio` for market and
  model) stored on the submission (`p_recover_*`, `expected_gross_*`, `max_gross`,
  the eight states). Nothing numerical comes from the client; Your View is never
  read.
* **Replace** is an explicit confirm over an active entry (`replace=True`): a new
  submission version becomes current in the same transaction, earlier versions
  stay (insert-only), `entry_events` records `replaced`. Any failure rolls back
  and the previous version stays current; the draft is kept.
* **Withdraw** clears the current pointer (`state = 'withdrawn'`) with a
  `withdrawn` event; nothing is deleted. **Re-entry** is a new confirm (new
  version, `confirmed` event).
* **Concurrency and idempotency:** round `FOR SHARE` (the lock job's `FOR UPDATE`
  waits, and vice versa), entry `FOR UPDATE` (created with `ON CONFLICT DO NOTHING`
  so two devices can never create two entries), expected entry version, draft
  version, and a per-user idempotency key (the page derives it from its tab and the
  versions shown, so a double click is one submission; reusing a key for different
  content is refused). **The deadline is checked with `clock_timestamp()` after all
  locks are held** (also for drafts and adoption): a request that waited for the
  lock job or another device can never use the transaction start time to slip in
  after the deadline. Found by the multi-connection tests: withdrawal originally
  checked the deadline before waiting for the entry lock (fixed).

## 9. Stage F — application integration

* **Backend mode** (`ChallengeService(backend=...)`, enabled when accounts are
  configured): the live round is the **published round's frozen snapshot**; there
  is no fallback to a snapshot built on the fly. No round, database unavailable,
  deadline passed (lock pending) and locked are explicit states.
  `current_round` prefers an open round whose deadline is ahead, otherwise the most
  recent round past its deadline. Development rounds are shown only with
  `DISKI9_SHOW_DEVELOPMENT_ROUNDS=1`, refused in production.
* **State lifecycle (signed-in participant)** — `app/challenge/persist.py`:
  1. *Hydration* on page load and route change fills the tab copy (`ch-session`)
     from the account (draft, entry, versions), unless the copy holds unsaved
     changes (`acct.dirty`) or unresolved guest work.
  2. *Actions* work on the page's own copy and version (they never pull in
     another device's newer draft); every change to the predictions is saved in the
     same request (`drafts.save_draft` with the page's version and a per-tab
     writer token). "Saved to your account" appears only after the database
     confirmed the write.
  3. *Response ordering:* Dash discards the response of a superseded callback but
     the server still runs it; migration `app_0005` records the writing tab and
     its request sequence so an older request from the same tab arriving late is
     ignored and a newer one may replace it. Other tabs and devices still need the
     current version.
  4. *Conflicts and failures* show a short message with **Load latest saved
     portfolio** or **Try again**; nothing is merged and the page keeps the
     participant's unsaved choice until they decide.
  5. *Sign-out* clears the tab (`Clear-Site-Data` and script, including the
     adoption marker); *account switching* is detected by the owner marker.
* **Match Lab contexts** — `app/lab_context.py`: opened from the Weekly Challenge
  (Screener "Weekly Challenge") on a snapshot fixture → **frozen**: the baseline is
  the snapshot's estimated goals and the probabilities come from Goal Model 1.0's
  own `markets` function; the live calculation details are replaced by a note;
  the bookmaker card is labelled as the latest prices. Otherwise → **live**
  (latest data). Each context has its own Your View in the tab
  (`"<fixture>"` / `"r:<round>:<fixture>"`) and in the database
  (`LiveContext` / `RoundContext`); a reset applies only to the context shown. The
  Weekly Challenge "Your View" probability source uses only frozen-context
  adjustments (`integration.personal_probabilities`).
* **Indicators** (T-19): Screener line above the match list ("Weekly Challenge
  snapshot · Frozen … · Deadline …" with the shared-snapshot note, or "Latest
  available data · Model updated …"); builder status strip (round, status,
  frozen time, deadline) and note; Match Lab context line; review footer; My
  Challenge facts (published, frozen, deadline, classification). All times are the
  stored values, shown in SAST; the snapshot time is never presented as the time of
  each bookmaker quote.
* **My Challenge** distinguishes no round, not started, draft in progress, ready to
  confirm, confirmed, confirmed with unconfirmed draft changes, withdrawn, locked
  (with or without an entry) and the classification once known ("competitive
  round (unofficial beta: no official championship yet)" or "practice round").
  The illustrative championship panel and the Leaderboards stay labelled as
  demonstration data (persistent leaderboards come with settlement).
* **Guests** keep the tab prototype on the published round but cannot confirm a
  real entry ("Sign in to confirm"); the demonstration round is unchanged.
* **Guest-work adoption UI** — `app/challenge/adopt_ui.py`: **Keep** in the
  sign-in dialog marks the review as pending; the page lists what can be saved,
  what differs from saved account work (one choice: keep the account's or replace
  with the guest's), and what cannot be saved with the reason. **Save to my
  account** runs `services.adoption.adopt` (one transaction); **Discard guest
  work** clears it. Found by the browser journeys: the first page after sign-in
  used to replace guest predictions with account data before the choice (fixed).
* **Development round mirroring real fixtures** (`dev-open --mirror-upcoming`):
  real upcoming fixtures and their current estimated goals from the local football
  store with synthetic odds, so the same match exists in both contexts. Real
  fixture IDs are used read-only; the round is still a development round.

## 10. Stage G — final acceptance (19 Nov 2026)

### 10.1 Most recent locked entry (owner-approved UX refinement)

Problem: My Challenge showed only the current round, so once another round was
open a participant could no longer see the entry they had confirmed for a round
whose deadline had passed (while its matches were being played).

* **Service** `entries.latest_locked_entry(engine, principal, exclude_round_id,
  include_development)`: read-only, owner-scoped (the signed-in principal's own
  `entries` row; no user ID from the browser). It returns the most recent round
  (by deadline, database clock) where the participant's entry is **confirmed with
  a current submission** and the deadline has passed (status `open` = lock pending,
  or `locked`/`settling`/`final`). Withdrawn entries have no current submission and
  are never returned. The round already shown as the current round is excluded, so
  an entry is never displayed twice. Values come from the stored immutable
  submission (`submissions` / `submission_selections`), never from a draft.
* **Page** (`pages.locked_entry_card`, via `persist.most_recent_locked`): a compact,
  read-only card titled **Most recent locked entry** below the current round's
  cards: round code (with "Development ·" for dev rounds), status pill
  (**Deadline passed** while the lock job has not run, then **Locked**), deadline,
  frozen-odds time, confirmation time and version, classification once locked, the
  fixed credits (100 virtual: 40 / 30 / 20 / 10), maximum payout, "Results: not
  available yet (settlement comes in a later phase)", the stored Market and Diski 9
  estimates, and an expandable list of the nine predictions with their frozen odds
  (the existing confirmed-predictions component). No buttons; nothing about results
  or payouts is invented. Shown only to signed-in participants; failures hide the
  card rather than showing partial data.
* **Related fix found while testing:** after the deadline, a page loaded afresh
  showed the participant's round as "unavailable" (the builder only chose the live
  round while it was playable), hiding a confirmed entry. In backend mode the
  published round past its deadline is now shown read-only, and the current-round
  card distinguishes **Deadline passed** ("the round is waiting to be locked",
  facts "Changes: none possible (lock pending)") from **Locked**.
* Not built (deferred): full history, search, settlement, results, analytics,
  championship calculations, persistent leaderboards.

### 10.2 Automated regression coverage added in Stage G

| File | What it proves |
|---|---|
| `tests/backend/test_backend_locked_entry.py` (8) | lock-pending then locked status; stored current version (replacement v2, buckets 4/3/2); open round does not hide it; no duplicate of the current round; current-round draft changes leave it unchanged; draft save, replace and withdraw refused after the deadline; withdrawn and never-entered accounts get nothing; owner scope; guests refused; development rounds hidden unless enabled |
| `tests/backend/test_app_persistence.py` (11) | page code on real PostgreSQL: guest work never replaced before the keep/discard choice; unsaved changes survive hydration and saved work is restored in a new tab; a stale device gets a conflict and keeps its own copy, the other device's draft is untouched, "Load latest" brings it in; overlapping saves from one tab keep the newest; account switch clears the other account's work; Match Lab frozen context uses the snapshot baseline, live context the latest data, a fixture outside the round falls back to live; My Challenge locked-entry card (pending → locked text, stored odds, credits, no results, no Withdraw), unchanged by draft changes, not duplicated, absent for withdrawn, never-entered and guest; current round after the deadline says "Deadline passed" until locked |
| `tests/backend/test_backend_schedule_display.py` (5) | SAST conversion (midnight crossing, no DST); stored frozen time and deadline shown as stored; no page hard-codes "Thursday"/"Friday"; an alternative schedule (own window and publication rule) works with the same 15-minute deadline rule while Friday 08:00 SAST stays the default; Friday-evening participation window arithmetic |
| `tests/backend/test_backend_upgrade_paths.py` (3) | fresh install to `app_0005` with schedule v2; upgrade from 6C.2 (`app_0002`) keeps accounts and Your View numbers exactly (row becomes `unassigned`); upgrade from the Stage D checkpoint (`app_0003`) keeps round, draft (version 4), confirmed entry and Your View with no row lost or duplicated; submissions still immutable; downgrade/re-upgrade to each revision keeps data; a new engine reads the same state |

Stage F defects and their durable tests: deadline after lock waits
(`test_backend_entries::test_waiting_for_the_lock_job_cannot_extend_the_window`,
`…another_device…`, `test_backend_drafts::test_waiting_for_another_device_cannot_extend_the_draft_window`);
stale-device handling (`test_app_persistence::test_stale_device…`); guest work
before the decision (`test_app_persistence::test_guest_work…`); open round chosen
over an expired one (`test_backend_rounds::test_current_round_prefers_an_open_round_before_its_deadline`);
overlapping same-tab saves (`test_backend_drafts::test_saves_from_one_tab_are_ordered…`,
`test_app_persistence::test_overlapping_saves…`); separate tabs and devices
(`test_backend_drafts::test_concurrent_saves_from_two_devices`,
`test_backend_entries::test_simultaneous_confirmations_from_two_devices`).

### 10.3 Schedules and times (T-19, D-11 revised)

Friday 08:00 SAST remains the default publication rule (schedule `weekend` v2);
alternative schedules remain supported (`create_round(schedule_code=…)`). The
deadline is always the earliest included kickoff minus 15 minutes. Pages display
stored UTC times converted to SAST (`Africa/Johannesburg`, UTC+2 all year).

**Shorter participation window with Friday-evening fixtures** (reported, no rule
changed): when a round includes a Friday-evening kickoff the common deadline falls
on Friday evening, so publication at 08:00 SAST leaves about 10–13 hours (12 h 45 min
for a 21:00 kickoff; 10 h 45 min for 19:00). Weeks without Friday fixtures keep the
full Friday-to-Saturday window.

### 10.4 Quantitative regression (engines unchanged)

* `git diff 597ed70 HEAD -- src/diski9/challenge src/diski9/screener src/diski9/odds
  src/diski9/db src/diski9/ingestion src/diski9/api_football src/diski9/research`
  is **empty**: Goal Model 1.0, odds/consensus, classification, feasibility,
  accumulator and payout engines, analysis (512-state, conditional), scoring and the
  football database code are byte-identical to the pre-persistence baseline.
* `tools/phase6c3_quant_regression.py` computes on fixed inputs (the frozen
  demonstration pool, 420 outcomes; six deterministic complete portfolios; a Goal
  Model grid of 24 goal-estimate pairs; the demonstration scoring rounds and the
  classification boundaries 0/4/5/6/200 entries with and without cancellation):
  outcome assessments and buckets, the round-opening report, Market and Diski 9
  evaluations (recovery probability, nothing-back probability, expected gross,
  full payout distributions), Your View source evaluation, the 512-state correct-count
  analysis, the calculation breakdown, the application service's cached evaluation,
  Goal Model market probabilities, round scores and championship summary. Run on
  `597ed70` (separate worktree and environment) and on this branch, the 1.47 MB
  JSON outputs are **byte-identical** (SHA-256 `88bcd717deca6c1c…`).
* The engine suites (14 files, 407 tests) pass on both the baseline and this branch.
* Persistence round trips: stored submissions equal the engine's values
  (`test_backend_entries::test_confirmation_stores_snapshot_values_and_engine_evaluation`);
  snapshots round-trip with identical fingerprints at full precision
  (`test_backend_rounds::test_real_pool_round_trips_at_full_precision`).

### 10.5 Database migration and restart checks

The upgrade-path tests above, the existing migration suite (clean upgrade,
downgrade to base, repeat upgrade, mirror agreement, history-table protection,
runtime-role privileges, browser roles) and a real PostgreSQL server restart
(`pg_ctl restart -m fast`) of the browser-journey database: users, drafts,
submissions, confirmed entries, Your View rows, rounds and the snapshot
fingerprints (MD5 of all fingerprints) were identical before and after
(42 / 37 / 19 / 15 / 6 / 8).

### 10.6 Browser acceptance (Stage G)

Journeys A–G (Stage F) still apply; the Stage G code changes touch only My
Challenge and the post-deadline display, so they were not repeated. New:

* **Journey H** (`tools/e2e_6c3/journey_h.js`, run twice, rounds `dev-lock-e2e8`
  and `dev-lock-e2e9`): a participant confirms nine predictions in a 4-minute round;
  after the deadline the mirrored round becomes current and My Challenge shows the
  card **Deadline passed … waiting to be locked**; after `round lock` it shows
  **Locked** and the practice classification; the nine stored odds are all shown;
  the card has no buttons; adding current-round predictions leaves it identical;
  no horizontal overflow at 768 and 390 px; another account sees neither the card
  nor the round code; no page errors.
* **Screenshots** (`tools/e2e_6c3/shots.js`): Weekly Challenge frozen information,
  Screener Weekly Challenge and All Upcoming Fixtures context lines, Match Lab
  frozen and latest headers, My Challenge current round, each at 1360, 768 and
  390 px; no overflow, no page errors; the frozen Your View (1.27 → 1.42) persisted
  across a reload while the live context stayed at 1.27.

### 10.7 Performance (browser end to end and backend)

Browser timings (`tools/e2e_6c3/perf.js`, headless Chromium, same container, same
football data copy, median of 5 runs; Match Lab steps once). An action ends with
the last Dash callback of its continuous chain (Resource Timing; a gap over 1 s
ends it). Configurations: **A** pre-persistence app `597ed70` (prototype,
demonstration round, its odds are stale so only the demo round is playable);
**B** this branch in prototype mode (accounts off, same demo round); **C** this
branch with accounts on, guest, published round `dev-mirror-e2e` (20 fixtures);
**D** the same signed in (persistence active).

| ms (median) | A baseline | B prototype | C guest | D signed in |
|---|---|---|---|---|
| Weekly Challenge load | 440 | 475 | 749 | 1,071 |
| Add prediction | 166 | 174 | 148 | 192 |
| Remove prediction | 151 | 172 | 118 | 178 |
| Screener load | 259 | 287 | 341 | 453 |
| Match Lab open (row click) | 1,588 | 1,512 | 1,624 | 828 |
| Your View adjustment | 580 | 538 | 587 | 631 |
| Your View reset | 566 | 563 | 645 | 665 |
| Context switch (All upcoming) | — | — | 1,153 | 1,796 |
| My Challenge load | 308 | 310 | 315 | 370 |

* **A versus B** (same inputs): equivalent within run-to-run noise — no code
  regression on the prototype path.
* **C/D versus A/B** use a different round (published 20-fixture snapshot versus the
  demonstration pool) and the first row of the Screener differs, so Match Lab and
  context-switch figures are not directly comparable across those columns.
* **D versus C** (persistence cost on the same round): about +320 ms on the Weekly
  Challenge load and +640 ms on the context switch; saves on add/remove are within
  noise (+30–60 ms). Server-side profiling: each signed-in callback first runs the
  Phase 6C.2 session check (`_before_request` → `sessions.resolve`, about 10 ms
  alone, up to about 125 ms when five callbacks run in parallel) and then 30–40 ms
  of persistence reads (draft, entry, Your View context resolution). No repeated
  writes were found: identical saves write nothing (tested), hydration reads only
  on page load or route change.
* **Intermittent outlier, not caused by persistence:** about every 5 minutes (the
  `--ttl 300` default) one request rebuilds the Screener data (bookmaker consensus
  for ~240 fixtures, ~0.9 s alone, ~3 s with concurrent requests waiting); measured
  earlier as 3–4 s loads. Unchanged since the baseline; candidates for later work:
  background refresh. A trailing 4 ms callback ~3.7 s after a guest page load is a
  client-side follow-up and not counted.
* Backend services (Stage F, local PostgreSQL, median of 20): publish 41 ms;
  snapshot load 5.8 ms uncached / 0.3 ms cached; draft save 11.7 ms; Your View save
  2.7 ms; current round 2.4 ms.
* Limitations: one container, local PostgreSQL and local auth on the same host;
  no network latency; small data; no baseline exists for signed-in behaviour
  (persistence did not exist), so D is compared with C.
