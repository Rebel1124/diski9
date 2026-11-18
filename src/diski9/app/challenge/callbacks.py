"""Weekly Challenge callbacks: UI state, engine calls and rendering only.

Participant state is the browser-session store ``ch-session`` (``sessionStorage``:
one browser tab, survives a page refresh, never sent to other users, never kept
on the server). The educational explorer keeps its own memory store
``ch-explore`` so it can never touch the portfolio.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.education import illustrate
from diski9.challenge.structured import SelectionBlock, selection_blocks, validate_portfolio

from . import components as c
from . import pages
from .charts import at_least_figure, exact_figure, focus_range
from .service import ChallengeService, key_str, parse_key

NAV = (
    ("/", "Screener"),
    ("/challenge", "Weekly Challenge"),
    ("/challenge/me", "My Challenge"),
    ("/leaderboards", "Leaderboards"),
)


def nav_links(path: str) -> list:
    path = path or "/"
    return [
        dcc.Link(label, href=href, className="nav-link" + (" on" if path == href else ""))
        for href, label in NAV
    ]


def _flash(text: str, kind: str = "info") -> dict:
    return {"text": text, "kind": kind}


# ------------------------------------------------------------- the reducer
def apply_action(service: ChallengeService, state: dict | None, action: str, arg=None):
    """Pure state transition: (new state, flash or None). Every rule check is an
    engine call; this function only decides what the UI does with the answer."""
    s = pages.normal_state(state)
    mode = pages.effective_mode(service, s)
    snap = service.snapshot(mode) if mode else None
    if snap is not None and s.get("fp") != snap.fingerprint:
        if s["selections"]:
            flash = _flash(
                "The round snapshot changed, so your earlier draft was cleared. "
                "Selections are never carried between snapshots.",
                "warn",
            )
            s.update(selections=[], submitted=None, fp=snap.fingerprint, mode=mode)
            return s, flash
        s.update(fp=snap.fingerprint, mode=mode)
    avail = service.availability(mode or "live")

    if action == "mode":
        new = service.snapshot(arg)
        s = pages.normal_state(
            {"mode": arg if arg == "demo" else None, "fp": new.fingerprint if new else None}
        )
        return s, None
    if action == "nav":
        if arg in ("analyse", "review") and service.evaluate(snap, s["selections"]) is None:
            return s, _flash("Complete all nine predictions first.", "warn")
        if arg == "build" and not avail.playable:
            return s, _flash(avail.message, "warn")
        s["stage"] = arg
        return s, None
    if snap is None:
        return s, _flash("No round is available.", "warn")
    if action in ("pick", "remove", "clear") and pages.locked(avail):
        return s, _flash("This round is locked; predictions can't change.", "warn")
    if action == "clear":
        s["selections"] = []
        return s, _flash("Portfolio cleared.")
    if action == "remove":
        s["selections"] = [k for k in s["selections"] if k != arg]
        return s, None
    if action == "pick":
        if arg in s["selections"]:  # tapping a selected outcome removes it
            s["selections"] = [k for k in s["selections"] if k != arg]
            return s, None
        o = snap.outcome(parse_key(arg))
        if o is None:
            return s, _flash("That outcome is not on this round's sheet.", "warn")
        chosen = service.outcomes_for(snap, s["selections"])
        block = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, DEFAULT_CONFIG).get(o.key)
        if block is None:
            s["selections"] = [*s["selections"], arg]
            return s, None
        return s, _flash(
            {
                SelectionBlock.INELIGIBLE: "That outcome isn't eligible: its market chance is "
                "outside 20%–95% or its odds don't qualify.",
                SelectionBlock.FIXTURE_TAKEN: "You already have a prediction from this match. "
                "Remove it first to choose a different outcome.",
                SelectionBlock.BUCKET_FULL: "That bucket is full. Remove one of its predictions "
                "to swap it.",
                SelectionBlock.WOULD_BLOCK_COMPLETION: "Adding that would make your portfolio "
                "impossible to finish with the matches left.",
            }[block],
            "warn",
        )
    if action == "submit":
        return submit(service, s, snap, avail)
    return s, None


def submit(service, s, snap, avail):
    """Prototype submission: re-validate everything before recording it in the tab."""
    if not avail.playable or pages.locked(avail):
        return s, _flash("Submissions aren't open for this round.", "warn")
    if s.get("fp") != snap.fingerprint:
        return s, _flash("The round snapshot changed. Please review your portfolio again.", "warn")
    if snap.config_version != DEFAULT_CONFIG.version:
        return s, _flash("The round uses a different configuration.", "warn")
    chosen = service.outcomes_for(snap, s["selections"])
    try:
        validate_portfolio(chosen, snap.snapshot_at, DEFAULT_CONFIG, pool=snap.outcomes)
    except ValueError as e:
        return s, _flash(f"Your portfolio is not valid: {e}", "warn")
    mk, md = service.evaluate(snap, s["selections"])
    s["submitted"] = {
        "at": service.now().astimezone(UTC).isoformat(),
        "fp": snap.fingerprint,
        "round_id": snap.round_id,
        "mode": "demo" if snap.is_demo else "live",
        "selections": list(s["selections"]),
        "config": snap.config_version,
        "p_recover_market": mk.p_recover,
        "p_recover_model": md.p_recover,
        "expected_market": mk.expected_gross,
    }
    return s, _flash(
        "Demonstration submission confirmed in this browser tab. It is not a competition entry.",
        "ok",
    )


# ------------------------------------------------------------- registration
def register(app, data, service: ChallengeService) -> None:
    local = data.local

    @app.callback(
        Output("screener-root", "style"),
        Output("ch-root", "children"),
        Output("site-nav-links", "children"),
        Output("ch-rendered", "data"),
        Input("url", "pathname"),
        State("ch-session", "data"),
        State("ch-explore", "data"),
    )
    def route(path, state, explore):
        path = (path or "/").rstrip("/") or "/"
        show = {"display": "block"} if path == "/" else {"display": "none"}
        if path == "/challenge":
            return (
                show,
                pages.challenge_shell(service, state, explore, local),
                nav_links(path),
                pages.stage_signature(service, state),
            )
        if path == "/challenge/me":
            return show, pages.my_challenge(service, state, local), nav_links(path), None
        if path == "/leaderboards":
            return show, pages.leaderboards(), nav_links(path), None
        if path == "/":
            return show, None, nav_links(path), None
        return (
            show,
            html.Div(
                [
                    html.H1("Page not found", className="ch-h1"),
                    dcc.Link("Back to the Screener", href="/"),
                ],
                className="ch-page",
            ),
            nav_links(path),
            None,
        )

    @app.callback(
        Output("ch-session", "data"),
        Output("ch-flash", "data"),
        Input({"t": "pick", "k": ALL}, "n_clicks"),
        Input({"t": "remove", "k": ALL}, "n_clicks"),
        Input({"t": "nav", "to": ALL, "i": ALL}, "n_clicks"),
        Input({"t": "mode", "m": ALL}, "n_clicks"),
        Input(c.T("clear", ALL), "n_clicks"),
        Input(c.T("submit", ALL), "n_clicks"),
        State("ch-session", "data"),
        prevent_initial_call=True,
    )
    def reduce(_p, _r, _n, _m, _c, _s, state):
        trig = ctx.triggered_id
        if not trig or not ctx.triggered or not ctx.triggered[0].get("value"):
            return no_update, no_update  # a component was (re)rendered, not clicked
        t = trig["t"]
        arg = trig.get("k") or trig.get("to") or trig.get("m")
        new, flash = apply_action(service, state, t, arg)
        return new, flash if flash is not None else no_update

    @app.callback(
        Output({"t": "flash", "i": ALL}, "children"),
        Input("ch-flash", "data"),
        State({"t": "flash", "i": ALL}, "id"),
    )
    def show_flash(flash, ids):
        if not flash:
            return [None] * len(ids)
        return [
            html.Div(
                flash["text"], className=f"ch-flash {flash.get('kind', 'info')}", role="status"
            )
        ] * len(ids)

    @app.callback(
        Output({"t": "stage", "i": ALL}, "children"),
        Output({"t": "stepper", "i": ALL}, "children"),
        Output("ch-rendered", "data", allow_duplicate=True),
        Input("ch-session", "data"),
        State({"t": "stage", "i": ALL}, "id"),
        State("ch-rendered", "data"),
        State("ch-explore", "data"),
        prevent_initial_call=True,
    )
    def refresh_stage(state, ids, rendered, explore):
        if not ids:
            return [], [], no_update
        sig = pages.stage_signature(service, state)
        step = [pages.stepper(service, state)] * len(ids)
        if sig == rendered:
            return [no_update] * len(ids), step, no_update
        return [pages.stage_body(service, state, explore, local)] * len(ids), step, sig

    @app.callback(
        Output({"t": "fixtures", "i": ALL}, "children"),
        Output({"t": "fx-count", "i": ALL}, "children"),
        Output({"t": "tracker", "i": ALL}, "children"),
        Input("ch-session", "data"),
        Input(c.T("f-league", ALL), "value"),
        Input(c.T("f-date", ALL), "value"),
        Input(c.T("f-market", ALL), "value"),
        Input(c.T("f-bucket", ALL), "value"),
        Input(c.T("f-search", ALL), "value"),
        Input("ch-fxpage", "data"),
        State({"t": "fixtures", "i": ALL}, "id"),
    )
    def refresh_builder(state, league, date, market, bucket, search, page, ids):
        if not ids:
            return [], [], []
        state = pages.normal_state(state)
        mode, snap, avail, sels = pages.current(service, state)
        if snap is None:
            return [no_update] * len(ids), [no_update] * len(ids), [no_update] * len(ids)

        def first(v):
            return v[0] if v else None

        filters = {
            "league": first(league),
            "date": first(date),
            "market": first(market),
            "bucket": first(bucket),
            "search": first(search),
        }
        cards, count = pages.fixture_list(
            service, snap, sels, filters, local, pages.locked(avail), page or 1
        )
        trk = pages.tracker_view(service, snap, sels, pages.locked(avail))
        return [cards] * len(ids), [count] * len(ids), [trk] * len(ids)

    @app.callback(
        Output("ch-fxpage", "data"),
        Input({"t": "fxpg", "d": ALL}, "n_clicks"),
        Input(c.T("f-league", ALL), "value"),
        Input(c.T("f-date", ALL), "value"),
        Input(c.T("f-market", ALL), "value"),
        Input(c.T("f-bucket", ALL), "value"),
        Input(c.T("f-search", ALL), "value"),
        State("ch-fxpage", "data"),
        prevent_initial_call=True,
    )
    def page_nav(_clicks, *rest):
        page = rest[-1] or 1
        trig = ctx.triggered_id
        if isinstance(trig, dict) and trig.get("t") == "fxpg":
            if not ctx.triggered[0].get("value"):
                return no_update
            return max(1, page + (1 if trig["d"] == "next" else -1))
        return 1  # a filter changed: back to the first page

    @app.callback(
        Output({"t": "analysis", "i": ALL}, "children"),
        Output({"t": "chart", "i": ALL}, "figure"),
        Output({"t": "thr-out", "i": ALL}, "children"),
        Input(c.T("source", ALL), "value"),
        Input(c.T("chart-mode", ALL), "value"),
        Input(c.T("chart-range", ALL), "value"),
        Input(c.T("thr", ALL), "value"),
        State("ch-session", "data"),
        prevent_initial_call=True,
    )
    def refresh_analysis(source, mode_, rng, thr, state):
        if not source:
            return [], [], []
        state = pages.normal_state(state)
        _, snap, _, sels = pages.current(service, state)
        evs = service.evaluate(snap, sels) if snap is not None else None
        if evs is None:
            return [no_update], [no_update], [no_update]
        ev = evs[0] if source[0] == "market" else evs[1]
        x_max = (
            focus_range(evs[0])
            if (rng or ["focus"])[0] == "focus"
            else float(evs[0].max_gross) * 1.05
        )
        t = float(thr[0]) if thr and thr[0] is not None else None
        fig = (
            exact_figure(ev, x_max)
            if (mode_ or ["at_least"])[0] == "exact"
            else at_least_figure(ev, x_max, t)
        )
        return (
            [pages.analysis_body(ev, snap)],
            [fig],
            [pages.threshold_text(ev, t if t is not None else 100)],
        )

    @app.callback(
        Output({"t": "edu-out", "i": ALL}, "children"),
        Output("ch-explore", "data"),
        Output({"t": "edu", "b": ALL}, "value"),
        Input({"t": "edu", "b": ALL}, "value"),
        Input(c.T("edu-reset", ALL), "n_clicks"),
        State({"t": "edu", "b": ALL}, "id"),
    )
    def explore(values, _reset, ids):
        if not ids:
            return [], no_update, []
        codes = [i["b"] for i in ids]
        trig = ctx.triggered_id
        if isinstance(trig, dict) and trig.get("t") == "edu-reset":
            vals = dict(pages.DEFAULT_ILLUSTRATION_PCT)
        else:
            vals = {
                k: (v if v is not None else pages.DEFAULT_ILLUSTRATION_PCT[k])
                for k, v in zip(codes, values, strict=True)
            }
        ill = illustrate({k: v / 100 for k, v in vals.items()})
        out = c.explorer_output(ill)
        return [out] * len(ids_out(ctx)), vals, [vals[k] for k in codes]

    def ids_out(cx):
        spec = cx.outputs_list[0]
        return spec if isinstance(spec, list) else [spec]

    @app.callback(
        Output({"t": "lb-body", "i": ALL}, "children"),
        Output({"t": "lb-round-wrap", "i": ALL}, "style"),
        Input(c.T("lb-tab", ALL), "value"),
        Input(c.T("lb-round", ALL), "value"),
        prevent_initial_call=True,
    )
    def leaderboard(tab, rnd):
        if not tab:
            return [], []
        t = tab[0]
        style = {"display": "none"} if t == "championship" else {}
        return [pages.leaderboard_body(t, rnd[0] if rnd else None)], [style]


__all__ = ["apply_action", "key_str", "Decimal"]
