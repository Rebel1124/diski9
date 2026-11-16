# Milestone 5.3 — Screener presentation: BTTS and Over/Under 2.5

*16 November 2026. The dark theme, table, cards, pagination, sorting, filters,
selection highlighting, market tabs, expanders and freshness labels are all
unchanged. Only what the BTTS and Over/Under views emphasise has changed.*

## 1. Why

Milestone 5.2 found that, read as probabilities, the averaged team-history
percentages are less accurate than the league's own rate:

| Market | Brier: team history | Brier: league rate |
|---|---|---|
| BTTS | 0.264 | 0.248 |
| Over 2.5 | 0.261 | 0.243 |

They also barely rank fixtures within a league (AUC about 0.5). Historical
records are still true and useful as a description of the past. They just
should not look like a forecast. So the screen now separates three questions:

| Layer | Question it answers | Example |
|---|---|---|
| Historical records | What happened in these teams' recent matches? | Aston Villa: BTTS in 6 of 10 |
| League baseline | How often does this happen in this competition? | League BTTS baseline 49% |
| Market-implied probability | What do bookmakers' prices imply? | BTTS Yes 54.7% · BTTS No 45.3% (Fresh) |

No model-generated probability or expected goals appears anywhere (Layer 3
stays in research).

## 2. Expanded fixture analysis

Screenshots: `docs/screenshots/m53_btts_detail.png` and `m53_ou25_detail.png`.

**Both Teams to Score**

```
HISTORICAL RECORDS (i)
  Aston Villa                       Sunderland
  BTTS in 6 of 10                   BTTS in 4 of 10
  No BTTS in 4 of 10                No BTTS in 6 of 10
  current-season matches            current-season matches

LEAGUE BTTS BASELINE (i)
  49%   Premier League 2026/27: 100 matches before kickoff

REFERENCE ODDS  [Fresh]  checked by Diski 9 …; provider update …
MARKET-IMPLIED PROBABILITIES (i)
  BTTS Yes 54.7%  |  BTTS No 45.3%
  [Yes 1.70] [No 2.05]
```

**Over/Under 2.5** uses the same layout:
* records: "Over 2.5 in 6 of 10" and "Under 2.5 in 4 of 10"
* "League Over 2.5 baseline"
* market-implied "Over 2.5 | Under 2.5"

**Design rules applied:**
* **Counts, not percentages, for team history.** Both outcomes are shown
  ("BTTS in 6", "No BTTS in 4"), with the true denominator.
* **Equal typography for paired market outcomes** (22px / 700 each, verified in
  the browser). The higher probability is never enlarged.
* **The averaged team percentage is no longer a headline.**
  * It survives only in the "How are these figures calculated?" expander, as
    *"Recent BTTS occurrence (average of the two shares): 50%. Used only to
    order fixtures in the 'recent occurrence' rankings. It describes past
    matches and is not a probability for this fixture."*
  * It is never called a predicted probability, confidence or "Diski
    probability".
* **Prices are shown once.** The price cells no longer repeat the implied
  percentage.

## 3. Fixture tables and cards

| BTTS table column | Content | Tooltip |
|---|---|---|
| Home record / Away record | `6/10` (BTTS matches / current-season matches), `—` with no history | yes |
| Recent BTTS (sortable) | average of the two shares, regular weight (not emphasised) | "Historical occurrence … (not a probability)" |
| League | league baseline | yes |
| Market Yes · No | market-implied probabilities, e.g. `55% · 45%` (whole %, same consensus as the detail), with a `stale` tag when Stale | yes |
| Data | `Limited` marker | yes |

* Over/Under is identical, with "Market Over · Under".
* The historical complement column ("BTTS No" / "Under 2.5") was removed. The
  table keeps 10 columns.
* Mobile cards show `BTTS records 6/10 · 4/10`, `League 49%` and
  `Market 55% · 45%`.

**Rankings,** relabelled to describe what they sort by (the algorithm is
unchanged):

| BTTS | Over/Under |
|---|---|
| Highest recent BTTS occurrence | Highest recent Over 2.5 occurrence |
| Lowest recent BTTS occurrence | Lowest recent Over 2.5 occurrence |

**Thresholds:**
* Labels are "Minimum recent BTTS / no-BTTS / Over 2.5 / Under 2.5
  occurrence".
* They are disabled for kickoff ordering, with the hint "Available for
  recent-occurrence rankings".

**Legend:** "Records use up to ten current-season matches; recent occurrence
and league baselines are historical, not predicted probabilities."

## 4. League baseline methodology

> **Superseded (engine 2.2.0):** league baselines now use the current season only, with no previous-season blending, and are unavailable below 30 matches. See [`ui_cleanup_and_baseline.md`](ui_cleanup_and_baseline.md). The description below is kept as a record of engine 2.1.0.

This is the exact Milestone 5.2 research rule (`engine.league_baseline`). A
test checks it equals `research.historical_goals.league_prior`.

1. Take the fixture's competition and season.
2. Take the eligible league matches of that competition and season that kicked
   off **before** the fixture. These are the same matches every other
   statistic uses. The following never enter:
   * awarded, abandoned and postponed fixtures
   * play-off rounds
   * confirmed neutral venues
   * other competitions
   * later results
   * the fixture itself
3. With **30 or more** such matches: baseline = the share with BTTS (or 3+
   goals). Label: *"Premier League 2026/27: 100 matches before kickoff"*.
4. With **fewer than 30** and the previous season of the same competition
   stored: blend, with the current season weighted n ÷ 30. Label: *"Premier
   League 2026/27 (11 matches) blended with 2025/26"*, plus the visible note
   *"League baseline uses last season's league results to stabilise the
   estimate while the current season is still young."*
5. With **no** current-season match: the previous season alone. Label: *"… 2025/26
   results (no 2026/27 matches yet)"*.
6. With fewer than 30 matches and no previous season stored: **Unavailable**.
   Label: *"Not enough league history is stored for this competition yet."*
   No value is invented.

**Rules that keep the layers separate:**
* Previous-season data is used **only** for the league-level baseline.
* Team records remain current-season, current-competition only. That is
  tested: a team's previous-season and other-division matches never enter its
  record.
* The expander states the arithmetic, for example *"12 2026/27 matches
  weighted 12/30, blended with 2025/26 (380 matches)"*.

Screenshot `m53_league_baseline_explanation.png` shows the blended case, taken
from a copy of the database evaluated on 29 August 2026.

## 5. Early-season and missing data

* **The Limited threshold is unchanged at six** current-season matches (and
  three current-division matches).
* A small team sample shows its true count with a small `Limited` tag beside
  that team ("BTTS in 1 of 1 — Limited"), plus one short line: *"Fewer than six
  current-season matches for at least one team: the records are a small sample.
  The league baseline gives wider context."*
* The league baseline is always labelled as the league's figure, never put in
  a "team rate" field.
* **No eligible matches:**
  * The detail says "No current-season history" and the table shows `—`.
  * Never "0 of 0" without a label, and never 0%.
  * The league baseline and market odds still show independently when
    available.

Screenshots: `m53_limited_example.png` (Venue basis, 4–5 venue matches per
team) and `m53_league_baseline_explanation.png` (one match each, early
season).

## 6. Market-implied probabilities

* **Values:**
  * They reuse the existing consensus and the proportional margin removal, so
    both outcomes sum to 100% (within rounding).
  * They are the same numbers as the expanded "Reference odds and
    market-implied probabilities" table. A test asserts the value appears in
    both places.
* **Fresh / Stale / Unavailable:**
  * The existing badge and the "checked by Diski 9 … / provider update …" line
    stay.
  * Stale adds "Prices may have changed" and the timestamps; the table and
    cards show a `stale` tag.
  * Unavailable shows "Market-implied probabilities unavailable" with the
    reason, or "API-Football does not currently provide bookmaker odds for the
    PSL, so market-implied probabilities are unavailable".
  * A baseline or record is never substituted.
* **Unchanged:**
  * consensus validation
  * bookmaker-group requirements
  * freshness rules
  * Challenge eligibility (`challenge_consensus`; tested: eligible when Fresh,
    not when Stale)

## 7. Why historical counts are not predicted probabilities

**"BTTS in 8 of 10" is a fact about ten past matches.** It does not mean an 80%
chance in the next one:
* the sample is small
* the opponents differ
* in Milestone 5.2 testing, such records barely separated high-scoring from
  low-scoring fixtures within a league
* the league's own rate was a better guide than the team percentages, at every
  sample size

**What to read instead:**
* The **league baseline** is wider historical context.
* The **market-implied probability** is what the betting market currently
  expects.

None of the three is a Diski 9 forecast.
