# Diski 9 Weekly Challenge — Decision Register (revised, Phase 6C.2)

**Phase 6C.5 Stage A (owner approval, 20 Nov 2026):** the Phase 6C.5 business
requirements (L-01 to L-37) and the specification
[`docs/architecture/phase6c5_design_specification.md`](../architecture/phase6c5_design_specification.md)
are approved, with decisions **CH-01 to CH-12** (the Stage A questions Q-1 to Q-12)
and the amendment **D-30a** below. Stage B is authorised; Stage C needs separate
approval. Private mini-leagues are removed from the MVP roadmap.

**Phase 6C.6 Stage A (owner approval of the design, 21 Nov 2026):**
* The design `docs/architecture/phase6c6_design_proposal.md` is approved with
  decisions **Q-01 to Q-14** (its §11): remove `--by-email` operator identity
  (Q-01); authenticated manual lock, unattended lock only as `SYSTEM` (Q-02);
  bootstrap verifies control of the target account, emergency recovery only after
  a documented, fail-closed security design (Q-03); **phased automation — 6C.6
  automates preparation, lock, results import, settlement, finalisation and
  championship processing, while publication stays operator-approved; automatic
  publication is a later, separately authorised phase** (Q-04); configurable
  fail-closed provider limits proposed in Stage C (Q-05); environment
  configuration with stream allowlist and pause, Official disabled (Q-06); host
  decision before Stage F (Q-07); one webhook channel approved in Stage D (Q-08);
  no alerts table initially (Q-09); `/healthz` deferred to hosting (Q-10); the
  **S-02 finalisation rule preserved unchanged** — "deadline + 24 h" wording means
  max(settlement cutoff, last material change) + 24 h (Q-11; design §12); local
  restore drill in Stage F (Q-12); continue on `feature/phase-6c6-operations`, no
  merge (Q-13); practice-round timing evidence is not competitive-lifecycle
  evidence, no time overrides (Q-14).
* Stage A closed; Stage B (S-07) authorised; Stage C onwards not authorised.
* Record: [`docs/architecture/phase6c6_implementation.md`](../architecture/phase6c6_implementation.md) §1.

**Phase 6C.6 Stage B (owner review, 21 Nov 2026 — provisional acceptance):**
* S-07 remediation provisionally accepted, subject to final verification.
* **Q-03 emergency owner recovery deferred:** no recovery command, recovery secret,
  bypass, endpoint or migration; authenticated bootstrap retained; interim manual
  database-administrator procedure documented (`docs/authentication.md` §6.1);
  Q-03 remains an open security decision.
* **Browser tests in GitHub CI approved:** Node and pinned Playwright in the full
  CI path; the documentation-only path, the `checks` status check and protection
  settings unchanged.
* Stage B not yet formally accepted; Stage C not authorised.

**Phase 6C.6 Stage B formal acceptance and Stage C authorisation (21 Nov 2026):**
* **Stage B formally accepted** (candidate `85b8608`, CI run 86: 1,731 passed, 0
  skipped; documentation head `607bf64`, CI run 87).
* Q-03 remains deferred; CI timeout of 40 minutes ratified; GitHub Actions runtime
  warnings recorded as separate maintenance item M-CI-1.
* **Stage C (scheduling and lifecycle orchestration) authorised:** a database-driven
  reconciler run by an external cron-style trigger; **Beta publication stays
  supervised** (no automatic publication or round creation; no unused autonomous
  publication path); `SYSTEM` only for lock, results import, settlement and
  finalisation; Official unreachable; no live provider calls in development or
  tests; no new migration unless separately justified. Stages D–G not authorised.

**Phase 6C.6 Stage C formal acceptance and Stage D authorisation (21 Nov 2026):**
* **Stage C formally accepted** (candidate `f89de9d`, CI run 89: 1,750 passed, 0
  skipped; documentation head `490f5e4`, CI run 90).
* Provider limits accepted **provisionally as defaults only**; automated provider
  calls stay disabled; live use needs the subscription allowance, account-wide
  consumption, competing workloads and a safety reserve verified first; no cap
  increase without approval.
* Scheduler advisory lock accepted for now; behaviour under realistic hosted
  PostgreSQL timeouts and pooling to be evidenced before hosted Beta (no timeout
  weakening as the default answer).
* **Stage D (monitoring, alerts and recovery) authorised:** `ops status`,
  `ops check`, three-level severity, one disabled-by-default webhook, recovery
  runbook, read-only job history, locking review; no real notification
  destination, no migration without separate approval, no force-finalise, no
  automatic alert resolution. Stages E–G not authorised.

**Phase 6C.6 Stage D closure and Stage E authorisation (21 Nov 2026):**
* **Scheduler-locking remediation (R1–R6) formally accepted** (`0f3c0b1`, CI run 95:
  1,778 passed, 0 failed, 0 skipped, all 13 browser tests; documentation head
  `f5458a3`, CI run 96). **Stage D closed.** Accepted Stage D architecture is not
  reopened without a material defect. The 20-minute abandonment threshold must
  always exceed the maximum in-flight duration; changes to those limits need review.
* **Stage E (operational administration and remaining backlog) authorised:** backlog
  reconciliation and scope matrix first; administrative CLI usability, round
  investigation, documented recovery, S-07 account-command clarity, publication
  readiness assessment, operator guide. Any new privileged capability, new kind of
  competition-state change or security-boundary change is presented for approval
  first. Not authorised: force-finalise, emergency owner recovery or break-glass,
  autonomous publication, account deletion without an approved design, ML-01
  change without a focused authorisation, D-29 trial restart, Official activation,
  live provider calls, webhook activation, migrations, CI timeout change, Stages F–G.

**Phase 6C.6 Stage D acceptance and scheduler-locking remediation (21 Nov 2026):**
* **Stage D monitoring, alerts and recovery formally accepted** (`45faeac`, CI run
  92: 1,765 passed, 0 skipped; documentation head `f4e0447`, CI run 93).
* The demonstrated scheduler-locking defect must be remediated before Stage D is
  closed for operational readiness: **R1–R6 authorised** (session-level advisory
  lock on a dedicated connection outside a transaction; direct or session-mode
  connection required; ownership checks with a unique run identity; conservative
  abandonment; bounded tick duration and provider operations; predictable cleanup),
  plus crash- and concurrency-safe provider-budget accounting. No lease table or
  migration unless the approved approach proves unsuitable. Provider limits stay
  provisional and live calls stay off. Stage E not authorised.

**Phase 6C.5 Stage F4 closure and Stage G owner acceptance (21 Nov 2026) — Phase 6C.5 complete:**
* **F4 closed** at `f0ac3c2` (CI run 81; 1,682 passed, 0 failed, 0 skipped; 12
  journeys, 253 checks, 0 problems; Match Lab intermittent test corrected, 40/40
  under CPU saturation; head `app_0007`; fingerprint
  `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4`). Application
  code unchanged from the F3 baseline `c2583c3`; no rule, bucket or scoring change.
* **G-1 Functional acceptance:** the Phase 6C.5 functionality (weekly leaderboards,
  championship lifecycle, corrections, History, My Challenge and the supporting
  competition services) is accepted.
* **G-2 Performance limitations:** the signed-in Dash leaderboards page load above
  600 ms and the guest page-load variability around 600 ms are accepted limitations,
  not blockers. The targets and measured results are retained; missed targets are
  not reclassified as passes.
* **G-3 Match Lab defect ML-01:** the stale-adjustment race is accepted as a known
  low-severity defect for 6C.5 and **scheduled as a targeted maintenance fix, with
  regression coverage, before private beta testing with real users** (register:
  `weekly_challenge_phase6c_plan.md`, "Outstanding work accepted at the 6C.5
  closure"). Not implemented in Stage G.
* **G-4 Local versus hosted:** the local integration, performance, concurrency and
  integrity evidence is accepted; it does **not** establish production scalability,
  hosted Supabase readiness or deployment readiness.
* **G-5 Release gates remain open:** S-07 remediation is mandatory in 6C.6 and before
  any hosted deployment or Official activation; genuine Beta finalisation (deadline +
  24 h), D-29, D-36, D-38, hosted Supabase authentication acceptance and the relevant
  6C.3 backlog remain open. **No Official competition stream is authorised.**
* Unchanged: `broad60-432-v1` (Foundation 60–95 %, Balanced 40–<60 %, Challenger
  20–<40 %), picks 4/3/2, credits 40/30/20/10, `points-150-75-v2` and the
  championship rules, stream isolation.
* Not authorised: 6C.6 implementation, the ML-01 fix, merge or tag, deployment,
  Official activation.
* Record: [`docs/architecture/phase6c5_implementation.md`](../architecture/phase6c5_implementation.md) §9.9 and §10;
  acceptance record: [`docs/architecture/phase6c5_stage_g_handover.md`](../architecture/phase6c5_stage_g_handover.md).

**Phase 6C.5 Stage F4 (checkpoint, 21 Nov 2026; approved and closed — see the Stage G entry above):**
* F4 changed no application code and no business rule. The intermittent Match Lab
  browser test was a test-synchronisation fault (fixed; assertions unchanged).
* A low-severity Match Lab defect was found and **not** fixed (a late detail rebuild
  can restore a Match Lab adjustment after Reset or an edit); recorded as a known
  defect for the owner's decision.
* The guest Dash page load now measures at the 600 ms boundary; it is not claimed as
  a pass. The signed-in miss remains the accepted limitation.
* All release gates are carried forward unchanged (S-07, genuine Beta finalisation,
  D-29, D-36, D-38, hosted Supabase acceptance, the 6C.3 backlog).
* Record: [`docs/architecture/phase6c5_implementation.md`](../architecture/phase6c5_implementation.md) §9;
  handover: [`docs/architecture/phase6c5_stage_g_handover.md`](../architecture/phase6c5_stage_g_handover.md).

**Phase 6C.5 Stage F3 (owner approval and closure, 21 Nov 2026):**
* F3 (performance, scalability and concurrency) is approved and closed at `c2583c3`
  (CI run 79; 1,682 passed). No business rule changed. F4 (final regression,
  stability and handover) is authorised; Stage G closure and 6C.6 are not.
* The signed-in Dash leaderboard page load (653 ms against the 600 ms target) is an
  **accepted, documented limitation**; the target is unchanged and the result is not
  a pass. No Screener callback redesign in F4.
* The History shared-rank optimisation is deferred unless F4 finds a correctness
  issue or a material regression. The remaining F3 scalability limitations are
  accepted as documented; production performance is not established.
* **S-07 remains a mandatory Phase 6C.6 remediation and a release gate.**
* The Weekly Challenge buckets stay `broad60-432-v1` (Foundation 60–95%, Balanced
  40–<60%, Challenger 20–<40%); a proposal to raise Foundation to 65% was reviewed
  and not adopted.
* Record: [`docs/architecture/phase6c5_implementation.md`](../architecture/phase6c5_implementation.md) §8.13.

**Phase 6C.5 Stage F2 (owner approval and closure, 21 Nov 2026):**
* F2 (integration and security testing) is approved and closed at `7afc03b`. No
  business rule changed. F3 (performance and concurrency) is authorised; F4, Stage
  G and 6C.6 are not.
* **S-07 remediation is a mandatory Phase 6C.6 item and a release gate** before any
  hosted deployment or Official activation (implementation record §7.2).
* The genuine beta 24-hour finalisation window must be demonstrated in later
  acceptance; development time overrides do not prove it.
* Record: [`docs/architecture/phase6c5_implementation.md`](../architecture/phase6c5_implementation.md) §7.14.

**Phase 6C.5 Stage F1 (owner approval and closure, 21 Nov 2026):**
* F1 (development tooling and resumable development championships) is approved and
  closed at `8379606`. No business rule changed. F2 (integration and security
  testing) is authorised; F3, F4 and Stage G are not.
* Record: [`docs/architecture/phase6c5_implementation.md`](../architecture/phase6c5_implementation.md) §6.9.

**Phase 6C.5 Stage E (owner approval and closure, 21 Nov 2026):**
* Stage E (Leaderboards and Historical Performance UI) is approved and closed. No
  business rule changed.
* The owner added one presentation rule: each My Challenge History chart is shown
  only from **three eligible rounds**. The allocation chart counts the counted
  competitive rounds played in the scope; the points chart counts the counted rounds
  played in its one championship. Below three, a compact placeholder appears.
* Record: [`docs/architecture/phase6c5_stage_e_closure_handover.md`](../architecture/phase6c5_stage_e_closure_handover.md).
  Stage F needs separate authorisation.

**Phase 6C.4 Stage A review (owner approval, 19 Nov 2026):** decisions S-01 to S-11
below (the assessment's Q-1 to Q-13, as finally approved) and the amendment of
`settle/v1` to a completion-based cutoff. Detail and rationale:
[`docs/architecture/phase6c4_implementation.md`](../architecture/phase6c4_implementation.md).
Stages B–D authorised; the CLI wrapper (E), My Challenge results (F) and final
acceptance (G) wait for separate authorisation.

**Phase 6C.2 (owner brief):** architecture confirmed (Supabase Auth; Supabase-hosted
PostgreSQL for future production; local PostgreSQL and local Supabase for
development; hosting still undecided until Phase 10; no AWS). Implemented as
described in [`docs/authentication.md`](../authentication.md). The owner approved
T-14 to T-17 on 19 November 2026 (T-15 and T-16 with additional requirements, all
implemented and tested in Phase 6C.2 except the parts of T-15 that need persistent
portfolios, which belong to Phase 6C.3).

**Phase 6C.0/6C.1 approval (owner review):** D-01 (Supabase Auth), D-08
(`settle/v1`), D-29b (research collection activation), D-39 (football store stays
separate during 6C), D-40 (merge and v4.0.0 release), T-12 (session lifetimes) and
T-13 (automated testing) approved. D-29 validation and the D-36 final retention
policy remain outstanding.

**Phase 6C architecture finalisation (owner review):** approved D-03 (PostgreSQL
direction), D-04, D-05, D-06, D-11, D-12, D-32b-Q1, D-34, D-35, D-37, D-38,
T-09, T-10 and T-11; D-02 deferred to Phase 10 with hosting-independence
constraints; D-36 approved in principle (final retention policy before launch);
D-29 weekly research collection approved (activation needs schedule
confirmation; validation outstanding); D-08 accepted in principle pending the
exact definitions in [`settle/v1`](weekly_challenge_settle_v1.md); D-01 provider
recommendation in the [auth comparison](../architecture/auth_provider_comparison.md).
D-33 unchanged. Architecture: [technical architecture](../architecture/phase6c_architecture_considerations.md),
[database design](../architecture/phase6c_database_design.md),
[Phase 6C plan](weekly_challenge_phase6c_plan.md).

**Phase 6C preparation (owner review):** D-32b (round invalidation after
widespread voids) approved with clarifications; see the
[D-32b note](weekly_challenge_d32_round_invalidation.md). Its validation on real
pools is added to D-29. The remaining outstanding decisions, and new items found
during Phases 6A and 6B, are reviewed in the
[outstanding decision review](weekly_challenge_phase6c_decision_review.md); none
of them is approved by that review. Architecture questions for Phase 6C are in
[Phase 6C architecture considerations](../architecture/phase6c_architecture_considerations.md).

**Phase 6B close-out (owner review):** D-33 approved; D-32 settlement rules
approved; D-29 remains an open validation requirement with an approved approach.
The technical backlog for the next phases is in the implementation plan.

This register supersedes the Phase 5C register (`2e079ba`) and the Phase 6A.2
version (`6d5b47f`). IDs are kept, so history can be traced. Superseded items are
listed at the end.

**Legend:**
* **Approved:** decided by the owner.
* **Provisional (empirical):** supported by the Phase 6A.1/6A.2 synthetic
  simulations, still to be confirmed on 6–8 captured real round pools.
* **Proposed (technical):** Claude's recommendation for an implementation detail.
  It is adopted unless the owner objects.
* **Outstanding:** needs an owner decision before the named phase.

## Approved by the owner

| ID | Decision |
|---|---|
| C-01 | 100 virtual credits per completed round; 9 selections on 9 distinct fixtures; markets 1X2, BTTS and Over/Under 2.5 |
| C-06 | Goal Model 1.0 unchanged; existing strict consensus and eligibility (≥ 3 bookmaker groups, fresh within 24 h) |
| C-07 | Weekly leaderboard by net virtual credits; no real money, prizes, affiliate links or staking advice |
| C-08 | "Your Payout Probability" chart kept: cumulative step view plus exact-payout view; the 100-credit value equals the summary; the nine-fold only in the all-win state; credits, never percentages, on the x axis |
| C-09 | **Broad-60 buckets by margin-adjusted market probability at full precision:** A Foundation 60–95% inclusive; B Balanced 40% to < 60%; C Challenger 20% to < 40%. Outcomes outside 20–95% are not eligible |
| C-10 | **Strict structure:** exactly 4 A, 3 B and 2 C picks, plus the nine-fold "The Diski 9"; no flexible counts |
| C-11 | **Fixed credits:** 40 / 30 / 20 / 10; no adjustable stakes |
| C-12 | Configuration is versioned (`broad60-432-v1`); a change means a new version, never an in-place edit |
| C-13 | No 280 groupings, no efficient frontier, no recommendation. The Phase 6A engine is kept as a baseline and generalised |
| C-14 | Eight-state maths and D-15 rounding kept; market-based and model-based estimates shown separately, never mixed |
| C-15 | Bucket tracker: Foundation X/4, Balanced X/3, Challenger X/2, Total X/9 |
| C-16 | Permanent "Explore Your Bucket Risk" feature with hypothetical probabilities and fair odds, never linked to the participant's portfolio |
| C-17 | Incomplete portfolios show only completed-bucket figures, clearly distinguished; portfolio analytics only at 9/9 |
| C-18 | No championship or season explorer |
| C-19 | **Championships:** exactly 10 completed rounds, then reset; join any time; every round counts; nothing carries forward |
| C-20 | **Recovery-gated weekly points:** gross ≥ 100.00 (inclusive) is required for any points; gross < 100 or no entry scores 0; points are non-additive; maximum 150 per round. "No recovery, no championship points." The schedule itself is D-31 |
| C-21 | **Weekly ranking** by realised net (equivalently settled gross); **championship ranking** by cumulative championship points |
| D-26 | **Weekly ties (approved Phase 6A.2.1): standard competition ranking.** Rank = 1 + the number of entrants with a strictly greater settled gross (exact, 0.01). Tied entrants share the rank and **each receives that rank's full points**; later ranks are skipped (350, 350, 290 → 1, 1, 3 → 150, 150, 125). More than ten entrants may receive top-ten points. No averaging; no timestamp, ID or other tie-breaks. Tied entrants below 100.00 get 0. Points are whole numbers |
| D-27 | **Championship ties (approved):** total points → successful recoveries → qualifying top-ten finishes (rank ≤ 10, gross ≥ 100.00, championship-eligible round) → joint position under standard competition ranking (joint champions allowed). Cumulative gross or net credits are never a tie-break |
| D-28 | **Operational thresholds (approved):** a round opens only with ≥ 15 eligible fixtures, ≥ 3 eligible leagues and an exact strict 4/3/2 feasibility check (existing freshness and ≥ 3 bookmaker-group rules unchanged). A round counts toward the championship only with **≥ 5 valid entries** (distinct participants with a locked, complete, valid final submission at the deadline; resubmissions count once). Otherwise it is a **practice round**: it settles, shows results and a weekly table, awards no points, doesn't affect tie-breakers and doesn't advance the counter. Practice results are kept separately **Clarified at the 6C.3 checkpoint:** five or more valid entries make a round *competitively classified* (stored as the legacy designation value `championship`); this alone never makes a round count toward an official championship, which also needs the official series and a started Official Championship 1 (D-38). Unofficial competitive beta rounds are expected before then |
| D-30 | **Championship continuation (approved):** a championship is always ten completed championship-eligible rounds, independent of league seasons and calendar quarters. Breaks, end of season or unavailable pools **pause** it with points preserved; it is never shortened and no champion is crowned early. After ten rounds: finalise, archive, record the champion(s), reset. Join any time; all ten rounds count; history and lifetime statistics kept *Exception approved 20 Nov 2026: **D-30a** (a completed championship whose successor has commenced may keep fewer than ten rounds after a later invalidation).* |
| D-31 | **Approved for the MVP (Phase 6A.3): Scenario D, `points-150-75-v2`.** Ranks 1–10 earn 150/135/125/120/115/110/105/100/95/90, any other recovery 75, no recovery 0; D-26 ties; maximum 150 per round and 1,500 per championship. Implemented in `diski9.challenge.scoring`. The incentive evidence is simulated (D-29); approval does not claim real-world incentives are eliminated |
| D-30a | **Exceptional historical correction (approved 20 Nov 2026, Q-11):** a championship normally requires ten valid competitive rounds for completion and must not be deliberately shortened. If a previously counted round is subsequently invalidated after the next championship has officially commenced, the affected historical championship may exceptionally retain fewer than ten valid competitive rounds. Its original identity, start date, name and membership boundaries are preserved, its standings are recalculated and the correction is transparently disclosed; subsequent championships are unaffected. Where the next championship has not yet commenced, the approved reopening and replacement-round method applies (L-33). This is an exceptional rule; it does not replace the normal ten-round requirement (D-30). Commencement = the next championship's first associated round (CH-03) |
| CH-01 | **Competition streams (approved 20 Nov 2026, Q-1):** three isolated streams: development (synthetic testing, hidden from public users), beta (genuine pre-launch, clearly labelled Beta, same mechanics as official) and official (after launch; D-38 unchanged; D-29 gates the official series only). Beta history stays visible to its participants; beta points, standings and titles never carry over into the official series |
| CH-02 | **Championship membership (approved with clarification, Q-2):** rounds are assigned in deadline order, never by settlement completion order; a round is assigned when all earlier rounds of the stream are assigned and its championship is determined (normally at publication; a round whose championship depends on unresolved earlier rounds waits); membership is immutable from assignment; a later round may publish its weekly results first, its championship contribution waiting where necessary. Practice and invalidated rounds are members that never count, never advance the counter and never rename. Detail: specification §8.3 |
| CH-03 | **Championship naming (approved with amendment, Q-3):** display name "Championship MMM-YY" from the SAST publication date of the **first associated round** (even if that round later becomes practice or void), established when the championship is created at that round's assignment; immutable identity, start date and name; same-month collisions get " (2)", " (3)", … |
| CH-04 | **Review does not block (approved with clarification, Q-4):** a completed championship under review never prevents the next championship from commencing or progressing; corrections stay within the affected championship; an active championship is complete only with ten published valid competitive rounds |
| CH-05 | **Restored rounds (approved with safeguards, Q-5):** a round restored to valid republishes its weekly results, keeps its championship and counts only within remaining capacity (counted + pending < 10); it never displaces a counted round, never moves, never exceeds ten; otherwise its weekly result is published without championship points, with an explanation; competing restored rounds take capacity in deadline order; audited. Verified: D-32b voids can be restored through the existing owner reopening; operator invalidations cannot (no 6C.4 path; documented limitation) |
| CH-06 | **Under Review (approved, Q-6):** an indicator, not a state; lifecycle Upcoming, In Progress, Completed; Corrected and D-30a historical-correction indicators explained in words (never an unexplained "Short") |
| CH-07 | **Championship display names (approved, Q-7):** the name at lock of the participant's latest counted entry; weekly results keep each entry's name at lock; immutable internal identifiers; retroactive anonymity and pseudonymisation take precedence, including in historical versions |
| CH-08 | **Refunded-only participants (approved, Q-8):** not in official standings; their summary explains why; rankable participants without recovery stay listed with zero points; refunded entries are neither successful nor unsuccessful recoveries |
| CH-09 | **Guest access (approved, Q-9):** public weekly and championship standings, including history, as approved in 6C.2; beta clearly identified; no personal summaries, history, settlement details, predictions, portfolios, account data or development rounds and championships |
| CH-10 | **My Challenge during review (approved, Q-10):** shows the last published return, weekly rank and championship points and the current settlement, clearly distinguished; published points stay until the corrected round is finalised; no provisional championship points |
| CH-12 | **Practice-round leaderboards (approved, Q-12):** a valid practice round has a weekly leaderboard labelled Practice Round, ineligible for points, never advancing the counter or entering standings or competitive recovery statistics; invalidated practice rounds show no results table |
| D-15 | Settlement precision: each accumulator rounded half-up to 0.01; state gross = sum; recovery = gross ≥ 100.00 (approved in Phase 6A) |
| D-32 | **Partially voided portfolios (approved, Phase 6B close-out):** a voided prediction settles at decimal odds 1.00; all other predictions settle normally; a bucket containing an incorrect, non-voided prediction pays 0; bucket payouts, including The Diski 9, are recalculated with the adjusted odds; the approved payout rounding (D-15) is retained; an entry recovering at least 100.00 credits stays eligible for championship points in a competitive round, except a fully voided entry (D-33); no replacement predictions after the submission deadline. Whole-round invalidation is D-32b |
| D-33 | **Entire portfolio voided (approved, Phase 6B close-out):** when all nine predictions of a confirmed portfolio are void: gross returned 100.00; net 0.00; championship points 0; excluded from the weekly ranking (other entrants ranked as if it were absent); no successful recovery and no qualifying top-ten finish recorded; settlement status "Void — Refunded"; the entry counts toward the five-valid-entry minimum assessed at the deadline, subject to the round-invalidation rule (D-32b); the portfolio and its settlement record are retained for history and audit. The participant is neither penalised nor rewarded for predictions that were never tested. Implemented in the scoring engine as `AllVoidPolicy.REFUND_UNRANKED` (the default of `points-150-75-v2`) |
| D-32b | **Round invalidation after widespread voids (approved, Phase 6C preparation):** a round remains competitive only when, at final settlement, **(1)** strictly more than 50% of all predictions belonging to the valid confirmed entries locked at the deadline were settled on played results (exactly 50% fails), and **(2)** at least five entries remain eligible for the weekly ranking (not "Void — Refunded"). Otherwise the whole round is void: every confirmed participant gets the original 100 credits back; net 0; no championship points, recoveries, qualifying top-ten finishes or competitive weekly ranking; the championship counter does not advance; submissions, results, provisional settlement calculations and the invalidation reason are retained. Clarifications: the authoritative locked entry set is used; prediction instances are counted, not unique fixtures; played predictions count whether correct or incorrect; pending fixtures never invalidate a round (the rule is evaluated only when every prediction has a final verdict, and the settlement cutoff bounds the wait); evaluation is deterministic and provisional until the R-14 correction window ends; an exceptional operator invalidation needs the operator permission, an explicit reason and an audit trail; a result correction triggers an auditable reassessment that can never duplicate points or advance the counter twice. Validation on real pools is part of D-29, keeping observed voids separate from simulated cancellations. Detail: [D-32b note](weekly_challenge_d32_round_invalidation.md). Practice rounds: D-32b-Q1 (approved) |
| D-03 | **Database (approved direction, Phase 6C architecture finalisation):** PostgreSQL for the new competition backend, locally through Docker Compose and in production; SQLAlchemy 2 and Alembic; production compatibility and concurrency tests run against real PostgreSQL. The existing SQLite football store stays separate during Phase 6C and is recommended for migration to PostgreSQL before hosted deployment (database design §12; timing D-39) |
| D-02 | **Hosting (deferred to Phase 10):** provider selection waits until Phase 10. Until then the application stays container-compatible and hosting-independent (configuration from the environment, no essential local file state for the competition backend, jobs as CLI commands, health check) |
| D-04 | **Leaderboard privacy (approved):** public leaderboards show chosen usernames, never personal names or email addresses. Participants may choose anonymous participation: their rows show a stable, randomly generated alias (for example "Anonymous 4821") that is unique, not derived from any account data, and can be regenerated on request; the alias keeps anonymous entries distinguishable in rankings, ties and championship tables without revealing the account |
| D-05 | **Usernames (approved):** 3–24 characters; case-insensitive uniqueness; validation of the character set and a blocklist (including names imitating staff or Diski 9); at most one change every 30 days; auditable name history; operator rename with a reason. Historical anonymity preferences are respected: a leaderboard shows the name or alias recorded at lock; anonymity can be applied retroactively but is never removed retroactively |
| D-06 | **Deadline buffer (approved):** 15 minutes before the earliest eligible kickoff, stored per round and enforced on the server (database clock inside the write transaction) |
| D-11 | **Round calendar (approved):** weekend rounds and Thursday publication at 08:00 SAST initially. Round calendars, eligible leagues, publication times, deadlines and settlement windows are configurable (versioned round schedules) to support future Champions League and other midweek rounds **Revised 19 Nov 2026 (6C.3 checkpoint):** the standard weekend publication target is **Friday 08:00 SAST** (Africa/Johannesburg), stored as weekend schedule version 2 (version 1, Thursday, is kept for rounds published under it). It is a target, not a guarantee: a round opens only when every opening rule passes. The round window, the 15-minute common deadline, the 48-hour settlement cutoff and all eligibility rules are unchanged; Friday fixtures are not excluded. Automated publication remains Phase 6C.6 |
| D-12 | **PSL coverage (approved):** current PSL odds coverage limitations are accepted; missing coverage is explained transparently in the UI during Phase 6D |
| D-32b-Q1 | **Practice rounds (approved):** the majority-played requirement applies to practice rounds, but not the five-ranked-entry minimum. A practice round with 50% or fewer played predictions becomes void. Practice and void rounds earn no championship points and do not advance the championship |
| D-34 | **Roles and entitlements (approved):** participant, operator and owner roles, with independent feature entitlements (initially `lucy.research`, `lucy.voice`, `lucy.presenter`, held only by the owner). Identity, roles and entitlements are separate. All permissions are checked server-side; hiding UI elements is never the control. A future premium participant may receive specific entitlements without operator or owner permissions. Lucy, payments, billing and premium features are not implemented in Phase 6C |
| D-35 | **Result corrections (approved):** authorised operators may correct results; each correction requires an explicit reason and records the original and corrected values, the actor's identity and timestamps in an immutable audit record |
| D-36 | **Account deletion (approved in principle):** deletion removes or anonymises personal information while retaining necessary non-identifying historical competition records; covers deletion at the authentication provider, research records (which hold no user data), logs and backups, and applicable privacy requirements. The final retention policy requires review before launch |
| D-37 | **Eligibility and terms (approved as the proposed launch policy):** 18+ self-declaration and versioned terms acceptance, subject to applicable legal requirements; the schema records the declaration and each accepted terms version |
| D-38 | **First official championship (approved):** beta rounds are unofficial; Official Championship 1 begins only after D-29 validation and formal launch approval |
| D-29a | **Weekly research collection (approved approach):** a separate weekly collection after the odds trial ends: all eight leagues, one complete fixture and odds snapshot each Thursday at 08:00 SAST, results collected and rechecked until final, raw and normalised data with provider and capture timestamps, existing consensus, freshness and eligibility rules, feasibility recorded, at least six to eight qualifying pools, D-32b validation with observed and simulated voids kept apart, and no ability to modify production competition records. Activation requires the owner's confirmation of the schedule ([proposal](../research/weekly_pool_collection_proposal.md)) |
| D-01 | **Authentication (approved, Phase 6C.0/6C.1 approval):** Supabase Auth. Develop and test locally; no paid cloud infrastructure yet; use Supabase's supported authentication interfaces for Python, Flask and Dash (to be confirmed in Phase 6C.2) rather than assuming generic OIDC compatibility; keep independent Diski 9 user identities, roles and entitlements and provider-independent competition services; no passwords in the application database; plan for verified email, secure account recovery, session revocation and future social sign-in. Implementation in Phase 6C.2 |
| D-08 | **Settlement rules `settle/v1` (approved):** as defined in [`settle/v1`](weekly_challenge_settle_v1.md): the fixed cutoff of 48 hours after the latest scheduled kickoff recorded at publication, the V1–V5 rules and the verdict priority. Additional requirements: completion at or before the cutoff is eligible for normal settlement subject to higher-priority void rules; actual match-completion time is distinguished from provider result-receipt time; delayed result notifications use the approved correction process; original provider statuses, raw results and normalised verdicts are preserved; all timestamps in UTC; the settlement-policy version is recorded against each published round; later kickoff changes cannot silently modify the published cutoff; tests cover conflicting provider statuses, exact cutoff boundaries and repeated deliveries; where reliable evidence is insufficient the operator is alerted rather than completion times or results being invented. Implementation in Phase 6C.4. **Amended 19 Nov 2026 (S-03):** the cutoff is completion-based throughout `settle/v1` |
| D-29b | **Weekly research collection (approved and activated):** branch `research/weekly-pools`; capture Thursdays 08:00 SAST from 26 November 2026; results daily 09:15 SAST after the first capture. Implemented in Phase 6C.0 |
| D-39 | **Football store (approved):** the SQLite football database stays separate throughout Phase 6C; the competition backend consumes it through defined integration boundaries and copies required data into immutable round snapshots and result records; migration to PostgreSQL is a separate approved task before hosted deployment |
| D-40 | **Merge and release (approved, done):** `feature/weekly-challenge-final-polish` merged to `main` (`d12ddff`) and released as v4.0.0 (`0286fa8`), described as an accepted functional prototype with browser-session persistence |
| D-41 | **Match Lab qualitative inputs (approved, 19 Nov 2026):** the free-text adjustment reason (Section B) and per-factor research notes (Section C) are removed and replaced by static guidance per factor ([factor guidance](match_lab_factor_guidance.md)); no reason field on the manual adjustment; Your View holds numbers only. **Deferred** until real-user feedback: historical adjustment reasons, adjustment versioning, prediction journals, qualitative-factor performance attribution, personal prediction dashboards, research-note collection for model training and related consent flows; no historical adjustment tables or note fields. Phase 6C.3 still persists the current numerical Your View across devices (T-10). Phase 7 Lucy will research factors within the same framework and suggest adjustments that the user explicitly accepts or rejects |
| S-01 | **Results collection (approved 19 Nov 2026, Q-1):** a competition-specific by-ID results fetch through the existing provider client and normalisation; existing football ingestion behaviour preserved; raw provider evidence and normalised values stored as immutable, versioned observations in PostgreSQL with provenance, receipt times, ordering and idempotency; batched fixture IDs; no polling of distant or unrelated fixtures; no automated scheduling in 6C.4 |
| S-02 | **Correction window and finalisation (approved, Q-2):** earliest finalisation = max(fixed cutoff, last material settlement change) + 24 hours (database clock), and only with every relevant prediction (valid locked entry set) resolved, no unresolved settlement-blocking alert and all settlement and round-validity checks complete. **Material** = any change across the locked round to a prediction verdict, void reason or rule, accumulator outcome or return, entry gross or net, entry completeness, recovery classification, rank eligibility or D-33 classification, D-32b validity or designation, or an authorised round invalidation. A 90-minute score correction that changes none of these is recorded and shown but does not restart the window; metadata changes and repeated identical observations never do. Unselected fixtures never block. **Blocking alerts:** unknown or unsupported status; final-played without a valid 90-minute score; conflicting material scores; regression from final to not-started; conflicting kickoff or rescheduling evidence; unverified evidence of early commencement; possible late completion or delayed notification. Blocking alerts need an audited resolution; informational alerts never block |
| S-03 | **Completion-based cutoff (approved, Q-3):** normal settlement needs reliable evidence that the match genuinely completed at or before the fixed cutoff (48 hours after the latest scheduled kickoff in the published snapshot), subject to higher-priority void rules; a match that starts before the cutoff but completes after it is void; no grace period. A final-played observation we recorded at or before the cutoff establishes completion; a result first received after the cutoff does not: it is preserved, the cutoff-based void stands, a blocking alert is raised, and an audited correction (reliable evidence of completion by the cutoff) or an audited confirmation of the void resolves it. No completion time is manufactured. The cutoff never moves. `settle/v1` §2, rule 3 and the consequential wording amended accordingly; no new void code |
| S-04 | **Early commencement and rescheduling (approved, Q-4/Q-11):** V3 keeps two independently recorded branches: *started* (reliable actual event evidence, or our timestamped observation of an in-play or final state before the deadline) and *rescheduled* (a reliable, consistent revised scheduled kickoff earlier than the deadline, applied automatically). A revised schedule is never proof of commencement. Contradictory schedule observations are kept and raise a blocking alert. The provider's `periods.first` is supporting evidence only: alone it never decides V3; a suggested breach without corroboration raises a blocking alert. Actual kickoff is never filled from a scheduled kickoff. Ordinary matches without kickoff evidence need no manual review |
| S-05 | **Conflicting results (approved, Q-5):** every material observation is kept, including a return to an earlier state (A → B → A); identical repeated deliveries are idempotent; an older fetch committing late never overrides newer evidence; material conflicts are resolved through the correction process, not by silently replacing verdicts |
| S-06 | **Finalised rounds (approved, Q-6/Q-7):** routine imports never reopen a finalised round; material changes detected afterwards raise an alert. Only the owner may reopen, with verified identity, recent authentication (T-14), supporting evidence, a mandatory reason, an impact preview and explicit confirmation, an immutable audit record, transactional recalculation and a new settlement version; the original final settlement and all versions are kept. Operators may make audited provisional corrections. Championship recalculation is 6C.5 |
| S-07 | **Operator authentication (approved, Q-8):** interactive CLI password authentication through Supabase Auth, exposed in Stage E. Database credentials are never proof of operator authority; identity and application roles are verified independently of provider metadata; sensitive operations need recent authentication (T-14); credentials never appear in shell history, arguments, logs or audit payloads; human operator actions are distinguished from future explicitly authorised scheduled operations; no general authorisation bypass. *Implemented in Stage E (20 Nov 2026) for every settlement command (`docs/operator_settlement_cli.md`); the 6C.3 `round create/publish/lock/dev-open` commands are unchanged (open item for 6C.6). *Assessed in 6C.5 F2 (21 Nov 2026; implementation record §7.2): the email-identified `round` and `account` commands give no capability beyond the application database credential they need, have no web path and no production database exists, so deferral to 6C.6 is safe; it is a release gate before Phase 10 hosting or D-38 activation (current exposure low, medium before deployment)* |
| S-08 | **Development result modes (approved, Q-9):** a development round has an explicit, frozen result mode, `synthetic` or `real`. Synthetic mode never falls back to real results; real mode never reads synthetic observations; synthetic evidence is scoped to its development round, protected at the database and service layers; development-only time overrides with safeguards; production and genuine rounds refuse synthetic evidence and time overrides; existing development rounds need an explicit mode before settlement. Deterministic scenario builders in Stage C; CLI in Stage E |
| S-09 | **Settlement finalisation in 6C.4 (approved, Q-10):** state transitions, authoritative settlement versions, correction-window calculation and audited reopening in 6C.4; weekly ranks, points, leaderboards and championship progression consume them in 6C.5 |
| S-10 | **Migration `app_0006` (approved in principle, Q-12):** repeated historical observation states, scoped synthetic observations, operator observations with provenance, frozen correction-window configuration, explicit development result mode, verdict rule and evidence references, settlement-run evidence and timing, authoritative settlement version references and lifecycle integrity. No grace-window column. Existing records, constraints, account isolation and append-only protections preserved |
| S-11 | **Participant settlement presentation (approved for Stage F, Q-13):** pending predictions never shown as incorrect; unresolved accumulator payouts never shown as zero (an accumulator with an incorrect leg may be shown as unsuccessful); settled-so-far returns clearly separated from completed settlement; no definitive recovery before the entry and round-validity checks complete; frozen odds and predictions kept; no new tabs or probability charts |
| T-12 | **Session lifetimes (approved):** participant idle expiry 14 days; absolute lifetime 30 days; operator authentication recency at most 12 hours; additional recent authentication for sensitive operations (changing roles or entitlements, overriding results, invalidating competitive rounds, reopening frozen championships); secure server-side sessions with rotation, revocation, CSRF protection and appropriate cookies. The exact sensitive-operation policy is proposed in Phase 6C.2 |
| T-13 | **Automated testing (approved):** repository checks with a real PostgreSQL service (implemented in Phase 6C.1: `.github/workflows/ci.yml`) |
| T-14 | **Sensitive-operation re-authentication (approved 19 Nov 2026):** the password must have been entered within 15 minutes for changing roles or entitlements, overriding results, invalidating rounds, reopening frozen championships, suspending accounts and changing the password. The approved participant session lifetimes and 12-hour operator recency (T-12) are unchanged. Implemented in Phase 6C.2 (`permissions.SENSITIVE`, `authorize()`, `/auth/reauthenticate`) |
| T-15 | **Guest drafts at authentication transitions (approved 19 Nov 2026):** guests build and analyse temporary portfolios without registering; after sign-in or registration a person with guest work in the tab is offered an explicit choice to keep or discard it; an existing authenticated portfolio is never silently overwritten; an adopted draft is revalidated against the current eligible round and frozen snapshot and never submitted automatically; private browser-session data is cleared at sign-out and on account switching; a previous account's portfolio or private Your View adjustments are never exposed to another account or a guest. **Phase 6C.2 (done):** the keep/discard choice for the browser tab (keeping leaves the work in the tab only, nothing saved or submitted), clearing at sign-out (`Clear-Site-Data` plus script) and on account switching (opaque owner marker). **Phase 6C.3:** saving a kept draft to the account (adoption), the no-overwrite rule against a stored portfolio, revalidation against the current round and snapshot, and server-side Your View storage (T-10) **Extended at the 6C.3 checkpoint:** the keep/discard choice also covers the guest's compatible numerical Your View adjustments (live and frozen contexts), revalidated on the server; adoption is explicit, never automatic; differing saved account work is replaced only after a clear choice; incompatible or wrong-round work is listed with the reason and not adopted |
| T-16 | **Provider revocation delay (approved with safeguards, 19 Nov 2026):** a revocation made at Supabase (for example a ban or a sign-out elsewhere) reaches ordinary participant browsing at the next provider refresh, within about an hour. Safeguards, all implemented and tested: local sign-out invalidates the application session immediately; application-level suspension takes effect on the next request; role and entitlement revocations apply to the next protected operation (permissions are loaded from the database on every request); privileged operations check the provider first and fail closed, and sensitive ones also require T-14. The distinction between provider-side and application-side revocation is documented in `docs/authentication.md` §5 |
| T-17 | **Email links with a confirm button (approved 19 Nov 2026):** confirmation and recovery links open a page with a button; loading or scanning the page consumes nothing, only the deliberate button press uses the single-use token. Implemented and tested in Phase 6C.2, including against a real Supabase Auth server |
| T-18 | **Snapshot construction age (approved 19 Nov 2026, 6C.3 checkpoint):** a snapshot is published only if it was constructed no more than one hour before publication by the database clock and not after it (server configuration `DISKI9_SNAPSHOT_MAX_AGE_MINUTES`, 1–180, default 60; not a participant setting). This is separate from, and never replaces, the odds rules: every eligible quote must still be verified within 24 hours before the snapshot with at least three independent bookmaker groups, and every opening rule must pass. A published snapshot never expires or changes |
| T-19 | **Frozen versus latest information in the pages (approved 19 Nov 2026, 6C.3 checkpoint):** Weekly Challenge views show the round's actual stored snapshot (frozen) time, the deadline and the round status, with a short note that all participants use the same frozen odds and baseline estimates; All Upcoming Fixtures shows the latest available information with real update times where reliable (never called live or real-time). The snapshot time is not presented as the time of every bookmaker quote. Times are shown in SAST |
| T-20 | **Most recent locked entry (approved 19 Nov 2026, 6C.3 Stage G):** My Challenge keeps the current-round experience and, when another round is current, also shows the participant's most recent confirmed entry in a round whose deadline has passed: a compact read-only card with the round identity and true status (**Deadline passed** while the lock has not run, then **Locked**), the nine confirmed predictions with frozen odds and the fixed credits, read from the stored immutable submission. Withdrawn entries are not shown; the current round is never duplicated; no results or payouts before settlement. Not a history interface (full history, search, results and analytics remain deferred) |
| T-21 | **Your View now on My Challenge (approved 19 Nov 2026, Option A):** the confirmed-portfolio card shows, for the signed-in participant only, a third estimate card "Your View" (tagged "now"), the same size as Market and Diski 9, calculated on each page load from the frozen-context Your View currently saved for the round, applied to the confirmed nine predictions (unadjusted matches use the Diski 9 baseline). It is labelled private and not part of the entry, is never stored with the submission and never used for scoring; it changes if the participant changes their view. Freezing Your View at confirmation (Option B) is not built: it would make entries read private analysis and record past adjustments, which needs a separate decision (D-41) |

## Provisional (empirical) — synthetic evidence, to confirm on real pools

Evidence: [championship scoring research](../research/weekly_challenge_championship_scoring.md)
and [risk-structure research](../research/weekly_challenge_risk_structure.md).

| ID | Finding | Status |
|---|---|---|
| P-01 | Under the preferred schedule (D-31), championship points track **recoveries** (Spearman 0.94–0.99 from 5 to 1,000 entrants); the champion's best round is 14–21% of their total | Provisional (6A.2.1) |
| P-02 | Recovery-focused selection is favoured at every field size (1.56–2.97× its share); lowest-in-band never exceeds proportional (max 1.04 ± 0.16 at 100 entrants) | Provisional (6A.2.1) |
| P-03 | Cumulative net is close to a lottery; F1-style rewards variance in large fields; percentile rewards low-variance finishes without recovery (Phase 6A.2) | Provisional |
| P-04 | The old 50-floor schedule rewarded high variance at 50–100 entrants (lowest-in-band 1.43–1.86×). The 75 floor removes this; the compressed top ten adds a further gain at 10–25 entrants. Paired (CRN) reductions are significant from 10 to 500 entrants | Provisional (6A.2.1) |
| P-05 | The weekly tie rule has a negligible effect on incentives (paired differences within Monte Carlo error). Ties crossing the top-ten boundary occur in 4–11% of rounds at 50+ entrants; first-place ties in ~1% | Provisional (6A.2.1) |
| P-06 | The real weekend pool passes every opening check; 15-fixture random sub-pools open 99.75% of the time (Phase 6A.2) | Provisional |
| P-07 | Points are never negative, so skipping a round can never help; late joiners finish lower on average, as intended (Phase 6A.2) | Provisional |
| P-08 | Full-points ties are **duplication-neutral**: a duplicated portfolio earns what it would earn if entered once; average-points ties penalised duplicates. Duplicated portfolios almost never win championships | Provisional (6A.2.1) |
| P-09 | A trailing participant gains nothing significant by switching to high variance in rounds 8–10 under the preferred schedule (it did at 100 entrants under the old one) | Provisional (6A.2.1) |
| P-10 | Joint champions become common in very large fields under the 75 floor (19% at 500, 27% at 1,000 entrants), driven by the floor, not the tie rule | Provisional (6A.2.1) |

## Proposed (technical) — adopted unless you object

| ID | Proposal | Rationale |
|---|---|---|
| T-01 | Generalised engine `ChallengeConfig` (bands, sizes, stakes, classification source); the 6A 3/3/3 config kept as a legacy regression vector | Reuses tested 6A code; one source of truth |
| T-02 | Bucket derived server-side from the stored full-precision `market_prob`; the client never sends a bucket | Integrity; no boundary disputes from display rounding |
| T-05 | Points stored as integers; championship standings computed by aggregation, plus a frozen snapshot at completion (replaces the fraction storage needed only by the superseded average-points rule) | Corrections re-score automatically |
| T-07 | Round **designation** fixed at the deadline: `championship` / `practice` / `postponed` / `void`. Afterwards a round can become void only through the approved D-32b rule at final settlement (which depends on which predictions were tested, never on results) or an audited operator action | Designation must not depend on match results |
| T-08 | **Void round:** a round cancelled or invalidated as a whole after the deadline returns every stake and does not count (no points, counter unchanged). Partial voids settle normally under D-32; widespread voids invalidate a round under the approved D-32b rule | Prevents an all-void round handing every entrant 100.00, a recovery and a shared first place (150 points each) |
| T-06 | Any settlement correction re-scores the whole round; after a championship is frozen, only the audited `--reopen` path | Positions depend on all entrants |
| R-01 | Common deadline: earliest eligible kickoff minus 15 minutes | Unchanged from 5C |
| R-02 | Round sheet frozen at publish | Unchanged |
| R-03 | Picker lists only eligible outcomes, with a count of the hidden fixtures | Unchanged |
| R-04 | One entry per user per round, resubmittable until the deadline | Unchanged |
| R-06 | Dependency-free production maths with exact decimals | Unchanged |
| R-07 | Settle on the 90-minute score | Unchanged |
| R-08 | Void selection = odds 1.00; an all-void bucket returns its own stake (40 / 30 / 20); a fully void portfolio follows D-33 (refunded, unranked, not a recovery) | Updated for unequal stakes; consistent with D-32 and D-33 |
| R-09 | Same as D-15 | Unchanged |
| R-11 | Routes `/challenge`, `/challenge/learn`, `/challenge/me`, `/leaderboards` | Adds the learn page |
| R-14 | 24-hour correction window before a round is final | Unchanged. **Defined 19 Nov 2026 (S-02)** |
| T-09 | **(Approved, Phase 6C architecture finalisation)** **Server-side withdrawal (new):** only before the deadline; an insert-only withdrawal record; a withdrawn entry is not in the locked set (does not count for D-28 or D-32b); the participant may submit again before the deadline. *Clarified by the owner on 20 Nov 2026: a withdrawal also clears the participant's saved predictions for that round (a fresh start, as in the browser-only flow); the withdrawn submission stays in the entry history* | The prototype withdrawal is a browser note only |
| T-10 | **(Approved, Phase 6C architecture finalisation)** **Your View storage (new):** private per user and fixture, with the Phase 6B.3 model-context stamp; never used for submission, settlement or scoring; deleted with the account | Keeps Your View educational and separate from the competition **Refined at the 6C.3 checkpoint:** one current numerical state per user, fixture and analytical context: the live Match Lab context, and each published round's frozen snapshot context (identified by the snapshot, determined on the server). Saving or resetting one context never changes another; no history is kept (D-41) |
| T-11 | **(Approved, Phase 6C architecture finalisation)** **Designation history and derived counters (new):** designations are insert-only records with a basis (`deadline`, `d32b`, `operator`) and reason; the latest is current. Championship round numbers, the counter, points and standings are derived from current designations and settlements | D-32b reassessments and corrections can never duplicate points or advance the counter twice |

## Outstanding — owner decision needed

A recommendation is not an approval. Options and rationale: the
[outstanding decision review](weekly_challenge_phase6c_decision_review.md) and the
documents linked below.

| ID | Question | Recommendation | Needed |
|---|---|---|---|
| D-29 | **Championship scoring validation (open validation requirement):** validate `points-150-75-v2` and D-32b on six to eight qualifying real weekly pools (observed voids separate from simulated scenarios). Retain D-31 unless the evidence is compelling | Run as pools accumulate | Before the first official championship |
| D-36 | Final data-retention policy | Pseudonymisation as in the database design §11; log retention 30 days; backups per provider schedule; legal review | Before launch |

## Superseded Phase 5C items

| Old ID | Old decision | Superseded by |
|---|---|---|
| C-02 | 3 buckets × 3 picks; 30/30/30/10 | C-09, C-10, C-11 |
| C-03 | All 280 arrangements shown; dominated ones disabled | C-13 |
| C-04 | Frontier chart (recovery × expected return) | C-13 |
| C-05 | Recommended = efficient with the highest recovery | C-13 |
| R-05 | Store all 280 points per submission | Design §4.3: inputs plus 8 states only |
| R-10 | Weekly ties share a rank, net only | D-26 (shared position plus averaged points) |
| R-12 | Market probability shown only in tooltips | C-09 (market probability decides the bucket and is always shown) |
| R-13 | Frontier marker and tie rules | C-13 |
| R-15 | Payout chart under the selected grouping | C-08 (kept, under the complete portfolio) |
| D-07 | Edit policy | Folded into R-04 (unchanged) |
| **D-09** | Season scoring: average net per round entered, with a qualification threshold | **C-19, C-20, D-27:** 10-round championships with recovery-gated points |
| D-10 | Market-implied expected return omitted from the MVP | C-14 (market and model shown separately) |
| D-13 | Season definition (Aug–May) | C-19 (championships of 10 completed rounds) |
| C-20 (6A.2 schedule) | 150/135/120/110/100/95/90/85/80/75, 50 outside the top ten | D-31 (`points-150-75-v2`), approved Phase 6A.3 |
| D-26 (6A.2 proposal) | Average-points weekly ties with exact fractions (e.g. 63.75) | D-26 approved: standard competition ranking, full points, integers |
| T-03, T-04 (6A.2) | Proposed opening checks and 5-entrant minimum | D-28 approved |
| T-05 (6A.2) | Points stored as exact fractions | T-05 revised: integers |
| D-28 (6A.2) | "Confirm D-26, D-27, T-03 and T-04" | D-26, D-27, D-28 approved |
| D-30 (6A.2) | Copy for a championship cut short | D-30 approved: pause, never shorten |
| D-14 | Merge Phase 5B research | Not needed: 6A.1/6A.2 research is stdlib-only and self-contained |
