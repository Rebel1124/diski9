"""Weekly Challenge page layouts (presentation only)."""

from __future__ import annotations

from dash import dcc, html

from diski9.challenge import analysis as pa
from diski9.challenge import demo
from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.roundsheet import RoundStatus
from diski9.challenge.scoring import POINTS_150_75_V2
from diski9.challenge.structured import (
    IssueCode,
    SelectionBlock,
    assess_outcome,
    portfolio_progress,
    selection_blocks,
)

from . import charts
from . import components as c
from .service import ChallengeService, key_str

CFG = DEFAULT_CONFIG
STAGES = (
    ("overview", "Overview"),
    ("build", "Build"),
    ("review", "Review"),
)
DEFAULT_STATE = {"mode": None, "fp": None, "selections": [], "stage": "overview", "submitted": None}


def normal_state(state: dict | None) -> dict:
    s = dict(DEFAULT_STATE)
    s.update(state or {})
    s["selections"] = list(s.get("selections") or [])
    return s


def effective_mode(service: ChallengeService, state: dict) -> str | None:
    """The participant's chosen mode, or live when nothing was chosen and it is playable."""
    if state.get("mode"):
        return state["mode"]
    return "live" if service.availability("live").playable else None


def current(service: ChallengeService, state: dict):
    """(mode, snapshot, availability, selections valid for this snapshot)."""
    mode = effective_mode(service, state)
    snap = service.snapshot(mode) if mode else None
    avail = service.availability(mode or "live")
    sels = state["selections"] if snap is not None and state.get("fp") == snap.fingerprint else []
    return mode, snap, avail, sels


def locked(avail) -> bool:
    return avail.status is RoundStatus.LOCKED


# ------------------------------------------------------------------ shell
def challenge_shell(service, state, explore, local, personal=None) -> html.Div:
    state = normal_state(state)
    return html.Div(
        [
            html.Div(
                [
                    html.H1("Weekly Challenge", className="ch-h1"),
                    html.Span("Virtual credits only · no real money", className="muted small"),
                ],
                className="ch-title",
            ),
            html.Div(id=c.T("stepper"), children=stepper(service, state)),
            html.Div(id=c.T("flash")),
            html.Div(
                id=c.T("stage"), children=stage_body(service, state, explore, local, personal)
            ),
        ],
        className="ch-page",
    )


def stepper(service, state) -> html.Nav:
    state = normal_state(state)
    mode, snap, avail, sels = current(service, state)
    complete = snap is not None and service.evaluate(snap, sels) is not None
    reach = {
        "overview": True,
        "build": avail.playable and snap is not None,
        "review": complete,
    }
    return html.Nav(
        [
            html.Button(
                [html.Span(str(i + 1), className="ch-step-n"), label],
                id={"t": "nav", "to": key, "i": "stepper"},
                n_clicks=0,
                disabled=not reach[key],
                className="ch-step" + (" on" if state["stage"] == key else ""),
            )
            for i, (key, label) in enumerate(STAGES)
        ],
        className="ch-stepper",
        **{"aria-label": "Challenge steps"},
    )


def stage_signature(service, state) -> list:
    state = normal_state(state)
    mode, snap, _, _ = current(service, state)
    sub = (state.get("submitted") or {}).get("at")
    return [state["stage"], mode, snap.fingerprint if snap else None, sub]


def stage_body(service, state, explore, local, personal=None):
    state = normal_state(state)
    mode, snap, avail, sels = current(service, state)
    stage = state["stage"]
    complete = snap is not None and service.evaluate(snap, sels) is not None
    if stage == "build" and snap is not None and avail.playable:
        return builder(service, snap, sels, avail, explore, local, personal)
    if stage == "review" and complete:
        return review(service, snap, sels, avail, state, local)
    return overview(service, state, mode, snap, avail, local)


# --------------------------------------------------------------- overview
def overview(service, state, mode, snap, avail, local) -> html.Div:
    n = len(state["selections"]) if snap is not None and state.get("fp") == snap.fingerprint else 0
    actions = []
    if avail.playable and snap is not None:
        actions.append(
            html.Button(
                f"Resume your portfolio ({n}/9) →" if n else "Start building →",
                id={"t": "nav", "to": "build", "i": "overview"},
                n_clicks=0,
                className="ch-btn primary",
            )
        )
    if mode != "demo":
        if not avail.playable:
            actions.append(
                html.Button(
                    "Try the demonstration round",
                    id={"t": "mode", "m": "demo"},
                    n_clicks=0,
                    className="ch-btn primary",
                )
            )
    else:
        live = service.availability("live")
        actions.append(
            html.Button(
                "Leave the demonstration" if not live.playable else "Switch to the live round",
                id={"t": "mode", "m": "live"},
                n_clicks=0,
                className="ch-btn ghost",
            )
        )
    unavailable = None
    if mode != "demo" and not avail.playable:
        unavailable = html.Div(
            [
                html.Strong("The live round isn't available. "),
                avail.message,
                " You can still learn how the challenge works with the "
                "demonstration round: historical fixtures and prices, clearly labelled, for "
                "practice only.",
            ],
            className="ch-ribbon warn",
        )
    pts = POINTS_150_75_V2
    return html.Div(
        [
            c.demo_ribbon(snap),
            unavailable,
            html.Div(
                [
                    html.Div(
                        [
                            html.P(
                                [
                                    "Build a portfolio of nine predictions with ",
                                    html.Strong("100 virtual credits"),
                                    ". The aim is simple: ",
                                    "get your 100 back.",
                                ],
                                className="ch-lead",
                            ),
                            c.objectives(),
                            html.Div(actions, className="ch-actions"),
                        ],
                        className="ch-card ch-hero",
                    ),
                    c.status_panel(service.availability(mode) if mode else avail, snap, local),
                ],
                className="ch-grid-2",
            ),
            html.Div(
                [html.H2("How your 100 credits are split", className="ch-h2"), c.structure_table()],
                className="ch-card",
            ),
            html.Div(
                [
                    html.H2("Championship points", className="ch-h2"),
                    html.Div(
                        [
                            html.Div([html.Span(f"{i + 1}"), html.Strong(str(p))], className="pt")
                            for i, p in enumerate(pts.top_points)
                        ]
                        + [
                            html.Div(
                                [html.Span("11+"), html.Strong(str(pts.recovery_points))],
                                className="pt",
                            )
                        ],
                        className="ch-points",
                    ),
                    html.P(
                        "Points need a recovery: at least 100.00 credits back. Ten competitive "
                        "rounds make a championship.",
                        className="muted small",
                    ),
                    c.rules_details(),
                ],
                className="ch-card",
            ),
        ]
    )


# ---------------------------------------------------------------- builder
def _filter(label, control, cls="filter"):
    return html.Div([html.Label(label), control], className=cls)


def builder(service, snap, sels, avail, prefs, local, personal=None) -> html.Div:
    leagues = sorted({f.league for f in snap.fixtures})
    days = sorted({local(f.kickoff, "%Y-%m-%d") for f in snap.fixtures})
    day_label = {
        d: local(
            next(f.kickoff for f in snap.fixtures if local(f.kickoff, "%Y-%m-%d") == d), "%a %d %b"
        )
        for d in days
    }
    filters = html.Div(
        [
            _filter(
                "League",
                dcc.Dropdown(
                    id=c.T("f-league"),
                    options=leagues,
                    value=[],
                    multi=True,
                    placeholder="All leagues",
                    className="dropdown",
                ),
            ),
            _filter(
                "Date",
                dcc.Dropdown(
                    id=c.T("f-date"),
                    options=[{"label": day_label[d], "value": d} for d in days],
                    value=None,
                    placeholder="All dates",
                    className="dropdown",
                ),
            ),
            _filter(
                "Market",
                dcc.Dropdown(
                    id=c.T("f-market"),
                    options=[{"label": v, "value": k} for k, v in c.MARKET_SHORT.items()],
                    value=None,
                    placeholder="All markets",
                    className="dropdown",
                ),
            ),
            _filter(
                "Bucket",
                dcc.Dropdown(
                    id=c.T("f-bucket"),
                    options=[{"label": b.name, "value": b.code} for b in CFG.buckets],
                    value=None,
                    placeholder="All buckets",
                    className="dropdown",
                ),
            ),
            _filter(
                "Team",
                dcc.Input(
                    id=c.T("f-search"),
                    type="search",
                    placeholder="Search a team",
                    debounce=True,
                    className="ch-input",
                ),
            ),
            html.Div(
                dcc.Checklist(
                    id=c.T("f-avail"),
                    options=[{"label": "Available only", "value": "on"}],
                    value=[],
                    className="chips",
                ),
                className="filter ch-avail",
            ),
        ],
        className="ch-filters",
    )
    lock_note = (
        html.Div("This round is locked: the deadline has passed.", className="ch-ribbon warn")
        if locked(avail)
        else None
    )
    cards, count = fixture_list(service, snap, sels, {}, local, locked(avail), 1, personal)
    view = (prefs or {}).get("view", "matches")
    toggle = dcc.RadioItems(
        id=c.T("view"),
        value=view,
        inline=True,
        className="segmented ch-view",
        options=[
            {"label": "Choose matches", "value": "matches"},
            {"label": "Portfolio analysis", "value": "analysis"},
        ],
    )
    return html.Div(
        [
            c.demo_ribbon(snap),
            lock_note,
            toggle,
            html.Div(
                [
                    html.Div(
                        analysis_panel(service, snap, sels, prefs, personal)
                        if view == "analysis"
                        else None,
                        id=c.T("analysis-view"),
                        className="ch-main",
                        style={} if view == "analysis" else {"display": "none"},
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2("Choose nine predictions", className="ch-h2"),
                                    html.Span(count, id=c.T("fx-count"), className="muted small"),
                                ],
                                className="ch-row-between",
                            ),
                            filters,
                            html.P(
                                "Mkt: the market's chance, which sets the bucket. D9: Diski 9's "
                                "model. Odds: the frozen reference odds that set your payout.",
                                className="muted small ch-legend",
                            ),
                            html.Div(cards, id=c.T("fixtures"), className="ch-fixtures"),
                        ],
                        id=c.T("matches-view"),
                        className="ch-main",
                        style={"display": "none"} if view == "analysis" else {},
                    ),
                    html.Aside(
                        [
                            c.source_selector((prefs or {}).get("source", "market")),
                            html.Div(
                                id=c.T("tracker"),
                                children=tracker_view(
                                    service, snap, sels, locked(avail), prefs, personal
                                ),
                            ),
                        ],
                        className="ch-side",
                    ),
                ],
                className="ch-builder",
            ),
        ]
    )


FIXTURES_PER_PAGE = 10  # rendering every outcome at once is slow in the browser


def fixture_list(
    service, snap, sels, filters: dict, local, is_locked: bool, page: int = 1, personal=None
):
    """(children for the fixture area, count text). Filters never touch the portfolio."""
    chosen = service.outcomes_for(snap, sels)
    assess = {o.key: assess_outcome(o, snap.snapshot_at, CFG) for o in snap.outcomes}
    blocks = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, CFG)
    league = set(filters.get("league") or [])
    day = filters.get("date")
    market = filters.get("market")
    bucket = filters.get("bucket")
    avail_only = bool(filters.get("available"))
    q = (filters.get("search") or "").strip().lower()
    by_fx: dict = {}
    for o in snap.outcomes:
        by_fx.setdefault(o.fixture_id, []).append(o)
    matches = []
    for fx in snap.fixtures:
        if league and fx.league not in league:
            continue
        if day and local(fx.kickoff, "%Y-%m-%d") != day:
            continue
        if q and q not in fx.home.lower() and q not in fx.away.lower():
            continue
        outs = [
            o
            for o in by_fx.get(fx.fixture_id, [])
            if (not market or str(o.market) == market)
            and (not bucket or (assess[o.key].eligible and assess[o.key].bucket == bucket))
            and (not avail_only or blocks.get(o.key) in (None, SelectionBlock.SELECTED))
        ]
        if outs:
            matches.append((fx, outs))
    if not matches:
        empty = html.P(
            "No matches fit these filters. Your selected predictions are kept in your portfolio.",
            className="muted ch-empty",
        )
        return [empty], f"0 of {len(snap.fixtures)} matches"
    pages_n = max(1, -(-len(matches) // FIXTURES_PER_PAGE))
    page = min(max(int(page or 1), 1), pages_n)
    start = (page - 1) * FIXTURES_PER_PAGE
    shown = matches[start : start + FIXTURES_PER_PAGE]
    cards = [
        c.fixture_card(fx, outs, assess, blocks, local, is_locked, personal) for fx, outs in shown
    ]
    pager = html.Div(
        [
            html.Button(
                "‹ Previous",
                id={"t": "fxpg", "d": "prev"},
                n_clicks=0,
                className="pager-btn",
                disabled=page <= 1,
            ),
            html.Span(f"Page {page} of {pages_n}", className="muted small"),
            html.Button(
                "Next ›",
                id={"t": "fxpg", "d": "next"},
                n_clicks=0,
                className="pager-btn",
                disabled=page >= pages_n,
            ),
        ],
        className="pager",
    )
    text = f"Matches {start + 1}–{start + len(shown)} of {len(matches)}"
    if len(matches) != len(snap.fixtures):
        text += f" (filtered from {len(snap.fixtures)})"
    return [*cards, pager], text


def tracker_view(service, snap, sels, is_locked: bool, prefs=None, personal=None) -> html.Div:
    source = (prefs or {}).get("source", "market")
    prob = pa.probability_for(source, personal)
    chosen = service.outcomes_for(snap, sels)
    progress = portfolio_progress(chosen, snap.snapshot_at, CFG, pool=snap.outcomes)
    stats, nine = pa.bucket_stats(chosen, prob, CFG)
    by_bucket: dict = {}
    for o in chosen:
        by_bucket.setdefault(CFG.classify(o.market_probability), []).append(o)
    if progress.is_complete:
        msg = "Portfolio complete. Check the analysis, then review and submit."
    elif progress.issues_of(IssueCode.CANNOT_COMPLETE):
        msg = (
            "These picks can't be completed from the remaining matches. Remove a pick to free "
            "up a bucket or match."
        )
    elif not progress.is_valid:
        msg = progress.issues[0].message
    else:
        need = [f"{CFG.bucket(k).name} {v}" for k, v in progress.remaining.items() if v]
        msg = "Still needed: " + ", ".join(need) if need else ""
    port = service.portfolio(snap, sels)
    ev = pa.evaluate_with(port, prob) if port is not None else None

    def label(o):
        fx = snap.fixture(o.fixture_id)
        return f"{fx.home} v {fx.away}"

    return c.tracker(
        stats, nine, by_bucket, label, prob, msg, ev, port is not None and not is_locked, is_locked
    )


# --------------------------------------------------------------- analysis
def analysis_panel(service, snap, sels, prefs, personal=None) -> html.Div:
    """Portfolio analysis inside the builder: recovery, possible payouts and the number
    of correct predictions, all for the selected probability source."""
    port = service.portfolio(snap, sels)
    if port is None:
        n = len(sels)
        return html.Div(
            [
                html.H2("Portfolio analysis", className="ch-h2"),
                html.P(
                    f"Pick all nine predictions to see your portfolio's chances ({n}/9 so far). "
                    "The tracker already shows each bucket's chance and payout so far.",
                    className="muted",
                ),
            ],
            className="ch-card ch-empty-analysis",
        )
    source = (prefs or {}).get("source", "market")
    prob = pa.probability_for(source, personal)
    ev = pa.evaluate_with(port, prob)
    cc = pa.correct_count_analysis(port, prob)
    label = pa.SOURCE_LABEL[source]
    return html.Div(
        [
            html.Div(
                [
                    html.H2("Portfolio analysis", className="ch-h2"),
                    html.Span(f"{label} estimate", className="ch-pill demo"),
                ],
                className="ch-row-between",
            ),
            recovery_section(ev),
            payouts_section(ev),
            correct_section(cc),
        ]
    )


def recovery_section(ev) -> html.Div:
    rows = [
        ("100+ back", ev.p_recover, "teal"),
        ("Something, under 100", ev.p_partial, "amber"),
        ("Nothing back", ev.p_zero, "grey"),
    ]
    return html.Div(
        [
            html.H3("Will you get your 100 credits back?", className="ch-h3"),
            html.Div(
                [
                    dcc.Graph(
                        figure=charts.recovery_donut(ev),
                        config={"displayModeBar": False},
                        className="ch-donut",
                    ),
                    html.Div(
                        [
                            *(
                                html.Div(
                                    [
                                        html.Span(className=f"sw {cls}"),
                                        html.Span(name),
                                        html.Strong(c.pct(p, 1)),
                                    ],
                                    className="ch-legend-row",
                                )
                                for name, p, cls in rows
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span("Expected gross", className="muted small"),
                                            html.Strong(f"{ev.expected_gross:,.2f} cr"),
                                        ]
                                    ),
                                    html.Div(
                                        [
                                            html.Span("Expected net", className="muted small"),
                                            html.Strong(f"{ev.expected_net:+,.2f} cr"),
                                        ]
                                    ),
                                ],
                                className="ch-expect",
                            ),
                            html.P(
                                "Expected payout is the average over very many imaginary repeats "
                                "of this week, not a promise and not the most likely result: most "
                                "weeks pay less, a few pay much more.",
                                className="muted small",
                            ),
                        ],
                        className="ch-recovery-legend",
                    ),
                ],
                className="ch-recovery",
            ),
        ],
        className="ch-card",
    )


def payouts_section(ev) -> html.Div:
    rows = charts.state_rows(ev)
    by_gross: dict = {}
    for s in rows:
        by_gross.setdefault(s.gross, []).append(s)
    same = [v for v in by_gross.values() if len(v) > 1]
    accs = html.Div(
        [
            html.Span(
                [
                    c.chip(a.code),
                    f" pays {c.credits(a.payout)} if all "
                    f"{len(a.legs) if a.code != 'NINE' else 9} correct",
                ],
                className="ch-acc-pay",
            )
            for a in (*ev.buckets, ev.nine_fold)
        ],
        className="ch-acc-pays small",
    )
    head = html.Tr(
        [
            html.Th("Outcome"),
            html.Th("Foundation", className="c"),
            html.Th("Balanced", className="c"),
            html.Th("Challenger", className="c"),
            html.Th("Diski 9", className="c"),
            html.Th("Total payout", className="num"),
            html.Th("Chance", className="num"),
        ]
    )
    body = [
        html.Tr(
            [
                html.Td(pa.state_label(s.wins)),
                *[html.Td("✓" if w else "—", className="c") for w in s.wins],
                html.Td("✓" if all(s.wins) else "—", className="c"),
                html.Td(c.credits(s.gross), className="num"),
                html.Td(c.pct(s.probability, 2), className="num"),
            ]
        )
        for s in rows
    ]
    return html.Div(
        [
            html.H3("Possible payouts", className="ch-h3"),
            html.P(
                "Each row is one combination of completed buckets, with your total payout "
                "for the week. A bucket pays only when all of its predictions are correct.",
                className="muted small",
            ),
            accs,
            dcc.Graph(
                figure=charts.states_figure(ev),
                config={"displayModeBar": False},
                className="ch-states-graph",
            ),
            html.P(
                "Same total payout: "
                + "; ".join(
                    " and ".join(pa.state_label(s.wins) for s in v)
                    + f" ({c.credits(v[0].gross)} cr)"
                    for v in same
                ),
                className="muted small",
            )
            if same
            else None,
            html.Details(
                [
                    html.Summary("All eight combinations in a table"),
                    html.Div(
                        html.Table(
                            [html.Thead(head), html.Tbody(body)], className="ch-table states"
                        ),
                        className="ch-table-wrap",
                    ),
                ],
                className="ch-details",
            ),
        ],
        className="ch-card",
    )


def correct_section(cc) -> html.Div:
    k0 = cc.most_likely
    head = html.Tr(
        [
            html.Th("Correct", className="num"),
            html.Th("Combinations", className="num"),
            html.Th("Chance", className="num"),
            html.Th("Average payout", className="num"),
            html.Th("Range", className="num"),
            html.Th("Get 100+ back", className="num"),
            html.Th("Share of expected", className="num"),
        ]
    )
    body = [
        html.Tr(
            [
                html.Td(str(r.k), className="num"),
                html.Td(str(r.combinations), className="num"),
                html.Td(c.pct(r.probability, 2), className="num"),
                html.Td(
                    f"{r.expected_gross:,.2f}" if r.expected_gross is not None else "—",
                    className="num",
                ),
                html.Td(f"{r.min_gross:,.0f}–{r.max_gross:,.0f}", className="num"),
                html.Td(c.pct(r.p_recover, 1) if r.p_recover is not None else "—", className="num"),
                html.Td(f"{r.contribution:,.2f}", className="num"),
            ]
        )
        for r in cc.rows
    ]
    return html.Div(
        [
            html.H3("How many predictions might you get right?", className="ch-h3"),
            html.Div(
                [
                    html.Span(["Expected: ", html.Strong(f"{cc.expected_correct:.1f} of 9")]),
                    html.Span(["Most likely: ", html.Strong(f"{cc.most_likely} correct")]),
                ],
                className="ch-kpis small",
            ),
            dcc.Graph(
                id=c.T("k-hist"),
                figure=charts.correct_histogram(cc, k0),
                config={"displayModeBar": False},
                className="ch-hist",
            ),
            html.Div(
                [
                    html.Span("Look at:", className="muted small"),
                    dcc.RadioItems(
                        id=c.T("k-select"),
                        value=k0,
                        inline=True,
                        className="ch-k",
                        options=[{"label": str(k), "value": k} for k in range(10)],
                    ),
                ],
                className="ch-k-row",
            ),
            html.Div(id=c.T("k-detail"), children=k_detail(cc, k0)),
            html.P(
                "More correct predictions don't always mean a bigger payout: a bucket pays only "
                "when every one of its predictions is right. Two correct Challenger picks can get "
                "your 100 back, while six correct picks spread across unfinished buckets can pay "
                "nothing.",
                className="muted small",
            ),
            html.Details(
                [
                    html.Summary("Average payout by number correct"),
                    dcc.Graph(
                        figure=charts.conditional_payout_figure(cc, k0),
                        config={"displayModeBar": False},
                    ),
                ],
                className="ch-details",
            ),
            html.Details(
                [
                    html.Summary("Full table (all 512 combinations, grouped)"),
                    html.Div(
                        html.Table([html.Thead(head), html.Tbody(body)], className="ch-table"),
                        className="ch-table-wrap",
                    ),
                    html.P(
                        "Average payout and 'Get 100+ back' are conditional: they assume "
                        "exactly that many predictions are correct. 'Share of expected' is "
                        "that count's contribution to your overall expected payout.",
                        className="muted small",
                    ),
                ],
                className="ch-details",
            ),
        ],
        className="ch-card",
    )


def k_detail(cc, k: int) -> html.Div:
    r = cc.rows[int(k)]
    if r.probability == 0:
        return html.Div(
            f"Exactly {r.k} correct can't happen with these estimates.",
            className="ch-kdetail muted small",
        )
    return html.Div(
        [
            html.Strong(f"If exactly {r.k} of 9 are correct"),
            html.Span(
                f"chance {c.pct(r.probability, 1)} · {r.combinations} combinations",
                className="muted small",
            ),
            html.Div(
                [
                    html.Span(["Average payout ", html.Strong(f"{r.expected_gross:,.2f} cr")]),
                    html.Span(["Range ", html.Strong(f"{r.min_gross:,.2f}–{r.max_gross:,.2f}")]),
                    html.Span(["Get 100+ back ", html.Strong(c.pct(r.p_recover, 1))]),
                ],
                className="ch-kstats small",
            ),
        ],
        className="ch-kdetail",
    )


# ----------------------------------------------------------------- review
def review(service, snap, sels, avail, state, local) -> html.Div:
    mk, md = service.evaluate(snap, sels)
    rows = []
    for acc in mk.buckets:
        for k in acc.legs:
            o = snap.outcome(k)
            fx = snap.fixture(o.fixture_id)
            rows.append(
                html.Tr(
                    [
                        html.Td(c.chip(acc.code, acc.code)),
                        html.Td(f"{fx.home} v {fx.away}"),
                        html.Td(c.outcome_text(o)),
                        html.Td(c.pct(o.market_probability, 1), className="num"),
                        html.Td(f"{o.reference_odds:.2f}", className="num"),
                    ]
                )
            )
    sub = state.get("submitted")
    confirmed = sub and sub.get("fp") == snap.fingerprint and sub.get("selections") == sels
    can_submit = avail.playable and not locked(avail)
    compare = html.Div(
        [
            html.Div(
                [
                    html.Span(label, className="ch-metric-label"),
                    html.Span(f"Recover 100: {c.pct(ev.p_recover)}"),
                    html.Span(f"Nothing back: {c.pct(ev.p_zero)}", className="small"),
                    html.Span(
                        f"Expected: {ev.expected_gross:,.2f} cr ({ev.expected_net:+,.2f})",
                        className="small",
                    ),
                ],
                className="ch-metric",
            )
            for label, ev in (("Market estimate", mk), ("Diski 9 model", md))
        ],
        className="ch-metrics two",
    )
    return html.Div(
        [
            c.demo_ribbon(snap),
            html.H2("Review your portfolio", className="ch-h2"),
            html.Div(
                [
                    html.Div(
                        html.Table(
                            [
                                html.Thead(
                                    html.Tr(
                                        [
                                            html.Th("Bucket"),
                                            html.Th("Match"),
                                            html.Th("Prediction"),
                                            html.Th("Mkt", className="num"),
                                            html.Th("Odds", className="num"),
                                        ]
                                    )
                                ),
                                html.Tbody(rows),
                            ],
                            className="ch-table",
                        ),
                        className="ch-table-wrap",
                    ),
                    html.P(
                        f"Allocation: Foundation 40, Balanced 30, Challenger 20, The Diski 9 10 "
                        f"credits. Round {snap.round_id} · snapshot {local(snap.snapshot_at)} · "
                        f"configuration {snap.config_version}.",
                        className="muted small",
                    ),
                ],
                className="ch-card",
            ),
            compare,
            html.P(
                "Estimates assume independent matches and are not guarantees. Credits are "
                "virtual and have no cash value.",
                className="muted small",
            ),
            html.Div(
                [
                    html.Strong("Demonstration submission confirmed. "),
                    f"Recorded in this browser tab only at {local(sub['at'])} — it is not a "
                    "competition entry and nothing is stored on a server.",
                ],
                className="ch-ribbon ok",
            )
            if confirmed
            else None,
            html.Div(
                [
                    html.Button(
                        "← Back to builder",
                        id={"t": "nav", "to": "build", "i": "rv"},
                        n_clicks=0,
                        className="ch-btn ghost",
                    ),
                    html.Button(
                        "Confirm demonstration submission" if not confirmed else "Confirmed ✓",
                        id=c.T("submit"),
                        n_clicks=0,
                        disabled=bool(confirmed) or not can_submit,
                        className="ch-btn primary",
                    ),
                ],
                className="ch-actions end",
            ),
            html.P(
                "Prototype: confirming checks your portfolio again and records it in this "
                "browser tab. Live entries, accounts and deadlines arrive in a later phase.",
                className="muted small",
            ),
        ]
    )


# ------------------------------------------------------------- my challenge
def my_challenge(service, state, local) -> html.Div:
    state = normal_state(state)
    mode, snap, avail, sels = current(service, state)
    draft = html.Div(
        [
            html.H2("This round", className="ch-h2"),
            html.P(
                f"{'Demonstration' if mode == 'demo' else 'Live'} round "
                f"{snap.round_id if snap else '—'} · {avail.title}",
                className="small",
            ),
            html.P(
                f"Draft: {len(sels)} of 9 predictions."
                if sels
                else "You haven't started a portfolio for this round.",
                className="muted",
            ),
            dcc.Link("Go to the Weekly Challenge →", href="/challenge", className="ch-btn ghost"),
        ],
        className="ch-card",
    )
    sub = state.get("submitted")
    if sub:
        submitted = html.Div(
            [
                html.H2("Demonstration submission", className="ch-h2"),
                html.P(
                    f"Round {sub['round_id']} · confirmed {local(sub['at'])} in this tab only.",
                    className="small",
                ),
                html.P(
                    f"Recover 100: {c.pct(sub['p_recover_market'])} (market) · "
                    f"{c.pct(sub['p_recover_model'])} (Diski 9 model). Expected return "
                    f"{sub['expected_market']:,.2f} credits (market).",
                    className="muted small",
                ),
            ],
            className="ch-card",
        )
    else:
        submitted = html.Div(
            [
                html.H2("Demonstration submission", className="ch-h2"),
                html.P("Nothing confirmed yet.", className="muted"),
            ],
            className="ch-card",
        )
    history = demo.demo_history()
    table = demo.demo_championship()
    me = next((s for s in table.standings if s.participant_id == demo.YOU), None)
    rows = []
    for r, s in history:
        kind = {"competitive": "Competitive", "practice": "Practice", "void": "Void"}[
            r.classification.value
        ]
        rows.append(
            html.Tr(
                [
                    html.Td(r.round_id),
                    html.Td(kind),
                    html.Td(c.credits(s.gross) if s else "—", className="num"),
                    html.Td(str(s.rank) if s and s.rank else "—", className="num"),
                    html.Td("Yes" if s and s.recovered else "No"),
                    html.Td(str(s.points) if s else "0", className="num strong"),
                ]
            )
        )
    hist = html.Div(
        [
            html.H2("Illustrative history", className="ch-h2"),
            html.Div(
                "Demonstration data: invented results to show how weekly and championship "
                "points work. Not your real results.",
                className="ch-ribbon",
            ),
            html.Div(
                [
                    c.metric("Championship points", str(me.points), f"rank {me.rank}"),
                    c.metric("Recoveries", str(me.recoveries), f"in {me.rounds_entered} rounds"),
                    c.metric("Top-ten finishes", str(me.qualifying_top10), "with a recovery"),
                ]
                if me
                else [],
                className="ch-metrics",
            ),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("Round"),
                                    html.Th("Type"),
                                    html.Th("Gross", className="num"),
                                    html.Th("Rank", className="num"),
                                    html.Th("Recovered"),
                                    html.Th("Points", className="num"),
                                ]
                            )
                        ),
                        html.Tbody(rows),
                    ],
                    className="ch-table",
                ),
                className="ch-table-wrap",
            ),
        ],
        className="ch-card",
    )
    return html.Div(
        [
            html.H1("My Challenge", className="ch-h1"),
            html.Div([draft, submitted], className="ch-grid-2"),
            hist,
        ],
        className="ch-page",
    )


# -------------------------------------------------------------- leaderboards
def leaderboards() -> html.Div:
    rounds = demo.demo_rounds()
    return html.Div(
        [
            html.H1("Leaderboards", className="ch-h1"),
            html.Div(
                "Demonstration data: invented players and results, scored with the real "
                "points rules. Live leaderboards arrive with accounts and stored entries.",
                className="ch-ribbon",
            ),
            html.Div(
                [
                    dcc.RadioItems(
                        id=c.T("lb-tab"),
                        value="weekly",
                        inline=True,
                        className="segmented",
                        options=[
                            {"label": "This week", "value": "weekly"},
                            {"label": "Championship", "value": "championship"},
                        ],
                    ),
                    html.Div(
                        dcc.Dropdown(
                            id=c.T("lb-round"),
                            value=demo.LATEST_ROUND,
                            clearable=False,
                            searchable=False,
                            className="dropdown",
                            options=[
                                {"label": demo.round_label(r), "value": r.round_id}
                                for r in reversed(rounds)
                            ],
                        ),
                        id=c.T("lb-round-wrap"),
                        className="ch-lb-round",
                    ),
                ],
                className="ch-row-between",
            ),
            html.Div(
                id=c.T("lb-body"),
                children=leaderboard_body("weekly", demo.LATEST_ROUND),
                className="ch-card",
            ),
        ],
        className="ch-page",
    )


def leaderboard_body(tab: str, round_id: str | None):
    if tab == "championship":
        return [
            html.H2(f"Championship {demo.CHAMPIONSHIP_ID}", className="ch-h2"),
            c.championship_table(demo.demo_championship()),
        ]
    rid = round_id or demo.LATEST_ROUND
    r = next(x for x in demo.demo_rounds() if x.round_id == rid)
    return [
        html.H2(f"Week {rid}", className="ch-h2"),
        c.weekly_table(demo.demo_round_score(rid), r),
    ]


__all__ = ["key_str"]
