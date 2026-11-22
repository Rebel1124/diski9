"""Read-only operational history (Stage D; data access ready for Stage E).

Recent job runs with their outcome class, plus, for one round, its audit records
(indexed on ``audit_log (target_type, target_id, at)``) and the settlement runs
linked to scheduler jobs. Bounded result sets only; no account or provider data.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, bindparam, text

from ..db import read_only
from .snapshot import JobRow

KNOWN_JOBS = (
    "scheduler.tick",
    "scheduler.lock",
    "scheduler.results",
    "scheduler.results_full",
    "scheduler.settle",
    "scheduler.finalise",
    "scheduler.prepare_draft",
    "scheduler.prepare_readiness",
    "scheduler.prepare_refresh",
    "scheduler.prepare_screener",
    "ops.notify",
    "lock",
    "publish",
    "results-import",
)


def recent_jobs(
    engine: Engine,
    *,
    limit: int = 30,
    job: str | None = None,
    round_code: str | None = None,
    failed_only: bool = False,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    jobs = (job,) if job else KNOWN_JOBS
    where = ["job IN :jobs"]
    params: dict[str, Any] = {"jobs": list(jobs), "limit": limit}
    with read_only(engine) as conn:
        round_id = None
        if round_code:
            round_id = conn.execute(
                text("SELECT id FROM app.rounds WHERE code = :c"), {"c": round_code}
            ).scalar_one_or_none()
            where.append("scope IN :scopes")
            params["scopes"] = [round_code] + ([str(round_id)] if round_id else [])
        if failed_only:
            where.append("status = 'failed'")
        stmt = text(
            "SELECT id, job, scope, status, started_at, finished_at, error, api_requests "
            f"FROM app.job_runs WHERE {' AND '.join(where)} ORDER BY started_at DESC LIMIT :limit"
        ).bindparams(bindparam("jobs", expanding=True))
        if "scopes" in params:
            stmt = stmt.bindparams(bindparam("scopes", expanding=True))
        rows = [
            JobRow(
                r.id, r.job, r.scope, r.status, r.started_at, r.finished_at, r.error, r.api_requests
            )
            for r in conn.execute(stmt, params)
        ]
        ids = [r.id for r in rows if r.job == "scheduler.settle"]
        links = {}
        if ids:
            links = dict(
                conn.execute(
                    text(
                        "SELECT job_run_id, id FROM app.settlement_runs WHERE job_run_id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": ids},
                ).all()
            )
        audit = []
        if round_id is not None:
            audit = [
                dict(r._mapping)
                for r in conn.execute(
                    text(
                        "SELECT id, at, action, actor_role, job_run_id FROM app.audit_log "
                        "WHERE target_type = 'round' AND target_id = :t ORDER BY at DESC LIMIT 50"
                    ),
                    {"t": str(round_id)},
                )
            ]
    return {
        "jobs": [dict(r.as_dict(), settlement_run_id=links.get(r.id)) for r in rows],
        "audit": audit,
    }
