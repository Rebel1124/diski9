"""Migration commands for the competition database (``diski9 app-db ...``)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_LOCATION = PROJECT_ROOT / "migrations_app"
VERSION_TABLE = "app_alembic_version"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(SCRIPT_LOCATION))
    # alembic interpolates '%' in options
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def current(url: str) -> str | None:
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"version_table": VERSION_TABLE, "version_table_schema": "public"}
            )
            return ctx.get_current_revision()
    finally:
        engine.dispose()


def head() -> str:
    return ScriptDirectory.from_config(alembic_config("postgresql://unused/x")).get_current_head()
