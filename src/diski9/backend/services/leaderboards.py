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
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, Engine, select, text

from ...challenge import scoring
from ..auth.accounts import LockedName, leaderboard_names
from ..auth.permissions import Principal
from ..db.schema import championship_series, rounds
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
        common = {
            "round_code": r.code, "stream": stream, "classification": classification,
            "round_void": round_void, "void_basis": void_basis, "entries": entries_n,
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


__all__ = ["DEFAULT_PAGE_SIZE", "WeeklyBoard", "WeeklyRow", "clear_cache", "weekly_board"]
