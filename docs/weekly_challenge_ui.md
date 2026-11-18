# Weekly Challenge prototype UI (Phase 6B.3)

**Status:** interactive prototype on branch `feature/weekly-challenge-final-polish`.
* Phase 6B.3 is the final polish of Phase 6B.2 (`8260849`); section 0 lists its
  changes. Sections 1–9 describe Phase 6B.2 and remain valid except where section 0
  supersedes them (the former "Screener" page is now called **Match Lab**).
* It has no accounts, stored entries, settlement or live competition. A
  confirmed portfolio is **browser-scoped and non-authoritative** until Phase 6C.
* Leaderboards and history are labelled demonstration data.

## 0. Phase 6B.3 changes

**Naming and headings.** The navigation reads Diski 9 · Match Lab · Weekly
Challenge · My Challenge · Leaderboards. The page at `/` is the **Match Lab**
(route, modules and ids unchanged); its heading is "Match Lab" alone, rendered by
the same `components.page_header` as the other three pages (same element, size,
weight, colour, spacing and alignment). The former slogan ("We calculate the
probabilities…") was removed from the page and from the match-analysis card, with
its spacing, at the product owner's request. The per-match card is
titled "Match analysis".

**Filters.** Columns are sized for the longest values ("Both Teams to Score
(BTTS)", "Highest model vs market edge", "7 leagues selected", custom date ranges).
Desktop (≥ 1180 px) uses two balanced rows with Minimum probability spanning both
rows on the right; 900–1179 px uses three columns, 721–899 px two, phones one.
Dropdowns and dates carry full-value tooltips (the league tooltip lists the
selected leagues). Tested at 1366, 1180, 1024, 800 px and iPhone 13: no value
truncated, no overflow.

**My Challenge.** "This round" and "Confirmed portfolio" are equal in width and
height on desktop and stack naturally on phones. "This round" lists the round,
predictions (draft or submitted), deadline (or "None" for the demonstration),
credits (100: 40 / 30 / 20 / 10), confirmation (confirmed, withdrawn or not) and
whether replacing or withdrawing is still possible, all from the stored state,
with the browser-tab disclaimer. The three source cards sit in one compact row.

**How to play.** Three build steps (Choose nine different matches; Compare
probabilities and assess your risk; Review and submit) with Lucide icons, a
balanced two-column layout and the points schedule beneath. The note now says
championship points are awarded for recoveries in competitive rounds only, never
in demonstration or practice rounds. Rules and scoring are unchanged.

**Frozen Weekly Challenge universe.** With Weekly Challenge selected, the list is
built from the round snapshot itself (`integration.frozen_universe`): every
snapshot fixture passing the league and date filters, with the snapshot's Goal
Model 1.0 probabilities, estimated goals (now frozen on `RoundFixture`), market
probabilities and reference odds. Probability, edge and EV rankings and the
minimum-probability filter all use these same frozen values
(`integration.frozen_order`, reusing the Screener ranking rules), so what is shown
and what is sorted or filtered always agree. The live model cache is not
consulted. A market the snapshot lacks for a fixture shows "Not in snapshot", is
ranked last, and is removed by a minimum probability; nothing is filled from live
data. All upcoming matches keeps the latest model and market data. Opening a match
still shows the live Match Lab analysis for that fixture.

**Your View persistence.** `lab-store` now uses session storage: adjustments
survive navigation, a refresh and a server restart in the same tab, and end when
the tab closes. Each fixture's adjustments carry a model-context stamp (Goal
Model version, fixture and rounded baseline estimated goals) in the store's
`_ctx` entry; if the baseline changes they are not reapplied
(`lab.stored_adjustment`). Reset removes the adjustment and its stamp. Your View
never changes frozen probabilities, odds, eligibility, buckets or payouts; a
confirmed portfolio keeps the values captured at confirmation, and a replacement
captures the view current at that time. Demo and live never share fixtures, so
adjustments can't leak between rounds. Entries saved before Phase 6B.3 have no
stamp and are applied as before.

**Lost-tap fix.** When the builder mounts, Dash can fire the action callback with
every button listed as triggered; a tap in the same batch was ignored because only
the first trigger was inspected. The reducer now acts on the single input with a
click (`callbacks.clicked_id`), and the builder's redundant first list re-render
is skipped. A tap made in the very instant of mounting can still be merged by
Dash before its click count is updated; it then has no effect and can simply be
repeated (no wrong state is stored).

**Performance (vs Phase 6B.2, same machine).** Builder render block 2.4–3.3 s on
both; builder taps 0.17–0.36 s vs 0.19–0.32 s; taps after the Match Lab 0.26–0.50 s
vs 0.38–0.56 s. No material regression.

Screenshots: `docs/screenshots/weekly_challenge_final_polish/`.

## 1. Routes and journey

| Route | Page |
|---|---|
| `/` | Match Lab (formerly the Screener): Matches (Weekly Challenge / All upcoming matches), a portfolio progress strip, match analysis and the Weekly Challenge selection cards for the selected match. |
| `/challenge` | Two steps: **1 Build portfolio → 2 Review & Submit**. |
| `/challenge/me` | My Challenge. |
| `/leaderboards` | This week and Championship (demonstration data). |

Intended Screener journey: select a fixture → review the Diski 9 model analysis
(Match Lab) → adjust expected goals to form Your View → select a Weekly Challenge
prediction (cards) → explore the Bookmaker Market Reference.

**Design standards.** Dark theme with the teal accent; bucket colours Foundation
green, Balanced blue, Challenger amber, The Diski 9 purple (`--b-nine`, also used
for the portfolio count on both pages). No emojis anywhere (a test scans the app
source). Icons are from the Lucide set (ISC licence), bundled locally in
`app/icons.py` and drawn as CSS masks in the text colour (`assets/icons.css` is
generated from it; a test checks they match). Icons are decorative and always sit
beside text, so no state is shown by colour or icon alone.

**Numbers.** Values carry no "cr" suffix (151.99, Expected gross 80.30). The word
"credits" stays in labels and explanations that establish the unit
("Foundation · 40 credits", "100 credits back"). Points keep "pts".

## 2. Screener

**Filter bar.** One desktop row: Matches · Market · Leagues · Dates · Rank by ·
Minimum probability, wrapping to three columns (900–1179 px), two (721–899 px)
and one on phones. Matches is a two-option segmented control. The
"Only show matches with odds" toggle was **removed** (layout, callback input,
`ScreenerData.filtered`, JS and CSS). Minimum probability keeps its disabled state
and explanation for non-probability rankings.

**Match universes.**
* *All upcoming matches*: every upcoming fixture, including those without
  bookmaker odds (shown as "No odds"; ranked after priced fixtures by edge / EV).
* *Weekly Challenge*: exactly the fixtures of the active round snapshot.
  Switching universe resets to page 1 and sets a compatible date range (the
  snapshot's kickoff dates, or the default fortnight for All upcoming).
* Odds are never treated as Weekly Challenge eligibility; eligibility and
  snapshot rules are unchanged.

**One table presentation.** Both universes show the same Market / Edge cell: the
outcome with the best probability edge (or EV when ranking by EV), the
percentage-point difference and the market probability. For the Weekly Challenge
view the cell is computed by `integration.frozen_market_value` from the **frozen
snapshot** (its Diski 9 and margin-adjusted market probabilities and reference
odds) with the shared `diski9.odds.value` definitions, and formatted by the shared
`data.fill_value_cell`. Edge / EV ranking in that view uses the same frozen
values. The raw odds sequence and the "Challenge odds" label are gone; a "Your
pick: …" line marks matches in the portfolio. The tooltip states the snapshot
time, the frozen odds and that edge is a probability difference, not expected
value. Bucket eligibility still uses the full-precision market probability.

**Progress strip.** F / B / C counts in bucket colours; the overall count (5/9) in
Diski 9 purple.

## 3. Match Lab Weekly Challenge cards

The former seven-row table is replaced by the builder's own outcome-card
component (`components.outcome_button`), in three market groups: Match result
(Home, Draw, Away) · Both teams score (Yes, No) · Total goals (Over 2.5, Under
2.5). Each card shows the outcome, frozen odds, **Mkt** (sets the bucket), **D9**
and **You**, the bucket tag and the selection or availability state. "You = D9"
marks a match without adjustments; a legend explains Mkt / D9 / You.

Tapping an open card adds it, tapping the selected card removes it, and a card
offering **Replace · bucket** (shown only when the engine would accept the swap)
asks for confirmation before replacing the pick on that match. Every action goes
through the shared reducer and engine validation, so the builder and the Match
Lab always show the same portfolio. The panel sits after the Match Lab and before
the Bookmaker Market Reference (the detail callback fills two containers with the
panel between them). The Match Lab calculations are unchanged.

## 4. Weekly Challenge builder

* **How to play** keeps the two objectives (get your 100 credits back; finish in
  the top ten and get your 100 back), the allocation table and the points
  schedule, and adds **Build your portfolio**: choose nine different matches;
  compare Market, Diski 9 and Your View; understand your portfolio risk; review
  and submit before the deadline (icons and one line each).
* **Stepper.** The current step is filled and marked `aria-current="step"`; an
  available step is outlined; the build step shows a check once complete; Review &
  Submit is disabled until the portfolio is complete. A stored "review" step with
  an incomplete draft always shows the builder.
* **Outcome cards** show full names (no "Under …" truncation). Builder cards show
  **You** only for matches the participant adjusted, beside the Mkt value that
  decides the bucket.
* **Filters** keep Available only; the team search is wide enough for its
  placeholder and names.
* **Probability source.** Market / Diski 9 / Your View changes the tracker
  probabilities, combined bucket chances, recovery, expected payout, charts and
  the calculation explanation (which names the source). It never changes buckets,
  eligibility, frozen odds or possible payouts.

## 5. Portfolio analysis

All numbers come from `diski9.challenge.analysis` and the eight-state engine.

1. **Will you get your 100 credits back?** Recovery doughnut (100+ back /
   something under 100 / nothing back) with expected gross and net.
   **How are these calculated?** (collapsed) shows, for the current portfolio and
   source (`analysis.calculation_breakdown`):
   * Step 1: each bucket's legs, P(bucket succeeds) = product of the leg
     probabilities, payout = credits × combined frozen odds (D-15 rounding), and
     the independence assumption in plain words; The Diski 9 pays only in the
     all-nine outcome, not as a fourth independent bucket.
   * Step 2: the eight outcomes table: completed buckets, probability, gross,
     probability × gross, 100+ back, and a total row.
   * Step 3: recovery = the sum of the qualifying outcome probabilities (shown),
     with a note on when this equals 100% minus nothing back.
   * Step 4: expected gross = sum of probability × gross; expected net = expected
     gross − 100; an explanation that it is a probability-weighted average, and
     that rounding is for display only.
2. **Possible payouts.** Bucket payouts and the eight-state bar chart; the same
   outcome table is in its expander (one shared component).
3. **How many predictions might you get right?** One combined chart: bars of
   P(exactly k correct) on the left axis (unconditional, never renormalised) and a
   line of the probability-weighted conditional expected gross on the right axis,
   with a dotted 100 reference. **Focus on 0–8 correct** (default) hides the
   nine-correct point from the payout line and says so on the chart, with its
   value; **Show all nine** plots it. Impossible counts are gaps. Clicking a bar
   or the 0–9 selector shows the chance, combinations, conditional average,
   minimum, maximum and conditional chance of 100+. The 512-combination table
   stays in its expander. The separate average-payout chart was removed.

## 6. Participant state: source of truth and storage policy

`app/challenge/state.py` is the single source of truth. The browser-session store
`ch-session` holds:
* the **working draft** (`fp`, `selections`, `meta`, `notes`, `stage`) for the
  active mode;
* the **confirmed submission** (`submitted`), written only by Submit and removed
  only by Withdraw;
* `parked`: the other mode's draft and submission (demo and live are isolated);
* `withdrawn` (a note of the last withdrawal) and `confirm` (a pending dialog).

Every page render and every action calls `state.reconcile`, which brings the
stored state up to date with the current snapshot identically on both paths.
`sync_store` writes the reconciled state back on page load and navigation, and
never writes an empty (not yet hydrated) store.

**Root cause of the reported restart bug (reproduced in a browser).** The live
snapshot is pinned in server memory and its fingerprint includes its build time,
so a restarted server built a new fingerprint for the same round. Phase 6B.1 page
renders treated a draft with another fingerprint as empty and matched the
submission by fingerprint ("not confirmed"), while the reducer migrated the draft
lazily on the next action, so the next unrelated click brought the old portfolio
back (and that click was discarded). Now reconciliation is eager on reads and
writes, submissions are matched by round and mode, drafts are compared
order-free, and actions are applied after reconciliation.

**Lifecycle (prototype, browser tab only).**

| Event | Draft | Confirmed submission |
|---|---|---|
| Page navigation | kept | kept |
| Page refresh | kept (`sessionStorage`) | kept, shown immediately |
| App server restart, same tab | kept; revalidated against the rebuilt snapshot (unchanged picks kept, changed ones listed for review) | kept, shown immediately |
| Closing and reopening the tab | gone | gone |
| Opening another tab | empty (new session); a *duplicated* tab copies the session | as draft |
| Snapshot refresh (same round) | revalidated, never silently moved to new odds | kept (frozen record) |
| New round | cleared | closed as an earlier round, not shown as current |
| Demo ↔ live | parked and restored per mode | parked and restored per mode |
| Clear draft | cleared | unchanged |
| Replace | — | replaced only after every check passes |
| Withdraw (confirmed) | cleared | removed; stays removed after refresh, restart and later actions |

Your View (`lab-store`) uses session storage since Phase 6B.3 (section 0): it follows
the same lifecycle as the draft. A submission stores the Your View values used at
confirmation.
No `localStorage` or database persistence is used (both need approval and belong to
Phase 6C).

## 7. Review & Submit, withdrawal, My Challenge, Leaderboards

**Review & Submit:** source cards, the nine picks, allocation and snapshot; the
confirm / replace button; **Withdraw submission** when a confirmed entry exists;
the confirmation dialog (check icon, "You're in!").

**Withdrawal.** A secondary button with an undo icon and restrained red styling,
on Review & Submit and My Challenge, while the round is open. A confirmation
dialog explains that the confirmed entry for the round is removed and the working
portfolio cleared, and that a new portfolio can be submitted before the deadline.
"Keep my submission" changes nothing. After the deadline the action is refused. On
success the round shows **Withdrawn** with "Build a new portfolio"; old selections
are never resubmitted. Clear draft, Replace and Withdraw remain separate actions.

**My Challenge:** a compact "This round" card (status, progress, prototype
browser-tab notice) and a confirmed-summary card (frozen Market / Diski 9 / Your
View metrics, maximum payout, Withdraw) side by side; "Show my nine predictions"
as a separate full-width card with three bucket columns (stacked on phones) and a
one-line Diski 9 summary; then the illustrative championship and history. The body
re-renders whenever the stored state changes.

**Leaderboards:** gold trophy, silver medal and bronze medal icons for positions
1–3 on the podium and in the weekly and championship rank columns, next to the
numeric rank. Shared ranks get identical icons and no position is manufactured
(1, 1, 3 shows two trophies and a bronze). Scoring, ranking, tie-breaks,
highlighting and demonstration notices are unchanged.

## 8. Performance

Measured in headless Chromium against the same database (demo round). Phase 6B.1
is commit `680127d`.

| Measure | Phase 6B.1 | Phase 6B.2 |
|---|---|---|
| Main-thread block after the builder renders | ~5.0 s | ~2.5 s |
| Builder tap | 0.33–0.43 s | 0.18–0.27 s |
| Builder tap after visiting the Match Lab | 1.8–2.0 s | 0.43–0.50 s |

Changes: one CSS-driven state tag per outcome card (7 elements instead of 13–18),
the Match Lab unmounted while another page shows (rebuilt from the selection and
the Match Lab store on return), the Match Lab panel rendered only on the Screener,
and the store write-back limited to page loads. The remaining render block is
Dash's per-component store subscriptions over ~1,500 elements.

## 9. Testing

* `tests/test_challenge_state.py`: restart, hydration, isolation, withdrawal, and a
  Playwright server-restart walkthrough.
* `tests/test_match_universe.py`: toggle removal, universes, frozen edge cells for
  all three markets.
* `tests/test_playtest_refinement.py`: Match Lab cards, calculation reconciliation,
  combined chart, zero-probability counts, stepper, How to play, rank icons, no
  emojis.
* Screenshots: `docs/screenshots/weekly_challenge_playtest_refinement/`.

```bash
uv run diski9 serve
```
