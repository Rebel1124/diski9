# Phase 6C.3 — Checkpoint handover (end of Stage D)

**Purpose:** a durable record of where Phase 6C.3 stands, so work can resume after
the owner's checkpoint review (or after a context reset) without re-deriving
anything. Design and decisions: [`phase6c3_implementation.md`](phase6c3_implementation.md).

## 1. Baseline and branch

| Item | Value |
|---|---|
| Starting baseline | `feature/match-lab-guidance` at `597ed70` (1,158 tests; CI green) |
| Branch | `feature/phase-6c3-competition-persistence` |
| Stage commits | `630dc5d` (Stages A–B), `1c3dc9d` (Stage C), `see git log` (Stage D and docs) |
| Stable release | v4.0.0 on `main` (unchanged) |
| Not done (by instruction) | merge to `main`, release tag, deployment, Stages E–G |

## 2. Completed stages

* **A — assessment:** `phase6c3_implementation.md` §1.
* **B — rounds and frozen snapshots:** create, publish (opening checks, frozen
  snapshot, deadline, settlement cutoff), lock (entry set, valid-entry count,
  `championship`/`practice` designation), development rounds, CLI.
* **C — drafts:** private, versioned, validated against the snapshot, read-only
  after the deadline.
* **D — Your View:** private, numeric only (D-41), model-context checked,
  versioned.

Stages C and D are **backend services with tests**. The Dash pages still use the
prototype's browser-tab state; connecting them is Stage F (approved scope, not
yet authorised).

## 3. Files

| File | Role |
|---|---|
| `migrations_app/versions/app_0003_competition_persistence.py` | Additive migration (§5) |
| `src/diski9/backend/services/common.py` | Typed user-safe errors, `require_active`, `cli_principal`, database-error mapping |
| `src/diski9/backend/services/snapshots.py` | Store and load frozen snapshots; fingerprint check; per-process cache |
| `src/diski9/backend/services/rounds.py` | Round reads, schedule window, create, publish, lock |
| `src/diski9/backend/services/drafts.py` | Draft get, save, clear |
| `src/diski9/backend/services/your_view.py` | Your View get, get_many, save, reset; `frozen_context` |
| `src/diski9/backend/devdata.py` | Deterministic synthetic development snapshots |
| `src/diski9/backend/db/schema.py` | Mirror updated for the new columns |
| `src/diski9/cli.py` | `diski9 round list|show|create|publish|lock|dev-open` |
| `tools/phase6c3_demo.py` | Local demonstration of drafts and Your View (development only) |
| `tests/backend/test_backend_rounds.py`, `test_backend_drafts.py`, `test_backend_your_view.py`, `test_backend_runtime_role.py`, `svc_helpers.py` | New tests (real PostgreSQL) |
| `docs/phase6c3_local_acceptance_mac.md` | Owner's local acceptance steps |

## 4. Service interfaces

All take a server-built `Principal` (never a client user ID) and an `Engine`.

```text
rounds.create_round(engine, principal, *, code, window_start, window_end,
                    schedule_code="weekend", development=False) -> RoundView      [round.publish]
rounds.publish_round(engine, principal, round_id, snapshot, *, source,
                     max_snapshot_age=1h) -> RoundView                             [round.publish]
rounds.lock_round(engine, principal | rounds.SYSTEM, round_id) -> LockResult      [jobs.run]
rounds.get_round / round_id_for_code / list_rounds / current_round / schedule_window
rounds.published_snapshot(engine, round_id) -> RoundSnapshot (cached, immutable)

drafts.get_draft(engine, principal, round_id) -> DraftView                         [analysis.persist_own]
drafts.save_draft(engine, principal, round_id, selections, *, expected_version) -> DraftView
drafts.clear_draft(engine, principal, round_id, *, expected_version) -> DraftView

your_view.get_your_view(engine, principal, fixture_id, context) -> YourView        [analysis.persist_own]
your_view.get_many(engine, principal, {fixture_id: context}) -> {fixture_id: YourView}
your_view.save_your_view(engine, principal, fixture_id, context, state, *, expected_version)
your_view.reset_your_view(engine, principal, fixture_id, context, *, expected_version)
your_view.frozen_context(snapshot, fixture_id, model_version) -> str | None
```

Errors (`services.common`): `NotFound`, `AccountInactive`, `RoundClosed`,
`ValidationFailed(issues)`, `VersionConflict(latest)`, `PublicationRefused(details)`,
`LockRefused`, `SnapshotIntegrityError`, `PersistenceFailed`; plus the existing
`AuthorizationError` family. Each has a user-safe `message`.

## 5. Database and transaction decisions

* `app_0003` (additive): `portfolio_drafts.version`, `your_view_adjustments.version`,
  `rounds.is_development` (set once), snapshot rows insertable only while the
  round is `draft`, draft writes only while `open` and before `deadline_at`
  (database clock), `EXECUTE` on the new functions revoked from `PUBLIC` and
  granted to `diski9_app`. Downgrade reverses it; up/down/up tested.
* Publish and lock each run in one transaction holding the round row
  `FOR UPDATE`; drafts take the round `FOR SHARE`; versions use
  `UPDATE … WHERE version = :expected` and `INSERT … ON CONFLICT DO NOTHING`.
* Deadline = earliest snapshot kickoff − 15 minutes; cutoff = latest kickoff +
  48 hours; both set once at publication.
* No schema change for Your View contexts (one row per user and fixture; see
  Owner-1).

## 6. Tests and CI at the checkpoint

Local, full suite with the genuine Supabase Auth server running: **1,228 passed,
1 skipped** (the skip needs a database holding a hosted Supabase `auth` schema, as
before). Baseline at `597ed70`: 1,158. New: 28 (rounds) + 19 (drafts) + 21 (Your
View) + 3 (runtime role and browser roles) = 71 backend tests, all on real
PostgreSQL; the migration and health tests now expect `app_0003`.

Measured service times (local PostgreSQL 16, median of 20, while other tests ran):
publish 41 ms (20 fixtures, 140 offers); snapshot load 5.8 ms uncached, 0.3 ms
cached; draft save 11.7 ms (6.9 ms when unchanged, no write); draft read 1.3 ms;
Your View save 2.7 ms; Your View for 20 fixtures 1.1 ms; current round 2.4 ms. The
page-level before/after comparison belongs to Stage F/G, once pages call these
services. Lint and
formatting clean. CI: `.github/workflows/ci.yml` unchanged (PostgreSQL 17,
genuine Supabase Auth, migrations up/down/up).

## 7. Outstanding

* **Owner decisions:** Owner-1 (frozen versus live Your View context), Owner-2
  (guest Your View adoption), ID-5 (publication snapshot-age guard) — see
  `phase6c3_implementation.md` §6. D-29 and D-36 remain outstanding and do not
  block.
* **Known limitations:** pages not yet connected (Stage F); no confirmation
  service yet (lock tests insert entries through repositories); development
  fixture IDs repeat between development rounds with the same seed (so Your View
  for a development fixture carries over between such rounds; real fixture IDs
  are unique); database-restart reconstruction is covered by a new engine and
  cleared cache in tests and was checked manually by restarting the local
  PostgreSQL server.
* **Untouched:** quantitative engines, competition rules, authentication code,
  football store, research collector, odds trial.

## 8. Local testing

[`docs/phase6c3_local_acceptance_mac.md`](../phase6c3_local_acceptance_mac.md).

## 9. Remaining scope (Stages E–G, after approval)

* **E — confirmed submissions:** `services/portfolios.py`: confirm (server-side
  validation from the snapshot, engine evaluation stored on the submission,
  idempotency key), replace (atomic, new version, prior kept), withdraw (explicit,
  `entry_events`), re-entry; concurrency tests with multiple connections
  (double confirm, confirm v. withdraw, confirm v. lock, replace v. replace).
  The lock already counts only active confirmed entries.
* **F — pages:** hydrate the Weekly Challenge builder, My Challenge and Match Lab
  from the services for signed-in users (browser stores only for UI state);
  frozen versus live contexts per Owner-1; save, loading, conflict and deadline
  messages; guest draft adoption (T-15) and Owner-2; remove prototype-only
  disclaimers where persistence is real.
* **G — acceptance:** journeys A–F in real browsers (desktop and mobile),
  screenshots under `docs/screenshots/phase6c3/`, quantitative regression
  comparisons, performance before and after integration, final report.
