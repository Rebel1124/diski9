"""Operational data access: job runs (with overlap protection) and audit records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, insert, select, text, update

from ..db.schema import audit_log, job_runs


def try_job_lock(conn: Connection, job: str, scope: str = "") -> bool:
    """Transaction-scoped advisory lock for ``(job, scope)``: ``False`` means another
    run holds it, and this run must stop (and may record itself as skipped)."""
    return conn.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"diski9:{job}:{scope}"},
    ).scalar_one()


def start_job(
    conn: Connection,
    job: str,
    scope: str = "",
    args: Mapping[str, Any] | None = None,
    host: str | None = None,
) -> int:
    return conn.execute(
        insert(job_runs)
        .values(job=job, scope=scope, args=dict(args or {}), host=host)
        .returning(job_runs.c.id)
    ).scalar_one()


def finish_job(
    conn: Connection, run_id: int, status: str, *, api_requests: int = 0, error: str | None = None
) -> None:
    conn.execute(
        update(job_runs)
        .where(job_runs.c.id == run_id)
        .values(
            status=status,
            finished_at=func.clock_timestamp(),
            api_requests=api_requests,
            error=error,
        )
    )


def record_audit(
    conn: Connection,
    *,
    action: str,
    target_type: str,
    target_id: str,
    actor: UUID | None = None,
    actor_role: str = "system",
    reason: str | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    job_run_id: int | None = None,
) -> int:
    return conn.execute(
        insert(audit_log)
        .values(
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor_user_id=actor,
            actor_role=actor_role,
            reason=reason,
            before=dict(before) if before is not None else None,
            after=dict(after) if after is not None else None,
            request_id=request_id,
            job_run_id=job_run_id,
        )
        .returning(audit_log.c.id)
    ).scalar_one()


def audit_for(conn: Connection, target_type: str, target_id: str) -> list:
    return list(
        conn.execute(
            select(audit_log)
            .where(audit_log.c.target_type == target_type, audit_log.c.target_id == target_id)
            .order_by(audit_log.c.id)
        )
    )
