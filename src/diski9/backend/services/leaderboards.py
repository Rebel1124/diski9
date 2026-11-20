"""Weekly leaderboards: read-only services (Phase 6C.5 Stage B).

Specification: ``docs/architecture/phase6c5_design_specification.md`` §9.1, §9.2,
§11.3, §12.2, §13 and decisions CH-01, CH-09, CH-12.

* **Official** results are read from the persisted score sets (the latest revision
  of the round). While the round is reopened they are returned as the **last
  published** results with ``under_review`` set: they are no longer definitive.
* **Provisional** standings are computed on read from the latest settlement of each
  locked entry. Nothing is stored; there are no points, no projections, pending
  payouts are never shown as lost, and an undecided recovery or net stays ``None``
  (S-11).
* Every read is one ``READ ONLY`` ``REPEATABLE READ`` transaction: no writes, a
  consistent snapshot, no football provider and no settlement engine.
* Rows carry a display name and approved statistics only; never user or entry IDs,
  emails, predictions or odds. ``is_me`` is decided on the server.
* Development rounds are visible only when development rounds are enabled.

Championship standings, history and statistics come with Stages C and E.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, Engine, select, text

from ...challenge import scoring
from ..auth.accounts import LockedName, leaderboard_names
from ..auth.permissions import Principal
from ..db.schema import championship_series, championship_versions, championships, rounds
from . import championships as championships_svc
from .common import NotFound, ValidationFailed
from .competition import ALLOCATION, current_designation_row, stream_of

DEFAULT_PAGE_SIZE = 50  # L-27
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class WeeklyRow:
    position: int | None  # official or provisional rank; None when not ranked
    shared: bool  # the position is shared with another entry
    name: str
    returned: Decimal | None  # gross returned (settled so far while provisional)
    net: Decimal | None  # None while undecided
    recovery: str  # recovered | not_recovered | undecided | refunded | round_refund
    points: int | None  # weekly points (official competitive rounds only)
    settled: int | None  # predictions settled so far (provisional only)
    pending: int | None  # predictions still pending (provisional only)
    status: str  # ranked | refunded | round_void | in_progress | awaiting_round | provisional
    is_me: bool = False


@dataclass(frozen=True)
class WeeklyBoard:
    round_code: str
    stream: str  # development | beta | official
    state: str  # open | locked | provisional | final | under_review | unpublished
    classification: str | None  # competitive | practice | None (not fixed yet)
    round_void: bool
    void_basis: str | None  # d32b | operator
    revision: int | None  # official publication number
    corrected: bool  # a later official revision exists (re-published after review)
    published_at: datetime | None
    entries: int  # locked valid entries
    settled_predictions: int | None
    pending_predictions: int | None
    rows: tuple[WeeklyRow, ...]
    total: int
    page: int
    pages: int
    page_size: int
    me: WeeklyRow | None
    me_page: int | None
    me_status: str | None  # None for guests; not_entered | the row status
    # championship association (CH-02): never speculative
    championship: str | None = None  # display name once assigned
    # assigned | practice | void | not_counted | pending_assignment | not_applicable
    championship_status: str | None = None
    # True: its weekly points count toward the championship; False: they do not
    # (practice, void, restored without capacity); None: not decided yet
    counts_toward_championship: bool | None = None
    championship_note: str | None = None  # plain-language explanation (CH-05, CH-02)
    championship_round: int | None = None  # its counted-round number (slot), once counted
    championship_rounds_required: int | None = None


@contextmanager
def _snapshot(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="REPEATABLE READ")
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            yield conn


def _viewer(viewer: Principal | None) -> UUID | None:
    if viewer is None or not getattr(viewer, "is_authenticated", False):
        return None
    return viewer.user_id


# ------------------------------------------------------------------ provisional cache
_CACHE: OrderedDict[tuple, tuple] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 64


def _cache_get(key):
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    return None


def _cache_put(key, value) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


@dataclass(frozen=True)
class _Prov:
    """Internal provisional row (never leaves this module with its IDs)."""

    user_id: UUID
    name: LockedName
    gross: Decimal
    complete: bool
    all_void: bool
    settled: int
    pending: int


def _provisional(conn: Connection, round_id: UUID, evaluated: bool) -> tuple:
    """Provisional rows in display order, cached per latest settlement run."""
    run = conn.execute(
        text(
            "SELECT max(id) FROM app.settlement_runs WHERE round_id = :r AND status = 'succeeded'"
        ),
        {"r": round_id},
    ).scalar()
    key = (round_id, run, evaluated)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    rows = conn.execute(
        text(
            "SELECT e.user_id, e.locked_at, e.public_name_at_lock, e.privacy_mode_at_lock, "
            "s.gross, s.complete, s.basis, s.legs FROM app.entries e JOIN LATERAL ("
            "  SELECT gross, complete, basis, legs FROM app.entry_settlements es "
            "  WHERE es.entry_id = e.id ORDER BY es.revision DESC LIMIT 1) s ON true "
            "WHERE e.round_id = :r AND e.locked_submission_id IS NOT NULL ORDER BY e.id"
        ),
        {"r": round_id},
    ).all()
    items = []
    for r in rows:
        verdicts = [leg["verdict"] for leg in (r.legs or {}).get("legs", [])]
        pending = sum(1 for v in verdicts if v == "pending")
        items.append(
            _Prov(
                r.user_id,
                LockedName(r.user_id, r.locked_at, r.public_name_at_lock, r.privacy_mode_at_lock),
                r.gross,
                r.complete,
                r.complete and r.basis == "all_void",
                len(verdicts) - pending,
                pending,
            )
        )
    ranked = [p for p in items if not p.all_void]
    ranks = scoring.competition_ranks([p.gross for p in ranked])  # the one ranking rule
    rank_of = {id(p): k for p, k in zip(ranked, ranks, strict=True)}
    counts: dict[int, int] = {}
    for k in ranks:
        counts[k] = counts.get(k, 0) + 1
    ordered = sorted(
        items, key=lambda p: (p.all_void, rank_of.get(id(p), 0), -p.gross, str(p.user_id))
    )
    out = []
    for p in ordered:
        k = rank_of.get(id(p))
        decided = p.complete and evaluated
        if p.all_void:
            recovery, status, net = "refunded", "refunded", Decimal("0.00")
        elif decided:
            recovery = "recovered" if p.gross >= ALLOCATION else "not_recovered"
            status, net = "provisional", p.gross - ALLOCATION
        else:
            recovery, net = "undecided", None
            status = "awaiting_round" if p.complete else "in_progress"
        row = WeeklyRow(
            position=k,
            shared=k is not None and counts[k] > 1,
            name="",
            returned=ALLOCATION if p.all_void else p.gross,
            net=net,
            recovery=recovery,
            points=None,
            settled=p.settled,
            pending=p.pending,
            status=status,
        )
        out.append((p.user_id, p.name, row))
    value = tuple(out)
    _cache_put(key, value)
    return value


# ------------------------------------------------------------------ official
def _official_row(r, kind: str) -> WeeklyRow:
    if r.status == "round_void":
        recovery, net = "round_refund", Decimal("0.00")
    elif r.status == "void_refunded":
        recovery, net = "refunded", Decimal("0.00")
    else:
        recovery = "recovered" if r.recovered else "not_recovered"
        net = r.gross - ALLOCATION
    return WeeklyRow(
        position=r.rank,
        shared=r.rank is not None and r.same_rank > 1,
        name="",
        returned=r.gross,
        net=net,
        recovery=recovery,
        points=r.points if kind == "championship" else None,
        settled=None,
        pending=None,
        status={"void_refunded": "refunded"}.get(r.status, r.status),
    )


# ------------------------------------------------------------------ service
def weekly_board(
    engine: Engine,
    round_id: UUID,
    *,
    viewer: Principal | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    include_development: bool = False,
) -> WeeklyBoard:
    """The weekly leaderboard of one round, one page at a time (read-only)."""
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValidationFailed("Invalid page size.", [{"field": "page_size"}])
    me_id = _viewer(viewer)
    with _snapshot(engine) as conn:
        r = conn.execute(select(rounds).where(rounds.c.id == round_id)).one_or_none()
        if (
            r is None
            or r.published_at is None
            or r.status in ("draft", "postponed")
            or (r.is_development and not include_development)
        ):
            raise NotFound("No such round.")
        series = conn.execute(
            select(championship_series.c.code).where(championship_series.c.id == r.series_id)
        ).scalar_one()
        stream = stream_of(r.is_development, series)
        base = conn.execute(
            text(
                "SELECT designation FROM app.designations "
                "WHERE round_id = :r AND basis = 'deadline'"
            ),
            {"r": round_id},
        ).scalar()
        classification = {"championship": "competitive", "practice": "practice"}.get(base or "")
        cur = current_designation_row(conn, round_id)
        round_void = cur is not None and cur.designation == "void"
        void_basis = cur.basis if round_void else None
        entries_n = conn.execute(
            text(
                "SELECT count(*) FROM app.entries WHERE round_id = :r "
                "AND locked_submission_id IS NOT NULL"
            ),
            {"r": round_id},
        ).scalar_one()
        champ_name, champ_status, counts, note, slot, required = _round_championship(
            conn, round_id, stream
        )
        common = {
            "round_code": r.code, "stream": stream, "classification": classification,
            "round_void": round_void, "void_basis": void_basis, "entries": entries_n,
            "championship": champ_name, "championship_status": champ_status,
            "counts_toward_championship": counts, "championship_note": note,
            "championship_round": slot, "championship_rounds_required": required,
        }  # fmt: skip
        if r.status == "open":
            return _empty(common, "open", page_size, entries=0, me_status=None)
        latest = conn.execute(
            text(
                "SELECT id, revision, kind, published_at FROM app.score_sets "
                "WHERE round_id = :r ORDER BY revision DESC LIMIT 1"
            ),
            {"r": round_id},
        ).one_or_none()
        if latest is not None and r.status in ("final", "settling"):
            state = "final" if r.status == "final" else "under_review"
            return _official(conn, common, state, latest, me_id, page, page_size)
        if r.status == "final":  # final before official results existed (awaiting backfill)
            return _empty(common, "unpublished", page_size, me_status=None)
        evaluation = conn.execute(
            text(
                "SELECT outcome FROM app.round_evaluations WHERE round_id = :r "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"r": round_id},
        ).scalar()
        evaluated = evaluation is not None and evaluation != "not_evaluated"
        data = _provisional(conn, round_id, evaluated)
        if not data:
            return _empty(
                common, "locked", page_size, me_status=_not_entered(conn, round_id, me_id)
            )
        return _provisional_board(conn, common, data, me_id, page, page_size)


def _not_entered(conn, round_id, me_id) -> str | None:
    if me_id is None:
        return None
    has = conn.execute(
        text(
            "SELECT 1 FROM app.entries WHERE round_id = :r AND user_id = :u "
            "AND locked_submission_id IS NOT NULL"
        ),
        {"r": round_id, "u": me_id},
    ).scalar()
    return "locked" if has else "not_entered"


def _empty(common, state, page_size, *, entries=None, me_status=None) -> WeeklyBoard:
    c = dict(common)
    if entries is not None:
        c["entries"] = entries
    return WeeklyBoard(
        **c, state=state, revision=None, corrected=False, published_at=None,
        settled_predictions=None, pending_predictions=None, rows=(), total=0, page=1,
        pages=1, page_size=page_size, me=None, me_page=None, me_status=me_status,
    )  # fmt: skip


def _bounds(total: int, page: int, page_size: int) -> tuple[int, int]:
    pages = max(1, math.ceil(total / page_size))
    return min(max(1, page), pages), pages


def _official(conn, common, state, latest, me_id, page, page_size) -> WeeklyBoard:
    total = conn.execute(
        text("SELECT count(*) FROM app.round_scores WHERE score_set_id = :s"), {"s": latest.id}
    ).scalar_one()
    void_round = latest.kind == "void"
    page, pages = _bounds(total, page, page_size)
    lo, hi = (page - 1) * page_size + 1, page * page_size
    rows = conn.execute(
        text(
            "SELECT * FROM (SELECT rs.*, count(*) OVER (PARTITION BY rs.rank) AS same_rank, "
            "e.locked_at, e.public_name_at_lock, e.privacy_mode_at_lock "
            "FROM app.round_scores rs JOIN app.entries e ON e.id = rs.entry_id "
            "WHERE rs.score_set_id = :s) t "
            "WHERE display_order BETWEEN :lo AND :hi OR user_id = :me ORDER BY display_order"
        ),
        {"s": latest.id, "lo": lo, "hi": hi, "me": me_id},
    ).all()
    names = leaderboard_names(
        conn,
        [LockedName(x.user_id, x.locked_at, x.public_name_at_lock, x.privacy_mode_at_lock)
         for x in rows],
    )  # fmt: skip
    page_rows, me, me_page = [], None, None
    for x, name in zip(rows, names, strict=True):
        row = replace(_official_row(x, latest.kind), name=name, is_me=x.user_id == me_id)
        if row.is_me:
            me, me_page = row, math.ceil(x.display_order / page_size)
        if lo <= x.display_order <= hi and not void_round:
            page_rows.append(row)
    me_status = None
    if me_id is not None:
        me_status = me.status if me is not None else "not_entered"
    revisions = latest.revision
    return WeeklyBoard(
        **common, state=state, revision=revisions, corrected=revisions > 1,
        published_at=latest.published_at, settled_predictions=None, pending_predictions=None,
        rows=tuple(page_rows), total=0 if void_round else total, page=page,
        pages=1 if void_round else pages, page_size=page_size, me=me,
        me_page=None if void_round else me_page, me_status=me_status,
    )  # fmt: skip


def _provisional_board(conn, common, data, me_id, page, page_size) -> WeeklyBoard:
    round_void = common["round_void"]
    total = len(data)
    page, pages = _bounds(total, page, page_size)
    lo = (page - 1) * page_size
    window = list(data[lo : lo + page_size])
    mine = [(i, d) for i, d in enumerate(data) if me_id is not None and d[0] == me_id]
    wanted = window + [d for _, d in mine if d not in window]
    names = leaderboard_names(conn, [d[1] for d in wanted])
    named = {
        id(d): replace(d[2], name=n, is_me=d[0] == me_id)
        for d, n in zip(wanted, names, strict=True)
    }
    me, me_page, me_status = None, None, None
    if mine:
        i, d = mine[0]
        me = named[id(d)]
        if round_void:  # a void round refunds everyone: no positions
            me = replace(
                me,
                position=None,
                shared=False,
                returned=ALLOCATION,
                net=Decimal("0.00"),
                recovery="round_refund",
                status="round_void",
            )
        me_page, me_status = i // page_size + 1, me.status
    elif me_id is not None:
        me_status = "not_entered"
    settled = sum(d[2].settled for d in data)
    pending = sum(d[2].pending for d in data)
    rows = () if round_void else tuple(named[id(d)] for d in window)
    return WeeklyBoard(
        **common, state="provisional", revision=None, corrected=False, published_at=None,
        settled_predictions=settled, pending_predictions=pending, rows=rows,
        total=0 if round_void else total, page=page, pages=1 if round_void else pages,
        page_size=page_size, me=me, me_page=None if round_void else me_page,
        me_status=me_status,
    )  # fmt: skip


NOT_COUNTED_FULL = (
    "This round was restored after its championship had already reached "
    "{n} counted rounds, so its points do not count toward the championship."
)
NOT_COUNTED_RESERVED = (
    "This round was restored while the championship's remaining slots "
    "were reserved by unresolved rounds, so its points do not count toward "
    "the championship unless a slot becomes available."
)


def _round_championship(conn: Connection, round_id: UUID, stream: str) -> tuple:
    """(championship display name, status, counts, note) of a round; no name until
    the round is actually assigned, so nothing speculative is ever shown."""
    row = conn.execute(
        text(
            "SELECT c.id, c.display_name, c.counted_rounds, c.rounds_required, cr.role, cr.slot "
            "FROM app.championship_rounds cr "
            "JOIN app.championships c ON c.id = cr.championship_id WHERE cr.round_id = :r"
        ),
        {"r": round_id},
    ).one_or_none()
    if row is not None:
        status = {"pending": "assigned", "counted": "assigned"}.get(row.role, row.role)
        counts = {"counted": True, "pending": None}.get(row.role, False)
        note = None
        if row.role == "not_counted":
            full = row.counted_rounds >= row.rounds_required
            note = (NOT_COUNTED_FULL.format(n=row.rounds_required) if full
                    else NOT_COUNTED_RESERVED)  # fmt: skip
        elif row.role == "void":
            note = "This round was invalidated, so it does not count toward the championship."
        elif row.role == "practice":
            note = "Practice round: not eligible for championship points."
        return row.display_name, status, counts, note, row.slot, row.rounds_required
    if not championships_svc.stream_open(conn, stream):
        return None, "not_applicable", False, None, None, None
    blocking = conn.execute(
        text(
            "SELECT r.code FROM app.championship_rounds cr JOIN app.rounds r ON r.id = cr.round_id "
            "WHERE cr.role = 'pending' AND cr.championship_id = (SELECT id FROM app.championships "
            "WHERE stream = :s ORDER BY ordinal DESC LIMIT 1) ORDER BY r.deadline_at, r.id"
        ),
        {"s": stream},
    ).scalars().all()  # fmt: skip
    note = None
    if blocking:
        which = " and ".join(f"Round {c}" for c in blocking)
        verb = "is" if len(blocking) == 1 else "are"
        note = f"The championship this round counts toward is confirmed when {which} {verb} final."
    return None, "pending_assignment", None, note, None, None


# ------------------------------------------------------------------ round list
@dataclass(frozen=True)
class RoundSummary:
    code: str  # the authoritative round code (selector value)
    label: str  # human-readable: code and its SAST match window
    status: str  # open | locked | settling | final
    deadline_at: datetime
    has_results: bool  # official results published


def _window_label(start: datetime, end: datetime) -> str:
    a, b = start.astimezone(championships_svc.SAST), end.astimezone(championships_svc.SAST)
    if a.month == b.month:
        return f"{a.day}–{b.day} {b:%b}" if a.day != b.day else f"{b.day} {b:%b}"
    return f"{a.day} {a:%b} – {b.day} {b:%b}"


def round_list(
    engine: Engine, *, stream: str = "beta", include_development: bool = False, limit: int = 200
) -> tuple[RoundSummary, ...]:
    """Published rounds of one stream for the weekly selector, newest deadline first
    (read-only; bounded)."""
    _visible(stream, include_development)
    where, params = championships_svc._stream_where(stream)
    with _snapshot(engine) as conn:
        rows = conn.execute(
            text(
                "SELECT r.code, r.status, r.deadline_at, r.window_start_at, r.window_end_at, "
                "EXISTS (SELECT 1 FROM app.score_sets x WHERE x.round_id = r.id) AS has_results "
                "FROM app.rounds r JOIN app.championship_series s ON s.id = r.series_id "
                "WHERE r.published_at IS NOT NULL AND r.deadline_at IS NOT NULL "
                f"AND r.status NOT IN ('draft', 'postponed') AND {where} "
                "ORDER BY r.deadline_at DESC, r.id DESC LIMIT :n"
            ),
            params | {"n": limit},
        ).all()
    return tuple(
        RoundSummary(r.code, f"{r.code} · {_window_label(r.window_start_at, r.window_end_at)}",
                     r.status, r.deadline_at, r.has_results)
        for r in rows
    )  # fmt: skip


def default_round(rounds: tuple[RoundSummary, ...]) -> RoundSummary | None:
    """The most relevant round: the newest with results or settlement under way
    (official or provisional standings), else the newest locked round, else the
    newest open round. Never chosen by insertion time."""
    for wanted in (("final", "settling"), ("locked",), ("open",)):
        for r in rounds:  # newest deadline first
            if r.status in wanted:
                return r
    return None


def round_id_for(
    engine: Engine, code: str, *, stream: str, include_development: bool = False
) -> UUID | None:
    """The round with this code in this stream (None otherwise): selectors carry
    codes, never identifiers, and a code from another stream resolves to nothing."""
    _visible(stream, include_development)
    where, params = championships_svc._stream_where(stream)
    with _snapshot(engine) as conn:
        return conn.execute(
            text(
                "SELECT r.id FROM app.rounds r JOIN app.championship_series s "
                f"ON s.id = r.series_id WHERE r.code = :code AND {where}"
            ),
            params | {"code": code},
        ).scalar()


def stream_options(engine: Engine, *, include_development: bool = False) -> tuple[str, ...]:
    """Streams a viewer may select: beta, development (only when development
    rounds are enabled) and official (only once the official series has started)."""
    with _snapshot(engine) as conn:
        out = ["beta"]
        if championships_svc.stream_open(conn, "official"):
            out.insert(0, "official")
    if include_development:
        out.append("development")
    return tuple(out)


# ------------------------------------------------------------------ championships
@dataclass(frozen=True)
class ChampionshipSummary:
    name: str
    stream: str
    status: str  # upcoming | in_progress | completed
    start_date: date
    counted_rounds: int
    rounds_required: int
    current: bool


@dataclass(frozen=True)
class ChampionshipRow:
    position: int
    shared: bool
    name: str
    rounds_played: int
    recoveries: int
    qualifying_top10: int
    points: int
    recovery_rate: Decimal  # recoveries / valid competitive rounds played
    is_me: bool = False


@dataclass(frozen=True)
class ChampionshipBoard:
    stream: str
    name: str | None  # None when the stream has no championship yet
    status: str | None
    start_date: date | None
    counted_rounds: int
    rounds_required: int
    under_review: bool  # a member round is reopened (or, on unrepaired data, out of date)
    review_reasons: tuple[str, ...]  # reopened | recalculation_pending | integrity_review
    corrected_after_completion: bool
    corrected_with_fewer_rounds: bool  # D-30a disclosure (never "Short")
    version: int | None  # the version shown (the latest published unless one was chosen)
    published_at: datetime | None
    champions: tuple[str, ...]  # completed and at least one point
    no_champion: bool  # completed and every participant has zero points
    pending_assignment: int  # stream rounds waiting for their championship (current only)
    rows: tuple[ChampionshipRow, ...]
    total: int
    page: int
    pages: int
    page_size: int
    me: ChampionshipRow | None
    me_page: int | None
    me_status: str | None  # None for guests; ranked | refunded_only | practice_only |
    # awaiting_results | not_entered
    championships: tuple[ChampionshipSummary, ...]  # for the selector, newest first
    # Stage D (corrections): review details, versions and disclosures
    review_rounds: tuple[str, ...] = ()  # codes of the rounds under review
    latest_version: int | None = None  # the current published version
    definitive: bool = True  # False while under review or when an older version is shown
    reopened_after_completion: bool = False  # L-33: completed once, needs more rounds again
    not_counted_rounds: tuple[str, ...] = ()  # restored without capacity (CH-05)
    disclosure: str | None = None  # plain-language correction explanation


@dataclass(frozen=True)
class ChampionshipVersionSummary:
    version: int
    cause: str  # round_assigned | round_published | round_republished | round_invalidated
    # | round_restored | backfill | repair
    status: str
    counted_rounds: int
    champion_count: int
    published_at: datetime
    reason: str | None
    current: bool


def _visible(stream: str, include_development: bool) -> None:
    if stream not in championships_svc.STREAMS or (
        stream == "development" and not include_development
    ):
        raise NotFound("No such competition.")


def _summaries(conn: Connection, stream: str) -> tuple[ChampionshipSummary, ...]:
    rows = conn.execute(
        select(championships)
        .where(championships.c.stream == stream)
        .order_by(championships.c.ordinal.desc())
    ).all()
    return tuple(
        ChampionshipSummary(c.display_name, stream, c.status, c.start_date, c.counted_rounds,
                            c.rounds_required, i == 0)
        for i, c in enumerate(rows)
    )  # fmt: skip


def championship_list(
    engine: Engine, *, stream: str = "beta", include_development: bool = False
) -> tuple[ChampionshipSummary, ...]:
    """Championships of a stream for selectors (display names only), newest first."""
    _visible(stream, include_development)
    with _snapshot(engine) as conn:
        return _summaries(conn, stream)


def _review(conn: Connection, champ_id) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(reasons, round codes). ``reopened``: a counted or void member is reopened
    (its re-finalisation may change the standings). ``recalculation_pending``: a
    member's role disagrees with its latest publication, which normal processing
    never leaves behind (only unrepaired data; ``competition verify`` reports it)."""
    rows = conn.execute(
        text(
            "SELECT r.code, cr.role, r.status, ss.kind FROM app.championship_rounds cr "
            "JOIN app.rounds r ON r.id = cr.round_id LEFT JOIN LATERAL ("
            "  SELECT kind FROM app.score_sets WHERE round_id = r.id "
            "  ORDER BY revision DESC LIMIT 1) ss ON true "
            "WHERE cr.championship_id = :c AND cr.role IN ('counted', 'void', 'not_counted') "
            "ORDER BY r.deadline_at, r.id"
        ),
        {"c": champ_id},
    ).all()
    reasons, codes = set(), []
    for x in rows:
        if x.status == "settling" and x.role in ("counted", "void"):
            reasons.add("reopened")
            codes.append(x.code)
        elif x.status != "settling" and (
            (x.role == "counted" and x.kind != "championship")
            or (x.role == "void" and x.kind == "championship")
            or (x.role == "not_counted" and x.kind == "void")
        ):
            reasons.add("recalculation_pending")
            codes.append(x.code)
    return tuple(sorted(reasons)), tuple(codes)


def _outside_stream(conn: Connection, champ_id, stream: str) -> bool:
    """A member that is not a round of the championship's stream: the standings
    cannot be treated as definitive until the inconsistency is investigated
    (``competition verify`` reports it as material)."""
    members = set(conn.execute(text(
        "SELECT round_id FROM app.championship_rounds WHERE championship_id = :c"),
        {"c": champ_id}).scalars())  # fmt: skip
    if not members:
        return False
    return bool(members - {r.id for r in championships_svc.stream_rounds(conn, stream)})


def _disclosure(c, counted: int, invalidated: int) -> str | None:
    if c.status == "completed" and c.boundary_fixed_at is not None and counted < c.rounds_required:
        n = invalidated or (c.rounds_required - counted)
        rounds_txt = "One previously counted round was" if n == 1 else \
            f"{n} previously counted rounds were"  # fmt: skip
        return (f"This championship was corrected after completion. {rounds_txt} "
                "invalidated and the final standings were recalculated.")  # fmt: skip
    if c.status == "in_progress" and c.completed_at is not None:
        return ("A previously counted round was invalidated after this championship was "
                "completed, so it continues until it has "
                f"{c.rounds_required} valid counted rounds.")  # fmt: skip
    if c.corrected_after_completion and c.status == "completed":
        return "This championship was corrected after completion."
    return None


def championship_versions_list(
    engine: Engine, *, stream: str = "beta", name: str, include_development: bool = False
) -> tuple[ChampionshipVersionSummary, ...]:
    """Every published version of one championship, newest first (read-only)."""
    _visible(stream, include_development)
    with _snapshot(engine) as conn:
        c = conn.execute(select(championships).where(
            championships.c.stream == stream, championships.c.display_name == name)
        ).one_or_none()  # fmt: skip
        if c is None:
            raise NotFound("No such championship.")
        rows = conn.execute(
            select(championship_versions)
            .where(championship_versions.c.championship_id == c.id)
            .order_by(championship_versions.c.version.desc())
        ).all()
        return tuple(
            ChampionshipVersionSummary(v.version, v.cause, v.status, v.counted_rounds,
                                       v.champion_count, v.created_at, v.reason,
                                       v.version == c.current_version)
            for v in rows
        )  # fmt: skip


def championship_board(
    engine: Engine,
    *,
    stream: str = "beta",
    name: str | None = None,
    viewer: Principal | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    include_development: bool = False,
    version: int | None = None,
) -> ChampionshipBoard:
    """Official standings of one championship (the current one by default), one page
    at a time, from its latest published version or, with ``version``, an earlier
    published one (read-only; names are resolved now, so retroactive anonymity
    applies to every version)."""
    _visible(stream, include_development)
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValidationFailed("Invalid page size.", [{"field": "page_size"}])
    me_id = _viewer(viewer)
    with _snapshot(engine) as conn:
        summaries = _summaries(conn, stream)
        q = select(championships).where(championships.c.stream == stream)
        q = (q.where(championships.c.display_name == name) if name is not None
             else q.order_by(championships.c.ordinal.desc()).limit(1))  # fmt: skip
        c = conn.execute(q).one_or_none()
        waiting = _waiting(conn, stream)
        if c is None:
            if name is not None:
                raise NotFound("No such championship.")
            return ChampionshipBoard(
                stream, None, None, None, 0, 10, False, (), False, False, None, None, (),
                False, waiting, (), 0, 1, 1, page_size, None, None,
                None if me_id is None else "not_entered", summaries,
            )  # fmt: skip
        v = None
        shown = c.current_version if version is None else version
        if shown is not None:
            v = conn.execute(
                select(championship_versions).where(
                    championship_versions.c.championship_id == c.id,
                    championship_versions.c.version == shown,
                )
            ).one_or_none()
            if v is None:
                raise NotFound("No such championship version.")
        total = 0 if v is None else conn.execute(
            text("SELECT count(*) FROM app.championship_standings WHERE version_id = :v"),
            {"v": v.id},
        ).scalar_one()  # fmt: skip
        page, pages = _bounds(total, page, page_size)
        lo, hi = (page - 1) * page_size + 1, page * page_size
        rows = [] if v is None else conn.execute(
            text(
                "SELECT * FROM (SELECT cs.*, count(*) OVER (PARTITION BY cs.rank) AS same_rank, "
                "e.locked_at, e.public_name_at_lock, e.privacy_mode_at_lock "
                "FROM app.championship_standings cs JOIN app.entries e ON e.id = cs.name_entry_id "
                "WHERE cs.version_id = :v) t "
                "WHERE display_order BETWEEN :lo AND :hi OR user_id = :me "
                "OR (:done AND rank = 1 AND points > 0) "
                "ORDER BY display_order"
            ),
            {"v": v.id, "lo": lo, "hi": hi, "me": me_id,
             "done": v.status == "completed"},
        ).all()  # fmt: skip
        names = leaderboard_names(
            conn,
            [LockedName(x.user_id, x.locked_at, x.public_name_at_lock, x.privacy_mode_at_lock)
             for x in rows],
        )  # fmt: skip
        page_rows, me, me_page, champions = [], None, None, []
        status = v.status if v is not None else c.status
        counted_rounds = v.counted_rounds if v is not None else c.counted_rounds
        completed = status == "completed"
        for x, nm in zip(rows, names, strict=True):
            row = ChampionshipRow(
                x.rank, x.same_rank > 1, nm, x.rounds_played, x.recoveries, x.qualifying_top10,
                x.points, (Decimal(x.recoveries) / Decimal(x.rounds_played)).quantize(
                    Decimal("0.0001")), x.user_id == me_id,
            )  # fmt: skip
            if row.is_me:
                me, me_page = row, math.ceil(x.display_order / page_size)
            if lo <= x.display_order <= hi:
                page_rows.append(row)
            if completed and x.rank == 1 and x.points > 0:
                champions.append(nm)
        me_status = None
        if me_id is not None:
            me_status = "ranked" if me is not None else _not_ranked(conn, c.id, me_id)
        reasons, review_rounds = _review(conn, c.id)
        if _outside_stream(conn, c.id, stream):  # data written outside the services
            reasons = tuple(sorted({*reasons, "integrity_review"}))
        roles = conn.execute(
            text(
                "SELECT r.code, cr.role FROM app.championship_rounds cr JOIN app.rounds r "
                "ON r.id = cr.round_id WHERE cr.championship_id = :c ORDER BY r.deadline_at, r.id"
            ),
            {"c": c.id},
        ).all()
        invalidated = conn.execute(
            text(
                "SELECT count(DISTINCT x) FROM app.championship_versions v, unnest(v.round_ids) x "
                "WHERE v.championship_id = :c "
                "AND NOT x = ANY(coalesce(CAST(:cur AS uuid[]), '{}'::uuid[]))"
            ),
            {"c": c.id, "cur": None if v is None else list(v.round_ids)},
        ).scalar_one()  # fmt: skip
        current = version is None or version == c.current_version
        return ChampionshipBoard(
            stream=stream, name=c.display_name, status=status, start_date=c.start_date,
            counted_rounds=counted_rounds, rounds_required=c.rounds_required,
            under_review=bool(reasons), review_reasons=reasons,
            corrected_after_completion=c.corrected_after_completion,
            corrected_with_fewer_rounds=(completed and c.boundary_fixed_at is not None
                                         and counted_rounds < c.rounds_required),
            version=shown, published_at=v.created_at if v else None,
            champions=tuple(champions), no_champion=completed and not champions,
            pending_assignment=waiting if c.ordinal == _max_ordinal(conn, stream) else 0,
            rows=tuple(page_rows), total=total, page=page, pages=pages, page_size=page_size,
            me=me, me_page=me_page, me_status=me_status, championships=summaries,
            review_rounds=review_rounds, latest_version=c.current_version,
            definitive=current and not reasons,
            reopened_after_completion=c.status == "in_progress" and c.completed_at is not None,
            not_counted_rounds=tuple(x.code for x in roles if x.role == "not_counted"),
            disclosure=_disclosure(c, c.counted_rounds, invalidated) if current else None,
        )  # fmt: skip


# ------------------------------------------------------------------ personal result
@dataclass(frozen=True)
class PersonalRoundResult:
    """A participant's own official result in one round next to its current
    settlement (CH-10): during a review the last published values stay visible and
    are labelled as no longer definitive; no provisional championship points."""

    round_code: str
    published: bool  # official results exist
    under_review: bool  # reopened: the published values are no longer definitive
    revision: int | None
    rank: int | None
    shared: bool
    gross: Decimal | None
    weekly_points: int | None  # points under the weekly methodology
    status: str | None  # ranked | void_refunded | round_void
    championship: str | None
    counts_toward_championship: bool | None
    championship_points: int | None  # weekly points that count (0 if they do not)
    championship_note: str | None
    current: object | None  # participant_results.ParticipantSettlement (current settlement)


def my_round_result(
    engine: Engine, viewer: Principal, round_id: UUID, *, include_development: bool = False
) -> PersonalRoundResult | None:
    """The viewer's own last published result and current settlement for a round;
    ``None`` for guests or without a confirmed entry (participant-scoped)."""
    from .participant_results import my_settlement

    me_id = _viewer(viewer)
    if me_id is None:
        return None
    current = my_settlement(engine, viewer, round_id)
    if current is None or (current.is_development and not include_development):
        return None
    with _snapshot(engine) as conn:
        r = conn.execute(select(rounds).where(rounds.c.id == round_id)).one()
        series = conn.execute(
            select(championship_series.c.code).where(championship_series.c.id == r.series_id)
        ).scalar_one()
        name, _status, counts, note, _slot, _req = _round_championship(
            conn, round_id, stream_of(r.is_development, series)
        )
        row = conn.execute(
            text(
                "SELECT s.revision, rs.rank, rs.gross, rs.points, rs.status, "
                "(SELECT count(*) FROM app.round_scores x WHERE x.score_set_id = s.id "
                "AND x.rank = rs.rank) AS same_rank "
                "FROM app.score_sets s JOIN app.round_scores rs ON rs.score_set_id = s.id "
                "WHERE s.round_id = :r AND rs.user_id = :u ORDER BY s.revision DESC LIMIT 1"
            ),
            {"r": round_id, "u": me_id},
        ).one_or_none()
        if row is None:
            return PersonalRoundResult(r.code, False, False, None, None, False, None, None,
                                       None, name, counts, None, note, current)  # fmt: skip
        champ_points = None
        if counts is True:
            champ_points = row.points
        elif counts is False:
            champ_points = 0
        return PersonalRoundResult(
            r.code, True, r.status == "settling", row.revision, row.rank,
            row.rank is not None and row.same_rank > 1, row.gross, row.points, row.status,
            name, counts, champ_points, note, current,
        )  # fmt: skip


def _max_ordinal(conn, stream) -> int:
    return conn.execute(
        text("SELECT coalesce(max(ordinal), 0) FROM app.championships WHERE stream = :s"),
        {"s": stream},
    ).scalar_one()


def _waiting(conn, stream) -> int:
    """Published rounds of the stream not yet assigned to a championship."""
    if not championships_svc.stream_open(conn, stream):
        return 0
    assigned = set(
        conn.execute(
            text(
                "SELECT cr.round_id FROM app.championship_rounds cr JOIN app.championships c "
                "ON c.id = cr.championship_id WHERE c.stream = :s"
            ),
            {"s": stream},
        ).scalars()
    )
    return sum(1 for r in championships_svc.stream_rounds(conn, stream) if r.id not in assigned)


def _not_ranked(conn, champ_id, user_id) -> str:
    """Why a signed-in participant has no official championship rank (CH-08)."""
    roles = set(
        conn.execute(
            text(
                "SELECT cr.role FROM app.championship_rounds cr JOIN app.entries e "
                "ON e.round_id = cr.round_id WHERE cr.championship_id = :c AND e.user_id = :u "
                "AND e.locked_submission_id IS NOT NULL"
            ),
            {"c": champ_id, "u": user_id},
        ).scalars()
    )
    if "counted" in roles:
        return "refunded_only"  # entered counted rounds but every entry was refunded
    if "pending" in roles:
        return "awaiting_results"
    if "not_counted" in roles:
        return "not_counted_only"  # only restored rounds that do not count (CH-05)
    if "void" in roles:
        return "invalidated_only"  # only rounds later invalidated: refunded, no standing
    if "practice" in roles:
        return "practice_only"
    return "not_entered"


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "ChampionshipBoard",
    "ChampionshipRow",
    "ChampionshipSummary",
    "ChampionshipVersionSummary",
    "RoundSummary",
    "PersonalRoundResult",
    "WeeklyBoard",
    "WeeklyRow",
    "championship_board",
    "championship_list",
    "championship_versions_list",
    "clear_cache",
    "default_round",
    "round_id_for",
    "round_list",
    "stream_options",
    "my_round_result",
    "weekly_board",
]
