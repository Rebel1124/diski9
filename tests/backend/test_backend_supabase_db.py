"""Supabase PostgreSQL compatibility on REAL PostgreSQL.

* Always: the ``app`` schema is invisible to Supabase's browser-facing roles
  (``anon``, ``authenticated``: Data API, GraphQL, Realtime), every table has
  row-level security with access only for the runtime role, and the
  transaction-pooler engine mode keeps the timeouts and the database clock.
* With ``DISKI9_TEST_SUPABASE_DB_URL`` (a database that already contains a real
  Supabase Auth ``auth`` schema, such as the local harness database): the
  competition migrations coexist with it and never touch it.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, pool, text

from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, migrate, transaction
from diski9.backend.db import schema as app_schema


def _eng(url):
    return create_engine(url, poolclass=pool.NullPool)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_roles_cannot_see_the_app_schema(pg_url, role):
    eng = _eng(pg_url)
    with eng.connect() as conn:
        usage = conn.execute(
            text("SELECT has_schema_privilege(:r, 'app', 'USAGE')"), {"r": role}
        ).scalar()
        assert usage is False
        for t in app_schema.metadata.sorted_tables:
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": role, "t": f"app.{t.name}", "p": priv},
                ).scalar(), (role, t.name, priv)
    eng.dispose()


def test_browser_role_queries_fail(pg_url):
    eng = _eng(pg_url)
    with eng.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE anon"))
        with pytest.raises(Exception, match="permission denied"):
            conn.execute(text("SELECT count(*) FROM app.user_private"))
    eng.dispose()


def test_every_table_has_row_level_security_and_a_runtime_policy(pg_url):
    eng = _eng(pg_url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, "
                "EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'app' "
                "        AND p.tablename = c.relname AND 'diski9_app' = ANY (p.roles)) AS policy "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'app' AND c.relkind = 'r'"
            )
        ).all()
    assert rows and all(r.relrowsecurity and r.policy for r in rows), [
        r.relname for r in rows if not (r.relrowsecurity and r.policy)
    ]
    eng.dispose()


def test_runtime_role_still_works_under_row_level_security(pg_url):
    eng = _eng(pg_url)
    with eng.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE diski9_app"))
        conn.execute(
            text(
                "INSERT INTO app.audit_log (action, target_type, target_id, actor_role) "
                "VALUES ('test.rls', 't', '1', 'system')"
            )
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.audit_log WHERE action = 'test.rls'")
            ).scalar()
            >= 1
        )
        conn.rollback()
    eng.dispose()


def test_transaction_pooler_mode_keeps_settings_and_clock(pg_url):
    eng = make_app_engine(
        BackendDatabaseSettings(
            environment="test",
            pooler_mode="transaction",
            statement_timeout_ms=4321,
            lock_timeout_ms=1234,
            _env_file=None,
        ),
        url=pg_url,
    )
    with transaction(eng) as conn:
        assert conn.execute(text("SHOW timezone")).scalar() == "UTC"
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "4321ms"
        assert conn.execute(text("SHOW lock_timeout")).scalar() == "1234ms"
        a = db_now(conn)
        assert db_now(conn) == a
        assert conn.execute(text("SELECT pg_try_advisory_xact_lock(42)")).scalar()
    eng.dispose()


SUPABASE_DB = os.environ.get("DISKI9_TEST_SUPABASE_DB_URL")


@pytest.mark.skipif(not SUPABASE_DB, reason="needs a database holding a real Supabase auth schema")
def test_migrations_coexist_with_supabase_auth_schema():
    eng = _eng(SUPABASE_DB)

    def auth_fingerprint():
        with eng.connect() as conn:
            return conn.execute(
                text(
                    "SELECT string_agg(table_name || ':' || column_name || ':' || data_type, ',' "
                    "ORDER BY table_name, column_name) FROM information_schema.columns "
                    "WHERE table_schema = 'auth'"
                )
            ).scalar()

    before = auth_fingerprint()
    assert before, "no auth schema found"
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS public.app_alembic_version"))
    migrate.upgrade(SUPABASE_DB)
    assert migrate.current(SUPABASE_DB) == migrate.head()
    assert auth_fingerprint() == before  # Supabase-managed schema untouched
    with eng.connect() as conn:
        assert (
            conn.execute(text("SELECT has_schema_privilege('anon', 'app', 'USAGE')")).scalar()
            is False
        )
    migrate.downgrade(SUPABASE_DB, "base")
    assert auth_fingerprint() == before
    eng.dispose()
