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

**Corrections (Stage D: L-32, L-33, L-34 / D-30a, CH-05).** A determined
member's role follows the round's latest official publication, applied in
``resolve_roles`` (pure) under the stream lock:

* counted -> void (a re-finalisation invalidates it): the contribution is removed
  and the counter falls. An active championship continues (L-32); a completed one
  whose successor has not commenced returns to ``in_progress`` (L-33); one whose
  boundary is fixed stays ``completed`` with fewer rounds (L-34 / D-30a).
* void or ``not_counted`` -> valid (restored, CH-05 / spec §23.5): it counts only
  while ``counted + pending < rounds_required``; otherwise it is ``not_counted``.
  Restored and ``not_counted`` members are reconsidered in deadline order before
  any new round is assigned, so freed capacity goes to the earliest restored round
  and never to whichever transaction commits first.
* ``not_counted`` -> void: stays out.
* A reopened round keeps its last published role (its latest score set is
  unchanged until re-finalisation), so reopening never changes standings.

Membership never moves; capacity reserved by pending members is never taken.
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


# ------------------------------------------------------------------ role resolution (pure)
@dataclass(frozen=True)
class RoleChange:
    round_id: UUID
    before: str
    after: str

    @property
    def kind(self) -> str:
        """determined | invalidated | restored | not_counted | excluded."""
        if self.before == "pending":
            return "determined"
        if self.before == "counted":
            return "invalidated"
        if self.after == "counted":
            return "restored"
        if self.after == "not_counted":
            return "not_counted"
        return "excluded"  # not_counted -> void


def resolve_roles(m: ChampModel, outcome: dict, order: dict) -> list[RoleChange]:
    """Apply authoritative outcomes to one championship's members (mutates
    ``m.roles``; returns the changes). ``outcome[round_id]`` is ``role_of(...)``:
    pending | practice | counted (valid) | void; ``order[round_id]`` sorts by
    deadline. Capacity (CH-05, spec §23.5): a restored or ``not_counted`` member
    counts only while counted + pending < required, earliest deadline first; a
    pending member already holds its reserved slot."""
    before = dict(m.roles)
    candidates = []
    for rid, role in before.items():
        out = outcome.get(rid, role)
        if role == "pending":
            if out in ("practice", "void"):
                m.roles[rid] = out
            elif out == "counted":
                m.roles[rid] = "counted"  # its reserved slot
        elif role == "counted":
            if out == "void":
                m.roles[rid] = "void"  # L-32 / L-33 / L-34
        elif role in ("void", "not_counted"):
            if out == "counted":
                candidates.append(rid)
            elif role == "not_counted" and out == "void":
                m.roles[rid] = "void"
        # practice is fixed at the lock and never changes
    if m.counted > m.required:
        raise ChampionshipIntegrityError(
            f"{m.name}: more than {m.required} counted rounds; nothing was changed."
        )
    for rid in sorted(candidates, key=lambda r: order[r]):
        m.roles[rid] = "not_counted"
        if m.commitment < m.required:
            m.roles[rid] = "counted"
    ordered = sorted(before, key=lambda r: order[r])
    return [RoleChange(r, before[r], m.roles[r]) for r in ordered if m.roles[r] != before[r]]


def expected_status(counted: int, required: int, fixed: bool, started: bool) -> str:
    """A fixed boundary means the successor has commenced: the championship stays
    completed, exceptionally with fewer rounds (L-34 / D-30a). Otherwise it is
    completed at ``required`` counted rounds and returns to in progress below it
    (L-33). ``started``: it has had a counted round, so it never returns to
    upcoming even if every counted round is later invalidated."""
    if fixed or counted >= required:
        return "completed"
    return "in_progress" if counted > 0 or started else "upcoming"


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
    changes: tuple[RoleChange, ...] = ()  # role changes applied (Stage D included)


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


def _models(conn: Connection, stream: str):
    rows = conn.execute(
        select(championships).where(championships.c.stream == stream)
        .order_by(championships.c.ordinal)
    ).all()  # fmt: skip
    members = conn.execute(
        select(championship_rounds).where(
            championship_rounds.c.championship_id.in_([c.id for c in rows])
        )
    ).all() if rows else []  # fmt: skip
    models, by_id = [], {}
    for c in rows:
        m = ChampModel(c.id, c.ordinal, c.display_name, c.start_date, c.rounds_required,
                       fixed=c.boundary_fixed_at is not None)  # fmt: skip
        models.append(m)
        by_id[c.id] = m
    for mem in members:
        by_id[mem.championship_id].roles[mem.round_id] = mem.role
    return rows, models, by_id


def _outcomes(facts_rows) -> tuple[dict, dict]:
    outcome = {r.id: role_of(r.status, r.base, r.latest_kind) for r in facts_rows}
    order = {r.id: (r.deadline_at, str(r.id)) for r in facts_rows}
    return outcome, order


def process_stream(
    conn: Connection,
    stream: str,
    *,
    actor: UUID | None = None,
    cause: str = "round_published",
    cause_round_id: UUID | None = None,
    cause_score_set_id: int | None = None,
    refresh_all: bool = False,
    reason: str | None = None,
) -> Processed:
    """Apply role changes, assign waiting rounds and refresh every affected
    championship (``refresh_all``: every championship of the stream, for repair)."""
    if not stream_open(conn, stream):
        return Processed(stream, skipped="the official series has not started (D-38)")
    _lock_stream(conn, stream)
    facts_rows = stream_rounds(conn, stream)
    fact = {r.id: r for r in facts_rows}
    _rows, models, _by_id = _models(conn, stream)
    series_id, required = _series_for(conn, stream)
    outcome, order = _outcomes(facts_rows)
    for m in models:  # members outside the stream are an integrity failure (verify)
        for rid in m.roles:
            if rid not in fact:
                raise ChampionshipIntegrityError(
                    f"{m.name}: a member round is not in the {stream} stream; nothing was changed."
                )
    touched: set = {m.key for m in models} if refresh_all else set()
    # 1. role changes of members (lock; first publication; re-finalisation: Stage D),
    #    restored rounds before any new assignment (spec §23.5 rule 4)
    changes: dict = {}
    all_changes: list[RoleChange] = []
    for m in models:
        ch_ = resolve_roles(m, outcome, order)
        if ch_:
            changes[m.key] = ch_
            all_changes += ch_
            touched.add(m.key)
        if cause_round_id in m.roles and m.roles[cause_round_id] == "counted":
            touched.add(m.key)  # a re-finalised counted round: re-aggregate
    # 2. assignment of unassigned rounds, in deadline order
    facts = [RoundFact(r.id, r.deadline_at, r.published_at, outcome[r.id]) for r in facts_rows]
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
    # a counted member always has a slot (CHECK); _refresh renumbers them by deadline.
    # Roles that stop counting drop their slot first (two statements keep the CHECK).
    for c in all_changes:
        if c.after != "counted":
            conn.execute(update(championship_rounds)
                         .where(championship_rounds.c.round_id == c.round_id)
                         .values(role=c.after, slot=None))  # fmt: skip
    for c in all_changes:
        if c.after == "counted":
            conn.execute(update(championship_rounds)
                         .where(championship_rounds.c.round_id == c.round_id)
                         .values(role="counted", slot=1))  # fmt: skip
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
                                 cause_score_set_id=cause_score_set_id, actor=actor,
                                 changes=changes.get(m.key, []), reason=reason)  # fmt: skip
    return Processed(stream, None, len(plan.assignments), tuple(created_names), versions,
                     plan.waiting, tuple(all_changes))  # fmt: skip


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


def _started(conn, champ_id) -> bool:
    """It has published a counted round (same definition in processing and
    inspection, so repair and verify agree)."""
    return conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM app.championship_versions WHERE championship_id = :c "
        "AND counted_rounds > 0)"), {"c": champ_id}).scalar_one()  # fmt: skip


CORRECTION_CAUSES = ("round_republished", "round_invalidated", "round_restored", "repair")


def _cause_and_reason(cause, changes, fact, *, was, status, n, required, fixed):
    """Version cause and a plain-language reason for role changes (audited)."""
    parts = []
    kinds = {c.kind for c in changes}
    for c in changes:
        code = fact[c.round_id].code
        if c.kind == "invalidated":
            parts.append(f"Round {code} was invalidated; its contribution was removed")
        elif c.kind == "restored":
            parts.append(f"Round {code} was restored and counts toward the championship")
        elif c.kind == "not_counted":
            parts.append(f"Round {code} was restored after the championship already had "
                         f"{required} counted rounds (or reserved slots), so its points do "
                         "not count toward the championship")  # fmt: skip
        elif c.kind == "excluded":
            parts.append(f"Round {code} was invalidated again")
    if was == "completed" and status == "in_progress":
        parts.append(f"the championship returned to in progress with {n} of {required} "
                     "counted rounds (L-33)")  # fmt: skip
    elif fixed and status == "completed" and n < required and "invalidated" in kinds:
        parts.append(f"the next championship had already commenced, so this championship "
                     f"stays completed with {n} counted rounds (D-30a)")  # fmt: skip
    if cause in ("repair", "backfill"):
        kind = cause
    elif "invalidated" in kinds:
        kind = "round_invalidated"
    elif kinds & {"restored", "not_counted", "excluded"}:
        kind = "round_restored"
    else:
        kind = cause
    return kind, ("; ".join(parts) + ".") if parts else None


def _refresh(conn, m: ChampModel, fact, *, cause, cause_round_id, cause_score_set_id,
             actor, changes=(), reason=None) -> int:  # fmt: skip
    """Bring one championship's counter, slots, status and published standings up to
    date. A version is inserted when the standings, status or counter change, or a
    member's role changed (every role change is versioned, spec §23.5). Returns the
    number of versions written."""
    counted = sorted((rid for rid, r in m.roles.items() if r == "counted"),
                     key=lambda rid: (fact[rid].deadline_at, str(rid)))  # fmt: skip
    sources = []
    for rid in counted:
        set_id = fact[rid].valid_set
        if set_id is None:
            raise ChampionshipIntegrityError("A counted round has no competitive score set.")
        sources.append((rid, set_id))
    # members that stopped counting never keep a slot; then counted slots are 1..n
    conn.execute(
        update(championship_rounds)
        .where(championship_rounds.c.championship_id == m.key,
               championship_rounds.c.role != "counted", championship_rounds.c.slot.is_not(None))
        .values(slot=None)
    )  # fmt: skip
    for i, rid in enumerate(counted, start=1):
        conn.execute(update(championship_rounds).where(championship_rounds.c.round_id == rid)
                     .values(slot=i))  # fmt: skip
    n = len(counted)
    cur = conn.execute(select(championships).where(championships.c.id == m.key)).one()
    status = expected_status(n, m.required, m.fixed, _started(conn, m.key))
    table, name_entry = compute_standings(conn, m.key, sources)
    digest = content_hash(status, counted, table.scoring_version, table.standings)
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
    # role changes from corrections are always versioned (spec §23.5 rule 5); a
    # pending member's first outcome is versioned only if it changes the standings
    forced = any(c.kind != "determined" for c in changes)
    if last == digest and not forced:  # (repair too: a version only for a difference)
        conn.execute(update(championships).where(championships.c.id == m.key).values(**values))
        return 0
    champions = 0
    if status == "completed":
        champions = sum(1 for s in table.standings if s.rank == 1 and s.points > 0)
    version = (cur.current_version or 0) + 1
    kind, why = _cause_and_reason(cause, changes, fact, was=cur.status, status=status, n=n,
                                  required=m.required, fixed=m.fixed)  # fmt: skip
    if kind in ("round_published", "backfill") and cur.current_version is not None \
            and cause_round_id is not None and cause_round_id in counted \
            and conn.execute(text("SELECT count(*) FROM app.score_sets WHERE round_id = :r"),
                             {"r": cause_round_id}).scalar_one() > 1:  # fmt: skip
        kind = "round_republished"
    if cur.current_version is None and n == 0 and not forced:
        kind = "round_assigned"
    text_reason = "; ".join(x for x in (reason, why) if x) or None
    vid = conn.execute(
        insert(championship_versions).values(
            championship_id=m.key, version=version, cause=kind, cause_round_id=cause_round_id,
            cause_score_set_id=cause_score_set_id, status=status, counted_rounds=n,
            round_ids=counted, champion_count=champions, scoring_version=table.scoring_version,
            content_hash=digest, actor_user_id=actor, reason=text_reason,
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
    corrected = cur.completed_at is not None and kind in CORRECTION_CAUSES
    if corrected and not cur.corrected_after_completion:
        values["corrected_after_completion"] = True
    conn.execute(update(championships).where(championships.c.id == m.key).values(**values))
    ops.record_audit(
        conn, action="championship.version", target_type="championship", target_id=str(m.key),
        actor=actor, actor_role="system" if actor is None else "operator",
        before={"version": cur.current_version, "status": cur.status,
                "counted_rounds": cur.counted_rounds},
        after={"version": version, "cause": kind, "status": status, "counted_rounds": n,
               "content_hash": digest, "champions": champions, "reason": text_reason,
               "role_changes": [{"round": fact[c.round_id].code, "from": c.before,
                                 "to": c.after} for c in changes]},
    )  # fmt: skip
    if status == "completed" and cur.status != "completed":
        conn.execute(insert(domain_events).values(
            kind="championship_completed", round_id=cause_round_id,
            payload={"name": m.name, "version": version, "champions": champions}))  # fmt: skip
    elif cur.status == "completed" and status != "completed":
        conn.execute(insert(domain_events).values(
            kind="championship_reopened", round_id=cause_round_id,
            payload={"name": m.name, "version": version, "counted_rounds": n}))  # fmt: skip
    elif corrected and status == "completed":
        conn.execute(insert(domain_events).values(
            kind="championship_corrected", round_id=cause_round_id,
            payload={"name": m.name, "version": version, "counted_rounds": n,
                     "champions": champions}))  # fmt: skip
    return 1


# ------------------------------------------------------------------ integrity
@dataclass(frozen=True)
class Finding:
    """An integrity finding. ``category``:

    * ``repairable``: derived competition data disagree with authoritative
      settlement or published weekly results; ``competition repair`` can rebuild
      them (it never rewrites membership or settlement);
    * ``material``: needs separate, authorised investigation (repair refuses the
      stream).
    """

    category: str
    subject: str  # championship display name or round code
    message: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.message}"


@dataclass(frozen=True)
class Note:
    """A legitimate state that is not a fault: ``under_review``,
    ``pending_assignment``, ``historical_correction`` (D-30a), ``not_counted``
    (CH-05), ``reopened_after_completion`` (L-33), ``backfill_needed``."""

    kind: str
    subject: str
    message: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.message}"


@dataclass(frozen=True)
class Inspection:
    stream: str
    findings: tuple[Finding, ...]
    notes: tuple[Note, ...]
    republish: tuple[tuple[UUID, int], ...]  # (round, final settlement version) to publish

    @property
    def material(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.category == "material")

    @property
    def repairable(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.category == "repairable")


_FINAL_VERSIONS = """
SELECT r.id, r.code, r.status,
       (SELECT v.id FROM app.settlement_versions v WHERE v.round_id = r.id
         ORDER BY v.version DESC LIMIT 1) AS latest_version,
       (SELECT v.kind FROM app.settlement_versions v WHERE v.round_id = r.id
         ORDER BY v.version DESC LIMIT 1) AS latest_version_kind,
       ss.id AS set_id, ss.settlement_version_id AS set_version, ss.kind AS set_kind,
       (SELECT v.kind FROM app.settlement_versions v WHERE v.id = ss.settlement_version_id)
         AS set_version_kind
  FROM app.rounds r
  LEFT JOIN LATERAL (SELECT id, settlement_version_id, kind FROM app.score_sets
                      WHERE round_id = r.id ORDER BY revision DESC LIMIT 1) ss ON true
 WHERE r.id = ANY(:ids)
"""


def _weekly_findings(conn: Connection, facts_rows, findings, notes, republish) -> None:
    """Published weekly results against authoritative settlement (spec §11.6 step 1)."""
    from . import competition

    ids = [r.id for r in facts_rows if r.status in ("final", "settling")]
    if not ids:
        return
    for r in conn.execute(text(_FINAL_VERSIONS), {"ids": ids}).all():
        if r.status == "settling":
            if r.set_id is not None:
                notes.append(
                    Note(
                        "under_review",
                        f"Round {r.code}",
                        "reopened: the last published results stay current until re-finalisation",
                    )
                )
            continue
        if r.set_id is None:
            notes.append(
                Note(
                    "backfill_needed",
                    f"Round {r.code}",
                    "final without official results (competition backfill)",
                )
            )
            continue
        if r.set_version_kind != "final":
            findings.append(Finding("material", f"Round {r.code}",
                                    "official results do not reference a final settlement "
                                    "version"))  # fmt: skip
            continue
        if r.latest_version_kind == "final" and r.set_version != r.latest_version:
            findings.append(Finding("repairable", f"Round {r.code}",
                                    "re-finalised, but the latest final settlement version "
                                    "has no official results"))  # fmt: skip
            republish.append((r.id, r.latest_version))
            continue
        # re-score the published settlement and compare row by row
        d = competition.current_designation_row(conn, r.id)
        scoring_version = conn.execute(select(rounds.c.scoring_version)
                                       .where(rounds.c.id == r.id)).scalar_one()  # fmt: skip
        try:
            records = competition.locked_records(conn, r.id)
            rr = competition.round_result(r.id, d.designation, scoring_version, records)
            score = scoring.score_round(rr, scoring.get_scoring_config(scoring_version))
        except (competition.PublicationRefused, scoring.ScoringInputError) as exc:
            findings.append(Finding("material", f"Round {r.code}",
                                    f"settlement cannot be re-scored: {exc}"))  # fmt: skip
            continue
        expected = sorted(
            (s.participant_id, str(s.gross), s.rank, s.points, s.recovered, s.qualifying_top10,
             competition.score_status(score.classification, s)) for s in score.scores
        )  # fmt: skip
        actual = sorted(
            (str(x.entry_id), str(x.gross), x.rank, x.points, x.recovered, x.qualifying_top10,
             x.status)
            for x in conn.execute(text(
                "SELECT entry_id, gross, rank, points, recovered, qualifying_top10, status "
                "FROM app.round_scores WHERE score_set_id = :s"), {"s": r.set_id})
        )  # fmt: skip
        if competition.KIND_OF[score.classification] != r.set_kind or expected != actual:
            findings.append(Finding("material", f"Round {r.code}",
                                    "published weekly results differ from a re-scoring of "
                                    "the authoritative settlement"))  # fmt: skip


def inspect_stream(conn: Connection, stream: str) -> Inspection:
    """Read-only integrity inspection of a stream: weekly results, membership,
    roles, counters, slots, status, standings, boundaries and isolation. Never
    writes. Legitimate review, pending assignment, D-30a and ``not_counted``
    states are notes, not findings."""
    findings: list[Finding] = []
    notes: list[Note] = []
    republish: list[tuple[UUID, int]] = []
    facts_rows = stream_rounds(conn, stream)
    fact = {r.id: r for r in facts_rows}
    _weekly_findings(conn, facts_rows, findings, notes, republish)
    champs = conn.execute(
        select(championships).where(championships.c.stream == stream)
        .order_by(championships.c.ordinal)
    ).all()  # fmt: skip
    rows, models, by_id = _models(conn, stream)
    outcome, order = _outcomes(facts_rows)
    for c in champs:
        m = by_id[c.id]
        mem = conn.execute(select(championship_rounds).where(
            championship_rounds.c.championship_id == c.id)).all()  # fmt: skip
        outside = [x for x in mem if x.round_id not in fact]
        if outside:
            findings.append(Finding("material", c.display_name,
                                    f"{len(outside)} member round(s) are not in the {stream} "
                                    "stream"))  # fmt: skip
            continue
        first = min(mem, key=lambda x: (x.assigned_at, order[x.round_id]), default=None)
        if first is not None:
            start, base = base_name(fact[first.round_id].published_at)
            if c.start_date != start or not (
                c.display_name == base or c.display_name.startswith(base + " (")
            ):
                findings.append(Finding("material", c.display_name,
                                        "name or start date does not match its first "
                                        "associated round"))  # fmt: skip
        stored_counted = [x for x in mem if x.role == "counted"]
        if len(stored_counted) > c.rounds_required:
            findings.append(
                Finding("material", c.display_name, f"more than {c.rounds_required} counted rounds")
            )
            continue
        for x in stored_counted:
            if fact[x.round_id].valid_set is None:
                findings.append(Finding("material", c.display_name,
                                        f"counted round {fact[x.round_id].code} has no "
                                        "competitive score set"))  # fmt: skip
        if any(f.subject == c.display_name and f.category == "material" for f in findings):
            continue
        # roles against the authoritative outcomes (what processing would apply)
        probe = ChampModel(c.id, c.ordinal, c.display_name, c.start_date, c.rounds_required,
                           dict(m.roles), c.boundary_fixed_at is not None)  # fmt: skip
        try:
            role_changes = resolve_roles(probe, outcome, order)
        except ChampionshipIntegrityError as exc:
            findings.append(Finding("material", c.display_name, str(exc)))
            continue
        for rc in role_changes:
            if rc.kind == "determined":
                findings.append(Finding("repairable", c.display_name,
                                        f"round {fact[rc.round_id].code} has an outcome "
                                        f"({rc.after}) not yet applied"))  # fmt: skip
            else:
                findings.append(Finding("repairable", c.display_name,
                                        f"round {fact[rc.round_id].code} is {rc.before} but "
                                        f"its authoritative outcome makes it {rc.after}; "
                                        "recalculation needed"))  # fmt: skip
        for x in mem:
            if x.role == "not_counted":
                notes.append(Note("not_counted", c.display_name,
                                  f"round {fact[x.round_id].code} was restored without "
                                  "championship points (capacity, CH-05)"))  # fmt: skip
        counted = sorted(stored_counted, key=lambda x: order[x.round_id])
        if len(counted) != c.counted_rounds:
            findings.append(Finding("repairable", c.display_name,
                                    f"counter {c.counted_rounds} != {len(counted)} counted "
                                    "rounds"))  # fmt: skip
        if [x.slot for x in counted] != list(range(1, len(counted) + 1)):
            findings.append(
                Finding(
                    "repairable", c.display_name, "counted slots are not 1..n in deadline order"
                )
            )
        started = _started(conn, c.id)
        expected = expected_status(len(counted), c.rounds_required,
                                   c.boundary_fixed_at is not None, started)  # fmt: skip
        if c.status != expected:
            findings.append(Finding("repairable", c.display_name,
                                    f"status {c.status} != {expected}"))  # fmt: skip
        if expected == "completed" and len(counted) < c.rounds_required:
            notes.append(Note("historical_correction", c.display_name,
                              f"completed with {len(counted)} of {c.rounds_required} counted "
                              "rounds after a correction (D-30a)"))  # fmt: skip
        if c.status == "in_progress" and c.completed_at is not None:
            notes.append(Note("reopened_after_completion", c.display_name,
                              "a counted round was invalidated after completion; it needs "
                              "more valid rounds (L-33)"))  # fmt: skip
        if c.current_version is None:
            findings.append(Finding("repairable", c.display_name, "no published version"))
            continue
        v = conn.execute(select(championship_versions).where(
            championship_versions.c.championship_id == c.id,
            championship_versions.c.version == c.current_version)).one()  # fmt: skip
        sources = [(x.round_id, fact[x.round_id].valid_set) for x in counted]
        try:
            table, _ = compute_standings(conn, c.id, sources)
        except (ChampionshipIntegrityError, scoring.ScoringInputError) as exc:
            findings.append(Finding("material", c.display_name, str(exc)))
            continue
        if content_hash(expected, [x.round_id for x in counted], table.scoring_version,
                        table.standings) != v.content_hash:  # fmt: skip
            findings.append(
                Finding(
                    "repairable", c.display_name, "published standings differ from a recomputation"
                )
            )
        n_rows = conn.execute(select(func.count()).select_from(championship_standings).where(
            championship_standings.c.version_id == v.id)).scalar_one()  # fmt: skip
        if n_rows != len(table.standings):
            findings.append(Finding("repairable", c.display_name,
                                    f"{n_rows} standings rows, expected "
                                    f"{len(table.standings)}"))  # fmt: skip
        if v.counted_rounds != len(counted) or list(v.round_ids) != [x.round_id for x in counted]:
            findings.append(
                Finding(
                    "repairable",
                    c.display_name,
                    "the current version does not list the counted rounds",
                )
            )
        if v.champion_count != (sum(1 for s in table.standings if s.rank == 1 and s.points > 0)
                                if expected == "completed" else 0):  # fmt: skip
            findings.append(
                Finding(
                    "repairable", c.display_name, "the current version's champion count is wrong"
                )
            )
    for later, earlier in zip(champs[1:], champs, strict=False):
        if earlier.boundary_fixed_at is None:
            findings.append(Finding("repairable", earlier.display_name,
                                    f"boundary not fixed although {later.display_name} "
                                    "exists"))  # fmt: skip
    # waiting rounds: legitimate unless they could be assigned now
    probe_models = [ChampModel(m.key, m.ordinal, m.name, m.start_date, m.required,
                               dict(m.roles), m.fixed) for m in models]  # fmt: skip
    try:
        for pm in probe_models:
            resolve_roles(pm, outcome, order)
        plan = plan_assignments(
            [RoundFact(r.id, r.deadline_at, r.published_at, outcome[r.id]) for r in facts_rows],
            probe_models, _series_for(conn, stream)[1],
        )  # fmt: skip
        for rid, _ in plan.assignments:
            findings.append(
                Finding(
                    "repairable",
                    f"Round {fact[rid].code}",
                    "can be assigned to a championship but is not",
                )
            )
        for rid in plan.waiting:
            notes.append(Note("pending_assignment", f"Round {fact[rid].code}",
                              "championship assignment pending: an earlier round holds the "
                              "last available slot"))  # fmt: skip
    except ChampionshipIntegrityError:
        pass  # already reported per championship
    if stream != "development":
        dev = conn.execute(text(
            "SELECT count(*) FROM app.championship_rounds cr JOIN app.championships c "
            "ON c.id = cr.championship_id JOIN app.rounds r ON r.id = cr.round_id "
            "WHERE c.stream = :s AND r.is_development"), {"s": stream}).scalar_one()  # fmt: skip
        if dev:
            findings.append(
                Finding(
                    "material", stream, f"{dev} development round(s) inside the {stream} stream"
                )
            )
    return Inspection(stream, tuple(findings), tuple(notes), tuple(republish))


def verify_stream(conn: Connection, stream: str) -> list[str]:
    """The problems found (repairable and material); empty when consistent.
    Legitimate review, pending assignment and D-30a states are not problems."""
    return [str(f) for f in inspect_stream(conn, stream).findings]


__all__ = [
    "ChampionshipIntegrityError",
    "Finding",
    "Inspection",
    "Note",
    "Processed",
    "RoleChange",
    "expected_status",
    "inspect_stream",
    "resolve_roles",
    "base_name",
    "on_round_event",
    "plan_assignments",
    "process_stream",
    "role_of",
    "unique_name",
    "verify_stream",
]
