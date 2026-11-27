# Future product enhancements (backlog)

Documented ideas approved for the backlog only. Nothing here is implemented or
scheduled; each item needs its own design, data audit and owner approval. The
Educational Experience Enhancement workstream (glossary, guidance and future
educational topics) is recorded separately in
[`../architecture/weekly_challenge_a3_implementation.md`](../architecture/weekly_challenge_a3_implementation.md)
("Future educational opportunities").

## Release dependency: Official championship scheduling (Phase 10; required)

Recorded 24 Nov 2026 at Scenario A3 Checkpoint 4C. This is a **deployment and
private-Beta exit requirement**, not optional backlog. The scheduled `weekend` series
is Beta, and A3 (`app_0009`) preserves that binding; the scheduler supports Beta only.
Before public Official competition, a separately approved Phase 10 work item must
deliver:
* Official championship scheduling;
* automatic Official round creation;
* A3 configuration binding for Official rounds;
* Beta and Official isolation;
* the controlled transition from private Beta to public Official competition.

Not implemented in Scenario A3. Details:
[`../architecture/weekly_challenge_a3_implementation.md`](../architecture/weekly_challenge_a3_implementation.md)
(Checkpoint 4C).

## Release dependency: administration device migration (Phase 10; required before Phase 11)

Recorded 25 Nov 2026 at Stage F3 Checkpoint 2 (owner decision). Diski 9 is
administered during the MVP from the owner's **employer-managed** MacBook, an accepted
risk ([`../architecture/phase6c6_implementation.md`](../architecture/phase6c6_implementation.md)
§13.14). Credential security and privacy risks are reassessed before the F5 invited
Beta. **Before Phase 11 public launch**, a Phase 10 work item must move administration
to the owner's personal MacBook, including:
* new SSH and WireGuard credentials generated on the new device;
* revocation of the old device's access (WireGuard peer, SSH key);
* credential review and rotation where appropriate;
* removal of the private CA trust from the old device;
* independent verification of access from the new device.

Retained at Checkpoint 2 acceptance (25 Nov 2026), together with the pre-F5
reassessment. Not implemented in Stage F3.

## Achievements beyond the Phase 7 MVP (not committed)

Phase 7 delivers six badges and three levels only
([`../architecture/phase7_achievements.md`](../architecture/phase7_achievements.md)). Removed
proposals are **not** committed future work. They may be reconsidered after launch only if
genuine user feedback justifies them:
* Beat the Bookie, Payback Pirate and Payback Week, Top Ten Titan and Top Ten,
  Championship Winner, Clean Sweep, Consistency Champion, Away Day Specialist;
* unlocking, XP, streaks, achievement leaderboards, public achievement profiles, reward
  shops, feature unlocks, configurable rules and levels beyond Pro.

Draw Dynamo and level achievability can be reassessed with Beta data.

## Personal Performance Analytics (post-launch; not implemented)

Recorded 24 Nov 2026 at Scenario A3 Checkpoint 4B. Documentation only: no
implementation during Scenario A3 or Stage F3.

**Unlock rule:** the dashboard unlocks after a participant completes **three eligible
Weekly Challenge rounds**. Three rounds unlock it; they do not make the figures
statistically significant.

**Potential analytics:**
* performance by league and team;
* performance by market: 1X2, BTTS and Over/Under 2.5;
* Foundation, Balanced and Challenger performance;
* accuracy across market probability ranges;
* personal probability adjustments compared with the Goal Model and the market;
* accumulator completion rates;
* historical prediction accuracy and virtual-credit performance trends.

**Data principles:**
* use actual historical submissions and authoritative settled results only;
* preserve the frozen odds, probabilities and configuration versions recorded with
  each entry (never recompute with current data or a later configuration);
* audit data availability before implementation (which submissions, results and
  frozen values exist for every participant and round);
* show sample sizes beside every figure, and an insufficient-data notice where a
  breakdown has too few predictions to mean anything.

**Purpose:** education and better analytical understanding of one's own predictions.
It must not encourage increased risk-taking (no streak pressure, no "chase" prompts,
no framing of past results as a reason to stake differently).

## Phase 8 deferred register (recorded 27 Nov 2026; not committed, not in the MVP)

Recorded at the Phase 8 CP1 decisions. None of these may enter the MVP without explicit
owner approval. Detail and evidence:
[`../architecture/phase8_implementation.md`](../architecture/phase8_implementation.md) §10.

**Modelling and data**
* Independent European competition modelling (Champions League, Europa League), only if
  justified by evidence and user demand; re-evaluate the Champions League model after
  the 2026/27 season.
* Low-data and alternative modelling investigations (previous-season carry-over,
  cross-league strength, alternative low-data models), only if subsequently justified.
* Dixon–Coles (or similar) market fit to reduce the draw residual of the Poisson market
  fit (mean draw residual −1.46 pp in CP1).
* Additional European competitions (the Conference League is excluded from the MVP).
* Midweek and European Weekly Challenge rounds.

**Product and education**
* Edge-based recognition enhancements; user-versus-market analysis; a public track
  record.
* Educational enhancements and additional analytical education beyond the MVP Learn
  section and Match Lab explanations.
* An independent Diski 9 probability threshold filter (removed from the MVP by OD-4,
  27 Nov 2026; the MVP has one Minimum Market Probability slider).
* Personal Performance Analytics (recorded above).
* Achievement threshold reassessment with Beta data (recorded above).
* Private mini-leagues (removed from the MVP roadmap; reconsider only with active users).

**Operations and housekeeping**
* ML-01 Match Lab stale-adjustment race: **required before private Beta** (Phase 6
  register).
* A3 housekeeping items carried from Scenario A3.
* Egress policy reassessment after Phase 9 (API-Football block decision).
* Account deletion and privacy gates before launch.
* The administration move to the personal MacBook: **mandatory within Phase 10, before
  wider MVP participation** (owner, 27 Nov 2026; recorded above). The employer-device
  reassessment happens before participant-dependent testing.
* API-Football subscription continuity: Pro expires 14 Dec 2026 with no auto-renewal
  (owner considering a longer term in December).

## Learn: future educational resources (recorded 27 Nov 2026; not MVP commitments)

Owner direction at the Phase 8 CP2A closure. Core lightweight Learn content stays in
Phase 8 CP3B, unchanged. Everything below needs its own later approval; no CMS, resource
management system, PDF generation or video hosting infrastructure is to be introduced
for it.

* **Downloadable resources** (future enhancement, timing to be decided): PDF educational
  guides, worked examples, probability cheat sheets and research summaries.
* **YouTube integration** (Phase 11 and ongoing, subject to approval): embedded videos
  and tutorials from the owner's Diski 9 channel, linked to the relevant Learn topics.
* **Recommended reading** (future enhancement): books, academic papers, websites and
  other football-analytics resources.
* **Growth:** content expands over time with user feedback and the YouTube channel.

Intended relationship: **YouTube = discover · Learn = understand · Match Lab = apply ·
Weekly Challenge = practise.**

Also deferred at the same closure: a version-aware mode for
`tools/phase6c3_quant_regression.py`, only if a future need arises (the tool stays
unchanged, and its accepted Goal Model 1.0 baseline remains reproducible at its original
commit).
