from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from diski9.db.schema import bookmakers, odds_fetches, odds_fixture_observations, odds_quotes
from diski9.ingestion.fixtures import store_fixtures
from diski9.odds.collect import collect_odds

from .conftest import envelope, json_response
from .factories import T0, fixture_item, full_book, odds_item, seed_competition

KICK = T0 + timedelta(days=3)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def setup(conn, extra=()):
    seed_competition(conn)
    store_fixtures(
        conn,
        [
            fixture_item(1, 10, 20, status="NS", kickoff=KICK),
            fixture_item(2, 30, 40, status="NS", kickoff=KICK),
            fixture_item(3, 50, 60, status="FT", kickoff=T0 - timedelta(days=1)),
            *extra,
        ],
        lambda: T0,
    )


def run(conn, make_client, pages, monkeypatch, at=T0):
    """pages: list of lists of odds items. Freezes retrieval time to ``at``."""
    import diski9.api_football.client as client_mod

    class FrozenDT:
        @staticmethod
        def now(tz=None):
            return at

    monkeypatch.setattr(client_mod, "datetime", FrozenDT)

    def handler(request):
        page = int(request.url.params.get("page", 1))
        return json_response(envelope(pages[page - 1], current=page, total=len(pages)))

    client, _ = make_client(handler)
    return collect_odds(conn, client, 39, 2026, Clock(at))


def quotes(conn, **filters):
    q = select(odds_quotes)
    for k, v in filters.items():
        q = q.where(getattr(odds_quotes.c, k) == v)
    return conn.execute(q.order_by(odds_quotes.c.id)).all()


def test_first_collection_inserts_seven_outcomes_per_complete_book(conn, make_client, monkeypatch):
    setup(conn)
    s = run(conn, make_client, [[odds_item(1, {8: full_book(), 11: full_book()})]], monkeypatch)
    assert s.quotes_inserted == 14 and s.fixtures_collected == 1
    rows = quotes(conn)
    assert {r.outcome for r in rows} == {
        "HOME",
        "DRAW",
        "AWAY",
        "BTTS_YES",
        "BTTS_NO",
        "OVER_2_5",
        "UNDER_2_5",
    }
    r = quotes(conn, bookmaker_id=8, outcome="OVER_2_5")[0]
    assert r.decimal_odds == Decimal("1.90")
    assert r.first_seen_at == T0 and r.last_seen_at == T0 and r.ended_at is None
    assert r.first_provider_updated_at.isoformat() == "2026-11-15T03:00:00+00:00"
    obs = conn.execute(select(odds_fixture_observations)).one()
    assert obs.bookmakers_listed == 2 and obs.quotes_parsed == 14
    assert conn.execute(select(odds_fetches)).one().status == "complete"
    assert {b.id for b in conn.execute(select(bookmakers))} == {8, 11}  # auto-registered


def test_unchanged_quotes_not_duplicated(conn, make_client, monkeypatch):
    setup(conn)
    page = [[odds_item(1, {8: full_book()})]]
    run(conn, make_client, page, monkeypatch, at=T0)
    s = run(conn, make_client, page, monkeypatch, at=T0 + timedelta(hours=3))
    assert s.quotes_unchanged == 7 and s.quotes_inserted == 0
    rows = quotes(conn)
    assert len(rows) == 7
    assert all(r.times_seen == 2 and r.last_seen_at == T0 + timedelta(hours=3) for r in rows)


def test_price_change_preserved_even_with_same_provider_timestamp(conn, make_client, monkeypatch):
    setup(conn)
    run(conn, make_client, [[odds_item(1, {8: full_book(home="2.00")})]], monkeypatch, at=T0)
    later = T0 + timedelta(hours=3)
    s = run(conn, make_client, [[odds_item(1, {8: full_book(home="2.10")})]], monkeypatch, at=later)
    assert s.quotes_price_changed == 1 and s.quotes_inserted == 1 and s.quotes_unchanged == 6
    home = quotes(conn, bookmaker_id=8, outcome="HOME")
    assert [(r.decimal_odds, r.end_reason) for r in home] == [
        (Decimal("2.00"), "price_changed"),
        (Decimal("2.10"), None),
    ]
    assert home[0].ended_at == later and home[1].first_seen_at == later
    # same provider timestamp on both episodes
    assert home[0].first_provider_updated_at == home[1].first_provider_updated_at


def test_disappearance_and_reappearance(conn, make_client, monkeypatch):
    setup(conn)
    run(conn, make_client, [[odds_item(1, {8: full_book(), 11: full_book()})]], monkeypatch, at=T0)
    t1 = T0 + timedelta(hours=3)
    book11_no_btts = {k: v for k, v in full_book().items() if k != "8"}
    s = run(
        conn,
        make_client,
        [[odds_item(1, {8: full_book(), 11: book11_no_btts})]],
        monkeypatch,
        at=t1,
    )
    assert s.quotes_disappeared == 2
    gone = quotes(conn, bookmaker_id=11, market="BTTS")
    assert all(r.end_reason == "disappeared" and r.ended_at == t1 for r in gone)
    t2 = T0 + timedelta(hours=6)
    run(conn, make_client, [[odds_item(1, {8: full_book(), 11: full_book()})]], monkeypatch, at=t2)
    btts = quotes(conn, bookmaker_id=11, market="BTTS")
    assert len(btts) == 4 and sum(r.ended_at is None for r in btts) == 2  # new episode


def test_incomplete_market_not_stored(conn, make_client, monkeypatch):
    setup(conn)
    book = full_book()
    book["1"] = [("Home", "2.0"), ("Away", "3.0")]  # no Draw
    s = run(conn, make_client, [[odds_item(1, {8: book})]], monkeypatch)
    assert {r.market for r in quotes(conn)} == {"BTTS", "OU25"}
    assert any("incomplete 1X2" in w for w in s.warnings)


def test_fixture_missing_from_complete_response_disappears(conn, make_client, monkeypatch):
    setup(conn)
    run(
        conn,
        make_client,
        [[odds_item(1, {8: full_book()})], [odds_item(2, {8: full_book()})]],
        monkeypatch,
    )
    s = run(
        conn,
        make_client,
        [[odds_item(1, {8: full_book()})]],
        monkeypatch,
        at=T0 + timedelta(hours=1),
    )
    assert s.quotes_disappeared == 7
    assert all(r.end_reason == "disappeared" for r in quotes(conn, fixture_id=2))


def test_finished_unknown_and_kicked_off_fixtures_skipped(conn, make_client, monkeypatch):
    setup(conn, extra=[fixture_item(4, 70, 80, status="PST", kickoff=KICK)])
    items = [
        odds_item(3, {8: full_book()}, kickoff=T0 - timedelta(days=1)),  # already played
        odds_item(4, {8: full_book()}),  # postponed
        odds_item(999, {8: full_book()}),  # unknown fixture
    ]
    s = run(conn, make_client, [items], monkeypatch)
    assert s.fixtures_collected == 0 and quotes(conn) == []
    assert dict(s.skipped) == {"kicked_off": 1, "status_PST": 1, "unknown_fixture": 1}


def test_active_quotes_closed_at_kickoff(conn, make_client, monkeypatch):
    setup(conn)
    run(conn, make_client, [[odds_item(1, {8: full_book()})]], monkeypatch, at=T0)
    after = KICK + timedelta(hours=2)
    s = run(conn, make_client, [[odds_item(1, {8: full_book()})]], monkeypatch, at=after)
    assert s.quotes_closed_at_kickoff == 7 and s.skipped["kicked_off"] == 1
    assert all(r.end_reason == "kickoff" and r.ended_at == KICK for r in quotes(conn))


def test_empty_response(conn, make_client, monkeypatch):
    setup(conn)
    s = run(conn, make_client, [[]], monkeypatch)
    assert s.fixtures_in_response == 0 and s.requests == 1
