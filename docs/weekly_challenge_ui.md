# Weekly Challenge prototype UI (Phase 6B)

**Status:** an interactive prototype on branch `feature/weekly-challenge-ui`, built on
the Phase 6A.3 engines (`eb08a12`).
* It has no accounts, stored entries, settlement or live competition.
* Everything shown as a leaderboard or history is labelled **demonstration data**.

## 1. Routes

| Route | Page |
|---|---|
| `/` | Screener and Match Lab, unchanged. It stays mounted and is only hidden on the other routes, so its filters and Match Lab state survive navigation. |
| `/challenge` | The Weekly Challenge, as four steps in one page: **Overview → Build → Analyse → Review** (the stepper). |
| `/challenge/me` | My Challenge: the current draft, the demonstration submission, and an illustrative history. |
| `/leaderboards` | Two views: This week and Championship (demonstration data). |

* **Navigation:** a site bar (Screener · Weekly Challenge · My Challenge ·
  Leaderboards) uses `dcc.Location` and `dcc.Link`, with no page reloads.
* **Deviation from the Phase 5C routes:** there is no separate
  `/challenge/learn` page. *Explore Your Bucket Risk* is an expandable panel in
  the Build and Analyse steps, so it sits next to the decisions it explains.
* **Unknown routes** show a "Page not found" message with a link back.

## 2. Architecture

```
diski9.challenge (domain, pure)              diski9.app.challenge (Dash, presentation)
  config      ChallengeConfig broad60-432-v1   service.py    ChallengeService: frozen live/demo snapshots,
  structured  eligibility, progress,                         evaluation cache keyed by snapshot fingerprint
              selection_blocks, feasibility,   pages.py      layouts: overview, builder, analysis, review,
              exact evaluation, p_partial                    My Challenge, leaderboards
  roundsheet  RoundSnapshot, live builder,     components.py bucket chips, outcome buttons, tracker,
              demo loader, assess_round                      explorer, metric cards, tables, rules
  scoring     points-150-75-v2 (+ D-33 policy) charts.py     Plotly figures from engine distributions
  education   illustrative compounding maths   callbacks.py  router, state reducer (apply_action), renders
  demo        deterministic demo results
```

**Callbacks** only:
* manage UI state;
* call the engines;
* render the results.

**Calculations stay in the domain modules:**
* classification, eligibility, the reasons an outcome can't be added
  (`selection_blocks`), feasibility, validation, evaluation, distributions,
  scoring and the explorer maths;
* the chart module turns engine values into drawing coordinates only.

**Pattern-matching IDs.** Components on the challenge pages use pattern-matching
IDs (`{"t": name, "i": …}`), and callbacks use `ALL`, so a callback is a no-op
when its page isn't showing. This follows the existing app's single-layout
pattern; there are no Dash Pages.

## 3. Data and snapshots

**Live round** (`build_live_snapshot`):
* Read-only, from the local database, for a rolling 7-day window.
* It reuses the existing strict Challenge consensus unchanged:
  * fresh within 24 hours;
  * at least 3 independent bookmaker groups;
  * complete market;
  * pre-kickoff.
* It also reuses the existing margin adjustment (`implied`) and the Goal Model
  1.0 probability from the screener cache.
* Outcomes failing the consensus, or without a model forecast, are left off the
  sheet. Exclusion reasons are kept in `diagnostics`, so the page can say why a
  round is unavailable.
* The snapshot is frozen for 15 minutes per process.
* No API requests are made.

**Demonstration round** (`snapshot_from_research_pool`):
* The frozen 17 Nov 2026 research pool (60 fixtures, 6 leagues).
* It is always labelled as demonstration data: a ribbon on every step, a
  "Demo" status pill and "Practice only".
* **Limitation:** the pool has no per-outcome observation times. Its strict
  consensus was evaluated *as of* the pool time, which is therefore used as the
  observation time.

**Assessment uses the snapshot's own time.**
* `assess_round(snapshot, now)` runs the production opening checks (≥ 15
  eligible fixtures, ≥ 3 leagues, exact 4/3/2 feasibility) at the snapshot time.
* Only the live deadline (earliest kickoff − 15 minutes) uses the wall clock.

| Status | Shown when |
|---|---|
| `open` | the live round passes the checks and the deadline hasn't passed |
| `locked` | the live round is past its deadline (the builder is read-only and submission is disabled) |
| `demo` | the demonstration round |
| `no_round` | no fixtures in the window |
| `stale_odds` | prices exist but aren't fresh enough |
| `missing_markets` | no complete, independently priced markets |
| `insufficient` | fewer than 15 fixtures or 3 leagues |
| `infeasible` | no strict 4/3/2 portfolio can be built |

When the live round isn't playable, the overview explains why and offers
**"Try the demonstration round"**. In this environment the local odds were last
updated on 17 Nov, so the live state is **"Reference odds are out of date"**.

**No mixing of snapshots.**
* Each snapshot has a content fingerprint.
* The session draft stores it. A draft from another snapshot is never shown or
  evaluated, and the next action clears it with a notice.
* A prototype submission re-checks the fingerprint.

## 4. Session state

| Store | Storage | Holds | On refresh | On a new tab |
|---|---|---|---|---|
| `ch-session` | `sessionStorage` | mode (live/demo), snapshot fingerprint, selections (outcome keys), step, demonstration submission | kept | empty |
| `ch-explore` | memory | explorer slider values | reset to 70/50/30 | reset |
| `ch-flash` | memory | the last notice | cleared | cleared |
| `ch-fxpage` | memory | match-list page | page 1 | page 1 |

* There is no participant state on the server or at module level.
* Filters are component values; they reset when the Build step re-renders.

## 5. Builder

**Filters:** league, date, market, bucket, and a team search. Filters only change
the match list: the tracker always lists every selection with a remove button.

**Matches are listed 10 per page**, as in the Screener. Rendering all ~420
outcome buttons at once made the browser unresponsive (a Dash cost of having
many pattern-matched buttons); paging keeps every interaction instant.

**Each outcome shows:**
* its name;
* **Mkt**, the market chance that decides the bucket;
* **D9**, Diski 9's model, for comparison;
* the reference odds;
* a bucket-coloured edge;
* a tag: the bucket, "✓ Foundation" when selected, or the reason it can't be
  chosen.

| Reason (from `selection_blocks`) | Tag | Tooltip |
|---|---|---|
| ineligible (outside 20–95%, or the odds don't qualify) | Not eligible | outside range or odds rule |
| fixture already used | Fixture already used | remove the other pick first |
| bucket full | Bucket full | remove one to swap it |
| would block completion | Would leave the portfolio impossible to finish | the remaining matches couldn't fill the other buckets |

Picks are never replaced automatically. Tapping a selected outcome removes it.

**Tracker:**
* per-bucket segmented bars: Foundation x/4 (green), Balanced x/3 (blue),
  Challenger x/2 (amber), The Diski 9 (purple);
* credits per bucket and a total out of 9;
* a status line ("Still needed: …", or "can't be completed");
* the list of picks with remove buttons, plus "Clear all";
* **"Continue to analysis"**, enabled only when production validation passes.

On phones the tracker sits above the list, and a fixed bottom bar
("F 2/4 · B 0/3 · C 2/2 · 4/9 · View") keeps progress visible.

## 6. Explore Your Bucket Risk

An expandable panel labelled as an **educational illustration**, using
independent outcomes and fair odds.
* One slider per bucket, within its band: Foundation 60–95%, Balanced 40–59%,
  Challenger 20–39%. Defaults are 70/50/30, with a reset.
* **Per bucket** (`diski9.challenge.education.illustrate`):
  * legs and credits;
  * the individual chance;
  * combined chance = pᴺ (24.01% / 12.50% / 9.00% at the defaults);
  * fair odds = 1 / combined;
  * fair payout = credits × fair odds;
  * a meter, and dots per leg.
* The combined chance of all nine is shown below.
* Its state is a separate memory store. Its callback has no output to the
  portfolio store (a test checks this).

## 7. Analysis and charts

* **Estimate toggle:** Market estimate (default) or Diski 9 model, from
  `evaluate_market_and_model`.
* **Cards:**
  * the chance of getting 100+ credits back (primary);
  * something back but under 100 (`p_partial`);
  * nothing back;
  * expected return, gross and net, with "an average, not a promise".
* **Accumulators** (each bucket and The Diski 9): picks, credits, combined odds,
  chance under the chosen estimate, and the payout if it wins. Switching the
  estimate changes only the chances and expected values; payouts are unchanged
  (tested).
* **"All eight possible outcomes"** is an expandable state table.
* **"About these numbers"** covers the two estimates, independence, expected
  return, and why payouts don't change.

**Your Payout Probability** (Plotly, from engine values only):
* **At least this payout:** a step function built from explicit vertices, with
  no smoothing.
  * It starts at 100% at 0 credits.
  * The vertical drops sit at attainable payouts.
  * Closed dots mark P(≥ v) at each attainable v, so a threshold equal to a
    payout includes it.
  * A dashed marker at 100 credits, plus a diamond, sit at exactly the summary
    recovery chance.
* **Exactly this payout:** narrow bars per distinct payout. Equal payouts are
  aggregated by the engine; the masses sum to 1.
* **Focus on buckets / Full range** change only the x-axis range (focus shows
  every payout except the all-win one).
* **"Explore a payout"** is a slider showing P(≥ x) from the engine.

## 8. Review and prototype submission

The Review step shows:
* the nine picks, with bucket, match, prediction, market chance and odds;
* the allocation;
* the round, snapshot time and configuration;
* market and model estimates side by side;
* risk notes.

**"Confirm demonstration submission"** re-checks everything before recording the
portfolio in the browser tab:
* the round is playable and not locked;
* the snapshot fingerprint matches;
* the configuration version matches;
* `validate_portfolio` passes (nine distinct fixtures, strict 4/3/2, eligibility
  at the snapshot time).

The confirmation says it is **not a competition entry and nothing is stored on a
server**. Editing afterwards is allowed; confirming again replaces it.

## 9. My Challenge and leaderboards

**My Challenge** shows:
* the current draft (n/9) and round status;
* the confirmed demonstration submission (recovery chance under both estimates,
  expected return);
* an **illustrative history**, with a ribbon saying it's invented. It lists
  weekly results for "You (demo)", plus championship points, recoveries and
  top-ten finishes.

**Leaderboards** use `diski9.challenge.demo`: deterministic invented results,
scored by the production engine (points are never hard-coded).

**Weekly view**, with a week selector:
* shared ranks shown with "=" (two tied first on 150; next is 3rd);
* a three-way tie at 10th (90 each; next is 13th on 75);
* "Void — Refunded" rows listed separately;
* banners for the practice (DEMO-P1) and void (DEMO-V1) weeks.

**Championship view:**
* progress "Round 7 of 10 completed";
* shared positions (=6);
* the tie rule printed under the table.

## 10. D-33 (proposed; pending product-owner confirmation)

`AllVoidPolicy.REFUND_UNRANKED` is now the default policy of `points-150-75-v2`.
An entry whose nine selections are all void:
* is refunded 100 credits;
* is **excluded from competitive ranking**, so other ranks are computed as if
  it were absent;
* earns 0 points, no recovery and no top-ten finish;
* is not counted in the championship;
* is displayed separately as **Void — Refunded**.

It still counts toward the five valid entries fixed at the deadline, so it never
turns a round into a practice round. A genuine 100.00 recovery is unaffected.

The other policies (`score_as_settled`, `no_points`) remain available. **D-33 is
not marked approved.** D-32 (partially voided rounds) remains for Phase 6C; there
is no majority-void threshold.

## 11. Running and checking

```bash
uv run diski9 serve
```

Then open http://127.0.0.1:8050/challenge.

* **Screenshots:** `docs/screenshots/weekly_challenge/` (desktop 1366 × 900 at
  2×, and iPhone 13), captured with Playwright from a real browser session using
  a valid demonstration portfolio.
* **Tests:** `tests/test_challenge_ui.py`, including a phone-viewport browser
  journey.

## 12. Outstanding before a live competition

* Accounts and identity (D-01), hosting (D-02) and the database (D-03).
* Persistent round sheets and submissions with server-side deadlines (Phase 6C+).
* Settlement and void rules (D-08, D-32) and confirmation of D-33.
* Live leaderboards and championship persistence.
* Real-pool validation of the scoring incentives (D-29).
* A scheduled odds refresh, so live rounds open with fresh prices.
