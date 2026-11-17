# Phase 5A — bookmaker odds for all eight leagues

Branch `feature/eight-league-odds` (from `main` at v3.1.0). Odds coverage only:
no Weekly Challenge work, no new markets, competitions or providers, and no
change to Goal Model 1.0, forecast snapshots, the database schema or the odds
methodology.

## 1. Audit of the existing odds architecture

| Area | Finding |
|---|---|
| Supported leagues | Eight domestic leagues in `src/diski9/leagues.py` (table below). UEFA competitions (2, 3) are not supported. |
| What limited odds to EPL + PSL | Only the `odds_enabled` flag per league. It was read in three places: `collect-odds`, `refresh-data --with-odds` and `monitor-odds` (the trial). No query, filter or UI rule was league-specific. The app decides "No odds" vs "—" from whether a league has any stored quotes. |
| Retrieval | `collect_odds` pages through `/odds?league&season` (about 10 fixtures per page). The client paces requests, retries with backoff on rate limits and refuses to go below a 500-request daily reserve. |
| Storage and deduplication | `odds_quotes` stores *price episodes*: an unchanged price extends its row, a changed price ends it and starts a new one, a vanished price is ended. Nothing is overwritten or deleted. Duplicate fixture items across inconsistent pages keep the newest provider snapshot. `odds_fetches` and `odds_fixture_observations` log every collection. |
| Freshness and completeness | `ConsensusRules`, applied at read time:<br>• a quote must be observed by us and provider-updated within 24 h<br>• the bookmaker must be eligible and not an exchange<br>• a bookmaker counts only with a complete outcome set for that market (incomplete markets are also dropped when parsing)<br>• each market is judged independently |
| Consensus | The median price across independent bookmaker groups (affiliated brands count once), rounded to 2 dp. Challenge-eligible means fresh with at least 3 groups. Stale prices are never Challenge-eligible. |
| App integration | `ScreenerData` loads `display_consensus` for every upcoming fixture. The Screener, Match Lab and Edge/EV (`odds/value.py`) read it, so every league is treated identically. |
| Odds trial | A scheduled task runs `monitor-odds` every 3 h from branch `claude/gifted-newton-h6o5hk`, capturing raw EPL + PSL snapshots to `monitoring/odds_trial/`. It shows provider timestamps, quotes and requests, but not per-market coverage. |
| Quota | API-Football Pro allows 7,500 requests a day. One eight-league collection uses **14 requests** (measured below). |

### Rules compared with the Phase 5A requirements

| Requirement | Implementation | Status |
|---|---|---|
| API-Football Pro as primary source | yes | ✔ |
| Median of valid quotes from distinct bookmakers | median over independent bookmaker groups (affiliates count once) | ✔ (slightly stricter) |
| Maximum quote age 24 h | 24 h for our observation **and** the provider update | ✔ (stricter) |
| ≥ 3 independent bookmakers for Challenge eligibility | `min_bookmakers = 3`, fresh only | ✔ |
| Each market assessed independently | yes | ✔ |
| Stale, incomplete or invalid prices never shown as valid | stale prices are labelled stale and never ranked; incomplete or invalid prices are excluded | ✔ |

**One difference to decide on:** the app **displays** a fresh consensus from one
or more bookmaker groups, and the Screener's Edge/EV ranking uses it too. Only
Challenge eligibility requires three.

* In the real data below this makes no difference: every fresh fixture had at
  least 5 groups.
* Smallest safe correction, if you want it: rank Edge/EV only when the
  consensus has at least 3 groups (a one-line filter in `ScreenerData.market_value`).
* Not changed in this phase, pending your decision.

## 2. The eight supported leagues

| League | API-Football ID | Tier | Odds collected (now) | Provider odds coverage, 2026 season |
|---|---:|---:|---|---|
| English Premier League | 39 | 1 | yes (already) | yes |
| English Championship | 40 | 2 | **yes (new)** | yes |
| South African Premiership | 288 | 1 | yes (already) | **no** |
| South African 1st Division | 289 | 2 | **yes (new)** | yes, but no fixtures returned |
| Spanish La Liga | 140 | 1 | **yes (new)** | yes |
| French Ligue 1 | 61 | 1 | **yes (new)** | yes |
| German Bundesliga | 78 | 1 | **yes (new)** | yes |
| Italian Serie A | 135 | 1 | **yes (new)** | yes |

## 3. Changes

* **`leagues.py`:**
  * `odds_enabled=True` set explicitly for all eight leagues; the default stays `False`, so a future league does not collect odds by accident.
  * New `odds_competitions()` helper.
  * New `ODDS_TRIAL_COMPETITIONS = (39, 288)`.
* **Trial unchanged:** `monitor-odds` now defaults to `ODDS_TRIAL_COMPETITIONS` rather than `odds_enabled`, so the approved trial keeps its EPL + PSL scope from any branch. The scheduled task and its branch were not touched.
* **`collect-odds` and `refresh-data --with-odds`:**
  * Both collect all eight leagues.
  * A failure in one league is rolled back and reported without stopping the others.
  * Quota or authentication errors (`FATAL_ERRORS`) stop the remaining leagues, since every later request would fail the same way.
  * `collect-odds` exits non-zero if any league failed.
* **New `odds-coverage` command** (`odds/coverage.py`):
  * Reads the local database only (no API requests).
  * Evaluates each upcoming fixture with the app's own consensus rules.
  * Reports per league:
    * upcoming fixtures, and fixtures with any quotes
    * fresh coverage per market (1X2, BTTS, OU 2.5) and for any market
    * Challenge-eligible coverage (≥ 3 groups)
    * independent bookmaker groups, quote age and provider-update age
    * coverage by time to kickoff
    * exclusion reasons, the last collection, and the provider's coverage flag
  * Prints a table, or JSON with `--json`, and writes the JSON with `--out`.
* **App wording:** the methodology no longer says "Premier League and PSL only". No UI layout, colours or behaviour changed.
* **Not changed:** no migration, no new dependency, and no change to consensus, margin removal, Edge/EV, Goal Model 1.0 or forecast snapshots.

## 4. Coverage report (real API data, 17 Nov 2026 21:12 UTC)

`uv run diski9 collect-odds` used **14 requests** for all eight leagues (2 pages
each for 39, 40, 140, 61, 78 and 135; 1 empty page each for 288 and 289). There were
no errors and no inconsistent pagination. Then `uv run diski9 odds-coverage`,
with fixtures in the next 14 days:

| League | ID | Upcoming | With quotes | Fresh 1X2 | Fresh BTTS | Fresh OU2.5 | Fresh, any market | Challenge-eligible (≥ 3) | Bookmaker groups (min–median–max) | Provider update age |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| Premier League | 39 | 21 | 20 | 20 (95%) | 20 (95%) | 20 (95%) | 20 (95%) | 20 (95%) | 6–9–10 | 17.7 h |
| Championship | 40 | 36 | 12 | 12 (33%) | 12 (33%) | 12 (33%) | 12 (33%) | 12 (33%) | 10–10–10 | 17.3 h |
| PSL | 288 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | — | — |
| PSL 1st Division | 289 | 16 | 0 | 0 | 0 | 0 | 0 | 0 | — | — |
| La Liga | 140 | 20 | 20 | 10 (50%) | 10 (50%) | 10 (50%) | 10 (50%) | 10 (50%) | 10–10–10 | 18.2–19.0 h |
| Ligue 1 | 61 | 18 | 18 | 18 (100%) | 18 (100%) | 18 (100%) | 18 (100%) | 18 (100%) | 5–8–10 | 18.0 h |
| Bundesliga | 78 | 18 | 17 | 9 (50%) | 9 (50%) | 9 (50%) | 9 (50%) | 9 (50%) | 9–10–10 | 18.5–19.0 h |
| Serie A | 135 | 20 | 20 | 20 (100%) | 20 (100%) | 20 (100%) | 20 (100%) | 20 (100%) | 6–9–10 | 18.2 h |
| **All** | | **157** | **107** | | | | **89 (57%)** | **89 (57%)** | | |

**By time to kickoff (fixtures / with quotes / fresh):**

| League | 1–3 days | 3–7 days | 7–14 days |
|---|---|---|---|
| EPL | — | 10 / 10 / 10 | 11 / 10 / 10 |
| Championship | — | 20 / 12 / 12 | 16 / 0 / 0 |
| La Liga | 1 / 1 / 1 | 9 / 9 / 9 | 10 / 10 / 0 |
| Ligue 1 | 1 / 1 / 1 | 8 / 8 / 8 | 9 / 9 / 9 |
| Bundesliga | 1 / 1 / 1 | 8 / 8 / 8 | 9 / 8 / 0 |
| Serie A | — | 10 / 10 / 10 | 10 / 10 / 10 |

How to read it:

* **Odds usually appear about one round ahead.** Fixtures within the next 7 days
  are almost fully covered in every league with provider coverage.
* **The following round is patchy.**
  * The Championship has no quotes yet for its matchday 7–14 days out.
  * La Liga and the Bundesliga list prices for that round, but the provider's
    update timestamp for them is days old (14 Nov and 8 Nov). The 24-hour rule
    therefore correctly excludes them as stale (`stale_provider_update`) instead
    of showing them as valid.
* **Fresh markets are well supplied:** 5–10 independent bookmaker groups, so every
  fresh market also met the 3-bookmaker Challenge minimum.
* **PSL and PSL 1st Division:** none of their upcoming fixtures had odds, in line
  with the PSL's provider flag and with the trial's constant zero PSL fixtures.

## 5. Limitations and observations

* **PSL coverage (provider):**
  * API-Football reports no odds coverage for the 2026 PSL (288).
  * It reports coverage for the PSL 1st Division (289) but returned no fixtures.
  * Both leagues stay visible for statistics with the existing "No odds" state.
  * No workaround (other provider or source) was introduced.
* **Provider update cadence:**
  * The provider's fixture-level `update` timestamp moved once a day in the trial,
    at about 02:00–03:30 UTC.
  * Under the 24-hour rule a slate can go stale shortly before the next daily
    update if that update is late.
  * Collecting after about 04:00 UTC gives the freshest window.
  * The rule was not relaxed.
* **Quota:**
  * 14 requests per eight-league collection. Collecting every 3 hours would be
    about 112 requests a day (1.5% of 7,500), in addition to the trial's 24.
  * Fixture refreshes (`refresh-data`) already covered all eight leagues before
    this phase.
* **Model vs market in the new top flights:**
  * With real odds, Edge/EV rankings in Ligue 1, Serie A, La Liga and the
    Bundesliga are dominated by underdogs against heavy favourites (e.g. PSG v
    Lorient: market 77% home, model 56%).
  * This is the known Goal Model 1.0 limitation already published in the
    methodology (strong favourites estimated too cautiously, especially in La
    Liga and Serie A): with about 10 matches played, strength smoothing pulls
    dominant teams towards the league average.
  * It is a property of the frozen model, not of the odds, and the figures should
    be read with that caveat.
  * Not addressed in this phase: the model is frozen.
* **Consensus odds** remain reference prices, not prices you can bet at.
* **Coverage depends on when you collect:** the report describes the database at
  run time, and its figures change as rounds open and prices age.

## 6. Refreshing and checking eight-league odds

```bash
uv run diski9 refresh-data --with-odds      # fixtures, standings, odds (8 leagues), screener cache
uv run diski9 odds-coverage                 # table: coverage per league and market (no API)
uv run diski9 odds-coverage --json          # full JSON (lead-time buckets, exclusions)
uv run diski9 odds-coverage --competitions 140 61 --horizon-days 7
uv run diski9 collect-odds                  # odds only, all eight leagues (~14 requests)
uv run diski9 collect-odds --competitions 135   # one league
```

Restart `serve` (or wait up to 5 minutes) to see the new prices in the app.
