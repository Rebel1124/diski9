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
                    dcc.Link(
                        "Join this week's challenge", href="/challenge", className="ch-btn primary"
                    ),
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
            text = (f"{st.name}: #{st.rank}" + (" (shared)" if st.shared else "")
                    + f" · {st.points} pts · {status}")  # fmt: skip
        else:
            text = f"{st.name}: no ranked round yet · {status}"
        standing_lines.append(html.Li(text))
    if not standing_lines:
        standing_lines = [html.Li("No championship entries yet in this view.")]
    note = (
        "Competitive population: your ranked entries in rounds that counted toward a "
        "championship. Refunded entries, practice and void rounds, rounds restored without "
        "championship points and rounds awaiting results are not included; they are listed "
        "below. Return on allocation = net ÷ allocated."
    )
    others = []
    if s.practice_entries:
        word = "entry" if s.practice_entries == 1 else "entries"
        others.append(f"Practice: {s.practice_entries} {word}, "
                      f"{s.practice_recoveries} recovered")  # fmt: skip
    if s.refunded_entries:
        others.append(f"Refunded (all void): {s.refunded_entries}")
    if s.void_rounds:
        others.append(f"Void rounds: {s.void_rounds}")
    if s.not_counted_entries:
        others.append(f"Restored without championship points: {s.not_counted_entries}")
    if s.awaiting_results:
        others.append(f"Awaiting official results: {s.awaiting_results}")
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
            html.Div(
                [
                    c.metric(
                        "Rounds played", f"{s.played} of {s.counted_rounds}", f"missed {s.missed}"
                    ),
                    c.metric(
                        "Recoveries",
                        str(s.recoveries),
                        f"recovery rate {_pct(s.recovery_rate)}"
                        if s.played
                        else "no rounds played yet",
                    ),
                    c.metric("Top-ten finishes", str(s.qualifying_top10), "with a recovery"),
                    c.metric("Allocated", c.credits(s.allocated), "virtual credits"),
                    c.metric("Returned", c.credits(s.returned), "virtual credits"),
                    c.metric(
                        "Net",
                        f"{s.net:+,.2f}",
                        f"return on allocation {_pct(s.roi)}"
                        if s.roi is not None
                        else "nothing allocated yet",
                    ),
                ],  # fmt: skip
                className="ch-metrics six me-metrics",
            ),
            html.P(note, className="muted small"),
            html.P(" · ".join(others), className="muted small") if others else None,
            html.P(
                "Includes a round under review: the last published values are used until "
                "it is republished.",
                className="ch-ribbon warn small",
            )
            if s.under_review
            else None,
        ],  # fmt: skip
        className="ch-card me-summary",
    )


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
    """Round codes on the axis only while they fit; otherwise on hover only."""
    fig.update_xaxes(showticklabels=n <= 6, tickangle=0)


def _graph(fig, label: str) -> html.Div:
    """The chart with an accessible name (dcc.Graph takes no ARIA attributes)."""
    return html.Div(
        dcc.Graph(figure=fig, config={"displayModeBar": False, "responsive": True},
                  className="me-chart"),
        role="img", **{"aria-label": label},
    )  # fmt: skip


def allocation_chart(s) -> html.Div:
    title = html.Div("Cumulative virtual allocation and return", className="ch-h2 small-h")
    if not s.allocation_series:
        return html.Div(
            [title, html.P("No counted competitive rounds played yet.", className="muted small")],
            className="ch-card",
        )
    xs = [p.round_code for p in s.allocation_series]
    fig = _figure()
    _ticks(fig, len(xs))
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=[float(p.value_a) for p in s.allocation_series],
            name="Allocated",
            mode="lines+markers",
            line={"color": charts.MUTED, "dash": "dash"},
            hovertemplate="%{x}<br>Allocated %{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=[float(p.value_b) for p in s.allocation_series],
            name="Returned",
            mode="lines+markers",
            line={"color": charts.TEAL},
            customdata=[p.detail for p in s.allocation_series],
            hovertemplate="%{x}<br>Returned %{y:,.2f}<br>%{customdata}<extra></extra>",
        )
    )
    return html.Div(
        [title, _graph(fig, "Cumulative virtual credits allocated and returned by round"),
         html.P("Counted competitive rounds you played, oldest first. Virtual credits.",
                className="muted small")],
        className="ch-card",
    )  # fmt: skip


def points_chart(s) -> html.Div:
    name = s.points_championship
    title = html.Div("Cumulative championship points" + (f" · {name}" if name else ""),
                     className="ch-h2 small-h")  # fmt: skip
    if not s.points_series:
        return html.Div(
            [title, html.P("No counted rounds in this championship yet.", className="muted small")],
            className="ch-card",
        )
    fig = _figure()
    fig.update_layout(showlegend=False)
    _ticks(fig, len(s.points_series))
    fig.add_trace(
        go.Scatter(
            x=[p.round_code for p in s.points_series],
            y=[float(p.value_a) for p in s.points_series],
            mode="lines+markers",
            line={"color": charts.AMBER, "shape": "hv"},
            name="Points",
            customdata=[p.detail for p in s.points_series],
            hovertemplate="%{x}<br>%{y:.0f} pts<br>%{customdata}<extra></extra>",
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
        className="ch-card",
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
        rows.append(html.Tr([
            lbu.cell(r.round_code, "Round", "strong"),
            lbu.cell(f"{local(r.deadline_at.isoformat())}", "Deadline", "small"),
            lbu.cell(championship_text(r), "Championship", "small"),
            lbu.cell({"competitive": "Competitive", "practice": "Practice"}.get(
                r.classification or "", "—"), "Type"),
            lbu.cell(status_text(r), "Status", "warn" if r.state == "under_review" else ""),
            lbu.cell(returned, "Returned", "num strong"),
            lbu.cell(lbu.signed(r.net), "Net", "num"),
            lbu.cell(lbu.RECOVERY_TEXT.get(r.recovery or "", "—"), "Recovery"),
            lbu.cell(rank, "Rank", "num"),
            lbu.cell(pts, "Points", "num strong"),
            lbu.cell(html.Button("Details", id={"t": "hist-open", "i": r.round_code},
                                 className="ch-btn ghost small"), "", "c"),
        ]))  # fmt: skip
    head = ["Round", "Deadline", "Championship", "Type", "Status", "Returned", "Net",
            "Recovery", "Rank", "Points", ""]  # fmt: skip
    numeric = {"Returned", "Net", "Rank", "Points"}
    return html.Div(
        [
            html.H2("Your entries", className="ch-h2"),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [html.Th(h, className="num" if h in numeric else "") for h in head]
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
    head = [html.H2(f"Round {code}", className="ch-h2")]
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
    panel = results_ui.panel(res, rec, local) if res is not None else [
        html.P("No settlement for this entry yet.", className="muted small")]  # fmt: skip
    return html.Div([*head, *panel], className="me-hist-detail")


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
