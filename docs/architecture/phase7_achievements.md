# Phase 7: Rewards & Achievements (design and decision record)

**Status:** Checkpoint 0 (requirements and discovery) accepted by the owner on 26 Nov 2026.
CP1/CP2 (this design record, the backend and focused tests) is implemented and awaits
independent review and owner acceptance. CP3 (frontend, visual review, end-to-end
validation, full regression and closure) is not yet authorised.

**Code:** `src/diski9/backend/services/achievements.py`.
**Tests:** `tests/test_achievements.py` (pure rules) and
`tests/backend/test_backend_achievements.py` (PostgreSQL).

This record supersedes earlier achievement proposals. In particular, the "Phase 9 badges
and achievements derived from `domain_events`" notes in
[`phase6c_architecture_considerations.md`](phase6c_architecture_considerations.md),
[`phase6c_database_design.md`](phase6c_database_design.md) §8.3 and
[`phase6c5_design_specification.md`](phase6c5_design_specification.md) §11.5 and §19 are
superseded. They remain unchanged as historical records.

## 1. Purpose

Achievements recognise prediction skill and give a longer-term journey that does not
depend on weekly rank, recovery or championship position. They are **recognition
only**: no credits, points, prizes or entitlements, and no effect on rankings,
standings, entry rules, settlement, scoring or configuration.

## 2. Approved badges (owner, 26 Nov 2026)

Each badge is awarded at most once per user per eligible round. Different badges can be
earned in the same round. One correct selection can count towards a bucket badge and a
market badge. All six are available from the start, with no unlocking, expiry or reset.

| Badge | Qualification in one eligible round |
|---|---|
| Foundation Fundi | All four Foundation selections correct |
| Balanced Brawler | All three Balanced selections correct |
| Challenger Champ | Both Challenger selections correct |
| Goals Guru | At least three correct Over/Under 2.5 selections (Over and Under mixed), across all nine |
| BTTS Bonanza | At least three correct BTTS Yes/No selections (mixed), across all nine |
| Draw Dynamo | At least **two** correct draw selections, across all nine (D-1) |

**How voids are treated:**

- A void selection is never correct.
- A bucket containing a void selection cannot earn its perfect-bucket badge.
- The entry's other genuinely correct selections still count.

## 3. Levels (D-1, revised)

| Level | Qualification |
|---|---|
| Beginner | Default |
| Semi-Pro | At least **one** badge of **each** of the six types |
| Pro | At least **three** badges of **each** of the six types |

**How the level is calculated:**

- The level depends on the lowest of the six counts, with categories at zero included.
  The total does not decide it: for example, counts of 10, 10, 10, 10, 10 and 0 are still
  Beginner.
- Badges keep accumulating after Pro.
- Level emblems are not badges.
- Levels show accumulated accomplishments across categories. They are not a
  statistically validated rating of skill.
- **Next-level progress:** the level is calculated on every read (`level_for`,
  `progress_for`). Progress names the categories still below the next target.

## 4. Pace and achievability (indicative only)

- **Three correct draws:** the committed real-odds research pools contain no draw priced
  above 29% (`docs/research/weekly_challenge_risk/pool_weekend.json` and
  `pool_fortnight.json`). Draws therefore fall in Challenger, which holds two selections.
  So three correct draws in one entry are **practically unachievable under the current
  configurations**. This is not a mathematical impossibility for every conceivable price,
  and it is why D-1 sets Draw Dynamo at two.
- **Rarest badges:** Challenger Champ (about 7% a round for a random A3 strategy;
  `docs/research/weekly_challenge_bucket_review.md` §7) and, when attempted, Draw Dynamo
  are the rarest.
- **What the estimates mean:** the expected wait for one badge is not the expected time
  to complete all six categories. Draw Dynamo and Challenger Champ are often earned
  together, and actual progression depends on each user's strategy and participation.
  No threshold optimisation was done; achievability can be reassessed during Beta.

## 5. Eligibility and publication

| Rule | Implementation |
|---|---|
| Authoritative point | The round's **latest published score set**, published atomically with finalisation |
| Order of filters | The latest score set revision is chosen **before** eligibility, whatever its kind. A competitive round later republished as void loses all its badges |
| Eligible round | That latest score set has `kind = 'championship'` (competitive) |
| Eligible entry | The viewer's locked entry has `round_scores.status = 'ranked'` |
| Excluded | Practice and void score sets; `void_refunded` entries (all nine void, D-5); rounds with no published score set (provisional, awaiting results or never published) |
| Championship membership | Irrelevant: a competitive round marked `not_counted` still awards badges (D-2) |
| Reopened round | Keeps its last published score set until republished. Provisional revisions never count (D-4), matching the leaderboards and My Challenge History |
| Corrections | Republication is reflected automatically, including counts and levels going down |
| History | Every eligible published round in the stream is included. There is no back-fill process |

## 6. Settlement revision binding

- **Which revision is evaluated:** the entry settlement revision with the highest
  `revision` among those whose `run_id` is no later than the score set's `run_id`.
- **Why this matches the settlement lifecycle:**
  - Revisions are written only when an entry changes (`settlement.apply`), so an
    unchanged entry keeps an earlier revision. That is why an exact `run_id` match is not
    required.
  - Run IDs are an increasing identity, and per-entry revisions increase with successive
    runs.
  - Publication (`competition.publish_finalised`, called by `corrections.finalise_round`)
    uses the latest revision at finalisation, and the score set records the final run.
    The binding therefore reproduces exactly the revision the publication was built from.
  - After a reopening, new provisional revisions belong to later runs and are excluded.
- **Single snapshot:** the whole read is one `REPEATABLE READ`, read-only transaction (the
  same `_snapshot` helper the leaderboards use). Concurrent republication therefore cannot
  mix versions.

## 7. Historical data

- **Source of the predictions:** the predictions come from the entry settlement's stored
  `legs`. Each leg holds its position, frozen bucket, market, outcome and verdict, as
  written by `settlement._legs_json`.
- **Validation:** the legs are checked against the **round's own frozen configuration**
  (`rounds.config_version` → `get_config`). The checks are:
  - nine predictions with positions 0–8;
  - 4/3/2 bucket counts;
  - each outcome valid for its market, taken from the authoritative definitions
    (`diski9.api_football.markets.MARKET_OUTCOMES`):
    - 1X2: `HOME`, `DRAW` or `AWAY`;
    - BTTS: `BTTS_YES` or `BTTS_NO`;
    - OU25: `OVER_2_5` or `UNDER_2_5`;
  - verdicts of `won`, `lost` or `void`;
  - exact JSON types: an integer position, and string bucket, market, outcome and
    verdict. Missing fields or values of another type are refused.
- **No reclassification:** buckets are never reclassified, so Broad60 and A3 bindings are
  preserved.
- **Bad or missing records:** a missing, incomplete or malformed authoritative record, or
  one for a different submission, raises `AchievementIntegrityError`
  (`code = "achievement_integrity"`, with a message that is safe to show). The summary is
  refused rather than shown as zero achievements. Nothing is guessed from current odds or
  configuration, and no repair is attempted.

## 8. Architecture: derived, not persisted (D-6)

**What the service consists of:**

- **Pure rules:** `badges_for` and `level_for` / `progress_for`.
- **One participant-scoped SQL read:** it covers the viewer's locked entries in one
  stream, each round's latest score set, the entry's score row and the bound entry
  settlement. It uses existing indexes (`ix_entries_user`, `ix_score_sets_round`, the
  score set and entry primary keys, `entry_settlements (entry_id, revision)`). There is no
  N+1 pattern, no caching and no new index.
- **Public functions:**
  - `my_achievements(engine, viewer, *, stream, include_development)` returns the six
    counts (zeros included), the total, the level, the progress and the badges per
    eligible round;
  - `my_round_badges(engine, viewer, round_id, …)` returns one round's badges under the
    same rules, for the History detail view in CP3.

**Not added:**

- tables, migrations, stored counts or a stored level;
- a promotion service, jobs or event handlers;
- caching or new infrastructure;
- any change to settlement, scoring or configuration.

**Why nothing is stored:** a stored model would need writers inside the finalisation and
reopening transactions, idempotency, recalculation after corrections, a back-fill and its
own tests. No correctness, performance or architectural need justified that. If a
genuine limitation appears, work stops and the evidence and alternatives go to the owner
before any architecture is added.

## 9. Streams, security and privacy (D-3)

- **Separate streams:** Development, Beta and Official counts and levels are strictly
  separate. Official starts at zero at launch, and Beta remains a separate record under
  the existing stream visibility rules. There is no reset between championships within a
  stream, and no Beta archive interface.
- **Identity:** the viewer comes from the authenticated server-side principal. Guests
  get `None`. Every read is filtered by the viewer's own user ID, including the
  single-round lookup.
- **Development stream:** needs `include_development`. The caller passes the server's own
  setting (`Backend.show_development`, from `DISKI9_SHOW_DEVELOPMENT_ROUNDS`, which is
  refused in production), never a browser value. Without it the stream raises `NotFound`.
- **Personal data and deletion:** no new personal data is stored, and achievements stay
  private for the MVP. Account deletion and anonymisation (D-36) are unchanged; derived
  achievements need nothing extra.

## 10. User interface (D-7; CP3, not yet authorised)

- **Placement:** a third **Achievements** segment beside Current and History on My
  Challenge, with no new navigation tab.
- **Contents:**
  - the level emblem and name;
  - the total;
  - progress that makes the every-category rule clear;
  - six cards in Bucket and Market groups, each with a name, icon, rule, count and
    progress towards the next level.
- **Per-round chips:** optional small badge chips in the History detail view.
- **Owner review:** the visual design is reviewed by the owner in CP3.

## 11. Testing

- **Unit tests** (`tests/test_achievements.py`): every rule, its exact thresholds and the
  cases below them:
  - Draw Dynamo at two;
  - mixed Over/Under and Yes/No selections;
  - markets across buckets;
  - voids;
  - several badges in one round, with no duplicates;
  - all the owner's level examples, zero categories and accumulation beyond Pro;
  - progress;
  - stored-leg validation, including malformed variants and an unknown configuration.
- **PostgreSQL tests** (`tests/backend/test_backend_achievements.py`), run as one story
  through the real services:
  - provisional rounds award nothing, and published rounds do;
  - a round republished as void loses its badges;
  - a `not_counted` round still awards badges;
  - practice, void and refunded entries are excluded;
  - a partially voided entry still earns its other badges;
  - accumulation across championships;
  - a reopened round keeps its badges until republished;
  - a correction demotes the level, and a further correction restores it;
  - an unchanged entry whose revision predates the republished run;
  - isolation of the Development, Beta (an A3 round finalised on the real clock) and
    Official streams;
  - development visibility authorised by the server;
  - guests and cross-user reads;
  - read-only behaviour;
  - a malformed authoritative record is refused.
- **Test helpers:** the test helpers gained optional, default-preserving parameters:
  extra Draw, Over 2.5 and BTTS No offers, a configuration version, a non-development
  stream and a correction window.
- **Full regression:** the full regression run and the end-to-end development
  championship exercise are reserved for CP3.

## 12. Checkpoints (D-8)

| Checkpoint | Scope | State |
|---|---|---|
| CP0 | Requirements and discovery | Accepted, 26 Nov 2026 |
| CP1/CP2 | Design record, backend, focused tests | Implemented; awaiting review and acceptance |
| CP3 | Frontend, visual review, end-to-end validation, full regression, closure | Not authorised. Backend acceptance is the gate |

## 13. Deferred and out of scope

The following are **not** part of the MVP. Removed proposals are not committed future
work:

- the removed badge proposals: Beat the Bookie, Payback Pirate and Payback Week, Top Ten
  Titan and Top Ten, Championship Winner, Clean Sweep, Consistency Champion and Away Day
  Specialist;
- unlocking, XP and points, streaks;
- achievement leaderboards and public profiles;
- shops and prizes;
- feature unlocks;
- progression engines and configurable rules;
- levels beyond Pro.

Personal Performance Analytics, broader educational enhancements, private mini-leagues
and commercialisation remain deferred. Stored achievements would be reconsidered only if
an approved future feature (for example, public achievements) needed them.
