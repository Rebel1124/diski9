"""Fixtures for the competition-backend tests, which run against real PostgreSQL.

Set ``DISKI9_APP_TEST_DATABASE_URL`` to a database whose name ends in ``_test``
(docs/backend.md). Without it these tests are skipped locally; continuous
integration sets ``DISKI9_REQUIRE_POSTGRES=1`` so a missing database fails instead.
The schema is dropped and migrated afresh once per test session; tests create
their own rows with unique values instead of deleting (history tables cannot be
deleted from).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from pg_helpers import make_round, make_user
from sqlalchemy import Engine, create_engine, pool, text

from diski9.backend.db import (
    BackendDatabaseSettings,
    make_app_engine,
    migrate,
    require_test_database_url,
    transaction,
)

REQUIRE = os.environ.get("DISKI9_REQUIRE_POSTGRES") == "1"


def _test_url() -> str:
    url = os.environ.get("DISKI9_APP_TEST_DATABASE_URL")
    if not url:
        msg = "PostgreSQL tests need DISKI9_APP_TEST_DATABASE_URL (see docs/backend.md)"
        if REQUIRE:
            pytest.fail(msg)
        pytest.skip(msg)
    return require_test_database_url(url, os.environ.get("DISKI9_APP_ENVIRONMENT", "test"))


def reset_schema(url: str) -> None:
    eng = create_engine(url, poolclass=pool.NullPool)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS public.app_alembic_version"))
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'diski9_app') "
                "THEN CREATE ROLE diski9_app NOLOGIN; END IF; END $$;"
            )
        )
    eng.dispose()


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = _test_url()
    reset_schema(url)
    migrate.upgrade(url)
    return url


@pytest.fixture(scope="session")
def engine(pg_url) -> Iterator[Engine]:
    eng = make_app_engine(
        BackendDatabaseSettings(environment="test", lock_timeout_ms=2000), url=pg_url
    )
    yield eng
    eng.dispose()


@pytest.fixture
def world(engine):
    """A user and an open round with its snapshot (committed)."""
    with transaction(engine) as conn:
        uid = make_user(conn)
        rid, snap, fids = make_round(conn)
    return {"user": uid, "round": rid, "snapshot": snap, "fixtures": fids}
