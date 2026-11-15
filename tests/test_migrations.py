from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from diski9.db.engine import alembic_config
from diski9.db.schema import metadata

EXPECTED = {
    "competitions",
    "seasons",
    "venues",
    "teams",
    "team_seasons",
    "fixtures",
    "neutral_venue_overrides",
    "bookmakers",
    "odds_fetches",
    "odds_fixture_observations",
    "odds_quotes",
    "ingestion_runs",
}


def test_upgrade_creates_all_tables(engine):
    names = set(inspect(engine).get_table_names())
    assert names >= EXPECTED
    assert "alembic_version" in names


def test_migration_matches_metadata(engine):
    with engine.connect() as c:
        ctx = MigrationContext.configure(c, opts={"compare_type": False})
        diff = compare_metadata(ctx, metadata)
    assert diff == []


def test_partial_unique_index_on_active_quotes(engine):
    idx = {i["name"]: i for i in inspect(engine).get_indexes("odds_quotes")}
    assert idx["uq_odds_quotes_active"]["unique"]


def test_downgrade_to_base_and_back(db_url, engine):
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "base")
    eng = create_engine(db_url)
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    assert set(inspect(create_engine(db_url)).get_table_names()) >= EXPECTED


def test_foreign_keys_enforced(conn):
    import pytest
    from sqlalchemy.exc import IntegrityError

    from diski9.db.schema import seasons
    from tests.factories import T0

    with pytest.raises(IntegrityError):
        conn.execute(
            seasons.insert().values(
                competition_id=999, year=2026, is_current=True, coverage_odds=False, updated_at=T0
            )
        )
