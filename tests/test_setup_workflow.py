"""Integration: first-time setup from a completely empty SQLite file, re-runs,
incremental refresh, and failure handling, against a simulated API-Football."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, inspect, select

from diski9 import workflow
from diski9.db import make_engine
from diski9.db.schema import (
    competitions,
    fixtures,
    screener_results,
    seasons,
    standings_snapshots,
    team_seasons,
    teams,
    venues,
)
from diski9.ingestion.common import MissingReferenceData
from diski9.ingestion.fixtures import ingest_fixtures
from diski9.leagues import BACKFILL_SEASONS, COMPETITIONS, CURRENT_SEASON

from .conftest import envelope, json_response
from .factories import T0, fixture_item, full_book, odds_item

DAY = timedelta(days=1)
TEAMS_PER_LEAGUE = 4


def team_ids(cid: int) -> list[int]:
    return [cid * 100 + i for i in range(1, TEAMS_PER_LEAGUE + 1)]


class FakeApi:
    """Serves leagues, teams, fixtures, standings, bookmakers and odds."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail: set[tuple[str, int, int]] = set()  # (endpoint, league, season) -> HTTP 500
        self.played_upcoming: set[int] = set()  # upcoming fixture ids reported as finished

    def fixtures(self, cid: int, season: int) -> list[dict]:
        out, fid = [], cid * 1_000_000 + season * 100
        start = T0 - (CURRENT_SEASON - season + 1) * 365 * DAY
        k = 0
        for h in team_ids(cid):
            for a in team_ids(cid):
                if h == a:
                    continue
                fid += 1
                k += 1
                if season < CURRENT_SEASON or k <= 6:
                    item = fixture_item(
                        fid,
                        h,
                        a,
                        league=cid,
                        season=season,
                        kickoff=start + k * 7 * DAY,
                        ft=(k % 3, (k + 1) % 2),
                        venue_id=h,
                    )
                else:  # upcoming within the screener window
                    kick = T0 + (k - 6) * DAY
                    status = "FT" if fid in self.played_upcoming else "NS"
                    item = fixture_item(
                        fid,
                        h,
                        a,
                        league=cid,
                        season=season,
                        kickoff=kick,
                        status=status,
                        ft=(2, 2),
                        venue_id=h,
                    )
                out.append(item)
        return out

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.strip("/")
        p = dict(request.url.params)
        self.calls.append((path, p))
        league, season = int(p.get("league", p.get("id", 0))), int(p.get("season", 0))
        if (path, league, season) in self.fail:
            return httpx.Response(500, text="boom")
        if path == "leagues":
            return json_response(
                envelope(
                    [
                        {
                            "league": {
                                "id": league,
                                "name": COMPETITIONS[league].name,
                                "type": "League",
                            },
                            "country": {"name": "Testland"},
                            "seasons": [
                                {
                                    "year": y,
                                    "start": f"{y}-08-01",
                                    "end": f"{y + 1}-05-31",
                                    "current": y == CURRENT_SEASON,
                                    "coverage": {"odds": y == CURRENT_SEASON},
                                }
                                for y in BACKFILL_SEASONS
                            ],
                        }
                    ]
                )
            )
        if path == "odds/bookmakers":
            return json_response(
                envelope([{"id": 8, "name": "Book 8"}, {"id": 11, "name": "Book 11"}])
            )
        if path == "teams":
            return json_response(
                envelope(
                    [
                        {
                            "team": {
                                "id": t,
                                "name": f"Team {t}",
                                "code": None,
                                "country": "Testland",
                            },
                            "venue": {"id": t, "name": f"Ground {t}", "city": "Town"},
                        }
                        for t in team_ids(league)
                    ]
                )
            )
        if path == "fixtures":
            return json_response(envelope(self.fixtures(league, season)))
        if path == "standings":
            rows = [
                {
                    "rank": i + 1,
                    "team": {"id": t, "name": f"Team {t}"},
                    "points": 10 - i,
                    "goalsDiff": 0,
                    "all": {
                        "played": 3,
                        "win": 1,
                        "draw": 1,
                        "lose": 1,
                        "goals": {"for": 3, "against": 3},
                    },
                    "update": "2026-11-14T00:00:00+00:00",
                }
                for i, t in enumerate(team_ids(league))
            ]
            return json_response(envelope([{"league": {"standings": [rows]}}]))
        if path == "odds":
            if league != 39:
                return json_response(envelope([]))
            upcoming = [
                f
                for f in self.fixtures(39, CURRENT_SEASON)
                if f["fixture"]["status"]["short"] == "NS"
            ]
            items = [
                odds_item(
                    f["fixture"]["id"],
                    {8: full_book(), 11: full_book(), 4: full_book()},
                    kickoff=T0 + DAY,
                )
                for f in upcoming[:2]
            ]
            for item, f in zip(items, upcoming[:2], strict=True):
                item["fixture"]["date"] = f["fixture"]["date"]
            return json_response(envelope(items))
        return httpx.Response(404)

    def fixture_calls(self) -> Counter:
        return Counter(
            (int(p["league"]), int(p["season"])) for path, p in self.calls if path == "fixtures"
        )


@pytest.fixture
def empty_db(tmp_path):
    url = f"sqlite:///{tmp_path / 'brand_new.sqlite'}"
    eng = make_engine(url)
    assert inspect(eng).get_table_names() == []  # truly empty: no tables at all
    yield eng
    eng.dispose()


@pytest.fixture
def api(make_client):
    fake = FakeApi()
    client, _ = make_client(fake.handler)
    return fake, client


def counts(eng) -> dict[str, int]:
    with eng.connect() as c:
        out = {
            t.name: c.execute(select(func.count()).select_from(t)).scalar()
            for t in (
                competitions,
                seasons,
                teams,
                venues,
                team_seasons,
                fixtures,
                standings_snapshots,
            )
        }
        out["distinct_fixtures"] = c.execute(
            select(func.count(func.distinct(fixtures.c.id)))
        ).scalar()
        out["active_cache"] = c.execute(
            select(func.count()).where(screener_results.c.superseded_at.is_(None))
        ).scalar()
    return out


def run_setup(eng, client, **kw):
    return workflow.setup(eng, client, clock=lambda: T0, log=lambda _m: None, **kw)


def test_setup_from_empty_database_populates_everything(empty_db, api):
    fake, client = api
    res = run_setup(empty_db, client, with_odds=True)
    c = counts(empty_db)
    n_comp, n_seasons = len(COMPETITIONS), len(BACKFILL_SEASONS)
    per_season = TEAMS_PER_LEAGUE * (TEAMS_PER_LEAGUE - 1)
    assert c["competitions"] == n_comp and c["seasons"] == n_comp * n_seasons
    assert c["teams"] == n_comp * TEAMS_PER_LEAGUE and c["venues"] == n_comp * TEAMS_PER_LEAGUE
    assert c["fixtures"] == c["distinct_fixtures"] == n_comp * n_seasons * per_season
    assert c["team_seasons"] == n_comp * n_seasons * TEAMS_PER_LEAGUE
    assert c["standings_snapshots"] == 2 * TEAMS_PER_LEAGUE  # EPL + PSL official tables
    # every competition and every season 2023-2026 was fetched exactly once
    assert fake.fixture_calls() == Counter(
        {(cid, yr): 1 for cid in COMPETITIONS for yr in BACKFILL_SEASONS}
    )
    # screener cache: 6 upcoming top-flight fixtures per league x 2 leagues x 2 bases
    assert res.screener_fixtures == 12 and c["active_cache"] == 24
    assert workflow.missing_requirements(empty_db) == []
    # reference rows were created before fixtures: no dangling foreign keys
    with empty_db.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    # the order of API calls: leagues before any fixtures
    paths = [p for p, _ in fake.calls]
    assert paths.index("fixtures") > max(i for i, p in enumerate(paths) if p == "leagues")


def test_setup_rerun_is_idempotent_and_skips_historical_seasons(empty_db, api):
    fake, client = api
    run_setup(empty_db, client)
    before = counts(empty_db)
    fake.calls.clear()
    res = run_setup(empty_db, client)
    assert counts(empty_db) == before
    assert fake.fixture_calls() == Counter({(cid, CURRENT_SEASON): 1 for cid in COMPETITIONS})
    assert len(res.seasons_skipped) == len(COMPETITIONS) * (len(BACKFILL_SEASONS) - 1)
    assert res.screener["inserted"] == 0 and res.screener["unchanged"] == 24
    fake.calls.clear()
    run_setup(empty_db, client, force=True)  # explicit full re-fetch still creates no duplicates
    assert sum(fake.fixture_calls().values()) == len(COMPETITIONS) * len(BACKFILL_SEASONS)
    assert counts(empty_db) == before


def test_incremental_refresh_fetches_only_current_season(empty_db, api):
    fake, client = api
    run_setup(empty_db, client)
    before = counts(empty_db)
    fake.calls.clear()
    # a top-flight upcoming fixture has now been played
    upcoming_id = next(
        f["fixture"]["id"]
        for f in fake.fixtures(39, CURRENT_SEASON)
        if f["fixture"]["status"]["short"] == "NS"
    )
    fake.played_upcoming.add(upcoming_id)
    # refresh after that fixture's kickoff (T0 + 1 day); earlier, point-in-time rules ignore it
    res = workflow.refresh(
        empty_db, client, clock=lambda: T0 + timedelta(hours=36), log=lambda _m: None
    )
    assert fake.fixture_calls() == Counter({(cid, CURRENT_SEASON): 1 for cid in COMPETITIONS})
    assert {p for p, _ in fake.calls} == {"fixtures", "standings"}  # no leagues/teams/backfill
    assert res.fixtures_updated == 1
    after = counts(empty_db)
    assert after["fixtures"] == before["fixtures"]
    assert res.screener["superseded"] >= 1  # results using the new match were recalculated


def test_refresh_before_setup_refuses_without_api_calls(empty_db, api):
    fake, client = api
    with pytest.raises(workflow.SetupIncomplete, match="Run `diski9 setup` first"):
        workflow.refresh(empty_db, client, clock=lambda: T0, log=lambda _m: None)
    assert fake.calls == []


def test_interrupted_setup_builds_no_cache_and_resumes(empty_db, api):
    fake, client = api
    fake.fail.add(("fixtures", 289, 2024))
    with pytest.raises(Exception, match="HTTP 500"):
        run_setup(empty_db, client)
    c = counts(empty_db)
    assert c["active_cache"] == 0  # screener never calculated on incomplete history
    assert c["fixtures"] > 0  # completed seasons were kept
    assert any("289" in p for p in workflow.missing_requirements(empty_db))
    fake.fail.clear()
    fake.calls.clear()
    run_setup(empty_db, client)
    fetched = fake.fixture_calls()
    assert fetched[(289, 2024)] == 1 and fetched[(39, 2023)] == 0  # resumed, not restarted
    assert counts(empty_db)["active_cache"] == 24
    assert workflow.missing_requirements(empty_db) == []


def test_ingest_without_season_row_names_the_missing_reference(empty_db, api):
    from diski9.db import upgrade

    fake, client = api
    upgrade(str(empty_db.url))
    with empty_db.begin() as conn, pytest.raises(MissingReferenceData, match="seasons row") as err:
        ingest_fixtures(conn, client, 39, CURRENT_SEASON)
    assert "competition 39, season 2026" in str(err.value)
    assert fake.calls == []  # checked before spending an API request
