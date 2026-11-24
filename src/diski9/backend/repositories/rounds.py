"""Rounds data access: schedules, rounds and their status history, immutable snapshots.

Locking helpers make the concurrency conventions explicit:
* :func:`lock_round_for_submission` takes ``FOR SHARE`` on the round row, so many
  submissions can proceed together but a status change has to wait for them;
* :func:`lock_round_for_change` takes ``FOR NO KEY UPDATE`` (used by lock,
  settlement and operator jobs), which waits for in-flight submissions to commit and
  serialises every change of the round, but does not block foreign-key checks of rows
  that merely *reference* the round (``FOR KEY SHARE``). Championship processing
  inserts such rows for other rounds of the stream under the stream lock; with
  ``FOR UPDATE`` two finalisations could deadlock (Phase 6C.5 F3, implementation
  record §8). The round's key is never updated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Row, insert, select, update

from ..db.schema import (
    championship_series,
    round_schedules,
    round_snapshots,
    round_status_history,
    rounds,
    snapshot_fixtures,
    snapshot_offers,
)


def schedule_id(conn: Connection, code: str = "weekend", version: int | None = None) -> int:
    """The id of an explicit ``version`` of ``code``, or (no version) of the row valid
    at this transaction's database timestamp. Never the latest version (A3 4A)."""
    if version is not None:
        return conn.execute(
            select(round_schedules.c.id).where(
                round_schedules.c.code == code, round_schedules.c.version == version
            )
        ).scalar_one()
    from ..services.schedules import current_schedule

    return current_schedule(conn, code).id


def series_id(conn: Connection, code: str) -> int:
    return conn.execute(
        select(championship_series.c.id).where(championship_series.c.code == code)
    ).scalar_one()


def create_round(
    conn: Connection,
    code: str,
    schedule: int,
    series: int,
    window_start: datetime,
    window_end: datetime,
) -> UUID:
    return conn.execute(
        insert(rounds)
        .values(
            code=code,
            schedule_id=schedule,
            series_id=series,
            window_start_at=window_start,
            window_end_at=window_end,
        )
        .returning(rounds.c.id)
    ).scalar_one()


def set_status(
    conn: Connection,
    round_id: UUID,
    to_status: str,
    *,
    reason: str | None = None,
    actor: UUID | None = None,
    job_run_id: int | None = None,
    **fields: Any,
) -> None:
    """Change the round's status (and set-once fields such as the deadline) and
    append the status history row in the same transaction."""
    current = conn.execute(
        select(rounds.c.status).where(rounds.c.id == round_id).with_for_update(key_share=True)
    ).scalar_one()
    conn.execute(update(rounds).where(rounds.c.id == round_id).values(status=to_status, **fields))
    conn.execute(
        insert(round_status_history).values(
            round_id=round_id,
            from_status=current,
            to_status=to_status,
            actor_user_id=actor,
            job_run_id=job_run_id,
            reason=reason,
        )
    )


def lock_round_for_submission(conn: Connection, round_id: UUID) -> Row:
    return conn.execute(
        select(rounds.c.id, rounds.c.status, rounds.c.deadline_at)
        .where(rounds.c.id == round_id)
        .with_for_update(read=True)
    ).one()


def lock_round_for_change(conn: Connection, round_id: UUID, nowait: bool = False) -> Row:
    return conn.execute(
        select(rounds).where(rounds.c.id == round_id).with_for_update(nowait=nowait, key_share=True)
    ).one()


def insert_snapshot(
    conn: Connection,
    round_id: UUID,
    *,
    as_of: datetime,
    fingerprint: str,
    model_version: str,
    feasibility: Mapping[str, Any],
    fixtures: Iterable[Mapping[str, Any]],
    offers: Iterable[Mapping[str, Any]],
    params_hash: str | None = None,
    job_run_id: int | None = None,
) -> int:
    snap_id = conn.execute(
        insert(round_snapshots)
        .values(
            round_id=round_id,
            as_of=as_of,
            fingerprint=fingerprint,
            model_version=model_version,
            params_hash=params_hash,
            feasibility=dict(feasibility),
            source_job_run_id=job_run_id,
        )
        .returning(round_snapshots.c.id)
    ).scalar_one()
    fx = [dict(f, snapshot_id=snap_id) for f in fixtures]
    if fx:
        conn.execute(insert(snapshot_fixtures), fx)
    of = [dict(o, snapshot_id=snap_id) for o in offers]
    if of:
        conn.execute(insert(snapshot_offers), of)
    return snap_id
