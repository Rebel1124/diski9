# Diski 9

Football research and virtual prediction platform: a transparent **Statistical
Screener** (1X2 Form Score, BTTS, Over/Under 2.5) and, later, the **Diski 9
Weekly Challenge** (nine picks, three probability-balanced buckets).

Source-of-truth specifications: *DISKI 9 Product Outline (Nov 2026)* and
*Statistical Screener Specification v1.2*.

## Status

* **Milestone 1** — project foundation and API-Football verification:
  [`docs/milestone1_api_football_verification.md`](docs/milestone1_api_football_verification.md)
* **Milestone 2** — SQLite schema (SQLAlchemy Core + Alembic), idempotent historical
  results ingestion, on-demand pre-match odds collection, median consensus odds:
  [`docs/milestone2_report.md`](docs/milestone2_report.md)
* **Milestone 3** — Statistical Screener engine (spec v1.2), approved home grounds,
  screener cache, odds monitoring trial: [`docs/milestone3_report.md`](docs/milestone3_report.md)
* **Milestone 4** — Plotly Dash Statistical Screener, official standings, implied
  probabilities, historical sanity check: [`docs/milestone4_report.md`](docs/milestone4_report.md)
* **Setup fix and Form Score scale (0–5):** [`docs/setup_fix_and_scale_change.md`](docs/setup_fix_and_scale_change.md)
* **Milestone 5** — simplified Screener, new Diski Form Score, current-season goals
  indicators, stale odds display: [`docs/milestone5_report.md`](docs/milestone5_report.md)
* **Milestone 5.1** — UI refinements, market-implied 1X2 summary, Form Score and
  market-implied goals research (offline; scripts in `scripts/research_*.py`, which
  need the dev dependencies numpy and scipy installed by `uv sync`):
  [`docs/milestone5_1_report.md`](docs/milestone5_1_report.md)
* **Milestone 5.2** — statistical model research and validation (offline; no
  production change): [`docs/milestone5_2_product_recommendations.md`](docs/milestone5_2_product_recommendations.md),
  with the [baseline and reproduction guide](docs/milestone5_2_baseline.md) and reports on the
  [Form Score](docs/milestone5_2_form_score_research.md),
  [goal models](docs/milestone5_2_goal_model_research.md) and
  [BTTS / Over-Under](docs/milestone5_2_goals_market_research.md)
* **Milestone 5.3** — Diski Form Score Model D (engine 2.1.0), BTTS / Over-Under shown as
  records, league baseline and market-implied probabilities:
  [`docs/milestone5_3_report.md`](docs/milestone5_3_report.md)
* **Engine 2.4.0** — Match Result Form Score from the last eight current-season matches
  (normalised for shorter windows), current-season league average, display-only venue
  context: [`docs/form_current_season.md`](docs/form_current_season.md)
* **Research: unified goal-distribution model** (estimated goals → 1X2, BTTS,
  Over/Under 2.5; research only, not in the app):
  [`docs/goal_distribution_research.md`](docs/goal_distribution_research.md), with
  [cross-league validation](docs/goal_model_crossleague_validation.md) (La Liga, Ligue 1,
  Bundesliga, Serie A, Champions League, Europa League)

Not yet built: Challenge, user accounts, leaderboards.

## Getting started on a new computer

Requirements: Python 3.12 (uv installs it if needed), [uv](https://docs.astral.sh/uv/),
git, and an API-Football Pro key.

### 1. Install

```bash
git clone https://github.com/Rebel1124/diski9.git
cd diski9
git checkout claude/gifted-newton-h6o5hk
uv sync
```

### 2. Add your API key

```bash
cp .env.example .env
```

Edit `.env` and set `DISKI9_API_FOOTBALL_KEY=<your key>`. The file is
git-ignored; never commit it. (In Claude Code Cloud the key is injected by the
network proxy instead, so leave it unset there.)

### 3. First-time setup (one command)

```bash
uv run diski9 setup --with-odds
```

This applies the migrations, then, in order:

1. competitions and seasons (the foreign-key parents of fixtures), bookmakers
2. teams and venues for every competition-season
3. fixtures and results for **2023–2026** in the EPL, Championship, PSL and
   PSL 1st Division
4. venue classification and a check that every required season loaded
5. official standings, current odds (`--with-odds`)
6. the Screener cache, calculated **only** if step 4 passed

It takes about 30 seconds and roughly 45 API requests. It is safe to re-run:
completed historical seasons are skipped (only the current season is
re-fetched), everything is upserted, and an interrupted setup resumes where it
stopped. `--force` re-fetches every season.

### 4. Launch the Screener

```bash
uv run diski9 serve
```

Open http://127.0.0.1:8050. Options: `--port 8060`, `--tz Europe/London`
(the default display time zone is Africa/Johannesburg).

### 5. Routine refresh (after new matches)

```bash
uv run diski9 refresh-data --with-odds
```

Incremental: current-season fixtures, official standings, current odds and the
Screener cache (about 10 requests). It never repeats the historical backfill,
and it refuses with a clear message if `setup` has not completed. Without
`--with-odds`, consensus odds expire 24 hours after the last odds collection.

Restart `serve` (or wait up to 5 minutes) for the app to show refreshed data.

### Methodology (engine 2.4.0)

All three markets use **current-season league matches only** (never earlier seasons
or other divisions), point in time, with the actual number of matches as the
denominator and Unavailable (never zero) when a team has no matches yet.

* **Diski Form Score (0–5)**, Model D, from each team's last **eight** current-season
  league matches, home or away (fewer early in the season, normalised by N):
  2.5 × points ÷ 3N + 2.5 × (goal difference clipped to ±1.8N, + 1.8N) ÷ 3.6N.
  Fewer than eight matches shows an **Early season** note. Each team is compared with
  one **league Form Score average** (current season; shown once at least 12 teams and
  80% of the season's teams have three or more matches). **Venue context** (last five
  home / away matches vs overall) is display only.
* **BTTS / Over 2.5**: team records (up to ten current-season matches in the
  current competition), a point-in-time **league baseline** (current season only;
  shown from 30 completed league matches), and market-implied probabilities.
* **Reference odds**: Fresh, Stale (last valid consensus, labelled) or
  Unavailable. Stale odds are never eligible for the Challenge.

Full details: [`docs/form_current_season.md`](docs/form_current_season.md),
[`docs/milestone5_3_model_migration.md`](docs/milestone5_3_model_migration.md),
[`docs/milestone5_3_screener_ux.md`](docs/milestone5_3_screener_ux.md),
[`docs/ui_cleanup_and_baseline.md`](docs/ui_cleanup_and_baseline.md),
[`docs/form_benchmark.md`](docs/form_benchmark.md) and
[`docs/screener_methodology.md`](docs/screener_methodology.md) (earlier engines).
Results from older engine versions are never shown; rebuild them locally with
`uv run diski9 screener-refresh` (no API requests).

## Stack

Python 3.12 · uv · httpx · pydantic-settings · SQLite · SQLAlchemy Core · Alembic · Plotly Dash · pytest · ruff.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

### Other commands

```bash
uv run diski9 screener-show --direction btts_yes     # ranked view in the terminal
uv run diski9 consensus --competition 39             # consensus odds
uv run diski9 quality-report                         # data-quality report
uv run diski9 ingest-fixtures --seasons 2026         # low-level: one competition-season job
uv run python scripts/historical_sanity_check.py     # point-in-time integrity check
uv run python scripts/compare_methodologies.py       # old vs new ranking comparison
```

The database lives at `data/diski9.sqlite` (git-ignored; `DISKI9_DATABASE_URL`
overrides). Bookmaker metadata, venue exceptions and approved home grounds are
edited in `config/`.

### Verifying the API

```bash
uv run python scripts/verify_api_football.py --budget 40
```

Writes a sanitised summary (no account details) to
`docs/api_verification_summary.json`. Uses ~22 quota requests.

## Layout

```
src/diski9/
  config.py                 settings from DISKI9_* env vars / .env
  leagues.py                supported competitions and seasons
  cli.py                    `diski9` command (on-demand jobs)
  workflow.py               first-time setup and incremental refresh
  db/                       schema (SQLAlchemy Core), types, engine, migrations helper
  ingestion/                reference data, fixtures/results, classification, quality checks
  odds/                     odds collection (price episodes), consensus, monitoring trial
  screener/                 Form Score, benchmarks, BTTS/OU indicators, ranking, cache, sanity check
  app/                      Dash app: data service (read-only), views, layout/callbacks, assets/style.css
  api_football/
    client.py               HTTP client: envelope, pagination, retries, quota guard
    ratelimit.py            rate-limit header parsing and client-side pacing
    errors.py               exception hierarchy
    markets.py              verified bet-id / outcome mapping, quote extraction
migrations/                 Alembic migrations
config/                     bookmakers.csv, neutral_venue_exceptions.csv, approved_home_grounds.csv
monitoring/odds_trial/      raw odds captures from the monitoring trial
scripts/verify_api_football.py
tests/                      offline tests (httpx.MockTransport) + trimmed real fixtures
docs/                       verification report and summary JSON
```

## Ground rules

* API-Football `/predictions` is blocked in the client and must not be used.
* Historical bookmaker odds are **not** backfilled. Only current/upcoming
  pre-match odds are collected, from the point collection starts.
* Statistical indicators are descriptive, never presented as predictions or edges.
