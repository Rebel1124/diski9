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
| 3.1 | Minor UI refinements (target size, legend wrapping, Reference Odds) | this record (section below) |
| 4 | Activation (`app_0008`, default switch, docs) | not started; migration not authorised |
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

## Future educational opportunities (documented, not implemented)

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
