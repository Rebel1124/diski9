"""Derive candidate approved home grounds from stored fixtures (evidence report).

A (team, venue, season) is proposed as an approved home ground when the club
played at least --min-matches regular-season home league matches at a venue
that is neither its registered ground nor its usual (modal) ground that season.
Output is a CSV for config/approved_home_grounds.csv; review before committing.

Run: uv run python scripts/home_ground_evidence.py [--min-matches 3]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

from sqlalchemy import select

from diski9.db import make_engine
from diski9.db.schema import competitions, fixtures, seasons, team_seasons, teams, venues
from diski9.leagues import CURRENT_SEASON


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-matches", type=int, default=3)
    args = ap.parse_args()
    eng = make_engine()
    with eng.connect() as c:
        ts = {
            (r.team_id, r.competition_id, r.season): {r.registered_venue_id, r.modal_home_venue_id}
            for r in c.execute(select(team_seasons))
        }
        team_name = dict(c.execute(select(teams.c.id, teams.c.name)).all())
        venue_name = dict(c.execute(select(venues.c.id, venues.c.name)).all())
        comp_name = dict(c.execute(select(competitions.c.id, competitions.c.name)).all())
        dates = {
            (r.competition_id, r.year): (r.start_date, r.end_date)
            for r in c.execute(select(seasons))
        }
        uses: dict[tuple, list[str]] = defaultdict(list)
        for f in c.execute(
            select(fixtures).where(
                fixtures.c.round_type == "regular", fixtures.c.venue_id.is_not(None)
            )
        ):
            known = ts.get((f.home_team_id, f.competition_id, f.season), set())
            if f.venue_id not in known:
                uses[(f.home_team_id, f.venue_id, f.competition_id, f.season)].append(
                    f.kickoff_utc.date().isoformat()
                )
    out = csv.writer(sys.stdout)
    out.writerow(
        ["team_id", "team_name", "venue_id", "venue_name", "valid_from", "valid_to", "evidence"]
    )
    for (team, venue, comp, season), days in sorted(uses.items()):
        if len(days) < args.min_matches:
            continue
        start, end = dates[(comp, season)]
        out.writerow(
            [
                team,
                team_name.get(team),
                venue,
                venue_name.get(venue),
                start,
                "" if season == CURRENT_SEASON else end,
                f"{len(days)} regular-season home league matches in {comp_name[comp]} {season} "
                f"({min(days)} to {max(days)}) per API-Football fixtures",
            ]
        )


if __name__ == "__main__":
    main()
