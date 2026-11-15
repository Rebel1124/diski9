"""Reference data: competitions/seasons, teams/venues, bookmakers, overrides."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, select

from diski9.api_football import ApiFootballClient
from diski9.db.schema import (
    bookmakers,
    competitions,
    neutral_venue_overrides,
    seasons,
    team_seasons,
    teams,
    venues,
)
from diski9.leagues import COMPETITIONS

from .common import Clock, RunStats, ingestion_run, upsert, utcnow

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def store_competition(conn: Connection, item: dict[str, Any], now) -> int:
    lg = item["league"]
    cfg = COMPETITIONS.get(lg["id"])
    upsert(
        conn,
        competitions,
        [
            {
                "id": lg["id"],
                "name": lg["name"],
                "country": item["country"]["name"],
                "type": lg["type"],
                "tier": cfg.tier if cfg else None,
                "parent_competition_id": None,  # set after all competitions exist
                "odds_enabled": bool(cfg and cfg.odds_enabled),
                "updated_at": now,
            }
        ],
        ["id"],
    )
    rows = [
        {
            "competition_id": lg["id"],
            "year": s["year"],
            "start_date": s.get("start"),
            "end_date": s.get("end"),
            "is_current": bool(s.get("current")),
            "coverage_odds": bool((s.get("coverage") or {}).get("odds")),
            "updated_at": now,
        }
        for s in item.get("seasons") or []
    ]
    upsert(conn, seasons, rows, ["competition_id", "year"])
    return len(rows)


def sync_competitions(
    conn: Connection, client: ApiFootballClient, ids: list[int] | None = None, clock: Clock = utcnow
) -> RunStats:
    ids = ids or list(COMPETITIONS)
    with ingestion_run(conn, "sync_competitions", clock) as stats:
        for cid in ids:
            items = client.get("leagues", {"id": cid}).items
            stats.requests += 1
            if not items:
                raise ValueError(f"league {cid} not found")
            stats.updated += store_competition(conn, items[0], clock())
        for cid in ids:
            parent = COMPETITIONS[cid].parent_id if cid in COMPETITIONS else None
            if parent in ids:
                conn.execute(
                    competitions.update()
                    .where(competitions.c.id == cid)
                    .values(parent_competition_id=parent)
                )
    return stats


def ensure_venue(conn: Connection, venue: dict[str, Any] | None, now) -> int | None:
    if not venue or not venue.get("id"):
        return None
    upsert(
        conn,
        venues,
        [
            {
                "id": venue["id"],
                "name": venue.get("name"),
                "city": venue.get("city"),
                "updated_at": now,
            }
        ],
        ["id"],
    )
    return venue["id"]


def ensure_team(conn: Connection, team: dict[str, Any], now) -> None:
    """Create a minimal team row if missing; refresh the name."""
    upsert(conn, teams, [{"id": team["id"], "name": team["name"], "updated_at": now}], ["id"])


def sync_teams(
    conn: Connection,
    client: ApiFootballClient,
    competition_id: int,
    season: int,
    clock: Clock = utcnow,
) -> RunStats:
    with ingestion_run(conn, "sync_teams", clock, competition_id, season) as stats:
        items = client.get("teams", {"league": competition_id, "season": season}).items
        stats.requests += 1
        now = clock()
        for item in items:
            t = item["team"]
            venue_id = ensure_venue(conn, item.get("venue"), now)
            upsert(
                conn,
                teams,
                [
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "code": t.get("code"),
                        "country": t.get("country"),
                        "home_venue_id": venue_id,
                        "updated_at": now,
                    }
                ],
                ["id"],
            )
            upsert(
                conn,
                team_seasons,
                [
                    {
                        "team_id": t["id"],
                        "competition_id": competition_id,
                        "season": season,
                        "registered_venue_id": venue_id,
                        "updated_at": now,
                    }
                ],
                ["team_id", "competition_id", "season"],
            )
            stats.updated += 1
    return stats


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            {k.strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(line for line in fh if not line.lstrip().startswith("#"))
        ]


def _bool(value: str, default: bool) -> bool:
    if value == "":
        return default
    return value.lower() in {"1", "true", "yes", "y"}


def sync_bookmakers(
    conn: Connection,
    client: ApiFootballClient | None,
    config_path: Path | None = None,
    clock: Clock = utcnow,
) -> RunStats:
    """Refresh bookmaker names from the API (if a client is given) and apply
    ``config/bookmakers.csv`` (exchange flag, affiliation group, eligibility)."""
    config_path = config_path or CONFIG_DIR / "bookmakers.csv"
    with ingestion_run(conn, "sync_bookmakers", clock) as stats:
        now = clock()
        if client is not None:
            for b in client.get("odds/bookmakers").items:
                upsert(
                    conn,
                    bookmakers,
                    [{"id": b["id"], "name": b.get("name"), "updated_at": now}],
                    ["id"],
                )
                stats.updated += 1
            stats.requests += 1
        for row in read_csv(config_path):
            bid = int(row["id"])
            existing = conn.execute(select(bookmakers.c.name).where(bookmakers.c.id == bid)).first()
            upsert(
                conn,
                bookmakers,
                [
                    {
                        "id": bid,
                        "name": existing.name
                        if existing and existing.name
                        else (row.get("name") or None),
                        "is_exchange": _bool(row.get("is_exchange", ""), False),
                        "affiliation_group": row.get("affiliation_group") or None,
                        "eligible": _bool(row.get("eligible", ""), True),
                        "notes": row.get("notes") or None,
                        "updated_at": now,
                    }
                ],
                ["id"],
            )
    return stats


def ensure_bookmaker(conn: Connection, bookmaker_id: int, name: str | None, now) -> None:
    """Bookmakers seen in odds but absent from /odds/bookmakers are added as-is."""
    stmt = select(bookmakers.c.id).where(bookmakers.c.id == bookmaker_id)
    if conn.execute(stmt).first() is None:
        conn.execute(bookmakers.insert().values(id=bookmaker_id, name=name, updated_at=now))


def load_neutral_overrides(
    conn: Connection, config_path: Path | None = None, clock: Clock = utcnow
) -> int:
    """Replace ``neutral_venue_overrides`` with ``config/neutral_venue_exceptions.csv``."""
    config_path = config_path or CONFIG_DIR / "neutral_venue_exceptions.csv"
    rows = read_csv(config_path)
    now = clock()
    conn.execute(neutral_venue_overrides.delete())
    for row in rows:
        conn.execute(
            neutral_venue_overrides.insert().values(
                fixture_id=int(row["fixture_id"]),
                classification=row["classification"],
                note=row.get("note") or None,
                updated_at=now,
            )
        )
    return len(rows)
