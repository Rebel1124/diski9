# Phase 8 CP3A-R: product simplification and technical reassessment

*28 Nov 2026. Research and recommendations only. Nothing here is approved or implemented.*

- Authorisation: record [§15.15](phase8_implementation.md).
- The decision currently in force is P8-FROZEN (record §15.2), reopened for investigation only.
- Every number below comes from local data, source inspection or documents already on record. No provider request, protected database access or production change was made.

**Evidence markers**
- **[S]** source code, with file and line references;
- **[R]** a research run in this checkpoint, reproducible with the commands in §K;
- **[D]** an existing document;
- **[A]** an assumption or judgement.

## Contents

- A. Executive summary
- B. Current architecture
- C. The twelve items
- D. Fixture-window research
- E. Goal Model sensitivity
- F. Recommended methodology
- G. Homepage and navigation
- H. Implementation plan
- I. Revised Phase 8 estimates
- J. Decision register
- K. Reproduction, research plan and limitations

---

## A. Executive summary

**1. The real problem is the entry window, not the price model.**
- **Today's rule** sets one common deadline per round: the round's earliest kickoff minus 15 minutes [S `rounds.py:634`].
- **The evidence [R]:** in **every one** of the 120 historical weeks in which a round could open, the earliest kickoff was on **Friday**, mostly 18:00–21:00 SAST.
- **The result:** publication at Friday 08:00 SAST leaves participants about **10–13 hours on a working Friday**. Saturday and Sunday arrivals cannot enter at all.
- **Why items 1, 2 and 6 only matter with rolling entry:** under today's rule nobody submits on Saturday, so nobody uses a stale Friday price. Those concerns appear only once later entry is allowed.

**2. Two coherent ways to fix it.**

| | **Option S: Saturday–Sunday universe** | **Option R: rolling Friday–Sunday entry with daily price editions** |
|---|---|---|
| How | Keep the frozen snapshot and the common deadline. Move the fixture window to Saturday–Sunday, so the deadline moves to Saturday at about 13:15–14:15 SAST | Fixed entry close on Sunday, per-fixture cutoffs, one new immutable price "edition" each morning, dynamic buckets per edition, re-review if a reviewed price changes |
| Entry window | Friday 08:00 to Saturday midday, about 29 h, including a weekend morning | Friday 08:00 to Sunday 12:00 SAST, about 52 h |
| Weeks a round opens [R] | 118 of 120 | 120 of 120 |
| Price staleness at entry | at most about 1 day (the provider updates odds once a day) | under 1 day |
| Backend change | a new schedule version; no schema or methodology change | multi-snapshot rounds, an automatic edition builder, per-entry cutoffs, new lock and settlement references, a migration |
| Active effort | **about 8–12 h** | **about 38–53 h** on top of the shared simplifications |

**3. Recommendation [A].**
- **Adopt Option S, the shared simplifications and irrevocable submissions for private Beta.**
- **Keep Option R as the documented next step**, to build if Beta participants show they want Sunday entry.
- Option R is feasible and the owner's preferred direction, but it roughly doubles the remaining Phase 8 effort. Most of its benefit, weekend entry, comes from Option S at a fraction of the cost and risk.
- If the owner prefers Option R now, the design in §F.2 is the smallest coherent version found.

**4. Friday–Sunday versus Friday–Monday (item 11).**
- Removing Monday **never changed whether a round could open**: 120 of 120 weeks either way [R]. Monday fixtures are about 5% of the Friday–Monday total.
- The only material difference is for late Sunday arrivals under rolling entry.
- **Recommendation:** Option B (Friday–Sunday) under Option R; Saturday–Sunday under Option S. Monday fixtures move to research in both.

**5. Goal Model (item 7): retain 1.1 as it is.**
- **The labels are swapped.** Production is strength `k_s` = **12** and tempo `k_t` = **96**. The request read them the other way round.
- **Configuration D** (`k_s` 18, `k_t` 90) makes 1X2 log loss worse, by **+0.0038** (95% CI +0.0028 to +0.0048).
  - This holds in both the selection and the confirmation periods.
  - Six of the eight leagues are worse.
  - It is more under-confident: calibration slope 1.22 against 1.07.
- The whole effect comes from the **strength** change (12 → 18). The **tempo** change (96 → 90) moves no probability by more than 0.5 percentage points.
- D fails five of the six pre-registered criteria.

**6. Simplifications worth approving whatever is decided about pricing:**
- remove the Research only toggle;
- remove the frozen/latest toggle (frozen for challenge fixtures, latest for research);
- an automatic weekday/weekend experience;
- a rolling 7-day research list in place of the 14-day date picker;
- the two-card homepage;
- irrevocable single submissions.

**7. Corrections to the brief, found in the source:**
- There is **no operator per-entry void, refund or correction** today. Only round invalidation, result corrections, finalise and reopen exist [S `corrections.py:269,422,451,547`].
- **Publication is manual**: a person runs `round publish`. The scheduler only prepares drafts [S `prepare.py:17`].
- The window is Friday 00:00 UTC to Tuesday 00:00 UTC (Friday 02:00 SAST to Tuesday 02:00 SAST), not a SAST rule.
- **Prices do not refresh after publication**, and there is no Saturday–Monday refresh at all [S `refresh.py:287`].
- **The provider's pre-match odds update about once a day**, at 02:00–03:30 UTC. This was observed on EPL only [D `phase6c6_stage_e1b_design.md` §1.3]. So "latest available pricing" means **daily** prices, not continuous.
- **The API-Football Pro plan expires on 14 Dec 2026 with no automatic renewal** [D cost log]. Any latest-pricing design depends on renewing it.

---

## B. Current architecture (what the proposals touch)

| Area | How it works today | Key references |
|---|---|---|
| Schedule | Versioned, immutable rows in `round_schedules` (v1 to v3). Fields: window rule, publication rule, 15-minute buffer, eight eligible competitions, config `a3-432-v1`, contiguity guards | [S] `app_0001:245,819`; `app_0004:53`; `app_0009:70`; `app_0008` |
| Draft round | The scheduler creates it 78 h before the target and runs readiness checks. **It never publishes** | [S] `rounds.py:431`; `prepare.py:17,734` |
| Publication | Manual, under the `round.publish` permission. The snapshot must be at most 1 h old. Opening checks D-28: at least 15 fixtures, at least 3 leagues, exact 4-3-2 feasibility. Sets the deadline and `settle_cutoff_at` | [S] `rounds.py:523-679,748`; `structured.py:410` |
| Snapshot | **One per round** (`round_snapshots.round_id` is UNIQUE). Offers hold odds, market and model probabilities, bucket and groups. Fingerprinted. Rows are refused once the round leaves draft | [S] `app_0001:312`; `snapshots.py:59-145`; `roundsheet.py:86`; `app_0003:56` |
| Consensus | At least 3 bookmaker groups, quotes no older than 24 h, complete markets, median, margin-adjusted | [S] `odds/consensus.py:49-273`; `config.py:97` |
| Feasibility | Exact bipartite matching (`_match`), with `portfolio_feasible`, `selection_blocks` and `portfolio_progress` | [S] `structured.py:296-471` |
| Odds refresh | Tuesday–Friday sweeps for the unpublished draft only. About 22 requests per sweep, about 110 per normal week, against 7,500 a day | [S] `refresh.py:106,287`; [D] e1b §5 |
| Drafts | `portfolio_drafts` keyed by (user, round), storing the snapshot fingerprint. Guest adoption refuses a fingerprint mismatch | [S] `drafts.py:200,251`; `adoption.py:113` |
| Entries | `entries` is UNIQUE per (round, user). `submissions` is versioned and idempotent. `submission_selections` copies the odds, probabilities, bucket and groups, with a **foreign key to `snapshot_offers`**. Confirm, replace and withdraw are allowed until the deadline | [S] `entries.py:231,370`; `app_0001:456` |
| Locking | One common `deadline_at` (set once), enforced by DB triggers and `_check_open`. `lock_round` locks every valid entry at once and re-checks buckets against `snapshot_offers` | [S] `app_0001:92`; `rounds.py:798-908` |
| Settlement | Reads the per-submission copies through `locked_submission_id`. Rule V3 compares kickoffs with the round `deadline_at`. Results use `kickoff_at_publish` | [S] `settlement.py:216`; `settle.py:248`; `results.py:172` |
| Championships, leaderboards, rewards | Ordered by `deadline_at`. Rewards read the frozen legs | [S] `championships.py:275,394`; `achievements.py:182` |
| Match Lab | Two contexts: `round` (frozen, `r:<round>:<fid>`) and `live`, plus the `#lab-latest` toggle. Your View is keyed by context and snapshot. ML-01 gates | [S] `lab_context.py:34-219`; `app.py:571,876`; `app_0004:40` |
| Homepage | One domestic card. States: open, locked, settling, upcoming, unavailable. `#research-only` is stored per browser session | [S] `home.py:28-280`; `callbacks.py:781` |
| Research list | Date range picker defaulting to today + 14 days; 21-day cache horizon | [S] `app.py:437`; `refresh.SCREENER_DAYS` |

**Already in place for per-entry records (item 6) [S]:**
- every submission row already stores its accepted odds, market and model probabilities, bucket, bookmaker groups, snapshot ID, and config, calculation, model and rules versions;
- settlement already reads those copies.

The blockers to per-entry pricing are narrower:
- the one-snapshot-per-round constraint;
- the foreign key to `snapshot_offers` (it works as long as each price edition is its own snapshot row);
- the lock-time bucket re-check;
- references to `deadline_at` in V3 and in championship ordering.

---

## C. Findings for each item

Tags used below:
- **(S)** needed for Option S;
- **(R)** needed for Option R;
- **(both)** applies under either option.

### Item 1: Latest available pricing (R)

- **Current:**
  - Prices are frozen at publication.
  - Refresh stops at publication.
  - The provider itself updates pre-match odds about once a day [D].
- **Proposed:** centrally refreshed prices for future challenges.
- **Evidence:**
  - Under today's rule nobody can submit after Friday evening (§A.1), so a stale price is never used. Stale prices only become a problem if entry is extended (item 4).
  - Because the provider updates once a day, the sensible refresh is **one sweep after the daily update, plus one confirmation**: Saturday and Sunday at 04:15 and 05:15 UTC. Hourly polling would re-read identical data [D e1b table, "Intensive" risk].
- **Feasibility:** high. The existing refresh `plan` and `_league_step` run unchanged. Only the "stop at publication" rule changes for the edition builder.
- **Operational cost:**
  - About 44 extra requests on each of Saturday and Sunday, so about 90 a week. Total scheduler use stays under 5% of the 7,500-a-day quota.
  - **No incremental cost while the Pro plan ($16 a month) is renewed.** No new services.
- **Risks:**
  - The provider skips a daily update. Mitigation: the previous edition stays valid within freshness, then entry pauses (safe failure).
  - The update cadence is measured only on EPL, mid-week.
  - The plan expires on 14 Dec.
- **Freshness rule:** keep the 24 h requirement. A morning sweep keeps an edition fresh until the next morning's sweep. If a sweep fails, the existing hourly retry slots apply. Relaxing it to about 30 h is an option for the owner, not a recommendation.
- **Alternative:** Option S (no repricing; prices at most about 1 day old by the deadline).
- **Recommendation:** **defer** (approve only together with Option R).

### Item 2: Dynamic bucket classification (R)

- **Current:** buckets are frozen in the snapshot, and the lock re-checks them against `snapshot_offers` [S `rounds.py:798`].
- **Proposed:** buckets from the latest margin-adjusted market probability. A3 bands and the 4-3-2 rule are unchanged.
- **Feasibility:**
  - With price editions, each edition classifies its own offers using the existing `CFG.classify`. So "dynamic" means "per edition", without new code paths.
  - `_match` and `portfolio_progress` are reused unchanged.
  - A draft selection whose bucket changes or becomes ineligible is **flagged, never removed**. The tracker shows "Price update: this pick is now Balanced", and review is blocked until the participant resolves it.
- **Risks:** a draft built on Friday may need edits on Saturday. That is an inherent cost of the proposal, so the messaging matters.
- **Recommendation:** **defer** (part of the Option R package).

### Item 3: Irrevocable submissions (both)

- **Current:** confirm, replace (resubmit) and withdraw are all allowed until the deadline [S `entries.py:231,370`].
- **Proposed:** one final confirmation; no withdraw, replace or re-entry.
- **Feasibility:** high, and it removes code paths rather than adding them:
  - the UI ids `askwithdraw`, `confirmwithdraw` and `cancelwithdraw`;
  - the active-entry resubmit;
  - the `replace=True` service path;
  - the withdraw wording.
- **What stays:** `withdraw_entry` stays for history and tests on old rounds. The tables and `entry_events` are kept (insert-only). Old rounds are still read under their own rules.
- **Concurrency:** duplicate submission is already prevented by `UNIQUE(round_id, user_id)`, the entry `FOR UPDATE` lock and idempotency keys. None of this changes.
- **Adoption:** guests only ever have drafts, so adoption is unaffected.
- **Correction to the brief:** there is no per-entry operator void or refund to preserve. If one is wanted for Beta (for example, a support case), it is new work, about 4–6 h. It is not recommended now; round invalidation exists.
- **Effect on tests:** about 27 test functions and 12 files reference withdraw or replace. They need legitimate updates for future rounds; the historical behaviour tests stay.
- **Recommendation:** **approve.** Review plus an explicit confirmation step with clear wording is the safeguard.

### Item 4: Rolling Friday–Sunday submission window (R; Option S is the alternative)

- **Current:** a common deadline at the earliest kickoff minus 15 min, which is Friday evening in 100% of opened weeks [R].
- **Proposed:**
  - submit from Friday to Sunday;
  - each selection must have more than 15 min to kickoff at submission time;
  - a full A3 portfolio is required;
  - no Monday.
- **Evidence [R, §D]:**

| Arrival (Friday–Sunday window) | Weeks with at least 9 fixtures | Proxy feasible | Resample feasible |
|---|---|---|---|
| Saturday 15:00 SAST | 120 of 120 | 109 of 114 | 100% |
| Sunday 10:00 SAST | 116 of 120 | 94 of 108 | 96.5% |
| Sunday 15:00 SAST | 114 of 120 | 80 of 106 | 93.6% |

  - A Sunday-afternoon entry is technically possible most weeks, but in about a quarter of weeks the remaining pool is thin.
  - In the median Sunday-afternoon week only 14 fixtures remain, so the choice is narrow.
- **Required changes:**
  - `deadline_at` becomes the **entry close**, a fixed rule held in a new schedule version.
  - Per-selection kickoff checks at submission, in the service and in the database.
  - Each entry locks at submission.
  - `lock_round` runs at entry close, to fix the designation and privacy.
  - Settlement rule V3 compares against **the submission time**.
  - Championship ordering by `deadline_at` still works.
  - Draft expiry is unchanged.
- **Sunday cutoff:** **Sunday 12:00 SAST** is recommended. It is simple to explain and keeps the pool viable: the Sunday 10:00 figures above apply. After that, "Entries for this round have closed".
- **Time zone:** state every rule in SAST (`Africa/Johannesburg`, no daylight saving). The window becomes Friday 00:00 to Monday 00:00 SAST.
- **Fairness:**
  - Late entrants see Friday results and team news, but with daily editions they also pay the updated prices.
  - Competitors' picks stay private until entry close. Today leaderboards show only locked entries, and all entries lock together [S `leaderboards.py:167-171`]. With per-entry locking, leaderboards must also wait for the round's entry close: a small filter.
- **Recommendation:** **modify.** Use Option S for Beta (common Saturday deadline, frozen snapshot). Keep rolling entry, with the Sunday 12:00 close, as the post-Beta step. Approving rolling entry without items 1, 2 and 6 is **not recommended**: Sunday entrants would hold an information advantage at Friday prices.

### Item 5: Remove the frozen/latest Match Lab toggle (both)

- **Current:** challenge-origin matches can switch to latest data, with a separate context and its own Your View [S `app.py:571,876`].
- **Proposed:** no toggle.
- **Under Option S:**
  - Challenge fixtures always show the frozen snapshot.
  - Research fixtures always show latest data.
  - The context is chosen automatically from where the participant came from. This is already resolved by `lab_context.resolve_target`.
  - The "Use latest available data" control and its callback branch are removed. `wants_latest` always returns false for future rounds.
- **Under Option R:** the round context resolves to the **current edition**, so challenge data is effectively latest. Your View is keyed by (user, fixture, round) rather than by snapshot, so an adjustment survives a new edition.
- **Kept internally:** the `round` and `live` context kinds, the `r:<round>:<fid>` keys, the ML-01 gates, the frozen read-only view for locked and historical rounds, and stored adjustments.
- **Tests:** about 23 + 9 toggle tests (CP3A-4 and CP3A-4B) are retired or rewritten, because the requirement changes. The ML-01 regression tests stay.
- **Recommendation:** **approve**.

### Item 6: Submission-time analytical records (R)

- **Current:** each submission already copies the accepted odds, market and model probabilities, bucket, groups, snapshot and version identities [S].
- **Under Option R:**
  - Each edition is its own immutable snapshot row, so the existing foreign key from `submission_selections` to `snapshot_offers` keeps working.
  - The submission's `snapshot_id` names the edition.
  - **No duplication or new record type is needed.**
- **Gaps:**
  - Your View values are not stored with a submission. They don't affect scoring. Storing them is optional, about 2 h; not recommended for Beta.
  - Market-implied estimates come from the edition.
- **Review to confirmation:**
  - The confirm call carries the edition ID that was reviewed.
  - If the current edition differs **and** any selection's odds or bucket changed, the call is refused with "Prices were updated. Please review your portfolio again."
  - If nothing changed, it is accepted.
  - This is atomic inside the existing confirm transaction.
- **Recommendation:** **defer** (part of the Option R package). Under Option S no change is needed.

### Item 7: Goal Model sensitivity

**Retain 1.1 (`k_s` 12, `k_t` 96).** Details in §E.

### Item 8: Remove the Research only toggle (both)

- **Current:** `#research-only` (session storage) and `set_research`. The default depends on the challenge state [S `home.py:255`; `callbacks.py:781`].
- **Proposed:** removed. The experience is decided by the lifecycle (item 9). "Research versus challenge" stays an internal concept: which list, which context.
- **Effect:**
  - Removes one store, one callback and the tooltip.
  - About 18 tests in CP3A-2 are rewritten.
  - No account state exists, so there is nothing to migrate.
- **Recommendation:** **approve**.

### Item 9: Automatic challenge or research experience (both)

**Rule [A]:**
- If an open round exists **and** the participant has not submitted, the weekend card's primary action is **Build your portfolio** (challenge list).
- Otherwise the primary action is **Analyse matches** (research list).

**States:**
- **International breaks and insufficient fixtures:** detected automatically, because the round fails the D-28 opening checks. 23 of 147 season weeks were break or season-gap weeks with no big-five football, and none could open [R]. No manual calendar is needed.
- **Settlement:** a previous round awaiting settlement does not affect the transition; settlement status shows in My Challenge.
- **Already submitted:** shows "Your portfolio is in" with a link to My Challenge.
- **Too late:**
  - Option S: after the deadline.
  - Option R: after Sunday 12:00, or when no feasible portfolio remains (`portfolio_feasible` against the remaining fixtures).
  - Either way the card says so and offers research.
- **Provider outage:**
  - Option S: if no round is published, the card shows the existing unavailable state.
  - Option R: if no fresh edition is available, entry pauses with a message.
- **What already exists:** this reuses `challenge_status` [S `home.py:142`] with one extra input (has this user submitted?).
- **Recommendation:** **approve**.

### Item 10: Restrict the displayed fixture universe (both)

- **Current:** the research list defaults to today + 14 days, with a date picker. Provider odds exist only about one round ahead anyway [D].
- **Evidence [R]:**
  - Monday–Thursday domestic football is thin: a **median of 12 fixtures a week** across all eight leagues.
  - **34 of 147 weeks had none** (breaks and season gaps).
  - A strict Monday–Thursday research list would often be empty until European matches arrive (CP2B.2).
- **Recommendation: modify:**
  - **Research list:** a rolling **next 7 days** of fixtures, with no date picker.
  - **Weekend challenge list:** the round's fixtures only.
  - Ingestion and cache keep their longer horizons (operational preparation) but are not displayed.
  - Direct Match Lab links to a fixture outside the window still resolve. They are context-based, not list-based.
  - Drafts are untouched: they belong to the round.

### Item 11: Friday–Sunday versus Friday–Monday

See §D. **Recommendation:**
- Option B (Friday–Sunday) if Option R is approved.
- The Saturday–Sunday universe under Option S.
- Monday fixtures move to research in both.

### Item 12: Two-card homepage (both)

**Recommendation:** **approve the structure.** Layouts are in §G. The exact wording needs the owner's design approval.

---

## D. Fixture-window research

### D.1 Method and data

**Schedules [R]**
- Six leagues with provider odds, regular season, 147 season weeks (August 2023 to 13 November 2026, excluding June and July):
  - EPL and Championship from the local store;
  - La Liga, Ligue 1, Bundesliga and Serie A from the research store.
- **PSL and PSL 1st Division are never challenge-eligible today.** They have no provider odds [D]. They are counted only in the research volumes.
  - **This matters for a South African audience:** local football appears only in research.

**Arrivals**
- Five arrival times: Friday 08:00, Saturday 10:00, Saturday 15:00, Sunday 10:00 and Sunday 15:00 SAST.
- Eligible fixtures are those in the window with kickoff later than arrival + 15 min.

**Evidence types, kept separate**

| Type | What it is | Limitation |
|---|---|---|
| Schedule | Complete historical fixture availability | none material |
| Proxy | Point-in-time Goal Model 1.1 probabilities classified into A3 buckets, checked with the production `_match` | Model probabilities are less extreme than market ones. On the two real snapshots, 82–84% of outcomes land in the same bucket, but the model finds fewer Foundation picks (46 against 67). **The proxy is pessimistic.** It is available only once both teams have 2 matches and the competition 20, so 116 of 120 opened weeks can be assessed |
| Resample | Bucket profiles of the 60 fully priced fixtures in the real 17 Nov 2026 snapshot, drawn at random for each remaining fixture (the CP1 method) | One snapshot; ignores fixture-specific structure |
| Real | That snapshot, by arrival time | One weekend; assumes the Tuesday prices held |

**No historical point-in-time odds exist locally**: only three days of captures (15–17 Nov 2026). No claim below uses odds observed after an arrival time. **A reliable point-in-time assessment needs weekend-long captures of real consensus**, which the scheduler would collect passively once Saturday and Sunday sweeps exist (Option R), or an approved collection.

### D.2 Results (opened weeks; D-28 counts at Friday 08:00 SAST)

| | A: Friday–Monday (today) | B: Friday–Sunday | S: Saturday–Sunday |
|---|---|---|---|
| Weeks a round opens (of 147) | 120 | 120 | 118 |
| Opens and proxy feasible | 112 | 112 | 109 |
| Median fixtures at publication | 59 | 55.5 | 50 |
| 10th percentile / minimum | 43 / 25 | 39 / 22 | 35 / 14 |
| Real snapshot: fixtures, of which can fill Foundation | 60, 36 | 57, 35 | 54, 33 |

**Rolling arrivals (opened weeks, 120)**

| Arrival | A: median fixtures | A: proxy feasible | B: median fixtures | B: proxy feasible | B: fewer than 9 fixtures |
|---|---|---|---|---|---|
| Saturday 10:00 | 53.5 | 110 of 116 | 50 | 110 of 116 | 0 |
| Saturday 15:00 | 49 | 110 of 115 | 45 | 109 of 114 | 0 |
| Sunday 10:00 | 22 | 99 of 111 | 19 | 94 of 108 | 4 |
| Sunday 15:00 | 17 | 91 of 110 | 14 | 80 of 106 | 6 |

**Context**
- **Opening:** the 27 weeks that could not open are breaks, season starts and ends, and the Christmas period. Removing Monday changed **no** opening decision.
- **Monday's share:** 5.1% of Friday–Monday fixtures (399 of 7,853, all eight leagues).
- **Option S deadline** (earliest Saturday kickoff minus 15 min): Saturday 13:15 SAST in 53 weeks, 14:15 in 51, and later in the rest.
- **Today's deadline:** Friday, in 120 of 120 weeks, mostly 18:00–21:00 SAST.
- **Midweek (Monday–Thursday, eight leagues):** a median of 12 fixtures a week, with none in 34 of 147 weeks.

### D.3 Conclusions

1. **Option B is supported by the evidence.** Dropping Monday costs no opening weeks. It only narrows a late-Sunday entrant's pool: under the proxy, 75% of weeks are feasible at Sunday 15:00 against 83% with Monday. With an entry close at Sunday 12:00 SAST, the Sunday 10:00 figures apply (87% proxy, 96.5% resample).
2. **A Sunday entry opportunity is real but narrow.** The median is about 19 fixtures on Sunday morning and 14 in the afternoon. It is meaningful for one late entry, not for a considered portfolio.
3. **Option S keeps nearly all opening weeks (118 of 120)** and moves the deadline to Saturday afternoon. That is the cheapest way to make the challenge reachable at the weekend.
4. **No special Sunday rules, relaxed thresholds or extra competitions are needed under any option.**

---

## E. Goal Model sensitivity

The protocol was committed before the run: [`docs/research/phase8_cp3ar/goal_model_sensitivity_protocol.md`](../research/phase8_cp3ar/goal_model_sensitivity_protocol.md), commit `757a234`. Results are in `docs/research/phase8_cp3ar/goal_model_sensitivity.json` [R].

### E.1 Labels

- **Production:** `k_s` (strength) = **12** and `k_t` (tempo) = **96** [S `goal_model.py:60-61`].
- **Interpretation:** the proposal was read by value, i.e. 96 → 90 and 12 → 18.
- **Configurations:** A (12/96), B (12/90), C (18/96), D (18/90).
- **Label check:** the literal reading (`k_s` 90, `k_t` 18) was computed once as a check only. It is far worse: 1X2 log-loss Δ +0.030.
- **Prior search:** these values all lie inside the grid originally searched (`k_s` 0.5–32, `k_t` 8–∞) [D `goal_distribution_research.md`].

### E.2 Data

- Eight domestic leagues, 2023/24 to 2026/27 (to mid-November 2026).
- 8,474 fixtures available under the 1.1 rules, identical for every configuration. Paired comparisons throughout.
- The research harness reproduces the production `estimate` to 1.3e-15.
- **All of these seasons were examined before. This is not an untouched holdout.**

### E.3 Results

Differences are config − A, as log-loss Δ with 95% ISO-week bootstrap intervals.

| | B (tempo 90) | C (strength 18) | **D (18/90)** |
|---|---|---|---|
| 1X2, all seasons | −0.00002 [−0.00003, −0.00000] | +0.00379 [+0.00285, +0.00484] | **+0.00378 [+0.00283, +0.00482]** |
| 1X2, selection seasons | −0.00002 | +0.00389 | +0.00387 [+0.00265, +0.00511] |
| 1X2, confirmation seasons | −0.00001 | +0.00364 | +0.00363 [+0.00199, +0.00518] |
| BTTS, all seasons | −0.00003 | +0.00011 | +0.00008 [−0.00012, +0.00026] |
| O/U 2.5, all seasons | −0.00007 | +0.00003 | −0.00004 [−0.00040, +0.00035] |
| 1X2 Brier (A 0.6152) | 0.6152 | 0.6177 | 0.6177 |
| Home-win calibration slope (A 1.067) | 1.067 | 1.224 | 1.224 |
| Home-win ECE (A 0.0118) | 0.0116 | 0.0174 | 0.0173 |

**D's 1X2 Δ by league**

| League | Δ |
|---|---|
| EPL | +0.0049* |
| Championship | +0.0005 |
| PSL | +0.0043* |
| PSL 1st Division | −0.0008 |
| La Liga | +0.0060* |
| Ligue 1 | +0.0038* |
| Bundesliga | +0.0048* |
| Serie A | +0.0070* |

\* CI lower bound > 0.

**D's 1X2 Δ by season stage** (the smaller of the two teams' match counts)

| Band | Δ | CI excludes zero |
|---|---|---|
| 2–5 | +0.0054 | yes |
| 6–9 | +0.0061 | yes |
| 10–19 | +0.0043 | yes |
| 20+ | +0.0022 | yes |

- **By calendar month:** worse in every month, most in September to November and least in April and May.

**Stability**
- **D lowers the spread of estimated goals** (standard deviation of λ_home 0.393 → 0.350) and team round-to-round volatility (0.333 → 0.309 goals).
- **That is the mechanism of the loss:** stronger shrinkage pulls genuinely strong and weak teams towards average. That makes the model **more under-confident**: the slope rises from an already-above-1 value of 1.07 to 1.22.

**Size of change against A**

| Config | Home-win change: median | 90th percentile | max | Over 3 pp |
|---|---|---|---|---|
| B | 0.01 pp | 0.04 pp | 0.19 pp | 0% |
| D | 1.4 pp | 3.2 pp | 7.0 pp | 13% |

### E.4 Worked examples (production `estimate` function)

| Fixture | A: λ home – away, P(home) | D: λ home – away, P(home) |
|---|---|---|
| EPL 2026-09-19, Nottingham Forest v Coventry (both teams 4 matches) | 1.876 – 1.080, 56.0% | 1.756 – 1.151, 51.5% |
| PSL 2023-12-30, Mamelodi Sundowns v Polokwane City (13 v 15 matches) | 1.852 – 0.534, 69.3% | 1.664 – 0.593, 63.5% |
| La Liga 2025-04-14, Atlético Madrid v Valladolid (30 v 30 matches) | 2.858 – 0.590, 83.6% | 2.608 – 0.645, 79.4% |

- **What drives the change:** in each example it comes almost entirely from **strength**. In the Sundowns example, home strength drops from 1.607 to 1.458 under `k_s` 18. Tempo factors change in the third decimal place.
- **The pooled calibration slope shows these shrunk estimates are too cautious.** Larger strength shrinkage makes the under-confidence worse.
- Full intermediate values are in the JSON.

### E.5 Verdict against the pre-registered criteria

| Criterion | D result |
|---|---|
| G1 meaningful improvement | **fail** (a deterioration is demonstrated) |
| G2 consistency | **fail** (worse in both periods) |
| G3 BTTS / O/U | pass |
| G4 calibration | **fail** (ECE 0.0173 against a limit of 0.0168) |
| G5 leagues | **fail** (six leagues materially worse) |
| G6 early season | **fail** |

- B passes G3–G6 but shows no meaningful improvement (G1): it is practically identical to A.
- **Recommendation: retain Goal Model 1.1 unchanged.** No model version, migration or history work is needed.
- If greater stability is wanted for **presentation**, that is an education matter for CP3B, not a parameter change.

---

## F. Recommended integrated methodology

### F.1 For private Beta: Option S plus the shared simplifications (recommended)

**Week rhythm**
- **Monday–Thursday:** Learn & Research.
  - A rolling 7-day research list with latest data, Goal Model or market-implied analysis, Your View and Training Ground.
  - European analysis joins after CP2B.2.
- **Friday 08:00 SAST:** the round is published, as today: frozen snapshot, A3 buckets, D-28 checks, manual publication.
- **Fixtures:** Saturday and Sunday (window Saturday 00:00 to Monday 00:00 SAST). The research used UTC boundaries, Saturday 00:00 to Monday 00:00 UTC; no fixture in these leagues kicks off in the two-hour difference.
- **Entries:** from publication to the earliest Saturday kickoff minus 15 minutes, typically Saturday 13:15–14:15 SAST. The homepage shows the exact time.
- **Submission:** one final, irrevocable submission, after review and an explicit confirmation.
- **After the deadline:** the round locks, competitors' portfolios become visible, and matches play. Settlement and championships run as today.
- **Monday:** the homepage returns to Learn & Research automatically. My Challenge shows progress and settlement.

**Unchanged:**
- A3, nine distinct fixtures, 100 credits, scoring, championships and rewards;
- the frozen snapshot architecture, consensus, the 24 h freshness rule and the provider budget;
- the eight eligible competitions.

**Historical rounds:**
- The new schedule is a new `round_schedules` version (v4) with its own `active_from`.
- Earlier rounds keep v1 to v3 and their rules.
- **No transition framework is needed:** the schedule mechanism already provides this.

**Trade-offs**
- **Lost:** Friday fixtures (about 10% of today's universe) and Monday fixtures (5%) leave the challenge. Both stay in research.
- **Price staleness:** an entrant on Saturday morning uses Friday-morning prices. Because the provider updates once a day, that is at most one update behind.

### F.2 If Option R is chosen instead: rolling entry with daily editions (the smallest coherent design)

- **Window and fixtures:** Friday–Sunday (window Friday 00:00 to Monday 00:00 SAST). The fixture universe is fixed at publication.
- **Editions:**
  - Friday's publication is edition 1.
  - The scheduler builds edition *n* automatically each Saturday and Sunday morning, after the provider's daily update. It runs the same consensus, classification and feasibility checks and records a fingerprint.
  - An edition contains only fixtures from the published universe that have not yet started.
  - **Safe failure:** if an edition cannot be built, the previous one remains valid until its prices exceed 24 h; after that, entry pauses with a message.
- **Submission:**
  - Valid against the current edition: each selection more than 15 min before kickoff, full A3 under that edition's buckets.
  - Confirmation re-checks the edition that was reviewed (item 6).
  - The entry locks immediately and is irrevocable.
- **Entry close:** Sunday 12:00 SAST. `lock_round` then runs to fix the designation and privacy.
- **Drafts:** re-validated against each new edition. Changed or ineligible selections are flagged, never removed. Guest adoption re-validates instead of refusing on a fingerprint mismatch.
- **Settlement:** reads the copies as today. Rule V3 uses the submission time. Championships and rewards are unchanged.
- **Privacy:** leaderboards show entries only after entry close, because they otherwise show locked entries as soon as they lock.
- **Match Lab:** the round context resolves to the current edition. Your View is keyed by (user, fixture, round). No toggle.

**Schema (one migration):**
- `round_snapshots` gains an edition number, and the UNIQUE constraint becomes (round_id, edition);
- the snapshot guard allows a new edition while the round is open;
- schedule v4 adds an entry-close rule;
- a per-selection kickoff check is added to the submission insert guard.

**Operations:**
- about 90 extra provider requests a week, no new service, no infrastructure change;
- snapshot storage of about 1,300 offer rows a week (negligible);
- backups unchanged.

### F.3 A representative participant journey (Option S)

1. **Tuesday:** Lerato opens Diski 9.
   - The **Learn & Research** card is active ("This week: 14 matches to analyse").
   - The **Apply & Compete** card says "Next challenge opens Friday 08:00".
   - She studies a Championship midweek match in the Match Lab and nudges Your View.
2. **Friday 09:00:** Apply & Compete is active ("Challenge open — entries close Saturday 13:15").
   - She taps **Build your portfolio** and sees the weekend fixtures with A3 buckets.
   - She opens two matches in the Match Lab (challenge context, no toggle) and adds picks. Her draft saves.
3. **Saturday 10:30:** on another device her draft is there. She completes 4-3-2, opens **Review**, then **Confirm final portfolio**. She sees: "Final — this portfolio cannot be changed."
4. **Saturday 13:15:** entries close and the round locks. The leaderboard shows everyone's portfolios.
5. **Sunday night and Monday:** results arrive and My Challenge shows her progress. On Monday the homepage is back to Learn & Research. Settlement completes within the existing window, and championship points and rewards follow.

---

## G. Homepage and navigation (proposal; needs design approval)

**Layout:** two cards, side by side at 768 px and wider, stacked on phones with Learn first. The core message "100 Credits. 9 Picks. 1 Challenge." sits in the Apply card. Both cards are always visible; only the status line and the primary action change.

```
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ MONDAY–THURSDAY               │ │ FRIDAY–SATURDAY*              │
│ Learn & Research              │ │ Apply & Compete               │
│ Analyse upcoming matches,     │ │ 100 Credits. 9 Picks.         │
│ compare market and model,     │ │ 1 Challenge.                  │
│ set Your View.                │ │                               │
│ [status line]                 │ │ [status line]                 │
│ [Analyse matches]  Training ▸ │ │ [primary action]  How to play▸│
└───────────────────────────────┘ └───────────────────────────────┘
```

\* The Apply card reads "Friday–Sunday" under Option R.

| State | Learn card status and action | Apply card status and action |
|---|---|---|
| Monday–Thursday | "N matches in the next 7 days" · **Analyse matches** (primary) | "Next challenge opens Friday 08:00" · How to play |
| Friday, challenge open | "Research any match" · Analyse matches | "Open — entries close Sat 13:15" · **Build your portfolio** (primary) |
| Saturday (Option S, before the deadline) | as above | "Closes today at 13:15" · **Build your portfolio** |
| Saturday or Sunday (Option R, enough fixtures) | as above | "Open until Sun 12:00 — N matches still available" · **Build your portfolio** |
| Already submitted | as above | "Your portfolio is in" · **View My Challenge** |
| Insufficient fixtures (D-28 failed) | "N matches to analyse" · **Analyse matches** | "No challenge this weekend — not enough eligible matches" · none |
| International break | "N matches to analyse" (may be few; European after CP2B.2) · **Analyse matches** | "No challenge this weekend — international break" (inferred: no big-league fixtures) · none |
| Entries closed | "Research any match" · **Analyse matches** | "Entries closed — matches in progress" · View leaderboard |
| Previous round awaiting settlement | unchanged | the current week's state; settlement shows in My Challenge, not on the card |

**Rules:**
- No disabled button without a reason line.
- Training Ground, My Challenge and Leaderboard stay in the tab bar all week.

**Navigation label:**
- "Portfolio Build" no longer describes a homepage that also serves midweek research.
- **Recommendation: rename the first tab to "Home"** at implementation, if approved. "Portfolio Build" remains the name of the builder page.
- No tab is renamed in this reassessment.

---

## H. Implementation plan (if approved)

### H.1 Recommended path (Option S plus the shared simplifications)

| CP | Scope | Main components | Migration | Testing | Acceptance | Active h |
|---|---|---|---|---|---|---|
| **R-1 Weekend schedule and irrevocable entries** | Schedule v4 (Saturday–Sunday window, unchanged deadline rule); remove withdraw, replace and resubmit for future rounds; wording; privacy until lock (already the case) | `round_schedules` (data migration, new version row), `entries.py`, `persist.py`, `callbacks.py`, `pages.py`, `components.py` | data-only migration (insert v4) | Schedule resolution and contiguity; publication with a Saturday deadline; no withdraw path for v4 rounds; historical rounds still allow their old actions; concurrency tests unchanged | v4 rounds publish with a Saturday deadline; a submission is final; v1–v3 history reads unchanged | 8–12 |
| **R-2 Experience simplification** | Two-card homepage; automatic experience; remove Research only; remove the frozen/latest toggle; rolling 7-day research list; "Home" label if approved | `home.py`, `callbacks.py`, `app.py`, `lab_context.py`, `pages.py` | none | Rewrite the CP3A-2 and CP3A-4 tests for the new requirements; keep ML-01 regressions; status matrix (§G); browser at 390, 768 and 1280 px | Every §G state renders correctly; no toggles; history and locked rounds still show frozen data | 12–17 |
| **R-3 Integration and acceptance** | Update the CP3A-5 integrated test; full suite; CI; docs; screenshots | tests, docs | none | Full suite and full CI | CI green, owner review | 5–7 |
| **Total** | | | | | | **25–36** |

### H.2 Option R (alternative to R-1; in addition to R-2 and R-3)

| CP | Scope | Active h |
|---|---|---|
| **R-1A Rolling entry and lifecycle** | Schedule v4 with a Sunday 12:00 entry close, per-selection kickoff checks (service and DB), entry lock at submission, `lock_round` at close, V3 against the submission time, irrevocable entries | 12–16 |
| **R-1B Daily price editions** | Edition schema, automatic edition builder in the refresh and prepare tick, edition safety checks and monitoring, draft re-validation and flags, adoption re-validation, re-review on confirmation, Match Lab and Your View keyed by round, lock re-check per edition | 22–30 |
| **Migration and compatibility** | One migration (editions, entry-close rule, guards) with downgrade; historical rounds load through `load_snapshot` unchanged | inside R-1B, 4–7 |
| **Total with R-2 and R-3** | | **55–75** (R-3 grows to 7–9) |

**Effect on tests in both options:**
- Existing tests for accepted behaviour on **historical** rounds stay.
- Tests for withdraw, toggles and Research only are replaced, because the requirements change (owner approval needed).
- No historical regression coverage is removed.

---

## I. Revised Phase 8 estimates (active hours; planning, not commitments)

| Item | Earlier (§15.7) | Option S path | Option R path | Why |
|---|---|---|---|---|
| CP3A-R reassessment | — | about 6–7 (done) | about 6–7 (done) | This document and two research runs |
| CP3A-R implementation | — | **25–36** | **55–75** | §H |
| CP3B | 14–20 | 13–19 | 14–20 | Less to explain (no toggles, one context). Option R adds an "editions" explanation |
| CP2B.2 | 7–10 | 6–9 | 6–9 | European analysis joins the Learn card; no separate gold card |
| CP4 | 8–12 | 9–13 | 11–15 | Revised lifecycle journeys. Option R adds edition and rolling-entry acceptance |
| **Remaining after this reassessment** | 29–42 | **53–77** | **86–119** | |

**Test execution and external dependencies:**
- **CI time:** each full CI run takes about 35 min, with about 3–4 runs expected. The full local suite takes about 43 min.
- **External dependencies (not active hours):**
  - API-Football Pro renewal by 14 Dec (needed for any odds work);
  - the European verification on 7 Dec (separately approved) for CP2B.2;
  - owner design approval of §G.

---

## J. Decision register

### J.1 Decisions that can be approved independently

| # | Decision | Recommendation |
|---|---|---|
| J1 | Retain Goal Model 1.1 (`k_s` 12, `k_t` 96); reject D | **Approve** |
| J2 | Irrevocable single submission for future rounds | **Approve** |
| J3 | Remove the Research only toggle; automatic experience | **Approve** |
| J4 | Remove the frozen/latest toggle (frozen for challenge, latest for research) | **Approve** |
| J5 | Rolling 7-day research list; remove the date picker; display window separate from ingestion | **Approve** |
| J6 | Two-card homepage structure (wording to design approval) | **Approve the structure** |
| J7 | Rename the first tab "Home" | Owner's choice (recommended) |
| J8 | Per-entry operator void or refund (does not exist today) | **Defer** (not needed for Beta) |

### J.2 Decisions that must be approved together (choose one package)

| Package | Contents | Recommendation |
|---|---|---|
| **Option S** | Saturday–Sunday universe; common deadline at the earliest Saturday kickoff minus 15 min; frozen snapshot retained; schedule v4 | **Approve for private Beta** |
| **Option R** | Items 1, 2, 4 and 6 together: daily editions, dynamic buckets per edition, rolling Friday–Sunday entry with a Sunday 12:00 SAST close, per-selection cutoffs, re-review on price change, Friday–Sunday window (item 11 Option B) | Defer to post-Beta; build if participants show demand for Sunday entry |
| **Retain today's design** | Friday–Monday universe; deadline Friday evening | Not recommended: about 10–13 h on a working Friday |

**Not recommended in any form:** rolling entry with frozen Friday prices. Late entrants would gain an information advantage.

### J.3 Unresolved questions and evidence gaps

1. **The provider's odds update cadence at weekends**, and for leagues other than EPL. It was measured only in a short mid-week trial. This determines the value of Option R. It can be observed passively once weekend sweeps exist, or through an approved check.
2. **No historical point-in-time odds** exist. Bucket feasibility rests on a pessimistic model proxy, one real snapshot and resampling (§D.1).
3. **The API-Football plan expires on 14 Dec 2026** and needs a renewal decision.
4. **Under Option S:** confirm that losing Friday and Monday fixtures from the challenge is acceptable. The exact Saturday deadline varies week to week; it is shown on the card.
5. **Under Option R:** confirm the Sunday 12:00 SAST close and whether 24 h freshness is kept (recommended) or relaxed to about 30 h.
6. **Publication stays manual** under both options. Under Option R, editions after the first would be automatic, which is a new operational behaviour needing approval.
7. **The time zone for all rules is SAST:** the schedule window would move from UTC-defined to SAST-defined boundaries.
8. **The final wording** of the cards and status lines (§G).

---

## K. Reproduction, research plan and limitations

**Research plan (as executed; bounded and within authorisation)**
- **Reused:**
  - the CP1 harness (`scripts/research_phase8_cp1.py`);
  - the two local SQLite stores, copied read-only;
  - the committed real snapshots (`docs/research/weekly_challenge_risk/pool_weekend.json` and `pool_fortnight.json`);
  - the production `_match`, `A3_432_V1` and `goal_model.estimate`.
- **Analyses:** the four Goal Model configurations under a pre-registered protocol; window and arrival feasibility (§D).
- **Effort:** about 6–7 h active; each run takes under 20 seconds.
- **Boundaries respected:** no provider requests, no protected databases, no new dependencies, no production change, no test changes.

**Commands**

```bash
uv run python tools/research/cp3ar/goal_model_sensitivity.py
```

```bash
uv run python tools/research/cp3ar/fixture_windows.py
```

Outputs are in `docs/research/phase8_cp3ar/`. Fixed seeds; a rerun reproduced the window output exactly.

**Limitations**
- Both studies reuse previously examined seasons.
- Proxy buckets are model-based (§D.1).
- Operational request figures come from the documented E.1b budget model, not from a weekend measurement.
- Effort figures are planning estimates.
