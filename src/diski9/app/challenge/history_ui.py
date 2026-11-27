"""My Challenge: History, personal summary and the two approved charts (Phase 6C.5
Stage E). Specification §9.4, §12.1, §12.5; L-28 to L-30; Q-10.

Presentation only. The statistics, history rows and chart series come from
:mod:`diski9.backend.services.challenge_history`; the drill-down reuses the 6C.4
results panel (``results_ui.panel``) on ``participant_results.my_settlement``.
Everything is scoped to the signed-in participant on the server; rows carry round
codes, which are resolved server-side only when the viewer has an entry in that
round. All values are virtual credits (no currency symbols).
"""

from __future__ import annotations

import plotly.graph_objects as go
from dash import dcc, html

from . import charts, persist, results_ui
from . import components as c
from . import leaderboards_ui as lbu

ALL = "__all__"
CHART_MIN_ROUNDS = 3  # owner decision (Stage E refinement): charts from three eligible rounds


def _empty(text: str) -> html.Div:
    return html.Div(text, className="ch-ribbon")


def tabs(value: str = "current") -> dcc.RadioItems:
    return dcc.RadioItems(
        id=c.T("me-tab"),
        value=value,
        inline=True,
        className="segmented ch-view",
        options=[
            {"label": "Current", "value": "current"},
            {"label": "History", "value": "history"},
            {"label": "Achievements", "value": "achievements"},
        ],  # fmt: skip
    )


def section(service, local) -> list:
    """The History tab's content: controls and the body."""
    b = persist.backend_of(service)
    if b is None:
        return [_empty("History needs the competition database.")]
    if persist.participant(service) is None:
        return [_empty("Sign in to see your history and personal statistics.")]
    from diski9.backend.services import leaderboards as lb

    try:
        streams = lb.stream_options(b.engine, include_development=b.show_development)
    except Exception:  # noqa: BLE001
        return lbu.unavailable("Your history is temporarily unavailable. Please try again "
                               "shortly.")  # fmt: skip
    stream = "beta" if "beta" in streams else streams[0]
    stream_ctl = dcc.Dropdown(
        id=c.T("me-hstream"), value=stream, clearable=False, searchable=False,
        className="dropdown lb-stream-select",
        options=[{"label": lbu.STREAM_LABEL[s], "value": s} for s in streams],
    )  # fmt: skip
    return [
        html.Div(
            [
                html.Div(stream_ctl, style=None if len(streams) > 1 else {"display": "none"}),
                dcc.Dropdown(
                    id=c.T("me-hscope"),
                    value=ALL,
                    clearable=False,
                    searchable=False,
                    className="dropdown lb-select",
                    options=scope_options(service, stream),
                ),  # fmt: skip
            ],
            className="lb-controls me-hist-controls",
        ),
        dcc.Loading(
            html.Div(id=c.T("me-hbody"), children=body(service, local, stream, ALL, 1)), type="dot"
        ),  # fmt: skip
    ]


def scope_options(service, stream: str) -> list:
    b = persist.backend_of(service)
    from diski9.backend.services import leaderboards as lb

    try:
        champs = lb.championship_list(b.engine, stream=stream,
                                      include_development=b.show_development)  # fmt: skip
    except Exception:  # noqa: BLE001
        champs = ()
    return [{"label": "All championships", "value": ALL}] + [
        {"label": x.name, "value": x.name} for x in champs
    ]


def body(service, local, stream: str, scope: str, page_no: int, open_code: str | None = None):
    b = persist.backend_of(service)
    p = persist.participant(service)
    if b is None or p is None:
        return [_empty("Sign in to see your history and personal statistics.")]
    from diski9.backend.services import challenge_history as ch

    champ = None if scope in (None, ALL) else scope
    try:
        stats = ch.my_statistics(b.engine, p, stream=stream, championship=champ,
                                 include_development=b.show_development)  # fmt: skip
        hist = ch.my_history(b.engine, p, stream=stream, championship=champ, page=page_no,
                             include_development=b.show_development)  # fmt: skip
    except Exception:  # noqa: BLE001 - never a raw error on the page
        return lbu.unavailable("Your history is temporarily unavailable. Please try again "
                               "shortly.")  # fmt: skip
    if hist.total == 0:
        return [
            html.Div(
                [
                    html.P("You have no entries yet in this view.", className="strong"),
                    dcc.Link("Join this week's challenge", href="/", className="ch-btn primary"),
                ],
                className="ch-card me-hist-empty",
            )
        ]
    return [
        summary(stats),
        html.Div([allocation_chart(stats), points_chart(stats)], className="me-charts"),
        history_table(hist, local),
        lbu.pager(hist.page, hist.pages, hist.total, hist.page_size, None, "hist"),
        html.Div(
            id=c.T("me-hdetail"),
            children=detail(service, local, stream, open_code) if open_code else None,
        ),
    ]


# ------------------------------------------------------------------ summary
def _pct(x) -> str:
    return "—" if x is None else f"{x:.1%}"


def summary(s) -> html.Div:
    standing_lines = []
    for st in s.standings:
        status = lbu.STATUS_LABEL.get(st.status, st.status)
        if st.rank is not None:
            text = [html.Strong(st.name), f" #{st.rank}" + (" (shared)" if st.shared else "")
                    + f" · {st.points:,} pts · {status}"]  # fmt: skip
        else:
            text = [html.Strong(st.name), f" · no ranked round yet · {status}"]
        standing_lines.append(html.Li(text))
    if not standing_lines:
        standing_lines = [html.Li("No championship entries yet in this view.")]
    note = (
        "Competitive population: your ranked entries in rounds that counted toward a "
        "championship. Refunded entries, practice and void rounds, rounds restored without "
        "championship points and rounds awaiting results are not included; they are counted "
        "separately. Recovery rate = recoveries ÷ rounds played. Return on allocation = total "
        "net ÷ total allocated (never an average of per-round percentages). Points are shown "
        "per championship and never added across championships or streams. All amounts are "
        "virtual credits."
    )
    others = []
    if s.practice_entries:
        others.append(f"Practice: {lbu.plural(s.practice_entries, 'entry', 'entries')}, "
                      f"{s.practice_recoveries:,} recovered")  # fmt: skip
    if s.refunded_entries:
        others.append(f"Refunded (all void): {s.refunded_entries:,}")
    if s.void_rounds:
        others.append(f"Void rounds: {s.void_rounds:,}")
    if s.not_counted_entries:
        others.append(f"Restored without championship points: {s.not_counted_entries:,}")
    if s.awaiting_results:
        others.append(f"Awaiting official results: {s.awaiting_results:,}")
    return html.Div(
        [
            html.Div(
                [
                    html.H2("Your statistics", className="ch-h2"),
                    lbu.stream_badge(s.stream),
                    html.Span(s.scope or "All championships", className="muted small"),
                ],
                className="ch-row-between",
            ),  # fmt: skip
            html.Ul(standing_lines, className="me-standings small"),
            html.P(
                "Includes a round under review: the last published values are used until "
                "it is republished.",
                className="ch-ribbon warn small",
            )
            if s.under_review
            else None,
            html.Div(
                [
                    stat_card(
                        "Rounds played",
                        "slate",
                        f"{s.played:,} of {s.counted_rounds:,}",
                        f"missed {s.missed:,}",
                    ),
                    stat_card(
                        "Recoveries",
                        "teal",
                        f"{s.recoveries:,}",
                        f"recovery rate {_pct(s.recovery_rate)}"
                        if s.played
                        else "no rounds played yet",
                    ),
                    stat_card(
                        "Top-10 finishes", "gold", f"{s.qualifying_top10:,}", "with a recovery"
                    ),
                    stat_card("Allocated", "violet", c.credits(s.allocated), "virtual credits"),
                    stat_card("Returned", "green", c.credits(s.returned), "virtual credits"),
                    stat_card(
                        "Net",
                        "blue",
                        lbu.signed(s.net),
                        [
                            html.Span("return on allocation "),
                            html.Span(_pct(s.roi), className=lbu.tone(s.roi)),
                        ]
                        if s.roi is not None
                        else "nothing allocated yet",
                        value_cls=lbu.tone(s.net),
                    ),
                ],  # fmt: skip
                className="me-stats",
            ),
            html.P(
                f"Based on {lbu.plural(s.played, 'counted competitive round')} you played"
                + (f" · {' · '.join(others)}" if others else "")
                + ".",
                className="muted small me-stats-note",
            ),
            html.Details(
                [
                    html.Summary("How your statistics are calculated"),
                    html.P(note, className="muted small"),
                ],
                className="ch-details me-method",
            ),  # fmt: skip
        ],  # fmt: skip
        className="ch-card me-summary",
    )


stat_card = c.stat_card  # shared with the Your Result cards (components)


# ------------------------------------------------------------------ charts
def _figure(height: int = 220) -> go.Figure:
    fig = charts._base(go.Figure(), height)
    fig.update_layout(
        showlegend=True,
        legend={"orientation": "h", "y": 1.12, "x": 0, "font": {"color": charts.MUTED, "size": 11}},
        margin={"l": 44, "r": 8, "t": 28, "b": 24},
        xaxis={"gridcolor": charts.GRID, "tickfont": {"color": charts.MUTED, "size": 10},
               "type": "category"},
        yaxis={"gridcolor": charts.GRID, "tickfont": {"color": charts.MUTED, "size": 10},
               "rangemode": "tozero"},
    )  # fmt: skip
    return fig


def _ticks(fig, n: int) -> None:
    """Rounds numbered 1..n on the axis (thinned when many); the match window and code
    appear on hover, so no technical identifier is shown as an axis label."""
    fig.update_xaxes(type="linear", tickmode="auto" if n > 12 else "linear", dtick=1,
                     tick0=1, nticks=min(n, 12), tickformat="d",
                     title={"text": "Counted round", "font": {"color": charts.MUTED,
                                                               "size": 10}})  # fmt: skip


def _hover(p) -> str:
    return f"{p.window} · {p.round_code}" if p.window else p.round_code


def locked_chart(title, have: int, what: str) -> html.Div:
    """The compact placeholder shown until a chart has three eligible rounds."""
    have = min(have, CHART_MIN_ROUNDS)
    return html.Div(
        [
            title,
            html.Div(
                [
                    html.P(f"Your {what} chart will become available after {CHART_MIN_ROUNDS} "
                           "eligible rounds.", className="small"),
                    html.Div(
                        [html.Span(className="me-lock-seg on" if i < have else "me-lock-seg")
                         for i in range(CHART_MIN_ROUNDS)],
                        className="me-lock-segs", **{"aria-hidden": "true"},
                    ),
                    html.Span(f"{have} of {CHART_MIN_ROUNDS} eligible rounds completed",
                              className="muted small"),
                ],
                className="me-chart-locked",
            ),
        ],
        className="ch-card me-chart-card locked",
    )  # fmt: skip


def _graph(fig, label: str) -> html.Div:
    """The chart with an accessible name (dcc.Graph takes no ARIA attributes)."""
    return html.Div(
        dcc.Graph(figure=fig, config={"displayModeBar": False, "responsive": True},
                  className="me-chart"),
        role="img", **{"aria-label": label},
    )  # fmt: skip


def allocation_chart(s) -> html.Div:
    title = html.H2("Cumulative virtual allocation and return", className="ch-h2 me-chart-title")
    if s.allocation_rounds < CHART_MIN_ROUNDS:
        return locked_chart(title, s.allocation_rounds, "allocation and return")
    xs = list(range(1, len(s.allocation_series) + 1))
    hover = [_hover(p) for p in s.allocation_series]
    fig = _figure()
    _ticks(fig, len(xs))
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=[float(p.value_a) for p in s.allocation_series],
            name="Allocated",
            mode="lines+markers",
            line={"color": charts.MUTED, "dash": "dash"},
            customdata=hover,
            hovertemplate="%{customdata}<br>Allocated %{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=[float(p.value_b) for p in s.allocation_series],
            name="Returned",
            mode="lines+markers",
            line={"color": charts.TEAL},
            customdata=[[h, p.detail] for h, p in zip(hover, s.allocation_series, strict=True)],
            hovertemplate="%{customdata[0]}<br>Returned %{y:,.2f}<br>%{customdata[1]}"
            "<extra></extra>",
        )
    )
    return html.Div(
        [title, _graph(fig, "Cumulative virtual credits allocated and returned by round"),
         html.P("Counted competitive rounds you played, oldest first. Virtual credits.",
                className="muted small")],
        className="ch-card me-chart-card",
    )  # fmt: skip


def points_chart(s) -> html.Div:
    name = s.points_championship
    title = html.H2("Cumulative championship points" + (f" · {name}" if name else ""),
                    className="ch-h2 me-chart-title")  # fmt: skip
    if s.points_rounds < CHART_MIN_ROUNDS:
        return locked_chart(title, s.points_rounds, "championship points")
    fig = _figure()
    fig.update_layout(showlegend=False)
    _ticks(fig, len(s.points_series))
    fig.add_trace(
        go.Scatter(
            x=list(range(1, len(s.points_series) + 1)),
            y=[float(p.value_a) for p in s.points_series],
            mode="lines+markers",
            line={"color": charts.AMBER, "shape": "hv"},
            name="Points",
            customdata=[[_hover(p), p.detail] for p in s.points_series],
            hovertemplate="%{customdata[0]}<br>%{y:.0f} pts<br>%{customdata[1]}<extra></extra>",
        )
    )
    note = (
        "Published points from this championship's counted rounds only; points never carry "
        "between championships."
    )
    if s.scope is None and name:
        note += " Showing your most recent championship; choose another above."
    return html.Div(
        [
            title,
            _graph(fig, f"Cumulative championship points in {name}"),
            html.P(note, className="muted small"),
        ],
        className="ch-card me-chart-card",
    )


# ------------------------------------------------------------------ history table
def status_text(r) -> str:
    if r.round_void:
        return "Round void · refunded"
    if r.entry_refunded:
        return "Refunded (all void)"
    return {
        "under_review": "Under review",
        "provisional": "Provisional",
        "locked": "Awaiting results",
        "unpublished": "Final (results not published)",
        "final": f"Corrected (v{r.revision})" if r.corrected else "Final",
    }.get(r.state, r.state)


def championship_text(r) -> str:
    if r.championship is None:
        return "Assignment pending" if r.classification == "competitive" else "—"
    role = {"counted": "counted", "practice": "practice", "void": "void",
            "not_counted": "not counted", "pending": "result pending"}.get(
        r.championship_role or "", "")  # fmt: skip
    return f"{r.championship} · {role}" if role else r.championship


def history_table(hist, local) -> html.Div:
    rows = []
    for r in hist.rows:
        returned = lbu.num(r.gross)
        if r.gross is None and r.current_gross is not None:
            returned = f"{lbu.num(r.current_gross)} so far"
        pts = "—"
        if r.weekly_points is not None:
            pts = str(r.weekly_points) + ("" if r.counts_toward_championship
                                          else " (not counted)")  # fmt: skip
        rank = "—" if r.rank is None else ("=" if r.shared else "") + f"{r.rank}"
        rnd = [
            html.Span(r.window or r.round_code, className="me-round"),
            html.Span(r.round_code, className="lb-code") if r.window else None,
        ]
        rows.append(html.Tr([
            lbu.cell(rnd, "Round", "me-round-cell"),
            lbu.cell(f"{local(r.deadline_at.isoformat())}", "Deadline", "txt small"),
            lbu.cell(championship_text(r), "Championship", "txt small me-champ-cell"),
            lbu.cell({"competitive": "Competitive", "practice": "Practice"}.get(
                r.classification or "", "—"), "Type", "txt"),
            lbu.cell(status_text(r), "Status", "txt warn" if r.state == "under_review"
                     else "txt"),
            lbu.cell(returned, "Returned", "num strong"),
            lbu.cell(lbu.signed(r.net), "Net", "num " + lbu.tone(r.net)),
            lbu.cell(lbu.RECOVERY_TEXT.get(r.recovery or "", "—"), "Recovery", "txt"),
            lbu.cell(rank, "Rank", "rank"),
            lbu.cell(pts, "Points", "num strong"),
            lbu.cell(html.Button("Details", id={"t": "hist-open", "i": r.round_code},
                                 className="ch-btn ghost small"), "", "c"),
        ]))  # fmt: skip
    head = ["Round", "Deadline", "Championship", "Type", "Status", "Returned", "Net",
            "Recovery", "Rank", "Points", ""]  # fmt: skip
    numeric = {"Returned", "Net", "Points"}
    return html.Div(
        [
            html.H2("Your entries", className="ch-h2"),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th(
                                        h,
                                        className="num"
                                        if h in numeric
                                        else "rank"
                                        if h == "Rank"
                                        else "c"
                                        if not h
                                        else "txt",
                                    )
                                    for h in head
                                ]  # fmt: skip
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    className="ch-table lb lb-cards me-hist-table",
                ),
                className="ch-table-wrap",
            ),
            html.P(
                "Newest first. Values are your published official results; practice, void "
                "and refunded entries are included.",
                className="muted small",
            ),
        ],  # fmt: skip
        className="ch-card",
    )


# ------------------------------------------------------------------ drill-down
def detail(service, local, stream: str, code: str) -> html.Div:
    b = persist.backend_of(service)
    p = persist.participant(service)
    if b is None or p is None:
        return None
    from diski9.backend.services import challenge_history as ch
    from diski9.backend.services import leaderboards as lb

    try:
        rid = ch.my_round_code_visible(b.engine, p, code, stream=stream,
                                       include_development=b.show_development)  # fmt: skip
        if rid is None:
            return html.Div("That entry is not available.", className="ch-ribbon warn")
        res = results_ui.fetch(service, rid)
        official = lb.my_round_result(b.engine, p, rid, include_development=b.show_development)
        rec = _record(service, b, p, rid)
    except Exception:  # noqa: BLE001
        return html.Div("This entry's details are temporarily unavailable.",
                        className="ch-ribbon warn")  # fmt: skip
    head = [html.H2(lbu.round_title(_window_of(b, rid), code), className="ch-h2")]
    if official is not None and official.published:
        rank = "—" if official.rank is None else f"#{official.rank}" + (
            " (shared)" if official.shared else "")  # fmt: skip
        pts = "—" if official.weekly_points is None else f"{official.weekly_points} pts"
        label = ("Last published official result (under review, no longer definitive)"
                 if official.under_review else "Official result")  # fmt: skip
        head.append(
            html.Div(
                [
                    html.Strong(label + ": "),
                    f"rank {rank} · returned {lbu.num(official.gross)} · {pts}",
                    html.Span(f" · {official.championship_note}", className="muted")
                    if official.championship_note
                    else None,
                ],
                className="ch-ribbon warn" if official.under_review else "ch-ribbon ok",
            )
        )
        if official.under_review:
            head.append(
                html.P(
                    "Below: the current settlement, which is provisional until the "
                    "round is re-finalised and republished.",
                    className="muted small",
                )
            )
    from . import achievements_ui

    head.append(achievements_ui.round_chips(service, rid, stream))  # published result only
    panel = results_ui.panel(res, rec, local) if res is not None else [
        html.P("No settlement for this entry yet.", className="muted small")]  # fmt: skip
    return html.Div([*head, *panel], className="me-hist-detail")


def _window_of(b, rid) -> str:
    """The round's friendly label for the drill-down heading (presentation only)."""
    from diski9.backend.services import leaderboards as lb
    from diski9.backend.services import rounds as rsvc

    try:
        v = rsvc.get_round(b.engine, rid)
        return lb.window_label(v.window_start_at, v.window_end_at)
    except Exception:  # noqa: BLE001 - the round code is shown instead
        return ""


def _record(service, b, p, rid):
    """Match names for the drill-down from the participant's stored submission."""
    from diski9.backend.services import entries
    from diski9.backend.services import rounds as rsvc

    try:
        view = rsvc.get_round(b.engine, rid)
        snap = rsvc.published_snapshot(b.engine, rid)
        entry = entries.get_entry(b.engine, p, rid)
        return persist.submitted_record(service, view, snap, entry)
    except Exception:  # noqa: BLE001 - fixture ids are shown instead
        return None


__all__ = ["ALL", "body", "detail", "scope_options", "section", "tabs"]
