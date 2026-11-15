"""Diski 9 Statistical Screener — Plotly Dash application.

Run: ``uv run diski9 serve`` (defaults to http://127.0.0.1:8050).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update
from dash.dash_table.Format import Format, Scheme

from .data import DIRECTIONS, ScreenerData
from .views import render_detail

ASSETS = Path(__file__).parent / "assets"
FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
)
MARKETS = [
    ("1X2", "Match result"),
    ("BTTS", "Both teams to score"),
    ("OU25", "Over/Under 2.5"),
]


def columns_for(market: str, basis: str) -> list[dict]:
    pct = Format(precision=0, scheme=Scheme.percentage)
    two = Format(precision=2, scheme=Scheme.fixed)
    base = [
        {"id": "kickoff", "name": "Kickoff"},
        {"id": "league", "name": "League"},
        {"id": "home", "name": "Home"},
        {"id": "away", "name": "Away"},
    ]
    if market == "1X2":
        diff_name = "Venue-adj. difference" if basis == "venue" else "Raw difference"
        return base + [
            {"id": "home_metric", "name": "Home form", "type": "numeric", "format": two},
            {"id": "away_metric", "name": "Away form", "type": "numeric", "format": two},
            {"id": "indicator", "name": diff_name, "type": "numeric", "format": two},
            {"id": "sample", "name": "Matches"},
            {"id": "odds", "name": "Odds H · D · A"},
            {"id": "limited", "name": "Data"},
        ]
    yes, no, odds = (
        ("BTTS Yes", "BTTS No", "Odds Yes · No")
        if market == "BTTS"
        else ("Over 2.5", "Under 2.5", "Odds O · U")
    )
    return base + [
        {"id": "home_metric", "name": "Home rate"},
        {"id": "away_metric", "name": "Away rate"},
        {"id": "indicator", "name": yes, "type": "numeric", "format": pct},
        {"id": "complement", "name": no, "type": "numeric", "format": pct},
        {"id": "sample", "name": "Matches"},
        {"id": "odds", "name": odds},
        {"id": "limited", "name": "Data"},
    ]


def threshold_config(market: str, direction: str) -> dict:
    if market == "1X2":
        if direction == "evenly_matched":
            return {
                "min": 0,
                "max": 3,
                "step": 0.25,
                "value": 3,
                "label": "Maximum difference",
                "marks": {0: "0", 1: "1", 2: "2", 3: "Any"},
            }
        return {
            "min": 0,
            "max": 3,
            "step": 0.25,
            "value": 0,
            "label": "Minimum difference",
            "marks": {0: "Any", 1: "1", 2: "2", 3: "3"},
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
                "New fixture results were loaded after the screener was last calculated. "
                "Run `diski9 refresh-data` (or `diski9 screener-refresh`) to update.",
                className="banner warn",
            )
        )
    if not leagues:
        banner.append(
            html.Div(
                "No screener results are cached yet. Run `diski9 refresh-data` to calculate them.",
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
                        f"Statistics calculated {data.local(snap.cache_calculated_at)} · "
                        f"odds loaded {data.local(snap.loaded_at)} {data.tz_label}",
                        className="muted small",
                        id="freshness",
                    ),
                ],
                className="topbar",
            ),
            *banner,
            dcc.Tabs(
                id="market",
                value="1X2",
                children=[
                    dcc.Tab(
                        label=lbl, value=val, className="tab", selected_className="tab--selected"
                    )
                    for val, lbl in MARKETS
                ],
                className="tabs",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Leagues"),
                            dcc.Checklist(
                                id="leagues",
                                options=[{"label": name, "value": cid} for cid, name in leagues],
                                value=[cid for cid, _ in leagues],
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
                            html.Label("Form basis"),
                            dcc.RadioItems(
                                id="basis",
                                options=[
                                    {"label": "Venue-specific", "value": "venue"},
                                    {"label": "Overall", "value": "overall"},
                                ],
                                value="venue",
                                inline=True,
                                className="segmented",
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
                            ),
                        ],
                        className="filter wide",
                    ),
                    html.Div(
                        [
                            html.Label("Minimum", id="threshold-label"),
                            dcc.Slider(
                                id="threshold", min=0, max=3, step=0.25, value=0, className="slider"
                            ),
                        ],
                        className="filter wide",
                    ),
                ],
                className="filters",
            ),
            html.Div(id="count", className="muted small count"),
            html.Div(
                dash_table.DataTable(
                    id="table",
                    columns=columns_for("1X2", "venue"),
                    data=[],
                    sort_action="native",
                    page_action="none",
                    cell_selectable=True,
                    style_as_list_view=True,
                    style_table={"overflowX": "auto"},
                    style_cell={"textAlign": "left", "fontFamily": FONT_STACK, "fontSize": "14px"},
                    style_header={"fontFamily": FONT_STACK},
                    style_cell_conditional=[
                        {"if": {"column_type": "numeric"}, "textAlign": "right"}
                    ],
                ),
                className="table-wrap",
            ),
            html.Div(id="cards", className="cards"),
            dcc.Store(id="selected"),
            html.Div(id="empty", className="empty-holder"),
            html.Div(id="detail", className="detail-holder"),
            html.Footer(
                "Diski 9 is a research tool. Historical indicators describe past matches and are "
                "not predictions. Consensus odds are reference values, not offers. "
                "No betting value or staking advice is provided.",
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
    )
    def update_directions(market: str):
        opts = [{"label": lbl, "value": val} for val, lbl in DIRECTIONS[market]]
        return opts, opts[0]["value"]

    @app.callback(
        Output("threshold", "min"),
        Output("threshold", "max"),
        Output("threshold", "step"),
        Output("threshold", "value"),
        Output("threshold", "marks"),
        Output("threshold-label", "children"),
        Input("market", "value"),
        Input("direction", "value"),
    )
    def update_threshold(market: str, direction: str | None):
        valid = {v for v, _ in DIRECTIONS[market]}
        direction = direction if direction in valid else DIRECTIONS[market][0][0]
        c = threshold_config(market, direction)
        return c["min"], c["max"], c["step"], c["value"], c["marks"], c["label"]

    @app.callback(
        Output("table", "data"),
        Output("table", "columns"),
        Output("table", "active_cell"),
        Output("table", "sort_by"),
        Output("count", "children"),
        Output("empty", "children"),
        Output("cards", "children"),
        Input("market", "value"),
        Input("leagues", "value"),
        Input("dates", "start_date"),
        Input("dates", "end_date"),
        Input("basis", "value"),
        Input("direction", "value"),
        Input("threshold", "value"),
    )
    def update_table(market, leagues, start, end, basis, direction, threshold):
        return table_payload(data, market, leagues, start, end, basis, direction, threshold)

    @app.callback(
        Output("selected", "data"),
        Input("table", "active_cell"),
        Input({"type": "fx", "index": ALL}, "n_clicks"),
        State("table", "data"),
        prevent_initial_call=True,
    )
    def select_fixture(active_cell, _clicks, rows):
        trig = ctx.triggered_id
        if isinstance(trig, dict) and trig.get("type") == "fx":
            if not any(t["value"] for t in ctx.triggered):  # list re-rendered, not clicked
                return no_update
            return int(trig["index"])
        return selected_fixture(active_cell, rows)

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


def table_payload(data: ScreenerData, market, leagues, start, end, basis, direction, threshold):
    """Pure function behind the table callback (also used by tests)."""
    valid = {v for v, _ in DIRECTIONS[market]}
    if direction not in valid:
        direction = DIRECTIONS[market][0][0]
    thr = _threshold_value(market, direction, threshold)
    results = (
        data.filtered(market, leagues, _date(start), _date(end), basis, direction, thr)
        if leagues
        else []
    )
    rows = data.table_rows(market, results)
    if not leagues:
        empty = html.Div("Select at least one league to see fixtures.", className="empty")
    elif not rows:
        empty = html.Div(
            "No fixtures match these filters. Try a wider date range or a lower threshold.",
            className="empty",
        )
    else:
        empty = None
    label = dict(DIRECTIONS[market])[direction]
    count = f"{len(rows)} fixtures · ranked by: {label}" if rows else ""
    return (
        rows,
        columns_for(market, basis),
        None,
        [],
        count,
        empty,
        fixture_cards(data, market, basis, results),
    )


def fixture_cards(data: ScreenerData, market: str, basis: str, results: list[dict]) -> list:
    """Compact, tappable fixture list used on phone-sized screens."""
    cards = []
    for r, row in zip(results, data.table_rows(market, results), strict=True):
        f = r["fixture"]
        if market == "1X2":
            diff = row["indicator"]
            name = "Venue-adj." if basis == "venue" else "Raw diff."
            metric = f"{name} {diff:+.2f}" if diff is not None else f"{name} —"
            sub = (
                f"Form {row['home_metric']:.2f} / {row['away_metric']:.2f}"
                if row["home_metric"] is not None and row["away_metric"] is not None
                else "Form n/a"
            )
        else:
            yes = row["indicator"]
            lbl = ("BTTS Yes", "No") if market == "BTTS" else ("Over 2.5", "Under")
            metric = f"{lbl[0]} {yes * 100:.0f}%" if yes is not None else f"{lbl[0]} —"
            sub = (
                f"{lbl[1]} {row['complement'] * 100:.0f}% · "
                f"{row['home_metric']} / {row['away_metric']}"
                if yes is not None
                else ""
            )
        cards.append(
            html.Button(
                [
                    html.Div(
                        [
                            html.Span(data.local(f["kickoff"])),
                            html.Span(row["league"], className="pill subtle"),
                        ],
                        className="card-top muted small",
                    ),
                    html.Div(f"{f['home']} v {f['away']}", className="card-teams"),
                    html.Div(
                        [
                            html.Span(metric, className="card-metric"),
                            html.Span(sub, className="muted small"),
                        ]
                    ),
                    html.Div(
                        [html.Span(_odds_text(row["odds"]), className="muted small")]
                        + (
                            [html.Span(row["limited"], className="pill warn")]
                            if row["limited"]
                            else []
                        ),
                        className="card-bottom",
                    ),
                ],
                id={"type": "fx", "index": f["id"]},
                className="fx-card",
                n_clicks=0,
            )
        )
    return cards


def _odds_text(cell: str) -> str:
    return cell if cell in ("No odds", "Unavailable") else f"Odds {cell}"


def selected_fixture(active_cell: dict | None, rows: list[dict] | None):
    if not active_cell:
        return no_update
    if active_cell.get("row_id") is not None:
        return int(active_cell["row_id"])
    idx = active_cell.get("row")
    if rows and idx is not None and 0 <= idx < len(rows):
        return int(rows[idx]["id"])
    return None


def _threshold_value(market: str, direction: str, value: float | None) -> float | None:
    if value is None:
        return None
    if market == "1X2":
        if direction == "evenly_matched":
            return None if value >= 3 else float(value)
        return None if value <= 0 else float(value)
    return None if value <= 0 else value / 100


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None
