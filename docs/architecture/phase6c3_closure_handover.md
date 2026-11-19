# Phase 6C.3 — Closure handover and Phase 6C.4 starting point

**Status (19 Nov 2026):** Phase 6C.3 (competition persistence) is **formally
accepted** by the product owner (19 Nov 2026) on the evidence recorded here, and
released as the **v4.1.0** development milestone (merged into `main`; release notes
[`../releases/v4.1.0.md`](../releases/v4.1.0.md)). The limitations in §5 are accepted
as deferred work; D-29 and D-36 remain outstanding requirements; the hosted Supabase
compatibility test remains deferred. Phase 6C.4 has **not** started: it begins from
the v4.1.0 baseline after a separate owner discussion and authorisation.

This document is the durable starting point after context compaction. Read it with:

| Document | Role |
|---|---|
| [`phase6c3_implementation.md`](phase6c3_implementation.md) | Full implementation record, §§1–11 (assessment, Stages B–G, post-Stage G changes) |
| [`phase6c3_implementation_handover.md`](phase6c3_implementation_handover.md) | Stage F/G handover (environment, commands, journeys) |
| [`../product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md) | Decision register (authoritative; D-, T-, C-, R-series) |
| [`../product/weekly_challenge_phase6c_plan.md`](../product/weekly_challenge_phase6c_plan.md) | Stage plan 6C.0–6C.6 and the deferred backlog |
| [`phase6c_database_design.md`](phase6c_database_design.md) | Schema design, including settlement tables (§6), transactions (§9), corrections (§10) |
| [`../phase6c3_local_acceptance_mac.md`](../phase6c3_local_acceptance_mac.md) | Owner's local testing guide |

## 1. Final verification

| Item | Value |
|---|---|
| Branch | `feature/phase-6c3-competition-persistence` (not merged; no tag; not deployed) |
| Latest code commit | `71fef65` before this handover; this documentation commit follows it (see `git log -1`) |
| CI | run 24 on `71fef65`: **success** (run 23 on `ee42e75` was cancelled only because run 24 superseded it) |
| Lint / format | `ruff check` and `ruff format --check` clean |
| Full suite (real PostgreSQL + local Supabase Auth) | **1,304 passed, 1 skipped** on `71fef65` (re-run for this handover; 1,299 at the Stage G report plus 5 tests added afterwards) |
| Skip | `tests/backend/test_backend_supabase_db.py:115` — needs a database holding a real Supabase `auth` schema (hosted compatibility test, deferred) |
| Remote | local and `origin/feature/phase-6c3-competition-persistence` identical (verified after each push) |
| Working tree | clean; the session checkout returns to `claude/gifted-newton-h6o5hk` |

## 2. Changes after the Stage G final report (`5a5c8be`)

| Commit | Change | Why |
|---|---|---|
| `d6d6cb4` | `round dev-open --mirror-upcoming --fixtures N` (default 20; `0` = every fixture within seven days of the first allowed kickoff) | The owner saw only one EPL match: the mirrored development round took the first 20 fixtures by kickoff. Development tooling only |
| `a92705c` | `current_round` tie-break: equal deadlines → the most recently published round | Three open rounds shared the same deadline (only possible with test rounds), so the shown round was arbitrary |
| `9189a71` | **Your View on My Challenge (T-21, Option A)**: calculated on each page load from the frozen-context Your View saved for the round, applied to the confirmed nine | Owner request; Option B (freezing Your View at confirmation) not built — needs a D-41 decision |
| `ee42e75`, `71fef65` | **My Challenge layout**: Your View is a third card, the same size as Market and Diski 9, to the right of Diski 9, tagged "NOW", with one explanatory line ("calculated now … private, not part of your entry, never scored"); "This round" and "Confirmed portfolio" are compact and of even height; register T-21 wording | Owner feedback on the first layout |

Nothing in these changes touches the engines, odds, snapshots, the football
schema, competition rules or stored entries.

## 3. Owner's local acceptance (recorded as reported, 19 Nov 2026)

Verified by the owner on their Mac (local PostgreSQL, Supabase CLI):
* migrations to `app_0005`; owner bootstrap; development rounds
  (`dev-accept-1`, `dev-accept-2 --fixtures 0`); a real round
  `2026-W47-weekend` created and published from freshly refreshed odds
  (`refresh-data --with-odds`, 28 requests);
* building and **confirming a portfolio** in `dev-accept-2` (replaced once,
  version 2), with the entry **persisting**;
* the updated **My Challenge** layout, including the Your View card (accepted:
  "The layout looks much better now, I am happy with it").

Not reported as tested locally by the owner (covered by automated tests and the
cloud browser journeys only): deadline expiry and `round lock` on the Mac, the
"Most recent locked entry" card, cross-device conflict, guest-work adoption,
withdrawal and account isolation (journeys A–H, §10.6 of the implementation
record).

## 4. Outstanding Phase 6C.3 closure items

1. ~~Owner's formal acceptance of Phase 6C.3.~~ **Done (19 Nov 2026).**
2. ~~Where 6C.4 starts.~~ **Decided:** 6C.3 merged into `main` and released as
   v4.1.0; 6C.4 starts from the v4.1.0 baseline when authorised.
3. Optional and **not performed by the owner**: their own check of lock and the
   locked-entry card (Mac guide §7 E and H). Covered by automated tests and
   browser journeys only.

No known open defects. Unverified only as listed in §3.

## 5. Accepted deferred limitations (backlog)

| Item | Detail | Target |
|---|---|---|
| Full historical entry browsing | My Challenge shows the current round and the single most recent locked entry only | 6C.5 (history) |
| Periodic Screener reload latency | every `--ttl` (default 300 s) one request rebuilds the Screener data (~0.9 s alone, 1–3 s with concurrent requests); unchanged since before 6C.3 | 6D (background refresh) |
| Direct fixture URL selection | typing `/?fixture=<id>` does not select the match (in-app links work) | 6D |
| CLI tracebacks for expected errors | for example `round dev-open` without the publish capability prints a traceback instead of one line | 6C.6 (administration) |
| Hosted Supabase compatibility testing | one skipped test; deferred with hosted infrastructure | Phase 10 |
| Freezing Your View at confirmation (T-21 Option B) | needs a D-41 decision | later product decision |
| Outstanding requirements | **D-29** championship scoring and D-32b validation on 6–8 real pools (before Official Championship 1); **D-36** account deletion and retention policy (before launch) | not blocking 6C.4 |

## 6. Roadmap (approved; unchanged)

6C.0 research and release preparation ✓ · 6C.1 PostgreSQL foundation ✓ · 6C.2
authentication and accounts ✓ · **6C.3 competition persistence ✓ (accepted;
v4.1.0)** · 6C.4 settlement, voids and corrections · 6C.5
leaderboards and championships · 6C.6 administration, scheduling and monitoring ·
6D integration, optimisation and comprehensive testing · 7 Lucy and LiveKit ·
8 European competition expansion · 9 badges and achievements · 10 deployment
and private beta · 11 public launch and YouTube.

## 7. Independent processes (not modified by this work)

| Process | Status (19 Nov 2026) |
|---|---|
| Research collector capture `trig_01R8pEXhrpsehX82xPKZcY2Z` "Diski 9 weekly pool capture (Fri 08:00 SAST)" | enabled; `CRON_TZ=Africa/Johannesburg 0 8 * * 5`; collector session `session_01G8XHfLBvJ245ZvKEBSqCJL`; branch `research/weekly-pools`; replies "not started yet" before 27 Nov 2026; first real capture **Fri 27 Nov 2026 08:00 SAST** |
| Research collector results `trig_01NBMtRe7Y3WhtibZ2ah6Cdq` (daily 09:15 SAST) | enabled; starts 28 Nov 2026 |
| Corrected stop conditions (approved 19 Nov 2026) | capture stops when `capture_target_reached` is true or after 2027-03-31, disabling **only** the capture task; results continue for open pools; at the hard end (on or after 2027-04-21) unresolved rounds are marked incomplete; the results task is disabled only when capture is disabled **and** no round is open |
| One-off verification `trig_01NsZ4MAkCRJt8j1YJKVDeBj` | rescheduled by the owner to **Fri 27 Nov 2026 09:30 SAST**, fires into this session; read-only checks of the first capture |
| Odds trial `trig_01T4GYs8Nma5ERz7NiEQpUhx` | running until 2026-11-21 15:00 UTC on `claude/gifted-newton-h6o5hk`; to be disabled by its own run after the end; latest capture `32c424a` (19 Nov 15:16Z) |

## 8. Phase 6C.4 — approved settlement policy (do not reopen)

Authoritative documents (current locations; none moved or superseded):
* [`docs/product/weekly_challenge_settle_v1.md`](../product/weekly_challenge_settle_v1.md) — D-08 `settle/v1` exact definitions;
* [`docs/product/weekly_challenge_d32_round_invalidation.md`](../product/weekly_challenge_d32_round_invalidation.md) — D-32b and D-32b-Q1;
* [`docs/product/weekly_challenge_decisions.md`](../product/weekly_challenge_decisions.md) — D-08 additional requirements, D-15, D-26, D-27, D-28, D-31, D-32, D-33, D-35, T-05 to T-11, R-14;
* [`docs/product/weekly_challenge_phase6c_plan.md`](../product/weekly_challenge_phase6c_plan.md) §6C.4 — objectives, acceptance criteria, tests;
* [`docs/architecture/phase6c_database_design.md`](phase6c_database_design.md) §6, §9, §10 — tables, concurrency, corrections.

Summary of the approved rules (the documents above take precedence):

* **Inputs and timestamps (D-08):** the round's `deadline_at` and
  `settle_cutoff_at` (fixed at publish) and insert-only **result observations**
  (provider, and audited operator corrections). Original provider statuses, raw
  results and normalised verdicts are preserved; all times UTC; the
  settlement-policy version (`rules_version = settle/v1`) is recorded on each
  round (already stored at publish). **Actual match completion is distinguished
  from the time the result was received**; delayed notifications use the
  correction process; where reliable evidence is insufficient the operator is
  alerted, never invented.
* **Fixed cutoff (D-08):** latest `kickoff_at_publish` on the round sheet + 48 h,
  computed once at publish (already stored by 6C.3); later kickoff changes never
  move it. "Completed by the cutoff" = a final-played status with a 90-minute
  score **and actual kickoff at or before the cutoff**.
* **Statuses (settle/v1 §1):** not started `TBD`, `NS`; in play `1H`, `HT`, `2H`,
  `ET`, `BT`, `P`, `LIVE`; interrupted `SUSP`, `INT`; final played `FT`, `AET`,
  `PEN`; final not played `PST`, `CANC`, `ABD`, `AWD`, `WO`. **Unknown codes →
  pending + operator alert.**
* **Verdict order:** V3 (started or rescheduled before the deadline → void) →
  V2 (`CANC`, `AWD`, `WO` → void; awarded and walkover results are not genuine
  90-minute results) → settle on the 90-minute score (includes **V5**: completed
  by the cutoff after a postponement, suspension, interruption, abandonment
  replay or resumption) → V1 (after the cutoff, postponed or rescheduled beyond
  it → void) → V4 (after the cutoff, `ABD`/`SUSP`/`INT` not completed → void) →
  catch-all (after the cutoff, anything else → void recorded as V1 + alert) →
  pending (before the cutoff, or a final status with a missing score; missing
  score after the cutoff alerts and stays pending until a score or a correction).
  Extra time and penalties never count. **Rescheduled fixtures:** brought forward
  but still after the deadline settle normally if completed by the cutoff; moved
  before the deadline → V3; moved beyond the cutoff → V1. A completion after the
  cutoff is recorded for research but never changes the verdict.
* **Markets (settle/v1 §4):** 1X2, BTTS (yes when both ≥ 1), Over/Under 2.5
  (over when total ≥ 3), on the 90-minute score.
* **Payouts (D-32, D-15):** a void prediction settles at decimal odds 1.00; a
  bucket with any incorrect non-void prediction pays 0; bucket payouts and The
  Diski 9 are recalculated with the adjusted odds; each accumulator rounded
  half-up to 0.01; gross = sum; **recovery = gross ≥ 100.00**. Settlement must
  equal the engine's eight-state values for every verdict combination (plan
  acceptance criterion).
* **All nine void (D-33):** gross 100.00, net 0, 0 points, excluded from the
  weekly ranking, no recovery or top-ten, status "Void — Refunded"; counts toward
  the five-valid-entry minimum assessed at the deadline (subject to D-32b);
  record kept. Engine: `AllVoidPolicy.REFUND_UNRANKED`.
* **Round invalidation (D-32b):** competitive only if `2 × played > total`
  (prediction instances of the locked entry set; exactly 50% fails) **and** ≥ 5
  ranked entries (not D-33 refunds). Not evaluated while any prediction is
  pending (the cutoff bounds the wait); provisional during the R-14 24-hour
  correction window; operator invalidation needs the capability, a written reason
  and an audit record; corrections trigger a reassessment recorded as a new
  designation row. Failure → whole round void: 100 credits back to everyone,
  net 0, no points, recoveries, top-ten finishes or ranking, counter not
  advanced, everything retained.
* **Practice rounds (D-32b-Q1):** the majority-played rule applies; the
  five-ranked-entry rule does not; practice and void rounds never earn points or
  advance a championship. Competitive (stored `championship`, D-28 clarified) is
  not official championship membership (D-38).
* **Corrections (D-35, T-06, settle/v1 §5):** provider corrections are new
  observations; operator corrections record original and corrected values,
  actor, reason, timestamps, take precedence until withdrawn by another audited
  action; any verdict change re-runs entry settlement, D-32b and the round's
  scores; after a championship freeze only the audited reopen path.
* **Immutability and idempotency (DB design §6, §9; T-11):** history tables are
  insert-only; verdict, entry settlement, evaluation and score-set rows are
  written only on change with unique revisions; one running settlement per
  round (row lock + partial unique index); a rerun with no new information
  inserts only a run record; points, recoveries and the championship counter
  are **derived** from the current designation and score set, never incremented,
  so reassessments cannot duplicate effects.
* **Ranking and championship implications (D-26, D-27, D-31, T-05, T-11):**
  standard competition ranking on settled gross (0.01), shared ranks receive full
  points; `points-150-75-v2`; championship standings are aggregations over
  current designations and score sets, so a correction renumbers later rounds of
  an open championship automatically (DB design §10) — implemented in 6C.5.
* **Already in the schema (`app_0001`):** `result_observations`,
  `settlement_runs`, `selection_verdicts`, `entry_settlements`,
  `round_evaluations`, `designations`, `score_sets`, `round_scores` (plan: "no
  structural database changes" for 6C.4).

## 9. Genuinely unresolved Phase 6C.4 implementation questions

These are implementation choices or scope boundaries, not approved rules. None
is resolved here.

1. **Result source and observation cadence.** The football store (D-39) keeps
   only the latest state per fixture (`status_short`, `kickoff_utc`, `ft_*`,
   `et_*`, `pen_*`), updated in place by `refresh-data`. V3 ("rescheduled to kick
   off before the deadline") and actual-kickoff checks need observations copied
   into `result_observations` over time. How often should the results job read
   the football store (and refresh it from the API) between publication and the
   cutoff, and is copying on change from the football store the intended
   boundary?
2. **Evidence for "actual kickoff".** The provider exposes a (possibly updated)
   kickoff time and a status, not a separate actual-start timestamp. Proposed
   reading, for confirmation: the kickoff recorded with the first in-play or
   final observation; if no reliable evidence exists, alert rather than infer
   (as D-08 requires).
3. **90-minute score mapping — verified, no question remains.**
   `src/diski9/ingestion/fixtures.py` stores `ft_home/ft_away` from the provider's
   `score.fulltime` (never `goals`), with extra time and penalties in separate
   columns, as `settle/v1` requires.
4. **6C.4 / 6C.5 boundary.** The plan places score sets, ranks, points and the
   finalisation job (`jobs/finalise.py`, R-14) in 6C.5, while D-32b needs the
   ranked-entry count and a provisional state. Proposed: 6C.4 writes verdicts,
   entry settlements (gross, recovery, D-33 basis), D-32b evaluations and
   provisional designations; 6C.5 writes score sets, ranks, points,
   finalisation and championship effects. To confirm.
5. **Participant-facing results in 6C.4.** The plan lists no UI for 6C.4. Should
   My Challenge (and the locked-entry card) show settled verdicts and gross in
   6C.4, or wait for 6C.5 together with leaderboards?
6. **Operator tooling and re-authentication.** The admin dashboard is out of
   scope until 6C.6, so corrections and operator voids would be CLI commands
   with `--by-email` (as `round lock`). T-14 requires recent password entry for
   result overrides and round invalidation in the web app; is an audited CLI
   (server-side access, actor and reason recorded) acceptable for 6C.4?
7. **Scheduling.** Results and settlement jobs run manually (CLI) until 6C.6
   automates them — to confirm.
8. **`postponed` round designation (T-07).** Its trigger (a whole round
   postponed, as opposed to individual fixture voids) is not defined in
   `settle/v1`; needs a definition or explicit deferral.
9. **Testing with development rounds.** Synthetic development fixtures have no
   real results; mirrored rounds use real fixture IDs. Should development rounds
   be settled from real observations where available and from operator-entered
   test results otherwise, kept strictly to development rounds?
10. **Corrections after finalisation.** The reopen path for frozen championships
    belongs with championships (6C.5); in 6C.4 a correction to a finalised round
    would stop with an alert. To confirm.
11. **Documentation wording (no rule change).** `settle/v1` §2's worked example
    ("before the next Thursday publication", finalisation "on Thursday evening")
    and D-29a ("each Thursday") predate the D-11 revision to Friday 08:00 SAST.
    The 48-hour cutoff and 24-hour correction window are unchanged; only the
    weekday in the examples is outdated. Flagged, not edited.

No conflicting policy interpretations were found between the authoritative
documents beyond item 11.

## 10. Resuming

Environment commands (cloud container) are in
[`phase6c3_implementation_handover.md`](phase6c3_implementation_handover.md) §8.
6C.3 is accepted and released as v4.1.0. Do not start 6C.4 until the owner has
authorised it after a separate discussion and answered or deferred the questions
in §9; begin 6C.4 with
an assessment document, as in earlier phases.
