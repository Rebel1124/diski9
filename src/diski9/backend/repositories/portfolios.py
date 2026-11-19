"""Portfolio data access: entries, confirmed submission versions, selections and
entry events (the foundations of Phase 6C.3; the full confirm/replace/withdraw
workflow, validation and analysis are added there)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Row, insert, select, update

from ..db.schema import entries, entry_events, submission_selections, submissions


def create_entry(conn: Connection, round_id: UUID, user_id: UUID) -> UUID:
    return conn.execute(
        insert(entries).values(round_id=round_id, user_id=user_id).returning(entries.c.id)
    ).scalar_one()


def lock_entry(conn: Connection, round_id: UUID, user_id: UUID, nowait: bool = False) -> Row | None:
    """The caller's entry for this round, locked ``FOR UPDATE`` (the user ID always
    comes from the server session, never from the client)."""
    return conn.execute(
        select(entries)
        .where(entries.c.round_id == round_id, entries.c.user_id == user_id)
        .with_for_update(nowait=nowait)
    ).one_or_none()


def find_submission_by_key(conn: Connection, user_id: UUID, key: str) -> Row | None:
    return conn.execute(
        select(submissions).where(
            submissions.c.user_id == user_id, submissions.c.idempotency_key == key
        )
    ).one_or_none()


def insert_submission(
    conn: Connection, values: Mapping[str, Any], selections: Iterable[Mapping[str, Any]]
) -> UUID:
    sub_id = conn.execute(
        insert(submissions).values(**values).returning(submissions.c.id)
    ).scalar_one()
    rows = [dict(s, submission_id=sub_id, snapshot_id=values["snapshot_id"]) for s in selections]
    conn.execute(insert(submission_selections), rows)
    return sub_id


def set_current_submission(
    conn: Connection,
    entry_id: UUID,
    submission_id: UUID | None,
    expected_version: int,
    state: str = "confirmed",
) -> bool:
    """Optimistic update: succeeds only if nobody changed the entry since it was read."""
    res = conn.execute(
        update(entries)
        .where(entries.c.id == entry_id, entries.c.version == expected_version)
        .values(current_submission_id=submission_id, state=state, version=entries.c.version + 1)
    )
    return res.rowcount == 1


def add_event(
    conn: Connection,
    entry_id: UUID,
    kind: str,
    *,
    submission_id: UUID | None = None,
    previous_submission_id: UUID | None = None,
    actor: UUID | None = None,
) -> None:
    conn.execute(
        insert(entry_events).values(
            entry_id=entry_id,
            kind=kind,
            submission_id=submission_id,
            previous_submission_id=previous_submission_id,
            actor_user_id=actor,
        )
    )
