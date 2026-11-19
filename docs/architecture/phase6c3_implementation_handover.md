# Phase 6C.3 — Handover (Stage G complete; awaiting owner acceptance)

This document lets Phase 6C.3 resume after context compaction without the
conversation history. Read it with:

* [`phase6c3_implementation.md`](phase6c3_implementation.md): assessment and every
  implementation decision (§§1–9);
* [`../product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md):
  the register (D-, T-series), which takes precedence;
* [`../product/weekly_challenge_phase6c_plan.md`](../product/weekly_challenge_phase6c_plan.md):
  stage plan and notes;
* [`../phase6c3_local_acceptance_mac.md`](../phase6c3_local_acceptance_mac.md): the
  owner's local testing guide;
* the authoritative prompts: the original **Phase 6C.3 implementation prompt**
  (Stages A–G; sections 7–19 on rounds, drafts, Your View, entries, integration,
  testing, performance, documentation, out of scope) and the **checkpoint approval
  prompt** (refinements 2.1–2.7, Stages E–G, final report items 1–23). Their
  requirements are summarised in §8 below.

## 1. Status

| Item | Value |
|---|---|
| Branch | `feature/phase-6c3-competition-persistence` (never merged; no tags; not deployed) |
| Baseline | `feature/match-lab-guidance` `597ed70` (1,158 tests) |
| Checkpoint A–D (accepted) | `96d127c` |
| After the checkpoint | `48e8f04` refinements · `1d5014a` Stage E · `bdace69` Stage F part 1 · `560c37a` Stage F journey fixes · Stage F checkpoint commit (this document; see `git log -1`) |
| Stage F checkpoint | `62a3147` (accepted by the owner, 19 Nov 2026) |
| Stage G | `3e597e7` locked entry, post-deadline display, regression and upgrade tests · final Stage G commit (docs, screenshots, tools; see `git log -1`) |
| Stages | A–G **complete**; Phase 6C.3 awaits the owner's local acceptance (no 6C.4) |
| Owner instruction | stop for product-owner acceptance testing; no merge, tag or deploy |

## 2. Approved decisions in force (do not reopen)

* Competition rules unchanged: 4/3/2 Broad60 buckets at full precision (C-09,
  C-10), credits 40/30/20/10 (C-11), ≥ 15 fixtures, ≥ 3 leagues, exact 4/3/2
  feasibility, strict odds (≥ 3 bookmaker groups, 24 h) (D-28, C-06), deadline =
  earliest snapshot kickoff − 15 min (D-06), settlement cutoff = latest kickoff +
  48 h (D-08), ≥ 5 valid entries for a competitive round (D-28), engines unchanged.
* **D-41**: Your View holds numbers only; no notes, reasons, history, journals,
  attribution, dashboards; Lucy/LiveKit not built.
* **Checkpoint decisions (19 Nov 2026):** Your View per analytical context (T-10
  refined); guest Your View adoption (T-15 extended); construction age one hour,
  separate from odds freshness (T-18); **D-11 revised: Friday 08:00 SAST**
  publication target (schedule v2), not a guarantee; frozen-versus-latest
  communication with stored timestamps (T-19); competitive classification is not
  official championship membership (D-28 clarified, D-38).
* Outstanding: **D-29**, **D-36**; hosted Supabase testing deferred.
* Never: modify the research collector or the odds trial; merge, tag, deploy;
  start Phase 6C.4.

## 3. What is implemented

### 3.1 Migrations (schema `app`, additive; up/down/up tested)
| Revision | Content |
|---|---|
| `app_0003` | `portfolio_drafts.version`, `your_view_adjustments.version`; `rounds.is_development` (set once); snapshot rows only while round is draft; drafts only while open and before `deadline_at` |
| `app_0004` | Your View per context: `id` PK, `context_kind` (`live`/`round`/`unassigned`), `snapshot_id` (FK with fixture to `snapshot_fixtures`), `UNIQUE NULLS NOT DISTINCT (user_id, fixture_id, context_kind, snapshot_id)`; earlier rows kept as `unassigned`, never applied; weekend schedule v2 Friday 08:00 SAST; development rounds never in the official series |
| `app_0005` | `writer_tab`, `writer_seq` on drafts and Your View (same-tab save ordering) |

### 3.2 Services (`src/diski9/backend/services/`)
```text
rounds:    create_round, publish_round(snapshot, source, snapshot_age_limit), lock_round(principal|SYSTEM),
           current_round(include_development), published_snapshot, schedule_window, max_snapshot_age()
           RoundView.classification ('competitive'|'practice'), .counts_toward_official_championship (False)
snapshots: store_snapshot, load_snapshot (fingerprint re-checked), CACHE
drafts:    get_draft, save_draft(selections, expected_version, writer), clear_draft
entries:   get_entry, confirm_entry(draft_version, expected_entry_version, idempotency_key, replace),
           withdraw_entry(expected_entry_version)
your_view: LiveContext(fixture_id, model_context), RoundContext(round_id, fixture_id);
           get_your_view, get_many, save_your_view(..., writer), reset_your_view, write_in, resolved_context
adoption:  plan_adoption, adopt(replace_conflicts) -> AdoptionResult; AdoptionStale
common:    typed user-safe errors, require_active, Writer, save_decision, map_db_errors, cli_principal
```
Every service takes a server-built `Principal`; writes are one transaction with the
database clock; deadlines are re-checked with `clock_timestamp()` after all locks.

### 3.3 Pages (Stage F)
* `ChallengeService(backend=Backend(engine))` when accounts are configured
  (`app.app.competition_backend`): published round only, no on-the-fly snapshot;
  `DISKI9_SHOW_DEVELOPMENT_ROUNDS=1` (refused in production) shows dev rounds.
* `app/challenge/persist.py`: hydration from the account (skips unsaved changes
  and unresolved guest work); actions work on the page copy and version; save in
  the same request; conflict → "Load latest saved portfolio", failure → "Try
  again"; confirm/replace/withdraw via `services.entries` (idempotency key from tab
  and versions); guests cannot confirm real entries.
* `app/lab_context.py` + `app/challenge/lab_persist.py`: frozen versus live Match
  Lab context, baseline, store key (`"<fid>"` / `"r:<round>:<fid>"`) and database
  row; reset per context; Weekly Challenge Your View source uses frozen
  adjustments only (`integration.personal_probabilities`).
* `app/challenge/adopt_ui.py` + `assets/account.js`: Keep → review → Save to my
  account / Discard guest work.
* Indicators with stored times (Screener `data-context`, builder status strip and
  note, Match Lab context line, review footer, My Challenge facts and states).
* CLI `diski9 round list|show|create|publish|lock|dev-open [--mirror-upcoming]`.

## 4. Tests run and results (Stage F checkpoint; Stage G results in §9)

* Backend (real PostgreSQL): rounds, drafts, Your View, refinements (contexts,
  migration of existing rows, adoption, construction age boundaries, Friday
  schedule, dev series, classification), entries (multi-connection races,
  injected failures, deadline after waits), runtime role. All pass.
* **Full suite with the local Supabase Auth server: 1,272 passed, 1 skipped**
  (the skip needs a hosted Supabase `auth` schema, as always). Baseline 1,158;
  checkpoint A–D 1,228.
* Defects found and fixed during Stage E/F: withdrawal checked the deadline before
  waiting for the entry lock; draft saves likewise; actions silently pulled in
  another device's draft; guest predictions overwritten before the keep/discard
  choice; current round chose an expired unlocked round over an open one.

## 5. Browser journeys completed (local, real Supabase Auth, real PostgreSQL `diski9_e2e`)

Scripts: `tools/e2e_6c3/` (README there). All passed with no page errors:

| Journey | Result |
|---|---|
| A returning participant | 4 picks saved; restored after navigation, reload, sign-out/in |
| B cross-device | second device sees the draft; stale device gets the conflict message; "Load latest saved portfolio" shows the other device's draft |
| C lifecycle | confirm → modal; draft edit shows "changes not confirmed"; replace (v2); withdraw; re-enter (v3); DB shows v1–v3, only v3 current |
| D guest adoption | portfolio 9/9 + frozen Your View adopted after Keep → Save; visible on another device; no entry created; with existing account draft: conflict listed, "Keep my account's saved work" kept it |
| E deadline and lock | 5 entries confirmed through the UI; early lock refused; after the deadline Withdraw absent; lock → `championship` (competitive) with 5 valid entries; second lock no change |
| F isolation | account B sees none of A's picks or adjustments in the same tab; A restored |
| G live v. frozen | frozen +0.20 (1.47) and live +0.10 (1.37) coexist; live reset leaves frozen intact; both restored after sign-out/in |

Screenshots (desktop unless noted, `docs/screenshots/phase6c3/`): builder_saved,
builder_conflict, builder_mobile_device2 (390 px), review, confirmed_modal,
my_challenge_changes, my_challenge_confirmed, my_challenge_locked,
withdraw_dialog, deadline_passed, guest_choice, adoption_review,
adoption_conflict, match_lab_frozen, match_lab_live. Note: some screenshots are
scrolled (the Match Lab ones show Sections B–D rather than the header); Stage G
should recapture header views and add tablet and more mobile captures.

Performance measured so far (backend services only, local PostgreSQL, median of 20):
publish 41 ms; snapshot load 5.8 ms uncached / 0.3 ms cached; draft save 11.7 ms
(6.9 ms unchanged); draft read 1.3 ms; Your View save 2.7 ms; Your View for 20
fixtures 1.1 ms; current round 2.4 ms. **Browser before/after measurements not yet
done.**

## 6. Known issues and limitations

* ~~My Challenge shows the current round only~~ — resolved in Stage G by the
  owner-approved **Most recent locked entry** card (T-20); full history stays
  deferred to 6C.5.
* ~~After the deadline a freshly loaded page showed the round as unavailable~~ —
  fixed in Stage G; "Deadline passed" (lock pending) versus "Locked" is asserted by
  `test_app_persistence` and Journey H.
* Screener data refresh (`--ttl`, default 300 s) makes one request every few
  minutes take 1–3 s (unchanged since before 6C.3).
* Typing `/?fixture=<id>` directly does not select the match (the link works only
  inside the app), so the journeys that load that address open the match the
  Screener selects first, not necessarily the one picked (both contexts were still
  exercised and asserted).
* The builder re-renders on round status changes only after the per-process round
  cache (3 s) refreshes.
* Development rounds mirroring real fixtures use real fixture IDs read-only;
  frozen Your View stays separated by snapshot.
* Environment: background commands default to a 30-minute limit (an app server
  was stopped once mid-journey: start servers with the 2-hour limit); the local
  Supabase Auth harness also stops at 2 hours; many test sign-ins reach the real
  rate limit (scripts clear `app.auth_rate_events` in `diski9_e2e` only); several
  short rounds open at once interfere (the earliest open deadline wins).
* Friday publication leaves about 10–13 hours before the common deadline in weeks
  with Friday-evening fixtures (reported; no rule changed).

## 7. Stage G work list (all done; see implementation record §10)

1. **Contextual Your View tests** already covered in backend tests; add an
   app-level test for `lab_context.resolve` (frozen baseline from snapshot, live
   otherwise) and for `persist.has_guest_work`/hydration skip.
2. **Snapshot freshness and scheduling** tests exist (boundaries, future, stale
   odds, Friday default); add alternative-schedule (midweek window rule) and SAST
   display checks if missing.
3. **Quantitative regression** (prompt §13.5 / approval §6.6): compare equivalent
   portfolios before and after persistence (stored submission values = engine
   values — covered in `test_backend_entries.py`), plus Goal Model, market
   probabilities, classification, feasibility, accumulator, expected gross,
   recovery, distributions, conditional outcome analysis, settlement maths — run
   and cite the existing engine suites; confirm serialization precision (covered by
   snapshot round-trip tests).
4. **Database regression** (§6.7): fresh install, upgrade from 6C.2 (`app_0002`)
   and from the checkpoint (`app_0003`) with data preserved, downgrade/re-upgrade,
   restart reconstruction (done manually at the checkpoint; repeat), least
   privilege and browser roles (tests exist).
5. **Browser**: recapture screenshots (Match Lab header in both contexts, Screener
   data-context line, tablet 768 px and mobile 390 px of builder, Match Lab, My
   Challenge, adoption); optionally rerun journeys only if code changes.
6. **Performance** (§6.8): browser timings before (prototype, `597ed70` or guest
   mode) and after (signed-in) for Weekly Challenge load, hydration, add/remove,
   Your View adjustment, context switch, analysis, confirm, replace, My Challenge
   load; inspect callback writes and queries.
7. **Docs**: finalise the implementation record (Stage G section), this handover,
   the Mac guide (already updated for the complete application), register if
   needed; final report with items 1–23 of the approval prompt.
8. Commit, push, verify CI (`.github/workflows/ci.yml`), return the checkout to
   `claude/gifted-newton-h6o5hk`, stop for owner acceptance.

## 8. Resuming: environment and commands (this cloud container)

```bash
mkdir -p /var/run/postgresql && chown postgres /var/run/postgresql
```

```bash
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/diski9-dev -o '-p 5433 -k /var/run/postgresql -c listen_addresses=127.0.0.1' -l /var/lib/postgresql/diski9-dev.log start"
```

Databases on 5433: `diski9_test` (pytest), `diski9_dev`, `diski9_e2e` (browser
journeys; owner bootstrapped; round `dev-mirror-e2e` open until 20 Nov 13:15 UTC).

```bash
.venv/bin/python tools/local_auth/local_auth.py run --gotrue /home/user/supabase/gotrue-v2.198.0
```
(background, 2-hour limit; writes `tmp/local_auth/env`, git-ignored)

```bash
set -a && . tmp/local_auth/env && set +a && DISKI9_APP_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/diski9_test uv run pytest -q
```

```bash
set -a && . tmp/dev/serve.env && set +a && DISKI9_APP_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/diski9_e2e DISKI9_SHOW_DEVELOPMENT_ROUNDS=1 uv run diski9 serve --port 8050
```
(background, 2-hour limit; `tmp/` holds local keys and is never committed)

Odds trial and research collector schedules run independently (see the session
summary in the conversation); do not touch them.

## 9. Stage G results (19 Nov 2026)

Full detail: [`phase6c3_implementation.md`](phase6c3_implementation.md) §10.

* Most recent locked entry (T-20) implemented, read-only, owner-scoped; plus the
  post-deadline display fix.
* New tests: locked entry (8), application-level persistence (11), schedules and
  SAST (5), upgrade paths (3).
* Quantitative regression: engine code byte-identical to `597ed70`; fingerprint
  JSON byte-identical (SHA-256 `88bcd717…`); engine suites 407/407 on both.
* Migration paths (fresh, `app_0002`, `app_0003`, down/up) and a real PostgreSQL
  restart: data identical.
* Browser: Journey H passed twice; 18 header/context screenshots plus 4 locked-entry
  captures at desktop, tablet and mobile; no overflow, no page errors.
* Performance: prototype path unchanged versus the baseline; signed-in overhead on
  the same round about +320 ms on Weekly Challenge load (session check plus
  persistence reads); no repeated writes.
* The final full-suite counts, CI run and commit are in the final report.
