"""Shared ingestion helpers: clock, run logging, SQLite upserts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Table, insert, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from diski9.db.schema import ingestion_runs

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def parse_api_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


def upsert(conn: Connection, table: Table, rows: list[dict[str, Any]], keys: list[str]) -> None:
    """INSERT ... ON CONFLICT DO UPDATE for every non-key column supplied."""
    if not rows:
        return
    for row in rows:
        stmt = sqlite_insert(table).values(**row)
        cols = {k: stmt.excluded[k] for k in row if k not in keys}
        stmt = (
            stmt.on_conflict_do_update(index_elements=keys, set_=cols)
            if cols
            else (stmt.on_conflict_do_nothing(index_elements=keys))
        )
        conn.execute(stmt)


@dataclass
class RunStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    requests: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@contextmanager
def ingestion_run(
    conn: Connection,
    job: str,
    clock: Clock = utcnow,
    competition_id: int | None = None,
    season: int | None = None,
) -> Iterator[RunStats]:
    """Record a job in ``ingestion_runs``. The data changes of a failed run are
    rolled back by the caller's transaction; the failure itself is recorded in
    a separate statement after rollback by the CLI layer."""
    run_id = conn.execute(
        insert(ingestion_runs).values(
            job=job,
            competition_id=competition_id,
            season=season,
            started_at=clock(),
            status="running",
        )
    ).inserted_primary_key[0]
    stats = RunStats()
    yield stats
    conn.execute(
        update(ingestion_runs)
        .where(ingestion_runs.c.id == run_id)
        .values(
            finished_at=clock(),
            status="complete",
            requests=stats.requests,
            inserted=stats.inserted,
            updated=stats.updated,
            unchanged=stats.unchanged,
        )
    )
