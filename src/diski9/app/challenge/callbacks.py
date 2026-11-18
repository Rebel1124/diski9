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

from diski9.challenge import analysis as pa
from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.structured import SelectionBlock, selection_blocks, validate_portfolio

from . import charts, integration, pages
from . import components as c
from .service import ChallengeService, key_str, parse_key

NAV = (
    ("/", "Screener"),
    ("/challenge", "Weekly Challenge"),
    ("/challenge/me", "My Challenge"),
    ("/leaderboards", "Leaderboards"),
)


# Builder and Match Lab buttons share one reducer and the same engine validation.
ACTION_OF = {"labpick": "pick", "labremove": "remove", "labreplace": "ask_replace",
             "confirmreplace": "replace", "cancelflash": "cancel"}  # fmt: skip


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
        if arg not in {key for key, _ in pages.STAGES}:
            return s, None
        if arg == "review" and service.evaluate(snap, s["selections"]) is None:
            return s, _flash("Complete all nine predictions first.", "warn")
        if arg == "build" and not avail.playable:
            return s, _flash(avail.message, "warn")
        s["stage"] = arg
        return s, None
    if snap is None:
        return s, _flash("No round is available.", "warn")
    if action in ("pick", "remove", "clear", "replace", "ask_replace") and pages.locked(avail):
        return s, _flash("This round is locked; predictions can't change.", "warn")
    if action == "clear":
        s["selections"] = []
        return s, _flash("Portfolio cleared.")
    if action == "remove":
        s["selections"] = [k for k in s["selections"] if k != arg]
        return s, None
    if action in ("ask_replace", "replace"):
        return replace_selection(service, s, snap, arg, confirm=action == "replace")
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


def replace_selection(service, s, snap, arg, confirm: bool):
    """Explicit replacement of the pick on the same match (asked, then confirmed). The
    new outcome is validated by the engine with the old pick removed; on failure the
    draft is unchanged."""
    new = snap.outcome(parse_key(arg))
    if new is None:
        return s, _flash("That outcome is not on this round's sheet.", "warn")
    old = next((k for k in s["selections"] if parse_key(k)[0] == new.key[0]), None)
    if old is None:
        return apply_action(service, s, "pick", arg)
    rest = [k for k in s["selections"] if k != old]
    block = selection_blocks(service.outcomes_for(snap, rest), snap.outcomes, snap.snapshot_at,
                             DEFAULT_CONFIG).get(new.key)  # fmt: skip
    if block is not None:
        return s, _flash("That replacement isn't possible: "
                         + {SelectionBlock.INELIGIBLE: "the outcome isn't eligible.",
                            SelectionBlock.BUCKET_FULL: "its bucket is already full.",
                            SelectionBlock.WOULD_BLOCK_COMPLETION: "the portfolio could no longer "
                            "be completed."}.get(block, "it isn't allowed."), "warn")  # fmt: skip
    old_o = snap.outcome(parse_key(old))
    if not confirm:
        return s, {"text": f"Replace {c.outcome_text(old_o)} with {c.outcome_text(new)} for this "
                   "match?", "kind": "confirm", "replace": arg}  # fmt: skip
    s["selections"] = [*rest, arg]
    return s, _flash(f"Replaced {c.outcome_text(old_o)} with {c.outcome_text(new)}.", "ok")


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

    def your_view(state, lab_store):
        _, snap, _, _ = pages.current(service, pages.normal_state(state))
        return integration.personal_probabilities(data, snap, lab_store)

    @app.callback(
        Output("screener-root", "style"),
        Output("ch-root", "children"),
        Output("site-nav-links", "children"),
        Output("ch-rendered", "data"),
        Input("url", "pathname"),
        State("ch-session", "data"),
        State("ch-prefs", "data"),
        State("lab-store", "data"),
    )
    def route(path, state, explore, lab_store):
        path = (path or "/").rstrip("/") or "/"
        show = {"display": "block"} if path == "/" else {"display": "none"}
        if path == "/challenge":
            return (
                show,
                pages.challenge_shell(service, state, explore, local, your_view(state, lab_store)),
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
        Input({"t": "labpick", "k": ALL}, "n_clicks"),
        Input({"t": "labremove", "k": ALL}, "n_clicks"),
        Input({"t": "labreplace", "k": ALL}, "n_clicks"),
        Input({"t": "confirmreplace", "k": ALL}, "n_clicks"),
        Input({"t": "cancelflash", "i": ALL}, "n_clicks"),
        Input({"t": "nav", "to": ALL, "i": ALL}, "n_clicks"),
        Input({"t": "mode", "m": ALL}, "n_clicks"),
        Input(c.T("clear", ALL), "n_clicks"),
        Input(c.T("submit", ALL), "n_clicks"),
        State("ch-session", "data"),
        prevent_initial_call=True,
    )
    def reduce(*args):
        state = args[-1]
        trig = ctx.triggered_id
        if not trig or not ctx.triggered or not ctx.triggered[0].get("value"):
            return no_update, no_update  # a component was (re)rendered, not clicked
        t = ACTION_OF.get(trig["t"], trig["t"])
        if t == "cancel":
            return no_update, {"text": ""}
        arg = trig.get("k") or trig.get("to") or trig.get("m")
        new, flash = apply_action(service, state, t, arg)
        return new, flash if flash is not None else no_update

    @app.callback(
        Output({"t": "flash", "i": ALL}, "children"),
        Input("ch-flash", "data"),
        State({"t": "flash", "i": ALL}, "id"),
    )
    def show_flash(flash, ids):
        if not flash or not flash.get("text"):
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
        State("ch-prefs", "data"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def refresh_stage(state, ids, rendered, explore, lab_store):
        if not ids:
            return [], [], no_update
        sig = pages.stage_signature(service, state)
        step = [pages.stepper(service, state)] * len(ids)
        if sig == rendered:
            return [no_update] * len(ids), step, no_update
        body = pages.stage_body(service, state, explore, local, your_view(state, lab_store))
        return [body] * len(ids), step, sig

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
        Input(c.T("f-avail", ALL), "value"),
        Input("ch-fxpage", "data"),
        Input("ch-prefs", "data"),
        Input("lab-store", "data"),
        State({"t": "fixtures", "i": ALL}, "id"),
    )
    def refresh_builder(
        state, league, date, market, bucket, search, avail_f, page, prefs, lab_store, ids
    ):
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
            "available": bool(first(avail_f)),
        }
        cards, count = pages.fixture_list(
            service,
            snap,
            sels,
            filters,
            local,
            pages.locked(avail),
            page or 1,
            your_view(state, lab_store),
        )
        trk = pages.tracker_view(
            service, snap, sels, pages.locked(avail), prefs, your_view(state, lab_store)
        )
        return [cards] * len(ids), [count] * len(ids), [trk] * len(ids)

    @app.callback(
        Output("ch-fxpage", "data"),
        Input({"t": "fxpg", "d": ALL}, "n_clicks"),
        Input(c.T("f-league", ALL), "value"),
        Input(c.T("f-date", ALL), "value"),
        Input(c.T("f-market", ALL), "value"),
        Input(c.T("f-bucket", ALL), "value"),
        Input(c.T("f-search", ALL), "value"),
        Input(c.T("f-avail", ALL), "value"),
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
        Output("ch-prefs", "data"),
        Input(c.T("source", ALL), "value"),
        Input(c.T("view", ALL), "value"),
        State("ch-prefs", "data"),
        prevent_initial_call=True,
    )
    def set_prefs(source, view, prefs):
        prefs = dict(prefs or {})
        new = dict(prefs)
        if source and source[0] is not None:
            new["source"] = source[0]
        if view and view[0] is not None:
            new["view"] = view[0]
        return no_update if new == prefs else new

    @app.callback(
        Output({"t": "analysis-view", "i": ALL}, "children"),
        Output({"t": "analysis-view", "i": ALL}, "style"),
        Output({"t": "matches-view", "i": ALL}, "style"),
        Input("ch-session", "data"),
        Input("ch-prefs", "data"),
        Input("lab-store", "data"),
        State({"t": "analysis-view", "i": ALL}, "id"),
    )
    def refresh_analysis(state, prefs, lab_store, ids):
        if not ids:
            return [], [], []
        n = len(ids)
        if (prefs or {}).get("view", "matches") != "analysis":
            return [None] * n, [{"display": "none"}] * n, [{}] * n
        state = pages.normal_state(state)
        _, snap, _, sels = pages.current(service, state)
        if snap is None:
            return [no_update] * n, [{}] * n, [{"display": "none"}] * n
        body = pages.analysis_panel(service, snap, sels, prefs, your_view(state, lab_store))
        return [body] * n, [{}] * n, [{"display": "none"}] * n

    @app.callback(
        Output({"t": "k-detail", "i": ALL}, "children"),
        Output({"t": "k-hist", "i": ALL}, "figure"),
        Input(c.T("k-select", ALL), "value"),
        State("ch-session", "data"),
        State("ch-prefs", "data"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def show_k(k, state, prefs, lab_store):
        if not k or k[0] is None:
            return [], []
        state = pages.normal_state(state)
        _, snap, _, sels = pages.current(service, state)
        port = service.portfolio(snap, sels) if snap is not None else None
        if port is None:
            return [no_update], [no_update]
        prob = pa.probability_for(
            (prefs or {}).get("source", "market"), your_view(state, lab_store)
        )
        cc = pa.correct_count_analysis(port, prob)
        return [pages.k_detail(cc, int(k[0]))], [charts.correct_histogram(cc, int(k[0]))]

    @app.callback(
        Output(c.T("k-select", ALL), "value"),
        Input(c.T("k-hist", ALL), "clickData"),
        prevent_initial_call=True,
    )
    def click_k(clicks):
        if not clicks or not clicks[0]:
            return [no_update] * len(clicks)
        return [int(clicks[0]["points"][0]["x"])]

    @app.callback(
        Output("ch-strip", "children"),
        Input("ch-session", "data"),
        Input("url", "pathname"),
    )
    def screener_strip(state, path):
        return integration.progress_strip(service, state) if (path or "/") == "/" else no_update

    @app.callback(
        Output("lab-challenge", "children"),
        Input("selected", "data"),
        Input("ch-session", "data"),
        Input("lab-store", "data"),
        Input("ch-flash", "data"),
    )
    def match_lab_panel(fid, state, lab_store, flash):
        return integration.lab_panel(service, data, state, fid, lab_store, flash)

    @app.callback(
        Output("selected", "data", allow_duplicate=True),
        Output("universe", "value", allow_duplicate=True),
        Input("url", "search"),
        prevent_initial_call=True,
    )
    def open_fixture(search):
        """Builder 'Match Lab' links: /?fixture=<id> selects that match in the Screener."""
        from urllib.parse import parse_qs

        fid = (parse_qs((search or "").lstrip("?")).get("fixture") or [None])[0]
        if not fid or not fid.isdigit():
            return no_update, no_update
        return int(fid), "challenge"

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
