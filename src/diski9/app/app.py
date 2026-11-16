"""Diski 9 Statistical Screener — Plotly Dash application.

Run: ``uv run diski9 serve`` (defaults to http://127.0.0.1:8050).

The results list is a plain HTML table (desktop) / card list (phones) rendered
server-side, ten fixtures per page. Ranking is a single control ("Rank by");
clicking a sortable column header changes that control. Dash's DataTable was
removed (deprecated in Dash 4); Dash AG Grid was evaluated but not adopted,
because its client-side sorting would conflict with server-side ranking and
pagination shared with the phone cards, for no visual gain over a styled table.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from diski9.screener.rank import DEFAULT_DIRECTION, KICKOFF_DIRECTIONS

from .data import DIRECTIONS, PAGE_SIZE, ScreenerData, paginate, valid_direction
from .views import FORM_TOOLTIP, basis_help, info, pill, render_detail, signed_class

ASSETS = Path(__file__).parent / "assets"
MARKETS = [("1X2", "Match result"), ("BTTS", "Both teams to score"), ("OU25", "Over/Under 2.5")]
STAT_PAIR = {  # header toggle between the two statistical directions of a market
    "1X2": ("home_stronger", "away_stronger"),
    "BTTS": ("btts_yes", "btts_no"),
    "OU25": ("over", "under"),
}


def columns_for(market: str) -> list[dict]:
    """Column definitions: id, label, alignment, sort key (None = not sortable)."""
    base = [
        {"id": "kickoff", "label": "Kickoff", "align": "left", "sort": "kickoff"},
        {"id": "league", "label": "League", "align": "left", "sort": None},
        {"id": "home", "label": "Home", "align": "left", "sort": None},
        {"id": "away", "label": "Away", "align": "left", "sort": None},
    ]
    if market == "1X2":
        return base + [
            {"id": "home_metric", "label": "Home form", "align": "right", "sort": None},
            {"id": "away_metric", "label": "Away form", "align": "right", "sort": None},
            {"id": "indicator", "label": "Form difference", "align": "right", "sort": "stat"},
            {"id": "odds", "label": "Odds H · D · A", "align": "right", "sort": None},
            {"id": "limited", "label": "Data", "align": "left", "sort": None},
        ]
    yes, no, odds = (
        ("BTTS Yes", "BTTS No", "Odds Yes · No")
        if market == "BTTS"
        else ("Over 2.5", "Under 2.5", "Odds Over · Under")
    )
    return base + [
        {"id": "home_metric", "label": "Home rate", "align": "right", "sort": None},
        {"id": "away_metric", "label": "Away rate", "align": "right", "sort": None},
        {"id": "indicator", "label": yes, "align": "right", "sort": "stat"},
        {"id": "complement", "label": no, "align": "right", "sort": None},
        {"id": "odds", "label": odds, "align": "right", "sort": None},
        {"id": "limited", "label": "Data", "align": "left", "sort": None},
    ]


def threshold_config(market: str, direction: str) -> dict:
    """Thresholds apply to statistical rankings only."""
    if direction in KICKOFF_DIRECTIONS:
        return {
            "min": 0,
            "max": 1,
            "step": 1,
            "value": 0,
            "disabled": True,
            "label": "Threshold",
            "marks": {0: "Off for kickoff ranking", 1: ""},
        }
    if market == "1X2":
        if direction == "evenly_matched":
            return {
                "min": 0,
                "max": 5,
                "step": 0.25,
                "value": 5,
                "disabled": False,
                "label": "Maximum form difference",
                "marks": {0: "0", 2.5: "2.5", 5: "Any"},
            }
        return {
            "min": 0,
            "max": 5,
            "step": 0.25,
            "value": 0,
            "disabled": False,
            "label": "Minimum form difference",
            "marks": {0: "Any", 2.5: "2.5", 5: "5"},
        }
    outcome = {
        "btts_yes": "BTTS Yes",
        "btts_no": "BTTS No",
        "over": "Over 2.5",
        "under": "Under 2.5",
    }[direction]
    return {
        "min": 0,
        "max": 100,
        "step": 5,
        "value": 0,
        "disabled": False,
        "label": f"Minimum {outcome} indicator",
        "marks": {0: "Any", 50: "50%", 100: "100%"},
    }


def create_app(data: ScreenerData) -> Dash:
    app = Dash(
        __name__,
        assets_folder=str(ASSETS),
        title="Diski 9 Screener",
        update_title=None,
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
        suppress_callback_exceptions=True,
    )
    app.server.config["DISKI9_DATA"] = data
    app.layout = lambda: build_layout(data)
    register_callbacks(app, data)
    return app


def build_layout(data: ScreenerData) -> html.Div:
    snap = data.snapshot()
    leagues = data.available_leagues()
    today = data.clock().astimezone(data.tz).date()
    banner = []
    if snap.stale:
        banner.append(
            html.Div(
                "New results were loaded after the screener was last calculated. "
                "Run `diski9 refresh-data` to update.",
                className="banner warn",
            )
        )
    if not leagues:
        banner.append(
            html.Div(
                "No screener results are cached yet. Run `diski9 setup` (first time) "
                "or `diski9 refresh-data`.",
                className="banner warn",
            )
        )
    return html.Div(
        [
            html.Header(
                [
                    html.Div(
                        [
                            html.Span("Diski 9", className="brand"),
                            html.Span("Statistical Screener", className="subtitle"),
                        ]
                    ),
                    html.Div(
                        f"Times in {data.tz_label} · statistics calculated "
                        f"{data.local(snap.cache_calculated_at)}",
                        className="muted small",
                    ),
                ],
                className="topbar",
            ),
            *banner,
            dcc.Tabs(
                id="market",
                value="1X2",
                className="tabs",
                children=[
                    dcc.Tab(
                        label=lbl, value=val, className="tab", selected_className="tab--selected"
                    )
                    for val, lbl in MARKETS
                ],
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Leagues"),
                            dcc.Checklist(
                                id="leagues",
                                options=[{"label": n, "value": c} for c, n in leagues],
                                value=[c for c, _ in leagues],
                                inline=True,
                                className="chips",
                            ),
                        ],
                        className="filter",
                    ),
                    html.Div(
                        [
                            html.Label("Dates"),
                            dcc.DatePickerRange(
                                id="dates",
                                start_date=today,
                                end_date=today + timedelta(days=14),
                                display_format="D MMM",
                                minimum_nights=0,
                                className="dates",
                            ),
                        ],
                        className="filter",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Form basis"),
                                    info(basis_help("1X2"), "About form basis"),
                                ],
                                className="label-row",
                                id="basis-label",
                            ),
                            dcc.RadioItems(
                                id="basis",
                                value="venue",
                                inline=True,
                                className="segmented",
                                options=[
                                    {"label": "Venue-specific", "value": "venue"},
                                    {"label": "Overall", "value": "overall"},
                                ],
                            ),
                        ],
                        className="filter",
                    ),
                    html.Div(
                        [
                            html.Label("Rank by"),
                            dcc.Dropdown(
                                id="direction",
                                clearable=False,
                                searchable=False,
                                className="dropdown",
                                options=[
                                    {"label": lbl, "value": v} for v, lbl in DIRECTIONS["1X2"]
                                ],
                                value=DEFAULT_DIRECTION,
                            ),
                        ],
                        className="filter",
                    ),
                    html.Div(
                        [
                            html.Label("Threshold", id="threshold-label"),
                            dcc.Slider(
                                id="threshold",
                                min=0,
                                max=1,
                                step=1,
                                value=0,
                                disabled=True,
                                className="slider",
                            ),
                        ],
                        className="filter",
                    ),
                ],
                className="filters",
            ),
            html.Div(id="legend", className="legend"),
            html.Div(
                [
                    html.Div(id="summary", className="muted small"),
                    html.Div(id="ranked-by", className="muted small"),
                ],
                className="results-head",
            ),
            html.Div(id="results-table", className="table-wrap"),
            html.Div(id="results-cards", className="cards"),
            html.Div(id="empty"),
            html.Div(
                [
                    html.Button("‹ Previous", id="prev", className="pager-btn", n_clicks=0),
                    html.Span(id="page-label", className="muted small"),
                    html.Button("Next ›", id="next", className="pager-btn", n_clicks=0),
                ],
                className="pager",
                id="pager",
            ),
            dcc.Store(id="page", data=1),
            dcc.Store(id="selected"),
            html.Div(id="detail", className="detail-holder"),
            html.Footer(
                "Diski 9 is a research tool. Historical indicators describe past matches and are "
                "not predictions. Consensus odds are reference values, not offers. No betting "
                "value or staking advice is provided.",
                className="footer muted small",
            ),
        ],
        className="page",
    )


def register_callbacks(app: Dash, data: ScreenerData) -> None:
    @app.callback(
        Output("direction", "options"),
        Output("direction", "value"),
        Input("market", "value"),
        Input({"type": "sort", "key": ALL}, "n_clicks"),
        State("direction", "value"),
    )
    def update_direction(market, _sort_clicks, current):
        opts = [{"label": lbl, "value": v} for v, lbl in DIRECTIONS[market]]
        trig = ctx.triggered_id
        if isinstance(trig, dict) and trig.get("type") == "sort":
            if not any(t["value"] for t in ctx.triggered):  # headers re-rendered, not clicked
                return opts, no_update
            return opts, header_sort(market, trig["key"], current)
        return opts, valid_direction(market, current)

    @app.callback(
        Output("threshold", "min"),
        Output("threshold", "max"),
        Output("threshold", "step"),
        Output("threshold", "value"),
        Output("threshold", "marks"),
        Output("threshold", "disabled"),
        Output("threshold-label", "children"),
        Output("basis-label", "children"),
        Output("legend", "children"),
        Input("market", "value"),
        Input("direction", "value"),
    )
    def update_controls(market, direction):
        c = threshold_config(market, valid_direction(market, direction))
        basis_label = [html.Label("Form basis"), info(basis_help(market), "About form basis")]
        legend = (
            [
                html.Span("Form scores are Diski Form Scores (0–5)", className="muted small"),
                info(FORM_TOOLTIP, "About Diski Form Score"),
            ]
            if market == "1X2"
            else [
                html.Span(
                    "Rates use up to ten current-season matches; indicators are historical, "
                    "not predicted probabilities",
                    className="muted small",
                )
            ]
        )
        return (
            c["min"],
            c["max"],
            c["step"],
            c["value"],
            c["marks"],
            c["disabled"],
            c["label"],
            basis_label,
            legend,
        )

    @app.callback(
        Output("results-table", "children"),
        Output("results-cards", "children"),
        Output("summary", "children"),
        Output("ranked-by", "children"),
        Output("empty", "children"),
        Output("page-label", "children"),
        Output("prev", "disabled"),
        Output("next", "disabled"),
        Output("page", "data"),
        Output("pager", "style"),
        Input("market", "value"),
        Input("leagues", "value"),
        Input("dates", "start_date"),
        Input("dates", "end_date"),
        Input("basis", "value"),
        Input("direction", "value"),
        Input("threshold", "value"),
        Input("prev", "n_clicks"),
        Input("next", "n_clicks"),
        State("page", "data"),
        State("selected", "data"),
    )
    def update_results(
        market, leagues, start, end, basis, direction, threshold, _p, _n, page, selected
    ):
        trig = ctx.triggered_id
        if trig == "prev":
            page = (page or 1) - 1
        elif trig == "next":
            page = (page or 1) + 1
        else:  # any filter / ranking / market change resets to page 1
            page = 1
        return results_payload(
            data, market, leagues, start, end, basis, direction, threshold, page, selected
        )

    @app.callback(
        Output("selected", "data"),
        Input({"type": "row", "index": ALL}, "n_clicks"),
        Input({"type": "fx", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def select_fixture(_rows, _cards):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not any(t["value"] for t in ctx.triggered):
            return no_update
        return int(trig["index"])

    @app.callback(
        Output("detail", "children"),
        Input("selected", "data"),
        Input("market", "value"),
        Input("basis", "value"),
    )
    def update_detail(fid, market, basis):
        r, ov, official = data.detail(fid, basis) if fid else (None, None, {})
        return render_detail(r, ov, official, market, data)

    app.clientside_callback(
        """function(fid) {
            if (fid && window.innerWidth < 720) {
                const el = document.getElementById('detail');
                if (el) { setTimeout(() => el.scrollIntoView({behavior: 'smooth'}), 150); }
            }
            return window.dash_clientside.no_update;
        }""",
        Output("detail", "className"),
        Input("selected", "data"),
    )


def header_sort(market: str, key: str, current: str | None) -> str:
    """Clicking 'Kickoff' toggles earliest/latest; clicking the indicator header
    toggles the market's two statistical rankings."""
    if key == "kickoff":
        return "kickoff_latest" if current == "kickoff_earliest" else "kickoff_earliest"
    first, second = STAT_PAIR[market]
    return second if current == first else first


def _threshold_value(market: str, direction: str, value: float | None) -> float | None:
    if value is None or direction in KICKOFF_DIRECTIONS:
        return None
    if market == "1X2":
        if direction == "evenly_matched":
            return None if value >= 5 else float(value)
        return None if value <= 0 else float(value)
    return None if value <= 0 else value / 100


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def results_payload(
    data, market, leagues, start, end, basis, direction, threshold, page, selected=None
):
    """Pure function behind the results callback (also used by tests)."""
    direction = valid_direction(market, direction)
    thr = _threshold_value(market, direction, threshold)
    results = (
        data.filtered(market, leagues, _date(start), _date(end), basis, direction, thr)
        if leagues
        else []
    )
    pg = paginate(results, page)
    rows = [data.row(market, r) for r in pg.results]
    if not leagues:
        empty = html.Div("Select at least one league to see fixtures.", className="empty")
    elif not results:
        empty = html.Div(
            "No fixtures match these filters. Try a wider date range or a lower threshold.",
            className="empty",
        )
    else:
        empty = None
    label = dict(DIRECTIONS[market])[direction]
    table = results_table(market, direction, rows, selected) if rows else None
    cards = [fixture_card(market, row, selected) for row in rows]
    pager_style = {"display": "none"} if pg.total <= PAGE_SIZE else {}
    return (
        table,
        cards,
        pg.summary,
        f"Ranked by: {label}" if results else "",
        empty,
        f"Page {pg.page} of {pg.pages}",
        pg.page <= 1,
        pg.page >= pg.pages,
        pg.page,
        pager_style,
    )


def _header(col: dict, market: str, direction: str) -> html.Th:
    cls = f"col-{col['align']}"
    if not col["sort"]:
        return html.Th(col["label"], className=cls)
    if col["sort"] == "kickoff":
        active = direction in KICKOFF_DIRECTIONS
        arrow = ("▲" if direction == "kickoff_earliest" else "▼") if active else "↕"
    else:
        active = direction in STAT_PAIR[market] or (
            market == "1X2" and direction == "evenly_matched"
        )
        arrow = (
            "↕"
            if not active
            else ("▼" if direction in ("home_stronger", "btts_yes", "over") else "▲")
        )
    return html.Th(
        html.Button(
            [col["label"], html.Span(f" {arrow}", className="arrow")],
            id={"type": "sort", "key": col["sort"]},
            className="sort-btn" + (" active" if active else ""),
            n_clicks=0,
            title="Change ranking",
        ),
        className=cls,
    )


def results_table(
    market: str, direction: str, rows: list[dict], selected: int | None
) -> html.Table:
    cols = columns_for(market)
    body = []
    for row in rows:
        cells = []
        for col in cols:
            cid = col["id"]
            cls = f"col-{col['align']}"
            if cid == "indicator":
                value = row["indicator_display"]
                cls += " strong " + (
                    signed_class(row["indicator"]).replace("num", "") if market == "1X2" else ""
                )
            elif cid == "complement":
                value = row["complement_display"]
            elif cid == "odds":
                value = [row["odds"]] + (
                    [" ", pill("stale", "warn subtle")] if row["odds_status"] == "stale" else []
                )
                cls += f" odds-{row['odds_status']}"
            elif cid == "limited":
                value = pill("Limited data", "warn subtle") if row["limited"] else ""
            else:
                value = row[cid]
            cells.append(html.Td(value, className=cls))
        body.append(
            html.Tr(
                cells,
                id={"type": "row", "index": row["id"]},
                n_clicks=0,
                className="row" + (" selected" if row["id"] == selected else ""),
            )
        )
    return html.Table(
        [html.Thead(html.Tr([_header(c, market, direction) for c in cols])), html.Tbody(body)],
        className="results",
    )


def fixture_card(market: str, row: dict, selected: int | None) -> html.Button:
    if market == "1X2":
        metric = f"Form difference {row['indicator_display']}"
        sub = f"Form {row['home_metric']} v {row['away_metric']}"
        metric_cls = "card-metric " + signed_class(row["indicator"]).replace("num", "")
    else:
        yes, no = ("BTTS Yes", "No") if market == "BTTS" else ("Over 2.5", "Under")
        metric = f"{yes} {row['indicator_display']}"
        sub = f"{no} {row['complement_display']} · {row['home_metric']} / {row['away_metric']}"
        metric_cls = "card-metric"
    odds = row["odds"] if row["odds"] in ("No odds", "—") else f"Odds {row['odds']}"
    bottom = [html.Span(odds, className="muted small")]
    if row["odds_status"] == "stale":
        bottom.append(pill("stale odds", "warn subtle"))
    if row["limited"]:
        bottom.append(pill("Limited data", "warn subtle"))
    return html.Button(
        [
            html.Div(
                [html.Span(row["kickoff"]), html.Span(row["league"], className="pill subtle")],
                className="card-top muted small",
            ),
            html.Div(f"{row['home']} v {row['away']}", className="card-teams"),
            html.Div(
                [html.Span(metric, className=metric_cls), html.Span(sub, className="muted small")]
            ),
            html.Div(bottom, className="card-bottom"),
        ],
        id={"type": "fx", "index": row["id"]},
        className="fx-card" + (" selected" if row["id"] == selected else ""),
        n_clicks=0,
    )
