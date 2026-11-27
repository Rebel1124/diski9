"""Diski 9 Screener and Match Lab — Plotly Dash application (Engine 3.0).

Run: ``uv run diski9 serve`` (defaults to http://127.0.0.1:8050).

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

from diski9.screener.rank import DEFAULT_DIRECTION, KICKOFF_DIRECTIONS, VALUE_DIRECTIONS

from . import education, lab_context
from .challenge import lab_persist
from .challenge.callbacks import (
    LAB,
    PORTFOLIO,
    legacy_redirect,
    nav_links,
    norm_path,
    research_list_shown,
)
from .challenge.callbacks import register as register_challenge
from .challenge.components import page_header
from .challenge.integration import (
    challenge_cell,
    challenge_cells,
    frozen_order,
    frozen_row,
    frozen_universe,
)
from .challenge.service import ChallengeService
from .data import (
    DIRECTIONS,
    MARKET_KEYS,
    PAGE_SIZE,
    ScreenerData,
    goals2,
    paginate,
    valid_direction,
)
from .icons import icon
from .lab import (
    ADJUST_MAX,
    CATEGORY_MAX,
    CONTEXT_MAX,
    SIDES,
    adjustment_notice,
    adjustment_text,
    baseline_rounded,
    breakdown,
    category_summary,
    category_total,
    context_summary,
    context_total,
    is_empty,
    lab_outputs,
    normalise_state,
    render_detail,
    signed_text,
    slider_max,
    slider_value,
    starting_point,
    store_adjustment,
    stored_adjustment,
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


VALUE_LABEL = {"edge": "Best edge", "ev": "Best EV"}
VALUE_TITLE = (
    "Model vs market: the outcome where the model probability most exceeds the "
    "margin-adjusted market probability (percentage points). Hover a cell for the "
    "consensus odds; select a match for every outcome."
)
EV_TITLE = (
    "Expected value at the consensus reference odds: model probability × odds − 1. A "
    "theoretical return per unit staked if the model's probability is right; not a "
    "promise of profit and not an offer from any single bookmaker."
)
VALUE_LEGEND = (
    " Edge = model probability − market probability (bookmaker margin removed), in percentage "
    "points. EV = model probability × consensus odds − 1. Only fresh prices are ranked. A "
    "positive value is not proof the market is wrong; select a match for the full comparison."
)
THRESHOLD_VALUE_HINT = (
    " The minimum model probability still applies: edge and EV only consider outcomes the "
    "model rates at least that likely."
)


def columns_for(market: str, direction: str | None = None) -> list[dict]:
    """Column definitions: id, label, alignment, sort key (None = not sortable). The
    final column adapts to the ranking: Market / Edge, Best edge or Best EV."""
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
    cols.append(
        {
            "id": "value",
            "label": VALUE_LABEL.get(direction or "", "Market / Edge"),
            "align": "right",
            "sort": None,
            "title": (EV_TITLE if direction == "ev" else VALUE_TITLE)
            + " Bookmaker odds are never a model input.",
        }
    )
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
    if direction in VALUE_DIRECTIONS:  # still a minimum *model* probability
        return {
            **base,
            "value": value,
            "disabled": False,
            "label": "Minimum model probability",
            "hint": None,  # explained in the legend (a hint here would sit under the tooltip)
            "tooltip": THRESHOLD_TOOLTIP,
        }
    outcome = DIRECTION_OUTCOME[direction]
    return {
        **base,
        "value": value,
        "disabled": False,
        "label": f"Minimum {outcome} probability",
        "hint": None,  # the label already names the outcome
        "tooltip": THRESHOLD_TOOLTIP,
    }


def create_app(data: ScreenerData, auth=None) -> Dash:
    """The Dash app. With ``auth`` (an ``AuthRuntime``), sign-in, accounts and the
    account menu are enabled; without it the app runs exactly as before (guests
    only, browser-session prototype)."""
    app = Dash(
        __name__,
        assets_folder=str(ASSETS),
        title="Diski 9",
        update_title=None,
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
        suppress_callback_exceptions=True,
    )
    app.server.config["DISKI9_DATA"] = data
    service = ChallengeService(data, backend=competition_backend(auth))
    app.server.config["DISKI9_CHALLENGE"] = service
    app.layout = lambda: build_shell(data, service)
    register_callbacks(app, data, service)
    register_challenge(app, data, service)
    from .health import register_health

    register_health(app.server, data.engine, auth.engine if auth is not None else None)
    if auth is not None:
        from diski9.backend.auth.web import init_auth

        init_auth(app.server, auth)
    app.server.before_request(legacy_redirect)  # after the auth hooks (CP3A-1)
    return app


def competition_backend(auth):
    """The persistent competition (Phase 6C.3) when accounts are configured: the
    published round, drafts, entries and Your View come from the competition
    database. Development rounds are shown only when explicitly enabled outside
    production (``DISKI9_SHOW_DEVELOPMENT_ROUNDS=1``)."""
    if auth is None:
        return None
    import os

    from diski9.backend.db.settings import BackendDatabaseSettings

    from .challenge.persist import Backend

    show_dev = os.environ.get("DISKI9_SHOW_DEVELOPMENT_ROUNDS") == "1"
    if show_dev and BackendDatabaseSettings().environment == "production":
        raise RuntimeError("DISKI9_SHOW_DEVELOPMENT_ROUNDS is refused in production")
    return Backend(auth.engine, show_development=show_dev)


def build_shell(data: ScreenerData, service: ChallengeService | None = None) -> html.Div:
    """Site shell: navigation, the Screener and Match Lab page (shown at ``/lab``) and
    the pages rendered into ``ch-root``: Portfolio Build (``/``, the Weekly Challenge
    builder), ``/challenge/me``, ``/leaderboards`` and ``/learn`` (Phase 8 CP3A-1).

    The Screener stays mounted and is only hidden on other routes, so its filters,
    selection and Match Lab state survive navigation. Weekly Challenge state lives
    in the browser-session store ``ch-session`` (this tab only, kept on refresh)."""
    service = service or ChallengeService(data)
    return html.Div(
        [
            dcc.Location(id="url", refresh=False),
            html.Nav(
                html.Div(
                    [
                        html.Span("Diski 9", className="nav-brand"),
                        html.Div(nav_links("/"), id="site-nav-links", className="nav-links"),
                        *account_menu(),
                    ],
                    className="nav-inner",
                ),
                className="site-nav",
                **{"aria-label": "Main"},
            ),
            # Portfolio Build introduction and Domestic Weekly Challenge card (CP3A-2)
            html.Div(id="pb-home"),
            html.Div(
                build_layout(data, "challenge" if service.availability("live").playable else "all"),
                id="screener-root",
                style={"display": "none"},  # shown by ``layout_mode`` (/lab; research list)
            ),
            html.Div(id="ch-root"),
            dcc.Store(id="ch-session", storage_type="session"),
            dcc.Store(id="ch-prefs", storage_type="session", data={"source": "market"}),
            dcc.Store(id="ch-flash", storage_type="memory"),
            dcc.Store(id="ch-rendered", storage_type="memory"),
            dcc.Store(id="ch-fxpage", storage_type="memory", data=1),
            dcc.Store(id="d9-adopt", storage_type="session"),
            html.Div(id="adopt-root"),
        ]
    )


def account_menu() -> list:
    """Sign-in links or the signed-in account menu, rendered on the server for this
    request (empty when authentication is not configured). Shows only the username;
    never an email address or internal identifier."""
    from flask import current_app, has_request_context

    if not has_request_context() or "DISKI9_AUTH" not in current_app.config:
        return []
    from diski9.backend.auth.web import current_principal, owner_tag

    p = current_principal()
    marker = html.Div(id="d9-owner", hidden=True, **{"data-owner": owner_tag()})
    if not p.is_authenticated:
        links = [
            html.A("Sign in", href="/auth/sign-in", className="acct-link"),
            html.A("Create account", href="/auth/sign-up", className="acct-link primary"),
        ]
        return [html.Div([*links, marker], className="nav-account")]
    label = p.username if p.onboarded else "Finish set-up"
    items = [
        html.Div("Signed in" if p.onboarded else "Account set-up incomplete", className="acct-who"),
        html.A(
            "Account settings" if p.onboarded else "Finish setting up",
            href="/account" if p.onboarded else "/account/welcome",
        ),
        html.A("Sign out", href="/auth/sign-out"),
    ]
    summary = [icon("circle-user", "acct-ic"), html.Span(label, className="acct-name")] + (
        [] if p.onboarded else [html.Span("Action needed", className="acct-badge")]
    )
    return [
        html.Div(
            [
                html.Details(
                    [html.Summary(summary, title=label), html.Div(items, className="acct-panel")],
                    className="acct-menu",
                ),
                marker,
            ],
            className="nav-account",
        )
    ]


def build_layout(data: ScreenerData, universe: str = "all") -> html.Div:
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
            page_header(
                "Match Lab",
                f"Times in {data.tz_label} · statistics calculated "
                f"{data.local(snap.cache_calculated_at)}",
            ),
            *banner,
            methodology_section(),
            html.Div(
                [
                    # The global Challenge Mode control is removed from the page (Phase 8
                    # CP3A-2): Research only in Portfolio Build and the Match Lab links
                    # set it. It stays as hidden internal state until CP3A-3/4 replace
                    # it with the list origin and the frozen/latest toggle.
                    html.Div(
                        [
                            html.Label("Matches"),
                            dcc.RadioItems(
                                id="universe",
                                options=[
                                    {"label": "Weekly Challenge", "value": "challenge"},
                                    {"label": "All upcoming matches", "value": "all"},
                                ],
                                value=universe,
                                className="segmented universe",
                            ),
                        ],
                        className="filter f-matches",
                        style={"display": "none"},
                        hidden=True,
                    ),
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
                        className="filter f-market",
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
                        className="filter f-leagues",
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
                        className="filter f-dates",
                    ),
                    html.Div(
                        [
                            html.Label(education.term("Rank by", "edge", "ev")),
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
                        className="filter f-rank",
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
            html.Div(id="data-context"),
            html.Div(id="ch-strip"),
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
            # The user's estimated-goal adjustments (Your View), keyed by fixture id with
            # a model-context stamp per fixture. Session storage (Phase 6B.3): this
            # browser tab only; survives navigation, refresh and a server restart, ends
            # when the tab closes. Never sent to the server's storage or shared.
            dcc.Store(id="lab-store", storage_type="session", data={}),
            # Match Lab journey: model analysis and Your View (detail), then the Weekly
            # Challenge selection cards, then the bookmaker market reference
            html.Div(id="detail", className="detail-holder"),
            html.Div(id="lab-challenge"),
            html.Div(id="detail-reference", className="detail-holder"),
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


def _parse_context(value) -> float | None:
    """A Section B match-context adjustment (empty means 0); None if invalid."""
    v = _parse_adjustment(value)
    if v is None or abs(v) > CONTEXT_MAX:
        return None
    return v


def lab_update(r: dict, trigger, value, stored: dict | None) -> tuple[dict, list[str]]:
    """Pure logic behind the Match Lab callback: the fixture's new user state and any
    messages about input that could not be used.

    * a match-context adjustment (Section B) updates Section B only;
      "Clear Section B adjustments" clears its numbers
    * a category adjustment (Section C) updates that category only
    * the compact B / C sliders and their number boxes are two views of ONE value:
      either trigger sets it, and the callback writes it back to both
    * a slider or box (Section D) sets the *final* estimate: the manual adjustment
      becomes final - baseline - Section B - Section C, so nothing is counted twice
    * Reset clears all adjustments in B, C and D
    """
    base_r = baseline_rounded(r)
    state = normalise_state(stored, base_r)
    team = r["fixture"]
    messages: list[str] = []
    if trigger == "lab-reset":
        for k in state["cats"]:
            state["cats"][k]["home"] = state["cats"][k]["away"] = 0.0
        state["context"]["home"] = state["context"]["away"] = 0.0
        state["manual"] = {"home": 0.0, "away": 0.0}
        return state, messages
    if trigger == "ctx-clear":
        state["context"]["home"] = state["context"]["away"] = 0.0
        return state, messages
    if trigger in ("ctx-home", "ctx-away", "ctx-home-slider", "ctx-away-slider"):
        side = trigger.split("-")[1]  # slider and box share one Section B value
        v = _parse_context(value)
        if v is None:
            messages.append(
                f"Match context adjustments must be numbers between -{CONTEXT_MAX:.2f} and "
                f"+{CONTEXT_MAX:.2f} goals; the previous value for {team[side]} was kept."
            )
        else:
            state["context"][side] = v
        return state, messages
    if isinstance(trigger, dict) and trigger.get("type") in ("cat-adj", "cat-slider"):
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
    for side in ("home", "away"):
        if trigger in (f"lab-{side}-slider", f"lab-{side}-input"):
            v = _parse_goals(value)
            if v is None:
                messages.append(
                    f"Estimated goals must be a number between 0 and {ADJUST_MAX:g}; "
                    f"{team[side]}'s estimate was not changed."
                )
            else:
                state["manual"][side] = round(
                    v - base_r[side] - context_total(state, side) - category_total(state, side), 2
                )
    return state, messages


def register_callbacks(app: Dash, data: ScreenerData, service=None) -> None:
    service = service or ChallengeService(data)

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
            "Poisson distribution). Bookmaker odds are shown separately for comparison."
            + (VALUE_LEGEND + THRESHOLD_VALUE_HINT if direction in VALUE_DIRECTIONS else ""),
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
        Input("universe", "value"),
        State("page", "data"),
        State("selected", "data"),
        State("ch-session", "data"),
    )
    def update_results(
        market,
        leagues,
        start,
        end,
        direction,
        threshold,
        _p,
        _n,
        _rows,
        _cards,
        universe,
        page,
        selected,
        ch_state=None,
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
            data,
            market,
            leagues,
            start,
            end,
            "overall",
            direction,
            threshold,
            page,
            selected,
            challenge=challenge_cells(service, ch_state, market)
            if universe == "challenge"
            else None,
        )

    @app.callback(
        Output("dates", "start_date"),
        Output("dates", "end_date"),
        Input("universe", "value"),
        State("ch-session", "data"),
        prevent_initial_call=True,
    )
    def universe_changed(universe, ch_state):
        """Switching match universe sets a compatible date range: the round snapshot's
        kickoff dates for the Weekly Challenge, the default fortnight otherwise."""
        rng = universe_dates(data, service, ch_state, universe)
        return rng if rng else (no_update, no_update)

    @app.callback(
        Output("detail", "children"),
        Output("detail-reference", "children"),
        Output("lab-store", "data", allow_duplicate=True),
        Input("selected", "data"),
        Input("market", "value"),
        Input("url", "pathname"),
        Input("universe", "value"),
        State("lab-store", "data"),
        State("ch-prefs", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def update_detail(fid, market, path, universe, lab, prefs=None):
        """The Match Lab is unmounted while another page shows (its large tree inside
        the hidden Screener slowed every Weekly Challenge tap) and rebuilt from the
        selection and the Match Lab store on return, so nothing is lost. The context
        (frozen Weekly Challenge snapshot or latest data) decides the baseline and
        which Your View is shown; a signed-in participant's saved Your View for that
        context is loaded from the account (Phase 6C.3)."""
        here = norm_path(path)
        # the Match Lab, or (until CP3A-3 moves the detail to /lab only) beneath the
        # research list in Portfolio Build
        if not (here == LAB or (here == PORTFOLIO and research_list_shown(service, prefs))):
            if ctx.triggered_id == "url":
                return None, None, no_update
            return no_update, no_update, no_update
        lc = lab_context.resolve(service, data, fid, universe) if fid else None
        new_lab = no_update
        if lc is not None and lc.r is not None:
            hydrated = lab_persist.load(service, lab, lc)
            if hydrated is not None:
                lab, new_lab = hydrated, hydrated
        r = lc.r if lc else None
        _, ov, official = data.detail(fid) if fid else (None, None, {})
        adj = stored_adjustment(lab, lc.key, r) if lc else None
        notice = adjustment_notice(lab, lc.key, r) if lc else None
        body, ref = split_detail(render_detail(r, ov, official, market, data, adj, notice))
        return body, ref, new_lab

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
        Output("ctx-home", "value"),
        Output("ctx-away", "value"),
        Output("ctx-sum", "children"),
        Output({"type": "cat-slider", "cat": ALL, "side": ALL}, "value"),
        Output("ctx-home-slider", "value"),
        Output("ctx-away-slider", "value"),
        Input("lab-home-slider", "value"),
        Input("lab-home-input", "value"),
        Input("lab-away-slider", "value"),
        Input("lab-away-input", "value"),
        Input("lab-reset", "n_clicks"),
        Input({"type": "cat-adj", "cat": ALL, "side": ALL}, "value"),
        Input("ctx-home", "value"),
        Input("ctx-away", "value"),
        Input("ctx-clear", "n_clicks"),
        Input({"type": "cat-slider", "cat": ALL, "side": ALL}, "value"),
        Input("ctx-home-slider", "value"),
        Input("ctx-away-slider", "value"),
        State("selected", "data"),
        State("market", "value"),
        State("universe", "value"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def adjust(*args):
        """Sections B, C and D: update this fixture's state for the context shown
        (frozen Weekly Challenge snapshot or latest data) and recalculate all seven
        probabilities. The model baseline is never modified. A signed-in
        participant's numbers are saved to that context only (Phase 6C.3)."""
        fid, market, universe, lab = args[-4:]
        if not fid or not ctx.triggered:
            raise PreventUpdate
        lc = lab_context.resolve(service, data, fid, universe)
        r = lc.r if lc else None
        _, ov, _ = data.detail(fid)
        if r is None or starting_point(r) is None:
            raise PreventUpdate
        trig = ctx.triggered_id
        value = ctx.triggered[0].get("value")
        state, messages = lab_update(r, trig, value, stored_adjustment(lab, lc.key, r))
        lab = store_adjustment(lab, lc.key, r, None if is_empty(state) else state)
        lab, problem = lab_persist.save(service, lab, lc, state)
        if problem:
            messages = [*messages, problem]
        b = breakdown(baseline_rounded(r), state)
        h, a = b["home"]["final"], b["away"]["final"]
        cat_out = [
            adjustment_text(state["cats"][o["id"]["cat"]][o["id"]["side"]])
            for o in ctx.outputs_list[7]
        ]
        sum_out = [category_summary(state, o["id"]["cat"]) for o in ctx.outputs_list[8]]
        out, compare = lab_outputs(r, market, ov, state, messages)
        base = starting_point(r)["estimated_goals"]
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
            signed_text(state["context"]["home"]),
            signed_text(state["context"]["away"]),
            context_summary(state),
            [
                slider_value(state["cats"][o["id"]["cat"]][o["id"]["side"]], CATEGORY_MAX)
                for o in ctx.outputs_list[14]
            ],
            slider_value(state["context"]["home"], CONTEXT_MAX),
            slider_value(state["context"]["away"], CONTEXT_MAX),
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


def split_detail(detail):
    """(header + Match Lab, bookmaker reference + footnote): the Weekly Challenge
    selection panel sits between them, after the participant has formed Your View."""
    kids = getattr(detail, "children", None)
    if not isinstance(kids, list) or len(kids) < 3:
        return detail, None
    return (
        html.Div(kids[:2], className=detail.className),
        html.Div(kids[2:], className=f"{detail.className} detail-ref"),
    )


def universe_dates(data, service, ch_state, universe: str):
    """(start, end) dates in local time for a match universe, or None to keep."""
    today = data.clock().astimezone(data.tz).date()
    if universe != "challenge":
        return today, today + timedelta(days=14)
    snap = (challenge_cells(service, ch_state, "1X2") or {}).get("snapshot")
    if snap is None or not snap.fixtures:
        return None
    days = [f.kickoff.astimezone(data.tz).date() for f in snap.fixtures]
    return min(days), max(days)


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
    data,
    market,
    leagues,
    start,
    end,
    basis,
    direction,
    threshold,
    page,
    selected=None,
    challenge: dict | None = None,
):
    """Pure function behind the results callback (also used by tests). All filters
    apply before ranking and pagination. "All upcoming matches" includes fixtures
    without bookmaker odds (shown as "No odds"); odds are never an eligibility test.

    ``challenge`` (the Weekly Challenge view) restricts the list to the frozen
    Challenge pool and shows its frozen reference odds and portfolio markers."""
    direction = valid_direction(market, direction)
    thr = _threshold_value(market, direction, threshold)
    if challenge is not None:
        # The Weekly Challenge universe is exactly the round snapshot's fixtures. Its
        # probabilities, estimated goals, market probabilities, odds, edge and EV, and
        # every ranking and minimum-probability filter, come from the frozen snapshot
        # - never from the live model cache or live odds.
        results = (
            frozen_order(
                challenge,
                frozen_universe(data, challenge, market, leagues, _date(start), _date(end)),
                market,
                direction,
                thr,
            )
            if leagues
            else []
        )
    else:
        results = (
            data.filtered(market, leagues, _date(start), _date(end), "overall", direction, thr)
            if leagues
            else []
        )
    # selection is the fixture id; cleared when filters remove it from the list
    if selected is not None and selected not in {r["fixture"]["id"] for r in results}:
        selected = None
    pg = paginate(results, page)
    if challenge is not None:
        mode = "ev" if direction == "ev" else "edge"
        rows = [
            frozen_row(challenge, market, data.row(market, r), r)
            | {"value": challenge_cell(challenge, market, r["fixture"]["id"], mode, thr)}
            for r in pg.results
        ]
    else:
        rows = [
            data.row(market, r) | {"value": data.value_cell(market, r, direction, thr)}
            for r in pg.results
        ]
    if not leagues:
        empty = html.Div("Select at least one league to see fixtures.", className="empty")
    elif challenge is not None and not results:
        empty = html.Div(
            challenge.get("message")
            or "No Weekly Challenge matches fit these filters. Switch to All upcoming matches "
            "to analyse every fixture.",
            className="empty",
        )
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
    cols = columns_for(market, direction)
    body = []
    for row in rows:
        cells = []
        for col in cols:
            cid = col["id"]
            cls = f"col-{col['align']}"
            if cid == "value":
                v = row["value"]
                value = value_lines(v)
                cls += f" value-cell v-{v['cls']} odds-{v['status']}" + outcome_class(v)
                cells.append(html.Td(value, className=cls, title=v["title"]))
                continue
            elif cid == "estimated_goals":
                # Data-quality flags (formerly a separate, usually empty "Data" column)
                if not row["available"]:
                    value = html.Span(
                        "Not in snapshot" if row.get("frozen") else "No model",
                        className="pill subtle",
                        title=row["unavailable_reason"],
                    )
                elif row["limited"]:
                    value = [
                        html.Span("Early season", className="pill warn subtle", title=EARLY_TITLE),
                        " ",
                        row[cid],
                    ]
                else:
                    value = row[cid]
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


def outcome_class(v: dict) -> str:
    """Outcome colour (Home blue, Draw teal, Away amber) for a positive 1X2 pick only;
    negative, zero, missing and stale values keep the neutral style."""
    return f" v-out-{v['outcome']}" if v.get("outcome") and v["cls"] == "pos" else ""


def value_lines(v: dict) -> list:
    """Two compact lines: the highlighted outcome and its market % (or odds for EV)."""
    out = [html.Span(v["main"], className="v-main")]
    if v["sub"]:
        out.append(html.Span(v["sub"], className="v-sub muted small"))
    if v.get("picked"):  # Weekly Challenge view: this match's pick in the portfolio
        out.append(
            html.Span(
                [icon("check", "ic-sm"), f"Your pick: {v['picked']}"],
                className="v-pick small",
            )
        )
    return out


def fixture_card(market: str, row: dict, selected: int | None) -> html.Button:
    if row["available"]:
        probs = " · ".join(f"{lbl} {row[f'p_{k}']}" for k, lbl in MARKET_KEYS[market])
        metric = f"Est. goals {row['estimated_goals']}"
    else:
        probs = row["unavailable_reason"]
        metric = "Not in the round snapshot" if row.get("frozen") else "No model estimate"
    odds = row["odds"] if row["odds"] in ("No odds", "—") else f"Odds {row['odds']}"
    bottom = [html.Span(odds, className="muted small")]
    if row["odds_status"] == "stale":
        bottom.append(pill("stale odds", "warn subtle"))
    v = row.get("value")
    if v and v["status"] == "fresh" and v["main"] not in (None, "—"):
        label = "Best EV" if v["mode"] == "ev" else "Edge"
        text = f"{label}: {v['main']}" + (f" · {v['sub']}" if v["sub"] else "")
        bottom.append(
            html.Span(text, className=f"small card-value v-{v['cls']}" + outcome_class(v))
        )
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
