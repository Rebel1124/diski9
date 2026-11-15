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

Not yet built: Dash UI, Challenge, user accounts.

## Stack

Python 3.12 · uv · httpx · pydantic-settings · SQLite · SQLAlchemy Core · Alembic · pytest · ruff.
Planned: Plotly Dash.

## Setup

```bash
uv sync
uv run pytest
uv run ruff check .
```

### API-Football authentication

The client sends `x-apisports-key` **only if** `DISKI9_API_FOOTBALL_KEY` is set.

* **Claude Code Cloud (`diski9` environment):** the key is injected by the
  environment's network proxy. Leave the variable unset.
* **Local development:** copy `.env.example` to `.env` (git-ignored) and set
  `DISKI9_API_FOOTBALL_KEY`.

The key is never logged, never included in `repr()`, and must never be committed.

### Database and jobs

```bash
uv run diski9 init-db
uv run diski9 sync-reference
uv run diski9 ingest-fixtures --seasons 2023 2024 2025 2026
uv run diski9 collect-odds
uv run diski9 consensus --competition 39
uv run diski9 screener-refresh --days 14
uv run diski9 screener-show --direction btts_yes
```

The database lives at `data/diski9.sqlite` (git-ignored; `DISKI9_DATABASE_URL`
overrides). Bookmaker metadata and venue exceptions are edited in `config/`.

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
  db/                       schema (SQLAlchemy Core), types, engine, migrations helper
  ingestion/                reference data, fixtures/results, classification, quality checks
  odds/                     odds collection (price episodes), consensus, monitoring trial
  screener/                 Form Score, benchmarks, BTTS/OU indicators, ranking, cache
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
