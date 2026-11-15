# Milestone 1 — API-Football Verification Report

*Run date: 15 November 2026 (UTC). Plan: API-Football **Pro** (7,500 requests/day, 300/minute).*
*Raw machine-readable results: [`api_verification_summary.json`](api_verification_summary.json).*

## 1. Authentication

* Requests go to `https://v3.football.api-sports.io/`. In Claude Code Cloud the
  `x-apisports-key` header is **injected by the environment's network proxy**.
  This works for Python (`httpx`) as well as curl. The key is never visible to
  application code and is not stored in the repository.
* The client adds the header itself only when `DISKI9_API_FOOTBALL_KEY` is set,
  for local development.

## 2. Endpoints tested

| Endpoint | Parameters | Result |
|---|---|---|
| `/status` | none | 200. Plan Pro, active, `limit_day` 7500. Does **not** count towards quota. `requests.current` lags by a few minutes. |
| `/leagues` | `id=39`, `id=40`, `id=288`, `id=289`, `country=South-Africa` | 200. Per-season `coverage` flags returned (see §4). |
| `/fixtures` | `league` + `season` (2023–2026) | 200. Whole season in one response (`paging.total = 1`). |
| `/odds` | `league=39&season=2026` | 200. **Paginated**: 10 fixtures per page, 3 pages, 25 fixtures. |
| `/odds` | `league=288&season=2026` | 200, `results: 0`. |
| `/odds` | `fixture=<id>` | 200. 1 item for EPL, 0 for PSL. |
| `/odds/bookmakers` | none | 200. 33 bookmakers (one has `name: null`, id 37). |
| `/odds/bets` | none | 200. 338 bet types (one has `name: null`). |
| `/predictions` | — | **Not called.** Blocked in the client (`ForbiddenEndpointError`). |

## 3. Response envelope and conventions

```json
{"get": "fixtures", "parameters": {...}, "errors": [] | {...},
 "results": 380, "paging": {"current": 1, "total": 1}, "response": [...]}
```

* **Errors:** `errors` is `[]` when there are none and an **object** otherwise,
  e.g. `{"token": ...}`, `{"requests": ...}`, `{"rateLimit": ...}`. They arrive
  with HTTP **200**. The client normalises them to a dict and raises typed
  exceptions: auth, daily quota, rate limit (retried), and generic.
* **Empty results** are `response: []`, `results: 0`, with no error. These are
  treated as valid empty data.
* **Pagination:** only some endpoints use it (`/odds` here). Sending `page` to a
  non-paginated endpoint is an error, so the client never sends `page=1`.
* **Rate-limit headers:** `x-ratelimit-requests-limit` and
  `x-ratelimit-requests-remaining` give the daily figures;
  `X-RateLimit-Limit` and `X-RateLimit-Remaining` give the per-minute figures.
  The daily-remaining header is **approximate and lags** like `/status`. It is
  used as a safety guard, not as an exact meter. The client keeps its own
  request log.
* **Timestamps:** ISO-8601 with an offset (`2026-11-21T12:30:00+00:00`) plus a
  Unix `timestamp` on fixtures.

## 4. League coverage

| | EPL (`league=39`) | SA Premiership (`league=288`, “Premier Soccer League”) |
|---|---|---|
| Season ids | Calendar start year (2026 = 2026/27) | Same (2026 = 2026-08-01 → 2027-05-22) |
| Lower division | Championship `40` | 1st Division `289` |
| Historical results 2023, 2024, 2025 | ✅ 380 FT each | ✅ 246 fixtures each (240 regular + 6 play-off/relegation) |
| Current season 2026 | 380 fixtures: 100 FT, 280 NS | 240 fixtures: 73 FT, 7 PST, 160 NS |
| `coverage.odds` flag | 2026 **true**; 2023–2025 false | **false for every season**, including 2026 |
| Live `/odds` result | ✅ 25 fixtures | ❌ 0 fixtures (league and fixture queries) |

### Historical result fields (verified)

* `fixture.id`, `fixture.date`, `fixture.timestamp`, `fixture.status.short`,
  `fixture.venue.{id,name,city}`
* `league.{id,season,round}`, `teams.{home,away}.{id,name}`
* `score.halftime`, **`score.fulltime`**, `score.extratime`, `score.penalty`, `goals`

**`score.fulltime` is the 90-minute score (stoppage time included).** In a
Championship 2025 play-off final that finished `AET`, `goals` included extra
time but `score.fulltime` did not. Diski 9 must therefore use `score.fulltime`,
**not `goals`**.

### Fixture statuses observed

`FT`, `NS`, `PST`, `CANC` (19 in PSL 2024), `AET` (Championship play-off), and
`AWD` (PSL 1st Division 2025). Awarded and walkover results (`AWD`, `WO`) and
cancelled matches (`CANC`) must be excluded from statistics.

## 5. Odds — market mapping (verified)

| Diski 9 market | API bet id | API name | API `value` strings → outcome |
|---|---|---|---|
| Match Result | **1** | Match Winner | `Home` → HOME, `Draw` → DRAW, `Away` → AWAY |
| BTTS | **8** | Both Teams Score | `Yes` → BTTS_YES, `No` → BTTS_NO |
| Over/Under 2.5 | **5** | Goals Over/Under | `Over 2.5` → OVER_2_5, `Under 2.5` → UNDER_2_5 |

* The ids are the same across every bookmaker, and no bookmaker has duplicate
  market blocks or duplicate values.
* Bet 5 includes many lines (0.5–6.5 and Asian quarter lines such as `2.75`).
  Only `2.5` is used.
* Odds are **decimal strings** (`"1.85"`). All values seen parse as numbers.
* `markets.extract_quotes()` emits a bookmaker's market only when **all** of its
  outcomes are present and valid.

### Structure

```
response[] → {league{id,season}, fixture{id,date,timestamp}, update,
              bookmakers[] → {id, name, bets[] → {id, name, values[] → {value, odd}}}}
```

### EPL coverage (20 upcoming fixtures, 21–29 Nov)

Distinct bookmakers with a complete market, per fixture:

| Market | Min | Max | Fixtures with ≥ 3 bookmakers |
|---|---|---|---|
| 1X2 | 6 | 10 | 20 / 20 |
| BTTS | 4 | 7 | 20 / 20 |
| O/U 2.5 | 5 | 8 | 20 / 20 |

* Bookmakers: William Hill, Bet365, Marathonbet, Betfair, BetVictor, Pinnacle,
  SBO, 1xBet, Betano, Dafabet.
* Pinnacle and SBO offered no BTTS. William Hill and Dafabet were missing O/U on
  some fixtures.
* Coverage falls with lead time: fixtures about 6 days out had 10 bookmakers;
  fixtures about 14 days out had 6.
* Odds appear about **14 days** before kickoff.

### Odds for already-played fixtures

The league query also returned 5 fixtures that had **already been played**
(8 November), with their last pre-kickoff prices. Odds therefore stay available
for some days after kickoff. Collection must filter on kickoff time.

## 6. Differences from the original architecture assumptions

1. **The provider update timestamp is per fixture, not per bookmaker or quote.**
   `update` is a single value per fixture. Every bookmaker and market shares it,
   and in practice the whole league shares it (all upcoming EPL fixtures showed
   `2026-11-15T03:24:17/18Z`). Quote-level freshness therefore cannot come from
   the provider. It must come from the fixture-level `update` together with our
   own retrieval and last-seen timestamps.
2. **There are no South African Premiership odds.** The league's coverage flag
   is false for every season, and live queries return nothing. The next PSL
   fixture (27 Nov) had no odds 12 days out, while EPL fixtures had odds 14 days
   out.
3. **There is no neutral-venue flag** in `/fixtures`. `venue.id` is often null
   (PSL 2025: 162/246; current-season fixtures that have not been played yet are
   frequently null). Neutral venues have to be inferred or curated.
4. **League seasons include non-regular rounds.** PSL seasons contain
   `Playoffs`, `Finals` or `Relegation Round` matches (promotion/relegation
   play-offs that involve 1st Division clubs). As a result the 2023 PSL data has
   18 distinct teams. The Championship has play-off `Semi-finals` and `Final`.
5. **Usage counters lag.** `/status` and the daily-remaining header trail actual
   usage by minutes. A local request count is needed for budgeting.
6. **`/odds` is paginated at 10 fixtures per page.** A full EPL refresh costs
   about 3 requests. `/fixtures` per league-season costs 1 request.

## 7. Quota consumption

* **37 quota-counted requests** in total for Milestone 1. That covers all
  exploration plus one full verification-script run (22 requests). `/status`
  confirmed `requests.current = 37`, matching the client's own count exactly.
* 4 extra `/status` calls, which do not count towards quota.
* That is 0.5% of the daily allowance. No retries or rate-limit events occurred.

**Projected steady-state cost** (indicative, both leagues):

| Job | Requests |
|---|---|
| Odds refresh every 3 h, EPL (3 pages) | 8 × 3 = 24/day |
| Fixture/status updates | about 10/day |
| One-off 3-season backfill, 2 leagues + lower divisions | about 20 |

Steady state is comfortably under 1% of the daily quota.

## 8. Implications for later milestones

* Store `provider_update` (fixture-level) and `retrieved_at` separately for
  every quote.
* De-duplicate on (fixture, bookmaker, market, outcome, odds). Insert a new row
  only when the price changes, and keep `last_seen_at` updated on unchanged
  rows. This preserves genuine price changes even when `update` is unchanged.
* Freshness check: `now − max(provider_update, …)` ≤ 24 h. Treat quotes that
  disappear from a later response as stale.
