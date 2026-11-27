"""Portfolio Build home (Phase 8 CP3A-2): the introduction, the Domestic Weekly
Challenge card with its status line and the local **Research only** toggle.

The card reads only stored facts: the published round (status, fixture window,
deadline, frozen time), the championship it belongs to, and, when no round is
current, the weekend schedule's publication target. Nothing is hard-coded and no
provider is called. The European Match Analysis card is not part of this module
until CP2B.2 is accepted.

Research only chooses which domestic list Portfolio Build shows: OFF, the published
challenge list (the existing builder, frozen data); ON, the upcoming domestic research
list (the existing Screener table, latest data, no competitive selection). Its initial
value depends on the challenge status; once the participant changes it, their choice
is kept in the browser session (``ch-prefs``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from dash import dcc, html

from diski9.challenge.roundsheet import RoundStatus

from .. import education
from ..icons import icon

OPEN, LOCKED, SETTLING, UPCOMING, UNAVAILABLE = (
    "open", "locked", "settling", "upcoming", "unavailable")  # fmt: skip
STATE_LABEL = {OPEN: "Open", LOCKED: "Entries closed", SETTLING: "Settling",
               UPCOMING: "Upcoming", UNAVAILABLE: "Not available"}  # fmt: skip
# owner-approved status wording (record §15.8 D3); times are filled from stored data
MSG_UPCOMING = "Next challenge expected to open {at}, subject to fixture availability."
MSG_UNAVAILABLE = (
    "No Weekly Challenge available this week. You can still research upcoming matches."
)
MSG_DATA_ERROR = ("Challenge information is temporarily unavailable. You can still research "
                  "upcoming matches.")  # fmt: skip
MSG_OPEN = "Entries close {at}."
MSG_LOCKED = "Entries closed. Awaiting match results."
MSG_SETTLING = "Results are being settled."

HEADLINE_1 = "Think you know football?"
HEADLINE_2 = "Put your skills to the test!"
TAGLINE = "9 picks. 100 virtual credits. One challenge."
FOOTNOTE = "Free to play. No real money. Just football."
RESEARCH_LABEL = "Research only"
RESEARCH_TIP = ("Analyse upcoming domestic matches using the latest available data. "
                "Research-only analysis does not form part of the Weekly Challenge.")  # fmt: skip
ACTION_BUILD = "Build domestic portfolio"
ACTION_RESEARCH = "Analyse domestic matches"
RESEARCH_NOTE = ("Upcoming domestic matches with the latest available data. "
                 "This analysis is not part of the Weekly Challenge, and no picks can be made "
                 "here.")  # fmt: skip
RESEARCH_VALUE = "on"
# assessment results that verifiably explain why no prototype round can open
_VERIFIED_REASONS = (RoundStatus.NO_ROUND, RoundStatus.MISSING_MARKETS, RoundStatus.STALE_ODDS,
                     RoundStatus.INSUFFICIENT, RoundStatus.INFEASIBLE)  # fmt: skip


@dataclass(frozen=True)
class ChallengeStatus:
    state: str  # open | locked | settling | upcoming | unavailable
    message: str
    round_code: str | None = None
    window: tuple[datetime, datetime] | None = None
    deadline: datetime | None = None
    frozen_at: datetime | None = None
    target: datetime | None = None
    reason: str | None = None  # a verified reason, shown only when known
    championship: str | None = None
    counted: int = 0
    required: int = 0

    @property
    def default_research(self) -> bool:
        """Owner decision (Part B, 27 Nov 2026): OFF while a challenge is open, locked
        or settling; ON when the next one is upcoming or none is available."""
        return self.state in (UPCOMING, UNAVAILABLE)


# ------------------------------------------------------------------ status
def schedule_target(backend) -> tuple[datetime, datetime] | None:
    """(database now, publication target of the competition week ``now`` belongs to)
    from the active weekend schedule, read-only; None if it cannot be resolved."""
    from diski9.backend.db import db_now, read_only
    from diski9.backend.jobs.prepare import load_schedule, week_at

    try:
        with read_only(backend.engine) as conn:
            now = db_now(conn)
            sched = load_schedule(conn)
            week = week_at(now, sched.window_rule, sched.publish_rule, timedelta(0))
        return now, week.target
    except Exception:  # noqa: BLE001 - the card then says "not available"
        return None


def _championship(backend, view) -> tuple[str | None, int, int]:
    from diski9.backend.services import leaderboards as lb

    dev = getattr(view, "is_development", False) if view is not None else backend.show_development
    if dev and not backend.show_development:
        return None, 0, 0
    try:
        cb = lb.championship_board(
            backend.engine,
            stream="development" if dev else "beta",
            page_size=1,
            include_development=backend.show_development,
        )
    except Exception:  # noqa: BLE001 - shown without championship details
        return None, 0, 0
    return cb.name, cb.counted_rounds, cb.rounds_required


def challenge_status(
    service, local, *, target_fn=schedule_target, championship: bool = True
) -> ChallengeStatus:
    """The domestic challenge's state for the card, from stored data only
    (``championship=False`` skips the standings lookup when only the state is needed)."""
    from . import persist

    b = persist.backend_of(service)
    if b is None:  # prototype mode: the round assembled from the local football store
        return _prototype_status(service, local)
    found = b.published()
    view = found[0] if found else None
    name, counted, required = _championship(b, view) if championship else (None, 0, 0)
    common = {"championship": name, "counted": counted, "required": required}
    if found is None and b.error:
        return ChallengeStatus(UNAVAILABLE, MSG_DATA_ERROR, **common)
    if view is not None and view.status in ("open", "locked", "settling"):
        snap = found[1]
        facts = {"round_code": view.code, "window": (view.window_start_at, view.window_end_at),
                 "deadline": view.deadline_at,
                 "frozen_at": view.snapshot_at or getattr(snap, "snapshot_at", None)}  # fmt: skip
        now = service.now()
        if view.status == "open" and view.deadline_at is not None and view.deadline_at > now:
            return ChallengeStatus(OPEN, MSG_OPEN.format(at=_at(local, view.deadline_at)),
                                   **facts, **common)  # fmt: skip
        if view.status == "settling":
            return ChallengeStatus(SETTLING, MSG_SETTLING, **facts, **common)
        return ChallengeStatus(LOCKED, MSG_LOCKED, **facts, **common)
    # no round, or the latest one is final: the next week is upcoming until its
    # scheduled publication time, then unavailable if nothing was published
    timing = target_fn(b)
    if timing is not None and timing[0] < timing[1]:
        return ChallengeStatus(UPCOMING, MSG_UPCOMING.format(at=_at(local, timing[1])),
                               target=timing[1], **common)  # fmt: skip
    return ChallengeStatus(UNAVAILABLE, MSG_UNAVAILABLE, **common)


def _prototype_status(service, local) -> ChallengeStatus:
    avail = service.availability("live")
    snap = service.snapshot("live")
    facts = {}
    if snap is not None and not snap.is_demo:
        facts = {"round_code": snap.round_id, "window": snap.window, "deadline": snap.deadline}
    if avail.status is RoundStatus.OPEN:
        msg = MSG_OPEN.format(at=_at(local, snap.deadline)) if snap and snap.deadline else ""
        return ChallengeStatus(OPEN, msg, **facts)
    if avail.status is RoundStatus.LOCKED:
        return ChallengeStatus(LOCKED, MSG_LOCKED, **facts)
    reason = avail.title if avail.status in _VERIFIED_REASONS else None
    return ChallengeStatus(UNAVAILABLE, MSG_UNAVAILABLE, reason=reason)


def _at(local, dt) -> str:
    return f"{local(dt)} SAST"


def research_on(prefs, status: ChallengeStatus) -> bool:
    """The participant's explicit choice this session, else the status default."""
    prefs = prefs or {}
    if "research" in prefs:
        return bool(prefs["research"])
    return status.default_research


# ------------------------------------------------------------------ layout
def football_icon() -> html.Span:
    return icon("football", "pb-ball")


def _window_text(local, window) -> str | None:
    if not window:
        return None
    start, end = window
    last = end - timedelta(seconds=1)  # the window is half-open
    return f"{local(start, '%a %d %b')} – {local(last, '%a %d %b')}"


def domestic_card(status: ChallengeStatus, local, research: bool) -> html.Div:
    meta = []
    if status.championship:
        meta.append(html.Span(status.championship, className="strong"))
        if status.required:
            meta.append(html.Span(f"{status.counted} of {status.required} rounds completed",
                                  className="muted"))  # fmt: skip
    if status.round_code:
        meta.append(html.Span(f"Round {status.round_code}", className="muted"))
    facts = []
    window = _window_text(local, status.window)
    if window:
        facts.append(("Fixtures", window))
    if status.state == OPEN and status.deadline is not None:
        facts.append(("Entry deadline", _at(local, status.deadline)))
    if status.state == UPCOMING and status.target is not None:
        facts.append(("Expected", _at(local, status.target)))
    return html.Section(
        [
            html.Div(
                [
                    html.H2("Domestic Weekly Challenge", className="ch-h2"),
                    html.Span(
                        STATE_LABEL[status.state], className=f"pb-state pb-state-{status.state}"
                    ),
                ],
                className="pb-card-head",
            ),  # fmt: skip
            html.Div(meta, className="pb-meta small") if meta else None,
            html.P(status.message, className="pb-status", id="pb-status-line"),
            html.P(status.reason, className="muted small pb-reason") if status.reason else None,
            html.Dl(
                [x for k, v in facts for x in (html.Dt(k), html.Dd(v))], className="pb-facts small"
            )
            if facts
            else None,  # fmt: skip
            html.Div(
                [
                    dcc.Checklist(
                        id="research-only",
                        options=[{"label": RESEARCH_LABEL, "value": RESEARCH_VALUE}],
                        value=[RESEARCH_VALUE] if research else [],
                        className="pb-switch",
                        inputClassName="pb-switch-input",
                        labelClassName="pb-switch-label",
                    ),
                    education.info(html.P(RESEARCH_TIP), "About Research only", "pb-research-info"),
                ],
                className="pb-research",
            ),
            html.Button(
                ACTION_RESEARCH if research else ACTION_BUILD,
                id="pb-go",
                n_clicks=0,
                className="ch-btn primary pb-go",
            ),  # fmt: skip
        ],
        className="pb-card pb-domestic",
        **{"aria-label": "Domestic Weekly Challenge"},
    )


def portfolio_home(service, local, prefs) -> html.Div:
    """The top of Portfolio Build. The European Match Analysis card is deliberately
    absent until CP2B.2 is accepted (no placeholder)."""
    status = challenge_status(service, local)
    research = research_on(prefs, status)
    return html.Div(
        [
            html.Div(
                [
                    football_icon(),
                    html.Div(
                        [
                            html.H1(HEADLINE_1, className="pb-h1"),
                            html.P(HEADLINE_2, className="pb-h2"),
                        ],
                        className="pb-headlines",
                    ),
                ],
                className="pb-hero",
            ),
            html.P(TAGLINE, className="pb-tagline"),
            html.Div([domestic_card(status, local, research)], className="pb-cards"),
            html.P(FOOTNOTE, className="muted small pb-footnote"),
            html.Div(mode_note(research), id="pb-mode-note"),
            html.Div(id="pb-list"),  # scroll target for the main action
        ],
        className="pb-home page",
    )


def mode_note(research: bool):
    """Above the research list: what it is. The competitive list carries its own
    frozen-snapshot notice inside the builder."""
    if not research:
        return None
    return html.Div(
        [html.Span("Research only", className="ctx-tag latest"), " ", RESEARCH_NOTE],
        className="pb-research-note small",
    )
