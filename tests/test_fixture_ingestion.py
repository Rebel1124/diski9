from __future__ import annotations

from datetime import timedelta

import httpx
from sqlalchemy import select

from diski9.db.schema import fixtures, ingestion_runs, team_seasons, teams
from diski9.ingestion import reference
from diski9.ingestion.fixtures import (
    ingest_fixtures,
    normalise_fixture,
    refresh_team_seasons,
    refresh_venue_classification,
    stale_fixture_ids,
    store_fixtures,
)
from diski9.ingestion.quality import promoted_relegated, season_report

from .conftest import envelope, json_response
from .factories import T0, fixture_item, round_robin, seed_competition


def clock():
    return T0


def get(conn, fid):
    return conn.execute(select(fixtures).where(fixtures.c.id == fid)).one()


def test_normalise_uses_90_minute_score_not_goals():
    item = fixture_item(
        1, 10, 20, status="AET", ft=(1, 1), et=(1, 0), goals=(2, 1), round_name="Final"
    )
    row = normalise_fixture(item)
    assert (row["ft_home"], row["ft_away"]) == (1, 1)
    assert (row["et_home"], row["et_away"]) == (1, 0)
    assert row["is_final"] and row["round_type"] == "playoff"
    assert row["stats_exclusion_reason"] == "playoff_round"
    assert row["kickoff_utc"].tzinfo is not None


def test_venue_id_zero_treated_as_missing(conn):
    seed_competition(conn)
    item = fixture_item(1, 10, 20, venue_id=None)
    item["fixture"]["venue"] = {"id": 0, "name": "Some Stadium", "city": "Upington"}
    store_fixtures(conn, [item], clock)
    row = get(conn, 1)
    assert row.venue_id is None and row.venue_name == "Some Stadium"


def test_store_is_idempotent(conn):
    seed_competition(conn)
    items = [
        fixture_item(1, 10, 20),
        fixture_item(2, 20, 10, kickoff=T0 + timedelta(days=7), status="NS"),
    ]
    s1 = store_fixtures(conn, items, clock)
    s2 = store_fixtures(conn, items, clock)
    assert (s1.inserted, s1.updated, s1.unchanged) == (2, 0, 0)
    assert (s2.inserted, s2.updated, s2.unchanged) == (0, 0, 2)
    assert conn.execute(select(fixtures)).rowcount != 0
    assert len(conn.execute(select(fixtures)).all()) == 2
    assert {t.id for t in conn.execute(select(teams))} == {10, 20}


def test_status_transition_updates_and_records_result_time(conn):
    seed_competition(conn)
    store_fixtures(conn, [fixture_item(1, 10, 20, status="NS")], clock)
    row = get(conn, 1)
    assert not row.is_final and row.result_recorded_at is None
    assert row.stats_exclusion_reason == "not_started"
    later = T0 + timedelta(hours=3)
    s = store_fixtures(conn, [fixture_item(1, 10, 20, status="FT", ft=(2, 2))], lambda: later)
    assert s.updated == 1
    row = get(conn, 1)
    assert row.is_final and (row.ft_home, row.ft_away) == (2, 2)
    assert row.result_recorded_at == later
    assert row.first_seen_at == T0
    assert row.stats_exclusion_reason is None


def test_excluded_statuses_retained_with_reason(conn):
    seed_competition(conn)
    store_fixtures(
        conn,
        [
            fixture_item(1, 10, 20, status="AWD", ft=(3, 0)),
            fixture_item(2, 20, 10, status="CANC"),
            fixture_item(3, 10, 30, status="PST"),
            fixture_item(4, 30, 10, round_name="Relegation Round - 1"),
        ],
        clock,
    )
    reasons = {r.id: r.stats_exclusion_reason for r in conn.execute(select(fixtures))}
    assert reasons == {1: "awarded", 2: "cancelled", 3: "postponed", 4: "relegation_round"}


def test_team_seasons_ignore_playoff_only_teams_and_classify_venues(conn):
    seed_competition(conn)
    items = round_robin([10, 20, 30, 40], start=T0 - timedelta(days=200), season=2025)
    items.append(
        fixture_item(
            9001,
            10,
            99,
            season=2025,
            round_name="Playoffs - 1",
            venue_id=510,
            kickoff=T0 - timedelta(days=100),
        )
    )
    # one regular match away from the usual ground, one with no venue
    items.append(
        fixture_item(
            9002,
            20,
            30,
            season=2025,
            venue_id=777,
            round_name="Regular Season - 9",
            kickoff=T0 - timedelta(days=90),
        )
    )
    items.append(
        fixture_item(
            9003,
            30,
            20,
            season=2025,
            venue_id=None,
            round_name="Regular Season - 9",
            kickoff=T0 - timedelta(days=89),
        )
    )
    store_fixtures(conn, items, clock)
    refresh_team_seasons(conn, 39, 2025, clock)
    members = {r.team_id: r for r in conn.execute(select(team_seasons))}
    assert set(members) == {10, 20, 30, 40}  # 99 played only a play-off
    assert members[10].modal_home_venue_id == 510
    summary = refresh_venue_classification(conn, 39, 2025)
    assert get(conn, 9002).venue_classification == "potential_neutral"
    assert get(conn, 9003).venue_classification == "unknown"
    assert get(conn, 1000).venue_classification == "home_ground"
    assert summary["home_ground"] == 13  # 12 round-robin + play-off at team 10's ground
    report = season_report(conn, 39, 2025, T0)
    assert report["regular_season_teams"] == 4
    assert any("more than once" in i for i in report["issues"])  # 20v30 twice
    assert any("expected 12" in i for i in report["issues"])


def test_neutral_override(conn, tmp_path):
    seed_competition(conn)
    store_fixtures(conn, round_robin([10, 20], start=T0 - timedelta(days=50), season=2025), clock)
    csv = tmp_path / "ov.csv"
    csv.write_text("# c\nfixture_id,classification,note\n1000,neutral,Cup final venue\n")
    assert reference.load_neutral_overrides(conn, csv, clock) == 1
    refresh_team_seasons(conn, 39, 2025, clock)
    refresh_venue_classification(conn, 39, 2025)
    row = get(conn, 1000)
    assert (row.venue_classification, row.venue_classification_reason) == (
        "neutral",
        "explicit_override",
    )


def test_promoted_and_relegated(conn):
    seed_competition(conn, 39, years=(2025, 2026))
    seed_competition(conn, 40, years=(2025, 2026), name="Championship")
    store_fixtures(
        conn,
        round_robin([1, 2], start=T0 - timedelta(days=300), league=39, season=2025, first_id=1),
        clock,
    )
    store_fixtures(
        conn,
        round_robin([3, 4], start=T0 - timedelta(days=300), league=40, season=2025, first_id=10),
        clock,
    )
    store_fixtures(
        conn,
        round_robin([1, 3], start=T0 - timedelta(days=50), league=39, season=2026, first_id=20),
        clock,
    )
    store_fixtures(
        conn,
        round_robin([2, 4], start=T0 - timedelta(days=50), league=40, season=2026, first_id=30),
        clock,
    )
    for cid in (39, 40):
        for yr in (2025, 2026):
            refresh_team_seasons(conn, cid, yr, clock)
    assert promoted_relegated(conn, 39, 40, 2026) == {
        "promoted": [3],
        "relegated": [2],
        "new_to_top_without_lower_history": [],
    }


def test_ingest_fixtures_with_client_and_rerun(conn, make_client):
    seed_competition(conn)
    payload = envelope(
        [
            fixture_item(1, 10, 20),
            fixture_item(2, 20, 10, status="NS", kickoff=T0 + timedelta(days=1)),
        ]
    )
    client, seen = make_client(lambda r: json_response(payload))
    s1 = ingest_fixtures(conn, client, 39, 2026, clock)
    s2 = ingest_fixtures(conn, client, 39, 2026, clock)
    assert (s1.inserted, s2.unchanged) == (2, 2)
    assert dict(seen[0].url.params) == {"league": "39", "season": "2026"}
    runs = conn.execute(select(ingestion_runs)).all()
    assert [r.status for r in runs] == ["complete", "complete"]
    assert runs[0].requests == 1 and runs[1].unchanged == 2


def test_stale_fixtures_detected(conn):
    seed_competition(conn)
    store_fixtures(
        conn,
        [
            fixture_item(1, 10, 20, status="NS", kickoff=T0 - timedelta(hours=5)),
            fixture_item(2, 20, 10, status="NS", kickoff=T0 + timedelta(hours=5)),
        ],
        clock,
    )
    assert stale_fixture_ids(conn, T0) == [1]
    assert any("still NS" in i for i in season_report(conn, 39, 2026, T0)["issues"])


def test_sync_reference_from_api(conn, make_client, tmp_path):
    league = {
        "league": {"id": 39, "name": "Premier League", "type": "League"},
        "country": {"name": "England"},
        "seasons": [
            {
                "year": 2026,
                "start": "2026-08-21",
                "end": "2027-05-30",
                "current": True,
                "coverage": {"odds": True},
            }
        ],
    }
    team_items = [
        {
            "team": {"id": 42, "name": "Arsenal", "code": "ARS", "country": "England"},
            "venue": {"id": 494, "name": "Emirates Stadium", "city": "London"},
        }
    ]
    books = [{"id": 8, "name": "Bet365"}, {"id": 37, "name": None}]

    def handler(request: httpx.Request):
        path = request.url.path.strip("/")
        return json_response(
            envelope({"leagues": [league], "teams": team_items, "odds/bookmakers": books}[path])
        )

    client, _ = make_client(handler)
    reference.sync_competitions(conn, client, [39], clock)
    reference.sync_teams(conn, client, 39, 2026, clock)
    cfg = tmp_path / "b.csv"
    cfg.write_text(
        "id,name,is_exchange,affiliation_group,eligible,notes\n37,,0,,0,unnamed\n8,,0,,,\n"
    )
    reference.sync_bookmakers(conn, client, cfg, clock)
    from diski9.db.schema import bookmakers

    b = {r.id: r for r in conn.execute(select(bookmakers))}
    assert b[8].name == "Bet365" and b[8].eligible
    assert not b[37].eligible
    ts = conn.execute(select(team_seasons)).one()
    assert (ts.team_id, ts.registered_venue_id) == (42, 494)
