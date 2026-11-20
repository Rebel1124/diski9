"""Weekly Challenge page layouts (presentation only)."""

from __future__ import annotations

from uuid import UUID

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

from . import charts, results_ui
from . import components as c
from . import state as st
from .service import ChallengeService, key_str

CFG = DEFAULT_CONFIG
# participant state lives in .state (one documented source of truth)
STAGES = st.STAGES
DEFAULT_STATE = st.DEFAULT_STATE
normal_state = st.normal_state


def sync(service: ChallengeService, state: dict | None) -> dict:
    """The stored state reconciled with the current snapshot (see ``state.reconcile``)."""
    return st.reconcile(service, state)


def effective_mode(service: ChallengeService, state: dict) -> str | None:
    """The participant's chosen mode, or live when nothing was chosen and it is playable."""
    if state.get("mode"):
        return state["mode"]
    if service.availability("live").playable:
        return "live"
    # A published round past its deadline (lock pending, or locked) is still the
    # participant's round: show it read-only rather than "unavailable".
    if getattr(service, "backend", None) is not None and service.live() is not None:
        return "live"
    return None


def current(service: ChallengeService, state: dict):
    """(mode, snapshot, availability, selections valid for this snapshot)."""
    state = sync(service, state)
    mode = effective_mode(service, state)
    snap = service.snapshot(mode) if mode else None
    avail = service.availability(mode or "live")
    sels = state["selections"] if snap is not None and state.get("fp") == snap.fingerprint else []
    return mode, snap, avail, sels


def locked(avail) -> bool:
    return avail.status is RoundStatus.LOCKED


FROZEN_NOTE = (
    "All participants use the same frozen odds and baseline estimates for this round. "
    "These may differ from the latest information shown under All Upcoming Fixtures."
)


def access(service, snap) -> str:
    """How this page treats the person (Phase 6C.3): ``account`` (signed-in
    participant, persistent round), ``guest`` / ``setup`` (persistent round, cannot
    save), ``prototype`` (no competition database, or the demonstration round)."""
    from . import persist

    if snap is None or snap.is_demo or persist.backend_of(service) is None:
        return "prototype"
    return "account" if persist.participant(service) else (persist.signed_in_label(service))


def save_status(service, state) -> html.Div | None:
    """A compact line under the tracker: saved to the account, not saved, or kept in
    this tab only. 'Saved' only after the database confirmed the write."""
    state = normal_state(state)
    _, snap, _, _ = current(service, state)
    kind = access(service, snap)
    if kind == "prototype":
        return None
    if kind in ("guest", "setup"):
        return html.P(
            [c.icon("info", "ic-sm"), " Kept in this browser tab only. ",
             html.A("Sign in", href="/auth/sign-in") if kind == "guest"
             else html.A("Finish setting up", href="/account/welcome"),
             " to save your portfolio and confirm an entry."],
            className="muted small ch-save-state",
        )  # fmt: skip
    acct = state.get("acct") or {}
    status = acct.get("status")
    if acct.get("dirty"):
        return html.P(
            [c.icon("alert", "ic-sm"), " Not saved: see the message above."],
            className="small ch-save-state warn",
        )
    if status == "saved":
        return html.P(
            [c.icon("check", "ic-sm"), " Saved to your account"],
            className="muted small ch-save-state ok",
        )
    return html.P("Your portfolio is saved to your account as you build it.",
                  className="muted small ch-save-state")  # fmt: skip


def round_times(rv, local) -> list[tuple[str, str]]:
    """Frozen (snapshot) time and deadline from the stored round record."""
    out = []
    if rv is None:
        return out
    if rv.snapshot_at is not None:
        out.append(("Frozen", f"{local(rv.snapshot_at)} SAST"))
    if rv.deadline_at is not None:
        out.append(("Deadline", f"{local(rv.deadline_at)} SAST"))
    return out


# ------------------------------------------------------------------ shell
def challenge_shell(service, state, explore, local, personal=None) -> html.Div:
    state = sync(service, state)
    return html.Div(
        [
            c.page_header("Weekly Challenge", "Virtual credits only · no real money"),
            html.Div(id=c.T("stepper"), children=stepper(service, state)),
            html.Div(id=c.T("flash")),
            html.Div(
                id=c.T("stage"), children=stage_body(service, state, explore, local, personal)
            ),
        ],
        className="ch-page",
    )


def active_stage(state, complete: bool) -> str:
    """The step actually shown: Review & Submit only for a complete portfolio."""
    return "review" if state["stage"] == "review" and complete else "build"


def stepper(service, state) -> html.Nav:
    """Two steps. The current step is highlighted and marked ``aria-current``; a step
    that can be opened but is not current is shown as available (and the build step
    as done once the portfolio is complete); an unreachable step is disabled."""
    state = sync(service, state)
    mode, snap, avail, sels = current(service, state)
    complete = snap is not None and service.evaluate(snap, sels) is not None
    reach = {"build": avail.playable and snap is not None, "review": complete}
    now = active_stage(state, complete)
    items = []
    for i, (key, label) in enumerate(STAGES):
        cur = key == now
        done = key == "build" and complete and not cur
        cls = "ch-step" + (" on is-current" if cur else "") + (" is-done" if done else "")
        cls += " is-available" if reach[key] and not cur else ""
        mark = c.icon("check", "ic-sm") if done else str(i + 1)
        items.append(
            html.Button(
                [html.Span(mark, className="ch-step-n"), label],
                id={"t": "nav", "to": key, "i": "stepper"},
                n_clicks=0,
                disabled=not reach[key],
                className=cls,
                title=("Current step" if cur else "Open this step" if reach[key]
                       else "Complete all nine predictions first"),
                **({"aria-current": "step"} if cur else {}),
            )
        )  # fmt: skip
    return html.Nav(items, className="ch-stepper", **{"aria-label": "Challenge steps"})


def stage_signature(service, state) -> list:
    state = sync(service, state)
    mode, snap, _, _ = current(service, state)
    sub = (state.get("submitted") or {}).get("at")
    return [
        state["stage"],
        mode,
        snap.fingerprint if snap else None,
        sub,
        state.get("modal"),
        len(state.get("notes") or []),
        state.get("confirm"),
        (state.get("withdrawn") or {}).get("at"),
    ]


def stage_body(service, state, explore, local, personal=None):
    state = sync(service, state)
    mode, snap, avail, sels = current(service, state)
    complete = snap is not None and service.evaluate(snap, sels) is not None
    if snap is None or not avail.playable:
        return unavailable(service, state, mode, snap, avail, local)
    if active_stage(state, complete) == "review":
        return review(service, snap, sels, avail, state, local, personal)
    return builder(service, snap, sels, avail, explore, local, personal, state)


# ------------------------------------------------------------- how to play
def how_to_play(open_: bool) -> html.Details:
    pts = POINTS_150_75_V2
    return html.Details(
        [
            html.Summary("How to play"),
            html.Div(
                [
                    html.Div(
                        [
                            html.P(
                                [
                                    "Build a portfolio of nine predictions with ",
                                    html.Strong("100 virtual credits"),
                                    ".",
                                ],
                                className="ch-lead",
                            ),
                            c.objectives(),
                            c.build_steps(),
                        ],
                        className="ch-htp-col",
                    ),
                    html.Div([c.structure_table()], className="ch-htp-col"),
                ],
                className="ch-htp",
            ),
            html.Div(
                [
                    html.Div([html.Span(f"{i + 1}"), html.Strong(str(p))], className="pt")
                    for i, p in enumerate(pts.top_points)
                ]
                + [
                    html.Div(
                        [html.Span("11+"), html.Strong(str(pts.recovery_points))], className="pt"
                    )
                ],
                className="ch-points",
            ),
            html.P(
                "Championship points are awarded for recoveries (at least 100.00 credits back) "
                "in competitive rounds only, never in demonstration or practice rounds. Ten "
                "competitive rounds make a championship.",
                className="muted small ch-points-note",
            ),
            c.rules_details(),
        ],
        open=open_,
        className="ch-details ch-howto",
    )


def status_strip(snap, avail, local, rv=None) -> html.Div:
    rep = avail.report
    items = [("Round", snap.round_id), ("Status", avail.title)]
    if rv is not None and not snap.is_demo:
        items += round_times(rv, local)
    else:
        if not snap.is_demo and snap.deadline:
            items.append(("Deadline", f"{local(snap.deadline)} SAST"))
        items.append(("Snapshot", f"{local(snap.snapshot_at)} SAST"))
    if rep is not None:
        items.append(("Fixtures", f"{rep.eligible_fixtures} in {rep.eligible_leagues} leagues"))
    leave = (
        html.Button(
            "Leave demo", id={"t": "mode", "m": "live"}, n_clicks=0, className="ch-btn small ghost"
        )
        if snap.is_demo
        else None
    )
    return html.Div(
        [
            *(html.Span([html.Span(k, className="muted"), " ", html.Strong(v)]) for k, v in items),
            leave,
        ],
        className="ch-statusbar small",
        title=FROZEN_NOTE if rv is not None and not snap.is_demo else None,
    )


def frozen_note(snap, rv) -> html.P | None:
    if rv is None or snap is None or snap.is_demo:
        return None
    return html.P(FROZEN_NOTE, className="muted small ch-frozen-note")


def unavailable(service, state, mode, snap, avail, local) -> html.Div:
    actions = []
    if mode == "demo" or (snap is not None and snap.is_demo):
        actions.append(
            html.Button(
                "Leave the demonstration",
                id={"t": "mode", "m": "live"},
                n_clicks=0,
                className="ch-btn ghost",
            )
        )
    else:
        actions.append(
            html.Button(
                "Try the demonstration round",
                id={"t": "mode", "m": "demo"},
                n_clicks=0,
                className="ch-btn primary",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Strong(avail.title + ". "),
                    avail.message,
                    " You can still learn how the Challenge works with the demonstration round: "
                    "historical fixtures and prices, clearly labelled, for practice only.",
                ],
                className="ch-ribbon warn",
            ),
            html.Div(actions, className="ch-actions"),
            how_to_play(True),
        ]
    )


def _filter(label, control, cls="filter"):
    return html.Div([html.Label(label), control], className=cls)


def builder(service, snap, sels, avail, prefs, local, personal=None, state=None) -> html.Div:
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
    state = state or {}
    notes = state.get("notes") or []
    notes_box = (
        html.Div(
            [
                html.Strong("Please review: the round snapshot changed. "),
                "These predictions were taken out of your draft:",
                html.Ul([html.Li(f"{n['label']} — {n['reason']}") for n in notes]),
                html.Button(
                    "OK",
                    id={"t": "dismissnotes", "i": 0},
                    n_clicks=0,
                    className="ch-btn small ghost",
                ),
            ],
            className="ch-ribbon warn",
        )
        if notes
        else None
    )
    new_user = not sels and not state.get("submitted")
    return html.Div(
        [
            c.demo_ribbon(snap),
            status_strip(snap, avail, local, service.round_view()),
            frozen_note(snap, service.round_view()),
            how_to_play(new_user),
            notes_box,
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


def outcome_states(service, snap, sels, keys, is_locked: bool, personal=None) -> list:
    """(className, disabled, title) for the given outcome keys with the current
    selections (used to update visible buttons in place)."""
    chosen = service.outcomes_for(snap, sels)
    blocks = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, CFG)
    personal = personal or {}
    out = []
    for key in keys:
        o = snap.outcome(key)
        a = assess_outcome(o, snap.snapshot_at, CFG)
        out.append(
            c.outcome_state(
                o,
                a.bucket if a.eligible else None,
                blocks.get(o.key),
                is_locked,
                personal.get(o.key),
            )
        )
    return out


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
    bd = pa.calculation_breakdown(port, prob)
    label = pa.SOURCE_LABEL[source]
    names = {o.key: _pick_label(snap, o) for b in port.buckets for o in b}
    return html.Div(
        [
            html.Div(
                [
                    html.H2("Portfolio analysis", className="ch-h2"),
                    html.Span(f"{label} estimate", className="ch-pill demo"),
                ],
                className="ch-row-between",
            ),
            recovery_section(ev, bd, label, names),
            payouts_section(ev, bd),
            correct_section(cc, label),
        ]
    )


def _pick_label(snap, o) -> str:
    fx = snap.fixture(o.fixture_id)
    return f"{fx.home} v {fx.away}: {c.outcome_text(o)}"


def _p(x: float) -> str:
    """Probability for the calculation tables: 4 significant decimals as a percentage."""
    return f"{x * 100:.2f}%" if x >= 0.0001 or x == 0 else f"{x * 100:.4f}%"


def _odds_product(x) -> str:
    """The exact product of decimal odds, or ≈ 4 decimals when it has more than 6."""
    t = format(x.normalize(), "f")
    return t if len(t.split(".")[-1]) <= 6 or "." not in t else f"≈ {x:.4f}"


def outcome_table(bd) -> html.Div:
    """The eight mutually exclusive outcomes (shared by the payouts section and the
    calculation breakdown): completed buckets, probability, gross payout, the
    probability-weighted payout and whether 100.00 is recovered, with a total row."""
    head = html.Tr(
        [
            html.Th("Completed buckets"),
            html.Th("Probability", className="num"),
            html.Th("Gross payout", className="num"),
            html.Th("Probability × payout", className="num"),
            html.Th("100+ back", className="c"),
        ]
    )
    body = [
        html.Tr(
            [
                html.Td(st.label),
                html.Td(_p(st.probability), className="num"),
                html.Td(c.credits(st.gross), className="num"),
                html.Td(f"{st.weighted:,.2f}", className="num"),
                html.Td(
                    [c.icon("check", "ic-sm"), " Yes"] if st.recovers else "No",
                    className="c " + ("ok" if st.recovers else "muted"),
                ),
            ],
            className="rec" if st.recovers else None,
        )
        for st in bd.states
    ]
    total = html.Tr(
        [
            html.Td(html.Strong("Total")),
            html.Td(_p(sum(st.probability for st in bd.states)), className="num"),
            html.Td(""),
            html.Td(html.Strong(f"{bd.expected_gross:,.2f}"), className="num"),
            html.Td(""),
        ],
        className="total",
    )
    return html.Div(
        html.Table([html.Thead(head), html.Tbody([*body, total])], className="ch-table states"),
        className="ch-table-wrap",
    )


def calculation_details(bd, source_label: str, names: dict) -> html.Details:
    """'How are these calculated?': the current portfolio's numbers, step by step,
    straight from the eight-state engine (no separate UI maths)."""
    step1 = []
    for b in bd.buckets:
        ps = " × ".join(_p(leg.probability) for leg in b.legs)
        odds = " × ".join(f"{leg.odds:.2f}" for leg in b.legs)
        step1.append(
            html.Div(
                [
                    html.Div([c.chip(b.code), html.Span(f" {b.stake} credits", className="muted")]),
                    html.Ul(
                        [
                            html.Li(
                                [
                                    html.Span(names.get(leg.key, str(leg.key))),
                                    html.Span(
                                        f"{_p(leg.probability)} · odds {leg.odds:.2f}",
                                        className="muted",
                                    ),
                                ]
                            )
                            for leg in b.legs
                        ],
                        className="ch-calc-legs",
                    ),
                    html.Div(
                        [
                            f"P({b.name} succeeds) = {ps} = ",
                            html.Strong(_p(b.probability)),
                        ],
                        className="ch-calc-eq",
                    ),
                    html.Div(
                        [
                            f"Payout = {b.stake} × ({odds}) = {b.stake} × "
                            f"{_odds_product(b.combined_odds)} = ",
                            html.Strong(c.credits(b.payout)),
                        ],
                        className="ch-calc-eq",
                    ),
                ],
                className=f"ch-calc-bucket b-{c.BUCKET_CLASS[b.code]}",
            )
        )
    nf = bd.nine_fold
    rec = [st for st in bd.states if st.recovers]
    return html.Details(
        [
            html.Summary([c.icon("calculator", "ic-sm"), " How are these calculated?"]),
            html.P(
                [
                    "Using the ",
                    html.Strong(source_label),
                    " probabilities for this portfolio. Payouts always use the frozen "
                    "reference odds, so only the probabilities change between sources.",
                ],
                className="small",
            ),
            html.H4("Step 1 · Each bucket's chance and payout", className="ch-h4"),
            html.P(
                "A bucket pays only if every one of its predictions is correct. The nine "
                "predictions are on different matches, so we treat them as independent: "
                "the result of one match doesn't change the chances in another. The chance "
                "that a bucket succeeds is then its predictions' chances multiplied together.",
                className="muted small",
            ),
            html.Div(step1, className="ch-calc-buckets"),
            html.P(
                [
                    c.chip("NINE"),
                    f" The Diski 9 ({nf.stake} credits) pays {nf.stake} × "
                    f"{_odds_product(nf.combined_odds)} (all nine odds multiplied) = "
                    f"{c.credits(nf.payout)} only when all "
                    f"nine are correct (chance {_p(nf.probability)}). It is not a fourth "
                    "independent bucket: it can only pay when Foundation, Balanced and "
                    "Challenger all succeed, so it appears only in the all-nine outcome below.",
                ],
                className="small",
            ),
            html.H4("Step 2 · All possible payout outcomes", className="ch-h4"),
            html.P(
                "The three buckets can each succeed or fail, giving eight outcomes that "
                "can't happen together; their probabilities add up to 100%. When all nine "
                "are correct the gross payout is the three bucket payouts plus The Diski 9.",
                className="muted small",
            ),
            outcome_table(bd),
            html.H4("Step 3 · Chance of getting 100 credits back", className="ch-h4"),
            html.P(
                [
                    "Add the probabilities of every outcome whose gross payout is at least "
                    "100.00: ",
                    " + ".join(_p(st.probability) for st in rec) or "none",
                    " = ",
                    html.Strong(_p(bd.p_recover)),
                    ".",
                ],
                className="small",
            ),
            html.P(
                "Here some outcomes pay something but less than 100, so the chance of "
                "getting 100 back is not simply 100% minus the chance of nothing back."
                if bd.has_partial
                else "Here every outcome that pays anything pays at least 100, so this also "
                "equals 100% minus the chance of nothing back.",
                className="muted small",
            ),
            html.H4("Step 4 · Expected gross and net", className="ch-h4"),
            html.P(
                [
                    "Expected gross = sum of (outcome probability × gross payout) = ",
                    html.Strong(f"{bd.expected_gross:,.2f}"),
                    " (the total row above). Expected net = expected gross − 100 = ",
                    html.Strong(f"{bd.expected_net:+,.2f}"),
                    ".",
                ],
                className="small",
            ),
            html.P(
                "Expected payout is a probability-weighted average over very many imaginary "
                "repeats of this week. It is not a guarantee and usually not the typical "
                "result. Values are calculated at full precision and rounded only for "
                "display, so the rounded figures shown may not add up exactly.",
                className="muted small",
            ),
        ],
        className="ch-details ch-calc",
    )


def recovery_section(ev, bd=None, source_label: str = "Market", names=None) -> html.Div:
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
                                            html.Strong(f"{ev.expected_gross:,.2f}"),
                                        ]
                                    ),
                                    html.Div(
                                        [
                                            html.Span("Expected net", className="muted small"),
                                            html.Strong(f"{ev.expected_net:+,.2f}"),
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
            calculation_details(bd, source_label, names or {}) if bd is not None else None,
        ],
        className="ch-card",
    )


def payouts_section(ev, bd=None) -> html.Div:
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
                    " and ".join(pa.state_label(s.wins) for s in v) + f" ({c.credits(v[0].gross)})"
                    for v in same
                ),
                className="muted small",
            )
            if same
            else None,
            html.Details(
                [html.Summary("All eight outcomes in a table"), outcome_table(bd)],
                className="ch-details",
            )
            if bd is not None
            else None,
        ],
        className="ch-card",
    )


def correct_section(cc, source_label: str = "Market", view: str = "focus") -> html.Div:
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
            html.Div(
                [
                    html.Span("Payout line:", className="muted small"),
                    dcc.RadioItems(
                        id=c.T("k-view"),
                        value=view,
                        inline=True,
                        className="ch-k ch-kview",
                        options=[
                            {"label": "Focus on 0–8 correct", "value": "focus"},
                            {"label": "Show all nine", "value": "all"},
                        ],
                    ),
                ],
                className="ch-k-row",
            ),
            dcc.Graph(
                id=c.T("k-hist"),
                figure=charts.correct_combined(cc, k0, view),
                config={"displayModeBar": False},
                className="ch-hist",
            ),
            html.P(
                [
                    f"Bars: the {source_label} chance of exactly that many correct "
                    "(left axis). Line: the average gross payout if exactly that many are "
                    "correct, weighting each combination by its probability (right axis). "
                    "Click a bar or choose a number below for details.",
                ],
                className="muted small",
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
            html.Div(
                [
                    html.Span(["Chance ", html.Strong(_p(r.probability))]),
                    html.Span(["Combinations ", html.Strong(str(r.combinations))]),
                    html.Span(["Average payout ", html.Strong(f"{r.expected_gross:,.2f}")]),
                    html.Span(["Minimum ", html.Strong(c.credits(r.min_gross))]),
                    html.Span(["Maximum ", html.Strong(c.credits(r.max_gross))]),
                    html.Span(["Get 100+ back ", html.Strong(c.pct(r.p_recover, 1))]),
                ],
                className="ch-kstats small",
            ),
        ],
        className="ch-kdetail",
    )


# ----------------------------------------------------------------- review
def estimate_cards(estimates: dict, tags: dict | None = None) -> html.Div:
    """Market / Diski 9 / Your View summary cards (recovery first). ``tags`` adds a
    small label beside a source's name (for example Your View "now")."""
    tags = tags or {}
    cards = []
    for src in pa.SOURCES:
        e = estimates.get(src)
        if not e:
            continue
        cards.append(
            html.Div(
                [
                    html.Span(
                        [
                            pa.SOURCE_LABEL[src],
                            html.Span(tags[src], className="ch-src-tag") if src in tags else None,
                        ],
                        className="ch-src-name",
                    ),
                    html.Div(
                        [
                            html.Span("Get 100+ back", className="muted small"),
                            html.Strong(c.pct(e["p_recover"], 1), className="ch-big teal"),
                        ]
                    ),
                    html.Div(
                        [
                            html.Span("Nothing back", className="muted small"),
                            html.Strong(c.pct(e["p_zero"], 1)),
                        ]
                    ),
                    html.Div(
                        [
                            html.Span("Expected gross", className="muted small"),
                            html.Strong(f"{e['expected']:,.2f}"),
                        ]
                    ),
                ],
                className="ch-src-card" + (" primary" if src == "market" else ""),
            )
        )
    return html.Div(cards, className="ch-src-cards")


def picks_table(rows) -> html.Div:
    head = html.Tr(
        [
            html.Th("Bucket"),
            html.Th("Match"),
            html.Th("Prediction"),
            html.Th("Market", className="num"),
            html.Th("Diski 9", className="num"),
            html.Th("Odds", className="num"),
        ]
    )
    return html.Div(
        html.Table([html.Thead(head), html.Tbody(rows)], className="ch-table"),
        className="ch-table-wrap",
    )


def review(service, snap, sels, avail, state, local, personal=None) -> html.Div:
    port = service.portfolio(snap, sels)
    evs = pa.evaluate_sources(port, personal or {})
    rows = []
    for code, b in zip(CFG.bucket_codes, port.buckets, strict=True):
        for o in b:
            fx = snap.fixture(o.fixture_id)
            rows.append(
                html.Tr(
                    [
                        html.Td(c.chip(code)),
                        html.Td(f"{fx.home} v {fx.away}"),
                        html.Td(c.outcome_text(o)),
                        html.Td(c.pct_in_band(o.market_probability, code), className="num"),
                        html.Td(c.pct(o.model_probability, 1), className="num"),
                        html.Td(f"{o.reference_odds:.2f}", className="num"),
                    ]
                )
            )
    sub = st.submission_for(state, snap)
    same = st.same_portfolio(sub, sels)
    other = bool(sub) and not same
    can_submit = avail.playable and not locked(avail)
    kind = access(service, snap)
    label = (
        "Confirmed"
        if same
        else ("Replace my confirmed entry" if kind == "account" else
              "Replace my confirmed portfolio")
        if other
        else "Confirm demonstration portfolio"
        if snap.is_demo
        else "Confirm entry"
        if kind == "account"
        else "Confirm portfolio"
    )  # fmt: skip
    if kind == "account" and (state.get("acct") or {}).get("dirty"):
        can_submit = False  # unsaved changes must be saved (or reloaded) first
    footer = {
        "account": "Confirming re-checks your saved portfolio against the frozen round and "
        "records it as your entry. You can replace or withdraw it until the deadline.",
        "guest": "Sign in to confirm an entry. Until then your portfolio is kept in this "
        "browser tab only.",
        "setup": "Finish setting up your account to confirm an entry. Until then your "
        "portfolio is kept in this browser tab only.",
    }.get(kind, "Prototype: confirming re-checks your portfolio and records it in this "
               "browser tab only. It is not a competition entry.")  # fmt: skip
    if kind == "guest":
        submit_button = html.A(
            [c.icon("send", "ic-sm"), " Sign in to confirm"],
            href="/auth/sign-in?next=/challenge",
            className="ch-btn primary big",
        )
    elif kind == "setup":
        submit_button = html.A(
            [c.icon("send", "ic-sm"), " Finish set-up to confirm"],
            href="/account/welcome",
            className="ch-btn primary big",
        )
    else:
        submit_button = html.Button(
            [c.icon("circle-check" if same else "send", "ic-sm"), " ", label],
            id=c.T("submit"),
            n_clicks=0,
            disabled=same or not can_submit,
            className="ch-btn primary big",
        )
    estimates = {
        s: {"p_recover": ev.p_recover, "p_zero": ev.p_zero, "expected": ev.expected_gross}
        for s, ev in evs.items()
    }
    if not personal:
        estimates.pop("personal")
    return html.Div(
        [
            c.demo_ribbon(snap),
            html.Div(
                [
                    html.H2("Review & Submit", className="ch-h2"),
                    html.Span(f"Round {snap.round_id}", className="muted small"),
                ],
                className="ch-row-between",
            ),
            estimate_cards(estimates),
            html.P(
                (
                    "Your View uses your Match Lab adjustments where you made them and Diski 9 "
                    "elsewhere. "
                    if personal
                    else ""
                )
                + "Every estimate assumes independent "
                "matches and is uncertain. Payouts are the same under every estimate: the "
                f"maximum, {c.credits(evs['market'].max_gross)} credits, needs all nine "
                "predictions to be correct.",
                className="muted small",
            ),
            html.Div(
                [
                    picks_table(rows),
                    html.P(
                        f"Allocation: Foundation 40, Balanced 30, Challenger 20, The Diski 9 "
                        f"10 credits. Frozen {local(snap.snapshot_at)} SAST · configuration "
                        f"{snap.config_version}.",
                        className="muted small",
                    ),
                ],
                className="ch-card",
            ),
            html.Div(
                [
                    html.Strong(
                        "You already have a confirmed "
                        + ("entry " if kind == "account" else "portfolio ")
                    ),
                    f"(round {sub['round_id']}, confirmed {local(sub['at'])}). It stays recorded "
                    "unless this one passes every check and you replace it.",
                ],
                className="ch-ribbon",
            )
            if other
            else None,
            html.Div(
                [
                    html.Button(
                        "← Back to builder",
                        id={"t": "nav", "to": "build", "i": "rv"},
                        n_clicks=0,
                        className="ch-btn ghost",
                    ),
                    withdraw_button("rv") if sub and can_submit else None,
                    submit_button,
                ],
                className="ch-actions end",
            ),
            html.P(footer, className="muted small"),
            confirmation_modal(state, local) if state.get("modal") and sub else None,
            withdraw_modal(sub, local) if state.get("confirm") == "withdraw" and sub else None,
        ]
    )


def withdraw_button(where: str) -> html.Button:
    """Secondary, restrained destructive action (never the primary button)."""
    return html.Button(
        [c.icon("undo", "ic-sm"), " Withdraw submission"],
        id={"t": "askwithdraw", "i": where},
        n_clicks=0,
        className="ch-btn ghost danger",
        title="Remove your confirmed entry for this round (you'll be asked to confirm)",
    )


def withdraw_modal(sub, local) -> html.Div:
    """Explicit confirmation before a confirmed submission is withdrawn."""
    return html.Div(
        html.Div(
            [
                html.Div(c.icon("alert", "ic-lg"), className="ch-modal-icon warn"),
                html.H2("Withdraw your submission?", className="ch-modal-title plain"),
                html.P(
                    f"This withdraws your confirmed entry for round {sub['round_id']} "
                    f"(confirmed {local(sub['at'])} SAST)"
                    + (
                        ". Your saved portfolio stays in your account."
                        if sub.get("persistent")
                        else " and clears your working portfolio."
                    )
                ),
                html.P(
                    "You can confirm again before the deadline. Nothing is resubmitted "
                    "automatically, and the withdrawal is recorded in your entry history.",
                    className="muted small",
                )
                if sub.get("persistent")
                else html.P(
                    "You can build and submit a new portfolio before the deadline. Your old "
                    "selections are not resubmitted automatically.",
                    className="muted small",
                ),
                html.Div(
                    [
                        html.Button(
                            "Keep my submission",
                            id={"t": "cancelwithdraw", "i": 0},
                            n_clicks=0,
                            className="ch-btn ghost",
                        ),
                        html.Button(
                            [c.icon("undo", "ic-sm"), " Withdraw submission"],
                            id={"t": "confirmwithdraw", "i": 0},
                            n_clicks=0,
                            className="ch-btn danger",
                        ),
                    ],
                    className="ch-actions",
                ),
            ],
            className="ch-modal",
            role="alertdialog",
            **{"aria-modal": "true", "aria-label": "Withdraw submission"},
        ),
        className="ch-modal-backdrop",
    )


def confirmation_modal(state, local) -> html.Div:
    sub = state["submitted"]
    demo_word = "demonstration " if sub.get("mode") == "demo" else ""
    return html.Div(
        html.Div(
            [
                html.Div(c.icon("circle-check", "ic-lg"), className="ch-modal-icon"),
                html.H2("You're in!", className="ch-modal-title"),
                html.P(
                    "Your entry has been confirmed."
                    if sub.get("persistent")
                    else f"Your {demo_word}portfolio has been confirmed."
                ),
                html.P(html.Strong("9 predictions. 100 virtual credits.")),
                html.P("Good luck with your Diski 9 predictions!"),
                html.P(
                    f"Round {sub['round_id']} · {local(sub['at'])} SAST"
                    + (" · demonstration only, not a competition entry" if demo_word else ""),
                    className="muted small",
                ),
                html.Div(
                    [
                        dcc.Link(
                            "View My Challenge", href="/challenge/me", className="ch-btn primary"
                        ),
                        html.Button(
                            "Close",
                            id={"t": "modalclose", "i": 0},
                            n_clicks=0,
                            className="ch-btn ghost",
                        ),
                    ],
                    className="ch-actions",
                ),
            ],
            className="ch-modal",
            role="dialog",
            **{"aria-modal": "true", "aria-label": "Portfolio confirmed"},
        ),
        className="ch-modal-backdrop",
    )


# ------------------------------------------------------------- my challenge
CLASSIFICATION_TEXT = {
    "competitive": "competitive round (unofficial beta: no official championship yet)",
    "practice": "practice round (fewer than five valid entries)",
}


def round_state(state, snap, avail, sels, kind="prototype", rv=None) -> tuple[str, str, str]:
    """(label, css class, one-line explanation) for the participant's round status."""
    sub = st.submission_for(state, snap)
    account = kind == "account"
    if locked(avail) and snap is not None and getattr(rv, "status", None) == "open":
        # Deadline passed, lock job not run yet: no changes possible, not "locked".
        if sub:
            return (
                "Deadline passed",
                "warn",
                (
                    "The submission deadline has passed. Your confirmed entry can no longer "
                    "change; the round is waiting to be locked."
                ),
            )
        return (
            "Deadline passed",
            "warn",
            (
                "The submission deadline has passed without a confirmed entry. The round is "
                "waiting to be locked."
            ),
        )
    if locked(avail) and snap is not None:
        cls_text = CLASSIFICATION_TEXT.get(getattr(rv, "classification", None) or "")
        tail = f" This is a {cls_text}." if cls_text else ""
        if sub:
            return "Locked", "warn", ("Your entry is locked." if account else
                                      "The deadline has passed; predictions can no longer "
                                      "change.") + tail  # fmt: skip
        return "Locked", "warn", "The deadline has passed without a confirmed entry." + tail
    if snap is None or not avail.playable:
        return "Unavailable", "off", avail.message
    if sub and st.same_portfolio(sub, sels):
        return (
            "Confirmed",
            "ok",
            (
                "Your entry is confirmed for this round."
                if account
                else "Your portfolio is confirmed for this round."
            ),
        )
    if sub:
        return (
            "Confirmed",
            "ok",
            "Your entry is confirmed. Your saved portfolio has changes that are not confirmed."
            if account
            else "Your portfolio is confirmed. Your working draft differs and has not been "
            "submitted.",
        )
    wd = state.get("withdrawn") or {}
    if wd.get("round_id") == snap.round_id and wd.get("mode") == st.mode_key(snap):
        return (
            "Withdrawn",
            "warn",
            "You withdrew your submission. "
            + (f"{len(sels)} of 9 predictions in a new draft." if sels else "")
            + " You can submit a new portfolio before the deadline.",
        )
    if account and len(sels) == CFG.required_selections:
        return "Ready to confirm", "demo", "Your saved portfolio is complete but not confirmed."
    if sels:
        return (
            "Draft in progress",
            "demo",
            (
                f"{len(sels)} of 9 predictions saved to your account."
                if account
                else f"{len(sels)} of 9 predictions chosen."
            ),
        )
    return "Not started", "off", "Build a portfolio of nine predictions."


def round_facts(state, snap, avail, sels, sub, label, local, rv=None) -> list[tuple[str, str]]:
    """Round details for the "This round" card, all from the stored prototype state
    and the round snapshot (nothing hard-coded beyond the approved allocation)."""
    if snap is None or not (avail.playable or locked(avail)):
        facts = [("Status", label)]
        if snap is not None:
            facts.insert(0, ("Round", snap.round_id))
        return facts + [("Credits", f"{CFG.total_credits} virtual credits per entry")]
    facts = [
        ("Round", ("Demonstration · " if snap.is_demo else "Live · ") + snap.round_id),
        ("Status", label),
    ]
    if sub:
        n = len(sub.get("selections") or [])
        facts.append(("Predictions", f"{n} of {CFG.required_selections} submitted"))
    else:
        facts.append(("Predictions", f"{len(sels)} of {CFG.required_selections} in your draft"))
    if snap.is_demo:
        facts.append(("Deadline", "None: demonstration round, practice only"))
    elif rv is not None:
        if rv.published_at is not None:
            facts.append(("Published", f"{local(rv.published_at)} SAST"))
        facts += round_times(rv, local)
        if rv.classification:
            facts.append(("Classification", CLASSIFICATION_TEXT[rv.classification].capitalize()))
    elif snap.deadline:
        facts.append(("Deadline", f"{local(snap.deadline)} SAST"))
    alloc = " / ".join(str(b.credits) for b in CFG.buckets) + f" / {CFG.nine_fold_credits}"
    facts.append(("Credits", f"{CFG.total_credits} virtual ({alloc})"))
    wd = state.get("withdrawn") or {}
    if sub:
        ver = f" (version {sub['version']})" if sub.get("version", 1) > 1 else ""
        facts.append(("Confirmation", f"Confirmed {local(sub['at'])} SAST{ver}"))
    elif wd.get("round_id") == snap.round_id and wd.get("mode") == st.mode_key(snap):
        facts.append(("Confirmation", f"Withdrawn {local(wd['at'])} SAST"))
    else:
        facts.append(("Confirmation", "Not confirmed"))
    if locked(avail) and getattr(rv, "status", None) == "open":
        facts.append(("Changes", "None possible: the deadline has passed (lock pending)"))
    elif locked(avail):
        facts.append(("Changes", "Locked: the deadline has passed"))
    elif sub:
        facts.append(("Changes", "You can replace or withdraw until the round locks"))
    else:
        facts.append(("Changes", "Build and confirm before the round locks"))
    return facts


def round_card(
    state, snap, avail, sels, sub, label, cls, line, local, kind="prototype", rv=None
) -> html.Div:
    facts = round_facts(state, snap, avail, sels, sub, label, local, rv)
    note = {
        "account": "Saved to your account. Results appear on My Challenge as the matches "
        "are settled.",
        "guest": "Kept in this browser tab only. Sign in to save your portfolio and confirm "
        "an entry.",
        "setup": "Kept in this browser tab only. Finish setting up your account to save "
        "and confirm.",
    }.get(kind, "Prototype: this entry is kept only in this browser tab. It is not an "
               "official competition entry.")  # fmt: skip
    return html.Div(
        [
            html.Div(
                [
                    html.H2("This round", className="ch-h2"),
                    html.Span(label, className=f"ch-pill {cls}"),
                ],
                className="ch-row-between",
            ),
            html.P(line, className="small ch-round-line"),
            html.Dl(
                [item for k, v in facts if k != "Status" for item in (html.Dt(k), html.Dd(v))],
                className="ch-facts small",
            ),
            html.Div(
                className="ch-total-bar",
                children=html.Div(className="fill", style={"width": f"{len(sels) / 9:.0%}"}),
            ),
            html.Div(
                [
                    dcc.Link(
                        [
                            "Build a new portfolio "
                            if label == "Withdrawn"
                            else "Open the Weekly Challenge ",
                            c.icon("arrow-right", "ic-sm"),
                        ],
                        href="/challenge",
                        className="ch-lab-link",
                    ),  # fmt: skip
                    html.P(note, className="muted small ch-proto-note"),
                ],
                className="ch-card-foot",
            ),
        ],
        className="ch-card ch-compact ch-round-card",
    )


def your_view_now(service, snap, sub) -> dict | None:
    """Your View for the confirmed nine predictions **now** (signed-in participant):
    the frozen-context Your View saved in the account for this round, applied to the
    confirmed predictions. Shown privately on My Challenge only; never stored with
    the entry and never used for scoring. ``None`` when nothing applies."""
    from . import integration, lab_persist

    if not sub or not sub.get("persistent") or snap is None:
        return None
    try:
        lab = lab_persist.load_round(service, {})
        personal = integration.personal_probabilities(None, snap, lab)
    except Exception:  # noqa: BLE001 - the card is simply not shown
        return None
    keys = sub.get("selections") or []
    chosen = {o.key for o in service.outcomes_for(snap, keys)}
    personal = {k: v for k, v in personal.items() if k in chosen}
    port = service.portfolio(snap, keys)
    if port is None:
        return None
    if not personal:
        return {"adjusted": 0}
    ev = pa.evaluate_sources(port, personal)["personal"]
    return {
        "adjusted": len({k[0] for k in personal}),
        "estimate": {"p_recover": ev.p_recover, "p_zero": ev.p_zero, "expected": ev.expected_gross},
    }


def confirmed_summary(sub, local, can_withdraw: bool, your_view=None, settled=False) -> html.Div:
    """Compact card: the frozen submission's Market / Diski 9 estimates, and (for a
    signed-in participant) Your View calculated now, as a third card of the same size,
    labelled private and not part of the entry."""
    estimates = dict(sub.get("estimates") or {})
    tags: dict = {}
    yv_note = None
    if your_view is not None and your_view.get("estimate"):
        estimates["personal"] = your_view["estimate"]
        tags["personal"] = "now"
        n = your_view["adjusted"]
        yv_note = (
            f"Your View is calculated now from your Weekly Challenge adjustments ({n} of 9 "
            "matches; the rest use Diski 9). Private, not part of your entry, never scored."
        )
    elif your_view is not None:
        yv_note = (
            "Your View: adjust one of these matches in the Match Lab from the Weekly "
            "Challenge to see your own estimate here."
        )
    return html.Div(
        [
            html.Div(
                [
                    html.H2("Confirmed portfolio", className="ch-h2"),
                    html.Span(
                        ("Demonstration · " if sub.get("mode") == "demo" else "")
                        + f"round {sub['round_id']} · {local(sub['at'])} SAST",
                        className="muted small",
                    ),
                ],
                className="ch-row-between",
            ),
            html.P(
                "Pre-match estimates from when you confirmed. They are expectations, not "
                "your result: see Your result for what actually happened.",
                className="small ch-prematch-note",
            )
            if settled
            else None,
            estimate_cards(estimates, tags),
            html.P(yv_note, className="muted small ch-yv-now-note") if yv_note else None,
            html.Div(
                [
                    html.Span(
                        "Market and Diski 9 values frozen when you confirmed. Maximum payout "
                        f"{c.credits(sub.get('max_gross', '0'))}.",
                        className="muted small",
                    ),
                    withdraw_button("me") if can_withdraw else None,
                ],
                className="ch-row-between ch-conf-foot ch-card-foot",
            ),
        ],
        className="ch-card ch-compact ch-conf-summary",
    )


def confirmed_predictions(
    sub, summary: str = "Show my nine predictions", cls: str = ""
) -> html.Details:
    """Full-width expandable card: the nine frozen predictions in three bucket
    columns (stacked on narrow screens) and a one-line Diski 9 summary."""
    groups = []
    for b in CFG.buckets:
        picks = [p for p in sub.get("picks", []) if p["bucket"] == b.code]
        groups.append(
            html.Div(
                [
                    html.Div(
                        [
                            c.chip(b.code),
                            html.Span(f"{b.credits} credits", className="muted small"),
                        ],
                        className="ch-trk-head",
                    ),
                    html.Ul(
                        [
                            html.Li(
                                [
                                    html.Span(p["match"], className="ch-pick-fx"),
                                    html.Span(
                                        [
                                            html.Span(p["outcome"]),
                                            html.Span(
                                                f"Mkt {c.pct(p['market'], 1)} · {p['odds']}",
                                                className="muted",
                                            ),
                                        ],
                                        className="ch-pick-sub small",
                                    ),
                                ],
                                className="ch-pick-text",
                            )
                            for p in picks
                        ],
                        className="ch-conf-list",
                    ),
                ],
                className=f"ch-conf-bucket b-{c.BUCKET_CLASS[b.code]}",
            )
        )
    return html.Details(
        [
            html.Summary(summary),
            html.Div(groups, className="ch-conf-grid"),
            html.P(
                [
                    c.chip("NINE"),
                    f" {CFG.nine_fold_credits} credits on all nine predictions together "
                    "(pays only if every prediction is correct).",
                ],
                className="small ch-conf-nine",
            ),
        ],
        className=("ch-details ch-card ch-conf-card " + cls).strip(),
    )


def locked_entry_card(rec, local, res=None) -> html.Div:
    """Most recent locked entry (read-only): the participant's confirmed entry in a
    round whose deadline has passed, shown beside another current round. Values are
    the stored submission's; actual results (when settled) come from the
    authoritative settlement (``res``); no actions."""
    pending = rec.get("round_status") == "open"
    label, line = (
        ("Deadline passed", "The submission deadline has passed, so this entry can no "
         "longer change. The round is waiting to be locked.")
        if pending
        else ("Locked", "This entry is locked. It cannot be edited, replaced or withdrawn.")
    )  # fmt: skip
    pill = "warn"
    if res is not None and res.settled:
        label, pill, line = results_ui.status(res)
    alloc = " / ".join(str(b.credits) for b in CFG.buckets) + f" / {CFG.nine_fold_credits}"
    ver = f" (version {rec['version']})" if rec.get("version", 1) > 1 else ""
    facts = [
        ("Round", ("Development · " if rec.get("development") else "") + rec["round_id"]),
        ("Status", label),
    ]
    if rec.get("deadline"):
        facts.append(("Deadline", f"{local(rec['deadline'])} SAST"))
    facts.append(("Frozen odds", f"{local(rec['snapshot_at'])} SAST"))
    facts.append(("Confirmed", f"{local(rec['at'])} SAST{ver}"))
    if rec.get("classification"):
        facts.append(("Classification", CLASSIFICATION_TEXT[rec["classification"]].capitalize()))
    facts += [
        ("Credits", f"{CFG.total_credits} virtual ({alloc})"),
        ("Maximum payout", c.credits(rec.get("max_gross", "0"))),
    ]
    if res is None or not res.settled:
        facts.append(("Results", "Pending: results appear here as the matches are settled"))
    settled = res is not None and res.settled
    card = html.Div(
        [
            html.Div(
                [
                    html.H2(
                        "Most recent entry" if settled else "Most recent locked entry",
                        className="ch-h2",
                    ),
                    html.Span(label, className=f"ch-pill {pill}"),
                ],
                className="ch-row-between",
            ),
            html.P(line, className="small ch-round-line"),
            html.Dl(
                [item for k, v in facts if k != "Status" for item in (html.Dt(k), html.Dd(v))],
                className="ch-facts small",
            ),
            html.P(
                "Pre-match estimates from when you confirmed (expectations, not results).",
                className="small ch-prematch-note",
            )
            if settled
            else None,
            estimate_cards(rec.get("estimates") or {}),
            None
            if settled
            else confirmed_predictions(
                rec, f"Show the nine predictions in {rec['round_id']}", "ch-locked-preds"
            ),
        ],
        className="ch-card ch-compact ch-locked-entry",
    )
    if not settled:
        return card
    return html.Div(
        [
            card,
            *results_ui.panel(
                res, rec, local, f"Show the nine predictions and results in {rec['round_id']}"
            ),
        ],
        className="ch-prev-entry",
    )


def timeline(items) -> html.Div:
    icons = {"recovered": "check", "lost": "x", "missed": "minus", "remaining": None}
    titles = {
        "recovered": "Recovered",
        "lost": "Not recovered",
        "missed": "Not entered",
        "remaining": "Still to play",
    }
    dots = []
    for i, it in enumerate(items):
        tip = f"Round {i + 1}: {titles[it['state']]}"
        if it.get("rank"):
            tip += f" · rank {it['rank']} · {it['points']} pts"
        dots.append(
            html.Div(
                [
                    html.Span(
                        c.icon(icons[it["state"]], "ic-sm") if icons[it["state"]] else None,
                        className="dot",
                    ),
                    html.Span(str(i + 1), className="lbl"),
                ],
                className=f"ch-tl-item {it['state']}",
                title=tip,
            )
        )
    legend = html.Div(
        [
            html.Span(
                [html.Span(c.icon("check", "ic-sm"), className="dot k recovered"), "recovered"]
            ),
            html.Span([html.Span(c.icon("x", "ic-sm"), className="dot k lost"), "not recovered"]),
            html.Span(
                [html.Span(c.icon("minus", "ic-sm"), className="dot k missed"), "not entered"]
            ),
            html.Span([html.Span("", className="dot k remaining"), "to play"]),
        ],
        className="ch-tl-legend small muted",
    )
    return html.Div([html.Div(dots, className="ch-timeline"), legend])


def my_challenge(service, state, local) -> html.Div:
    return html.Div(
        [
            c.page_header("My Challenge"),
            html.Div(id=c.T("me"), children=my_challenge_body(service, state, local)),
        ],
        className="ch-page",
    )


def my_challenge_body(service, state, local) -> list:
    """Re-rendered whenever the participant state changes (withdrawal, a new
    submission, a restored session), so the page never shows a stale state."""
    state = sync(service, state)
    mode, snap, avail, sels = current(service, state)
    kind = access_kind = access(service, snap)
    rv = service.round_view() if kind != "prototype" or (snap and not snap.is_demo) else None
    label, cls, line = round_state(state, snap, avail, sels, kind, rv)
    sub = st.submission_for(state, snap)
    res = None
    if (
        access_kind == "account"
        and sub
        and getattr(rv, "status", None) in ("locked", "settling", "final")
    ):
        res = results_ui.fetch(service, rv.id)  # authoritative, re-read on every render
        if res is not None and res.settled:
            label, cls, line = results_ui.status(res)
    settled = res is not None and res.settled
    can_withdraw = bool(sub) and avail.playable and not locked(avail)
    status = round_card(state, snap, avail, sels, sub, label, cls, line, local, kind, rv)
    if sub:
        yv_now = your_view_now(service, snap, sub) if access_kind == "account" else None
        confirmed = confirmed_summary(sub, local, can_withdraw, yv_now, settled=settled)
    else:
        confirmed = html.Div(
            [
                html.H2("Confirmed portfolio", className="ch-h2"),
                html.P(
                    "Nothing confirmed for this round. Confirm a portfolio on the Review & "
                    "Submit step.",
                    className="muted small",
                ),
            ],
            className="ch-card ch-compact ch-conf-summary",
        )
    m = demo.demo_summary()
    rate = c.pct(m["recovery_rate"], 0) if m["recovery_rate"] is not None else "—"
    perf = html.Div(
        [
            html.Div(
                [
                    html.H2("Championship (illustrative)", className="ch-h2"),
                    html.Span(
                        f"Round {m['completed']} of {m['required']}", className="muted small"
                    ),
                ],
                className="ch-row-between",
            ),
            html.Div(
                "Demonstration data: invented results that show how weekly and championship "
                "points work. They are not your submitted portfolio's results.",
                className="ch-ribbon small",
            ),
            html.Div(
                [
                    c.metric("Championship points", str(m["points"])),
                    c.metric("Rank", f"{m['rank']} of {m['field']}" if m["rank"] else "—"),
                    c.metric(
                        "Recoveries",
                        f"{m['recoveries']} of {m['entered']}",
                        f"{rate} recovery rate",
                    ),
                    c.metric("Top-ten finishes", str(m["top10"]), "with a recovery"),
                    c.metric("Best weekly finish", str(m["best_finish"] or "—")),
                ],
                className="ch-metrics five",
            ),
            timeline(m["timeline"]),
        ],
        className="ch-card",
    )
    rows = []
    for r, s in demo.demo_history():
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
                    html.Td(
                        "Yes"
                        if s and s.recovered and s.counts_for_championship
                        else "—"
                        if kind != "Competitive"
                        else "No",
                        className="c",
                    ),
                    html.Td(str(s.points) if s else "0", className="num strong"),
                ]
            )
        )
    hist = html.Details(
        [
            html.Summary("Round-by-round history (illustrative)"),
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
                                    html.Th("Recovered", className="c"),
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
            html.P(
                "Practice and void rounds don't count toward points, recoveries or progress.",
                className="muted small",
            ),
        ],
        className="ch-details ch-card",
    )
    previous = None
    if access_kind == "account":
        from . import persist

        rec = persist.most_recent_locked(service, getattr(rv, "id", None))
        if rec:
            prev_res = results_ui.fetch(service, UUID(rec["round_uuid"]))
            previous = locked_entry_card(rec, local, prev_res)
    current_results = results_ui.panel(res, sub, local) if settled else []
    return [
        html.Div([status, confirmed], className="ch-grid-me"),
        *current_results,
        None if settled else (confirmed_predictions(sub) if sub else None),
        previous,
        perf,
        hist,
        withdraw_modal(sub, local) if state.get("confirm") == "withdraw" and sub else None,
    ]


# -------------------------------------------------------------- leaderboards
def leaderboards() -> html.Div:
    rounds = demo.demo_rounds()
    return html.Div(
        [
            c.page_header("Leaderboards"),
            html.Div(
                "Demonstration data: invented players and results, scored with the real "
                "points rules. Leaderboards from real entries arrive with settlement in a "
                "later phase.",
                className="ch-ribbon",
            ),
            html.Div(
                [
                    dcc.RadioItems(
                        id=c.T("lb-tab"),
                        value="weekly",
                        inline=True,
                        className="segmented ch-view",
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
            html.Div(id=c.T("lb-body"), children=leaderboard_body("weekly", demo.LATEST_ROUND)),
        ],
        className="ch-page",
    )


def leaderboard_body(tab: str, round_id: str | None):
    if tab == "championship":
        table = demo.demo_championship()
        rows = [(s.rank, s.participant_id, f"{s.points} pts") for s in table.standings]
        me = next((s for s in table.standings if s.participant_id == demo.YOU), None)
        you = c.you_summary(
            f"#{me.rank}" if me else "—",
            f"{me.points} pts · {me.recoveries} recoveries" if me else "not entered",
            f"{table.completed_rounds} rounds completed, "
            f"{table.rounds_required - table.completed_rounds} remaining",
        )
        return [
            you,
            c.podium(rows),
            html.Div(
                [
                    html.H2(f"Championship {demo.CHAMPIONSHIP_ID}", className="ch-h2"),
                    c.championship_table(table),
                ],
                className="ch-card",
            ),
        ]
    rid = round_id or demo.LATEST_ROUND
    r = next(x for x in demo.demo_rounds() if x.round_id == rid)
    score = demo.demo_round_score(rid)
    ranked = [
        (s.rank, s.participant_id, f"{s.points} pts · returned {s.gross:,.2f}")
        for s in score.scores
        if s.rank is not None
    ]
    me = next((s for s in score.scores if s.participant_id == demo.YOU), None)
    if me is None:
        you = c.you_summary("—", "not entered this week", "")
    elif me.rank is None:
        you = c.you_summary("—", "Void — Refunded" if me.refunded else "not ranked", "")
    else:
        you = c.you_summary(
            f"#{me.rank}",
            f"{me.points} pts · returned {me.gross:,.2f}",
            "Recovered" if me.recovered else "Not recovered",
        )
    podium = c.podium(ranked) if r.classification.value != "void" else None
    return [
        you,
        podium,
        html.Div(
            [html.H2(f"Week {rid}", className="ch-h2"), c.weekly_table(score, r)],
            className="ch-card",
        ),
    ]


__all__ = ["key_str"]
