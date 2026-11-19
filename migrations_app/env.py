"""Alembic environment for the competition database (PostgreSQL, schema ``app``).

Separate from ``migrations/`` (the SQLite football store, D-39). The version table
lives in ``public.app_alembic_version`` so that dropping the ``app`` schema on a
downgrade does not remove it.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
VERSION_TABLE = "app_alembic_version"


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            version_table=VERSION_TABLE,
            version_table_schema="public",
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():  # pragma: no cover
    raise SystemExit("offline SQL generation is not supported for the competition schema")
run_migrations_online()
