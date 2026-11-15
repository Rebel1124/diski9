"""Data-quality checks over stored fixtures. Read-only; returns plain dicts."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, select

from diski9.db.schema import competitions, fixtures, team_seasons


def season_report(
    conn: Connection, competition_id: int, season: int, now: datetime
) -> dict[str, Any]:
    rows = conn.execute(
        select(fixtures).where(
            fixtures.c.competition_id == competition_id, fixtures.c.season == season
        )
    ).all()
    regular = [r for r in rows if r.round_type == "regular"]
    members = conn.execute(
        select(team_seasons.c.team_id).where(
            team_seasons.c.competition_id == competition_id,
            team_seasons.c.season == season,
            team_seasons.c.regular_season_fixtures > 0,
        )
    ).all()
    n_teams = len(members)
    expected_regular = n_teams * (n_teams - 1) if n_teams else None

    pairs = Counter((r.home_team_id, r.away_team_id) for r in regular)
    issues: list[str] = []
    if expected_regular is not None and len(regular) != expected_regular:
        issues.append(f"regular-season fixtures {len(regular)} != expected {expected_regular}")
    dup_pairs = [p for p, n in pairs.items() if n > 1]
    if dup_pairs:
        issues.append(f"{len(dup_pairs)} home/away pairings appear more than once")
    stale = [r.id for r in rows if r.kickoff_utc < now and r.status_short in ("NS", "TBD")]
    if stale:
        issues.append(f"{len(stale)} fixtures past kickoff still NS/TBD")
    missing_score = [r.id for r in rows if r.stats_exclusion_reason == "missing_score"]
    if missing_score:
        issues.append(f"{len(missing_score)} finished fixtures without a 90-minute score")
    bad_ht = [
        r.id
        for r in rows
        if r.is_final and r.ht_home is not None and (r.ht_home > r.ft_home or r.ht_away > r.ft_away)
    ]
    if bad_ht:
        issues.append(f"{len(bad_ht)} fixtures with half-time score above full-time score")
    future_final = [r.id for r in rows if r.is_final and r.kickoff_utc > now]
    if future_final:
        issues.append(f"{len(future_final)} fixtures final with kickoff in the future")

    return {
        "competition_id": competition_id,
        "season": season,
        "fixtures": len(rows),
        "regular_season_fixtures": len(regular),
        "regular_season_teams": n_teams,
        "expected_regular_season_fixtures": expected_regular,
        "final_results": sum(1 for r in rows if r.is_final),
        "stats_eligible": sum(1 for r in rows if r.stats_exclusion_reason is None),
        "status_counts": dict(Counter(r.status_short for r in rows)),
        "round_type_counts": dict(Counter(r.round_type for r in rows)),
        "exclusion_reasons": dict(
            Counter(r.stats_exclusion_reason for r in rows if r.stats_exclusion_reason)
        ),
        "venue_classification": dict(Counter(r.venue_classification for r in rows)),
        "venue_classification_reasons": dict(Counter(r.venue_classification_reason for r in rows)),
        "extra_time_matches": sum(1 for r in rows if r.et_home is not None),
        "issues": issues,
    }


def promoted_relegated(
    conn: Connection, top_id: int, lower_id: int, season: int
) -> dict[str, list[int]]:
    """Teams in the top flight this season that were in the lower division last
    season (promoted), and vice versa (relegated)."""

    def members(cid: int, yr: int) -> set[int]:
        q = select(team_seasons.c.team_id).where(
            team_seasons.c.competition_id == cid,
            team_seasons.c.season == yr,
            team_seasons.c.regular_season_fixtures > 0,
        )
        return {r.team_id for r in conn.execute(q)}

    top_now, top_prev = members(top_id, season), members(top_id, season - 1)
    low_now, low_prev = members(lower_id, season), members(lower_id, season - 1)
    return {
        "promoted": sorted(top_now & low_prev),
        "relegated": sorted(low_now & top_prev),
        "new_to_top_without_lower_history": sorted(top_now - top_prev - low_prev)
        if top_prev
        else [],
    }


def full_report(conn: Connection, seasons: list[int], now: datetime) -> dict[str, Any]:
    comps = conn.execute(
        select(competitions.c.id, competitions.c.name, competitions.c.parent_competition_id)
    ).all()
    out: dict[str, Any] = {"generated_at": now.isoformat(), "competitions": {}, "promotion": {}}
    for c in comps:
        out["competitions"][c.id] = {
            "name": c.name,
            "seasons": {s: season_report(conn, c.id, s, now) for s in seasons},
        }
        if c.parent_competition_id:
            out["promotion"][f"{c.parent_competition_id}<->{c.id}"] = {
                s: promoted_relegated(conn, c.parent_competition_id, c.id, s) for s in seasons[1:]
            }
    return out
