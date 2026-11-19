# Match Lab: factor guidance (MVP refinement)

*November 2026, decision D-41. Presentation only: Goal Model 1.0, the adjustment
calculations, limits (Section B ±1.00, Section C ±2.00 per factor, steps of 0.05),
probabilities, Weekly Challenge eligibility, odds, buckets, credits, settlement and
scoring are unchanged.*

## What changed

Sections B and C of Match Lab used to ask for a free-text reason ("Why are you
making this adjustment?") and per-factor "Research notes", shown afterwards as a
"Note" marker. They are replaced by short, static guidance that explains how to
think about each factor: what to look at, how it could move each team's estimated
goals, and when to leave the adjustment at zero. Users now only set numbers.

* No free-text fields remain in Match Lab's adjustment sections, and the final
  manual adjustment (Section D) has none.
* Your View in the browser tab holds numbers only. A Your View saved by the
  earlier version keeps its numbers exactly; its notes are ignored when read and
  dropped the next time it is saved.
* Verified: the old and new code give identical estimates, breakdowns, messages
  and probabilities over 19,575 random adjustment steps.

## Final wording

**Section B, Your Match Context Adjustment**

> Recent form, league position and head-to-head results are partly reflected in
> the model's estimated goals already. Adjust only if the context suggests
> something this season's goal data misses, such as a recent run that reflects a
> genuine change rather than an easy or difficult set of fixtures. Head-to-head
> results from earlier seasons often involve different squads and managers. Judge
> each team separately, keep adjustments modest, and leave them at 0.00 if the
> context only confirms what the model shows.

**Section C, introduction**

> These factors are not included in the statistical model. Adjust only for
> information the model has not already captured, judge each team separately, and
> leave an adjustment at 0.00 when the evidence is unclear.
>
> *(highlighted)* Adjustments are your own estimates, not guaranteed improvements.
> Related factors can overlap with each other and with recent results: avoid
> counting the same information twice.

**Squad & Availability** (injuries, suspensions, expected starting line-ups,
transfers and squad changes)

> Consider which key players are unavailable or likely to be rested, how important
> they are to the team's attack or defence, and the quality of their replacements.
> A missing first-choice striker may lower that team's estimated goals; an absent
> central defender or goalkeeper may raise the opponent's. Recent transfers matter
> mainly when this season's results do not yet reflect them.

**Fitness & Scheduling** (fixture congestion, rest days, travel demands, squad
rotation)

> Consider how many matches each team has played recently, their rest days and
> travel, and whether heavy rotation is likely. A tired or much-changed side may
> create fewer chances and concede more. Small differences in rest rarely justify
> more than a small adjustment.

**Tactics & Management** (managerial changes, tactical changes, changes in playing
style, relevant tactical matchups)

> Consider managerial or tactical changes that this season's results may not yet
> reflect, and how the two styles are likely to interact. A more attacking approach
> can raise both a team's estimated goals and its opponent's; a defensive set-up may
> lower both. A few matches under a new manager are a small sample.

**Match Conditions & Motivation** (weather and playing conditions, unusual venues
or home advantage, title or relegation circumstances, competition motivation and
other match-specific circumstances)

> Consider weather and pitch conditions, an unusual venue, and what each team is
> playing for. Heavy rain or strong wind often lowers scoring for both sides, and a
> team with little to play for may be less sharp. Motivation is hard to measure, so
> keep any adjustment modest unless the evidence is clear.

**Layout.** On screens wider than 760px each card in Sections B and C uses two
columns: the keywords and guidance on the left (about 60%), and the home and away
controls stacked on the right (about 40%) behind a subtle divider, aligned at the
same position in every card. Headings and status span the full width; Section B's
clear button and guardrail text sit beneath. Smaller screens stack heading and
status, keywords, guidance, then the home and away controls. Screenshots:
`layout_section_*` in `docs/screenshots/match_lab_guidance/`.

The wording lives in `src/diski9/app/lab.py` (`CONTEXT_ADJUST_NOTE`,
`FACTORS_NOTE`, `FACTORS_CAUTION`, `CATEGORY_GUIDANCE`). Screenshots before and after:
`docs/screenshots/match_lab_guidance/`.

## Direction for Phase 7 (Lucy)

The guidance is written as a shared analytical framework: the same questions a
person asks when adjusting a factor are the questions Lucy will work through. The
intended Phase 7 experience (not built; nothing of it exists in the MVP):

1. For a fixture and a factor, Lucy researches the relevant information.
2. Lucy presents verified findings with their sources.
3. Lucy explains why each finding matters, framed by that factor's guidance (which
   team, attack or defence, likely direction).
4. Lucy may suggest an estimated-goal adjustment within the existing limits, with
   its uncertainty and rationale, including "no adjustment" when evidence is weak.
5. The user can discuss the analysis with Lucy.
6. The user explicitly accepts or rejects each suggestion; only an accepted
   suggestion changes the user's numbers, exactly as if they had set it themselves.

Lucy does not fill in note boxes, and suggestions never change the model, the
Weekly Challenge or any competition record. Lucy's findings and conversations
belong to Lucy's own workspace (its separate schema, behind the `lucy.*`
entitlements), not to Your View.

## Deferred (not in the MVP)

Historical adjustment reasons, adjustment versioning, prediction journals,
qualitative-factor performance attribution, personal prediction dashboards,
research-note collection for model training and the consent flows these would
need. They may be reconsidered after feedback from real users (D-41).
