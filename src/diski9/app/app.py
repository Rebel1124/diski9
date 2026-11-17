"""Diski 9 Screener and Match Lab — Plotly Dash application (Engine 3.0).

Run: ``uv run diski9 serve`` (defaults to http://127.0.0.1:8050).

"We calculate the probabilities. You analyse the match. You make the call."

The results list is a plain HTML table (desktop) / card list (phones) rendered
server-side, ten fixtures per page, ranked by the Goal Model 1.0 probability of
the chosen outcome. Selecting a fixture opens The Match Lab: the statistical
baseline, match context, other factors to consider and the user's own
estimated-goal adjustments. Adjustments live only in the browser
(``dcc.Store``, memory), keyed by fixture: they never change the cached baseline,
are never written to the server and are invisible to other users.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from diski9.screener.rank import DEFAULT_DIRECTION, KICKOFF_DIRECTIONS

from .data import (
    DIRECTIONS,
    MARKET_KEYS,
    PAGE_SIZE,
    ScreenerData,
    goals2,
    paginate,
    valid_direction,
)
from .lab import (
    ADJUST_MAX,
    CATEGORY_MAX,
    NOTE_MAX,
    SIDES,
    adjustment_text,
    baseline_rounded,
    breakdown,
    category_summary,
    category_total,
    is_empty,
    lab_outputs,
    normalise_state,
    render_detail,
    slider_max,
)
from .methodology import methodology_section
from .views import pill

ASSETS = Path(__file__).parent / "assets"
MARKETS = [
    ("1X2", "Match Result (1X2)"),
    ("BTTS", "Both Teams to Score (BTTS)"),
    ("OU25", "Over/Under 2.5 Goals"),
]


def league_labels(selected: int, total: int) -> dict:
    """Compact summary for the league multiselect plus its built-in actions."""
    summary = (
        f"All {total} leagues"
        if total and selected == total
        else "1 league selected"
        if selected == 1
        else "{num_selected} leagues selected"
    )
    return {"select_all": "Select all", "deselect_all": "Clear all", "selected_count": summary}


EARLY_TITLE = "Early season: at least one team has played fewer than five league matches"
THRESHOLD_DISABLED = KICKOFF_DIRECTIONS
STAT_PAIR = {  # header toggle between two statistical directions of a market
    "1X2": ("home_win", "away_win"),
    "BTTS": ("btts_yes", "btts_no"),
    "OU25": ("over", "under"),
}
DIRECTION_OUTCOME = {
    "home_win": "home win",
    "draw": "draw",
    "away_win": "away win",
    "btts_yes": "BTTS Yes",
    "btts_no": "BTTS No",
    "over": "Over 2.5",
    "under": "Under 2.5",
}


def columns_for(market: str) -> list[dict]:
    """Column definitions: id, label, alignment, sort key (None = not sortable)."""
    cols = [
        {"id": "kickoff", "label": "Kickoff", "align": "left", "sort": "kickoff"},
        {"id": "league", "label": "League", "align": "left", "sort": None},
        {"id": "home", "label": "Home", "align": "left", "sort": None},
        {"id": "away", "label": "Away", "align": "left", "sort": None},
        {
            "id": "estimated_goals",
            "label": "Est. goals",
            "align": "right",
            "sort": None,
            "title": "Estimated goals (home – away) from Goal Model 1.0",
        },
    ]
    for i, (key, label) in enumerate(MARKET_KEYS[market]):
        cols.append(
            {
                "id": f"p_{key}",
                "label": label,
                "align": "right",
                "sort": "stat" if i == 0 else None,
                "title": f"Diski 9 model probability: {label}",
            }
        )
    odds_label = {"1X2": "Odds H · D · A", "BTTS": "Odds Yes · No", "OU25": "Odds Over · Under"}
    cols += [
        {
            "id": "odds",
            "label": odds_label[market],
            "align": "right",
            "sort": None,
            "title": "Consensus bookmaker odds (reference only; never a model input)",
        },
        {"id": "limited", "label": "Data", "align": "left", "sort": None},
    ]
    return cols


THRESHOLD_MARKS = {0: "Any", 50: "50%", 100: "100%"}
# Floating value above the thumb: "Any" at 0, otherwise the exact whole percentage
# (window.dccFunctions.thresholdLabel in assets/diski9.js).
THRESHOLD_TOOLTIP = {"always_visible": True, "placement": "top", "transform": "thresholdLabel"}


def threshold_config(market: str, direction: str, preferred: float | None = 0) -> dict:
    """The threshold is a minimum model probability (whole percentages) for the ranked
    outcome. For kickoff ordering it is disabled, shows Any and never filters; the
    user's last probability threshold is restored when a probability ranking returns."""
    base = {"min": 0, "max": 100, "step": 1, "marks": THRESHOLD_MARKS}
    if direction in THRESHOLD_DISABLED:
        return {
            **base,
            "value": 0,
            "disabled": True,
            "label": "Minimum probability",
            "hint": "Available when ranking by a probability",
            "tooltip": None,
        }
    value = int(round(min(max(float(preferred or 0), 0), 100)))
    outcome = DIRECTION_OUTCOME[direction]
    return {
        **base,
        "value": value,
        "disabled": False,
        "label": f"Minimum {outcome} probability",
        "hint": None,  # the label already names the outcome
        "tooltip": THRESHOLD_TOOLTIP,
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
                            html.Span("Screener & Match Lab", className="subtitle"),
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
            html.P(
                "We calculate the probabilities. You analyse the match. You make the call.",
                className="tagline",
            ),
            *banner,
            methodology_section(),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Market", htmlFor="market"),
                            dcc.Dropdown(
                                id="market",
                                options=[{"label": lbl, "value": v} for v, lbl in MARKETS],
                                value="1X2",
                                clearable=False,
                                searchable=False,
                                className="dropdown",
                            ),
                        ],
                        className="filter",
                    ),
                    html.Div(
                        [
                            html.Label("Leagues", htmlFor="leagues"),
                            dcc.Dropdown(
                                id="leagues",
                                options=[{"label": n, "value": c} for c, n in leagues],
                                value=[c for c, _ in leagues],
                                multi=True,
                                closeOnSelect=False,
                                searchable=False,
                                clearable=True,
                                placeholder="Select leagues",
                                labels=league_labels(len(leagues), len(leagues)),
                                className="dropdown leagues",
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
                                max=100,
                                step=1,
                                value=0,
                                marks=THRESHOLD_MARKS,
                                disabled=True,
                                allow_direct_input=False,
                                className="slider",
                            ),
                            html.Div(id="threshold-hint", className="hint threshold-hint"),
                        ],
                        className="filter threshold-filter",
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
            dcc.Store(id="threshold-pref", data=0),
            dcc.Store(id="selected"),
            # The user's estimated-goal adjustments, keyed by fixture id. Memory only:
            # lives in this browser tab, never sent to storage, never shared.
            dcc.Store(id="lab-store", storage_type="memory", data={}),
            html.Div(id="detail", className="detail-holder"),
            html.Footer(
                "Diski 9 is an educational football analytics tool. Probabilities are "
                "statistical estimates from Goal Model 1.0, not guarantees. Bookmaker odds are "
                "reference values, not offers, and are never used by the model. No betting "
                "or staking advice is provided.",
                className="footer muted small",
            ),
        ],
        className="page",
    )


def _number(value) -> float:
    """float() that also accepts text with a decimal comma (raises on invalid input)."""
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    return float(value)


def _parse_goals(value) -> float | None:
    """A typed or slid final estimate, rounded to 0.01; None if invalid."""
    try:
        v = _number(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v < 0 or v > ADJUST_MAX:
        return None
    return round(v, 2)


def _parse_adjustment(value) -> float | None:
    """A category adjustment in goals (empty means 0); None if invalid."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    try:
        v = _number(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or abs(v) > CATEGORY_MAX:
        return None
    return round(v, 2)


def lab_update(r: dict, trigger, value, stored: dict | None) -> tuple[dict, list[str]]:
    """Pure logic behind the Match Lab callback: the fixture's new user state and any
    messages about input that could not be used.

    * a category adjustment or note (Section C) updates that category only
    * a slider or box (Section D) sets the *final* estimate: the manual adjustment
      becomes final - baseline - Section C total, so nothing is counted twice
    * Reset clears all adjustments (notes are kept)
    """
    base_r = baseline_rounded(r)
    state = normalise_state(stored, base_r)
    team = r["fixture"]
    messages: list[str] = []
    if trigger == "lab-reset":
        for k in state["cats"]:
            state["cats"][k]["home"] = state["cats"][k]["away"] = 0.0
        state["manual"] = {"home": 0.0, "away": 0.0}
        return state, messages
    if isinstance(trigger, dict) and trigger.get("type") == "cat-adj":
        key, side = trigger.get("cat"), trigger.get("side")
        if key in state["cats"] and side in SIDES:
            v = _parse_adjustment(value)
            if v is None:
                messages.append(
                    f"Category adjustments must be numbers between -{CATEGORY_MAX:g} and "
                    f"+{CATEGORY_MAX:g} goals; the previous value for {team[side]} was kept."
                )
            else:
                state["cats"][key][side] = v
        return state, messages
    if isinstance(trigger, dict) and trigger.get("type") == "cat-note":
        key = trigger.get("cat")
        if key in state["cats"]:
            state["cats"][key]["note"] = str(value or "").strip()[:NOTE_MAX]
        return state, messages
    for side in ("home", "away"):
        if trigger in (f"lab-{side}-slider", f"lab-{side}-input"):
            v = _parse_goals(value)
            if v is None:
                messages.append(
                    f"Estimated goals must be a number between 0 and {ADJUST_MAX:g}; "
                    f"{team[side]}'s estimate was not changed."
                )
            else:
                state["manual"][side] = round(v - base_r[side] - category_total(state, side), 2)
    return state, messages


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
        Output("leagues", "labels"), Input("leagues", "value"), State("leagues", "options")
    )
    def update_league_summary(value, options):
        return league_labels(len(value or []), len(options or []))

    @app.callback(
        Output("threshold", "min"),
        Output("threshold", "max"),
        Output("threshold", "step"),
        Output("threshold", "value"),
        Output("threshold", "marks"),
        Output("threshold", "disabled"),
        Output("threshold", "tooltip"),
        Output("threshold-label", "children"),
        Output("threshold-hint", "children"),
        Output("legend", "children"),
        Input("market", "value"),
        Input("direction", "value"),
        State("threshold-pref", "data"),
    )
    def update_controls(market, direction, preferred):
        c = threshold_config(market, valid_direction(market, direction), preferred)
        legend = html.Span(
            "Probabilities and estimated goals come from Goal Model 1.0 (this season's goals, "
            "Poisson distribution). Bookmaker odds are shown separately for comparison.",
            className="muted small",
        )
        return (
            c["min"],
            c["max"],
            c["step"],
            c["value"],
            c["marks"],
            c["disabled"],
            c["tooltip"],
            c["label"],
            c["hint"],
            legend,
        )

    @app.callback(
        Output("threshold-pref", "data"),
        Input("threshold", "value"),
        State("direction", "value"),
        prevent_initial_call=True,
    )
    def remember_threshold(value, direction):
        """The last threshold chosen for a probability ranking (kept while kickoff
        ordering is shown, restored afterwards)."""
        if direction in THRESHOLD_DISABLED or value is None:
            raise PreventUpdate
        return value

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
        market, leagues, start, end, direction, threshold, _p, _n, _rows, _cards, page, selected
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
            data, market, leagues, start, end, "overall", direction, threshold, page, selected
        )

    @app.callback(
        Output("detail", "children"),
        Input("selected", "data"),
        Input("market", "value"),
        State("lab-store", "data"),
    )
    def update_detail(fid, market, lab):
        r, ov, official = data.detail(fid) if fid else (None, None, {})
        adj = (lab or {}).get(str(fid)) if fid else None
        return render_detail(r, ov, official, market, data, adj)

    @app.callback(
        Output("lab-store", "data"),
        Output("lab-home-slider", "value"),
        Output("lab-home-input", "value"),
        Output("lab-away-slider", "value"),
        Output("lab-away-input", "value"),
        Output("lab-home-slider", "max"),
        Output("lab-away-slider", "max"),
        Output({"type": "cat-adj", "cat": ALL, "side": ALL}, "value"),
        Output({"type": "cat-sum", "cat": ALL}, "children"),
        Output("lab-output", "children"),
        Output("lab-compare", "children"),
        Input("lab-home-slider", "value"),
        Input("lab-home-input", "value"),
        Input("lab-away-slider", "value"),
        Input("lab-away-input", "value"),
        Input("lab-reset", "n_clicks"),
        Input({"type": "cat-adj", "cat": ALL, "side": ALL}, "value"),
        Input({"type": "cat-note", "cat": ALL}, "value"),
        State("selected", "data"),
        State("market", "value"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def adjust(_hs, _hi, _as, _ai, _reset, _cat_values, _notes, fid, market, lab):
        """Sections C and D: update this fixture's state in the browser store and
        recalculate all seven probabilities. The model baseline is never modified."""
        if not fid or not ctx.triggered:
            raise PreventUpdate
        r, ov, _ = data.detail(fid)
        if r is None or not r["goal_model"].get("available"):
            raise PreventUpdate
        lab = dict(lab or {})
        trig = ctx.triggered_id
        value = ctx.triggered[0].get("value")
        state, messages = lab_update(r, trig, value, lab.get(str(fid)))
        if is_empty(state):
            lab.pop(str(fid), None)
        else:
            lab[str(fid)] = state
        b = breakdown(baseline_rounded(r), state)
        h, a = b["home"]["final"], b["away"]["final"]
        cat_out = [
            adjustment_text(state["cats"][o["id"]["cat"]][o["id"]["side"]])
            for o in ctx.outputs_list[7]
        ]
        sum_out = [category_summary(state, o["id"]["cat"]) for o in ctx.outputs_list[8]]
        out, compare = lab_outputs(r, market, ov, state, messages)
        base = r["goal_model"]["estimated_goals"]
        return (
            lab,
            h,
            goals2(h),
            a,
            goals2(a),
            slider_max(base["home"], h),
            slider_max(base["away"], a),
            cat_out,
            sum_out,
            out,
            compare,
        )

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
    """Clicking 'Kickoff' toggles earliest/latest; clicking the first probability
    header toggles the market's two main outcomes."""
    if key == "kickoff":
        return "kickoff_latest" if current == "kickoff_earliest" else "kickoff_earliest"
    first, second = STAT_PAIR[market]
    return second if current == first else first


def _threshold_value(market: str, direction: str, value: float | None) -> float | None:
    """A disabled threshold never filters, whatever value the slider holds."""
    if value is None or direction in THRESHOLD_DISABLED:
        return None
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
        data.filtered(market, leagues, _date(start), _date(end), "overall", direction, thr)
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
        active = direction in STAT_PAIR[market]
        arrow = "↕" if not active else ("▼" if direction == STAT_PAIR[market][0] else "▲")
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
            if cid == "odds":
                value = [row["odds"]] + (
                    [" ", pill("stale", "warn subtle")] if row["odds_status"] == "stale" else []
                )
                cls += f" odds-{row['odds_status']}"
            elif cid == "limited":
                if not row["available"]:
                    value = html.Span(
                        "No model", className="pill subtle", title=row["unavailable_reason"]
                    )
                elif row["limited"]:
                    value = html.Span(
                        "Early season", className="pill warn subtle", title=EARLY_TITLE
                    )
                else:
                    value = ""
            elif cid.startswith("p_"):
                value = row[cid]
                cls += " strong"
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
    if row["available"]:
        probs = " · ".join(f"{lbl} {row[f'p_{k}']}" for k, lbl in MARKET_KEYS[market])
        metric = f"Est. goals {row['estimated_goals']}"
    else:
        probs, metric = row["unavailable_reason"], "No model estimate"
    odds = row["odds"] if row["odds"] in ("No odds", "—") else f"Odds {row['odds']}"
    bottom = [html.Span(odds, className="muted small")]
    if row["odds_status"] == "stale":
        bottom.append(pill("stale odds", "warn subtle"))
    if row["limited"]:
        bottom.append(pill("Early season", "warn subtle"))
    return html.Button(
        [
            html.Div(
                [html.Span(row["kickoff"]), html.Span(row["league"], className="pill subtle")],
                className="card-top muted small",
            ),
            html.Div(f"{row['home']} v {row['away']}", className="card-teams"),
            html.Div(
                [
                    html.Span(metric, className="card-metric"),
                    html.Span(probs, className="muted small"),
                ]
            ),
            html.Div(bottom, className="card-bottom"),
        ],
        id={"type": "fx", "index": row["id"]},
        className="fx-card" + (" selected" if row["id"] == selected else ""),
        n_clicks=0,
    )
