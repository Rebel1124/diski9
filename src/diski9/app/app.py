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
from dash.exceptions import PreventUpdate

from diski9.screener.rank import DEFAULT_DIRECTION, KICKOFF_DIRECTIONS

from .data import DIRECTIONS, PAGE_SIZE, ScreenerData, paginate, valid_direction
from .views import FORM_TOOLTIP, basis_help, info, pill, render_detail, signed_class

ASSETS = Path(__file__).parent / "assets"
MARKETS = [("1X2", "Match result"), ("BTTS", "Both teams to score"), ("OU25", "Over/Under 2.5")]
LIMITED_TITLE = {
    "1X2": "Limited data: fewer than five eligible matches for at least one team",
    "BTTS": "Limited data: fewer than six current-season matches for at least one team",
    "OU25": "Limited data: fewer than six current-season matches for at least one team",
}
THRESHOLD_DISABLED = KICKOFF_DIRECTIONS + ("evenly_matched",)
DEFAULT_BASIS = {"1X2": "venue", "BTTS": "overall", "OU25": "overall"}
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
    word, market_lbl = (
        ("BTTS", "Market Yes · No") if market == "BTTS" else ("Over 2.5", "Market Over · Under")
    )
    return base + [
        {
            "id": "home_metric",
            "label": "Home record",
            "align": "right",
            "sort": None,
            "title": f"Home team: {word} matches / current-season matches",
        },
        {
            "id": "away_metric",
            "label": "Away record",
            "align": "right",
            "sort": None,
            "title": f"Away team: {word} matches / current-season matches",
        },
        {
            "id": "indicator",
            "label": f"Recent {word}",
            "align": "right",
            "sort": "stat",
            "title": "Historical occurrence: average of the two teams' recent shares "
            "(not a probability)",
        },
        {
            "id": "baseline",
            "label": "League",
            "align": "right",
            "sort": None,
            "title": f"League {word} baseline before kickoff",
        },
        {
            "id": "market",
            "label": market_lbl,
            "align": "right",
            "sort": None,
            "title": "Market-implied probabilities from consensus odds, margin removed",
        },
        {"id": "limited", "label": "Data", "align": "left", "sort": None},
    ]


def threshold_config(market: str, direction: str) -> dict:
    """Threshold is interactive only where it is meaningful:
    Match result - strongest home/away advantage; BTTS and O/U - the indicator rankings.
    It is reset to 'Any' whenever the ranking changes (predictable, documented)."""
    if direction in THRESHOLD_DISABLED:
        hint = (
            "Available for strongest home/away rankings"
            if market == "1X2"
            else "Available for recent-occurrence rankings"
        )
        return {
            "min": 0,
            "max": 1,
            "step": 1,
            "value": 0,
            "disabled": True,
            "label": "Threshold",
            "hint": hint,
            "marks": {0: "Any", 1: ""},
        }
    if market == "1X2":
        return {
            "min": 0,
            "max": 5,
            "step": 0.25,
            "value": 0,
            "disabled": False,
            "label": "Minimum form difference",
            "hint": None,
            "marks": {0: "Any", 2.5: "2.5", 5: "5"},
        }
    outcome = {
        "btts_yes": "BTTS",
        "btts_no": "no-BTTS",
        "over": "Over 2.5",
        "under": "Under 2.5",
    }[direction]
    return {
        "min": 0,
        "max": 100,
        "step": 5,
        "value": 0,
        "disabled": False,
        "label": f"Minimum recent {outcome} occurrence",
        "hint": None,
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
    if snap.outdated_rows:
        banner.append(
            html.Div(
                "The statistics were calculated with an earlier method. Run "
                "`uv run diski9 screener-refresh` to rebuild them (no API requests).",
                className="banner warn",
            )
        )
    if snap.stale:
        banner.append(
            html.Div(
                "New results were loaded after the screener was last calculated. "
                "Run `diski9 refresh-data` to update.",
                className="banner warn",
            )
        )
    if not leagues and not snap.outdated_rows:
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
            dcc.Store(id="basis-pref", storage_type="session", data={}),
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
                    "Records use up to ten current-season matches; recent occurrence and league "
                    "baselines are historical, not predicted probabilities",
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
            [html.Span(c["label"]), html.Span(c["hint"], className="hint")]
            if c["hint"]
            else c["label"],
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
        Output("selected", "data"),
        Input("market", "value"),
        Input("leagues", "value"),
        Input("dates", "start_date"),
        Input("dates", "end_date"),
        Input("basis", "value"),
        Input("direction", "value"),
        Input("threshold", "value"),
        Input("prev", "n_clicks"),
        Input("next", "n_clicks"),
        Input({"type": "row", "index": ALL}, "n_clicks"),
        Input({"type": "fx", "index": ALL}, "n_clicks"),
        State("page", "data"),
        State("selected", "data"),
    )
    def update_results(
        market,
        leagues,
        start,
        end,
        basis,
        direction,
        threshold,
        _p,
        _n,
        _rows,
        _cards,
        page,
        selected,
    ):
        """Single source of truth for the list, the page and the selected fixture id.

        * row/card click: select that fixture id, keep the current page
        * Previous / Next: change page, keep the selection
        * any filter, ranking or market change: back to page 1, keep the selection
          if the fixture is still in the filtered list (cleared otherwise)
        """
        trig = ctx.triggered_id
        if isinstance(trig, dict) and trig.get("type") in ("row", "fx"):
            if not any(t["value"] for t in ctx.triggered):
                raise PreventUpdate  # rows/cards were re-rendered, not clicked
            selected = int(trig["index"])
        elif trig == "prev":
            page = (page or 1) - 1
        elif trig == "next":
            page = (page or 1) + 1
        else:
            page = 1
        return results_payload(
            data, market, leagues, start, end, basis, direction, threshold, page, selected
        )

    @app.callback(
        Output("basis", "value"),
        Input("market", "value"),
        State("basis-pref", "data"),
    )
    def apply_basis_default(market, prefs):
        """Per-market Form Basis: the user's choice for that market in this session,
        otherwise the default (Match result: venue; BTTS and O/U: overall)."""
        return (prefs or {}).get(market, DEFAULT_BASIS[market])

    @app.callback(
        Output("basis-pref", "data"),
        Input("basis", "value"),
        State("market", "value"),
        State("basis-pref", "data"),
    )
    def remember_basis(basis, market, prefs):
        prefs = dict(prefs or {})
        prefs[market] = basis
        return prefs

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
    """A disabled threshold never filters, whatever value the slider holds."""
    if value is None or direction in THRESHOLD_DISABLED:
        return None
    if market == "1X2":
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
    # selection is the fixture id; cleared when filters remove it from the list
    if selected is not None and selected not in {r["fixture"]["id"] for r in results}:
        selected = None
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
        selected,
    )


def _header(col: dict, market: str, direction: str) -> html.Th:
    cls = f"col-{col['align']}"
    if not col["sort"]:
        return html.Th(col["label"], className=cls, title=col.get("title"))
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
            title=(col.get("title", "") + " · click to change ranking").lstrip(" ·"),
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
                if market == "1X2":  # only Form difference is emphasised
                    cls += " strong " + signed_class(row["indicator"]).replace("num", "")
            elif cid == "baseline":
                value = row["baseline_display"]
                cls += " muted"
            elif cid == "market":
                value = [row["market"]] + (
                    [" ", pill("stale", "warn subtle")] if row["market_status"] == "stale" else []
                )
                cls += f" odds-{row['market_status']}"
            elif cid == "odds":
                value = [row["odds"]] + (
                    [" ", pill("stale", "warn subtle")] if row["odds_status"] == "stale" else []
                )
                cls += f" odds-{row['odds_status']}"
            elif cid == "limited":
                value = (
                    html.Span("Limited", className="pill warn subtle", title=LIMITED_TITLE[market])
                    if row["limited"]
                    else ""
                )
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
        word = "BTTS" if market == "BTTS" else "Over 2.5"
        metric = f"{word} records {row['home_metric']} · {row['away_metric']}"
        sub = f"League {row['baseline_display']}"
        metric_cls = "card-metric"
    if market == "1X2":
        odds = row["odds"] if row["odds"] in ("No odds", "—") else f"Odds {row['odds']}"
        status = row["odds_status"]
    else:
        odds = row["market"] if row["market"] in ("No odds", "—") else f"Market {row['market']}"
        status = row["market_status"]
    bottom = [html.Span(odds, className="muted small")]
    if status == "stale":
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
