# Phase 6C.5 Stage E — Closure and Stage F handover

**Status (21 Nov 2026):** Phase 6C.5 Stage E (Leaderboards and Historical Performance
UI) is **formally approved by the owner and closed**. **Stage F (Development Tooling
and Testing) has not begun.** It needs a separate owner authorisation, as does
Stage G. Nothing has been merged, tagged or deployed.

Read this with the authoritative records. This page summarises them and does not
replace them.

| Document | Role |
|---|---|
| [`phase6c5_implementation.md`](phase6c5_implementation.md) | Implementation record. Stage E is §5: interfaces §5.2, read services §5.3, statistics §5.4, privacy §5.5, tests §5.7, performance §5.8, deviations §5.9, limitations §5.10, regression §5.11, refinements §5.12, final refinements §5.13, closure §5.14 |
| [`phase6c5_design_specification.md`](phase6c5_design_specification.md) | Specification; §23.12 and §23.13 record the Stage E choices and approval |
| [`../product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md) | Decision register: L-01 to L-37, CH-01 to CH-12, D-30a, and the Stage E chart threshold |
| [`../product/weekly_challenge_phase6c_plan.md`](../product/weekly_challenge_phase6c_plan.md) | Stage plan and roadmap status |
| [`../phase6c5_local_acceptance_mac.md`](../phase6c5_local_acceptance_mac.md) | Owner's local guide. Stage E visual acceptance is §15, with the acceptance record in §15.8 |
| [`../screenshots/phase6c5/README.md`](../screenshots/phase6c5/README.md), [`../screenshots/phase6c5/refined/README.md`](../screenshots/phase6c5/refined/README.md) | Screenshot evidence (original, refined and final) |

## 1. Scope delivered
* **Weekly Leaderboards.**
  - Stream and round selection, with the default round rule.
  - Public standings with display names only.
  - Personal summary shown independently of the page.
  - Every round state: open, locked, provisional (including provisionally void),
    final, corrected, under review, practice, void, refunded and pending assignment.
  - Shared ranks shown as "=n".
  - Points, 50-row pagination with "Go to my position", and a compact podium.
* **Championship Leaderboards.**
  - Championship selection, lifecycle status, and separate Under review and Corrected
    labels.
  - A ten-segment counted-round progress bar. A D-30a championship completed with
    fewer rounds is never shown as waiting.
  - Joint champions, "no champion", review reasons including integrity review, D-30a
    disclosures, and restored-without-points rounds.
  - Personal standing, or the reason there is none.
  - The points rules, generated from the scoring engine's own table.
* **My Challenge.**
  - Current and History tabs, with History scoped to the participant.
  - Statistics using the approved definitions (§9.4).
  - Two cumulative charts: allocation and return, and championship points for one
    championship.
  - Paginated entries.
  - Entry details reusing the 6C.4 results panel.
* **Read services.**
  - `challenge_history.py` (new) and additions to `leaderboards.py`, all read-only.
  - A display-only round `window` label.
  - No write path and no migration.

## 2. Owner-approved refinements
1. **First round (§5.12):**
   - aligned tables (the root cause was a reused CSS class);
   - statistics cards in the Build Portfolio card style;
   - a compact podium and grouped controls;
   - friendly round labels;
   - a larger progress bar;
   - the three-eligible-round rule for each chart;
   - the methodology moved behind a disclosure;
   - natural plurals;
   - a two-by-two phone navigation and compact phone cards;
   - History shown as cards up to tablet width.
2. **Final round (§5.13):**
   - equal spacing around the demonstration button;
   - Your Result cards in the statistics-card style, with refunds in amber, distinct
     from a recovery;
   - bold chart headings matching "Your statistics".

## 3. Commits (`feature/phase-6c5-leaderboards`, `Rebel1124/diski9`)

| Commit | Content |
|---|---|
| `b983bba` | Stage E implementation, tests, tools and screenshots |
| `70667e7` | Stage E documentation checkpoint |
| `eb12eec` | First owner refinements (code, tests, browser tool, refined screenshots) |
| `a02cb68` | First refinements documentation |
| `e820790` | Final owner refinements (code, tests, screenshots, documentation) |
| this record's commit | Closure documentation only |

## 4. Test and CI evidence
Each run is listed with its own scope.
* **Full local regression on the final code (`e820790`): 1,634 passed, 0 failed.**
  - The real PostgreSQL, local Supabase Auth and browser tests all ran.
  - The PostgreSQL refund-versus-recovery card test was added after this run had
    started, so it is **not** part of the 1,634.
* **Focused run with that test:** `test_backend_participant_results.py`,
  `test_backend_stage_e_history.py` and `test_stage_e_ui.py`: **47 passed**.
* **Earlier full runs:**
  - 1,632 passed and 0 failed at the first refinements, before their two new
    PostgreSQL tests (31 passed when those were run with the Stage E files);
  - 1,629 passed and 1 failed at `b983bba`, the intermittent test below.
* **Browser checks** (real app, local Supabase Auth, seeded development database):
  - first refinements: `tools/e2e_6c5/refined.js`, **108 page checks at 6 widths**
    (1360, 768, 430, 390, 360, 320 px), element-level, with a stress pass, 0 problems;
  - final refinements: `tools/e2e_6c5/final.js`, **71 checks at 4 widths** (1360,
    768, 390, 320 px), 0 problems;
  - original Stage E: `tools/e2e_6c5/shots.js`, 35 checks at 3 widths, 0 problems.
* **GitHub CI:**
  - **run 68 passed on `e820790`**, verified on 21 Nov 2026;
  - earlier runs 66 (`70667e7`) and 67 (`a02cb68`) also passed.
* **Known intermittent test:**
  `tests/test_match_context.py::test_browser_section_b_alignment_and_bookmaker_layout`
  is an unchanged Match Lab browser test.
  - It failed at `b983bba` and once at `29ff049` (before Stage E), and passed 2 of 3
    times when rerun alone.
  - It passed in the two latest full runs. It is still unresolved and is carried
    into Stage F; it has not been weakened, suppressed or removed.

## 5. Screenshot evidence
* `docs/screenshots/phase6c5/`: the original Stage E captures, 33 files.
* `docs/screenshots/phase6c5/refined/`, including:
  - the refined captures;
  - before/after comparisons (`compare_*.png`);
  - the Build Portfolio reference cards;
  - the `final_*.png` files for the final refinements.
* Each folder has a `README.md` index. All historical screenshots are kept.
* **Two items are labelled in the index as specimens** rather than real data:
  - the zero-net card, whose value was set in the page;
  - the long-name stress captures, where names were injected into the page because
    names recorded at lock cannot be changed.

## 6. Quantitative fingerprint
`88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`, unchanged and
re-verified on the final code.
* **Unchanged:** scoring, settlement, corrections, competition publication,
  championship processing, authentication, operator commands, ingestion, odds, the
  screener, Match Lab, Portfolio Analysis, and Build Portfolio's cards.

## 7. Database and migration status
* **Migration head:** `app_0007`, with no Stage E migration (verified with
  `migrate.head()`).
* **Owner's Mac:**
  - `diski9` is at `app_0006`; it was never migrated, backfilled, reset or modified.
  - The scratch acceptance copy `diski9_6c5_acceptance` is at `app_0007`. It was
    rebuilt from the backup with owner approval on 20 Nov 2026 (§15.8) and has not
    been changed since.
  - The backup `diski9-before-6c5.dump` is kept.
* No database operation was part of this closure.

## 8. Limitations
* **Performance:** the Stage E figures are server-side read times on one machine
  (1,000 participants). Representative multi-process load and concurrency testing
  has **not** been done.
* **Scale:** the 10,000-participant stretch runs for Stages D and E were **not
  executed**, and none is claimed.
* **Current result panel:**
  - The Your Result card styling was verified on the shared component through the
    History drill-downs: provisional, final, corrected, under review, void, refunded,
    and positive and negative Net.
  - Neither the owner's local data nor the showcase data contained a current round
    with a populated result panel. **No manual test of the Current-tab result panel
    was performed.** The shared component is supporting evidence only.
* **Round labels:** two rounds with the same match window show the same label; the
  small code beside it tells them apart.
* **Leaderboard width:** the table column is capped at 880 px on desktop.
* **Long names in leaderboard rows** were verified by injecting them in the browser.
* **Earlier stages:** the limitations recorded in §4.8 and §5.10 still apply,
  including:
  - an operator invalidation cannot be reversed;
  - membership is verified structurally rather than by full replay;
  - readers in the same process can contend with each other.

## 9. Deferred requirements for Stage F (Development Tooling and Testing)
* Investigate the intermittent Match Lab browser test.
* Representative multi-process performance and concurrency testing.
* The 10,000-participant stretch benchmarks, if Stage F confirms their scope.
* A manual or automated check of the Current-tab result panel against a live
  development round.
* Development tooling and testing as set out in the Phase 6C.5 plan.
* **Carried release gates and deferred items, unchanged:**
  - D-29: real-pool validation before the official series;
  - D-36: retention and pseudonymisation;
  - D-38: official activation gates;
  - S-07: hardening of the older operator commands;
  - hosted Supabase acceptance;
  - the 6C.3 backlog.
* Private mini-leagues stay excluded.

## 10. Independent odds research trial
This is separate from Stage E acceptance, and its status was checked from records only.
* **Last successful capture:** `7959b3f`, 20 Nov 2026 at 12:16:27 UTC (20 Premier
  League fixtures, 0 PSL fixtures, no errors), on `claude/gifted-newton-h6o5hk`.
  The latest commit on that branch's remote matches.
* **Missed captures:** 20 Nov at 15:14, 18:14 and 21:14 UTC, and 21 Nov at 00:14 UTC.
  - Each time, the session's automated permission check refused the capture command
    (`uv run diski9 monitor-odds --until 2026-11-21T15:00:00+00:00`, run in the
    research checkout). No capture ran and nothing was replayed.
  - The scheduled task is still enabled; its next firing was 21 Nov 03:14 UTC.
* **Trial end:** the approved conclusion is 21 Nov 2026 at 15:00 UTC. The trial is
  **not** described as complete here; its final status is to be confirmed after that
  time.
* This follow-up is still open and was not changed by this closure.

## 11. Stage F
**Stage F has not begun.** Stages F and G each need a separate owner authorisation.
