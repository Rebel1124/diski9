# Diski 9

Football research and virtual prediction platform: a transparent **Statistical
Screener** (1X2 Form Score, BTTS, Over/Under 2.5) and, later, the **Diski 9
Weekly Challenge** (nine picks, three probability-balanced buckets).

Source-of-truth specifications: *DISKI 9 Product Outline (Nov 2026)* and
*Statistical Screener Specification v1.2*.

## Status

**Milestone 1 — project foundation and API-Football verification.** Complete.
See [`docs/milestone1_api_football_verification.md`](docs/milestone1_api_football_verification.md).

No database ingestion, historical backfill, scheduled odds collection, Dash UI or
Challenge logic yet.

## Stack

Python 3.12 · uv · httpx · pydantic-settings · pytest · ruff.
Planned: Plotly Dash, SQLite, SQLAlchemy Core, Alembic.

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
  api_football/
    client.py               HTTP client: envelope, pagination, retries, quota guard
    ratelimit.py            rate-limit header parsing and client-side pacing
    errors.py               exception hierarchy
    markets.py              verified bet-id / outcome mapping, quote extraction
scripts/verify_api_football.py
tests/                      offline tests (httpx.MockTransport) + trimmed real fixtures
docs/                       verification report and summary JSON
```

## Ground rules

* API-Football `/predictions` is blocked in the client and must not be used.
* Historical bookmaker odds are **not** backfilled. Only current/upcoming
  pre-match odds are collected, from the point collection starts.
* Statistical indicators are descriptive, never presented as predictions or edges.
