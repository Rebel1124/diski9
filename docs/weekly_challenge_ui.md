# Weekly Challenge prototype UI (Phase 6B.1)

**Status:** interactive prototype on branch `feature/weekly-challenge-ux-refinement`.
* Phase 6B.1 refines the Phase 6B prototype (`556eb24`) after product-owner
  playtesting.
* It has no accounts, stored entries, settlement or live competition.
* Leaderboards and history are labelled demonstration data.

## 1. Routes and journey

| Route | Page |
|---|---|
| `/` | Screener and Match Lab. It now has a **Matches: Weekly Challenge / All upcoming matches** view, a portfolio progress strip and a **Weekly Challenge panel** for the selected match. It stays mounted, so its state survives navigation. |
| `/challenge` | Two steps: **1 Build portfolio → 2 Review & Submit**. |
| `/challenge/me` | My Challenge. |
| `/leaderboards` | This week and Championship (demonstration data). |

**Journey:**
* Open **Build portfolio** (or arrive from the Match Lab).
* **How to play** is an expandable panel: open for new users, closed once
  there's a draft or a confirmation. It holds the two goals, the bucket and
  credit table, the points schedule and the rules (everything from the former
  Overview).
* A compact **status strip** shows the round, status, deadline (live rounds),
  eligible fixtures and leagues, and the snapshot time. The demo strip has a
  "Leave demo" button.
* The builder's main area switches between **Choose matches** and **Portfolio
  analysis**, while the tracker stays visible.
* **Review & Submit** is the safeguard against accidental submission, followed
  by a **"You're in!"** confirmation.

When the live round isn't playable, the page explains why (stale odds, missing
markets, too few fixtures, infeasible pool, no fixtures) and offers the labelled
demonstration round.

**Layout decision — analysis panel.** I chose a two-state switch in the builder
over a drawer or a separate page:
* it uses the same column, so desktop and mobile behave identically;
* the tracker (with its remove buttons) stays beside the analysis, so changing a
  pick updates the analysis immediately;
* a drawer would hide the tracker on phones.

## 2. Builder

**Fixture cards**
* The three market groups sit side by side on wide screens: Match result (Home,
  Draw, Away) · Both teams score (Yes, No) · Total goals (Over, Under 2.5). They
  stack below 1180 px.
* Each outcome shows:
  * a short name;
  * the frozen odds;
  * **Mkt** (market chance, one decimal; it decides the bucket);
  * **D9** (Diski 9);
  * a bucket tag in the tracker colours (Foundation green, Balanced blue,
    Challenger amber).
* **States:** a selected outcome gets a filled tag with ✓ and a highlighted
  border. Disabled outcomes show "⊘ Not eligible / Match used / Bucket full /
  Can't complete" (text, icon and tooltip, never colour alone). Your View appears
  in the tooltip.
* **Band-safe rounding:** a percentage that would round across a band boundary
  (59.96% → "60.0%" in Balanced) is shown with more decimals.
* Each card links to the **Match Lab** (`/?fixture=<id>` selects the match and
  the Weekly Challenge view).

**Filters** (one row on wide screens, wrapping below): League · Date · Market ·
Bucket · Team · **Available only**.
* Available only hides outcomes that can't be selected now; selected outcomes
  stay visible.
* Filters never change the portfolio.
* Matches are listed 10 per page.

**Tracker** (sticky on desktop; above the list on phones, with a fixed bottom bar
"F 2/4 · B 0/3 · C 2/2 · 4/9 · View"):
* **Probability source** selector: Market / Diski 9 / Your View, with "What do
  these mean?" beside it.
* Each bucket is expandable and shows:
  * picks made and required;
  * credits;
  * a segmented bar;
  * **All succeed x%** and **pays y cr**, labelled "(so far: n of N picks)" until
    the bucket is complete;
  * its picks (match, outcome, chance under the chosen source, odds, ✕ remove).
* The Diski 9 row shows the same for all picks so far.
* At 9/9 it adds **Get 100+ back** and **Expected gross**.
* Changing the source changes chances only; odds and payouts are fixed.
* **Overflow fix:** rows have `min-width: 0` and wrap long names, so removing a
  pick can no longer push rows outside the card.

**Responsiveness.**
* *Root cause of slow taps:* every pick re-rendered the whole match list (~70
  pattern-matched buttons). Dash then rebuilt its callback graph for the whole
  layout, including the mounted Screener: about 2.5 s per tap.
* *Fix:* the list now re-renders only on filter or page changes. A pick updates
  the visible buttons' `className`, `disabled` and `title` in place. Every tag
  variant is rendered once and CSS shows the one for the state. Taps now take
  about 0.5 s end to end.

## 3. Portfolio analysis (builder → Portfolio analysis)

All values come from `diski9.challenge.analysis` and the eight-state engine, for
the selected source:
1. **Will you get your 100 credits back?** A doughnut of 100+ back / something
   under 100 / nothing back (they sum to 100%), with expected gross and net, and
   a plain-language note that the expected payout is an average, not a promise
   or the most likely result.
2. **Possible payouts.** Each bucket's own payout if it completes, then a
   horizontal bar per bucket-success state (No buckets complete → … → All nine
   correct), ordered by total payout from the top. Identical totals are named. An
   aligned eight-state table is in an expander.
3. **How many predictions might you get right?**
   * a histogram of P(exactly k correct) for k = 0–9 (Poisson-binomial over all
     512 combinations);
   * the expected and most likely counts;
   * choosing a count (bar click or the 0–9 selector) shows that count's
     conditional average payout, range and chance of 100+;
   * an expander with the conditional average payout by count (separate chart, no
     dual axis);
   * a full table with combinations C(9, k) and unconditional contributions;
   * an explanation that completing buckets, not the number correct, decides the
     payout.

**Removed from the participant UI:**
* Explore Your Bucket Risk (hypothetical sliders);
* the survival curve, exact-payout toggle, range toggle and payout slider.

The engine calculations (`payout_distribution`, `probability_at_least`) and the
education maths stay, with their tests.

## 4. Screener and Match Lab integration

**One portfolio.**
* The session store `ch-session` holds the draft for the whole app.
* Builder buttons (`pick`/`remove`) and Match Lab buttons (`labpick`, `labremove`,
  `labreplace` → confirm) go through one reducer (`apply_action`) and the same
  engine validation:
  * one prediction per match;
  * bucket membership and capacity;
  * snapshot identity;
  * round availability and deadline;
  * eligibility;
  * exact remaining feasibility.
* Edits in either place appear in the other immediately.

**Weekly Challenge view.**
* Lists exactly the frozen pool: same fixture ids, same snapshot.
* Its value column shows the **frozen reference odds** of the chosen market and
  "✓ <outcome>" for portfolio matches.
* *All upcoming matches* is the original Screener.
* The view defaults to Weekly Challenge when a live round is playable.
* Matches outside the pool can be analysed but not selected.

**Match Lab panel.** It sits above the Match Lab for the selected match. It lists
the match's Challenge outcomes:
* market, bucket tag, Market, Diski 9 and Your View chances, frozen odds;
* **Add to Weekly Challenge**, **✓ Added · Remove**, or **Replace <current
  pick>**. Replace is offered only when the engine would accept the swap, and it
  asks for confirmation. Otherwise a reason is shown.

There's no automatic redirect. A progress strip ("Weekly Challenge (demo) F 3/4 ·
B 0/3 · C 2/2 · 5/9 · Open builder") sits under the Screener filters.

## 5. Your View

**Definition.**
* It's computed with the Match Lab's own functions: `normalise_state` →
  `user_estimates` → `adjusted_probabilities`, which is Goal Model 1.0's `markets`
  for the adjusted expected goals.
* It's keyed by fixture id in the existing Match Lab store `lab-store`.
* Matches without adjustments use the unadjusted Diski 9 probability; the panel
  marks them "*" and says so.
* Adjusting expected goals updates all seven outcomes consistently.

**What it never changes:** official buckets, reference odds, eligibility,
allocations, payouts, points, other participants' views, or the stored Goal Model
output.

**Persistence:** `lab-store` keeps the existing Match Lab behaviour (browser
memory). Adjustments survive navigation within the app but not a page refresh. A
confirmed submission stores the Your View values used at that moment.

## 6. Snapshots, drafts and confirmed submissions

**Root cause of disappearing submissions:**
* the live snapshot was rebuilt every 15 minutes, giving it a new fingerprint;
* on the next action the reducer cleared the draft **and** `submitted`;
* switching between demo and live also reset the state.

**Fixes:**
* **One official snapshot per round.** Once a live snapshot passes the opening
  checks it is pinned for its round (ISO week) for the life of the process. An
  unplayable snapshot is retried every 15 minutes. Freshness is still assessed
  at the snapshot time.
* **Draft revalidation.** On a different snapshot, each pick is checked:
  * picks whose outcome, odds and market chance are unchanged, and which still
    fit, are kept;
  * the others are removed from the draft and listed in a **Please review**
    banner with the reason (removed from the sheet, odds or market chance
    changed, no longer eligible or fits).
  * Nothing moves to new odds silently, and the whole draft is never cleared
    automatically.
* **Frozen confirmed submission.** `submitted` records:
  * round id, snapshot fingerprint and time, configuration version;
  * each pick: key, bucket, match, outcome, frozen odds, market, Diski 9 and Your
    View probabilities, and whether Your View was adjusted;
  * Market / Diski 9 / Your View estimates;
  * the maximum payout and the confirmation time.
  * A snapshot change, mode change, refresh or failed resubmission never changes
    or deletes it.
* **Resubmission is explicit.** "Replace my confirmed portfolio" only replaces
  the record after every check passes; a failure keeps the old one.

**Session behaviour:**
* `ch-session` (draft, step, notes, confirmed submission) and `ch-prefs` (source,
  view) use `sessionStorage`: they survive a refresh in the same tab and are
  cleared when the tab closes.
* Filters and the match-list page reset when the builder re-renders.
* The confirmation modal stays until closed.

**Phase 6C:** server-side round records with publication, deadline and frozen
snapshots; persistent submissions; snapshot lifecycle (republication and
corrections).

## 7. Review & Submit, My Challenge, Leaderboards

**Review & Submit:**
* Market / Diski 9 / Your View cards (Your View only when adjusted): get 100+
  back, nothing back, expected gross;
* the nine picks with bucket, Market, Diski 9 and odds;
* the allocation and snapshot;
* the explicit confirm or replace button;
* the "You're in!" modal with **View My Challenge**.

**My Challenge:**
* compact round status: Unavailable / Not started / Draft in progress /
  Confirmed / Locked;
* an inspectable confirmed portfolio (source cards and nine picks by bucket);
* an illustrative championship summary: points, rank, recoveries and rate,
  top-ten finishes, best weekly finish, progress;
* a ten-round timeline (recovered / not recovered / not entered / to play);
* the history table in an expander.
* Practice and void rounds never count. Invented demo history is labelled
  separately from the user's own confirmed portfolio.

**Leaderboards:**
* a "You (demo)" summary card;
* a podium of the top three **positions**: ties share a place, nothing is
  reordered (ranks 1, 1, 3 show a shared 1st and a 3rd, with no 2nd);
* aligned tables;
* championship rounds completed and remaining;
* practice, void and "Void — Refunded" labels as before.

## 8. Testing and checking

* **Tests:** `tests/test_challenge_ui.py` and `tests/test_challenge_analysis.py`
  (512-state reconciliation, sources, bucket stats).
* **Screenshots:** `docs/screenshots/weekly_challenge_ux_refinement/` (desktop
  1366 × 900 at 2×, iPhone 13, iPad).

Run the app, then open http://127.0.0.1:8050/challenge:

```bash
uv run diski9 serve
```
