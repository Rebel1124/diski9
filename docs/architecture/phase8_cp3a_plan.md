# Phase 8 CP3A: Portfolio Build, navigation and context management (implementation plan)

*Plan for owner and ChatGPT review, 27 Nov 2026. **Not authorised for implementation.***

Decisions this plan implements: [`phase8_implementation.md`](phase8_implementation.md) §15 (governs), with §11 OD-4 where not superseded.

Markers used below:
- **[V]** verified in the current code (commit `7c7cf22`);
- **[R]** recommendation;
- **[A]** assumption;
- **[Q]** open question for the owner.

## 1. What already exists and is reused

| Mechanism | Where | Reuse |
|---|---|---|
| Routing | `dcc.Location(id="url")` (`app/app.py`); the router callback in `app/challenge/callbacks.py` (`route`) shows `screener-root` on `/` and renders `ch-root` for `/challenge`, `/challenge/me` and `/leaderboards` [V] | Kept; routes re-mapped (§2) |
| Navigation | `NAV` (`callbacks.py:27`): Match Lab `/`, Weekly Challenge `/challenge`, My Challenge, Leaderboards [V] | Becomes the five approved tabs |
| Screener list (All upcoming) | `screener-root`, kept mounted and hidden by style; table plus mobile cards (`results_payload`, `fixture_card`); filters, market selector, threshold, paging (`page`, `threshold-pref`, `selected`) [V] | Reused as the research list (§6) |
| Weekly Challenge builder | `pages.challenge_shell`, `stage_body`, fixture cards (`fixture_list`, `ch-fxpage`), tracker, review, submit, replace, withdraw, adoption (`adopt_ui`) [V] | Reused unchanged as the domestic challenge list |
| Universe toggle | `RadioItems id="universe"` (`app.py:388`), values `challenge` and `all` [V] | **Removed** from the UI. Its value is derived from the list the fixture was opened from (§4) |
| Match Lab detail | `lab.render_detail`; the `update_detail` and `adjust` callbacks (`app.py`), currently rendered under the `/` list [V] | Moved to the Match Lab tab, unchanged |
| Context resolution | `lab_context.resolve(service, data, fid, universe)` → `LabContext(kind="round"/"live", key, r)`; frozen key `r:<round>:<fixture>`, live key `<fixture>` [V] | Basis of the frozen/latest toggle (§4) |
| Your View storage | Browser `lab-store` (session) keyed by context; account rows per context (`your_view` service: `LiveContext` / `RoundContext`); stamps with source-aware identity (CP2B.1) [V] | Unchanged |
| States A/B/C | `lab.starting_point`, `market_fit` (CP2B.1) [V] | Unchanged |
| Round state | `rounds.current_round`, `persist.published()`, `availability()` with `RoundStatus` [V] | Extended for status messaging (§7) |
| Session state | `ch-session` (session: round, selections, stage), `ch-prefs` (session: source, filters), `lab-store` (session) [V] | Holds the list origin and the last fixture (§5) |

## 2. Navigation and fixture-list structure [R]

| Tab | Route | Content |
|---|---|---|
| Portfolio Build | `/` | Homepage introduction and cards; the domestic challenge list (`/?list=challenge`, the existing builder); the domestic research list (`/?list=research`, the existing Screener table, §6) |
| Match Lab | `/lab` | Detail of the last selected fixture. No selectors |
| My Challenge | `/challenge/me` | Unchanged (Current, History, Rewards) |
| Leaderboards | `/leaderboards` | Unchanged |
| Learn | `/learn` | Route and tab only; content in CP3B |

- `/challenge` redirects to `/?list=challenge`, so existing links and history links keep working.
- **Homepage:**
  - the agreed wording and one football icon from the existing icon set (`app/icons.py`), in teal, sized responsively, with no animation;
  - a collapsed How to Play;
  - the **Domestic Weekly Challenge card (teal)**: championship name, round code, status line (§7) and **Build domestic portfolio**;
  - the **European Match Analysis card (gold)** is **not rendered** until CP2B.2 is accepted (§8).
- Lists open beneath the cards on the same page. Tablet and mobile stack them (§9).

## 3. Removing the Challenge Mode toggle and duplicate selectors [R]

- Remove the `universe` RadioItems from the layout. The list choice comes from the card or link the user tapped (`?list=`), kept in `ch-prefs`.
- Match Lab loses its list and filters, which move to Portfolio Build. Match Lab renders `render_detail` only.
- The Weekly Challenge **selection panel** inside Match Lab (pick, remove and replace buttons; `ACTION_OF`) is kept **only in the frozen challenge context** [Q1].
- Nine callbacks test `path == "/"` and several use `allow_duplicate` (§9.1 of the record). Each is re-pointed to the new routes and covered by a route test. This is the main regression surface.

## 4. Frozen / latest context switching and adjustment isolation [R]

- **Context source.** A fixture opened from the domestic challenge list resolves with `universe="challenge"`, which is today's frozen path [V]. A fixture opened from the research list (or, later, the European list) resolves with `universe="all"`, the live path [V].
- **Toggle "Use latest available data".**
  - Rendered in the Match Lab header only when `LabContext.kind == "round"`, meaning a valid frozen snapshot exists. Existence of an independent model is irrelevant: CP2B.1 already builds frozen State B and C contexts.
  - Turning it on re-resolves the **same fixture** with `universe="all"`. Off returns to `"challenge"`. Its value is per fixture and session-scoped.
- **Isolation, mostly verified:**
  - frozen and live Your View already use different browser keys and different account rows [V];
  - stamps differ by context, including the CP2B.1 input identity [V];
  - so switching back restores the frozen adjustments untouched. CP3A adds tests, not mechanisms.
- **Competitive data is never modified:**
  - the latest view renders only the live payload and live odds;
  - the challenge selection panel is hidden in latest mode [Q1];
  - submission and the portfolio read only the published snapshot (`service.outcomes_for`), which the Match Lab cannot write [V].
- **Unavailable or stale latest data:**
  - fixture absent from the live data: an explicit "Latest data unavailable for this match" message, with the toggle still able to return to frozen;
  - stale odds: shown with the existing stale labels; State B needs fresh inputs, otherwise State C (CP2B.1);
  - frozen inputs are never substituted into the latest view.
- **Timestamps (stored, never hard-coded):**
  - frozen: `snapshot.snapshot_at`, labelled as the publication snapshot;
  - latest: `data.snapshot().cache_calculated_at` (model) and the displayed markets' observation times (`DisplayedMarket.snapshot_at` / age), labelled "latest collected", never "live".

## 5. Preserving portfolio state, filters and navigation context [R]

- Portfolio Build stays mounted while hidden (the existing `screener-root` pattern). The builder's state lives in `ch-session` [V]. Builder filters move into `ch-prefs`; they are not stored today (§9.1 of the record).
- `ch-prefs` gains `list` (challenge or research), `last_fixture` (id plus list origin) and the per-fixture latest toggle.
- **Match Lab opened from the tab:**
  - it restores `last_fixture` if it is still valid: still present in its origin list, and for the challenge context still in the published snapshot;
  - otherwise it shows the empty state "Choose a match in Portfolio Build" with a link.
- A **"← Back to Portfolio Build"** link returns to `/?list=<origin>`. The list, page, filters, picks, draft and adjustments are untouched because nothing is re-created.

## 6. Domestic research access when no challenge is published [R, Q2]

**Recommendation:** a secondary text link inside the **Domestic Weekly Challenge card**, "Research upcoming domestic matches (not part of the challenge)". It opens the existing Screener table as `/?list=research`.

- It is always present, and visually prominent when no challenge is open, locked or settling.
- The list carries a persistent "Research only" banner: selections are not possible and nothing here enters a portfolio.
- Fixtures opened from it use the latest data, with no toggle.

Why this option:
- it reuses the existing list and live path with no new architecture;
- it is not a mode toggle: it is a different, clearly labelled list reached by a link;
- it needs no new tab;
- the challenge list itself never mixes research fixtures.

Alternative considered: showing the research list only when no challenge exists. It is simpler visually, but research would disappear during challenge weeks, so it is not recommended.

## 7. Snapshot notices and challenge status messaging [R]

- **Domestic list notice:** "Odds, probabilities and model estimates were fixed when this challenge was published on {snapshot_at, local time} so every participant plays under the same conditions." The frozen Match Lab context uses the same text.
- **Card and list status**, from `current_round` and the next prepared week:

| State | Message (draft) |
|---|---|
| Upcoming | "The next challenge is expected {publication target, local}." (Shown only when a future week is being prepared; never promised.) |
| Unavailable | "No competitive challenge this week. There are not enough eligible matches (for example during an international break). Research upcoming matches below." |
| Open | "Open until {deadline, local}." |
| Locked | "Entries locked. Matches in progress." |
| Settling | "Results are being settled." The previous round's provisional results stay on My Challenge. |

- This closes the gap noted in §15.5: today a final round with no successor still shows "Round locked".
- **[V]** The publication target comes from `prepare.publication_target`, and the status from round and draft rows. Both are read-only.

## 8. European entry point before CP2B.2 acceptance [R]

- **The gold card is not rendered** until CP2B.2 is accepted (no dead button).
- **[R]** Gate it in code on the presence of European competitions in the registry (`odds_competitions()` / the league registry gains 2 and 3 only in CP2B.2). This needs no feature flag or configuration.
- CP3A keeps the card layout able to hold a second card, so CP2B.2 only adds the card and its list.

## 9. Desktop, tablet and mobile

- **390 px:** cards stacked; the existing card list and sticky tracker; Match Lab full width with the toggle under the title; the back link at the top.
- **768 px:** cards side by side when two exist.
- **1280 px:** the existing table and side tracker.
- No horizontal scroll at 390, 768 or 1280 px (existing acceptance criterion).

## 10. Checkpoints, dependencies and effort [R]

| Step | Content | Hours |
|---|---|---|
| CP3A-1 | Routes and tabs, `/challenge` redirect, `/lab` route, re-pointed path checks | 3–4 |
| CP3A-2 | Homepage introduction, icon, domestic card, status messaging, research link and list banner | 3–4 |
| CP3A-3 | Match Lab without selectors, last-fixture restore, empty state, back link, filter persistence in `ch-prefs` | 3–4 |
| CP3A-4 | Frozen/latest toggle, timestamps, unavailable or stale handling, selection panel only when frozen | 2–3 |
| CP3A-5 | Tests, browser journeys at 3 widths, screenshots, docs | 5–7 |
| **Total** | | **16–22 h** |

- **Dependencies:** none outstanding (CP2B.1 accepted). CP3B builds on CP3A's Match Lab route. CP2B.2 adds the gold card and list.
- **STOP:** visual review by the owner, then ChatGPT review.

## 11. Testing and browser acceptance (proportionate)

- **Route and label tests:** tab order and default, the `/challenge` redirect, `/lab`. Update the existing route tests (5 files and 2 tools, §9.3 of the record).
- **Context tests** (callback level):
  - frozen to latest to frozen restores the frozen adjustments;
  - latest adjustments never appear frozen, and the reverse;
  - stamps differ;
  - latest mode never changes the snapshot fingerprint or the draft;
  - the selection panel is absent in latest mode;
  - the toggle is absent for research fixtures;
  - the toggle is present for model-absent frozen fixtures (States B and C).
- **Status tests:** upcoming, unavailable, open, locked and settling messages from round fixtures, including a final round with no successor.
- **Preservation tests:** the round trip Portfolio Build → Match Lab → Portfolio Build keeps the list, page, filters, picks and draft. The tab restores the last valid fixture; an invalid one shows the empty state.
- **Browser** (condition-based waits only; 390, 768 and 1280 px):
  - a guest builds four picks, opens Match Lab, toggles latest, adjusts, toggles back and returns, with picks kept;
  - research list access when no round is open;
  - no horizontal scroll.
- **Full suite and CI.**

## 12. Database, migration, security and historical compatibility

- **No migration and no schema change.** Contexts, stamps and storage are unchanged [V].
- **Security:** latest mode is read-only. The account-side Your View contexts are already resolved on the server (`your_view._resolve`) [V].
- **History:** historical rounds, snapshots, submissions and saved adjustments are untouched. Old `/challenge` links redirect.

## 13. Risks, open questions and decisions

**Risks:**
- the re-pointed `path == "/"` callbacks and `allow_duplicate` outputs: covered by route and browser tests;
- **ML-01 stale-adjustment race** (Phase 6 register, required before private Beta) lives in `update_detail`. CP3A touches that callback but does **not** fix ML-01 unless the owner adds it [Q4];
- the extra Match Lab toggle could confuse users: mitigated by the default (frozen) and the explanatory text.

**Owner decisions:**
- **[Q1]** In latest mode, hide the challenge selection panel? Recommended: yes, so selections are only made against frozen odds.
- **[Q2]** Domestic research access as recommended in §6: an always-available secondary link in the domestic card opening the research-only list.
- **[Q3]** Status message wording in §7 (drafts).
- **[Q4]** Include the ML-01 fix in CP3A, about +2–3 h, since the same callback changes? Otherwise it stays a pre-Beta item.
- **[Q5]** Confirm that the gold card stays hidden (not "coming soon") until CP2B.2 is accepted.
