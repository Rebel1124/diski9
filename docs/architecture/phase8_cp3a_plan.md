# Phase 8 CP3A: Portfolio Build, navigation and context management (implementation plan)

*Plan approved by the owner on 27 Nov 2026, with the refinements below (record [§15.8](phase8_implementation.md)). It is implemented one checkpoint at a time, and each checkpoint is authorised, reviewed and accepted separately.*

- **Status:**
  - **CP3A-1** (routes and navigation) is implemented, awaiting review (§10.1);
  - **CP3A-2 onwards are not authorised.**

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
| **Training Grounds** (formerly Learn) | `/learn` | Route and tab; the approved Learn content follows in CP3B |
| Leaderboards | `/leaderboards` | Unchanged |

- **Training Grounds [D, 27 Nov 2026]:**
  - the Learn tab is renamed **Training Grounds**, in keeping with the football theme, and moved before Leaderboards;
  - it keeps all approved Learn functionality, content and future enhancements;
  - the internal route `/learn` and identifiers are unchanged.

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
- **Default when no challenge is available [recommended, for confirmation at CP3A-2]:**
  - the toggle **starts ON** only when there is no open, locked or settling round, i.e. no challenge information to show;
  - it is a starting value only (no forced switch, no automatic state change while the user is on the page), and the stored preference wins once the user has set it;
  - with a locked or settling round it starts OFF, so challenge information stays reachable;
  - the user's existing portfolio is never discarded.
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
| CP3A-3 | Match Lab without selectors, last-fixture restore with identity (C2), empty state, back link, filter persistence | 3–4 |
| CP3A-4 | Frozen/latest toggle (C1), timestamps, unavailable or stale handling, selection controls only when frozen (D1) | 2–3 |
| CP3A-4B | ML-01: regression test first, smallest correction (§10.2) | 2–3 |
| CP3A-5 | Integration, guest and signed-in browser journeys at 3 widths (C3), screenshots, full CI, docs | 5–7 |
| **Total** | | **19–26 h** |

- **Why +1 h on the provisional 18–25 h:** the local Research only toggle (control, tooltip, button text, two mounted lists, preserved state and the no-challenge default) costs about 1 h more than the secondary link it replaces. The signed-in journeys (C3) fit inside CP3A-5, because per-checkpoint browser checks now absorb some of its earlier scope.
- **CI:** CP3A-1 to CP3A-4 run focused local tests, regressions, lint and browser checks, and commit with `[skip ci]` (owner instruction, 27 Nov 2026). The full CI suite runs at CP3A-4B and CP3A-5. Intermediate acceptance is not CP3A acceptance.
- **Order:** the agreed order is kept. CP3A-4B follows CP3A-4 because ML-01 lives in `update_detail`, which CP3A-3/4 change. Fixing it afterwards tests the final callback.
- **STOP after every checkpoint:** independent review and owner acceptance.

### 10.1 CP3A-1 as implemented

- **`NAV`:** Portfolio Build `/`, Match Lab `/lab`, My Challenge `/challenge/me`, Training Grounds `/learn`, Leaderboards `/leaderboards`. The longer label was verified at 390, 768 and 1280 px: one line, no horizontal scroll.
- **Router:**
  - `/` (and the `/challenge` alias) renders the existing Weekly Challenge builder unchanged;
  - `/lab` shows the existing Screener and Match Lab unchanged;
  - `/learn` shows a plain Training Grounds page;
  - unknown paths show "Page not found" with a link back to Portfolio Build.
- **Path checks moved from `/` to `/lab`:** `update_detail`, `match_lab_panel`, `screener_strip`, `data_context` and `open_fixture`, which now acts only on `/lab`. `sync_round_views` moved from `/challenge` to `/`.
- **Visibility:** `screener-root` starts hidden, so the Match Lab never flashes on the home page.
- **Server redirect:** a Flask `before_request` hook, registered after the account hooks, redirects GET/HEAD requests for old addresses.
- **Unchanged:** the analytical behaviour, the universe toggle (removed in CP3A-3/4), state stores and the account and guest behaviour. There are no new component IDs apart from the Learn page content, and no database change.

### 10.2 CP3A-4B: ML-01 [D4]

- Reproduce the stale-adjustment race with a focused regression test, and show it fails before the fix where practical.
- Establish the exact mechanism, then make the smallest sufficient correction: stale callbacks must not apply adjustments to the wrong fixture, baseline or frozen/latest context.
- Historical adjustment compatibility is preserved. There is no broad callback or persistence refactor.

## 11. Testing and browser acceptance (proportionate)

- **Route and label tests:** tab order and labels (including Training Grounds), the redirects, `/lab`, `/learn`, the active tab and unknown paths (CP3A-1).
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
- **For confirmation at CP3A-2:** the Research only default when no challenge is available (§6).
