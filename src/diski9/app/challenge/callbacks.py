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
from . import state as st
from .service import ChallengeService, key_str, parse_key

NAV = (
    ("/", "Screener"),
    ("/challenge", "Weekly Challenge"),
    ("/challenge/me", "My Challenge"),
    ("/leaderboards", "Leaderboards"),
)


# Builder and Match Lab buttons share one reducer and the same engine validation.
ACTION_OF = {
    "labpick": "pick",
    "labremove": "remove",
    "labreplace": "ask_replace",
    "confirmreplace": "replace",
    "cancelflash": "cancel",
    "modalclose": "close_modal",
    "dismissnotes": "dismiss_notes",
}


def nav_links(path: str) -> list:
    path = path or "/"
    return [
        dcc.Link(label, href=href, className="nav-link" + (" on" if path == href else ""))
        for href, label in NAV
    ]


def _flash(text: str, kind: str = "info") -> dict:
    return {"text": text, "kind": kind}


# ------------------------------------------------------------- the reducer
def _meta(o) -> dict:
    """What a draft selection looked like when it was chosen (for revalidation)."""
    return {"odds": str(o.reference_odds), "p": repr(o.market_probability)}


migrate_draft = st.migrate_draft  # kept importable from here (Phase 6B.1 tests)


def apply_action(
    service: ChallengeService, state: dict | None, action: str, arg=None, personal=None
):
    """Pure state transition: (new state, flash or None). Every rule check is an
    engine call; this function only decides what the UI does with the answer.

    The stored state is reconciled first, exactly as every page render does, and the
    action is then applied to the reconciled state (a click is never swallowed by a
    snapshot change). Predictions taken out by the revalidation are reported."""
    before = len(pages.normal_state(state)["notes"])
    s, flash = _apply(service, state, action, arg, personal)
    review = len(s.get("notes") or []) - before
    if flash is None and review > 0:
        flash = _flash(
            f"The round snapshot changed. {review} prediction(s) need your review.", "warn"
        )
    return s, flash


def _apply(service, state, action, arg, personal):
    s = st.reconcile(service, state)  # the same reconciliation every page render uses
    mode = pages.effective_mode(service, s)
    snap = service.snapshot(mode) if mode else None
    avail = service.availability(mode or "live")
    if action == "mode":
        return st.switch_mode(service, s, arg), None
    if action == "close_modal":
        s["modal"] = None
        return s, None
    if action == "dismiss_notes":
        s["notes"] = []
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
            s["meta"] = {**(s.get("meta") or {}), arg: _meta(o) | {"label": _label(snap, o)}}
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
        return submit(service, s, snap, avail, personal)
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
    block = selection_blocks(
        service.outcomes_for(snap, rest), snap.outcomes, snap.snapshot_at, DEFAULT_CONFIG
    ).get(new.key)
    if block is not None:
        return s, _flash(
            "That replacement isn't possible: "
            + {
                SelectionBlock.INELIGIBLE: "the outcome isn't eligible.",
                SelectionBlock.BUCKET_FULL: "its bucket is already full.",
                SelectionBlock.WOULD_BLOCK_COMPLETION: "the portfolio could no longer "
                "be completed.",
            }.get(block, "it isn't allowed."),
            "warn",
        )
    old_o = snap.outcome(parse_key(old))
    if not confirm:
        return s, {
            "text": f"Replace {c.outcome_text(old_o)} with {c.outcome_text(new)} for this match?",
            "kind": "confirm",
            "replace": arg,
        }
    s["selections"] = [*rest, arg]
    s["meta"] = {**(s.get("meta") or {}), arg: _meta(new) | {"label": _label(snap, new)}}
    return s, _flash(f"Replaced {c.outcome_text(old_o)} with {c.outcome_text(new)}.", "ok")


def _label(snap, o) -> str:
    fx = snap.fixture(o.fixture_id)
    return f"{fx.home} v {fx.away}: {c.outcome_text(o)}"


def submit(service, s, snap, avail, personal=None):
    """Prototype submission. Everything is re-validated first; only on success is the
    frozen record written (replacing an earlier confirmation explicitly). On any
    failure the existing confirmed submission is kept unchanged."""
    if not avail.playable or pages.locked(avail):
        return s, _flash("Submissions aren't open for this round.", "warn")
    if s.get("fp") != snap.fingerprint:
        return s, _flash("The round snapshot changed. Please review your portfolio again.", "warn")
    if snap.config_version != DEFAULT_CONFIG.version:
        return s, _flash("The round uses a different configuration.", "warn")
    chosen = service.outcomes_for(snap, s["selections"])
    try:
        port = validate_portfolio(chosen, snap.snapshot_at, DEFAULT_CONFIG, pool=snap.outcomes)
    except ValueError as e:
        return s, _flash(f"Your portfolio is not valid: {e}", "warn")
    personal = personal or {}
    evs = pa.evaluate_sources(port, personal)
    replacing = s.get("submitted") is not None
    s["submitted"] = {
        "at": service.now().astimezone(UTC).isoformat(),
        "round_id": snap.round_id,
        "fp": snap.fingerprint,
        "snapshot_at": snap.snapshot_at.isoformat(),
        "mode": "demo" if snap.is_demo else "live",
        "config": snap.config_version,
        "selections": list(s["selections"]),
        "picks": [
            {
                "key": key_str(o.key),
                "bucket": code,
                "match": f"{snap.fixture(o.fixture_id).home} v {snap.fixture(o.fixture_id).away}",
                "outcome": c.outcome_text(o),
                "odds": str(o.reference_odds),
                "market": o.market_probability,
                "model": o.model_probability,
                "personal": personal.get(o.key),
                "personal_adjusted": o.key in personal,
            }
            for code, b in zip(DEFAULT_CONFIG.bucket_codes, port.buckets, strict=True)
            for o in b
        ],
        "estimates": {
            src: {"p_recover": ev.p_recover, "p_zero": ev.p_zero, "expected": ev.expected_gross}
            for src, ev in evs.items()
        },
        "max_gross": str(evs["market"].max_gross),
        # kept for Phase 6B readers
        "p_recover_market": evs["market"].p_recover,
        "p_recover_model": evs["model"].p_recover,
        "expected_market": evs["market"].expected_gross,
    }
    s["modal"] = s["submitted"]["at"]
    return s, _flash(
        (
            "Your confirmed demonstration portfolio was replaced."
            if replacing
            else "Demonstration submission confirmed."
        )
        + " It is not a competition entry.",
        "ok",
    )


def store_sync(service, state):
    """The reconciled state to write back, or ``no_update``. An empty store is never
    written: a value not yet hydrated from sessionStorage must not overwrite one that
    has been."""
    if not state:
        return no_update
    new = st.reconcile(service, state)
    return no_update if new == state else new


# ------------------------------------------------------------- registration
def register(app, data, service: ChallengeService) -> None:
    local = data.local

    def your_view(state, lab_store):
        _, snap, _, _ = pages.current(service, state)
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
        Output("ch-session", "data", allow_duplicate=True),
        Input("ch-session", "data"),
        Input("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )
    def sync_store(state, _path):
        """Write the reconciled state back to the store as soon as the page loads
        (and whenever the snapshot moved on), so what is stored is exactly what every
        page shows. An empty store is never written: a value that has not been
        hydrated from sessionStorage yet must not overwrite one that has."""
        return store_sync(service, state)

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
        Input({"t": "modalclose", "i": ALL}, "n_clicks"),
        Input({"t": "dismissnotes", "i": ALL}, "n_clicks"),
        Input({"t": "nav", "to": ALL, "i": ALL}, "n_clicks"),
        Input({"t": "mode", "m": ALL}, "n_clicks"),
        Input(c.T("clear", ALL), "n_clicks"),
        Input(c.T("submit", ALL), "n_clicks"),
        State("ch-session", "data"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def reduce(*args):
        state, lab_store = args[-2], args[-1]
        trig = ctx.triggered_id
        if not trig or not ctx.triggered or not ctx.triggered[0].get("value"):
            return no_update, no_update  # a component was (re)rendered, not clicked
        t = ACTION_OF.get(trig["t"], trig["t"])
        if t == "cancel":
            return no_update, {"text": ""}
        arg = trig.get("k") or trig.get("to") or trig.get("m")
        personal = your_view(state, lab_store) if t == "submit" else None
        new, flash = apply_action(service, state, t, arg, personal)
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
        Input("ch-session", "data"),
        Input(c.T("f-league", ALL), "value"),
        Input(c.T("f-date", ALL), "value"),
        Input(c.T("f-market", ALL), "value"),
        Input(c.T("f-bucket", ALL), "value"),
        Input(c.T("f-search", ALL), "value"),
        Input(c.T("f-avail", ALL), "value"),
        Input("ch-fxpage", "data"),
        State({"t": "fixtures", "i": ALL}, "id"),
    )
    def refresh_list(state, league, date, market, bucket, search, avail_f, page, ids):
        """Re-render the match list only when filters or the page change (or, with
        'Available only', when selections change). A pick or removal updates the
        existing outcome buttons in place (``refresh_buttons``): replacing ~70
        pattern-matched buttons on every click was the main source of latency."""
        if not ids:
            return [], []
        first = lambda v: v[0] if v else None  # noqa: E731
        if ctx.triggered_id == "ch-session" and not first(avail_f):
            return [no_update] * len(ids), [no_update] * len(ids)
        state = pages.sync(service, state)
        mode, snap, avail, sels = pages.current(service, state)
        if snap is None:
            return [no_update] * len(ids), [no_update] * len(ids)
        filters = {
            "league": first(league),
            "date": first(date),
            "market": first(market),
            "bucket": first(bucket),
            "search": first(search),
            "available": bool(first(avail_f)),
        }
        cards, count = pages.fixture_list(
            service, snap, sels, filters, local, pages.locked(avail), page or 1
        )
        return [cards] * len(ids), [count] * len(ids)

    @app.callback(
        Output({"t": "pick", "k": ALL}, "className"),
        Output({"t": "pick", "k": ALL}, "disabled"),
        Output({"t": "pick", "k": ALL}, "title"),
        Input("ch-session", "data"),
        Input("lab-store", "data"),
        State({"t": "pick", "k": ALL}, "id"),
        prevent_initial_call=True,
    )
    def refresh_buttons(state, lab_store, ids):
        """Selection state, disabled reasons and Your View titles for the visible
        outcome buttons, from the same engine call and component as a full render."""
        if not ids:
            return [], [], []
        state = pages.sync(service, state)
        _, snap, avail, sels = pages.current(service, state)
        if snap is None:
            n = len(ids)
            return [no_update] * n, [no_update] * n, [no_update] * n
        states = pages.outcome_states(
            service,
            snap,
            sels,
            [parse_key(i["k"]) for i in ids],
            pages.locked(avail),
            your_view(state, lab_store),
        )
        return [s[0] for s in states], [s[1] for s in states], [s[2] for s in states]

    @app.callback(
        Output({"t": "tracker", "i": ALL}, "children"),
        Input("ch-session", "data"),
        Input("ch-prefs", "data"),
        Input("lab-store", "data"),
        State({"t": "tracker", "i": ALL}, "id"),
    )
    def refresh_tracker(state, prefs, lab_store, ids):
        if not ids:
            return []
        state = pages.sync(service, state)
        mode, snap, avail, sels = pages.current(service, state)
        if snap is None:
            return [no_update] * len(ids)
        trk = pages.tracker_view(
            service, snap, sels, pages.locked(avail), prefs, your_view(state, lab_store)
        )
        return [trk] * len(ids)

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
        state = pages.sync(service, state)
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
        state = pages.sync(service, state)
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
