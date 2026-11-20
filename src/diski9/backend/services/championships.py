"""Championship lifecycle, membership and standings (Phase 6C.5 Stage C).

Specification: ``docs/architecture/phase6c5_design_specification.md`` §8, §9.3,
§11 and §23; decisions CH-01 to CH-12 and D-30a.

**Streams (CH-01).** ``development`` (every development round, hidden from public
users), ``beta`` and ``official`` never share championships, counters or points.
The official stream is processed only once the official series has been started
(``championship_series.started_at``, D-38 / D-29); nothing here starts it.

**Membership (CH-02).** Rounds of a stream are assigned strictly in deadline order.
A round joins the open championship as soon as its championship is certain:
normally at publication, while the championship's *commitment* (counted plus
pending members) is below ten. A pending member reserves a slot until its outcome
is known: ``practice`` (fixed at the lock) and ``void`` release it, ``counted``
keeps it. When the commitment is full but not complete, later rounds wait
(unassigned): their weekly results still publish, but their championship
association and contribution wait. When the open championship has ten counted
rounds, the next round creates and names the next championship and fixes the
previous one's boundary. Membership never changes after assignment (database
guard); settlement completion order never decides it.

**Naming (CH-03).** ``Championship MMM-YY`` from the SAST publication date of the
first associated round (whatever that round later becomes), with ``(2)``,
``(3)``, ... for a same-month collision. Set once at creation; immutable.

**Standings.** Recomputed from scratch with the unchanged
``challenge.scoring.aggregate_championship`` over the counted rounds' published
weekly results (participants are users). Every change is a new insert-only
version with materialised standings. Points are never adjusted incrementally.
The engine's weekly points are checked against the published score sets: any
difference is an integrity failure.

**Processing** (``process_stream``) is deterministic and idempotent. It runs under
a per-stream advisory lock (lock order: the caller's round row lock, then the
stream lock), inside the caller's transaction: publication and lock (6C.3), and
finalisation via ``competition.publish_finalised``.

**Stage C boundary.** Role changes of an already-determined member (a counted
round re-finalised as void, a void round restored to valid) are Stage D
(D-30a, L-32, L-33, CH-05). Stage C leaves them unapplied, and the read services
mark the championship *under review* (pending recalculation). A counted round
re-finalised as still valid is re-aggregated from its latest valid score set.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, func, insert, select, text, update

from ...challenge import scoring
from ..db.schema import (
    championship_rounds,
    championship_series,
    championship_standings,
    championship_versions,
    championships,
    domain_events,
    rounds,
)
from ..repositories import ops
from .common import ServiceError

SAST = ZoneInfo("Africa/Johannesburg")  # T-19: the application's display timezone
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # fmt: skip
STREAMS = ("development", "beta", "official")


class ChampionshipIntegrityError(ServiceError):
    """Published data disagree with a recomputation; nothing is written."""


# ------------------------------------------------------------------ naming (pure)
def base_name(published_at: datetime) -> tuple[date, str]:
    """(start date, ``Championship MMM-YY``) from a publication time, in SAST."""
    local = published_at.astimezone(SAST).date()
    return local, f"Championship {MONTHS[local.month - 1]}-{local.year % 100:02d}"


def unique_name(base: str, existing: Iterable[str]) -> str:
    """``base`` or ``base (n)``: the n-th championship of the stream with that base."""
    n = sum(1 for name in existing if name == base or name.startswith(base + " ("))
    return base if n == 0 else f"{base} ({n + 1})"


# ------------------------------------------------------------------ roles (pure)
def role_of(status: str, base_designation: str | None, latest_kind: str | None) -> str:
    """What a round currently is for championships, from authoritative state.

    * ``practice``: classified practice at the lock (D-28; never counts);
    * ``counted`` / ``void``: its latest official weekly publication is a
      competitive / void score set (a reopened round keeps its published state);
    * ``void`` also for a published round later postponed (never counts);
    * ``pending``: otherwise (open, locked or settling competitive, or final but
      not yet published).
    """
    if status == "postponed":
        return "void"
    if base_designation == "practice":
        return "practice"
    if status not in ("final", "settling"):  # official results exist only for these
        return "pending"
    if latest_kind == "championship":
        return "counted"
    if latest_kind == "void":
        return "void"
    if latest_kind == "practice":
        return "practice"
    return "pending"


# ------------------------------------------------------------------ assignment (pure)
@dataclass
class ChampModel:
    key: object  # championship id, or a placeholder for one created by the plan
    ordinal: int
    name: str
    start_date: date
    required: int
    roles: dict = field(default_factory=dict)  # round_id -> role
    fixed: bool = False
    new: bool = False

    @property
    def counted(self) -> int:
        return sum(1 for r in self.roles.values() if r == "counted")

    @property
    def commitment(self) -> int:
        return sum(1 for r in self.roles.values() if r in ("counted", "pending"))


@dataclass(frozen=True)
class RoundFact:
    round_id: UUID
    deadline_at: datetime
    published_at: datetime
    role: str


@dataclass(frozen=True)
class Plan:
    assignments: tuple  # (round_id, ChampModel)
    created: tuple  # ChampModel
    newly_fixed: tuple  # ChampModel whose boundary this plan fixes
    waiting: tuple  # round ids that cannot be assigned yet, in deadline order


def plan_assignments(facts: list[RoundFact], champs: list[ChampModel], required: int = 10) -> Plan:
    """Assign unassigned rounds in deadline order (``facts`` must be sorted). Pure:
    mutates only the models passed in (so the caller can apply them)."""
    member = {rid for c in champs for rid in c.roles}
    names = [c.name for c in champs]
    assignments, created, fixed = [], [], []
    waiting: list[UUID] = []
    for i, f in enumerate(facts):
        if f.round_id in member:
            continue
        open_ = champs[-1] if champs else None
        if open_ is None or open_.counted >= open_.required:
            if open_ is not None and not open_.fixed:
                open_.fixed = True
                fixed.append(open_)
            start, base = base_name(f.published_at)
            name = unique_name(base, names)
            names.append(name)
            c = ChampModel(("new", len(created)), (open_.ordinal + 1) if open_ else 1, name,
                           start, required, new=True)  # fmt: skip
            champs.append(c)
            created.append(c)
            target = c
        elif open_.commitment < open_.required:
            target = open_
        else:  # the last slot is reserved by an unresolved earlier round: wait
            waiting = [x.round_id for x in facts[i:] if x.round_id not in member]
            break
        target.roles[f.round_id] = f.role
        member.add(f.round_id)
        assignments.append((f.round_id, target))
    return Plan(tuple(assignments), tuple(created), tuple(fixed), tuple(waiting))


# ------------------------------------------------------------------ database access
_FACTS = """
SELECT r.id, r.code, r.deadline_at, r.published_at, r.status, r.is_development,
       s.code AS series,
       (SELECT d.designation FROM app.designations d
         WHERE d.round_id = r.id AND d.basis = 'deadline') AS base,
       ss.kind AS latest_kind, ss.id AS latest_set, ss.revision AS latest_revision,
       (SELECT x.id FROM app.score_sets x WHERE x.round_id = r.id AND x.kind = 'championship'
         ORDER BY x.revision DESC LIMIT 1) AS valid_set
  FROM app.rounds r
  JOIN app.championship_series s ON s.id = r.series_id
  LEFT JOIN LATERAL (SELECT id, kind, revision FROM app.score_sets
                      WHERE round_id = r.id ORDER BY revision DESC LIMIT 1) ss ON true
 WHERE r.published_at IS NOT NULL AND r.deadline_at IS NOT NULL AND r.status <> 'draft'
   AND {where}
 ORDER BY r.deadline_at, r.id
"""


def _stream_where(stream: str) -> tuple[str, dict]:
    if stream == "development":
        return "r.is_development", {}
    if stream in ("beta", "official"):
        return "NOT r.is_development AND s.code = :series", {"series": stream}
    raise ValueError(f"unknown stream {stream!r}")


def stream_rounds(conn: Connection, stream: str) -> list:
    where, params = _stream_where(stream)
    return conn.execute(text(_FACTS.format(where=where)), params).all()


def stream_of_round(conn: Connection, round_id: UUID) -> str:
    row = conn.execute(
        select(rounds.c.is_development, championship_series.c.code)
        .select_from(
            rounds.join(championship_series, championship_series.c.id == rounds.c.series_id)
        )
        .where(rounds.c.id == round_id)
    ).one()
    return "development" if row.is_development else row.code


def stream_open(conn: Connection, stream: str) -> bool:
    """The official stream exists only once the official series has started (D-38)."""
    if stream != "official":
        return True
    started = conn.execute(
        select(championship_series.c.started_at).where(championship_series.c.code == "official")
    ).scalar()
    return started is not None


def _lock_stream(conn: Connection, stream: str) -> None:
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"diski9:championship_stream:{stream}"},
    )


def _series_for(conn: Connection, stream: str) -> tuple[int, int]:
    """(series id, rounds per championship) used for new championships of a stream."""
    code = "beta" if stream == "development" else stream
    row = conn.execute(
        select(championship_series.c.id, championship_series.c.rounds_per_championship).where(
            championship_series.c.code == code
        )
    ).one()
    return row.id, row.rounds_per_championship


# ------------------------------------------------------------------ processing
@dataclass(frozen=True)
class Processed:
    stream: str
    skipped: str | None = None
    assigned: int = 0
    created: tuple[str, ...] = ()
    versions: int = 0
    waiting: tuple[UUID, ...] = ()
    deferred: tuple[UUID, ...] = ()  # determined members whose role change is Stage D


def on_round_event(
    conn: Connection,
    round_id: UUID,
    *,
    actor: UUID | None,
    cause: str = "round_published",
    cause_score_set_id: int | None = None,
) -> Processed:
    """Process the stream of ``round_id`` after its publication, lock or
    finalisation, in the caller's transaction (which holds the round row lock)."""
    stream = stream_of_round(conn, round_id)
    return process_stream(conn, stream, actor=actor, cause=cause, cause_round_id=round_id,
                          cause_score_set_id=cause_score_set_id)  # fmt: skip


def process_stream(
    conn: Connection,
    stream: str,
    *,
    actor: UUID | None = None,
    cause: str = "round_published",
    cause_round_id: UUID | None = None,
    cause_score_set_id: int | None = None,
) -> Processed:
    if not stream_open(conn, stream):
        return Processed(stream, skipped="the official series has not started (D-38)")
    _lock_stream(conn, stream)
    facts_rows = stream_rounds(conn, stream)
    fact = {r.id: r for r in facts_rows}
    rows = conn.execute(
        select(championships).where(championships.c.stream == stream)
        .order_by(championships.c.ordinal)
    ).all()  # fmt: skip
    members = conn.execute(
        select(championship_rounds).where(
            championship_rounds.c.championship_id.in_([c.id for c in rows])
        )
    ).all() if rows else []  # fmt: skip
    series_id, required = _series_for(conn, stream)
    models = []
    by_id = {}
    for c in rows:
        m = ChampModel(c.id, c.ordinal, c.display_name, c.start_date, c.rounds_required,
                       fixed=c.boundary_fixed_at is not None)  # fmt: skip
        models.append(m)
        by_id[c.id] = m
    touched: set = set()
    deferred = []
    # 1. outcomes of pending members (lock: practice; finalisation: counted / void)
    role_updates = []
    for mem in members:
        f = fact.get(mem.round_id)
        now_role = role_of(f.status, f.base, f.latest_kind) if f is not None else mem.role
        m = by_id[mem.championship_id]
        if mem.role == "pending" and now_role != "pending":
            role_updates.append((mem.round_id, now_role))
            m.roles[mem.round_id] = now_role
            touched.add(m.key)
        else:
            m.roles[mem.round_id] = mem.role
            if (
                mem.role in ("counted", "void")
                and now_role in ("counted", "void")
                and now_role != mem.role
            ):
                deferred.append(mem.round_id)  # Stage D (D-30a, L-32, L-33, CH-05)
        if mem.round_id == cause_round_id and mem.role == "counted":
            touched.add(m.key)  # a re-finalised counted round: re-aggregate
    # 2. assignment of unassigned rounds, in deadline order
    facts = [
        RoundFact(r.id, r.deadline_at, r.published_at, role_of(r.status, r.base, r.latest_kind))
        for r in facts_rows
    ]
    plan = plan_assignments(facts, models, required)
    now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
    for m in plan.newly_fixed:
        conn.execute(update(championships).where(championships.c.id == m.key)
                     .values(boundary_fixed_at=now))  # fmt: skip
    created_names = []
    for m in plan.created:
        m.key = conn.execute(
            insert(championships).values(
                stream=stream, series_id=series_id, ordinal=m.ordinal, start_date=m.start_date,
                display_name=m.name, rounds_required=m.required,
                boundary_fixed_at=now if m.fixed else None,
            ).returning(championships.c.id)
        ).scalar_one()  # fmt: skip
        created_names.append(m.name)
        first = next(rid for rid, target in plan.assignments if target is m)
        conn.execute(insert(domain_events).values(
            kind="championship_created", round_id=first,
            payload={"stream": stream, "name": m.name}))  # fmt: skip
    # a counted member always has a slot (CHECK); _refresh renumbers them by deadline
    for rid, role in role_updates:
        conn.execute(update(championship_rounds).where(championship_rounds.c.round_id == rid)
                     .values(role=role, slot=1 if role == "counted" else None))  # fmt: skip
    for rid, m in plan.assignments:
        role = m.roles[rid]
        conn.execute(insert(championship_rounds).values(
            round_id=rid, championship_id=m.key, role=role,
            slot=1 if role == "counted" else None))  # fmt: skip
        touched.add(m.key)
    versions = 0
    for m in models:
        if m.key in touched:
            versions += _refresh(conn, m, fact, cause=cause, cause_round_id=cause_round_id,
                                 cause_score_set_id=cause_score_set_id, actor=actor)  # fmt: skip
    return Processed(stream, None, len(plan.assignments), tuple(created_names), versions,
                     plan.waiting, tuple(deferred))  # fmt: skip


# ------------------------------------------------------------------ standings
def _round_results(conn: Connection, champ_id, sets: list[tuple[UUID, int]]):
    """RoundResults (participants = users) rebuilt from published score sets."""
    out, published, name_entry = [], {}, {}
    if not sets:
        return out, published, name_entry
    rows = conn.execute(
        text(
            "SELECT score_set_id, entry_id, user_id, gross, points, status "
            "FROM app.round_scores WHERE score_set_id = ANY(:s)"
        ),
        {"s": [s for _, s in sets]},
    ).all()
    by_set: dict[int, list] = {}
    for r in rows:
        by_set.setdefault(r.score_set_id, []).append(r)
    for round_id, set_id in sets:  # deadline order, so later entries win for names
        entries = []
        for r in by_set.get(set_id, []):
            refunded = r.status == "void_refunded"
            entries.append(scoring.EntryResult(
                participant_id=str(r.user_id), gross=r.gross,
                basis=(scoring.SettlementBasis.ALL_SELECTIONS_VOID if refunded
                       else scoring.SettlementBasis.SETTLED)))  # fmt: skip
            published[(str(round_id), str(r.user_id))] = r.points
            if not refunded:
                name_entry[r.user_id] = r.entry_id
        out.append(scoring.RoundResult(str(round_id), str(champ_id),
                                       scoring.RoundClassification.COMPETITIVE, tuple(entries),
                                       scoring.POINTS_150_75_V2.version, True))  # fmt: skip
    return out, published, name_entry


def compute_standings(conn: Connection, champ_id, counted: list[tuple[UUID, int]]):
    """Standings of a championship from its counted rounds' published score sets
    (``counted`` = [(round_id, score_set_id)] in deadline order)."""
    results, published, name_entry = _round_results(conn, champ_id, counted)
    table = scoring.aggregate_championship(str(champ_id), results)
    for rr in results:  # the engine must reproduce the published weekly points exactly
        for s in scoring.score_round(rr).scores:
            if published[(rr.round_id, s.participant_id)] != s.points:
                raise ChampionshipIntegrityError(
                    "Published weekly points differ from a recomputation; nothing was changed."
                )
    return table, name_entry


def content_hash(status: str, round_ids: list, scoring_version: str, standings) -> str:
    doc = {
        "status": status,
        "rounds": [str(r) for r in round_ids],
        "scoring": scoring_version,
        "standings": [[s.participant_id, s.rank, s.points, s.rounds_entered, s.recoveries,
                       s.qualifying_top10, s.display_order] for s in standings],
    }  # fmt: skip
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def _refresh(conn, m: ChampModel, fact, *, cause, cause_round_id, cause_score_set_id,
             actor) -> int:  # fmt: skip
    """Bring one championship's counter, slots, status and published standings up to
    date; insert a version only when something changed. Returns versions written."""
    counted = sorted((rid for rid, r in m.roles.items() if r == "counted"),
                     key=lambda rid: (fact[rid].deadline_at, str(rid)))  # fmt: skip
    sources = []
    for rid in counted:
        set_id = fact[rid].valid_set
        if set_id is None:
            raise ChampionshipIntegrityError("A counted round has no competitive score set.")
        sources.append((rid, set_id))
    for i, rid in enumerate(counted, start=1):
        conn.execute(update(championship_rounds).where(championship_rounds.c.round_id == rid)
                     .values(slot=i))  # fmt: skip
    # members that stopped counting never keep a slot (none in Stage C, kept for safety)
    conn.execute(
        update(championship_rounds)
        .where(championship_rounds.c.championship_id == m.key,
               championship_rounds.c.role != "counted", championship_rounds.c.slot.is_not(None))
        .values(slot=None)
    )  # fmt: skip
    n = len(counted)
    status = "upcoming" if n == 0 else ("completed" if n >= m.required else "in_progress")
    table, name_entry = compute_standings(conn, m.key, sources)
    digest = content_hash(status, counted, table.scoring_version, table.standings)
    cur = conn.execute(select(championships).where(championships.c.id == m.key)).one()
    last = None
    if cur.current_version is not None:
        last = conn.execute(
            select(championship_versions.c.content_hash).where(
                championship_versions.c.championship_id == m.key,
                championship_versions.c.version == cur.current_version,
            )
        ).scalar_one()
    values = {"counted_rounds": n, "status": status}
    if status == "completed" and cur.completed_at is None:
        values["completed_at"] = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
    if last == digest:
        conn.execute(update(championships).where(championships.c.id == m.key).values(**values))
        return 0
    champions = 0
    if status == "completed":
        champions = sum(1 for s in table.standings if s.rank == 1 and s.points > 0)
    version = (cur.current_version or 0) + 1
    kind = cause
    if cause in ("round_published", "backfill") and cur.current_version is not None \
            and cause_round_id is not None and cause_round_id in counted \
            and conn.execute(text("SELECT count(*) FROM app.score_sets WHERE round_id = :r"),
                             {"r": cause_round_id}).scalar_one() > 1:  # fmt: skip
        kind = "round_republished"
    if cur.current_version is None and n == 0:
        kind = "round_assigned"
    vid = conn.execute(
        insert(championship_versions).values(
            championship_id=m.key, version=version, cause=kind, cause_round_id=cause_round_id,
            cause_score_set_id=cause_score_set_id, status=status, counted_rounds=n,
            round_ids=counted, champion_count=champions, scoring_version=table.scoring_version,
            content_hash=digest, actor_user_id=actor,
        ).returning(championship_versions.c.id)
    ).scalar_one()  # fmt: skip
    if table.standings:
        conn.execute(insert(championship_standings), [
            {"version_id": vid, "user_id": UUID(s.participant_id), "rank": s.rank,
             "points": s.points, "rounds_played": s.rounds_entered, "recoveries": s.recoveries,
             "qualifying_top10": s.qualifying_top10, "display_order": s.display_order,
             "name_entry_id": name_entry[UUID(s.participant_id)]}
            for s in table.standings
        ])  # fmt: skip
    values["current_version"] = version
    conn.execute(update(championships).where(championships.c.id == m.key).values(**values))
    ops.record_audit(
        conn, action="championship.version", target_type="championship", target_id=str(m.key),
        actor=actor, actor_role="system" if actor is None else "operator",
        after={"version": version, "cause": kind, "status": status, "counted_rounds": n,
               "content_hash": digest, "champions": champions},
    )  # fmt: skip
    if status == "completed" and cur.status != "completed":
        conn.execute(insert(domain_events).values(
            kind="championship_completed", round_id=cause_round_id,
            payload={"name": m.name, "version": version, "champions": champions}))  # fmt: skip
    return 1


# ------------------------------------------------------------------ integrity (Stage C)
def verify_stream(conn: Connection, stream: str) -> list[str]:
    """Read-only integrity checks of a stream's championships; returns the problems
    found (empty when consistent). Repair is Stage D."""
    problems = []
    facts_rows = stream_rounds(conn, stream)
    fact = {r.id: r for r in facts_rows}
    champs = conn.execute(
        select(championships).where(championships.c.stream == stream)
        .order_by(championships.c.ordinal)
    ).all()  # fmt: skip
    for c in champs:
        mem = conn.execute(select(championship_rounds).where(
            championship_rounds.c.championship_id == c.id)).all()  # fmt: skip
        for x in mem:
            if x.round_id not in fact:
                problems.append(f"{c.display_name}: a member round is not in the {stream} stream")
                continue
            latest = fact[x.round_id].latest_kind
            if (x.role == "counted" and latest not in (None, "championship")) or (
                x.role == "void" and latest == "championship"
            ):
                problems.append(f"{c.display_name}: round {fact[x.round_id].code} was "
                                "re-finalised with a different outcome; awaiting Stage D "
                                "recalculation")  # fmt: skip
        counted = sorted((x for x in mem if x.role == "counted"),
                         key=lambda x: (fact[x.round_id].deadline_at, str(x.round_id))
                         if x.round_id in fact else (datetime.max, ""))  # fmt: skip
        if len(counted) != c.counted_rounds:
            problems.append(f"{c.display_name}: counter {c.counted_rounds} != {len(counted)} "
                            "counted rounds")  # fmt: skip
        if len(counted) > c.rounds_required:
            problems.append(f"{c.display_name}: more than {c.rounds_required} counted rounds")
        if [x.slot for x in counted] != list(range(1, len(counted) + 1)):
            problems.append(f"{c.display_name}: counted slots are not 1..n in deadline order")
        expected = (
            "upcoming"
            if not counted
            else "completed"
            if len(counted) >= c.rounds_required
            else "in_progress"
        )
        if c.status != expected:
            problems.append(f"{c.display_name}: status {c.status} != {expected}")
        sources = []
        for x in counted:
            f = fact.get(x.round_id)
            if f is None or f.valid_set is None:
                problems.append(f"{c.display_name}: counted round without a competitive score set")
                continue
            sources.append((x.round_id, f.valid_set))
        if c.current_version is None:
            problems.append(f"{c.display_name}: no published version")
            continue
        v = conn.execute(select(championship_versions).where(
            championship_versions.c.championship_id == c.id,
            championship_versions.c.version == c.current_version)).one()  # fmt: skip
        try:
            table, _ = compute_standings(conn, c.id, sources)
        except (ChampionshipIntegrityError, scoring.ScoringInputError) as exc:
            problems.append(f"{c.display_name}: {exc}")
            continue
        if content_hash(expected, [x.round_id for x in counted], table.scoring_version,
                        table.standings) != v.content_hash:  # fmt: skip
            problems.append(
                f"{c.display_name}: published standings differ from a recomputation"
                " (a re-finalised round may be awaiting Stage D recalculation)"
            )
        n_rows = conn.execute(select(func.count()).select_from(championship_standings).where(
            championship_standings.c.version_id == v.id)).scalar_one()  # fmt: skip
        if n_rows != len(table.standings):
            problems.append(f"{c.display_name}: {n_rows} standings rows, expected "
                            f"{len(table.standings)}")  # fmt: skip
    for later, earlier in zip(champs[1:], champs, strict=False):
        if earlier.boundary_fixed_at is None:
            problems.append(f"{earlier.display_name}: boundary not fixed although "
                            f"{later.display_name} exists")  # fmt: skip
    if stream != "development":
        dev = conn.execute(text(
            "SELECT count(*) FROM app.championship_rounds cr JOIN app.championships c "
            "ON c.id = cr.championship_id JOIN app.rounds r ON r.id = cr.round_id "
            "WHERE c.stream = :s AND r.is_development"), {"s": stream}).scalar_one()  # fmt: skip
        if dev:
            problems.append(f"{dev} development round(s) inside the {stream} stream")
    return problems


__all__ = [
    "ChampionshipIntegrityError",
    "Processed",
    "base_name",
    "on_round_event",
    "plan_assignments",
    "process_stream",
    "role_of",
    "unique_name",
    "verify_stream",
]
