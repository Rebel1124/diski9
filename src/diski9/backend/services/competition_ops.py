"""Operator services for competitions (Phase 6C.5 Stage C): stream status, the
integrity check and the historical backfill.

**Backfill** publishes the official weekly results of rounds that were finalised
before migration ``app_0007``, then assigns rounds to championships. It does so
through exactly the same services as normal finalisation
(``competition.publish_finalised``, ``championships.process_stream``), so it
produces the same result; it never reimplements settlement, ranking or points.

Safeguards:
* the read-only preview performs the real work inside a transaction that is
  rolled back;
* execution needs an operator principal (password per command, S-07) and the
  preview's confirmation token, and refuses if anything changed since the preview;
* processing is deterministic (deadline order per stream), with one transaction
  per round, so an interrupted run resumes safely and repeated runs are no-ops;
* everything is audited;
* rounds that cannot be classified reliably are reported and left alone, never
  assigned to a stream.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, text

from ...challenge import scoring
from ..auth.permissions import Capability, Principal, authorize
from ..db import read_only, transaction
from ..repositories import ops
from ..repositories import rounds as rounds_repo
from . import championships, competition
from .common import ServiceError


class BackfillRefused(ServiceError):
    pass


@dataclass(frozen=True)
class BackfillItem:
    round_code: str
    stream: str
    action: str  # publish | already_published | excluded
    reason: str | None = None
    kind: str | None = None  # championship | practice | void (score set kind)


@dataclass(frozen=True)
class BackfillPlan:
    items: tuple[BackfillItem, ...]
    championships_created: tuple[str, ...]
    rounds_assigned: int
    waiting: int  # rounds that stay unassigned (an earlier round is unresolved/excluded)
    token: str

    @property
    def to_publish(self) -> int:
        return sum(1 for i in self.items if i.action == "publish")


_CANDIDATES = """
SELECT r.id, r.code, r.status, r.is_development, r.result_mode, r.deadline_at, s.code AS series,
       (SELECT count(*) FROM app.score_sets x WHERE x.round_id = r.id) AS sets,
       (SELECT v.id FROM app.settlement_versions v WHERE v.round_id = r.id
         ORDER BY v.version DESC LIMIT 1) AS latest_version,
       (SELECT v.kind FROM app.settlement_versions v WHERE v.round_id = r.id
         ORDER BY v.version DESC LIMIT 1) AS latest_kind,
       (SELECT d.provisional FROM app.designations d WHERE d.round_id = r.id
         ORDER BY d.created_at DESC, d.id DESC LIMIT 1) AS provisional
  FROM app.rounds r JOIN app.championship_series s ON s.id = r.series_id
 WHERE r.status = 'final' {extra}
 ORDER BY r.deadline_at, r.id
"""


def _candidates(conn, round_id: UUID | None = None):
    if round_id is None:
        return conn.execute(text(_CANDIDATES.format(extra=""))).all()
    return conn.execute(text(_CANDIDATES.format(extra="AND r.id = :id")), {"id": round_id}).all()


def _stream(row) -> str:
    return "development" if row.is_development else row.series


def _exclusion(conn, row) -> str | None:
    """Why a final round without results cannot be published reliably."""
    if row.is_development and row.result_mode not in ("real", "synthetic"):
        return "development round without a result mode (cannot be classified)"
    if not row.is_development and row.result_mode != "real":
        return "real round without the real result mode (cannot be classified)"
    if row.series not in ("beta", "official"):
        return f"unknown series {row.series!r} (cannot be classified)"
    if not championships.stream_open(conn, _stream(row)):
        return "the official series has not started (D-38); not assigned to any stream"
    if row.latest_kind != "final" or row.latest_version is None:
        return "no final settlement version"
    if row.provisional is None or row.provisional:
        return "the round's designation is not final"
    return None


def _run(conn, actor_id: UUID | None):
    """The backfill work in ``conn`` (the caller commits or rolls back)."""
    items = []
    created: list[str] = []
    assigned = 0
    for row in _candidates(conn):
        stream = _stream(row)
        if row.sets:
            items.append(BackfillItem(row.code, stream, "already_published"))
            continue
        why = _exclusion(conn, row)
        if why is None:
            nested = conn.begin_nested()
            try:
                p = competition.publish_finalised(
                    conn, row.id, row.latest_version, actor=actor_id,
                    championship_cause="backfill",
                )  # fmt: skip
                nested.commit()
                items.append(BackfillItem(row.code, stream, "publish", kind=p.kind))
                continue
            except (competition.PublicationRefused, scoring.ScoringInputError) as exc:
                nested.rollback()
                why = getattr(exc, "message", None) or str(exc)
        if why is not None:
            items.append(BackfillItem(row.code, stream, "excluded", why))
    waiting = 0
    for stream in championships.STREAMS:
        out = championships.process_stream(conn, stream, actor=actor_id, cause="backfill")
        created += list(out.created)
        assigned += out.assigned
        waiting += len(out.waiting)
    return items, created, assigned, waiting


def _token(items) -> str:
    doc = [[i.round_code, i.stream, i.action, i.reason or "", i.kind or ""] for i in items]
    return hashlib.sha256(json.dumps(doc).encode()).hexdigest()[:16]


def preview_backfill(engine: Engine, actor: Principal) -> BackfillPlan:
    """Read-only: everything the backfill would do, done and rolled back."""
    authorize(actor, Capability.RUN_JOBS)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            items, created, assigned, waiting = _run(conn, actor.user_id)
        finally:
            trans.rollback()
    return BackfillPlan(tuple(items), tuple(created), assigned, waiting, _token(items))


def run_backfill(engine: Engine, actor: Principal, *, confirmation: str) -> BackfillPlan:
    """Publish and assign, one transaction per round (resumable, idempotent)."""
    authorize(actor, Capability.RUN_JOBS)
    plan = preview_backfill(engine, actor)
    if plan.token != confirmation:
        raise BackfillRefused("The data changed since the preview. Preview again.")
    published = []
    codes = {i.round_code for i in plan.items if i.action == "publish"}
    with read_only(engine) as conn:
        todo = [r.id for r in _candidates(conn) if r.code in codes]  # deadline order
    for rid in todo:
        with transaction(engine) as conn:
            r = rounds_repo.lock_round_for_change(conn, rid)  # round lock, then stream lock
            rows = _candidates(conn, rid)
            if not rows:
                continue
            row = rows[0]
            if row.sets or _exclusion(conn, row) is not None:
                continue  # published meanwhile (idempotent) or no longer eligible
            competition.publish_finalised(conn, rid, row.latest_version, actor=actor.user_id,
                                          championship_cause="backfill")  # fmt: skip
            published.append(r.code)
    created, assigned, waiting = [], 0, 0
    for stream in championships.STREAMS:
        with transaction(engine) as conn:
            out = championships.process_stream(conn, stream, actor=actor.user_id, cause="backfill")
            created += list(out.created)
            assigned += out.assigned
            waiting += len(out.waiting)
    with transaction(engine) as conn:
        ops.record_audit(
            conn, action="competition.backfill", target_type="competition", target_id="all",
            actor=actor.user_id, actor_role="operator",
            after={"published": published, "excluded": [i.round_code for i in plan.items
                                                        if i.action == "excluded"],
                   "token": plan.token},
        )  # fmt: skip
    return plan


# ------------------------------------------------------------------ status and integrity
@dataclass(frozen=True)
class StreamStatus:
    stream: str
    open: bool
    current: str | None
    status: str | None
    counted_rounds: int
    rounds_required: int
    championships: int
    waiting_rounds: tuple[str, ...]  # unassigned published rounds, deadline order
    unpublished_final: tuple[str, ...]  # final rounds without official results
    problems: tuple[str, ...]


def stream_status(engine: Engine, actor: Principal) -> tuple[StreamStatus, ...]:
    authorize(actor, Capability.RUN_JOBS)
    out = []
    with read_only(engine) as conn:
        for stream in championships.STREAMS:
            is_open = championships.stream_open(conn, stream)
            cur = conn.execute(
                text(
                    "SELECT display_name, status, counted_rounds, rounds_required, "
                    "(SELECT count(*) FROM app.championships x WHERE x.stream = :s) AS n "
                    "FROM app.championships WHERE stream = :s ORDER BY ordinal DESC LIMIT 1"
                ),
                {"s": stream},
            ).one_or_none()
            facts = championships.stream_rounds(conn, stream)
            assigned = set(
                conn.execute(
                    text(
                        "SELECT cr.round_id FROM app.championship_rounds cr "
                        "JOIN app.championships c ON c.id = cr.championship_id "
                        "WHERE c.stream = :s"
                    ),
                    {"s": stream},
                ).scalars()
            )
            waiting = tuple(r.code for r in facts if r.id not in assigned) if is_open else ()
            unpublished = tuple(r.code for r in facts if r.status == "final" and r.latest_set
                                is None)  # fmt: skip
            out.append(StreamStatus(
                stream, is_open, cur.display_name if cur else None, cur.status if cur else None,
                cur.counted_rounds if cur else 0, cur.rounds_required if cur else 10,
                cur.n if cur else 0, waiting, unpublished,
                tuple(championships.verify_stream(conn, stream)) if is_open else (),
            ))  # fmt: skip
    return tuple(out)


__all__ = [
    "BackfillItem",
    "BackfillPlan",
    "BackfillRefused",
    "StreamStatus",
    "preview_backfill",
    "run_backfill",
    "stream_status",
]
