# Phase 8 CP3A: Portfolio Build, navigation and context management (implementation plan)

*Plan approved by the owner on 27 Nov 2026, with the refinements below (record [§15.8](phase8_implementation.md)). It is implemented one checkpoint at a time, and each checkpoint is authorised, reviewed and accepted separately.*

- **Status:**
  - **CP3A-1** (routes and navigation) is **formally accepted** (27 Nov 2026; `e7c2aae`, `951a33a`; §10.1);
  - **CP3A-2** is **formally accepted** (27 Nov 2026; `2bd1e4f`, `5d63f7a`; §10.3);
  - **CP3A-3** is **formally accepted** (27 Nov 2026; `4e08e71`, closure `1648381`; §10.4, §10.5);
  - **CP3A-4** is **formally accepted** (owner, after ChatGPT's review; `57d6bc9`, `8af420f`, `fb1873d`; §10.6, §10.7);
  - **CP3A-4B** (ML-01 correction and cumulative testing) is implemented and verified (full local suite 2513/2513; CI run #175 success), awaiting review (§10.8);
  - **CP3A-5 onwards are not authorised.**

Decisions this plan implements: [`phase8_implementation.md`](phase8_implementation.md) §15 (governs), with §11 OD-4 where not superseded.

Markers used below:
- **[V]** verified in the code;
- **[D]** owner decision (27 Nov 2026);
- **[A]** assumption.

## 1. What already exists and is reused

| Mechanism | Where | Reuse |
|---|---|---|
| Routing | `dcc.Location(id="url")` (`app/app.py`); the router callback `route` in `app/challenge/callbacks.py` [V] | Kept; routes re-mapped in CP3A-1 (§2) |
| Navigation | `NAV` in `callbacks.py` [V] | The five approved tabs (CP3A-1) |
| Screener list (all upcoming) | `screener-root`, kept mounted and hidden by style; table plus mobile cards; filters, market selector, threshold, paging [V] | Reused as the domestic research list (§6) |
| Weekly Challenge builder | `pages.challenge_shell`, fixture cards, tracker, review, submit, replace, withdraw, adoption (`adopt_ui`) [V] | Reused unchanged as the domestic challenge list |
| Universe toggle | `RadioItems id="universe"` (`app.py`), values `challenge` and `all` [V] | Removed from the UI in CP3A-3/4. Its value comes from the list the fixture was opened from and from the frozen/latest toggle (§4) |
| Match Lab detail | `lab.render_detail`; the `update_detail` and `adjust` callbacks (`app.py`) [V] | At `/lab`, unchanged |
| Context resolution | `lab_context.resolve(service, data, fid, universe)` → `LabContext(kind="round"/"live", key, r)`; frozen key `r:<round>:<fixture>`, live key `<fixture>` [V] | Basis of the frozen/latest toggle (§4) |
| Your View storage | Browser `lab-store` (session) keyed by context; account rows per context (`LiveContext` / `RoundContext`); source-aware stamps (CP2B.1) [V] | Unchanged |
| States A/B/C | `lab.starting_point`, `market_fit` (CP2B.1) [V] | Unchanged |
| Round state | `rounds.current_round`, `persist.published()`, `availability()` with `RoundStatus` [V] | Extended for status messaging (§7) |
| Session state | `ch-session` (round, selections, stage), `ch-prefs` (source, filters), `lab-store` [V] | Holds the list origin, the Research only state and the last fixture (§5) |
| Information tooltips | `education.info` (keyboard- and touch-operable info icon) [V] | Reused for the Research only tooltip (§6) |

## 2. Navigation and fixture-list structure

| Tab | Route | Content |
|---|---|---|
| Portfolio Build | `/` | Homepage introduction and the domestic card (CP3A-2), with the domestic challenge list (the existing builder) or the domestic research list (the existing Screener table), chosen by the card's **Research only** toggle (§6) |
| Match Lab | `/lab` | Detail of the selected fixture; no selectors after CP3A-3 |
| My Challenge | `/challenge/me` | Unchanged |
| **Training Ground** (formerly Learn) | `/learn` | Route and tab; the approved Learn content follows in CP3B |
| **Leaderboard** (formerly Leaderboards) | `/leaderboards` | Unchanged functionality |

- **Tab names [D, 27 Nov 2026]:**
  - the Learn tab is renamed **Training Ground**, in keeping with the football theme, and moved before the leaderboard tab;
  - Leaderboards is renamed **Leaderboard**;
  - Training Ground keeps all approved Learn functionality, content and future enhancements;
  - Leaderboard keeps all leaderboard functionality, championship standings and history;
  - the internal routes (`/learn`, `/leaderboards`) and identifiers are unchanged. Page headings follow the tab names; general prose about the weekly and championship leaderboards stays plural.

- **Old addresses** [V, CP3A-1]:
  - `/challenge` is redirected to `/` by the server (query string kept) and aliased by the router;
  - old Match Lab deep links `/?fixture=<id>` are redirected to `/lab?fixture=<id>`;
  - builder and guidance links now point to `/lab?fixture=<id>`.
- **Homepage (CP3A-2) [D]:**
  - the approved wording and one prominent teal football icon from the existing icon set (`app/icons.py`) beside the two headline lines, sized responsively, with no animation;
  - a collapsed How to Play;
  - the **Domestic Weekly Challenge card (teal):** championship, round, status line (§7), the **Research only** toggle (§6) and the main action button;
  - "Free to play. No real money. Just football.";
  - the **European Match Analysis card (gold) is not rendered** until CP2B.2 is accepted (§8).

## 3. Removing the Challenge Mode toggle and duplicate selectors

- The `universe` RadioItems leaves the layout (CP3A-3/4).
- Match Lab loses its list and filters, which stay in Portfolio Build. Match Lab renders `render_detail` only.
- **[D1] Competitive selection controls** (the pick, remove and replace panel; `ACTION_OF`) are shown **only in the frozen challenge context**:
  - they are hidden whenever Match Lab shows latest data;
  - switching back to frozen restores them and the valid frozen Your View;
  - the existing status and deadline restrictions still apply.
- The route-dependent callbacks were re-pointed in CP3A-1 (§10.1). This is the main regression surface, so each one has a route test.

## 4. Frozen / latest context switching and adjustment isolation

- **Context source:**
  - a fixture opened from the domestic challenge list (Research only OFF) resolves with `universe="challenge"`, today's frozen path [V];
  - a fixture opened from the research list (Research only ON; later the European list) resolves with `universe="all"`, the live path [V].
- **Toggle "Use latest available data" (CP3A-4):**
  - **[C1] Visibility depends on the originating context, not the displayed one.**
    - It is rendered when the fixture was opened from the challenge list **and** a valid frozen snapshot of that round still contains it. The test is whether `resolve(..., "challenge")` would give `kind == "round"`, evaluated whichever context is displayed.
    - So the toggle **stays visible in latest mode** and the user can always return to frozen while that context is valid.
    - Independent model availability is irrelevant: CP2B.1 already builds frozen State B and C contexts.
  - On re-resolves the **same fixture** with `universe="all"`; off returns to `"challenge"`. The state is per fixture and session-scoped.
- **Isolation:**
  - frozen and live Your View already use different browser keys and different account rows [V];
  - stamps differ by context, including the CP2B.1 input identity [V];
  - so switching back restores the frozen adjustments untouched. CP3A adds tests, not mechanisms.
- **Competitive data is never modified:**
  - the latest view renders only the live payload and live odds;
  - selection controls are hidden in latest mode [D1];
  - submission and the portfolio read only the published snapshot (`service.outcomes_for`), which the Match Lab cannot write [V].
- **Unavailable or stale latest data:**
  - fixture absent from the live data: an explicit "Latest data unavailable for this match" message, with the toggle still able to return to frozen;
  - stale odds: shown with the existing stale labels; State B needs fresh inputs, otherwise State C (CP2B.1);
  - frozen inputs are never substituted into the latest view.
- **Timestamps (stored, never hard-coded):**
  - frozen: `snapshot.snapshot_at`, labelled as the publication snapshot;
  - latest: the model calculation time and the displayed markets' observation times, labelled "latest collected", never "live".

## 5. Preserving portfolio state, filters and navigation context

- Portfolio Build's builder state lives in `ch-session` [V]. Builder filters move into `ch-prefs` (not stored today).
- `ch-prefs` gains:
  - `research` (the Research only state);
  - `last_fixture`, holding the fixture id, origin list, analytical context, and the round id and snapshot fingerprint where applicable [C2];
  - the per-fixture latest toggle.
- **[C2/C4] Match Lab opened from the tab** restores `last_fixture` only when its identity still holds:
  - challenge origin: the same round is still the published round and its snapshot fingerprint is unchanged, and the fixture is in it;
  - research origin: the fixture is still in the latest data.
  - Otherwise it shows the empty state "Choose a match in Portfolio Build", with a link. A fixture or adjustment is never attached to a different round or baseline.
- A **"← Back to Portfolio Build"** link returns to `/` with the same list. The list, page, filters, picks, draft and adjustments are untouched because nothing is re-created.

## 6. Domestic research access: the Research only toggle [D2]

The owner rejected the secondary text link in favour of a compact toggle inside the domestic card.

- **Control:**
  - the label **Research only**, the switch and the information icon sit **immediately adjacent, grouped on the left** of the card, with the switch directly next to the label (never at the far right);
  - compact, in the existing visual language.
- **Tooltip** (the existing `education.info` pattern, operable by keyboard and touch): "Analyse upcoming domestic matches using the latest available data. Research-only analysis does not form part of the Weekly Challenge."

| | Research only OFF | Research only ON |
|---|---|---|
| Main button | **Build domestic portfolio** | **Analyse domestic matches** |
| List | Published challenge fixture list (the existing builder) | Upcoming domestic research list (the existing Screener table) |
| Data | Frozen market and analytical data | Latest available data |
| Competition | Portfolio construction under the existing challenge rules | None; clearly labelled research only |
| Match Lab | Frozen by default, with the optional latest-data toggle | Latest data, no frozen/latest toggle |

- **Switching** never changes selections, filters, drafts or valid adjustments. Both lists stay mounted and are shown or hidden.
- **Research is available all week**, whatever the challenge status.
- **Initial default [D, owner Part B, 27 Nov 2026], when the session has no choice yet:**

  | Challenge | Research only |
  |---|---|
  | Open | OFF |
  | Locked | OFF |
  | Settling | OFF |
  | Upcoming (not yet published) | ON |
  | Unavailable | ON |

  - it is a starting value only, not a continuous override;
  - once the participant changes the toggle, the choice is kept for the browser session (`ch-prefs`), including across Match Lab and back and a reload;
  - no account-level preference and no new persistence layer;
  - an unavailable challenge never exposes competitive functionality just to honour a preference: with Research only OFF and no playable round, the builder shows its existing unavailable message;
  - portfolios, drafts, filters and valid adjustments are never discarded.
- This is a local control within the domestic card, not the old global Challenge Mode toggle. It reuses the existing list components, and adds no tab and no new architecture.

## 7. Snapshot notices and challenge status messaging [D3]

- **Domestic list notice:** "Odds, probabilities and model estimates were fixed when this challenge was published on {snapshot_at, local time} so every participant plays under the same conditions." The frozen Match Lab context uses the same text.
- **Card status**, from `current_round` and the next prepared week:

| State | Message |
|---|---|
| Upcoming | "Next challenge expected to open {publication target, local}, subject to fixture availability." |
| Unavailable | "No Weekly Challenge available this week. You can still research upcoming matches." |
| Open | "Entries close {deadline, local}." |
| Locked | "Entries closed. Awaiting match results." |
| Settling | "Results are being settled." |

- Dates and times come from stored values (`prepare.publication_target`, the round's deadline). They are never hard-coded.
- A reason (for example, not enough eligible matches) is added **only** when it is the verified reason recorded by preparation.
- No message implies that matches are already in progress right after entries lock.
- The existing data-driven opening rules and international-break behaviour are unchanged. There is no break calendar and no championship pause.
- This closes the gap noted in §15.5: today a final round with no successor still shows "Round locked".

## 8. European entry point before CP2B.2 acceptance [D5]

- **The gold card is not rendered**: no "coming soon" card and no non-functional button.
- **Registry presence alone does not expose it.** CP3A has no European card code; CP2B.2 adds the card explicitly as part of its accepted scope. No feature-flag framework is introduced.
- CP3A keeps the card layout able to hold a second card.
- European football stays analysis only.

## 9. Desktop, tablet and mobile

- **390 px:** cards stacked; the Research only control wraps under the card text if needed; the existing card list and sticky tracker; Match Lab full width with the toggle under the title; the back link at the top.
- **768 px:** cards side by side when two exist.
- **1280 px:** the existing table and side tracker.
- No horizontal scroll at 390, 768 or 1280 px (existing acceptance criterion).

## 10. Checkpoints, dependencies and effort

| Step | Content | Hours |
|---|---|---|
| **CP3A-1** | Routes and tabs, `/lab`, `/learn`, redirects of old addresses, re-pointed route checks | 3–4 |
| CP3A-2 | Homepage introduction, icon, domestic card, Research only toggle and research list, status messaging, snapshot notice | 4–5 |
| CP3A-3 | Match Lab without selectors, last-fixture restore with identity (C2), empty state, back link, filter persistence; Minimum Market Probability (restored to the step list, see §10.4) | 5–7 |
| CP3A-4 | Frozen/latest toggle (C1), timestamps, unavailable or stale handling, selection controls only when frozen (D1) | 2–3 |
| CP3A-4B | ML-01: regression test first, smallest correction (§10.2) | 2–3 |
| CP3A-5 | Integration, guest and signed-in browser journeys at 3 widths (C3), screenshots, full CI, docs | 5–7 |
| **Total** | | **21–29 h** |

- **Why +1 h on the provisional 18–25 h:** the local Research only toggle (control, tooltip, button text, two mounted lists, preserved state and the no-challenge default) costs about 1 h more than the secondary link it replaces. The signed-in journeys (C3) fit inside CP3A-5, because per-checkpoint browser checks now absorb some of its earlier scope.
- **CI:** CP3A-1 to CP3A-4 run focused local tests, regressions, lint and browser checks, and commit with `[skip ci]` (owner instruction, 27 Nov 2026). The full CI suite runs at CP3A-4B and CP3A-5. Intermediate acceptance is not CP3A acceptance.
- **Order:** the agreed order is kept. CP3A-4B follows CP3A-4 because ML-01 lives in `update_detail`, which CP3A-3/4 change. Fixing it afterwards tests the final callback.
- **STOP after every checkpoint:** independent review and owner acceptance.

### 10.1 CP3A-1 as implemented

- **`NAV`:** Portfolio Build `/`, Match Lab `/lab`, My Challenge `/challenge/me`, Training Ground `/learn`, Leaderboard `/leaderboards`. All five labels were verified at 390, 768 and 1280 px: one line each, no horizontal scroll.
- **Router:**
  - `/` (and the `/challenge` alias) renders the existing Weekly Challenge builder unchanged;
  - `/lab` shows the existing Screener and Match Lab unchanged;
  - `/learn` shows a plain Training Ground page;
  - unknown paths show "Page not found" with a link back to Portfolio Build.
- **Path checks moved from `/` to `/lab`:** `update_detail`, `match_lab_panel`, `screener_strip`, `data_context` and `open_fixture`, which now acts only on `/lab`. `sync_round_views` moved from `/challenge` to `/`.
- **Visibility:** `screener-root` starts hidden, so the Match Lab never flashes on the home page.
- **Server redirect:** a Flask `before_request` hook, registered after the account hooks, redirects GET/HEAD requests for old addresses.
- **Unchanged:** the analytical behaviour, the universe toggle (removed in CP3A-3/4), state stores and the account and guest behaviour. There are no new component IDs apart from the Learn page content, and no database change.

### 10.2 CP3A-4B: ML-01 [D4]

- Reproduce the stale-adjustment race with a focused regression test, and show it fails before the fix where practical.
- Establish the exact mechanism, then make the smallest sufficient correction: stale callbacks must not apply adjustments to the wrong fixture, baseline or frozen/latest context.
- Historical adjustment compatibility is preserved. There is no broad callback or persistence refactor.

### 10.3 CP3A-2 as implemented

- **Home (`challenge/home.py`):**
  - the approved headlines with a teal football icon (added to the bundled icon set in the same 24 px, 2 px-stroke style; no dependency);
  - the tagline and footnote;
  - the **Domestic Weekly Challenge** card;
  - no European card and no placeholder.
- **Card facts, from stored data only:**
  - the championship name and progress (`championship_board`, guests included);
  - the round code, fixture window, entry deadline (open) or expected publication time (upcoming);
  - the status line in the approved wording (§7).
- **How the status is derived:**
  - open: the published round's deadline is ahead;
  - locked: past the deadline or locked;
  - settling: the round is settling;
  - with no round, or a final one: upcoming until the weekend schedule's publication target (Friday 08:00 SAST), then unavailable;
  - prototype mode: the opening assessment, with its verified reason;
  - so a final round no longer shows "Round locked" during a break.
- **Research only:**
  - a native checkbox styled as a compact switch, with its label, then the `education.info` tooltip, grouped on the left;
  - `set_research` stores only explicit changes;
  - `layout_mode` shows either the builder (OFF) or the Screener as the research list with latest data (ON) under the card;
  - both stay mounted, and the universe is set only when it differs, so filters and pages are not reset;
  - the global Matches control is hidden (kept as internal state until CP3A-3/4).
- **Research list safeguards:**
  - the Weekly Challenge selection panel and progress strip are not rendered there;
  - the latest-data line shows the model's stored time and that bookmaker prices carry their own collection times;
  - a research-only note sits above the list.
- **Closure refinements (record §15.10):**
  - homepage order and wording;
  - a full-width card without the round code or deadline field;
  - state-dependent button wording;
  - the locked notice without the demonstration invitation;
  - How to play collapsed;
  - Goal Model wording, championship stream resolution and the schedule-failure message;
  - the Minimum Market Probability filter is reported for a decision (proposed for CP3A-3).
- **Competitive list:** the builder's snapshot notice now states that odds, probabilities and model estimates were frozen at publication, with the stored snapshot time, and that current prices may differ.
- **Dependency on CP3A-3, documented:**
  - until the Match Lab detail moves to `/lab` only, selecting a match in the research list shows its analysis beneath the list (latest data, no selection controls), as the Screener did before;
  - the Match Lab tab itself is unchanged.

### 10.4 CP3A-3 as implemented

- **One entry point:**
  - Portfolio Build holds both domestic lists;
  - selecting a research match (`open_from_research`) or a challenge card's Match Lab link opens `/lab`;
  - nothing is analysed beneath a list any more;
  - the Screener layout is split into the research list (`screener-root`) and the Match Lab page (`lab-root`: back link, heading, challenge strip, detail, selection panel, bookmaker reference, footer). The Match Lab has no competition or fixture selectors, list, filters or Matches control.
  - **Market control [D, approved at CP3A-3 closure]:** the Match Lab keeps its own market selector (Match Result (1X2), Both Teams to Score (BTTS), Over/Under 2.5 Goals; `lab-market`), because its analysis is per market and the list's market selector is no longer on the page. Opening a research match carries the list's market across. It is not a fixture or universe selector. Changing market keeps the fixture, context, snapshot and valid Your View adjustments, and never changes portfolio selections.
- **Links name their context** (`app/links.py`):
  - `/lab?fixture=<id>&ctx=challenge&round=<round>` from the builder and its guidance panel;
  - `ctx=research` from the research list;
  - demonstration cards link without a challenge round;
  - old links without a context open the latest data, never a frozen snapshot they did not name.
- **Restoration:**
  - `open_lab` reads the address, including on a full page load, which fixes the CP3A-1 deep-link limitation;
  - `update_detail` resolves it with `lab_context.resolve_target`; the last valid target is kept in the browser session (`lab-target`) and restored when the tab is opened directly;
  - a challenge target resolves only to the same published round and snapshot fingerprint, and only to its frozen context;
  - invalid, missing or unavailable targets show a safe message or the empty state ("Choose a match in Portfolio Build"), never an arbitrary match and never latest data in place of a frozen context;
  - the same fixture in both lists keeps separate contexts and Your View keys.
- **Originating state:**
  - the research list stays mounted (filters, ranking, Minimum Market Probability and page kept);
  - the builder stays mounted while the Match Lab shows, and the router leaves it untouched on return (`ch-mounted`), so its filters, page, picks and draft are as left;
  - Research only is unchanged by navigation;
  - the challenge strip and selection panel appear only for challenge matches.
- **Minimum Market Probability [OD-4]:**
  - one control, 0–100% (0 = no minimum), inclusive, on actual margin-adjusted consensus, independent of the ranking;
  - research list: a fixture qualifies when any outcome of the selected market has a fresh consensus probability meeting it, and all outcomes stay displayed; above 0, fixtures without fresh consensus are excluded; model or market-implied estimates are never substituted;
  - model ranks only order fixtures (model-absent last, never dropped);
  - edge and EV consider only qualifying outcomes (`best_edge`/`best_ev` now filter on market probability) and still need the independent model (CP2B.1);
  - builder: a display filter on outcomes by their frozen market probability, like the bucket filter, with no freshness test, never changing picks, eligibility, buckets, odds or payouts;
  - the frozen Screener path (`frozen_order`) follows the same rule on frozen market probabilities.
- **Locked and settling challenges:**
  - the builder's locked view now lists the published fixtures read-only (pick buttons disabled) with frozen Match Lab links;
  - the Match Lab panel says entries are closed;
  - the reducer and the services refuse changes after the deadline, whatever the route or link.
- **Footer (B7):** distinguishes the independent Goal Model (results and goals, not bookmaker odds) from the market-implied model (market probabilities, where a reliable fit exists).
- **Estimate:**
  - the filter was approved for CP3A (OD-4) and counted in the original CP3A estimate (§9.3, "one slider") but omitted from the step list when this plan was rebuilt;
  - restoring it to CP3A-3 corrects that understatement rather than adding scope or double-counting. CP3A-3 5–7 h, CP3A 21–29 h, Phase 8 baseline 50–71 h.

### 10.5 CP3A-3 closure refinements (owner, 27 Nov 2026)

- **One published pair per resolution:**
  - root cause: one Match Lab resolution read the published round up to three times through the backend's short-lived cache (validation, snapshot, round view). A round change between reads could validate one round and analyse, stamp or store Your View against another;
  - correction: `ChallengeService.published_pair()` returns the round view and snapshot from one read. `resolve_target` validates that pair and passes it to `resolve(..., published=pair)`; `resolve` called without a pair makes one `published_pair()` read itself. Validation, frozen payload, round code, round id, fingerprint, model version, analysis stamp and Your View identity therefore come from the same round;
  - `resolve_target` also refuses a resolved context whose round is not the requested one (`CHALLENGE_GONE`);
  - no locking, cache, schema or framework changes.
- **Market selector** approved (§10.4).
- **Visual:** the Minimum Market Probability value clears its hint at all widths; locked fixture cards read normally (read-only, not unavailable), with selection still disabled. The homepage introduction now spans the full content width, aligned with the domestic card (its 760 px limit removed; wording and styling unchanged).
- **Carried forward to CP3A-4** (not implemented now):
  - replace outdated references to All Upcoming Fixtures in the Match Lab;
  - distinguish frozen snapshot times from latest-data calculation and observation times;
  - keep compact frozen-data source information for locked and settling challenge analysis;
  - the approved frozen/latest toggle and context-isolation requirements.

### 10.6 CP3A-4 as implemented

- **CP3A-3 accepted** by the owner after ChatGPT's independent review (`4e08e71`, `1648381`).
- **Intermittent browser test (carried to CP3A-4B):**
  - `test_ui_edge_refine.py::test_browser_outcome_colours_section_d_and_sliders` failed once in the CP3A-3 closure regression run (breakdown read straight after a slider move) and passed in three isolated reruns;
  - suspected but unconfirmed cause: CPU contention from screenshot jobs run alongside the suite;
  - to be verified explicitly at CP3A-4B; screenshot jobs are no longer run alongside regression runs.
- **Toggle "Use latest available data"** (`lab-latest`):
  - shown only for a match opened from a valid published challenge snapshot; OFF (frozen) on every new opening; kept across market changes, the address and the tab;
  - never shown for research matches, even when the match is also in the challenge;
  - independent of whether an independent Goal Model estimate exists.
- **Mechanism (existing context machinery):**
  - the Match Lab target carries `latest: true` for a challenge match viewed with the latest data (`lab_want`);
  - `resolve_target` validates the challenge target exactly as before, then returns the fixture's live context (store key `"<fixture>"`, `LiveContext`), never the frozen one (`"r:<round>:<fixture>"`, `RoundContext`); no latest data gives `LATEST_MISSING` (no fallback to frozen data);
  - `adjust` resolves from `lab-active`, so Your View changes land in the context shown; frozen and latest adjustments stay separate in browser and account storage and are restored on switching back (existing model-identity rules apply).
- **Competitive protection:**
  - `competitive(active)` (challenge context and not latest) gates the challenge strip and selection panel;
  - the reducer refuses every Match Lab selection action (`labpick`, `labremove`, `labreplace`, `confirmreplace`) unless `competitive(active)`, so stale controls cannot change a portfolio;
  - builder actions, drafts and picks are untouched; locked and settling rounds stay read-only in both modes (deadline rules in the reducer and services unchanged).
- **Source transparency:**
  - frozen: Weekly Challenge snapshot label, round and stored frozen time, and a note that current prices and estimates may differ; the footnote states the estimates are the frozen values;
  - latest: Latest available data label, the model calculation time and the selected market's odds observation time (or "No current bookmaker prices"), and a research-only note;
  - the page header no longer shows a statistics calculation time; "All Upcoming Fixtures" removed from the Match Lab components.
- **Published pair (display):** the research list's frozen line (`data_context`) reads one `published_pair()`.
- **Decision for review:** the bookmaker reference card in the frozen context still shows the latest collected prices, with its existing note ("not the round's frozen odds"); the frozen odds stay in the selection panel. Unchanged in CP3A-4.

### 10.7 CP3A-4 closure refinements (owner, 27 Nov 2026)

- **Bookmaker reference follows the context:**
  - frozen: built only from the validated snapshot (`lab_context.frozen_odds`): per market, the frozen consensus reference odds, the frozen margin-adjusted market probabilities, the number of independent bookmaker groups and the last observation before the freeze. The card is titled "Frozen Bookmaker Market Reference" with the snapshot's own times. Individual bookmaker prices are not stored with the snapshot, so none are shown; a market the snapshot does not hold is shown as unavailable. Nothing is derived from probabilities and no latest price is substituted. The model-vs-market comparison and Your View's value check use the same frozen reference;
  - latest-data and research-origin analysis keep the latest reference and observation times unchanged;
  - no snapshot schema change, migration, provider request or new data collection.
- **Supplementary statistics:** form, head-to-head and league positions stay latest data in both contexts; in the frozen context Section B states that they are supplementary latest data and never change the frozen estimates, probabilities or odds (they never did: the frozen payload and its model context come from the snapshot).
- **Source information:** left-aligned in both contexts (already so at `57d6bc9`; the centred image was a pre-fix capture), checked in the browser at three widths.
- **Stale-event investigation (findings; plan of record for review):**
  - the inconsistent mobile image (toggle on, frozen labels) was captured before the toggle's response: the browser flips the checkbox at once, the server's response sets the toggle and the analysis together. It was taken by an earlier version of the test whose wait matched text present in both contexts; every committed screenshot waits for the context-specific marker;
  - a Match Lab selection made while the toggle's response is pending is made on the frozen panel the participant can see, with `lab-active` still frozen: a legitimate frozen action, validated by the existing services (ownership, snapshot, eligibility, deadline). Once the response arrives, `lab-active` is latest and the reducer refuses any such action, even if the panel's removal is still pending;
  - **confirmed minor defect, corrected with owner approval at CP3A-4 closure:** a market change sent while the toggle's response was still in flight carried the pre-toggle `lab-target`, so the response rendered the frozen view and turned the toggle off (state consistent, the participant's switch lost). Correction in `lab_want`: a new opening (`lab-request` among the triggering inputs, read from `ctx.triggered_prop_ids` because the address and the request can arrive together) always starts frozen; for the same challenge match, any real event takes the mode from the toggle's current value; the initial call after a page load keeps the remembered mode. Regression tests cover both switching directions, new openings (including with the previous match's toggle on), tab restoration and rapid switching; the delayed-response browser probe now ends in the chosen mode in every case
  - **second intermittent browser test (carried to CP3A-4B):** `test_phase8_cp2b1.py::test_browser_match_lab_states_and_adjustments` timed out once in the closure regression run (research-only path, waiting for a restored adjustment after switching matches) and passed in three isolated reruns and in every earlier run; it shares the timing exposure of ML-01 and is to be verified explicitly at CP3A-4B;
  - **CP3A-4B carry-forward (owner):**
    - the ML-01 investigation and correction must cover frozen/latest switching as an additional trigger of the stale-adjustment race;
    - verify both recorded intermittent browser tests (`test_ui_edge_refine.py::test_browser_outcome_colours_section_d_and_sliders`, `test_phase8_cp2b1.py::test_browser_match_lab_states_and_adjustments`) and investigate whether either is ML-01 rather than assuming CPU contention or browser timing;
    - complete the scheduled full cumulative local suite and CI, including real Supabase Auth coverage;
    - no screenshot jobs alongside regression runs;
  - Your View: frozen and latest adjustments cannot move between contexts (separate keys and rows; `adjust` writes the context named by the `lab-active` value it was sent with, and `update_detail` sets the analysis and `lab-active` in one response). The toggle is one more trigger of the existing ML-01 stale-store race (an in-flight rebuild can restore an earlier adjustment within one context); recommended for the CP3A-4B ML-01 fix and its regression test.

### 10.8 CP3A-4B as implemented (ML-01 and cumulative testing)

- **CP3A-4 accepted:** `57d6bc9` (implementation), `8af420f` (closure refinements), `fb1873d` (lost-toggle correction). Limitations carried here: ML-01, both intermittent browser tests, the full suite, CI and real Supabase Auth.
- **ML-01 root cause (established):**
  - every rebuild of the analysis (`update_detail`, after a match, market or frozen/latest change, or a return to the tab) renders the Your View inputs from `lab-store` *as it was when the rebuild was requested*;
  - when the rebuilt inputs mount, Dash calls `adjust` with every input listed as changed (26 inputs, observed in the browser); `adjust` took the first (`ctx-home-slider`) as a user edit and saved it;
  - so an edit still in flight when a rebuild was requested (its response applied before the rebuild's) was overwritten by the older rendered value, in the browser store and, for signed-in participants, in the account (`lab_persist.save`);
  - affected paths: `update_detail` → mount → `adjust`, for match, market, frozen/latest and tab-return rebuilds. A signed-in rebuild could also write an older copy of the store back (`lab-store` from hydration).
  - Dash 4.5 behaviour confirmed from the renderer and in the browser: a Your View action taken *while* a rebuild is pending is held and merged into the mount call (listed first); an executing call of the same callback is dropped when a newer one is requested; responses whose outputs were replaced are dropped.
- **Second cause found during the investigation (rapid successive changes):** each slider step sends its own `adjust` request computed from the store as it was when sent; under load those responses can be applied out of order, the older last, undoing the newer edit; and every response wrote the moved slider back, so a late echo also moved the slider back and later steps started from the older value (steps lost).
- **Correction (smallest that removes both causes; no new architecture, no persistence or calculation change):**
  - the store carries a revision (`_rev`, raised by every saved edit); `update_detail` records which context and revision it rendered (`lab-rendered`);
  - a rebuild's mount call (recognised exactly: it lists both reset buttons, which no participant action does) is never treated as the first input's edit:
    - rendered from the current store, the inputs equal the stored state, so nothing happens, unless an input differs: that is a participant's edit Dash merged into the call, and only it is applied;
    - rendered from an older store, it re-shows the stored state of the context shown, never saving and never writing the store, so its own late response cannot hide a newer edit;
    - a reset click merged into the call (listed first) is applied, as before;
  - Your View edits run one at a time: a gate rendered with the inputs (`{"type": "lab-gate"}`, a client-side mirror of `lab-store`) is an input of `adjust`, so Dash holds a new edit until the previous one's store update is applied, and merges held edits into one with the latest values; `adjust` ignores the gate's own trigger;
  - an edit made with a slider no longer writes that slider back (its box and every derived value still update; text boxes keep their server formatting);
  - hydration writes the store only when the account actually changes it;
  - model identity and compatibility rules, calculations, contexts and storage keys are unchanged; a cross-match "late response" guard was tried and removed (Dash 4.5 drops responses whose outputs were replaced, and the guard's dependency chain delayed edits).
- **Regression evidence:** callback-level tests (rebuild after a concurrent reset, unchanged store, never saving, merged click, merged edit, edit revision, frozen/latest isolation, hydration) and a delayed-response browser test. Before the correction the browser test fails (Section B back to `+0.25` after the rebuild and after returning to the tab; a merged clear lost); after it, all pass. Three existing assertions that the moved slider is echoed back now assert that it is not (`no_update`), with its box assertions unchanged.
- **Intermittent browser tests:**
  - `test_ui_edge_refine.py::test_browser_outcome_colours_section_d_and_sliders` (box `+0.15`, breakdown `+0.10`): **cause established** — out-of-order concurrent edit responses (above). Reproduced deterministically once the slider echo was removed (the echo had masked it as lost steps); with four CPUs saturated the pre-fix code failed 6/10 and the corrected code passes 10/10. A test synchronisation fix also waits for the breakdown's expected state before reading it (assertion unchanged);
  - `test_phase8_cp2b1.py::test_browser_match_lab_states_and_adjustments` (B's input not `2.50` within 30 s): **cause not conclusively established.** Ruled out: a late previous-match response painting the next match (Dash drops it; pre-fix passed with A's adjust delayed 2.5 s) and CPU load alone (12/12 pre-fix passes saturated). Its wait is for the expected state, so the failure was a real end state; the mechanisms found (mount overwrite, out-of-order edits) are the ones that can produce one, and both are corrected. Corrected code: 10/10 passes saturated.
- **Delayed-response browser coverage (permanent, `test_phase8_cp3a4b.py`):** ML-01 itself, a merged clear, rapid successive slider steps, a market change during a pending toggle, rapid switching, tab restoration, reopening a challenge match (frozen) and unchanged picks and draft; 5/5 passes with four CPUs saturated.

## 11. Testing and browser acceptance (proportionate)

- **Route and label tests:** tab order and labels (including Training Ground), the redirects, `/lab`, `/learn`, the active tab and unknown paths (CP3A-1).
- **Context tests** (callback level):
  - frozen to latest to frozen restores the frozen adjustments;
  - latest adjustments never appear frozen, and the reverse;
  - stamps differ;
  - latest mode never changes the snapshot fingerprint or the draft;
  - selection controls are absent in latest mode;
  - the toggle is absent for research fixtures;
  - the toggle is present for model-absent frozen fixtures (States B and C) and **stays present in latest mode** (C1).
- **Restoration identity (C2):** restore only within the same round, snapshot fingerprint and context. A changed round or snapshot shows the empty state.
- **Status tests:** the five messages, including a final round with no successor.
- **Research only tests:** the button text and list follow the toggle; switching keeps picks, filters and drafts; the no-challenge default.
- **Preservation tests:** the round trip Portfolio Build → Match Lab → Portfolio Build keeps the list, page, filters, picks and draft.
- **Guest and signed-in journeys (C3), on authorised disposable environments only:**
  - browser-persisted and account-persisted adjustment isolation;
  - restoration of valid frozen adjustments;
  - latest-data adjustments preserved;
  - no silent transfer between contexts;
  - no portfolio mutation from latest-data analysis;
  - portfolio and draft preserved across navigation.
- **Browser** (condition-based waits; 390, 768 and 1280 px): no horizontal scroll.
- **Full suite and CI** at CP3A-4B and CP3A-5.

## 12. Database, migration, security and historical compatibility

- **No migration and no schema change.** Contexts, stamps and storage are unchanged [V].
- **Security:**
  - latest mode is read-only;
  - the account-side Your View contexts are resolved on the server (`your_view._resolve`) [V];
  - the redirect hook issues same-site relative redirects only.
- **History:** historical rounds, snapshots, submissions and saved adjustments are untouched. Old `/challenge` and `/?fixture=` links redirect.

## 13. Risks and remaining decisions

- **Risks:**
  - the re-pointed route callbacks and `allow_duplicate` outputs: covered by route and browser tests;
  - the extra Match Lab toggle could confuse users: mitigated by the frozen default and the explanatory text;
  - the historical acceptance scripts in `tools/e2e_*` still open `/challenge`; they keep working through the redirect.
- **Decided (Part B):** the Research only defaults (§6).
- **Outstanding from CP3A-1:**
  - direct Match Lab deep-link fixture restoration: CP3A-3;
  - Training Ground educational content: CP3B;
  - legacy acceptance script routes: CP3A-5;
  - signed-in participant browser acceptance: CP3A-5.
