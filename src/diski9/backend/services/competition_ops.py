"""Operator services for competitions (Phase 6C.5 Stages C and D): stream status,
the integrity check, the historical backfill and the audited repair.

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

**Repair** (Stage D, spec §11.6) rebuilds *derived* competition records from the
authoritative settlement and published weekly results, through the same services:
it publishes a re-finalised round's missing official results
(``publish_finalised``) and re-runs championship processing for every
championship of the stream (``process_stream`` with cause ``repair``), which
applies outstanding role changes, assigns rounds that can be assigned and writes a
new version only where the standings, status or counter differ. It never edits
history, never moves a membership, never sets points or winners by hand and never
touches settlement or football results. A stream with a *material* finding
(ambiguous or non-authoritative data) is refused and reported for separate
investigation. Safeguards: a read-only preview (work rolled back), an operator
with a password check (S-07) re-entered within 15 minutes for the write, a
reason, the preview's confirmation token (refused if anything changed), one
transaction per round then per stream (round lock, then stream lock), idempotent,
audited.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import Engine, text

from ...challenge import scoring
from ..auth.permissions import Capability, Principal, RecentAuthenticationRequired, authorize
from ..db import read_only, transaction
from ..repositories import ops
from ..repositories import rounds as rounds_repo
from . import championships, competition
from .common import ServiceError


class BackfillRefused(ServiceError):
    pass


class RepairRefused(ServiceError):
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
        created += [f"{name} ({stream})" for name in out.created]
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
            created += [f"{name} ({stream})" for name in out.created]
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
    waiting_rounds: tuple[str, ...]  # legitimately waiting (an earlier round holds the slot)
    unpublished_final: tuple[str, ...]  # final rounds without official results
    problems: tuple[str, ...]  # repairable and material findings
    repairable: tuple[str, ...] = ()
    material: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()  # legitimate states: review, pending assignment, D-30a ...
    not_yet_assigned: tuple[str, ...] = ()  # assignable but never processed (e.g. upgrade)


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
            unpublished = tuple(r.code for r in facts if r.status == "final" and r.latest_set
                                is None)  # fmt: skip
            ins = championships.inspect_stream(conn, stream) if is_open else None
            waiting = ins.waiting if ins else ()
            out.append(StreamStatus(
                stream, is_open, cur.display_name if cur else None, cur.status if cur else None,
                cur.counted_rounds if cur else 0, cur.rounds_required if cur else 10,
                cur.n if cur else 0, waiting, unpublished,
                tuple(str(f) for f in ins.findings) if ins else (),
                tuple(str(f) for f in ins.repairable) if ins else (),
                tuple(str(f) for f in ins.material) if ins else (),
                tuple(f"[{n.kind}] {n}" for n in ins.notes if n.kind != "pending_assignment")
                if ins else (),
                ins.assignable if ins else (),
            ))  # fmt: skip
    return tuple(out)


# ------------------------------------------------------------------ repair (Stage D)
@dataclass(frozen=True)
class ChampionshipChange:
    stream: str
    name: str
    before: tuple  # (status, counted rounds, version, champion count) or None if new
    after: tuple
    standings_changed: bool
    winners_changed: bool
    note: str | None = None  # boundary implication / review / D-30a


@dataclass(frozen=True)
class RepairPlan:
    streams: tuple[str, ...]
    republish: tuple[str, ...]  # rounds whose missing official results are published
    changes: tuple[ChampionshipChange, ...]
    repairable: tuple[str, ...]  # findings before the repair
    unrepairable: tuple[str, ...]  # material findings: refused, investigate separately
    remaining: tuple[str, ...]  # findings that would remain after the repair
    token: str

    @property
    def material_change(self) -> bool:
        return bool(self.republish or self.changes)


def _state(conn, stream: str) -> dict:
    rows = conn.execute(
        text(
            "SELECT c.display_name, c.status, c.counted_rounds, c.current_version, "
            "c.boundary_fixed_at IS NOT NULL AS fixed, v.content_hash, v.champion_count, "
            "(SELECT array_agg(s.user_id ORDER BY s.user_id) FROM app.championship_standings s "
            " WHERE s.version_id = v.id AND s.rank = 1 AND s.points > 0) AS leaders "
            "FROM app.championships c LEFT JOIN app.championship_versions v "
            "ON v.championship_id = c.id AND v.version = c.current_version WHERE c.stream = :s"
        ),
        {"s": stream},
    ).all()
    return {r.display_name: r for r in rows}


def _repair_work(conn, actor_id, scope: tuple[str, ...], reason: str | None):
    """The repair in ``conn`` (the caller commits or rolls back, or uses
    per-round transactions via ``run_repair``). Returns the plan's content."""
    republish, changes, repairable, unrepairable, remaining = [], [], [], [], []
    streams = []
    for stream in scope:
        if not championships.stream_open(conn, stream):
            continue
        ins = championships.inspect_stream(conn, stream)
        repairable += [f"{stream}: {f}" for f in ins.repairable]
        if ins.material:
            unrepairable += [f"{stream}: {f}" for f in ins.material]
            continue
        if not ins.findings:
            continue
        streams.append(stream)
        before = _state(conn, stream)
        for rid, version in ins.republish:
            code = conn.execute(text("SELECT code FROM app.rounds WHERE id = :r"),
                                {"r": rid}).scalar_one()  # fmt: skip
            competition.publish_finalised(conn, rid, version, actor=actor_id,
                                          championship_cause="repair")  # fmt: skip
            republish.append(code)
        championships.process_stream(conn, stream, actor=actor_id, cause="repair",
                                     refresh_all=True, reason=reason)  # fmt: skip
        after = _state(conn, stream)
        for name, a in after.items():
            b = before.get(name)
            if b is not None and (b.status, b.counted_rounds, b.current_version, b.fixed) == (
                a.status,
                a.counted_rounds,
                a.current_version,
                a.fixed,
            ):
                continue
            note = None
            if b is not None and not b.fixed and a.fixed:
                note = "boundary fixed (its successor has commenced)"
            elif a.status == "completed" and a.fixed and a.counted_rounds < 10:
                note = "completed with fewer than ten counted rounds (D-30a)"
            elif b is not None and b.status == "completed" and a.status == "in_progress":
                note = "returns to in progress (L-33)"
            changes.append(ChampionshipChange(
                stream, name,
                None if b is None else (b.status, b.counted_rounds, b.current_version,
                                        b.champion_count),
                (a.status, a.counted_rounds, a.current_version, a.champion_count),
                b is None or b.content_hash != a.content_hash,
                b is None or (b.leaders or []) != (a.leaders or []), note,
            ))  # fmt: skip
        remaining += [f"{stream}: {f}" for f in championships.inspect_stream(conn, stream).findings]
    return streams, republish, changes, repairable, unrepairable, remaining


def _repair_token(streams, republish, changes, repairable, unrepairable) -> str:
    doc = [list(streams), list(republish),
           [[c.stream, c.name, list(c.before or ()), list(c.after), c.standings_changed]
            for c in changes], list(repairable), list(unrepairable)]  # fmt: skip
    return hashlib.sha256(json.dumps(doc, default=str).encode()).hexdigest()[:16]


def _scope(stream: str | None) -> tuple[str, ...]:
    if stream is None:
        return championships.STREAMS
    if stream not in championships.STREAMS:
        raise RepairRefused(f"Unknown stream {stream!r}.")
    return (stream,)


def preview_repair(engine: Engine, actor: Principal, *, stream: str | None = None) -> RepairPlan:
    """Read-only: what ``run_repair`` would change, done and rolled back."""
    authorize(actor, Capability.RUN_JOBS)
    scope = _scope(stream)
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            streams, rep, changes, repairable, unrepairable, remaining = _repair_work(
                conn, actor.user_id, scope, None
            )
        finally:
            trans.rollback()
    return RepairPlan(tuple(streams), tuple(rep), tuple(changes), tuple(repairable),
                      tuple(unrepairable), tuple(remaining),
                      _repair_token(streams, rep, changes, repairable, unrepairable))  # fmt: skip


def _require_recent_password(actor: Principal) -> None:
    """The write needs the password re-entered within 15 minutes (as other
    sensitive operator changes), so an old preview cannot be confirmed later."""
    minutes = actor.extra.get("sensitive_recency_minutes", 15)
    if (
        actor.reauthenticated_at is None
        or actor.now is None
        or actor.now - actor.reauthenticated_at > timedelta(minutes=minutes)
    ):
        raise RecentAuthenticationRequired("reauthentication_required")


def run_repair(
    engine: Engine,
    actor: Principal,
    *,
    confirmation: str,
    reason: str,
    stream: str | None = None,
) -> RepairPlan:
    """Execute a previewed repair (token required; refused if anything changed)."""
    authorize(actor, Capability.RUN_JOBS)
    _require_recent_password(actor)
    if not reason or not reason.strip():
        raise RepairRefused("A reason is required for a competition repair.")
    plan = preview_repair(engine, actor, stream=stream)
    if plan.token != confirmation:
        raise RepairRefused("The data changed since the preview. Preview again.")
    if not plan.material_change:
        raise RepairRefused("Nothing to repair.")
    for stream_ in plan.streams:
        with read_only(engine) as conn:
            todo = championships.inspect_stream(conn, stream_).republish
        for rid, version in todo:  # one transaction per round: round lock, then stream lock
            with transaction(engine) as conn:
                rounds_repo.lock_round_for_change(conn, rid)
                # idempotent per settlement version (a retry publishes nothing twice)
                competition.publish_finalised(conn, rid, version, actor=actor.user_id,
                                              championship_cause="repair")  # fmt: skip
        with transaction(engine) as conn:
            championships.process_stream(conn, stream_, actor=actor.user_id, cause="repair",
                                         refresh_all=True, reason=reason.strip())  # fmt: skip
    with transaction(engine) as conn:
        ops.record_audit(
            conn, action="competition.repair", target_type="competition",
            target_id=stream or "all", actor=actor.user_id, actor_role="operator",
            reason=reason.strip(),
            after={"token": plan.token, "streams": list(plan.streams),
                   "republished": list(plan.republish),
                   "championships": [{"stream": c.stream, "name": c.name,
                                      "before": list(c.before or ()), "after": list(c.after),
                                      "standings_changed": c.standings_changed,
                                      "winners_changed": c.winners_changed}
                                     for c in plan.changes],
                   "unrepairable": list(plan.unrepairable)},
        )  # fmt: skip
    return plan


__all__ = [
    "BackfillItem",
    "BackfillPlan",
    "BackfillRefused",
    "ChampionshipChange",
    "RepairPlan",
    "RepairRefused",
    "StreamStatus",
    "preview_backfill",
    "preview_repair",
    "run_backfill",
    "run_repair",
    "stream_status",
]
