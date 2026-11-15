# Milestone 4 — Plotly Dash Statistical Screener

> **Note (15 Nov 2026):** Form Scores and league benchmarks in this report use the original −1 to 4 scale. The Screener now uses 0 to 5 (each value + 1); differences and rankings are unchanged. See [setup_fix_and_scale_change.md](setup_fix_and_scale_change.md).

*15 November 2026. Source of truth: Statistical Screener Specification v1.2.*

## 1. Running the app

```bash
uv sync
uv run diski9 init-db                 # applies migrations up to 0003 (standings snapshots)
uv run diski9 refresh-data            # fixtures -> official standings -> screener cache (~6 requests)
uv run diski9 serve                   # http://127.0.0.1:8050
```

Options:
* `serve --port 8060 --tz Europe/London` sets the port and display time zone.
  The default time zone is Africa/Johannesburg (SAST).
* `serve --ttl 300` sets how long data stays in memory before it is re-read
  from the database.
* `refresh-data --with-odds` also runs one on-demand odds collection (about 4
  requests). Without it, consensus odds use the latest `collect-odds` run and
  stop showing 24 h later, under the provisional freshness rule.

**Refreshing after new results.** `diski9 refresh-data` re-ingests the
current season (an idempotent upsert), reloads venue overrides and approved
grounds, re-classifies venues, takes an official standings snapshot, and
refreshes the Screener cache for the next 21 days. Cached rows whose inputs
changed are superseded, and unchanged rows are only re-verified. The app
shows a banner whenever fixtures were ingested after the cache was last
refreshed.

**Page interactions make no API-Football requests.** The app reads only the
local database; a test enforces this.

## 2. Interface

| Area | What it does |
|---|---|
| Market tabs | Match result · Both teams to score · Over/Under 2.5. Switching is instant and keeps the filters |
| Leagues | EPL and PSL chips (the leagues present in the cache). The PSL stays available without odds |
| Dates | Date range, defaulting to today + 14 days (display time zone) |
| Form basis | Venue-specific (default: home team at home vs away team away) or Overall |
| Rank by | 1X2: strongest home-team advantage, strongest away-team advantage, most evenly matched. BTTS: Yes (highest first) or No (lowest first). O/U: Over (highest first) or Under (lowest first) |
| Threshold | Market-specific: minimum difference, maximum difference (evenly matched), or minimum indicator for the selected outcome (0–100%) |
| Table | Kickoff, league, teams, team metrics, ranked indicator, the complementary outcome (goals markets), sample sizes ("5 / 5"), consensus odds, Limited-data flag. Every column header is also sortable |
| Phones (≤ 720 px) | Filters stack, and the table is replaced by tappable fixture cards (same ranking and flags). Tapping scrolls to the analysis. No horizontal page scrolling, verified with Playwright at iPhone 13 size |
| Match analysis | Opens on selection; the current market comes first: |
|  | · 1X2: both Form Scores with W/D/L sequence and full breakdown (W/D/L, points, PPG, GF/GA, GD/G, capped, ×0.5), raw and venue-adjusted difference, league benchmarks with season, source and sample size, and draw rate as context only |
|  | · BTTS / O2.5: team k/n rates, combined indicator and complement, plus averages, clean sheets and failed-to-score |
|  | · The matches used, with competition and provenance badges (This season / Earlier season / Other division / unverified venue) |
|  | · Reference odds for all 7 outcomes, with raw and market-implied probabilities |
|  | · League positions (official preferred) |
|  | · Last 5 head-to-head meetings regardless of age, with "older" flags |
|  | · The other markets in collapsible sections |

Every indicator has a short plain-language explanation. Each analysis shows
"Historical indicators, not predicted probabilities." A near-zero difference
is explicitly *not* a draw prediction. Nothing anywhere computes or shows
expected value, edges or staking advice.

Screenshots are in `docs/screenshots/`:
* `desktop_1x2_table.png`
* `desktop_1x2_detail.png` (Man City v Fulham)
* `desktop_btts_table.png`
* `desktop_ou25_psl_detail.png` (Orlando Pirates v Golden Arrows, no odds)
* `mobile_table.png`, `mobile_table_rows.png`, `mobile_detail.png`

## 3. Odds and implied probabilities

* **Consensus reference odds** for all seven outcomes come from the existing
  consensus engine. Each market shows its number of independent bookmakers
  and whether that meets the Challenge minimum of 3.
* **Raw implied probability** is 1 / odds. **Market-implied probability** is
  each reciprocal divided by their total, shown only when every outcome of the
  market has a consensus price. It is calculated from the displayed 2 dp odds,
  so users can verify it. The removed margin is shown as well.
* **Two timestamps are kept apart.** "Prices last verified by Diski 9" is our
  latest retrieval that saw the price. "Provider feed update" is
  API-Football's feed-level timestamp, labelled as not a bookmaker
  price-change time.
* **When odds are missing, the app says why.** For example, "API-Football
  currently provides no bookmaker odds for the PSL", or that prices are older
  than 24 h, the market is incomplete, or the match has started. It never
  invents values. The freshness rules are labelled provisional.

Example, Man City v Fulham, 21 Nov (as of 15 Nov):

| Market | Outcome | Consensus | Raw implied | Market-implied | Sources |
|---|---|---|---|---|---|
| 1X2 | Home / Draw / Away | 1.40 / 5.00 / 7.04 | 71.4% / 20.0% / 14.2% | 67.6% / 18.9% / 13.4% (margin 5.6%) | 10 |
| BTTS | Yes / No | 1.66 / 2.10 | 60.2% / 47.6% | 55.9% / 44.1% (margin 7.9%) | 7 |
| O/U 2.5 | Over / Under | 1.49 / 2.60 | 67.1% / 38.5% | 63.6% / 36.4% (margin 5.6%) | 7 |

The historical BTTS indicator for the same fixture is 45%, shown in its own
section. The app never subtracts one figure from the other.

## 4. Real fixtures (venue basis)

* **Match result, strongest home advantage:**
  * PSL Sekhukhune v Siwelele: +2.76.
  * PSL Orlando Pirates v Golden Arrows: +2.06 (no odds).
  * EPL Brighton v Newcastle: +1.72.
  * EPL Leeds v Coventry: +1.62.
  * EPL Man City v Fulham: +1.22.
* **Most evenly matched:**
  * EPL Liverpool v Man Utd: −0.08. Liverpool's raw form is higher (+0.60),
    but relative to league norms the teams are close. The app says this is
    not a draw prediction.
* **BTTS Yes, highest:** Aston Villa v Sunderland 80% (8/10 and 8/10);
  Ipswich v Aston Villa 70%; Man Utd v Brentford 70%. The PSL's highest is
  Kruger United v Sundowns at 60%, with "No odds".
* **League positions:** official snapshots were stored for the EPL (updated
  11 Nov) and the PSL (updated 6 Nov). The PSL official table shows Pirates
  2nd with P9, while the calculated table differs because of postponements.
  The official table is preferred and labelled.

## 5. Historical sanity check (calculation integrity, not a backtest)

`uv run python scripts/historical_sanity_check.py` produces
`docs/historical_sanity_check.json`. It covers every completed regular-season
EPL and PSL fixture in 2024/25, 2025/26 and 2026/27 to date: **1,394
fixtures**, each computed as at its own kickoff.

| Check | What it proves | Failures |
|---|---|---|
| No future matches | Every match used (windows, benchmark, head-to-head) kicked off before the fixture, and the fixture itself is never used | 0 |
| Independent reconstruction | Recomputing from a store that physically holds only pre-kickoff matches gives an identical result hash | 0 |
| Independent Form check | The home venue Form Score re-derived with separate SQL and arithmetic matches | 0 |
| Bounds | Form within [−1, 4]; all rates and indicators within [0, 1] | 0 |
| Deterministic | Computing twice gives the same hash | 0 |
| Benchmark count | The benchmark sample equals the SQL count of eligible pre-kickoff league matches | 0 |

A test deliberately introduces a leak (windows that look 60 days ahead) and
confirms the check catches it. Observations:
* Limited data flags concentrate in early-season fixtures involving promoted
  clubs: 17 fixtures per EPL season, 11 to 22 per PSL season.
* The benchmark switches from the previous season to the current one after
  120 matches, as configured.
* Only 2 fixtures had no form difference: Siwelele's first PSL matches,
  correctly, since there was no history.

No bookmaker odds were used.

## 6. Odds monitoring trial

**Interim findings** (the trial is still running and was not changed):
* 2 captures so far (11:13 and 11:21 UTC, 15 Nov). The first scheduled run is
  at 12:14 UTC, and runs continue every 3 h until 21 Nov 15:00 UTC. PSL
  checks follow on 25 and 27 Nov.
* The provider `update` value was about 7.9 h old and identical for all
  fixtures and bookmakers.
* No price changes between the captures.
* 10 bookmakers per fixture at 3–7 days out, a median of 6 at 7–14 days.
* No PSL odds.

**Completed findings:** none yet. Interim results are in
`docs/odds_trial_interim.json`.

## 7. API quota (Milestone 4)

10 requests: 2 standings checks during development, then `refresh-data`
(4 fixture seasons and 2 standings). The trial's scheduled captures are
counted separately.
