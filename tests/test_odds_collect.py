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


# ---------------------------------------------------------------------------
# Inconsistent provider pagination (observed live on 16 Nov 2026 ~04:56 UTC):
# page 1 from a fresh snapshot (total 2), page 2 from a stale snapshot (total 3)
# overlapping page 1.
def _pages_inconsistent(fresh_upd, stale_upd, at):
    from diski9.odds.collect import OddsPage

    fresh = [
        odds_item(1, {8: full_book(home="2.10")}, update=fresh_upd),
        odds_item(2, {8: full_book()}, update=fresh_upd),
    ]
    stale = [
        odds_item(2, {8: full_book(home="9.99")}, update=stale_upd),  # duplicate, older
        odds_item(5, {8: full_book()}, update=stale_upd),
    ]
    return [OddsPage(at, fresh, 1, 2), OddsPage(at, stale, 2, 3)]


def test_inconsistent_pages_deduplicated_newest_wins(conn):
    from diski9.odds.collect import reconcile_pages

    setup(conn, extra=[fixture_item(5, 90, 91, status="NS", kickoff=KICK)])
    pages = _pages_inconsistent("2026-11-16T03:25:21+00:00", "2026-11-15T03:24:18+00:00", T0)
    s = reconcile_pages(conn, 39, 2026, pages, clock=lambda: T0)
    assert s.inconsistent_pagination and s.duplicate_items == 1
    obs = conn.execute(select(odds_fixture_observations)).all()
    assert sorted(o.fixture_id for o in obs) == [1, 2, 5]  # one row per fixture, no UNIQUE error
    home2 = quotes(conn, fixture_id=2, outcome="HOME")
    assert [q.decimal_odds for q in home2] == [
        Decimal("2.00")
    ]  # fresh item kept, stale 9.99 ignored
    assert conn.execute(select(odds_fetches)).one().status == "inconsistent"


def test_inconsistent_fetch_does_not_infer_fixture_disappearance(conn, make_client, monkeypatch):
    from diski9.odds.collect import reconcile_pages

    setup(conn)
    # fixture 2 has active quotes; the inconsistent walk below omits it entirely
    run(
        conn,
        make_client,
        [[odds_item(1, {8: full_book()}), odds_item(2, {8: full_book()})]],
        monkeypatch,
    )
    from diski9.odds.collect import OddsPage

    later = T0 + timedelta(hours=3)
    pages = [
        OddsPage(later, [odds_item(1, {8: full_book()})], 1, 2),
        OddsPage(later, [odds_item(1, {8: full_book()})], 2, 3),
    ]
    s = reconcile_pages(conn, 39, 2026, pages, clock=lambda: later)
    assert s.inconsistent_pagination and s.quotes_disappeared == 0
    assert all(q.ended_at is None for q in quotes(conn, fixture_id=2))


def test_stale_item_never_moves_prices_backwards(conn):
    from diski9.odds.collect import OddsPage, reconcile_pages

    setup(conn)
    t1 = T0
    reconcile_pages(
        conn,
        39,
        2026,
        [
            OddsPage(
                t1, [odds_item(1, {8: full_book(home="2.10")}, update="2026-11-16T03:00:00+00:00")]
            )
        ],
        clock=lambda: t1,
    )
    t2 = T0 + timedelta(hours=1)
    s = reconcile_pages(
        conn,
        39,
        2026,
        [
            OddsPage(
                t2, [odds_item(1, {8: full_book(home="1.90")}, update="2026-11-15T03:00:00+00:00")]
            )
        ],
        clock=lambda: t2,
    )
    assert s.skipped["stale_item"] == 1 and s.quotes_price_changed == 0
    assert [q.decimal_odds for q in quotes(conn, fixture_id=1, outcome="HOME")] == [Decimal("2.10")]


def test_paginate_follows_largest_total_and_stops_on_empty(make_client):
    pages = {1: ([{"n": 1}], 2), 2: ([{"n": 2}], 3), 3: ([], 2)}

    def handler(request):
        page = int(request.url.params.get("page", 1))
        items, total = pages[page]
        return json_response(envelope(items, current=page, total=total))

    client, seen = make_client(handler)
    items = client.get_all("odds", {"league": 39})
    assert items == [{"n": 1}, {"n": 2}]
    assert [r.url.params.get("page") for r in seen] == [
        None,
        "2",
        "3",
    ]  # page 3 requested (total 3)
