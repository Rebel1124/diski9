"""Engine, connections and explicit transaction boundaries for the competition
database (SQLAlchemy 2 Core over psycopg 3).

Conventions (docs/backend.md):
* every write happens inside :func:`transaction` (one ``BEGIN``/``COMMIT``; any
  exception rolls back and is re-raised);
* reads that need a consistent view use :func:`read_only`;
* sessions run in UTC with statement and lock timeouts;
* row locks are taken explicitly (``FOR UPDATE`` / ``FOR SHARE``) by repositories;
* errors are logged without credentials.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import DBAPIError

from .settings import BackendDatabaseError, BackendDatabaseSettings

logger = logging.getLogger(__name__)

APPLICATION_NAME = "diski9-backend"


def make_app_engine(
    settings: BackendDatabaseSettings | None = None, *, url: str | None = None
) -> Engine:
    """A pooled engine for the competition database."""
    settings = settings or BackendDatabaseSettings()
    target = url or settings.url()
    connect_args: dict = {"application_name": APPLICATION_NAME}
    session_settings = {
        "timezone": "UTC",
        "statement_timeout": str(settings.statement_timeout_ms),
        "lock_timeout": str(settings.lock_timeout_ms),
    }
    if settings.pooler_mode == "session":
        connect_args["options"] = " ".join(f"-c {k}={v}" for k, v in session_settings.items())
    else:
        # transaction poolers reuse server connections between clients: no startup
        # options, no server-side prepared statements
        connect_args["prepare_threshold"] = None
    engine = create_engine(
        target,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,
        echo=settings.echo_sql,
        hide_parameters=True,
        connect_args=connect_args,
    )

    if settings.pooler_mode == "transaction":

        @event.listens_for(engine, "begin")
        def _per_transaction_settings(conn) -> None:
            for key, value in session_settings.items():
                conn.exec_driver_sql(f"SELECT set_config('{key}', '{value}', true)")

    @event.listens_for(engine, "handle_error")
    def _log_error(ctx) -> None:  # pragma: no cover - logging only
        logger.warning(
            "database error (%s): %s",
            engine.url.render_as_string(hide_password=True),
            type(ctx.original_exception).__name__,
        )

    return engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """One explicit read-write transaction: commit on success, roll back on error."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        except BaseException:
            trans.rollback()
            raise
        else:
            trans.commit()


@contextmanager
def read_only(engine: Engine) -> Iterator[Connection]:
    """A read-only transaction (writes fail with an error)."""
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        yield conn


def db_now(conn: Connection) -> datetime:
    """The database clock for this transaction (used for deadlines, never the
    application clock)."""
    return conn.execute(text("SELECT transaction_timestamp()")).scalar_one()


def check_health(engine: Engine) -> dict:
    """Connectivity and migration state, safe to expose to operators."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
            revision = conn.execute(
                text(
                    "SELECT version_num FROM public.app_alembic_version"
                    " WHERE to_regclass('public.app_alembic_version') IS NOT NULL"
                )
            ).scalar_one_or_none()
    except DBAPIError as exc:
        raise BackendDatabaseError(
            f"database unavailable at {engine.url.render_as_string(hide_password=True)}: "
            f"{type(exc.orig).__name__}"
        ) from None
    return {"ok": True, "server_version": version, "schema_revision": revision}
