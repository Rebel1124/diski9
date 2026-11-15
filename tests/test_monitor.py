from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from diski9.db.schema import odds_quotes
from diski9.ingestion.fixtures import store_fixtures
from diski9.odds.monitor import analyse, load_runs, replay, run_monitor

from .conftest import envelope, json_response
from .factories import T0, fixture_item, full_book, odds_item, seed_competition

KICK = T0 + timedelta(days=3)


def client_for(items_by_league, make_client):
    def handler(request):
        league = int(request.url.params["league"])
        return json_response(envelope(items_by_league.get(league, [])))

    client, _ = make_client(handler)
    return client


def test_capture_writes_slim_file_and_summary(tmp_path, make_client):
    item = odds_item(1, {8: full_book()}, kickoff=KICK)
    item["bookmakers"][0]["bets"].append({"id": 10, "name": "Exact Score", "values": []})
    client = client_for({39: [item]}, make_client)
    summary = run_monitor(client, [39, 288], 2026, tmp_path, now=T0)
    assert summary["competitions"][39]["quotes"] == 7
    assert summary["competitions"][288]["fixtures"] == 0
    runs = load_runs(tmp_path)
    bets = runs[0]["competitions"]["39"]["pages"][0]["items"][0]["bookmakers"][0]["bets"]
    assert {b["id"] for b in bets} == {1, 5, 8}  # unrelated markets dropped
    lines = (tmp_path / "runs.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["requests"] == 2


def test_capture_refused_after_end(tmp_path, make_client):
    client = client_for({}, make_client)
    with pytest.raises(RuntimeError):
        run_monitor(client, [39], 2026, tmp_path, until=T0, now=T0 + timedelta(seconds=1))


def test_replay_reproduces_episodes(tmp_path, make_client, conn, monkeypatch):
    import diski9.api_football.client as client_mod

    seed_competition(conn)
    store_fixtures(conn, [fixture_item(1, 10, 20, status="NS", kickoff=KICK)], lambda: T0)
    for hours, home, upd in (
        (0, "2.00", "2026-11-15T03:00:00+00:00"),
        (3, "2.10", "2026-11-15T03:00:00+00:00"),
    ):
        at = T0 + timedelta(hours=hours)
        monkeypatch.setattr(
            client_mod, "datetime", type("F", (), {"now": staticmethod(lambda tz=None, at=at: at)})
        )
        client = client_for(
            {39: [odds_item(1, {8: full_book(home=home)}, kickoff=KICK, update=upd)]}, make_client
        )
        run_monitor(client, [39], 2026, tmp_path, now=at)
    runs = load_runs(tmp_path)
    result = replay(conn, runs)
    assert result.fetches == 2 and not result.errors
    rows = conn.execute(select(odds_quotes)).all()
    assert len(rows) == 8  # 7 + one price change
    report = analyse(conn, runs)
    assert report["quotes"]["price_changes"] == 1
    assert report["quotes"]["price_changes_without_provider_update_change"] == 1
    assert report["provider_update"]["fixture_level_changes_between_runs"] == 0
