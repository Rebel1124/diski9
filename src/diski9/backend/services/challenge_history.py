"""My Challenge: History, personal statistics and chart series (Phase 6C.5 Stage E).

Read-only and participant-scoped: every query is filtered by the authenticated
viewer's own user id, taken from the server-side principal, never from the
client. Guests get nothing. Specification: ``phase6c5_design_specification.md``
§9.4 (definitions), §12.5 (History), L-28 to L-30, Q-10.

Everything comes from authoritative stored data. Weekly results are the
**published** score sets, the same numbers as the leaderboards. Championship
membership and roles come from ``championship_rounds``, and current settlement
from ``entry_settlements`` (for provisional or reopened rounds). Nothing here
ranks, scores, settles or assigns.

**Statistics (§9.4).** The scope is one stream, and either one championship or
every championship of the stream.

* **Competitive population:** ranked entries in **counted** rounds of the scope.
  This gives rounds played, recoveries, the recovery rate, qualifying top tens,
  and the allocated, returned, net and ROI totals.
  - ROI is aggregate (net ÷ allocated), never an average of per-round ratios.
  - Refunded entries, practice rounds, void rounds, rounds not counted (restored
    without capacity) and rounds awaiting results are excluded. They appear only
    as separate counts.
* **Missed:** counted rounds in the scope that the participant did not enter at
  all. A missed round is not an unsuccessful entry.
* **Practice record:** practice entries and their recoveries, kept separate.
* **Points:** the championship standing comes from that championship's current
  published version. Points are never added across championships or streams. For
  the all-championships scope, each championship's standing is listed separately.
* **Charts:**
  - cumulative allocation versus return over the competitive population;
  - cumulative points for exactly one championship, from its counted rounds'
    published weekly points (missed or refunded rounds add 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, text

from ..auth.permissions import Principal
from . import championships as championships_svc
from .common import NotFound, ValidationFailed
from .leaderboards import _snapshot, _viewer, _visible
from .leaderboards import window_label as lb_window

ALLOCATION = Decimal("100.00")
HISTORY_PAGE_SIZE = 20
MAX_HISTORY_PAGE_SIZE = 50


# ------------------------------------------------------------------ history list
@dataclass(frozen=True)
class HistoryRow:
    round_code: str
    deadline_at: datetime
    stream: str
    classification: str | None  # competitive | practice | None (not locked yet)
    state: str  # locked | provisional | final | under_review | unpublished
    round_void: bool
    void_basis: str | None  # d32b | operator
    entry_refunded: bool  # D-33: all nine predictions void
    published: bool  # official weekly results exist
    revision: int | None
    corrected: bool  # republished after a correction (revision > 1)
    gross: Decimal | None  # the published gross (official), else None
    net: Decimal | None
    recovery: str | None  # recovered | not_recovered | refunded | round_refund
    rank: int | None
    shared: bool
    weekly_points: int | None  # competitive rounds only
    championship: str | None  # display name once assigned
    championship_role: str | None  # pending | counted | practice | void | not_counted
    counts_toward_championship: bool | None
    current_gross: Decimal | None  # current settlement (provisional or under review)
    current_complete: bool | None
    window: str = ""  # friendly label: the round's SAST match window (presentation)


@dataclass(frozen=True)
class HistoryPage:
    rows: tuple[HistoryRow, ...]
    total: int
    page: int
    pages: int
    page_size: int


def _championship_filter(stream: str, championship: str | None) -> tuple[str, dict]:
    if championship is None:
        return "", {}
    return (
        " AND EXISTS (SELECT 1 FROM app.championship_rounds cx JOIN app.championships c2 "
        "ON c2.id = cx.championship_id WHERE cx.round_id = r.id AND c2.stream = :stream "
        "AND c2.display_name = :champ)",
        {"champ": championship, "stream": stream},
    )


_HISTORY = """
SELECT r.code, r.deadline_at, r.status AS round_status, r.window_start_at, r.window_end_at,
       (SELECT d.designation FROM app.designations d
         WHERE d.round_id = r.id AND d.basis = 'deadline') AS base,
       cur.designation AS cur_designation, cur.basis AS cur_basis,
       ss.id AS set_id, ss.revision, ss.kind AS set_kind,
       rs.rank, rs.gross, rs.points, rs.recovered, rs.status AS score_status,
       (SELECT count(*) FROM app.round_scores x
         WHERE x.score_set_id = ss.id AND x.rank = rs.rank) AS same_rank,
       es.gross AS cur_gross, es.complete AS cur_complete, es.basis AS cur_entry_basis,
       c.display_name AS champ, cr.role AS champ_role
  FROM app.entries e
  JOIN app.rounds r ON r.id = e.round_id
  JOIN app.championship_series s ON s.id = r.series_id
  LEFT JOIN LATERAL (SELECT designation, basis FROM app.designations d
                      WHERE d.round_id = r.id ORDER BY d.created_at DESC, d.id DESC
                      LIMIT 1) cur ON true
  LEFT JOIN LATERAL (SELECT id, revision, kind FROM app.score_sets x
                      WHERE x.round_id = r.id ORDER BY x.revision DESC LIMIT 1) ss ON true
  LEFT JOIN app.round_scores rs ON rs.score_set_id = ss.id AND rs.entry_id = e.id
  LEFT JOIN LATERAL (SELECT gross, complete, basis FROM app.entry_settlements es
                      WHERE es.entry_id = e.id ORDER BY es.revision DESC LIMIT 1) es ON true
  LEFT JOIN app.championship_rounds cr ON cr.round_id = r.id
  LEFT JOIN app.championships c ON c.id = cr.championship_id
 WHERE e.user_id = :me AND e.locked_submission_id IS NOT NULL
   AND r.published_at IS NOT NULL AND r.status NOT IN ('draft', 'postponed')
   AND {where}{champ}
"""


def _history_row(x, stream: str) -> HistoryRow:
    published = x.set_id is not None
    round_void = (x.set_kind == "void") if published else (x.cur_designation == "void")
    if published and x.round_status == "settling":
        state = "under_review"
    elif published:
        state = "final"
    elif x.round_status == "settling":
        state = "provisional"
    elif x.round_status == "final":
        state = "unpublished"  # final before official results existed (backfill)
    else:
        state = "locked"
    if published:
        if x.score_status == "round_void":
            recovery, net = "round_refund", Decimal("0.00")
        elif x.score_status == "void_refunded":
            recovery, net = "refunded", Decimal("0.00")
        else:
            recovery = "recovered" if x.recovered else "not_recovered"
            net = x.gross - ALLOCATION
    else:
        recovery, net = None, None
    counts = {"counted": True, "pending": None}.get(x.champ_role, False if x.champ_role else None)
    refunded = (x.score_status == "void_refunded") if published else (
        bool(x.cur_complete) and x.cur_entry_basis == "all_void")  # fmt: skip
    return HistoryRow(
        round_code=x.code, deadline_at=x.deadline_at, stream=stream,
        classification={"championship": "competitive", "practice": "practice"}.get(x.base or ""),
        state=state, round_void=round_void,
        void_basis=x.cur_basis if round_void else None, entry_refunded=refunded,
        published=published, revision=x.revision, corrected=bool(x.revision and x.revision > 1),
        gross=x.gross if published else None, net=net, recovery=recovery,
        rank=x.rank, shared=bool(x.rank is not None and x.same_rank > 1),
        weekly_points=x.points if published and x.set_kind == "championship" else None,
        championship=x.champ, championship_role=x.champ_role, counts_toward_championship=counts,
        current_gross=x.cur_gross if state in ("provisional", "under_review", "locked") else None,
        current_complete=x.cur_complete if state in ("provisional", "under_review") else None,
        window=lb_window(x.window_start_at, x.window_end_at),
    )  # fmt: skip


def my_history(
    engine: Engine,
    viewer: Principal | None,
    *,
    stream: str = "beta",
    championship: str | None = None,
    page: int = 1,
    page_size: int = HISTORY_PAGE_SIZE,
    include_development: bool = False,
) -> HistoryPage | None:
    """The viewer's own locked entries in one stream (optionally one championship),
    newest deadline first, one bounded page at a time. ``None`` for guests."""
    me = _viewer(viewer)
    if me is None:
        return None
    _visible(stream, include_development)
    if not 1 <= page_size <= MAX_HISTORY_PAGE_SIZE:
        raise ValidationFailed("Invalid page size.", [{"field": "page_size"}])
    where, params = championships_svc._stream_where(stream)
    champ_sql, champ_params = _championship_filter(stream, championship)
    params = params | champ_params | {"me": me}
    with _snapshot(engine) as conn:
        if championship is not None:
            _championship_exists(conn, stream, championship)
        total = conn.execute(
            text(
                "SELECT count(*) FROM app.entries e JOIN app.rounds r ON r.id = e.round_id "
                "JOIN app.championship_series s ON s.id = r.series_id "
                "WHERE e.user_id = :me AND e.locked_submission_id IS NOT NULL "
                "AND r.published_at IS NOT NULL AND r.status NOT IN ('draft', 'postponed') "
                f"AND {where}{champ_sql}"
            ),
            params,
        ).scalar_one()
        pages = max(1, math.ceil(total / page_size))
        page = min(max(1, page), pages)
        rows = conn.execute(
            text(_HISTORY.format(where=where, champ=champ_sql)
                 + " ORDER BY r.deadline_at DESC, r.id DESC LIMIT :n OFFSET :o"),
            params | {"n": page_size, "o": (page - 1) * page_size},
        ).all()  # fmt: skip
    return HistoryPage(tuple(_history_row(x, stream) for x in rows), total, page, pages, page_size)


def _championship_exists(conn, stream: str, name: str) -> None:
    found = conn.execute(
        text("SELECT 1 FROM app.championships WHERE stream = :s AND display_name = :n"),
        {"s": stream, "n": name},
    ).scalar()
    if not found:
        raise NotFound("No such championship.")


def my_round_code_visible(
    engine: Engine, viewer: Principal | None, code: str, *, stream: str,
    include_development: bool = False,
) -> UUID | None:  # fmt: skip
    """The round id for a History drill-down, only when the viewer has a locked entry
    in that round of that stream (so a code typed or edited by hand reveals nothing)."""
    me = _viewer(viewer)
    if me is None:
        return None
    _visible(stream, include_development)
    where, params = championships_svc._stream_where(stream)
    with _snapshot(engine) as conn:
        return conn.execute(
            text(
                "SELECT r.id FROM app.rounds r JOIN app.championship_series s "
                "ON s.id = r.series_id JOIN app.entries e ON e.round_id = r.id "
                "AND e.user_id = :me AND e.locked_submission_id IS NOT NULL "
                f"WHERE r.code = :code AND {where}"
            ),
            params | {"me": me, "code": code},
        ).scalar()


# ------------------------------------------------------------------ statistics
@dataclass(frozen=True)
class ChampionshipStanding:
    name: str
    status: str  # upcoming | in_progress | completed
    rank: int | None  # None: no ranked participation
    shared: bool
    points: int | None
    rounds_played: int | None


@dataclass(frozen=True)
class SeriesPoint:
    round_code: str
    deadline_at: datetime
    value_a: Decimal  # chart 1: cumulative allocated; chart 2: cumulative points
    value_b: Decimal | None  # chart 1: cumulative returned; chart 2: None
    detail: str  # the round's own contribution, in words
    window: str = ""  # friendly label: the round's SAST match window (presentation)
    # chart 2: True when the viewer has a ranked (played) entry in this counted round;
    # missed and refunded rounds are plotted but never count toward the chart threshold
    eligible: bool = True


@dataclass(frozen=True)
class PersonalStats:
    stream: str
    scope: str | None  # a championship display name, or None for all championships
    counted_rounds: int  # counted rounds in scope
    played: int  # ranked entries in counted rounds
    missed: int  # counted rounds not entered at all
    recoveries: int
    recovery_rate: Decimal | None  # None when no round was played
    qualifying_top10: int
    allocated: Decimal  # competitive population only
    returned: Decimal
    net: Decimal
    roi: Decimal | None  # net / allocated; None when nothing was allocated
    refunded_entries: int  # refunded (all nine void) entries in counted rounds
    void_rounds: int  # entries in rounds invalidated as a whole
    not_counted_entries: int  # restored rounds without championship capacity (CH-05)
    awaiting_results: int  # locked entries without official results yet
    practice_entries: int
    practice_recoveries: int
    under_review: bool  # a counted round in scope is reopened (published values shown)
    standings: tuple[ChampionshipStanding, ...]  # the scope's championships, newest first
    allocation_series: tuple[SeriesPoint, ...]
    points_championship: str | None  # the championship chart 2 shows
    points_series: tuple[SeriesPoint, ...]

    @property
    def allocation_rounds(self) -> int:
        """Distinct counted competitive rounds behind chart 1 (its threshold, §9.4)."""
        return len(self.allocation_series)

    @property
    def points_rounds(self) -> int:
        """Counted rounds of chart 2's championship that the viewer played."""
        return sum(1 for p in self.points_series if p.eligible)


_COUNTED = """
SELECT c.display_name AS champ, c.ordinal, r.id AS round_id, r.code, r.deadline_at,
       r.status AS round_status, r.window_start_at, r.window_end_at,
       (SELECT x.id FROM app.score_sets x WHERE x.round_id = r.id AND x.kind = 'championship'
         ORDER BY x.revision DESC LIMIT 1) AS set_id,
       EXISTS (SELECT 1 FROM app.entries e WHERE e.round_id = r.id AND e.user_id = :me
               AND e.locked_submission_id IS NOT NULL) AS entered
  FROM app.championship_rounds cr
  JOIN app.championships c ON c.id = cr.championship_id
  JOIN app.rounds r ON r.id = cr.round_id
 WHERE cr.role = 'counted' AND c.stream = :stream{champ}
 ORDER BY r.deadline_at, r.id
"""


def my_statistics(
    engine: Engine,
    viewer: Principal | None,
    *,
    stream: str = "beta",
    championship: str | None = None,
    include_development: bool = False,
) -> PersonalStats | None:
    """The viewer's statistics for one stream and scope (§9.4); ``None`` for guests."""
    me = _viewer(viewer)
    if me is None:
        return None
    _visible(stream, include_development)
    champ_sql = " AND c.display_name = :champ" if championship is not None else ""
    base = {"me": me, "stream": stream} | ({"champ": championship} if championship else {})
    where, sparams = championships_svc._stream_where(stream)
    with _snapshot(engine) as conn:
        if championship is not None:
            _championship_exists(conn, stream, championship)
        counted = conn.execute(text(_COUNTED.format(champ=champ_sql)), base).all()
        sets = [x.set_id for x in counted if x.set_id is not None]
        mine = {}
        if sets:
            for r in conn.execute(
                text(
                    "SELECT score_set_id, gross, rank, points, recovered, qualifying_top10, "
                    "status FROM app.round_scores WHERE score_set_id = ANY(:s) AND user_id = :me"
                ),
                {"s": sets, "me": me},
            ):
                mine[r.score_set_id] = r
        # other entries of the scope: practice, void, not counted, awaiting results
        others = conn.execute(
            text(
                "SELECT (SELECT d.designation FROM app.designations d WHERE d.round_id = r.id "
                "AND d.basis = 'deadline') AS base, ss.kind AS set_kind, rs.status AS st, "
                "rs.gross, cr.role "
                "FROM app.entries e JOIN app.rounds r ON r.id = e.round_id "
                "JOIN app.championship_series s ON s.id = r.series_id "
                "LEFT JOIN LATERAL (SELECT id, kind FROM app.score_sets x WHERE x.round_id = r.id "
                "ORDER BY x.revision DESC LIMIT 1) ss ON true "
                "LEFT JOIN app.round_scores rs ON rs.score_set_id = ss.id AND rs.entry_id = e.id "
                "LEFT JOIN app.championship_rounds cr ON cr.round_id = r.id "
                "LEFT JOIN app.championships c ON c.id = cr.championship_id "
                "WHERE e.user_id = :me AND e.locked_submission_id IS NOT NULL "
                "AND r.published_at IS NOT NULL AND r.status NOT IN ('draft', 'postponed') "
                f"AND {where}{champ_sql}"
            ),
            base | sparams,
        ).all()
        standings = _standings(conn, me, stream, championship)
    played = recoveries = top10 = refunded = 0
    allocated = returned = Decimal("0.00")
    alloc_series: list[SeriesPoint] = []
    under_review = False
    for x in counted:
        row = mine.get(x.set_id)
        if x.round_status == "settling":
            under_review = True
        if row is None:
            continue
        if row.status == "void_refunded":
            refunded += 1
            continue
        played += 1
        recoveries += bool(row.recovered)
        top10 += bool(row.qualifying_top10)
        allocated += ALLOCATION
        returned += row.gross
        alloc_series.append(SeriesPoint(
            x.code, x.deadline_at, allocated, returned,
            f"{row.gross:,.2f} returned of 100.00",
            lb_window(x.window_start_at, x.window_end_at),
        ))  # fmt: skip
    missed = sum(1 for x in counted if not x.entered)
    practice = [o for o in others if o.base == "practice" and o.set_kind == "practice"]
    net = returned - allocated
    points_name, points_series = _points_series(counted, mine, championship, standings)
    return PersonalStats(
        stream=stream, scope=championship, counted_rounds=len(counted), played=played,
        missed=missed, recoveries=recoveries,
        recovery_rate=(Decimal(recoveries) / Decimal(played)).quantize(Decimal("0.0001"))
        if played else None,
        qualifying_top10=top10, allocated=allocated, returned=returned, net=net,
        roi=(net / allocated).quantize(Decimal("0.0001")) if allocated else None,
        refunded_entries=refunded,
        void_rounds=sum(1 for o in others if o.set_kind == "void"),
        not_counted_entries=sum(1 for o in others if o.role == "not_counted"),
        awaiting_results=sum(1 for o in others if o.set_kind is None),
        practice_entries=len(practice),
        practice_recoveries=sum(1 for o in practice if o.st == "ranked" and o.gross >= ALLOCATION),
        under_review=under_review, standings=standings,
        allocation_series=tuple(alloc_series),
        points_championship=points_name, points_series=points_series,
    )  # fmt: skip


def _standings(conn, me, stream, championship) -> tuple[ChampionshipStanding, ...]:
    champ_sql = " AND c.display_name = :champ" if championship is not None else ""
    rows = conn.execute(
        text(
            "SELECT c.display_name, c.status, cs.rank, cs.points, cs.rounds_played, "
            "(SELECT count(*) FROM app.championship_standings y WHERE y.version_id = v.id "
            "AND y.rank = cs.rank) AS same_rank "
            "FROM app.championships c "
            "LEFT JOIN app.championship_versions v ON v.championship_id = c.id "
            "AND v.version = c.current_version "
            "LEFT JOIN app.championship_standings cs ON cs.version_id = v.id AND cs.user_id = :me "
            f"WHERE c.stream = :stream{champ_sql} AND (cs.user_id IS NOT NULL OR EXISTS ("
            "SELECT 1 FROM app.championship_rounds cr JOIN app.entries e ON e.round_id = "
            "cr.round_id AND e.user_id = :me AND e.locked_submission_id IS NOT NULL "
            "WHERE cr.championship_id = c.id)) ORDER BY c.ordinal DESC"
        ),
        {"me": me, "stream": stream} | ({"champ": championship} if championship else {}),
    ).all()
    return tuple(
        ChampionshipStanding(r.display_name, r.status, r.rank,
                             bool(r.rank is not None and r.same_rank > 1), r.points,
                             r.rounds_played)
        for r in rows
    )  # fmt: skip


def _points_series(counted, mine, championship, standings):
    """Cumulative published points for one championship: the selected one, or (all
    championships) the newest one the viewer took part in. Never across two."""
    name = championship or (standings[0].name if standings else None)
    if name is None:
        return None, ()
    total, out = 0, []
    for x in counted:
        if x.champ != name:
            continue
        row = mine.get(x.set_id)
        pts = row.points if row is not None and row.status == "ranked" else 0
        total += pts
        what = ("not entered" if not x.entered else "refunded" if row is not None
                and row.status == "void_refunded" else f"{pts} points")  # fmt: skip
        played = row is not None and row.status != "void_refunded"  # as in `played` above
        out.append(SeriesPoint(x.code, x.deadline_at, Decimal(total), None, what,
                               lb_window(x.window_start_at, x.window_end_at), played))  # fmt: skip
    return name, tuple(out)


__all__ = [
    "ChampionshipStanding",
    "HistoryPage",
    "HistoryRow",
    "PersonalStats",
    "SeriesPoint",
    "my_history",
    "my_round_code_visible",
    "my_statistics",
]
