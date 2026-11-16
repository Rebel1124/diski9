"""First-time setup and incremental refresh workflows.

``setup`` (first run on a new computer, safe to re-run):

1. apply migrations
2. load config (venue overrides, approved home grounds)
3. competitions + seasons for every configured competition  (FK parents of fixtures)
4. bookmakers
5. teams/venues per competition-season (registered home grounds)
6. fixtures for 2023-2026 per competition (historical seasons only once)
7. venue classification pass over everything
8. verify that every required competition-season loaded
9. official standings (top flights), optional odds
10. screener cache - only if step 8 passed

Each competition-season is its own transaction, so an interrupted setup keeps
what it finished and a re-run resumes. Completed historical seasons (an
``ingestion_runs`` row with status ``complete``) are skipped unless
``force=True``; the current season is always refreshed. All writes are upserts,
so re-running never duplicates rows.

``refresh`` (routine, after setup): current-season fixtures, standings,
optional odds, screener cache. It refuses to run, with a clear message, if
setup has not completed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Engine, func, inspect, select

from diski9.api_football import ApiFootballClient
from diski9.db import upgrade
from diski9.db.schema import competitions, fixtures, ingestion_runs, seasons
from diski9.ingestion import reference
from diski9.ingestion.common import MissingReferenceData, utcnow
from diski9.ingestion.fixtures import ingest_fixtures, refresh_venue_classification
from diski9.leagues import COMPETITIONS, CURRENT_SEASON, screener_competitions, seasons_for
from diski9.odds.collect import collect_odds
from diski9.screener import cache

Log = Callable[[str], None]


class SetupIncomplete(RuntimeError):
    """Required historical data is missing; the screener cache was not calculated."""


@dataclass
class WorkflowResult:
    requests: int = 0
    fixtures_inserted: int = 0
    fixtures_updated: int = 0
    fixtures_unchanged: int = 0
    seasons_fetched: list[tuple[int, int]] = field(default_factory=list)
    seasons_skipped: list[tuple[int, int]] = field(default_factory=list)
    screener: dict[str, int] = field(default_factory=dict)
    screener_fixtures: int = 0


def _completed(engine: Engine, job: str, competition_id: int, season: int) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                select(ingestion_runs.c.id).where(
                    ingestion_runs.c.job == job,
                    ingestion_runs.c.competition_id == competition_id,
                    ingestion_runs.c.season == season,
                    ingestion_runs.c.status == "complete",
                )
            ).first()
            is not None
        )


def missing_requirements(
    engine: Engine,
    competition_ids: list[int] | None = None,
    years: tuple[int, ...] | None = None,
) -> list[str]:
    """Human-readable list of what is missing for the screener to be valid."""
    competition_ids = competition_ids or list(COMPETITIONS)
    problems: list[str] = []
    if not inspect(engine).has_table("competitions"):
        return ["database not initialised (no tables)"]
    with engine.connect() as conn:
        have_comp = {r[0] for r in conn.execute(select(competitions.c.id))}
        have_season = {
            (r.competition_id, r.year)
            for r in conn.execute(select(seasons.c.competition_id, seasons.c.year))
        }
        counts = {
            (r.competition_id, r.season): r.n
            for r in conn.execute(
                select(
                    fixtures.c.competition_id, fixtures.c.season, func.count().label("n")
                ).group_by(fixtures.c.competition_id, fixtures.c.season)
            )
        }
    for cid in competition_ids:
        if cid not in have_comp:
            problems.append(f"competition {cid} not loaded")
            continue
        for yr in years or seasons_for(cid):
            if (cid, yr) not in have_season:
                problems.append(f"season row missing: competition {cid} season {yr}")
            elif not counts.get((cid, yr)) or not _completed(engine, "ingest_fixtures", cid, yr):
                problems.append(f"fixtures not loaded: competition {cid} season {yr}")
    return problems


def _ingest_season(
    engine: Engine, client: ApiFootballClient, cid: int, yr: int, clock, res: WorkflowResult
):
    with engine.begin() as conn:
        s = ingest_fixtures(conn, client, cid, yr, clock)
    res.seasons_fetched.append((cid, yr))
    res.fixtures_inserted += s.inserted
    res.fixtures_updated += s.updated
    res.fixtures_unchanged += s.unchanged
    return s


def _screener(engine: Engine, now: datetime, days: int, res: WorkflowResult) -> None:
    comps = screener_competitions()
    with engine.begin() as conn:
        ids = cache.upcoming_fixture_ids(conn, comps, now, now + timedelta(days=days))
        res.screener = cache.refresh(conn, ids, now, now)
        res.screener_fixtures = len(ids)


def setup(
    engine: Engine,
    client: ApiFootballClient,
    *,
    force: bool = False,
    with_odds: bool = False,
    days: int = 21,
    clock=utcnow,
    log: Log = print,
    migrate: bool = True,
) -> WorkflowResult:
    res = WorkflowResult()
    if migrate:
        upgrade(str(engine.url.render_as_string(hide_password=False)))
        log("database migrated")
    comp_ids = list(COMPETITIONS)

    with engine.begin() as conn:
        reference.load_neutral_overrides(conn, clock=clock)
        reference.load_approved_home_grounds(conn, clock=clock)
        reference.sync_competitions(conn, client, comp_ids, clock)
        reference.sync_bookmakers(conn, client, clock=clock)
    log(f"competitions, seasons and bookmakers loaded ({len(comp_ids)} competitions)")

    with engine.connect() as conn:
        available = {(r.competition_id, r.year) for r in conn.execute(select(seasons))}
    for cid in comp_ids:
        for yr in seasons_for(cid):
            if (cid, yr) not in available:
                raise MissingReferenceData(
                    f"API-Football lists no season {yr} for competition {cid}"
                )
            if force or yr == CURRENT_SEASON or not _completed(engine, "sync_teams", cid, yr):
                with engine.begin() as conn:
                    reference.sync_teams(conn, client, cid, yr, clock)
    log("teams and venues loaded")

    for cid in comp_ids:
        for yr in seasons_for(cid):
            historical = yr != CURRENT_SEASON
            if historical and not force and _completed(engine, "ingest_fixtures", cid, yr):
                res.seasons_skipped.append((cid, yr))
                continue
            s = _ingest_season(engine, client, cid, yr, clock, res)
            log(f"fixtures {cid}/{yr}: +{s.inserted} ~{s.updated} ={s.unchanged}")

    with engine.begin() as conn:
        for cid in comp_ids:
            for yr in seasons_for(cid):
                refresh_venue_classification(conn, cid, yr)

    problems = missing_requirements(engine, comp_ids)
    if problems:
        raise SetupIncomplete(
            "Historical data incomplete; screener not calculated: " + "; ".join(problems)
        )
    log("historical data verified")

    _standings_and_odds(engine, client, with_odds, clock, log)
    res.requests = client.quota_requests_made
    _screener(engine, clock(), days, res)
    log(f"screener cache: {res.screener_fixtures} fixtures {res.screener}")
    return res


def _standings_and_odds(
    engine, client, with_odds: bool, clock, log: Log, standings: bool = True
) -> None:
    if standings:
        top = [c.id for c in COMPETITIONS.values() if c.tier == 1]
        with engine.begin() as conn:
            for cid in top:
                reference.sync_standings(conn, client, cid, CURRENT_SEASON, clock)
        log("official standings updated")
    if with_odds:
        for cid in [c.id for c in COMPETITIONS.values() if c.odds_enabled]:
            # Odds are optional context: a failure is reported (and rolled back for
            # that competition) but never blocks the screener statistics.
            try:
                with engine.begin() as conn:
                    st = collect_odds(conn, client, cid, CURRENT_SEASON, clock)
            except Exception as exc:  # noqa: BLE001
                log(f"WARNING odds {cid}: collection failed and was rolled back ({exc!r:.300})")
                continue
            note = (
                " (provider pages inconsistent; deduplicated)" if st.inconsistent_pagination else ""
            )
            log(f"odds {cid}: {st.fixtures_collected} fixtures, {st.quotes_seen} quotes{note}")


def refresh(
    engine: Engine,
    client: ApiFootballClient,
    *,
    with_odds: bool = False,
    skip_standings: bool = False,
    days: int = 21,
    clock=utcnow,
    log: Log = print,
) -> WorkflowResult:
    """Incremental refresh: current season only. Requires a completed setup."""
    problems = missing_requirements(engine)
    if problems:
        raise SetupIncomplete(
            "Initial setup has not completed ("
            + "; ".join(problems[:4])
            + ("; ..." if len(problems) > 4 else "")
            + "). Run `diski9 setup` first."
        )
    res = WorkflowResult()
    with engine.begin() as conn:
        reference.load_neutral_overrides(conn, clock=clock)
        reference.load_approved_home_grounds(conn, clock=clock)
    for cid in COMPETITIONS:
        s = _ingest_season(engine, client, cid, CURRENT_SEASON, clock, res)
        log(f"fixtures {cid}/{CURRENT_SEASON}: +{s.inserted} ~{s.updated} ={s.unchanged}")
    with engine.begin() as conn:
        for cid in COMPETITIONS:
            refresh_venue_classification(conn, cid, CURRENT_SEASON)
    _standings_and_odds(engine, client, with_odds, clock, log, standings=not skip_standings)
    res.requests = client.quota_requests_made
    _screener(engine, clock(), days, res)
    log(f"screener cache: {res.screener_fixtures} fixtures {res.screener}")
    return res
