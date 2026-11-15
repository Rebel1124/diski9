# Milestone 2 — Database Foundation, Historical Results and Current Odds

*Run date: 15 November 2026 (UTC). Machine-readable quality report:
[`milestone2_data_quality.json`](milestone2_data_quality.json).*

## 1. Running the jobs

All jobs run on demand. No recurring schedule is active.

```bash
uv run diski9 init-db                                         # Alembic upgrade head
uv run diski9 sync-reference                                  # competitions, seasons, teams, bookmakers (~21 requests)
uv run diski9 ingest-fixtures --seasons 2023 2024 2025 2026   # backfill (16 requests)
uv run diski9 ingest-fixtures                                 # incremental: current season (4 requests)
uv run diski9 collect-odds                                    # one odds collection (EPL ~3 + PSL 1 requests)
uv run diski9 quality-report --out docs/milestone2_data_quality.json
uv run diski9 consensus --competition 39 --limit 10           # consensus reference odds now
```

The database defaults to `data/diski9.sqlite` (git-ignored). Override it with
`DISKI9_DATABASE_URL`.

## 2. Schema summary

| Table | Purpose / key points |
|---|---|
| `competitions` | API league id (PK), tier, parent competition (lower division → top flight), `odds_enabled` |
| `seasons` | (competition, year). Start/end dates, current flag, the API's odds-coverage flag |
| `venues` | API venue id |
| `teams` | API team id. Registered home ground from `/teams` |
| `team_seasons` | Membership per competition-season, from **regular-season** fixtures only. Registered ground and modal (usual) home ground. Supports promotion and relegation lookups |
| `fixtures` | API fixture id. Competition, season, round name and **round type**, kickoff (UTC), status, teams, venue, **90-minute score** (`score.fulltime`) plus HT/ET/penalties. `is_final`, `stats_exclusion_reason`, `venue_classification` with reason, `content_hash`, `first_seen_at`, `updated_at`, `result_recorded_at` |
| `neutral_venue_overrides` | Explicit exception list, loaded from `config/neutral_venue_exceptions.csv` |
| `bookmakers` | API id, name, `is_exchange`, `affiliation_group`, `eligible`, notes. Configured in `config/bookmakers.csv` |
| `odds_fetches` | One row per collection run: counts, status, warnings |
| `odds_fixture_observations` | One row per fixture per fetch: retrieval time, **provider update time**, bookmakers listed |
| `odds_quotes` | **Price episodes**: fixture, bookmaker, market, outcome, exact decimal odds, `first_seen_at` / `last_seen_at`, first/last provider update, `times_seen`, `ended_at` and `end_reason` (`price_changed`, `disappeared`, `kickoff`). A partial unique index allows only one active episode per fixture/bookmaker/outcome |
| `ingestion_runs` | Job audit log, including failures |

Design notes:
* Timestamps are timezone-aware UTC (ISO text). Odds are stored as exact
  decimals (text), never floats.
* SQLite foreign keys are enforced. The schema is created only via the Alembic
  migration `0001`. Tests verify that the migration matches the SQLAlchemy
  metadata and can be downgraded and upgraded.

## 3. Historical fixtures by league and season

| Competition | Season | Fixtures | Regular | Teams | Final | Stats-eligible | Excluded (reason) |
|---|---|---|---|---|---|---|---|
| EPL (39) | 2023 | 380 | 380 | 20 | 380 | 380 | — |
| | 2024 | 380 | 380 | 20 | 380 | 380 | — |
| | 2025 | 380 | 380 | 20 | 380 | 380 | — |
| | 2026 | 380 | 380 | 20 | 100 | 100 | 280 not started |
| Championship (40) | 2023 | 557 | 552 | 24 | 557 | 552 | 5 promotion play-off |
| | 2024 | 557 | 552 | 24 | 557 | 552 | 5 promotion play-off |
| | 2025 | 558 | 552 | 24 | 557 | 552 | 5 play-off, 1 cancelled |
| | 2026 | 552 | 552 | 24 | 180 | 180 | 372 not started |
| PSL (288) | 2023 | 246 | 240 | 16 | 246 | 240 | 6 play-off |
| | 2024 | 246 | 240 | 16 | 227 | 221 | **19 cancelled**, 6 play-off |
| | 2025 | 246 | 240 | 16 | 246 | 240 | 6 relegation round |
| | 2026 | 240 | 240 | 16 | 73 | 73 | 7 postponed, 160 not started |
| PSL 1st Div (289) | 2023 | 240 | 240 | 16 | 240 | 240 | — |
| | 2024 | 240 | 240 | 16 | 240 | 240 | — |
| | 2025 | 240 | 240 | 16 | 239 | 239 | 1 awarded |
| | 2026 | 240 | 240 | 16 | 80 | 80 | 160 not started |

**Total: 5,682 fixtures.** Every competition-season matches its expected
regular-season count (teams × (teams − 1)). There are no duplicate pairings, no
past fixtures still marked as not started, no final results with a missing
90-minute score, and no half-time scores above full-time scores.

## 4. Data quality and exclusions

**Exclusion rules** (`stats_exclusion_reason`; NULL means eligible):
* Status: `postponed`, `cancelled`, `abandoned`, `awarded`, `walkover`,
  `suspended`, `interrupted`, `not_started`, `in_progress`, `unknown_status`.
* `missing_score`: a finished match with no 90-minute score.
* Round type: `playoff_round`, `relegation_round`, `promotion_round` and
  `non_regular_round`. These fixtures are **retained** with their round name.
  Observed labels: `Playoffs - 1`, `Finals - n`, `Relegation Round`,
  `Promotion Play-offs - Semi-finals/Final`, `Semi-finals`, `Final`.

**Results** come from `score.fulltime` only. The three Championship play-off
finals that went to extra time keep separate `et_*` and `pen_*` columns.

**Idempotency, verified live.** A second full backfill (16 requests) reported
all 5,682 rows unchanged and made no writes. A second odds collection updated
975 existing quotes and inserted no rows.

**Live finding:** the provider sometimes sends `venue.id = 0` for an unknown
venue. This broke a foreign key on the first run and is now treated as
missing. Because each season runs in its own transaction, the failed season
rolled back cleanly and the rerun completed.

**Venue classification** (2023–2025, completed seasons):

| Competition | Home ground | Potential neutral | Unknown |
|---|---|---|---|
| EPL | 1,140 | 0 | 0 |
| Championship | 1,401 | 16 | 255 (2025 venue ids missing) |
| PSL | 442 | 89 | 207 |
| PSL 1st Div | 567 | 51 | 102 |

* A venue counts as the home ground if it is the team's registered ground
  (`/teams`) or its usual ground (the most frequent home venue that season:
  at least 3 matches and at least 50% of home matches).
* "Unknown" is never guessed. It means the venue id is missing, or the home
  team's ground cannot be determined.
* Most PSL "potential neutral" fixtures are clubs using **secondary home
  grounds**. Examples: SuperSport United at Lucas Moripe and Peter Mokaba;
  Kaizer Chiefs at Moses Mabhida. These are not true neutral venues (see
  decision 1).

**Promotion and relegation** are detected from `team_seasons`. Examples:
* EPL 2026 promoted ids 57, 64, 1346; relegated 39, 44, 48.
* PSL 2026 promoted Milford FC and Kruger United; relegated Orbit College and
  Magesi.

**Siwelele (PSL 2025) has no history under its team id.** Its first stored
season is 2025, with no earlier PSL or 1st Division record. This is
consistent with a PSL status purchase (see decision 2).

## 5. Current odds coverage (collected 15 Nov 2026, about 11:05 UTC)

| League | Fixtures in response | Upcoming collected | Quotes | Challenge-eligible: 1X2 / BTTS / OU2.5 | Independent sources (min–max) 1X2 / BTTS / OU2.5 |
|---|---|---|---|---|---|
| EPL | 25 (5 already played, skipped) | 20 | 975 | 20 / 20 / 20 | 6–10 / 4–7 / 5–8 |
| PSL | 0 | 0 | 0 | — (Screener-only) | — |

* The provider `update` value was `2026-11-15T03:24:17/18Z` for all 20
  fixtures, in both collections about 20 minutes apart.
* No affiliated duplicates are currently present. The configured groups have
  only one active brand each among today's bookmakers.
* None of the current bookmaker ids is an identifiable exchange. Betfair's 1X2
  overround averages about 6.1%, a sportsbook level, so it is kept and flagged
  for re-verification.

## 6. Example consensus reference odds (as of 15 Nov 2026, 11:07 UTC)

| Fixture | 1X2 Home / Draw / Away (sources) | BTTS Yes / No (sources) | O/U 2.5 Over / Under (sources) |
|---|---|---|---|
| 1557474 (21 Nov 12:30) | 1.40 / 5.00 / 7.04 (10) | 1.66 / 2.10 (7) | 1.49 / 2.60 (7) |
| 1557467 (21 Nov 15:00) | 1.75 / 3.75 / 4.50 (10) | 1.70 / 2.05 (7) | 1.80 / 2.06 (8) |
| 1557468 (21 Nov 15:00) | 2.02 / 3.60 / 3.59 (10) | 1.67 / 2.10 (7) | 1.82 / 2.01 (8) |
| 1557471 (21 Nov 15:00) | 2.38 / 3.58 / 2.85 (10) | 1.55 / 2.30 (7) | 1.69 / 2.20 (8) |

These are consensus reference odds, not an offer from any bookmaker. No
probabilities, expected values or edges are calculated.

## 7. Freshness and eligibility rules (as implemented)

At a reference time `as_of`, a quote counts only if **all** of these hold:

1. The price episode is in effect at `as_of`, and was first observed at or
   before `as_of`. This prevents look-ahead, so a past snapshot can be
   reproduced exactly.
2. The fixture has not kicked off.
3. **Our observation** of that price is at most **24 h** old. This is the
   latest retrieval at or before `as_of` that saw it.
4. **The provider's update timestamp** known at `as_of` is at most **24 h**
   old. A missing timestamp makes the quote ineligible.
5. The bookmaker is eligible and is not an exchange.
6. The bookmaker has valid prices for **every** outcome of the market;
   otherwise its whole market is dropped.
7. Each affiliation group contributes **one** bookmaker per market: the most
   recently observed one (ties go to the lowest id).

The consensus is the median of the remaining prices, rounded half-up to 2 dp.
The exact median is retained. A market is **displayable** with at least 1
source and **Challenge-eligible** with at least 3 independent sources. The
threshold can be overridden per competition.

**Limitations:**
* The provider timestamp is fixture-level, and in practice league-level. Rule 4
  is therefore a coarse feed-health check, not a per-bookmaker price time.
  Price changes are detected only by our own observations, at the resolution of
  our collection interval.
* A disappearance is recorded at the first retrieval that no longer shows the
  quote, so the true removal time lies between `last_seen_at` and `ended_at`.
* Rule 3 depends on regular collection. Without a schedule, quotes become stale
  24 h after the last manual run, which is intended.
* "Distinct bookmaker id" does not prove independence. Affiliation groups are
  maintained manually in `config/bookmakers.csv` and need periodic review.

## 8. API quota

**59 requests** for Milestone 2. The provider's `/status` counter went from 37
to 96, matching the run logs exactly:

| Job | Requests |
|---|---|
| Reference sync (4 leagues, bookmakers, 16 team-seasons) | 21 |
| Fixture backfill: first attempt (15, one season failed on `venue.id = 0`) and full idempotent rerun (16) | 31 |
| Odds: two EPL collections (3 + 3) and one PSL (1) | 7 |

Steady-state estimate: an odds collection every 3 h (32/day) plus fixture
updates (4–8/day) is under 1% of the 7,500 daily allowance.
