"""Idempotent historical and incremental fixture/result ingestion.

* ``/fixtures?league&season`` returns a full season in one request, so a season
  is always re-read whole and upserted. Re-running is safe: rows whose provider
  content is unchanged are left untouched (``content_hash``).
* The 90-minute result comes from ``score.fulltime`` (never ``goals``, which
  includes extra time).
* Statistical eligibility, round type and venue classification are derived
  here and stored with the row so later calculations can filter cheaply.
* Point-in-time safety: statistics must only use fixtures with
  ``is_final = 1 AND kickoff_utc < reference_time``; ``result_recorded_at``
  additionally records when we first observed each result.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import Connection, and_, func, or_, select, update

from diski9.api_football import ApiFootballClient
from diski9.db.schema import (
    approved_home_grounds,
    fixtures,
    neutral_venue_overrides,
    seasons,
    team_seasons,
    teams,
)

from .classify import (
    TeamGround,
    classify_round,
    classify_venue,
    is_final,
    modal_home_venue,
    stats_exclusion_reason,
)
from .common import (
    Clock,
    MissingReferenceData,
    RunStats,
    content_hash,
    ingestion_run,
    parse_api_datetime,
    upsert,
    utcnow,
)
from .reference import ensure_team, ensure_venue

# Columns derived purely from the provider payload (hashed for change detection).
PROVIDER_FIELDS = (
    "competition_id",
    "season",
    "round_name",
    "kickoff_utc",
    "status_short",
    "status_long",
    "home_team_id",
    "away_team_id",
    "venue_id",
    "venue_name",
    "venue_city",
    "ft_home",
    "ft_away",
    "ht_home",
    "ht_away",
    "et_home",
    "et_away",
    "pen_home",
    "pen_away",
)


def normalise_fixture(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten one ``/fixtures`` item into provider columns plus derived fields."""
    fx, lg, tm, sc = item["fixture"], item["league"], item["teams"], item["score"]
    venue = fx.get("venue") or {}
    status = fx.get("status") or {}
    row = {
        "id": int(fx["id"]),
        "competition_id": int(lg["id"]),
        "season": int(lg["season"]),
        "round_name": lg.get("round"),
        "kickoff_utc": parse_api_datetime(fx["date"]),
        "status_short": status.get("short") or "TBD",
        "status_long": status.get("long"),
        "home_team_id": int(tm["home"]["id"]),
        "away_team_id": int(tm["away"]["id"]),
        # The provider sometimes sends venue.id = 0 for "unknown"; treat as missing.
        "venue_id": venue.get("id") or None,
        "venue_name": venue.get("name"),
        "venue_city": venue.get("city"),
        "ft_home": (sc.get("fulltime") or {}).get("home"),
        "ft_away": (sc.get("fulltime") or {}).get("away"),
        "ht_home": (sc.get("halftime") or {}).get("home"),
        "ht_away": (sc.get("halftime") or {}).get("away"),
        "et_home": (sc.get("extratime") or {}).get("home"),
        "et_away": (sc.get("extratime") or {}).get("away"),
        "pen_home": (sc.get("penalty") or {}).get("home"),
        "pen_away": (sc.get("penalty") or {}).get("away"),
    }
    row["round_type"] = classify_round(row["round_name"])
    row["is_final"] = is_final(row["status_short"], row["ft_home"], row["ft_away"])
    row["stats_exclusion_reason"] = stats_exclusion_reason(
        row["status_short"], row["round_type"], row["ft_home"], row["ft_away"]
    )
    row["content_hash"] = content_hash({k: row[k] for k in PROVIDER_FIELDS})
    return row


def store_fixtures(
    conn: Connection, items: list[dict[str, Any]], clock: Clock = utcnow
) -> RunStats:
    """Upsert fixtures; returns inserted/updated/unchanged counts."""
    stats = RunStats()
    now = clock()
    rows = [normalise_fixture(i) for i in items]
    ids = [r["id"] for r in rows]
    existing = {
        r.id: r
        for r in conn.execute(
            select(fixtures.c.id, fixtures.c.content_hash, fixtures.c.result_recorded_at).where(
                fixtures.c.id.in_(ids)
            )
        )
    }
    for item, row in zip(items, rows, strict=True):
        prev = existing.get(row["id"])
        if prev is not None and prev.content_hash == row["content_hash"]:
            stats.unchanged += 1
            continue
        ensure_team(conn, item["teams"]["home"], now)
        ensure_team(conn, item["teams"]["away"], now)
        ensure_venue(conn, (item["fixture"].get("venue") or {}), now)
        row = {**row, "updated_at": now}
        if prev is None:
            row["first_seen_at"] = now
            row["result_recorded_at"] = now if row["is_final"] else None
            conn.execute(fixtures.insert().values(**row))
            stats.inserted += 1
        else:
            if prev.result_recorded_at is None and row["is_final"]:
                row["result_recorded_at"] = now
            conn.execute(update(fixtures).where(fixtures.c.id == row["id"]).values(**row))
            stats.updated += 1
    return stats


def refresh_team_seasons(
    conn: Connection, competition_id: int, season: int, clock: Clock = utcnow
) -> None:
    """Derive season membership (regular-season fixtures only) and modal home venues.

    Teams appearing only in play-off/relegation rounds (e.g. lower-division clubs
    in PSL play-offs) are *not* recorded as members of the competition.
    """
    now = clock()
    q = select(fixtures.c.home_team_id, fixtures.c.away_team_id, fixtures.c.venue_id).where(
        fixtures.c.competition_id == competition_id,
        fixtures.c.season == season,
        fixtures.c.round_type == "regular",
    )
    home_venues: dict[int, list[int | None]] = defaultdict(list)
    counts: dict[int, int] = defaultdict(int)
    for r in conn.execute(q):
        home_venues[r.home_team_id].append(r.venue_id)
        counts[r.home_team_id] += 1
        counts[r.away_team_id] += 1
    for team_id, n in counts.items():
        upsert(
            conn,
            team_seasons,
            [
                {
                    "team_id": team_id,
                    "competition_id": competition_id,
                    "season": season,
                    "modal_home_venue_id": modal_home_venue(home_venues.get(team_id, [])),
                    "regular_season_fixtures": n,
                    "updated_at": now,
                }
            ],
            ["team_id", "competition_id", "season"],
        )


def _team_grounds(conn: Connection, season: int) -> dict[int, TeamGround]:
    """Known grounds per team for a season, across all stored competitions."""
    q = (
        select(
            team_seasons.c.team_id,
            team_seasons.c.registered_venue_id,
            team_seasons.c.modal_home_venue_id,
            teams.c.home_venue_id,
            team_seasons.c.regular_season_fixtures,
        )
        .join(teams, teams.c.id == team_seasons.c.team_id)
        .where(team_seasons.c.season == season)
        .order_by(team_seasons.c.regular_season_fixtures)  # main competition wins (last)
    )
    out: dict[int, TeamGround] = {}
    for r in conn.execute(q):
        registered = r.registered_venue_id or r.home_venue_id
        prev = out.get(r.team_id)
        out[r.team_id] = TeamGround(
            registered_venue_id=registered or (prev.registered_venue_id if prev else None),
            modal_venue_id=r.modal_home_venue_id or (prev.modal_venue_id if prev else None),
        )
    return out


def _approved_lookup(conn: Connection):
    """Return f(team_id, kickoff) -> venue ids approved for that team on that date."""
    by_team: dict[int, list[tuple[str, str | None, int]]] = defaultdict(list)
    for r in conn.execute(select(approved_home_grounds)):
        by_team[r.team_id].append((r.valid_from, r.valid_to, r.venue_id))

    def lookup(team_id: int, kickoff) -> frozenset[int]:
        day = kickoff.date().isoformat()
        return frozenset(
            v
            for start, end, v in by_team.get(team_id, ())
            if start <= day and (end is None or day <= end)
        )

    return lookup


def refresh_venue_classification(
    conn: Connection, competition_id: int, season: int
) -> dict[str, int]:
    grounds = _team_grounds(conn, season)
    approved = _approved_lookup(conn)
    overrides = {
        r.fixture_id: r.classification
        for r in conn.execute(
            select(neutral_venue_overrides.c.fixture_id, neutral_venue_overrides.c.classification)
        )
    }
    summary: dict[str, int] = defaultdict(int)
    rows = conn.execute(
        select(
            fixtures.c.id,
            fixtures.c.venue_id,
            fixtures.c.home_team_id,
            fixtures.c.away_team_id,
            fixtures.c.kickoff_utc,
        ).where(fixtures.c.competition_id == competition_id, fixtures.c.season == season)
    ).all()
    for r in rows:
        cls, reason = classify_venue(
            r.venue_id,
            grounds.get(r.home_team_id, TeamGround()),
            grounds.get(r.away_team_id, TeamGround()),
            overrides.get(r.id),
            approved(r.home_team_id, r.kickoff_utc),
        )
        conn.execute(
            update(fixtures)
            .where(fixtures.c.id == r.id)
            .values(venue_classification=cls, venue_classification_reason=reason)
        )
        summary[cls] += 1
    return dict(summary)


def require_season(conn: Connection, competition_id: int, season: int) -> None:
    exists = conn.execute(
        select(seasons.c.year).where(
            seasons.c.competition_id == competition_id, seasons.c.year == season
        )
    ).first()
    if exists is None:
        raise MissingReferenceData(
            f"No seasons row for competition {competition_id}, season {season} "
            "(fixtures.competition_id/season reference seasons.competition_id/year). "
            "Run `diski9 setup` to load competitions and seasons first."
        )


def ingest_fixtures(
    conn: Connection,
    client: ApiFootballClient,
    competition_id: int,
    season: int,
    clock: Clock = utcnow,
) -> RunStats:
    """Fetch one competition-season and upsert it (one API request).

    Fixtures reference ``seasons(competition_id, year)``; that row must exist
    (created by ``sync_competitions`` / ``diski9 setup``). Checked before the
    API request so a missing prerequisite costs no quota.
    """
    require_season(conn, competition_id, season)
    items = fetch_season_fixtures(client, competition_id, season)
    return apply_season_fixtures(conn, items, competition_id, season, clock)


def fetch_season_fixtures(client: ApiFootballClient, competition_id: int, season: int) -> list:
    """The provider request of :func:`ingest_fixtures` alone (no database access),
    so a caller can fetch first and write in a short transaction afterwards (Phase
    6C.6 E.1b fetch-then-write)."""
    return client.get("fixtures", {"league": competition_id, "season": season}).items


def apply_season_fixtures(
    conn: Connection,
    items: list,
    competition_id: int,
    season: int,
    clock: Clock = utcnow,
    requests: int = 1,
) -> RunStats:
    """The database part of :func:`ingest_fixtures` for already-fetched items:
    the same ``ingestion_runs`` record, upsert, season membership and venue
    classification, in the caller's transaction."""
    require_season(conn, competition_id, season)
    with ingestion_run(conn, "ingest_fixtures", clock, competition_id, season) as stats:
        stats.requests += requests
        result = store_fixtures(conn, items, clock)
        stats.inserted, stats.updated, stats.unchanged = (
            result.inserted,
            result.updated,
            result.unchanged,
        )
        refresh_team_seasons(conn, competition_id, season, clock)
        stats.extra["venue_classification"] = refresh_venue_classification(
            conn, competition_id, season
        )
    return stats


def stale_fixture_ids(conn: Connection, now) -> list[int]:
    """Fixtures whose kickoff has passed but which are not yet final or excluded
    (candidates for an incremental update)."""
    q = select(fixtures.c.id).where(
        and_(
            fixtures.c.kickoff_utc < now,
            or_(
                fixtures.c.status_short.in_(["NS", "TBD"]),
                fixtures.c.stats_exclusion_reason == "in_progress",
            ),
        )
    )
    return [r.id for r in conn.execute(q)]


def count_by_status(conn: Connection, competition_id: int, season: int) -> dict[str, int]:
    q = (
        select(fixtures.c.status_short, func.count())
        .where(fixtures.c.competition_id == competition_id, fixtures.c.season == season)
        .group_by(fixtures.c.status_short)
    )
    return {status: n for status, n in conn.execute(q)}
