"""Builders for API-shaped payloads and minimal reference rows used in tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from diski9.db.schema import competitions, seasons

T0 = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def seed_competition(conn, cid: int = 39, years=(2025, 2026), name: str = "Premier League") -> None:
    conn.execute(
        competitions.insert().values(
            id=cid, name=name, country="England", type="League", tier=1, updated_at=T0
        )
    )
    for y in years:
        conn.execute(
            seasons.insert().values(
                competition_id=cid,
                year=y,
                is_current=(y == max(years)),
                coverage_odds=True,
                updated_at=T0,
            )
        )


def fixture_item(
    fid: int,
    home: int,
    away: int,
    *,
    league: int = 39,
    season: int = 2026,
    kickoff: datetime = T0,
    status: str = "FT",
    ft: tuple[int | None, int | None] = (1, 0),
    ht: tuple[int | None, int | None] = (0, 0),
    et: tuple[int | None, int | None] = (None, None),
    pen: tuple[int | None, int | None] = (None, None),
    goals: tuple[int | None, int | None] | None = None,
    round_name: str = "Regular Season - 1",
    venue_id: int | None = None,
) -> dict[str, Any]:
    if status in ("NS", "TBD", "PST", "CANC"):
        ft = ht = (None, None)
    return {
        "fixture": {
            "id": fid,
            "date": kickoff.isoformat(),
            "timestamp": int(kickoff.timestamp()),
            "venue": {
                "id": venue_id,
                "name": f"Venue {venue_id}" if venue_id else None,
                "city": None,
            },
            "status": {"short": status, "long": status},
        },
        "league": {"id": league, "season": season, "round": round_name},
        "teams": {
            "home": {"id": home, "name": f"Team {home}"},
            "away": {"id": away, "name": f"Team {away}"},
        },
        "goals": {"home": (goals or ft)[0], "away": (goals or ft)[1]},
        "score": {
            "halftime": {"home": ht[0], "away": ht[1]},
            "fulltime": {"home": ft[0], "away": ft[1]},
            "extratime": {"home": et[0], "away": et[1]},
            "penalty": {"home": pen[0], "away": pen[1]},
        },
    }


def round_robin(
    teams: list[int],
    *,
    start: datetime,
    league: int = 39,
    season: int = 2025,
    first_id: int = 1000,
    venue_of=lambda t: 500 + t,
    status: str = "FT",
) -> list[dict[str, Any]]:
    """Double round-robin: every ordered pair once, each team at its own ground."""
    items, fid, k = [], first_id, 0
    for h in teams:
        for a in teams:
            if h == a:
                continue
            items.append(
                fixture_item(
                    fid,
                    h,
                    a,
                    league=league,
                    season=season,
                    kickoff=start + timedelta(days=k),
                    status=status,
                    venue_id=venue_of(h),
                )
            )
            fid += 1
            k += 1
    return items


def odds_item(
    fid: int,
    books: dict[int, dict[str, list[tuple[str, str]]]],
    *,
    league: int = 39,
    season: int = 2026,
    kickoff: datetime = T0 + timedelta(days=3),
    update: str = "2026-11-15T03:00:00+00:00",
) -> dict[str, Any]:
    """books = {bookmaker_id: {"1": [("Home","2.0"),...], "8": [...], "5": [...]}}"""
    names = {"1": "Match Winner", "8": "Both Teams Score", "5": "Goals Over/Under"}
    return {
        "league": {"id": league, "season": season},
        "fixture": {"id": fid, "date": kickoff.isoformat(), "timestamp": int(kickoff.timestamp())},
        "update": update,
        "bookmakers": [
            {
                "id": bid,
                "name": f"Book {bid}",
                "bets": [
                    {
                        "id": int(bet),
                        "name": names[bet],
                        "values": [{"value": v, "odd": o} for v, o in vals],
                    }
                    for bet, vals in bets.items()
                ],
            }
            for bid, bets in books.items()
        ],
    }


def full_book(
    home="2.00", draw="3.40", away="3.80", yes="1.80", no="2.00", over="1.90", under="1.95"
):
    return {
        "1": [("Home", home), ("Draw", draw), ("Away", away)],
        "8": [("Yes", yes), ("No", no)],
        "5": [
            ("Over 1.5", "1.30"),
            ("Over 2.5", over),
            ("Under 2.5", under),
            ("Under 1.5", "3.50"),
        ],
    }
