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
