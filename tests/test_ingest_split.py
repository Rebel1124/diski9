"""Phase 6C.6 E.1b: fetch-then-write for fixtures and odds (REF-09).

The combined CLI functions (``ingest_fixtures``, ``collect_odds``) and the split
scheduler functions store identical data, and no football-store write lock is held
while a provider request is in flight. Mock transport and temporary SQLite stores
only."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine, select, text

from diski9.db import make_engine, upgrade
from diski9.db.schema import fixtures, ingestion_runs, odds_fetches, odds_quotes
from diski9.ingestion.fixtures import (
    apply_season_fixtures,
    fetch_season_fixtures,
    ingest_fixtures,
)
from diski9.odds.collect import collect_odds, fetch_odds_pages, reconcile_pages

from .conftest import envelope, json_response
from .factories import T0, fixture_item, full_book, odds_item, seed_competition

KICK = T0 + timedelta(days=30)
ITEMS = [fixture_item(i, 10 + i, 20 + i, status="NS", kickoff=KICK) for i in range(1, 4)]
ODDS = [odds_item(i, {8: full_book(), 11: full_book(home="2.10")}) for i in range(1, 4)]


def _store(tmp_path, name):
    url = f"sqlite:///{tmp_path / name}"
    upgrade(url)
    eng = make_engine(url)
    with eng.begin() as c:
        seed_competition(c)
    return url, eng


def _rows(eng, table, *cols):
    with eng.connect() as c:
        return [tuple(r) for r in c.execute(select(*[table.c[n] for n in cols]).order_by(*[
            table.c[n] for n in cols]))]  # fmt: skip


def _handler(url_for_probe=None, probes=None):
    def handler(request):
        if url_for_probe is not None:
            probes.append(_can_write(url_for_probe))
        path = request.url.path.strip("/")
        if path == "fixtures":
            return json_response(envelope(ITEMS))
        page = int(request.url.params.get("page", 1))
        return json_response(envelope(ODDS[(page - 1) * 2 : page * 2], current=page, total=2))

    return handler


def _can_write(url) -> bool:
    """Another process-like connection takes the store's write lock immediately."""
    probe = create_engine(url, connect_args={"timeout": 0.2})
    try:
        with probe.connect() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            c.exec_driver_sql("ROLLBACK")
        return True
    except Exception:  # noqa: BLE001 - "database is locked"
        return False
    finally:
        probe.dispose()


def test_split_fixture_ingestion_stores_the_same_rows(tmp_path, make_client):
    url_a, a = _store(tmp_path, "a.sqlite")
    url_b, b = _store(tmp_path, "b.sqlite")
    client, _ = make_client(_handler())
    with a.begin() as c:
        sa = ingest_fixtures(c, client, 39, 2026, lambda: T0)
    items = fetch_season_fixtures(client, 39, 2026)
    with b.begin() as c:
        sb = apply_season_fixtures(c, items, 39, 2026, lambda: T0)
    assert (sa.inserted, sa.requests) == (sb.inserted, sb.requests) == (3, 1)
    cols = ("id", "kickoff_utc", "status_short", "content_hash", "venue_classification")
    assert _rows(a, fixtures, *cols) == _rows(b, fixtures, *cols)
    assert _rows(a, ingestion_runs, "job", "status", "requests") == _rows(
        b, ingestion_runs, "job", "status", "requests"
    )


def test_split_odds_collection_stores_the_same_quotes(tmp_path, make_client):
    _, a = _store(tmp_path, "a.sqlite")
    _, b = _store(tmp_path, "b.sqlite")
    client, _ = make_client(_handler())
    for eng in (a, b):
        with eng.begin() as c:
            apply_season_fixtures(c, ITEMS, 39, 2026, lambda: T0)
    with a.begin() as c:
        st_a = collect_odds(c, client, 39, 2026, lambda: T0)
    pages = fetch_odds_pages(client, 39, 2026)
    with b.begin() as c:
        st_b = reconcile_pages(c, 39, 2026, pages, lambda: T0, started=T0)
    assert (st_a.pages, st_a.fixtures_collected, st_a.quotes_inserted) == (
        st_b.pages, st_b.fixtures_collected, st_b.quotes_inserted)  # fmt: skip
    cols = ("fixture_id", "bookmaker_id", "market", "outcome", "decimal_odds")
    assert _rows(a, odds_quotes, *cols) == _rows(b, odds_quotes, *cols)
    with a.connect() as c:
        fetch = c.execute(select(odds_fetches.c.retrieved_at, odds_fetches.c.status)).one()
    assert fetch.status == "complete"
    assert fetch.retrieved_at.replace(tzinfo=None) == T0.replace(tzinfo=None)  # start time


def test_no_store_write_lock_during_provider_requests(tmp_path, make_client):
    """The CLI functions now fetch before writing, so a second writer is never blocked
    by a slow provider request (previously the run record was inserted first)."""
    url, eng = _store(tmp_path, "s.sqlite")
    probes: list[bool] = []
    client, _ = make_client(_handler(url, probes))
    # one transaction per call, exactly as ``workflow.refresh`` runs them
    with eng.begin() as c:
        ingest_fixtures(c, client, 39, 2026, lambda: T0)
    with eng.begin() as c:
        collect_odds(c, client, 39, 2026, lambda: T0)
    assert probes and all(probes), probes  # 1 fixtures + 2 odds pages, never locked
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM odds_quotes")).scalar_one() > 0
