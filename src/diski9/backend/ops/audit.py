"""Read-only audit viewer (Phase 6C.6 Stage E; the "audit list" item of the approved
6C.6 design).

Authorised by the existing ``audit.view`` capability (operators and owners), so a
password-verified person is required. Shows when, what, who acted (their public
username, or ``SYSTEM`` for the scheduler) and on what (a round's code, an
account's username, or the target's type and id), with the recorded reason and job
link. Never shows email addresses, before/after payloads, request identifiers or
credentials. Bounded and indexed: newest first by primary key, at most 200 rows;
``--round`` uses ``audit_log (target_type, target_id, at)``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from ..auth.permissions import Capability, Forbidden, Principal, authorize
from ..db import read_only
from ..services.common import NotFound

MAX_ROWS = 200


def audit_list(
    engine: Engine,
    actor: Principal,
    *,
    limit: int = 50,
    action: str | None = None,
    round_code: str | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(actor, Principal):  # a person only: never the scheduler's SYSTEM
        raise Forbidden("human_only")
    authorize(actor, Capability.VIEW_AUDIT)
    limit = max(1, min(int(limit), MAX_ROWS))
    where, params = [], {"limit": limit}
    with read_only(engine) as conn:
        if round_code:
            rid = conn.execute(
                text("SELECT id FROM app.rounds WHERE code = :c"), {"c": round_code}
            ).scalar_one_or_none()
            if rid is None:
                raise NotFound(f"No round with code {round_code!r}.")
            where.append("a.target_type = 'round' AND a.target_id = :rid")
            params["rid"] = str(rid)
        if action:
            # a prefix such as "round." or "role"; LIKE wildcards in the input are literal
            esc = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("a.action LIKE :action ESCAPE '\\'")
            params["action"] = esc + "%"
        if since is not None:
            where.append("a.at >= :since")
            params["since"] = since
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute(
            text(
                "SELECT a.id, a.at, a.action, a.actor_role, a.target_type, a.target_id, "
                "a.reason, a.job_run_id, pa.username AS actor_name, "
                "CASE WHEN a.target_type = 'round' THEN r.code "
                "     WHEN a.target_type IN ('user', 'account') THEN pt.username END "
                "  AS target_name "
                "FROM app.audit_log a "
                "LEFT JOIN app.profiles pa ON pa.user_id = a.actor_user_id "
                "LEFT JOIN app.rounds r ON a.target_type = 'round' "
                "     AND r.id::text = a.target_id "
                "LEFT JOIN app.profiles pt ON a.target_type IN ('user', 'account') "
                "     AND pt.user_id::text = a.target_id "
                f"{clause} ORDER BY a.id DESC LIMIT :limit"
            ),
            params,
        ).all()
    out = []
    for r in rows:
        if r.actor_name:
            who = r.actor_name
        elif r.actor_role == "system" or (r.actor_role is None and r.job_run_id is not None):
            who = "SYSTEM"
        else:
            who = "-"
        out.append(
            {
                "id": r.id,
                "at": r.at,
                "action": r.action,
                "actor": who,
                "actor_role": r.actor_role or "-",
                "target": r.target_name or f"{r.target_type}:{r.target_id}",
                "reason": r.reason,
                "job_run_id": r.job_run_id,
            }
        )
    return out
