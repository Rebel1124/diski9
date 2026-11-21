"""Leaderboards: Weekly and Championship, from the real read services (Phase 6C.5
Stage E). Specification §12.1 to §12.4 and §12.6; decisions CH-06 to CH-12.

Presentation only. Every rank, return, recovery, point, status and indicator comes
from :mod:`diski9.backend.services.leaderboards`, the published official results,
or provisional settlement on read. Nothing here ranks, scores or decides a
recovery. Rows carry display names only. Selectors carry round codes and
championship display names, never identifiers, and the server resolves them
within the selected stream. When the competition database is not configured
(prototype mode), the Phase 6B demonstration leaderboards are shown instead, with
their ribbon.

Status is always written in words, never shown by colour alone. All values are
virtual credits: there are no currency symbols.
"""

from __future__ import annotations

from datetime import datetime

from dash import dcc, html

from diski9.challenge.scoring import POINTS_150_75_V2

from . import components as c
from . import persist

PAGE_SIZE = 50
STREAM_LABEL = {"beta": "Beta", "official": "Official", "development": "Development"}

RECOVERY_TEXT = {
    "recovered": "Recovered",
    "not_recovered": "Not recovered",
    "undecided": "Not decided yet",
    "refunded": "Refunded (all void)",
    "round_refund": "Refunded (round void)",
}
STATUS_TEXT = {
    "ranked": "Ranked",
    "refunded": "Refunded",
    "round_void": "Round void",
    "in_progress": "Settling",
    "awaiting_round": "Awaiting round result",
    "provisional": "Provisional",
}
REVIEW_TEXT = {
    "reopened": "A round in this championship has been reopened for review. These are the "
    "last published standings and they may change when the review ends.",
    "recalculation_pending": "A round's published result changed and these standings are "
    "waiting to be recalculated. They are the last published standings.",
    "integrity_review": "These standings are being checked by the competition team and are "
    "not final. They are the last published standings.",
}
NOT_RANKED_TEXT = {
    "not_entered": "You have not entered a round in this championship yet.",
    "awaiting_results": "Your entries are waiting for their official results.",
    "refunded_only": "Your entries in this championship were refunded (all predictions void), "
    "so you have no official ranking yet.",
    "practice_only": "You have only entered practice rounds, which do not count toward the "
    "championship.",
    "not_counted_only": "Your rounds in this championship were restored after it already had "
    "its ten counted rounds, so they do not count toward it.",
    "invalidated_only": "Your rounds in this championship were invalidated, so they do not "
    "count toward it.",
}
ALL_INVALIDATED = (
    "All previously counted rounds were subsequently invalidated. No official standings or "
    "champion remain for this championship. Subsequent championships are unaffected."
)


# ------------------------------------------------------------------ helpers
def backend(service):
    return persist.backend_of(service)


def viewer():
    from diski9.backend.auth.web import current_principal

    try:
        return current_principal()
    except Exception:  # noqa: BLE001 - outside a request: a guest
        return None


def sast(at: datetime | None) -> str:
    if at is None:
        return ""
    from diski9.backend.services.championships import SAST

    return f"{at.astimezone(SAST):%d %b %Y %H:%M} SAST"


def stream_badge(stream: str) -> html.Span:
    return html.Span(STREAM_LABEL.get(stream, stream), className=f"ch-pill lb-stream {stream}")


def num(value) -> str:
    return "—" if value is None else c.credits(value)


def signed(value) -> str:
    """A signed amount with a true minus sign (U+2212), which aligns with "+" in tables."""
    return "—" if value is None else f"{value:+,.2f}".replace("-", "\u2212")


def plural(n: int, one: str, many: str | None = None) -> str:
    """ "1 round played", "2 rounds played": natural counts instead of "round(s)"."""
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def round_title(window: str, code: str) -> str:
    """A round's user-facing name: its match window (the code is shown de-emphasised)."""
    return f"Round · {window}" if window else f"Round {code}"


def cell(value, label: str, cls: str = "") -> html.Td:
    """A table cell that keeps its column label on narrow screens (card layout)."""
    return html.Td(value, className=cls, **{"data-label": label})


def unavailable(text: str = "Leaderboards are temporarily unavailable. Please try again "
                "shortly.") -> list:  # fmt: skip
    return [html.Div(text, className="ch-ribbon warn")]


def rules() -> html.Details:
    """The points and tie-break rules from the scoring engine's own configuration."""
    cfg = POINTS_150_75_V2
    places = ["1st", "2nd", "3rd"] + [f"{n}th" for n in range(4, len(cfg.top_points) + 1)]
    items = [html.Li(f"{p}: {pts}") for p, pts in zip(places, cfg.top_points, strict=True)]
    items.append(html.Li(f"{len(cfg.top_points) + 1}th and below: {cfg.recovery_points}"))
    return html.Details(
        [
            html.Summary("How points work"),
            html.Div(
                [
                    html.P(
                        f"Weekly points are awarded only to entries that recover their "
                        f"{cfg.recovery_target:.0f} virtual credits:",
                        className="small",
                    ),
                    html.Ul(items, className="lb-points-list small"),
                    html.P(
                        "An entry that does not recover its credits receives 0 points. Shared "
                        "positions all receive that position's full points. Refunded entries, "
                        "practice rounds and void rounds award no points.",
                        className="small",
                    ),
                    html.P(
                        f"A championship normally has {cfg.championship_rounds} valid "
                        "competitive rounds. Standings are ordered by total points, then "
                        "successful recoveries, then top-ten finishes with a recovery; players "
                        "still level share the position.",
                        className="small",
                    ),
                ]
            ),
        ],
        className="ch-details lb-rules",
    )


def goto_page(i) -> int:
    """The page a pager button asks for: an int, or ``"me-<n>"`` for "Go to my position"."""
    try:
        return max(1, int(str(i).removeprefix("me-")))
    except (TypeError, ValueError):
        return 1


def pager(page: int, pages: int, total: int, page_size: int, me_page: int | None, kind: str):
    if total == 0:
        return None
    lo, hi = (page - 1) * page_size + 1, min(page * page_size, total)
    btn = "ch-btn ghost small"
    return html.Div(
        [
            html.Span(f"Showing {lo}–{hi} of {total}", className="muted small"),
            html.Div(
                [
                    html.Button(
                        "‹ Previous",
                        id={"t": f"{kind}-goto", "i": page - 1},
                        className=btn,
                        disabled=page <= 1,
                    ),
                    html.Span(f"Page {page} of {pages}", className="small"),
                    html.Button(
                        "Next ›",
                        id={"t": f"{kind}-goto", "i": page + 1},
                        className=btn,
                        disabled=page >= pages,
                    ),
                    # its own id ("me-<page>"): it must never share an id with "Next" or
                    # "Previous" when the viewer is on the adjacent page (Dash ids are unique)
                    html.Button(
                        "Go to my position",
                        id={"t": f"{kind}-goto", "i": f"me-{me_page}"},
                        className=btn,
                    )
                    if me_page is not None and me_page != page
                    else None,
                ],  # fmt: skip
                className="lb-pager-buttons",
            ),
        ],
        className="lb-pager",
    )


def you_box(title: str, rank: str | None, main: str, sub: str = "") -> html.Div:
    return html.Div(
        [
            html.Span(title, className="muted small"),
            html.Strong(rank, className="ch-you-rank") if rank else None,
            html.Span(main),
            html.Span(sub, className="muted small") if sub else None,
        ],
        className="ch-you lb-you",
    )


def rank_label(row) -> str:
    if row.position is None:
        return "—"
    return f"#{row.position}" + (" (shared)" if row.shared else "")


# ------------------------------------------------------------------ page
def page(service) -> html.Div:
    """The Leaderboards page shell: tab, stream and selector, then the body."""
    b = backend(service)
    if b is None:
        from . import pages

        return pages.demo_leaderboards()
    from diski9.backend.services import leaderboards as lb

    try:
        streams = lb.stream_options(b.engine, include_development=b.show_development)
    except Exception:  # noqa: BLE001
        return html.Div([c.page_header("Leaderboards"), *unavailable()], className="ch-page")
    stream = streams[0] if "official" in streams else "beta"
    options, value = selector_options(service, "weekly", stream)
    stream_ctl = (
        dcc.Dropdown(
            id=c.T("lb-stream"), value=stream, clearable=False, searchable=False,
            className="dropdown lb-stream-select",
            options=[{"label": STREAM_LABEL[s], "value": s} for s in streams],
        )
        if len(streams) > 1
        else html.Div(dcc.Dropdown(id=c.T("lb-stream"), value=stream, options=[
            {"label": STREAM_LABEL[stream], "value": stream}]), style={"display": "none"})
    )  # fmt: skip
    return html.Div(
        [
            c.page_header("Leaderboards"),
            html.Div(
                [
                    dcc.RadioItems(
                        id=c.T("lb-tab"),
                        value="weekly",
                        inline=True,
                        className="segmented ch-view",
                        options=[
                            {"label": "Weekly", "value": "weekly"},
                            {"label": "Championship", "value": "championship"},
                        ],
                    ),
                    html.Div(
                        [
                            stream_ctl,
                            dcc.Dropdown(
                                id=c.T("lb-round"),
                                value=value,
                                options=options,
                                clearable=False,
                                searchable=False,
                                className="dropdown lb-select",
                                placeholder="Nothing published yet",
                            ),  # fmt: skip
                        ],
                        className="lb-controls",
                    ),
                ],
                className="lb-top",
            ),
            html.Div(
                [
                    dcc.Loading(
                        html.Div(
                            id=c.T("lb-body"), children=body(service, "weekly", stream, value, 1)
                        ),
                        type="dot",
                    ),
                    rules(),
                ],
                className="lb-main",
            ),  # fmt: skip
        ],
        className="ch-page lb-page",
    )


def selector_options(service, tab: str, stream: str) -> tuple[list, str | None]:
    """Selector options and the default choice for a tab and stream."""
    b = backend(service)
    from diski9.backend.services import leaderboards as lb

    try:
        if tab == "championship":
            champs = lb.championship_list(b.engine, stream=stream,
                                          include_development=b.show_development)  # fmt: skip
            opts = [{"label": x.name + (" (current)" if x.current else ""), "value": x.name}
                    for x in champs]  # fmt: skip
            return opts, champs[0].name if champs else None
        rounds = lb.round_list(b.engine, stream=stream, include_development=b.show_development)
    except Exception:  # noqa: BLE001
        return [], None
    best = lb.default_round(rounds)
    return [{"label": r.label, "value": r.code} for r in rounds], best.code if best else None


def body(service, tab: str, stream: str, value: str | None, page_no: int) -> list:
    try:
        if tab == "championship":
            return championship_body(service, stream, value, page_no)
        return weekly_body(service, stream, value, page_no)
    except Exception:  # noqa: BLE001 - never a raw error on the page
        return unavailable()


# ------------------------------------------------------------------ weekly
def weekly_body(service, stream: str, code: str | None, page_no: int) -> list:
    b = backend(service)
    from diski9.backend.services import leaderboards as lb
    from diski9.backend.services.common import NotFound

    if stream == "official" and code is None:
        return [html.Div("The official series has not started yet.", className="ch-ribbon")]
    if code is None:
        return [html.Div("No published rounds yet. Rounds appear here once a Weekly "
                         "Challenge is published.", className="ch-ribbon")]  # fmt: skip
    rid = lb.round_id_for(b.engine, code, stream=stream, include_development=b.show_development)
    if rid is None:
        return [html.Div("That round is not available.", className="ch-ribbon warn")]
    try:
        wb = lb.weekly_board(b.engine, rid, viewer=viewer(), page=page_no, page_size=PAGE_SIZE,
                             include_development=b.show_development)  # fmt: skip
    except NotFound:
        return [html.Div("That round is not available.", className="ch-ribbon warn")]
    return [
        weekly_header(wb, stream),
        weekly_you(wb),
        weekly_banner(wb),
        weekly_podium(wb),
        weekly_table(wb),
        pager(wb.page, wb.pages, wb.total, wb.page_size, wb.me_page, "lbw"),
    ]


def weekly_header(wb, stream: str) -> html.Div:
    if wb.championship_status == "pending_assignment":
        champ = html.Span(
            [html.Strong("Championship assignment pending. "),
             wb.championship_note or "The championship this round counts toward is confirmed "
             "when the earlier unresolved rounds are final."],
        )  # fmt: skip
    elif wb.championship_status == "not_applicable":
        champ = html.Span("This round does not belong to a championship yet.", className="muted")
    elif wb.championship_round:
        champ = html.Span(f"{wb.championship} · counted round {wb.championship_round} of "
                          f"{wb.championship_rounds_required}")  # fmt: skip
    else:
        role = {"assigned": "result pending", "practice": "practice: no championship points",
                "void": "void: does not count", "not_counted": "does not count (restored)"}.get(
            wb.championship_status or "", "")  # fmt: skip
        champ = html.Span(f"{wb.championship}" + (f" · {role}" if role else ""))
    kind = {"competitive": "Competitive", "practice": "Practice"}.get(
        wb.classification or "", "Not classified yet"
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Strong(round_title(wb.window, wb.round_code), className="lb-title"),
                    stream_badge(stream),
                    html.Span(kind, className="ch-pill"),
                    html.Span(wb.round_code, className="lb-code", title="Round code")
                    if wb.window
                    else None,
                ],
                className="lb-head-line",
            ),
            html.Div(champ, className="small lb-head-champ"),
            html.Div(wb.championship_note, className="muted small")
            if wb.championship_note and wb.championship_status in ("not_counted", "void")
            else None,
        ],  # fmt: skip
        className="lb-head",
    )


def weekly_you(wb):
    if wb.me_status is None:
        return you_box("Your result", None, "Sign in to see your position.")
    me = wb.me
    if wb.me_status == "not_entered" or (me is None and wb.me_status != "locked"):
        return you_box("Your result", None, "You did not enter this round.")
    if wb.me_status == "locked" or me is None:
        return you_box("Your result", None, "Your entry is locked. Results appear as matches "
                       "are settled.")  # fmt: skip
    if me.status == "round_void" and wb.state == "provisional":
        return you_box("Your result (provisional)", None, "On the results so far this round "
                       "would be void and your 100 credits refunded.",
                       "Nothing is final until the round is finalised.")  # fmt: skip
    if me.status in ("round_void",):
        return you_box("Your result", None, "Round void · your 100 credits were refunded",
                       "A refund is not a recovery and is not ranked.")  # fmt: skip
    if me.status == "refunded":
        return you_box("Your result", None, "Void · Refunded · 100 credits returned · not ranked",
                       "All nine of your predictions were void.")  # fmt: skip
    if wb.state == "provisional":
        return you_box(
            "Your result (provisional)",
            rank_label(me),
            f"Returned so far {num(me.returned)} · {me.settled} settled, {me.pending} pending",
            RECOVERY_TEXT.get(me.recovery, ""),
        )
    pts = f" · {me.points} pts" if me.points is not None else ""
    title = "Your result (last published)" if wb.state == "under_review" else "Your result"
    return you_box(
        title,
        rank_label(me),
        f"Returned {num(me.returned)} · Net {signed(me.net)} · "
        f"{RECOVERY_TEXT.get(me.recovery, '')}{pts}",
        "Practice round: no championship points." if wb.classification == "practice" else "",
    )


def weekly_banner(wb):
    if wb.state == "open":
        return html.Div("Entries are revealed after the deadline.", className="ch-ribbon")
    if wb.state == "locked":
        return html.Div(f"Entries locked · {wb.entries} entries · settlement starts when "
                        "results arrive.", className="ch-ribbon")  # fmt: skip
    if wb.state == "unpublished":
        return html.Div("This round is final, but its official results have not been published "
                        "yet.", className="ch-ribbon warn")  # fmt: skip
    if wb.round_void and wb.state == "provisional":
        return html.Div("Provisional: on the results so far, too many predictions are void for "
                        "a valid round. If that stands when the round is finalised, every entry "
                        "is refunded its 100 credits and there are no ranks or points. Nothing "
                        "is final yet.", className="ch-ribbon warn")  # fmt: skip
    if wb.round_void:
        why = (
            "An operator invalidated this round"
            if wb.void_basis == "operator"
            else "Too many predictions were void, or too few entries remained, for a valid result"
        )
        return html.Div(f"Round void: {why}. Every entry was refunded its 100 credits; there "
                        "are no ranks or points.", className="ch-ribbon warn")  # fmt: skip
    parts = []
    if wb.state == "provisional":
        settled, pending = wb.settled_predictions or 0, wb.pending_predictions or 0
        parts.append(html.Div(
            f"Provisional · {settled} of {settled + pending} predictions settled · positions "
            "change as results arrive · official ranks and points when final.",
            className="ch-ribbon"))  # fmt: skip
    elif wb.state == "under_review":
        parts.append(
            html.Div(
                "Under review: these are the last published results and are no longer definitive. "
                "They will be republished when the review ends.",
                className="ch-ribbon warn",
            )
        )
    else:
        line = f"Final · published {sast(wb.published_at)}"
        if wb.corrected:
            line = f"Corrected · version {wb.revision} published {sast(wb.published_at)}"
        parts.append(html.Div(line, className="muted small lb-state"))
    if wb.classification == "practice":
        parts.append(html.Div(
            "Practice round: fewer than five entries. Results are shown for interest; practice "
            "rounds award no championship points and do not advance the championship.",
            className="ch-ribbon"))  # fmt: skip
    return html.Div(parts)


def weekly_podium(wb):
    if wb.state not in ("final", "under_review") or wb.round_void or wb.page != 1:
        return None
    rows, per_place = [], {}
    for r in wb.rows:
        if r.position is None or r.position > 3:
            continue
        per_place.setdefault(r.position, []).append(r)
    for place, items in per_place.items():  # at most three names per place
        for r in items[:3]:
            rows.append((place, r.name, num(r.returned)))
        if len(items) > 3:
            rows.append((place, f"and {len(items) - 3} others", ""))
    return c.podium(rows, value_label="Returned")


def weekly_table(wb):
    if wb.round_void or not wb.rows:
        if wb.state in ("final", "under_review", "provisional") and not wb.round_void:
            return html.P("No ranked entries.", className="muted small")
        return None
    provisional = wb.state == "provisional"
    competitive = wb.classification == "competitive" and not provisional
    if provisional:
        head = ["Position", "Name", "Returned so far", "Settled", "Pending", "Status"]
    else:
        head = ["Rank", "Name", "Returned", "Net", "Recovery"] + (["Points"] if competitive
                                                                    else [])  # fmt: skip
    numeric = {"Returned so far", "Settled", "Pending", "Returned", "Net", "Points"}
    head_cls = {"Position": "rank", "Rank": "rank", "Name": "lb-name-cell", "Net": "num lb-net",
                "Points": "num lb-pts"}  # fmt: skip
    rows = []
    for r in wb.rows:
        rank = c.rank_cell(r.position, r.shared) if r.position is not None else "—"
        name = [html.Span("You · ", className="lb-you-tag") if r.is_me else None,
                html.Span(r.name, className="lb-name")]  # fmt: skip
        if provisional:
            cells = [cell(rank, "Position", "rank"), cell(name, "Name", "lb-name-cell"),
                     cell(num(r.returned), "Returned so far", "num strong"),
                     cell(f"{r.settled:,}", "Settled", "num"),
                     cell(f"{r.pending:,}", "Pending", "num"),
                     cell(STATUS_TEXT.get(r.status, r.status), "Status", "txt")]  # fmt: skip
        else:
            cells = [
                cell(rank, "Rank", "rank"), cell(name, "Name", "lb-name-cell"),
                cell(num(r.returned), "Returned", "num strong"),
                cell(signed(r.net), "Net", "num lb-net " + tone(r.net)),
                cell(RECOVERY_TEXT.get(r.recovery, r.recovery),
                     "Recovery", "txt ok" if r.recovery == "recovered" else "txt muted"),
            ]  # fmt: skip
            if competitive:
                cells.append(cell("—" if r.points is None else f"{r.points:,}", "Points",
                                  "num strong lb-pts"))  # fmt: skip
        cls = " ".join(
            x
            for x in ("me" if r.is_me else "", "refund" if r.recovery in ("refunded",) else "")
            if x
        )
        rows.append(html.Tr(cells, className=cls))
    return html.Div(
        html.Table(
            [
                html.Thead(
                    html.Tr(
                        [
                            html.Th(
                                h,
                                className=head_cls.get(h, "num" if h in numeric else "txt"),
                                **({"data-col": "net"} if h == "Net" else {}),
                            )
                            for h in head
                        ]
                    )
                ),
                html.Tbody(rows),
            ],
            className="ch-table lb lb-cards " + ("lb-prov" if provisional else "lb-weekly"),
        ),  # fmt: skip
        className="ch-table-wrap",
    )


tone = c.tone  # performance colour for a signed amount (shared with the result cards)


# ------------------------------------------------------------------ championship
STATUS_LABEL = {"upcoming": "Upcoming", "in_progress": "In progress", "completed": "Completed"}


def progress(counted: int, required: int, completed: bool = False) -> html.Div:
    """Valid counted rounds out of the normal ten. A completed championship that kept
    fewer rounds (D-30a) is not shown as waiting: its unused segments are marked as not
    applicable and the text says it is complete."""
    short = completed and counted < required
    segs = [html.Span(className="lb-seg on" if i < counted else
                      "lb-seg na" if short else "lb-seg") for i in range(required)]  # fmt: skip
    text = (f"Completed with {counted} valid rounds" if short
            else f"{counted} of {required} valid rounds")  # fmt: skip
    return html.Div(
        [html.Div(segs, className="lb-segs", **{"aria-hidden": "true"}),
         html.Span(text, className="lb-progress-text")],
        className="lb-progress", role="img",
        **{"aria-label": text if short else
           f"{counted} of {required} valid competitive rounds counted"},
    )  # fmt: skip


def championship_body(service, stream: str, name: str | None, page_no: int) -> list:
    b = backend(service)
    from diski9.backend.services import leaderboards as lb
    from diski9.backend.services.common import NotFound

    if stream == "official" and name is None:
        return [html.Div("The official series has not started yet.", className="ch-ribbon")]
    try:
        cb = lb.championship_board(b.engine, stream=stream, name=name, viewer=viewer(),
                                   page=page_no, page_size=PAGE_SIZE,
                                   include_development=b.show_development)  # fmt: skip
    except NotFound:
        return [html.Div("That championship is not available.", className="ch-ribbon warn")]
    if cb.name is None:
        return [html.Div("The first championship begins with the next Weekly Challenge.",
                         className="ch-ribbon")]  # fmt: skip
    return [
        championship_header(cb, stream),
        championship_notices(cb),
        championship_you(cb),
        championship_table(cb),
        pager(cb.page, cb.pages, cb.total, cb.page_size, cb.me_page, "lbc"),
    ]


def championship_header(cb, stream: str) -> html.Div:
    pills = [html.Span(STATUS_LABEL.get(cb.status, cb.status), className="ch-pill ok"
                       if cb.status == "completed" else "ch-pill")]  # fmt: skip
    if cb.under_review:
        pills.append(html.Span("Under review", className="ch-pill warn"))
    if cb.corrected_after_completion:
        pills.append(html.Span("Corrected", className="ch-pill warn"))
    champion = None
    if cb.status == "completed":
        if cb.champions:
            label = "Champion" if len(cb.champions) == 1 else "Joint champions"
            champion = html.Div([c.rank_icon(1), html.Strong(f"{label}: "),
                                 html.Span(", ".join(cb.champions))],
                                className="lb-champion")  # fmt: skip
        else:
            champion = html.Div("No champion: no participant scored points.",
                                className="lb-champion muted")  # fmt: skip
    return html.Div(
        [
            html.Div(
                [html.Strong(cb.name), stream_badge(stream), *pills], className="lb-head-line"
            ),  # fmt: skip
            progress(cb.counted_rounds, cb.rounds_required, cb.status == "completed"),
            champion,
            html.Div(
                f"{plural(cb.pending_assignment, 'published round')} waiting for "
                "championship assignment.",
                className="muted small",
            )
            if cb.pending_assignment
            else None,
        ],  # fmt: skip
        className="lb-head",
    )


def championship_notices(cb) -> html.Div:
    out = []
    for reason in cb.review_reasons:
        out.append(html.Div(REVIEW_TEXT.get(reason, REVIEW_TEXT["reopened"]),
                            className="ch-ribbon warn"))  # fmt: skip
    if cb.status == "completed" and cb.corrected_with_fewer_rounds and cb.counted_rounds == 0:
        out.append(html.Div(ALL_INVALIDATED, className="ch-ribbon"))
    elif cb.disclosure:
        extra = (" Subsequent championships are unaffected."
                 if cb.corrected_with_fewer_rounds else "")  # fmt: skip
        out.append(html.Div(cb.disclosure + extra, className="ch-ribbon"))
    if cb.not_counted_rounds:
        out.append(
            html.Div(
                "Restored without championship points (the championship already had its counted "
                f"rounds): {', '.join(cb.not_counted_rounds)}.",
                className="muted small",
            )
        )
    if cb.status == "upcoming" and cb.total == 0:
        out.append(html.Div("This championship starts with the next valid competitive round. "
                            "Everyone starts at zero.", className="ch-ribbon"))  # fmt: skip
    return html.Div(out)


def championship_you(cb):
    if cb.me_status is None:
        return you_box("Your championship", None, "Sign in to see your position.")
    if cb.me is not None:
        m = cb.me
        rate = f" · recovery rate {m.recovery_rate:.0%}" if m.rounds_played else ""
        title = "Your championship (last published)" if cb.under_review else "Your championship"
        return you_box(
            title,
            rank_label(m),
            f"{m.points:,} pts · {plural(m.rounds_played, 'round')} played · "
            f"{plural(m.recoveries, 'recovery', 'recoveries')} · "
            f"{plural(m.qualifying_top10, 'top-10 finish', 'top-10 finishes')}{rate}",
        )
    return you_box(
        "Your championship",
        None,
        NOT_RANKED_TEXT.get(cb.me_status, "No ranked round in this championship yet."),
    )


def championship_table(cb):
    if not cb.rows:
        if cb.status != "upcoming" and not (cb.status == "completed" and cb.counted_rounds == 0):
            return html.P("No ranked participants yet.", className="muted small")
        return None
    head = [("Rank", "rank"), ("Name", "lb-name-cell"), ("Played", "num"),
            ("Recoveries", "num"), ("Top 10s", "num"), ("Points", "num lb-pts"),
            ("Rate", "num lb-rate")]  # fmt: skip
    rows = []
    for r in cb.rows:
        rows.append(
            html.Tr(
                [
                    cell(c.rank_cell(r.position, r.shared), "Rank", "rank"),
                    cell(
                        [
                            html.Span("You · ", className="lb-you-tag") if r.is_me else None,
                            html.Span(r.name, className="lb-name"),
                        ],
                        "Name",
                        "lb-name-cell",
                    ),
                    cell(f"{r.rounds_played:,}", "Played", "num"),
                    cell(f"{r.recoveries:,}", "Recoveries", "num"),
                    cell(f"{r.qualifying_top10:,}", "Top 10s", "num"),
                    cell(f"{r.points:,}", "Points", "num strong lb-pts"),
                    cell(f"{r.recovery_rate:.0%}", "Rate", "num lb-rate"),
                ],  # fmt: skip
                className="me" if r.is_me else "",
            )
        )
    return html.Div(
        [
            html.Div(
                html.Table(
                    [
                        html.Thead(html.Tr([html.Th(h, className=k) for h, k in head])),
                        html.Tbody(rows),
                    ],
                    className="ch-table lb lb-cards lb-champ",
                ),  # fmt: skip
                className="ch-table-wrap",
            ),
            html.P(
                "Ranked by points, then recoveries, then top-ten finishes with a recovery; "
                "players still level share the position. Rate = recoveries ÷ valid rounds "
                "played.",
                className="muted small",
            ),  # fmt: skip
        ]
    )


__all__ = ["body", "page", "selector_options"]
