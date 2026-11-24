# Weekly Challenge Scenario A3 — implementation record

**Owner decision (approved after independent review):** Scenario A3, configuration
version `a3-432-v1`: Foundation 60%–90% (both ends included), Balanced 40% to under 60%,
Challenger 10% to under 40%, by margin-adjusted market probability. Unchanged:
* 4 / 3 / 2 selections on nine distinct fixtures;
* the nine-fold and 40 / 30 / 20 / 10 credits;
* D-31 scoring;
* consensus and quote rules;
* the D-28 opening checks;
* the existing bucket completion probabilities.

Approved alongside: general Goal Model guidance, and a high-risk underdog warning for a
**selected** outcome whose market-implied probability is 10% to under 20%. Migration
`app_0008` is accepted in principle as the activation mechanism but **not authorised for
execution**. Evidence:
[`../research/weekly_challenge_bucket_review.md`](../research/weekly_challenge_bucket_review.md).

| Checkpoint | Scope | Status |
|---|---|---|
| R | Research preservation | done (`b01e057`, CI run 145 passed) |
| 1 | Version-aware application; `broad60-432-v1` stays the only configuration | done (`1767c8d`, CI run 146 passed) |
| 2 | Register `a3-432-v1` (inactive) | done (`30f4f28`, CI run 147 passed) |
| 3 | Guidance, warning and educational popovers | done (`fa1307a`, CI run 148 passed) |
| 3.1 | Minor UI refinements (target size, legend wrapping, Reference Odds) | done (`66c37f6`, CI run 149 passed) |
| 4A | Schedule-aware application (no migrations) | conditionally accepted (`38cb0e1`); local verification only, full CI deferred to 4C |
| 4B | Database schedule safeguards (`app_0008`) | this record (section below); targeted local verification, full CI deferred to 4C |
| 4C | Controlled activation (`app_0009`, approved UTC timestamp, default switch) | not started; no timestamp approved |
| 5 | Final verification | not started |

## Checkpoint 1: version-aware application

**Rule:** every round, snapshot, draft, entry and settlement resolves the configuration
it is bound to. Production code never falls back to `DEFAULT_CONFIG` for them.

| Resolver | Use |
|---|---|
| `RoundSnapshot.config` | `get_config(snapshot.config_version)`; unknown versions raise `ConfigError` |
| `rounds.round_config(conn, round_id)` | the version recorded at publication, else (draft) the version of the round's **own** schedule row |
| `rounds.schedule_config(conn, code)` | what a round created now would use (same selection as `create_round`, via `_current_schedule`) |
| `get_config(entry["config"])` (`pages.entry_config`) | stored entries (confirmed and locked cards) |
| `REQUIRED_SELECTIONS`, `TOTAL_CREDITS` | validated invariants of every configuration (9 selections, 100 credits) |

### Audit of `DEFAULT_CONFIG` dependencies

| Area | Before | After |
|---|---|---|
| Backend services (rounds, entries, drafts, snapshots) | already round-aware | unchanged; `drafts.validate_selections` now **requires** a configuration |
| Draft adoption (`adoption.py`, 2 calls) | default | the published snapshot's configuration |
| Settlement (`settlement.py`) | `settle_entry` default | the round's `config_version`; `EntrySettlement` records the recovery target |
| Prepare job (`jobs/prepare.py`) | `build_live_snapshot` default | the draft's own configuration (`round_config`), passed to the snapshot builder |
| CLI `round readiness` / `publish` (`cli.py`) | default | `round_config` |
| CLI `round dev-open`, dev championship, F2 e2e tool | default | `schedule_config` (what `create_round` binds the new round to) |
| Dev data (`devdata.py`) | labelled with the default | optional `config`; the default applies only to free-standing synthetic data |
| Settlement scenarios (`settlement_scenarios.py`) | default | the snapshot's configuration |
| Dash builder, fixture list, outcome states, tracker, analysis, review, confirm (`pages`, `callbacks`, `service`, `persist`, `state`, `integration`) | `DEFAULT_CONFIG` / `CFG` | the snapshot's configuration. Confirmation no longer compares with the default; an unknown version is refused |
| Band labels and eligibility messages (`components`, `callbacks`) | hard-coded "60%–95%", "20%–95%" | derived from the configuration (`band_text`, `eligible_range_text`) |
| Confirmed and locked entry cards; results panel (`pages`, `results_ui`) | default | the entry's stored version, and the stakes from its frozen settlement |
| State labels (`charts`, payouts section) | default | bucket names carried by the evaluation (from the portfolio's configuration) |
| Phase 6C.3 tools (`phase6c3_demo.py`, `phase6c3_quant_regression.py`) | default | the snapshot's configuration |

### Remaining legitimate default uses (allowlisted in `tests/test_config_version_guard.py`)

| Where | Why |
|---|---|
| `challenge/config.py` | the definition |
| Library default parameters (`structured.py` ×7, `analysis.py` ×2, `settle.py`) | pure functions keep their defaults for tests and research; every production call passes a configuration (guarded) |
| `roundsheet.snapshot_from_research_pool` / `build_live_snapshot` defaults | constructing a **new** snapshot with no round; production callers pass one (guarded) |
| `education.illustrate` | free-standing illustration, not tied to a round |
| `devdata.dev_snapshot` / `mirror_snapshot` | free-standing synthetic data; round-creating callers pass `config=` (guarded) |
| `app/challenge/service.py` (×2) | the prototype live snapshot and the demonstration round: new snapshots with no round record |
| `pages.rules_config` | explanatory text when no round exists at all |

**Guard:** `tests/test_config_version_guard.py` fails if:
* a new `DEFAULT_CONFIG` reference appears outside the allowlist;
* `DEFAULT_CONFIG` is imported under an alias;
* a production call relies on a default `config` argument;
* a registered configuration renames a bucket (presentation uses static bucket names).

### Verification (Checkpoint 1)

* v1 behaviour unchanged:
  * the `broad60-432-v1` fingerprint is identical before and after (and pinned in a test);
  * 17 Weekly Challenge views rendered for the demonstration round are byte-identical
    before and after (builder, fixture list, outcome states, tracker, analysis, review,
    how to play, round facts, confirmed and locked cards, ineligible-outcome text);
  * the Phase 6C.3 quantitative regression output (1.47 MB) is byte-identical.
* Fail-safe: unknown snapshot, round, schedule or entry versions raise `ConfigError`.
  The published-round loader already refuses unregistered versions ("temporarily
  unavailable").
* Draft binding (PostgreSQL): a draft keeps its schedule row's configuration after a
  newer schedule version exists, and publishes normally with a snapshot built for it. A
  snapshot for another configuration is refused.

## Checkpoint 2: `a3-432-v1` registered (inactive)

* `A3_432_V1` is registered next to `BROAD60_432_V1`; `DEFAULT_CONFIG` is still v1 and
  the only scheduled configuration (`weekend` unchanged).
* Fingerprints:
  * `broad60-432-v1`: `b8cb7c0372e6aac15b1638e100be35955dacfd3f11c1f3654ad52c9263cbba94`
    (unchanged);
  * `a3-432-v1`: `91dba48a002a4fed3dc340764ef1717228f7dea61401f29621e799de401b094e`.
* A3 differs from v1 only in its version and two bands: Foundation `[0.60, 0.90]` and
  Challenger `[0.10, 0.40)`. Balanced `[0.40, 0.60)`, 4/3/2, credits, the nine-fold, D-28,
  odds rules and market-only classification are identical (tested on the canonical form).
* `tests/test_challenge_a3.py` covers:
  * exact boundaries with adjacent floats (`math.nextafter`);
  * a sweep of 0.10–0.90 in 0.00001 steps (exactly one bucket each);
  * exclusions below 10% and above 90%;
  * D-28 opening and distinct-fixture matching, including a pool feasible only through
    the new Challenger outcomes;
  * the committed real pool;
  * version coexistence in the application paths;
  * the historical v1 settlement regression.
* **Real pool (reproduced exactly):** Challenger outcomes / fixtures go from 128 / 57 to
  164 / 60 (20–23 Nov) and from 65 / 29 to 74 / 29 (27–30 Nov). The additions are exactly
  the 10%–20% outcomes; eligible fixtures, leagues and D-28 opening are unchanged.
* **Historical v1 settlement regression:**
  * `tests/fixtures/challenge/v1_settlement_regression.json` was generated by the
    **pre-A3 code** (commit `b01e057`) with
    `tools/a3_v1_settlement_regression.py`: 12 portfolios from the committed pool,
    9 verdict vectors each, confirmation states (market and model) and a D-31 round;
  * the current code reproduces it exactly (the generator also gives byte-identical output
    on both commits);
  * portfolios valid under both configurations (all 12; the pool has no outcome above 90%)
    settle identically under A3 using their frozen v1 buckets: no reclassification.

## Checkpoint 3: guidance, warning and educational popovers

Presentation only. No calculation, eligibility, scoring, settlement or configuration
changes; A3 stays inactive and `DEFAULT_CONFIG` is still `broad60-432-v1`.

### Architecture

| Module | Content |
|---|---|
| `src/diski9/app/education.py` | the central glossary (`GLOSSARY`: title, approved short definition, the longer existing explanation); `info()` (the existing native `<details>` popover, moved from `views`, which re-exports it); `term(label, *keys)`; the guidance and warning text; `model_guidance(where)`; `underdog_panel(picks, where)` |
| `src/diski9/challenge/guidance.py` | the pure warning rule: `HIGH_RISK_UNDERDOG = [0.10, 0.20)`, `is_high_risk_underdog`, `high_risk_selections`. Outside the configuration and its fingerprint |
| `assets/diski9.js`, `assets/style.css` | positioning and style for the new `.term-info` popovers only; the existing popovers are unchanged |

The Match Lab's longer explanations (`lab.MODEL_PROB_HELP` and the others) now come from
the glossary, so each concept has one source.

### Placements (one explanation per concept per view)

| View | What |
|---|---|
| Weekly Challenge builder | `Mkt` and `D9` terms in the legend; "Understanding Model Probabilities" collapsed below it |
| Final review | `Market` and `Diski 9` column headings; the warning reminder above the picks table |
| Match Lab model-versus-market table | `Model`, `Market`, `Edge` and `EV` headings; the guidance (Match Lab wording: "review the match factors on this page") |
| Screener | one term on "Rank by" covering Edge and EV |
| Outcome card | a small "High risk" tag (only on eligible 10%–20% outcomes; the card title carries the explanation) |
| Tracker | one warning panel in the Challenger section for all selected high-risk underdogs |

No icons in repeated cells or cards apart from the targeted warning tag.

### Warning rule

The selected outcome's own margin-adjusted market probability is in `[0.10, 0.20)` **and**
the outcome is eligible under the round's configuration (`assess_outcome(..., round
config)`). Never fixture-level, never the model probability, no acknowledgement and never
a block. Under `broad60-432-v1` such outcomes are ineligible, so the warning cannot appear
on today's rounds. Several qualifying picks give one panel ("Includes 2 high-risk
underdogs"), each with its existing Match Lab link. The standalone Match Lab shows only the
general guidance, never the Weekly Challenge warning, so general guidance and challenge
eligibility stay separate.

### Verification

* `tests/test_a3_guidance.py` (25 tests):
  * the approved wording, verbatim;
  * the glossary as the single source;
  * the definitions against the calculations (normalisation; 55% vs 48% = +7.0 pp;
    0.55 × 2.10 − 1 = 0.155);
  * warning boundaries with adjacent floats (just below 0.10 no; 0.10, 0.15 and just
    below 0.20 yes; 0.20 no);
  * the market probability drives it, not the model;
  * eligibility (v1 round and stale quotes: no warning);
  * selected outcomes only, deduplicated;
  * select and deselect (2 → 1 → none, one panel);
  * review once, collapsed, with no acknowledgement;
  * tags only on eligible high-risk cards;
  * guidance and terms once per view;
  * both fingerprints unchanged.
* `tests/test_a3_guidance_browser.py` (Playwright) runs on desktop 1366 × 900 with the
  mouse, iPad Mini with the keyboard (focus, then Enter) and iPhone 13 with touch. It checks
  the builder, guidance, tracker warning, select and deselect, review, Screener and Match
  Lab. For every popover:
  * it opens;
  * it lies fully inside the viewport, including the four inside the horizontally
    scrolling Match Lab table;
  * only one is open at a time;
  * Escape closes it and returns focus to its button.

  Every view also has no horizontal page overflow and no page errors. The demonstration
  round is built under the registered `a3-432-v1` by a test-only patch; nothing is
  activated.
* Regression: the existing Weekly Challenge, Match Lab, market value, app and
  configuration-guard suites pass unchanged; the historical v1 settlement regression
  still reproduces exactly.
* Screenshots: `docs/screenshots/a3_cp3/` (desktop, tablet and phone; popovers closed and
  open; builder, guidance, tracker warning closed and open, review, Screener, Match Lab).

### Accessibility findings

| Concern | Result |
|---|---|
| Hover dependence | none: native `<details>`/`<summary>` opens with click, Enter/Space and tap |
| Name | each button has an aria-label ("What is Market Probability?") |
| Focus | visible `:focus-visible` outline; Escape closes and returns focus; a click outside closes |
| Touch target | 24 × 24 CSS px since Checkpoint 3.1 (was 22 × 22), in headings and legends only |
| Narrow tables | on phones (≤ 480 px) a heading's button sits under its label, so the Match Lab model-versus-market table keeps every column visible without scrolling. The first full run caught a 22 px overflow here (existing `test_browser_value_rankings_and_lab`); fixed in CSS, test unchanged |
| Clipping | `.term-info` popovers use fixed positioning, clamped 12 px from the screen edges, width `min(320 px, screen − 24 px)`, opening above when there is no room below. They escape the `.scroll-x` table container |
| Colour | the warning uses the existing warn colour plus an icon and text, never colour alone; the card tag icon is `aria-hidden` and its meaning is in the card title |
| Warning semantics | `role="note"`, not an alert: it informs and never interrupts |

Known minor point: on narrow phones the builder legend can wrap between a term's button and
the colon that follows it. It is readable and unchanged in meaning.

## Checkpoint 3.1: minor UI refinements

Presentation only. One educational concept is added (Reference Odds); everything else is
the same as Checkpoint 3.

| Change | Detail |
|---|---|
| Target size | `details.term-info > summary` is 24 × 24 CSS px (was 22 × 22). The visible 22 px circle is unchanged (drawn by `::before`), so the look, hover and open colours stay the same |
| Legend grouping | `term(..., suffix=":")` wraps the label, button and colon in `.term-keep` (`white-space: nowrap`), used for `Mkt` and `D9`. The rest of the legend wraps normally |
| Reference Odds | glossary entry `reference_odds` with the approved definition; the longer explanation is the existing `lab.ODDS_SOURCE` text, which now comes from the glossary. The Match Lab "Odds" heading uses `term()` like Model, Market, Edge and EV; Outcome has none |

**Definition check.** `diski9.odds.consensus`:
* counts each qualifying independent bookmaker group once; qualifying means fresh,
  eligible, non-exchange and complete market, and a group is represented by its most
  recently observed bookmaker;
* takes the median of those prices, rounded half-up to two decimals;
* documents the result as reference values, not offers.

This matches "decimal odds derived from the median odds across qualifying independent
bookmaker groups". Two details the short definition leaves to the existing longer
explanation and table notes:
* the Match Lab can show a stale consensus, labelled stale, computed by the same rules at
  an earlier retrieval;
* displaying odds needs one source, while Challenge eligibility needs at least three.

**Measured (Playwright, all three viewports):**

| | Before | After |
|---|---|---|
| Rendered target, all 10 buttons (legend 2, review 2, Screener 1, Match Lab 5) | 22 × 22 | 24 × 24 |
| Match Lab table overflow on phone (`scrollWidth − clientWidth`) | 0 | 0 |
| Narrowest gap between adjacent buttons on one line (phone Match Lab) | 28.8 px (4 buttons) | 16 px (5 buttons) |
| Legend groups split across lines, 320–480 px sweep (8 widths) | no grouping existed; the D9 colon wrapped onto the next line at 390 px (Checkpoint 3 phone screenshot) | 0 at every width |
| Match Lab heading buttons: vertical spread / offset from the right edge | — | 0 px / 0 px |

`tests/test_a3_guidance_browser.py` now asserts:
* every target is at least 24 × 24 and no two overlap;
* the Match Lab table fits on every viewport, with five aligned heading buttons;
* the legend groups never split and the legend never overflows at eight widths from 320
  to 480 px, while still wrapping on phones.

`tests/test_a3_guidance.py` checks:
* the approved Reference Odds wording;
* that the glossary holds only the five authorised entries;
* the `suffix` grouping;
* the five Match Lab terms.

Test robustness: one full local run had a single intermittent failure of the Weekly Challenge browser test (2,126 passed; the error text was not captured). It did not reproduce in isolation, under full CPU load or in a second full run (2,127 passed). Fixed pauses (150–350 ms) before reading popover and selection state were replaced by waits for the expected state (`until()`). The assertions are unchanged.

Screenshots: `docs/screenshots/a3_cp3_1/` (builder legend and Match Lab table on desktop,
tablet and phone, with popovers closed and open, including Reference Odds).

## Checkpoint 4A: schedule-aware application

Owner decisions applied:
* selection by round-creation time, half-open validity `[active_from, active_to)`;
* one database timestamp and one schedule row per creation;
* no match or several matches refuse; never the latest version.

No migration, schedule or configuration change. `DEFAULT_CONFIG` is still
`broad60-432-v1` and the application works against `app_0007`.

### Resolution and transaction design

| Piece | Behaviour |
|---|---|
| `services/schedules.schedule_at(conn, code, at)` | the single row of `code` with `active_from <= at < active_to` (NULL `active_to` = open-ended); none or several raise `ScheduleUnavailable`; naive datetimes are refused; the comparison runs in PostgreSQL on `timestamptz` |
| `schedules.current_schedule(conn, code)` | `schedule_at` at `transaction_timestamp()`, the same instant `rounds.created_at` receives in the same transaction |
| `rounds.create_round(..., expected_schedule_id=None)` | binds to `current_schedule` in its own write transaction; if the caller planned with another row, `ScheduleChanged` is raised and nothing is written |
| `rounds.create_scheduled_draft` | window, series check and binding from one `current_schedule` row in one transaction |
| `rounds.plan_window` / `schedule_window` | window from the row valid now, with its id (CLI `round create` passes it as `expected_schedule_id`) |
| `rounds.schedule_config` | configuration of the row valid at the transaction timestamp |
| `prepare.load_schedule` | `current_schedule` at the real database clock: the row a draft created now binds to (the test seam `_now` still drives week decisions) |
| `dev_championship.opening_parameters` | deadline buffer **and** configuration from the same row, whose id is then pinned in `create_round` |
| CLI `round dev-open`, `tools/e2e_6c5/f2_current.py` | configuration from the resolved row, id pinned in `create_round` |
| `repositories.rounds.schedule_id` (test helper) | an explicit version, or the row valid now |

Paths that plan in one transaction and create in another (CLI, dev championship, F2
tool) pin the planned row id. A boundary passing in between is refused instead of
producing a round whose snapshot or window came from another row. Publication still
uses the round's own row, and still refuses a snapshot built for another configuration.

### Demonstration round, prototype and rules text

* With a competition database: `ChallengeService.rules_config()` returns the
  configuration of the `weekend` row valid now (`Backend.schedule_config`). It is
  cached until the earlier of that row's `active_to` and 30 seconds, so a boundary is
  followed exactly once the new row exists.
* The demonstration round is built under that configuration and rebuilt when it
  changes. "How to play" with no round uses it.
* A real round always uses its own configuration.
* Errors (database unavailable, no or overlapping schedule, unregistered
  configuration) raise `ScheduleConfigUnavailable`:
  * the demonstration round shows "temporarily unavailable";
  * the rules text shows a notice instead of another configuration's rules.
* Without a competition database (prototype mode only), `DEFAULT_CONFIG` applies.
* The "This round" credits line uses the `TOTAL_CREDITS` invariant (100 under every
  configuration).

### Read-only inspection and readiness reporting

`diski9 round schedules [--schedule CODE] [--at ISO8601Z] [--json]` (no sign-in, writes
nothing) lists for each code:
* every version with its validity interval and whether it is valid now;
* its configuration, and whether that configuration is registered in this build
  (with its fingerprint prefix);
* rules, scoring, series and deadline buffer;
* the row selected now and at `--at`.

A timestamp without a UTC offset is refused.

`ops status` / `jobs status` (preparation lines) now show the configuration the
week's round is bound to: frozen at publication, bound at creation, or applying when
the draft is due. When a different row takes effect before the publication target,
a note explains it:
* for a draft that already exists: "this draft was created under weekend vN (…)
  before weekend vM (…) takes effect at T; it keeps vN and will publish under the
  original rules";
* for a draft not yet created: "… takes effect at T, after this draft is due; the
  draft will be bound to vN and publish under its rules".

### Default dependency audit

* `DEFAULT_CONFIG` production references (allowlist in
  `tests/test_config_version_guard.py`):
  * the definition;
  * library defaults: `structured` ×7, `analysis` ×2, `roundsheet` ×2;
  * `devdata` ×2 (free-standing synthetic data);
  * `education.illustrate`;
  * `service` ×2 and `pages` ×1, now reached **only when no competition database is
    configured**.
* `settle.py` no longer has a default.
* **`settle_entry` now requires `config`.** Its production caller (`services/settlement`)
  and the regression tool already passed it, so there is no production compatibility
  change. Six test calls were updated: five pinned to v1, and one security test now
  uses its round's `config_version`.
* Tests intended to exercise v1 rules:
  * 69 implicit-default calls in 12 files, plus explicit `DEFAULT_CONFIG` inputs in
    `settle_helpers`, `test_backend_rounds`, `test_backend_drafts` and
    `test_settle_entry`, now pass `BROAD60_432_V1` explicitly;
  * snapshot-bound helpers (`svc_helpers.valid_keys`, one entries assertion, one rounds
    assertion) use the snapshot's own `snap.config`;
  * assertions are unchanged.
* New guards:
  * `settle_entry` has no default;
  * no production or tool code orders schedule rows, limits them, or selects them
    without the bound id (checked against the previous commit: it flags all five old
    paths);
  * the resolver contains no latest-version fallback.

### Verification (local; full CI deferred to Checkpoint 4C)

* `tests/backend/test_backend_schedule_resolution.py` (PostgreSQL, synthetic codes),
  covering:
  * the boundary one microsecond before, at and after;
  * other UTC offsets, with the session time zone set to Pacific/Auckland;
  * naive instants refused;
  * no valid row, overlapping rows and a gap all refused, with nothing written;
  * the bound row valid at `created_at`;
  * a real boundary passing between two creations, where the pre-boundary draft keeps
    broad60 and publishes under it afterwards;
  * `expected_schedule_id` mismatch refused;
  * planned-window identity;
  * the scheduled draft's single-row binding and its refusal;
  * the dev championship buffer from the bound row (the first table row differs);
  * the inspection report and command, including the naive `--at` refusal;
  * prepare binding notes;
  * `Backend.schedule_config` following a real boundary exactly, and never falling
    back (unregistered configuration, no schedule, unreachable database).
* `tests/test_schedule_following_app.py`: the default only without a database; the
  demonstration round and rules follow the schedule and rebuild on change; a real
  round keeps its own configuration; errors show "unavailable" and recover.
* Historical regressions:
  * the v1 settlement regression generator output is byte-identical to the committed
    pre-A3 fixture;
  * the Phase 6C.3 quantitative regression is byte-identical between `66c37f6` and
    Checkpoint 4A (1,473,435 bytes; sha256 prefix `88bcd717deca6c1c`);
  * both fingerprints are unchanged.

### Limitations carried to Checkpoint 4B

* Overlaps and gaps are detected only when a row is resolved; the database does not
  prevent them yet.
* `rounds.schedule_id` and `rounds.created_at` can still be updated by the runtime
  role (only the foreign key protects `schedule_id`).
* No validity check at round insertion for writers outside these services. Several
  test fixtures insert rounds directly bound to the first schedule row.
* No coordination between round creation and a concurrent schedule change beyond
  the atomicity of each transaction (see the 4B plan below).

## Checkpoint 4B preparation (planning evidence only; nothing implemented)

1. **Historical consistency.**
   * Fresh databases: `weekend` v1 `[2026-11-19T00:00Z, t4)` and v2 `[t4, ∞)`, where t4
     is the `app_0004` migration time (one `now()`, so contiguous). They are
     consistent.
   * Protected databases were **not** inspected. Run this read-only audit there before
     installing guards (it lists rows that would violate them):
     ```sql
     -- rounds whose schedule row was not valid at their creation
     SELECT r.code, r.created_at, s.code AS schedule, s.version, s.active_from, s.active_to
       FROM app.rounds r JOIN app.round_schedules s ON s.id = r.schedule_id
      WHERE NOT (s.active_from <= r.created_at
                 AND (s.active_to IS NULL OR r.created_at < s.active_to));
     -- overlaps within a code
     SELECT a.code, a.version, b.version FROM app.round_schedules a
       JOIN app.round_schedules b ON a.code = b.code AND a.version < b.version
      WHERE tstzrange(a.active_from, a.active_to, '[)') && tstzrange(b.active_from, b.active_to, '[)');
     -- gaps and open-ended rows per code
     SELECT code, version, active_from, active_to,
            lead(active_from) OVER (PARTITION BY code ORDER BY version) AS next_from
       FROM app.round_schedules ORDER BY code, version;
     ```
   * A likely finding: rounds created before `2026-11-19T00:00Z` (v1's seeded
     `active_from`), if any were made in development before that date. They would
     need an owner decision: a documented exemption, or a corrected v1 `active_from`.
   * Test fixtures that need changing in 4B:
     * the direct round inserts bound to `ORDER BY id LIMIT 1` (`test_backend_weekly_results`,
       `test_backend_championship_repair`);
     * the 4A overlap and gap tests, which become "the database refuses" tests;
     * the `test_backend_config_binding` helper (it already closes the previous row).
2. **Runtime schedule writes:** none in `src` or `tools`. Writes happen only in
   migrations and tests (test engine, owner role). Revoking INSERT, UPDATE and DELETE
   on `round_schedules` from `diski9_app` changes `test_runtime_role_privileges` only.
   Note: `SELECT … FOR SHARE` needs UPDATE privilege, so coordination must not rely on
   row locks once UPDATE is revoked.
3. **Concurrency and locking proposal:**
   * Schedule changes (migrations) take an exclusive transaction-level advisory lock
     (`pg_advisory_xact_lock(hashtextextended('diski9.round_schedules', 0))`).
   * Round creation takes the shared form (`pg_advisory_xact_lock_shared`) before
     resolving. Advisory locks need no table privilege, and creators never block each
     other.
   * The `EXCLUDE USING gist` constraint is concurrency-safe by itself. The no-gap rule
     is a deferred constraint trigger that serialises per code with
     `pg_advisory_xact_lock(hashtextextended('diski9.round_schedules:' || code, 0))`.
   * The partial unique index on `(code) WHERE active_to IS NULL` gives one open-ended
     row per code.
4. **Coordinating creation with schedule migrations:**
   * With a future activation time T and the lock pair above, a creation either
     finishes before the migration (bound to the old row) or waits and then resolves
     against the committed new rows.
   * The `rounds` insert trigger re-checks validity at `created_at` against committed
     rows, so a creation that started before a commit can never be bound to a row
     that is not valid at its `created_at`. It is refused instead.
   * Referenced rows may only receive `active_to` once, never earlier than their
     latest round's `created_at`.
   * `rounds.schedule_id` and `created_at` become immutable (the existing
     `app.set_once()` mechanism, extended; `schedule_id` is NOT NULL, so set-once means
     immutable).
5. **`btree_gist`:**
   * It is a trusted extension (PostgreSQL 13+), so a database owner with CREATE on
     the database can install it; superuser is not needed.
   * Local and CI PostgreSQL (16 and 17) support it.
   * **Unresolved:** whether the role that runs migrations in the target environment
     may create it, and in which schema (Supabase installs extensions into
     `extensions`). It needs confirmation in the target environment.
   * If unavailable: a constraint trigger with the per-code advisory lock above, with a
     concurrency test (two transactions inserting overlapping rows must not both
     commit).
6. **SQLAlchemy mirror:** `test_mirror_matches_migrated_schema` compares tables,
   columns and primary keys only. Constraints, triggers and indexes need no mirror
   change unless columns are added (none planned).
7. **Migration and downgrade complications:**
   * `app_0008` must audit existing rows first and refuse with a clear message if any
     violate the new rules;
   * `app_0008`'s downgrade drops only its own constraints and triggers (and the
     extension only if it created it), and must not touch data;
   * `app_0009`'s downgrade (4C) must not remove `app_0008`'s safeguards;
   * `app_0004`'s downgrade silently skips when rounds reference v2. That behaviour is
     unchanged here and noted.

## Checkpoint 4B: database schedule safeguards (`app_0008`)

Safeguards only. No schedule, round or configuration data changes, no activation, no
`app_0009`, and `DEFAULT_CONFIG` is unchanged. Full GitHub CI is **deferred** to
Checkpoint 4C (`[skip ci]`, owner-approved); it has not run on this checkpoint.

### Safeguards

| Rule | Mechanism |
|---|---|
| No overlapping intervals per code | `round_schedules_no_overlap`: `EXCLUDE USING gist (code WITH =, tstzrange(active_from, active_to, '[)') WITH &&)` (`btree_gist`) |
| Exactly one open-ended row per code | partial unique index `round_schedules_one_open (code) WHERE active_to IS NULL`, plus the deferred check (the highest version must be open-ended) |
| No gaps, chronological order | deferred constraint trigger `round_schedules_contiguous`: ordered by version, each `active_to` equals the next `active_from` |
| Referenced rows protected | `round_schedules_row_guard`: a row used by a round can never be deleted and no column may change except `active_to`. `active_to` may be set once from NULL, strictly after the latest `created_at` of its rounds (equality refused). It may be reopened only when no later version remains (the undo of an unused activation). Any other change to it is refused |
| Validity at round insertion | `rounds_schedule_valid` (BEFORE INSERT): `active_from <= created_at < active_to` for the row it is bound to |
| Round identity immutable | `rounds_identity_immutable`: `app.set_once('schedule_id', 'created_at')` (both NOT NULL, so immutable) |
| Runtime privileges | `diski9_app` keeps SELECT on `round_schedules`; INSERT, UPDATE and DELETE are revoked. A new `MIGRATION_ONLY` table kind in the schema mirror records this |

**Migration audit (before installing anything).** The upgrade refuses with
`app_0008 upgrade refused: …` (and nothing is installed or changed) if existing data
has:
* overlapping versions;
* non-contiguous versions (a gap, a closed highest version, or an open earlier
  version);
* rounds outside their schedule's validity at `created_at`.

The message lists counts and examples. There is no repair, rebinding, timestamp
change or exemption: resolution is an owner decision.

### Locking protocol and concurrency guarantees

Key: `hashtextextended('diski9.round_schedules', 0)`, transaction-level advisory locks.

* **Schedule writers:** every statement that writes `round_schedules` (any role, any
  path, TRUNCATE included) takes the **exclusive** lock through the statement trigger
  `round_schedules_write_lock`. Privileged writers cannot skip it; only
  `session_replication_role = replica`, which needs superuser, disables triggers.
  Writers should call `SELECT app.schedule_write_lock()` first, so their own later
  statements read after the lock.
* **Round creators:** the application takes the **shared** lock
  (`schedules.lock_for_round_creation`, calling `pg_advisory_xact_lock_shared` directly
  so the code also works against `app_0007`) before resolving the schedule. The
  insert trigger takes it again for any direct SQL insert. Creators never block each
  other.
* **Isolation:** both checks refuse anything but READ COMMITTED. Under READ COMMITTED
  each query in the triggers takes a fresh snapshot after the lock is granted, so it
  sees every change committed before. The transaction timestamp (and so
  `created_at`) stays fixed, but the rows read do not. REPEATABLE READ or SERIALIZABLE
  would read a snapshot from before the lock, so they are refused. Backend writers
  already use READ COMMITTED; REPEATABLE READ is used only on read-only paths.
* **Consequences, each proved by a test with separate connections:**
  1. A creator whose transaction starts after a change began, but before it commits,
     waits, then binds to the new version (`created_at` ≥ boundary, version 2).
  2. A direct-SQL creator that read version 1 before the change and inserts after it
     commits is refused: its fixed `created_at` is not inside version 1's new interval.
  3. A writer waits for an uncommitted creation, then sees it and refuses a closing
     time at or before its `created_at`.
  4. Two concurrent conflicting activations cannot both commit; the result is
     contiguous with exactly one open-ended row.
  5. Two writers whose changes are each valid alone but would leave a gap together:
     the deferred check of the second runs after the first commits and refuses.
  6. Concurrent creators share the lock without waiting.
* **Deadlock avoidance:** writers take the exclusive lock first, before touching any
  row; creators take the shared lock before touching `rounds`. A transaction must not
  mix round creation and schedule writes under concurrency, because upgrading a held
  shared lock to exclusive can deadlock. PostgreSQL would detect it, and no
  application path does this.

### Application follow-ups (from the 4A review)

* `Backend.schedule_config` cache is keyed by schedule code. Its lifetime is measured
  from the monotonic instant **before** the query, so query latency only shortens it.
  **Maximum staleness:**
  * zero at a boundary already present in the cached row (subject to clock skew
    between the application host and the database);
  * up to `schedule_ttl` (30 s) after a schedule change that commits while an entry
    is cached.
* Preparation pins the schedule row the week was planned from (`Week.schedule_id` →
  `create_scheduled_draft(expected_schedule_id=…)`). A change committed between
  planning and creation writes nothing and is recorded as `retryable_failure`
  ("replanned on the next tick"). The success message reports the created round's own
  window, never the plan's.
* `create_round` and `create_scheduled_draft` take the shared lock before resolving.

### Fixture adjustments (assertions unchanged)

| Test | Adjustment | Why |
|---|---|---|
| `test_backend_schedule_resolution.add_row` | inserts each version open-ended and closes the previous open version at its `active_from` in the same transaction | every committed state must be contiguous with one open-ended row; every caller already used contiguous versions |
| `test_overlapping_versions…` / `test_a_gap…` (4A) | now assert the database refuses the overlap or gap | such states can no longer exist, so the resolver can no longer meet them |
| `test_backend_weekly_results`, `test_backend_championship_repair` | the direct round insert binds to the `weekend` row valid now instead of the first table row | v1 is closed; these tests are about championship membership, not schedules |
| `test_backend_migrations`, `test_backend_upgrade_paths`, `test_backend_concurrency` | head revision `app_0008` | new revision |
| `test_runtime_role_privileges` | `round_schedules` is read-only for the runtime role | the approved privilege change |
| `test_upgrade_to_competition_results…` | after the refused downgrade to `app_0006`, the revision is `app_0007` (data unchanged) | `migrations_app/env.py` uses one transaction per migration, so `app_0008`'s downgrade (safeguards only) committed before `app_0007` refused. This is pre-existing behaviour; downgrade one revision at a time in operations |

### Extension prerequisites (target environment unverified)

* `btree_gist` is a trusted extension (PostgreSQL 13+). A non-superuser with CREATE on
  the database can install it; the migration uses `CREATE EXTENSION IF NOT EXISTS`
  in the default schema.
* Local PostgreSQL 16 and CI PostgreSQL 17 support it.
* The exclusion constraint finds the default gist operator class regardless of
  `search_path`.
* **Unverified:** whether the target migration role may create it, and in which
  schema (Supabase normally places extensions in `extensions`). Confirm before any
  protected execution.
* Downgrade never drops the extension.

### Protected-database audit (prepared, not run)

Run read-only (for example `BEGIN TRANSACTION READ ONLY; … ROLLBACK;`) on each
protected database before an authorised `app_0008` execution. These queries mirror
the migration's own audit:

```sql
-- 1. overlapping versions
SELECT a.code, a.version, b.version FROM app.round_schedules a
  JOIN app.round_schedules b ON a.code = b.code AND a.version < b.version
 WHERE tstzrange(a.active_from, a.active_to, '[)') && tstzrange(b.active_from, b.active_to, '[)');
-- 2. non-contiguous versions
SELECT code, version, active_from, active_to,
       lead(active_from) OVER (PARTITION BY code ORDER BY version) AS next_from
  FROM app.round_schedules ORDER BY code, version;
-- 3. rounds outside their schedule's validity (e.g. created before 19 Nov 2026)
SELECT r.code, r.created_at, s.code AS schedule, s.version, s.active_from, s.active_to
  FROM app.rounds r JOIN app.round_schedules s ON s.id = r.schedule_id
 WHERE NOT (s.active_from <= r.created_at AND (s.active_to IS NULL OR r.created_at < s.active_to));
-- 4. prerequisites
SELECT extname, extnamespace::regnamespace FROM pg_extension WHERE extname = 'btree_gist';
SELECT has_database_privilege(current_user, current_database(), 'CREATE');
```

If anything is found, stop. Report the rows to the owner, who decides case by case.
Possible outcomes:
* a documented one-off correction migration;
* leaving that database at `app_0007`;
* a revised design.

The migration itself never repairs, rebinds, retimes or exempts.

### Remaining limitations

* `session_replication_role = replica` (superuser only) disables every trigger,
  including these guards.
* Backdating `created_at` in a direct insert is still possible, but only to an instant
  where the bound row was valid, so the binding stays historically valid.
* The `app_0009` activation (Checkpoint 4C) must call `app.schedule_write_lock()`
  first, and its downgrade must keep these safeguards.

## Future educational opportunities (documented, not implemented)

Separate product backlog (for example Personal Performance Analytics): [`../product/future_enhancements.md`](../product/future_enhancements.md).

Priority order is the owner's interest first.

1. **Accumulator probability:** why nine 70% predictions together succeed only about 4% of
   the time; the tracker's "All succeed" figures are the natural place.
2. **Variance:** why a sound portfolio often returns nothing in a given week, and how
   results spread over many rounds.
3. **Recovery probability:** the chance to get at least the 100 credits back, already
   shown as "Get 100+ back"; explain what drives it.
4. **Implied probability:** 1 ÷ odds, before the margin is removed.
5. **Bookmaker margin:** why implied probabilities add up to more than 100%.
6. **Estimated Goals:** the model's expected goals per team (called "Estimated Goals", not
   "xG").

Each would reuse `education.GLOSSARY` and `term()` with the same one-per-view rule.

## Requirements recorded for later checkpoints (not implemented)

1. **Activation boundary (Checkpoint 4):**
   * schedule validity and activation timestamps use explicit UTC semantics
     (`timestamptz`, timestamps given with a UTC offset or `Z`, never local or naive time);
   * validity periods of one schedule code neither overlap nor leave unintended gaps
     (`active_to` of version *n* equals `active_from` of version *n + 1*), enforced by a
     test and, if approved, a database constraint;
   * `active_from` is an explicit owner-approved timestamp, not `now()`;
   * round creation selects the schedule version **valid at the creation time** (today:
     the latest version). `_current_schedule` is the single place to change, so creation
     and `schedule_config` stay identical.
2. **Rounds at activation:**

   | Round state | Effect |
   |---|---|
   | Published or completed | unaffected |
   | Draft | keeps its own schedule row and configuration (proved in Checkpoint 1) |
   | Created at or after `active_from` | A3 |

   The downgrade is refused once any round references the new schedule row.
3. **Historical reproducibility (Checkpoint 2):**
   * pin the v1 fingerprint (done);
   * the settlement regression must compare existing v1 entries against their
     **original expected results** (frozen eight-state payouts and settled gross from the
     committed fixtures), not merely compare results under two configurations.
4. **Fail safely:** unknown or unregistered round configuration versions must fail, never
   fall back to `DEFAULT_CONFIG` (implemented in Checkpoint 1 and guarded).
   `broad60-432-v1` and, once registered, `a3-432-v1` stay registered permanently.
5. **Outstanding observations, kept for their own checkpoints:**
   * the intermittent `test_f2_backup_restore` timing issue (`-wal`/`-shm` side files)
     goes to Stage F3 Checkpoint 5;
   * the `dev_championship` schedule selection (`deadline_buffer_minutes` read from the
     first schedule row by id) goes to A3 Checkpoint 4;
   * explicit UTC activation semantics and schedule validity without gaps or overlaps go
     to A3 Checkpoint 4 (item 1 above).
6. **Warning on the selected outcome (Checkpoint 3):** triggered by the selected
   outcome's own market-implied probability (10% ≤ p < 20%) when that outcome is eligible
   under the round's configuration; never by fixture-level presence. Tests include a
   fixture with an in-band outcome that is not selected.

## Deferred tests (need activation or later checkpoints)

* Done in Checkpoint 2: A3 boundaries, fingerprint, real pool, historical v1
  regression, coexistence.
* Open v1 rounds confirmable after activation; new rounds created under A3 on the
  `weekend` schedule; migration upgrade and downgrade (Checkpoint 4).
* Done in Checkpoint 3: warning display at the 0.10, 0.1999… and 0.20 boundaries,
  driven by the market probability.
