"""Weekly Challenge callbacks: UI state, engine calls and rendering only.

Participant state is the browser-session store ``ch-session`` (``sessionStorage``:
one browser tab, survives a page refresh, never sent to other users, never kept
on the server). The educational explorer keeps its own memory store
``ch-explore`` so it can never touch the portfolio.
"""

from __future__ import annotations

import json
from datetime import UTC
from decimal import Decimal

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from diski9.challenge import analysis as pa
from diski9.challenge.config import ConfigError
from diski9.challenge.structured import SelectionBlock, selection_blocks, validate_portfolio

from ..links import CHALLENGE, CONTEXTS, RESEARCH, lab_href
from . import adopt_ui, charts, home, integration, lab_persist, pages, persist
from . import components as c
from . import state as st
from .service import ChallengeService, key_str, parse_key

# Phase 8 CP3A-1: the five approved tabs. Portfolio Build (the fixture-selection
# entry point) is the home page; the Match Lab moved to /lab. Old /challenge links
# are redirected to / by the server (``legacy_redirect``) and aliased here. The
# learning tab is labelled "Training Ground" and the leaderboards tab "Leaderboard"
# (owner, 27 Nov 2026); their routes stay /learn and /leaderboards.
PORTFOLIO = "/"
LAB = "/lab"
LEGACY_PORTFOLIO = "/challenge"
NAV = (
    (PORTFOLIO, "Portfolio Build"),
    (LAB, "Match Lab"),
    ("/challenge/me", "My Challenge"),
    ("/learn", "Training Ground"),
    ("/leaderboards", "Leaderboard"),
)


def norm_path(path: str | None) -> str:
    """The route a pathname shows: trailing slashes dropped, the legacy Weekly
    Challenge address treated as Portfolio Build."""
    path = (path or "/").rstrip("/") or "/"
    return PORTFOLIO if path == LEGACY_PORTFOLIO else path


def is_lab(path: str | None) -> bool:
    return norm_path(path) == LAB


def legacy_redirect():
    """Flask ``before_request`` hook for full page loads of pre-CP3A addresses:
    ``/challenge`` (the old Weekly Challenge builder) goes to Portfolio Build and
    ``/?fixture=<id>`` (the old Match Lab deep link) goes to ``/lab?fixture=<id>``.
    Query strings are kept; every other request is untouched."""
    from flask import redirect, request

    path = request.path.rstrip("/") or "/"
    query = request.query_string.decode("latin-1")
    if path == LEGACY_PORTFOLIO and request.method in ("GET", "HEAD"):
        return redirect(PORTFOLIO + ("?" + query if query else ""), code=302)
    if path == "/" and request.method in ("GET", "HEAD") and "fixture" in request.args:
        return redirect(LAB + "?" + query, code=302)
    return None


# Builder and Match Lab buttons share one reducer and the same engine validation.
ACTION_OF = {
    "labpick": "pick",
    "labremove": "remove",
    "labreplace": "ask_replace",
    "confirmreplace": "replace",
    "cancelflash": "cancel",
    "modalclose": "close_modal",
    "dismissnotes": "dismiss_notes",
    "askwithdraw": "ask_withdraw",
    "confirmwithdraw": "withdraw",
    "cancelwithdraw": "cancel_withdraw",
    "reload": "reload",
    "retry": "retry",
}
SELECTION_ACTIONS = frozenset({"pick", "remove", "clear", "replace"})


def nav_links(path: str) -> list:
    path = norm_path(path)
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
    if action in ("ask_withdraw", "withdraw", "cancel_withdraw"):
        return withdraw(service, s, snap, avail, action)
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
        block = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, snap.config).get(o.key)
        if block is None:
            s["selections"] = [*s["selections"], arg]
            s["meta"] = {**(s.get("meta") or {}), arg: _meta(o) | {"label": _label(snap, o)}}
            return s, None
        return s, _flash(
            {
                SelectionBlock.INELIGIBLE: "That outcome isn't eligible: its market chance is "
                f"outside {c.eligible_range_text(snap.config)} or its odds don't qualify.",
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
        service.outcomes_for(snap, rest), snap.outcomes, snap.snapshot_at, snap.config
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


def withdraw(service, s, snap, avail, action):
    """Withdraw the confirmed submission for the current round (asked, then
    confirmed). On success the confirmed entry and the working draft are cleared so
    the participant starts fresh; old selections are never resubmitted. Cancelling
    changes nothing. Not possible once the round has locked."""
    if action == "cancel_withdraw":
        s["confirm"] = None
        return s, None
    if pages.locked(avail):  # checked first: a locked round may not be "playable"
        s["confirm"] = None
        return s, _flash(
            "The deadline has passed: a confirmed submission can no longer be withdrawn.", "warn"
        )
    sub = st.submission_for(s, snap)
    if sub is None or not avail.playable:
        s["confirm"] = None
        return s, _flash("There is no confirmed submission to withdraw for this round.", "warn")
    if action == "ask_withdraw":
        s["confirm"] = "withdraw"
        return s, None
    s.update(
        submitted=None,
        selections=[],
        meta={},
        notes=[],
        stage="build",
        modal=None,
        confirm=None,
        withdrawn={
            "round_id": sub["round_id"],
            "mode": sub.get("mode"),
            "at": service.now().astimezone(UTC).isoformat(),
            "confirmed_at": sub.get("at"),
        },
    )
    return s, _flash(
        "Your submission was withdrawn. You can build and submit a new portfolio before the "
        "deadline.",
        "ok",
    )


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
    try:
        cfg = snap.config  # the round's own version; an unknown version is refused
    except ConfigError:
        return s, _flash("The round uses a configuration this app does not support.", "warn")
    chosen = service.outcomes_for(snap, s["selections"])
    try:
        port = validate_portfolio(chosen, snap.snapshot_at, cfg, pool=snap.outcomes)
    except ValueError as e:
        return s, _flash(f"Your portfolio is not valid: {e}", "warn")
    personal = personal or {}
    evs = pa.evaluate_sources(port, personal, pages.implied_for(snap, port.selections))
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
            for code, b in zip(cfg.bucket_codes, port.buckets, strict=True)
            for o in b
        ],
        "estimates": {
            src: {"p_recover": ev.p_recover, "p_zero": ev.p_zero, "expected": ev.expected_gross}
            for src, ev in evs.items()
            if ev is not None  # Diski 9 is unavailable unless all nine have a prediction
        },
        "max_gross": str(evs["market"].max_gross),
        # kept for Phase 6B readers (None when the Diski 9 estimate is unavailable)
        "p_recover_market": evs["market"].p_recover,
        "p_recover_model": evs["model"].p_recover if evs["model"] is not None else None,
        "expected_market": evs["market"].expected_gross,
    }
    s["modal"] = s["submitted"]["at"]
    s["withdrawn"] = None  # a new confirmation supersedes an earlier withdrawal note
    return s, _flash(
        (
            "Your confirmed demonstration portfolio was replaced."
            if replacing
            else "Demonstration submission confirmed."
        )
        + " It is not a competition entry.",
        "ok",
    )


def clicked_id(triggered) -> dict | None:
    """The id of the one button actually clicked in a callback trigger list.

    When buttons are (re)mounted, Dash can fire the callback with *every* input in
    the trigger list (all with n_clicks 0); a tap made at that moment arrives in the
    same batch. Looking only at the first entry swallowed that tap. The clicked
    input is the one with a positive value; anything ambiguous is ignored."""
    hits = [t for t in triggered or [] if t.get("value")]
    if len(hits) != 1:
        return None
    prop = hits[0].get("prop_id", "")
    raw = prop.rsplit(".", 1)[0]
    try:
        return json.loads(raw)
    except ValueError:
        return None


def store_sync(service, state):
    """The reconciled state to write back, or ``no_update``. An empty store is never
    written: a value not yet hydrated from sessionStorage must not overwrite one that
    has been."""
    if not state:
        return no_update
    new = st.reconcile(service, state)
    return no_update if new == state else new


# ------------------------------------------------------------- accounts (6C.3)
def account_action(service, state, action, arg=None, personal=None):
    """The reducer with persistence for signed-in participants in the published
    round (Phase 6C.3): selection changes are saved in the same request; confirm,
    replace and withdraw go to the entry service. Guests keep the browser-tab
    prototype, but cannot confirm an entry in a real round."""
    p = persist.participant(service)
    live = (pages.normal_state(state).get("mode") or None) != "demo"
    if persist.backend_of(service) is None or not live:
        return apply_action(service, state, action, arg, personal)
    if p is None:
        if action == "submit":
            who = persist.signed_in_label(service)
            return pages.sync(service, state), _flash(
                "Sign in to confirm an entry in this round. Your portfolio stays in this tab."
                if who == "guest"
                else "Finish setting up your account to confirm an entry.",
                "warn",
            )
        if action in ("reload", "retry"):
            return pages.sync(service, state), None
        return apply_action(service, state, action, arg, personal)
    # Actions work on the page's own copy and version, so another device's newer save
    # is reported as a conflict instead of being silently pulled in; only a page that
    # has never been hydrated is filled from the account first.
    base = pages.normal_state(state)
    if persist.has_guest_work(state):  # until the keep/discard choice: tab only
        return apply_action(service, state, action, arg, personal)
    if (
        not (base.get("acct") or {}).get("round")
        or (base.get("acct") or {}).get("owner") != persist._owner()
    ):
        base = persist.hydrate(service, state) or base
    if action == "reload":
        return persist.hydrate(service, base, force=True) or base, _flash(
            "Loaded your latest saved portfolio.", "ok"
        )
    if action == "retry":
        new, problem = persist.save_selections(service, base)
        return new, problem or _flash("Saved.", "ok")
    if action == "submit":
        avail = service.availability("live")
        if pages.locked(avail) or not avail.playable:
            return base, _flash("Entries aren't open for this round.", "warn")
        return persist.confirm(service, base)
    if action == "withdraw":
        if pages.locked(service.availability("live")):
            base["confirm"] = None
            return base, _flash(
                "The deadline has passed: a confirmed entry can no longer be withdrawn.", "warn"
            )
        return persist.withdraw(service, base)
    new, flash = apply_action(service, base, action, arg, personal)
    new["acct"] = base.get("acct")
    new["tab"] = base.get("tab")
    if action in SELECTION_ACTIONS and new.get("selections") != base.get("selections"):
        new, problem = persist.save_selections(service, new)
        if problem is not None:
            return new, problem
    return new, flash


# ------------------------------------------------------------- registration
def research_list_shown(service, prefs) -> bool:
    """Research only, as the participant chose it this session or by the status default."""
    if "research" in (prefs or {}):
        return bool(prefs["research"])
    return home.challenge_status(service, lambda dt, *a: "", championship=False).default_research


def register(app, data, service: ChallengeService) -> None:
    local = data.local
    adopt_ui.register(app, data, service)

    def your_view(state, lab_store):
        _, snap, _, _ = pages.current(service, state)
        return integration.personal_probabilities(data, snap, lab_store)

    @app.callback(
        Output("pb-home", "children"),
        Output("ch-root", "children"),
        Output("site-nav-links", "children"),
        Output("ch-rendered", "data"),
        Output("ch-mounted", "data"),
        Input("url", "pathname"),
        State("ch-session", "data"),
        State("ch-prefs", "data"),
        State("lab-store", "data"),
        State("ch-mounted", "data"),
    )
    def route(path, state, explore, lab_store, mounted=None):
        """Page content per route. Which list shows (and the Match Lab on /lab) is
        decided by ``layout_mode``.

        Phase 8 CP3A-3: going to the Match Lab leaves the Portfolio Build builder
        mounted (hidden), and coming back to Portfolio Build keeps it as it was, so the
        competitive list's filters, page, picks and draft are exactly as the
        participant left them. The builder's own callbacks keep it current meanwhile."""
        path = norm_path(path)
        if path == PORTFOLIO:
            if mounted == PORTFOLIO:
                content, sig = no_update, no_update
            else:
                content = pages.challenge_shell(service, state, explore, local,
                                                your_view(state, lab_store))  # fmt: skip
                sig = pages.stage_signature(service, state)
            return home.portfolio_home(service, local, explore), content, nav_links(path), sig, \
                PORTFOLIO  # fmt: skip
        if path == LAB:  # the page beneath stays as it is (hidden)
            return None, no_update, nav_links(path), no_update, no_update
        if path == "/challenge/me":
            return None, pages.my_challenge(service, state, local), nav_links(path), None, path
        if path == "/leaderboards":
            return None, pages.leaderboards(service), nav_links(path), None, path
        if path == "/learn":
            return None, pages.learn_page(), nav_links(path), None, path
        return (
            None,
            html.Div(
                [
                    html.H1("Page not found", className="ch-h1"),
                    dcc.Link("Back to Portfolio Build", href=PORTFOLIO),
                ],
                className="ch-page",
            ),
            nav_links(path),
            None,
            path,
        )

    @app.callback(
        Output("ch-session", "data", allow_duplicate=True),
        Input("url", "pathname"),
        State("ch-session", "data"),
        State("d9-adopt", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def sync_store(_path, state, adopt):
        """Write the reconciled state back to the store when a page loads or the route
        changes, so what is stored is exactly what every page shows. For a signed-in
        participant the working copy is first refreshed from the account (Phase
        6C.3), except while a guest-work decision is pending. An empty store is
        never written for guests: a value that has not been hydrated from
        sessionStorage yet must not overwrite one that has."""
        if persist.participant(service) is not None and adopt != "pending":
            fresh = persist.hydrate(service, state)
            if fresh is not None:
                fresh = st.reconcile(service, fresh)
                return no_update if fresh == state else fresh
        return store_sync(service, state)

    @app.callback(
        Output("lab-store", "data", allow_duplicate=True),
        Input("url", "pathname"),
        State("lab-store", "data"),
        State("d9-adopt", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def sync_round_views(path, lab, adopt):
        """A participant's saved Your View for the published round's frozen context,
        loaded into the tab when a Weekly Challenge page opens (any device)."""
        if adopt == "pending" or norm_path(path) not in (PORTFOLIO, "/challenge/me"):
            return no_update
        fresh = lab_persist.load_round(service, lab)
        return no_update if fresh is None or fresh == lab else fresh

    @app.callback(
        Output("data-context", "children"),
        Input("universe", "value"),
        Input("url", "pathname"),
    )
    def data_context(universe, path):
        """Frozen (Weekly Challenge) versus latest (All Upcoming Fixtures) information,
        with the actual stored times."""
        if norm_path(path) != PORTFOLIO:  # above the research list only (CP3A-3)
            return no_update
        return integration.data_context(service, data, universe)

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
        Input({"t": "askwithdraw", "i": ALL}, "n_clicks"),
        Input({"t": "confirmwithdraw", "i": ALL}, "n_clicks"),
        Input({"t": "cancelwithdraw", "i": ALL}, "n_clicks"),
        Input({"t": "nav", "to": ALL, "i": ALL}, "n_clicks"),
        Input({"t": "mode", "m": ALL}, "n_clicks"),
        Input(c.T("clear", ALL), "n_clicks"),
        Input(c.T("submit", ALL), "n_clicks"),
        Input({"t": "reload", "i": ALL}, "n_clicks"),
        Input({"t": "retry", "i": ALL}, "n_clicks"),
        State("ch-session", "data"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def reduce(*args):
        state, lab_store = args[-2], args[-1]
        trig = clicked_id(ctx.triggered)
        if trig is None:
            return no_update, no_update  # components were (re)rendered, not clicked
        t = ACTION_OF.get(trig["t"], trig["t"])
        if t == "cancel":
            return no_update, {"text": ""}
        arg = trig.get("k") or trig.get("to") or trig.get("m")
        personal = your_view(state, lab_store) if t == "submit" else None
        new, flash = account_action(service, state, t, arg, personal)
        return new, flash if flash is not None else no_update

    @app.callback(
        Output({"t": "flash", "i": ALL}, "children"),
        Input("ch-flash", "data"),
        State({"t": "flash", "i": ALL}, "id"),
    )
    def show_flash(flash, ids):
        if not flash or not flash.get("text"):
            return [None] * len(ids)
        recover = {
            "reload": ("Load latest saved portfolio", "reload"),
            "retry": ("Try again", "retry"),
        }.get(flash.get("recover"))
        out = []
        for ident in ids:
            kids = [flash["text"]]
            if recover:
                kids += [
                    " ",
                    html.Button(
                        recover[0],
                        id={"t": recover[1], "i": ident["i"]},
                        n_clicks=0,
                        className="ch-btn small ghost",
                    ),
                ]
            out.append(
                html.Div(kids, className=f"ch-flash {flash.get('kind', 'info')}", role="status")
            )
        return out

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
        Input(c.T("f-mmp", ALL), "value"),
        Input("ch-fxpage", "data"),
        State({"t": "fixtures", "i": ALL}, "id"),
    )
    def refresh_list(state, league, date, market, bucket, search, avail_f, mmp, page, ids):
        """Re-render the match list only when filters or the page change (or, with
        'Available only', when selections change). A pick or removal updates the
        existing outcome buttons in place (``refresh_buttons``): replacing ~70
        pattern-matched buttons on every click was the main source of latency."""
        if not ids:
            return [], []
        first = lambda v: v[0] if v else None  # noqa: E731
        if ctx.triggered_id == "ch-session" and not first(avail_f):
            return [no_update] * len(ids), [no_update] * len(ids)
        filtered = any(first(v) for v in (league, date, market, bucket, search, avail_f, mmp))
        if not ctx.triggered_id and (page or 1) == 1 and not filtered:
            # the builder has just rendered this exact list: re-rendering it here would
            # replace the outcome buttons and could swallow a tap made meanwhile
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
            "mmp": first(mmp) or 0,
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
        return [html.Div([trk, pages.save_status(service, state)])] * len(ids)

    @app.callback(
        Output("ch-fxpage", "data"),
        Input({"t": "fxpg", "d": ALL}, "n_clicks"),
        Input(c.T("f-league", ALL), "value"),
        Input(c.T("f-date", ALL), "value"),
        Input(c.T("f-market", ALL), "value"),
        Input(c.T("f-bucket", ALL), "value"),
        Input(c.T("f-search", ALL), "value"),
        Input(c.T("f-avail", ALL), "value"),
        Input(c.T("f-mmp", ALL), "value"),
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

    # ------------------------------------------------- Portfolio Build (CP3A-2)
    @app.callback(
        Output("ch-prefs", "data", allow_duplicate=True),
        Input("research-only", "value"),
        State("ch-prefs", "data"),
        prevent_initial_call=True,
    )
    def set_research(value, prefs):
        """Only an explicit change of the Research only toggle is stored (this browser
        session); rendering the toggle never writes, so until the participant chooses,
        the status default applies."""
        new = dict(prefs or {})
        new["research"] = home.RESEARCH_VALUE in (value or [])
        return no_update if new == (prefs or {}) else new

    @app.callback(
        Output("pb-go", "children"),
        Output("pb-mode-note", "children"),
        Input("research-only", "value"),
        State("pb-state", "data"),
    )
    def research_widgets(value, state=None):
        on = home.RESEARCH_VALUE in (value or [])
        return home.action_label(state, on), home.mode_note(on)

    @app.callback(
        Output("screener-root", "style"),
        Output("screener-root", "className"),
        Output("ch-root", "style"),
        Output("universe", "value", allow_duplicate=True),
        Output("lab-root", "style"),
        Input("url", "pathname"),
        Input("ch-prefs", "data"),
        State("universe", "value"),
        prevent_initial_call="initial_duplicate",
    )
    def layout_mode(path, prefs, universe):
        """What shows. /lab: the Match Lab only (CP3A-3). Portfolio Build: the challenge
        builder (Research only OFF) or the research list with latest data (ON). Every
        list stays mounted, so moving between them and the Match Lab never discards
        selections, drafts, filters, pages or adjustments."""
        shown, hidden = {"display": "block"}, {"display": "none"}
        path = norm_path(path)
        if path == LAB:
            return hidden, "", hidden, no_update, shown
        if path != PORTFOLIO:
            return hidden, "", shown, no_update, hidden
        if not research_list_shown(service, prefs):
            return hidden, "", shown, no_update, hidden
        return shown, "on-portfolio", hidden, (no_update if universe == "all" else "all"), hidden

    app.clientside_callback(
        """function(n) {
            if (n) {
                const el = document.getElementById('pb-list');
                if (el) { el.scrollIntoView({behavior: 'smooth', block: 'start'}); }
            }
            return window.dash_clientside.no_update;
        }""",
        Output("pb-list", "className"),
        Input("pb-go", "n_clicks"),
    )

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
        Input(c.T("k-view", ALL), "value"),
        State("ch-session", "data"),
        State("ch-prefs", "data"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def show_k(k, view, state, prefs, lab_store):
        if not k or k[0] is None:
            return [], []
        state = pages.sync(service, state)
        _, snap, _, sels = pages.current(service, state)
        port = service.portfolio(snap, sels) if snap is not None else None
        source = (prefs or {}).get("source", "market")
        if port is None or not pa.available(port, source):
            return [no_update], [no_update]
        implied = pages.implied_for(snap, port.selections) if source == "personal" else None
        prob = pa.probability_for(source, your_view(state, lab_store), implied)
        cc = pa.correct_count_analysis(port, prob)
        v = (view or ["focus"])[0] or "focus"
        return [pages.k_detail(cc, int(k[0]))], [charts.correct_combined(cc, int(k[0]), v)]

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
        Output({"t": "me", "i": ALL}, "children"),
        Input("ch-session", "data"),
        State({"t": "me", "i": ALL}, "id"),
        prevent_initial_call=True,
    )
    def refresh_me(state, ids):
        """My Challenge follows the store (withdrawal, confirmation, restored state)."""
        if not ids:
            return []
        return [pages.my_challenge_body(service, state, local)] * len(ids)

    @app.callback(
        Output("ch-strip", "children"),
        Input("ch-session", "data"),
        Input("url", "pathname"),
        Input("lab-active", "data"),
    )
    def screener_strip(state, path, active=None):
        """The Weekly Challenge strip: in the Match Lab, for a challenge match only."""
        if not is_lab(path) or (active or {}).get("ctx") != CHALLENGE:
            return None
        return integration.progress_strip(service, state)

    @app.callback(
        Output("lab-challenge", "children"),
        Input("lab-active", "data"),
        Input("ch-session", "data"),
        Input("lab-store", "data"),
        Input("ch-flash", "data"),
        Input("url", "pathname"),
    )
    def match_lab_panel(active, state, lab_store, flash, path):
        """The Weekly Challenge selection panel: in the Match Lab, for a match opened
        from the published challenge list only. A research match never shows
        competitive controls (CP3A-3)."""
        if not is_lab(path) or (active or {}).get("ctx") != CHALLENGE:
            return None
        return integration.lab_panel(service, data, state, active["fixture"], lab_store, flash)

    @app.callback(
        Output("lab-request", "data"),
        Input("url", "pathname"),
        Input("url", "search"),
    )
    def open_lab(path, search):
        """What the Match Lab address asks for (Phase 8 CP3A-3), including on a full page
        load: ``/lab?fixture=<id>&ctx=challenge|research[&round=<id>]``. No fixture in
        the address (the tab itself): None, so the last valid match is restored. An
        address without a context (an old link) opens the latest data, never a frozen
        snapshot it did not name."""
        from urllib.parse import parse_qs

        if not is_lab(path):
            return no_update
        q = parse_qs((search or "").lstrip("?"))
        raw = (q.get("fixture") or [None])[0]
        if raw is None:
            return None
        context = (q.get("ctx") or [RESEARCH])[0]
        if not raw.isdigit() or context not in CONTEXTS:
            return {"invalid": True}
        target = {"fixture": int(raw), "ctx": context}
        if context == CHALLENGE:
            rid = (q.get("round") or [None])[0]
            snap = service.snapshot("live")
            target["round"] = rid
            target["fp"] = snap.fingerprint if snap is not None and snap.round_id == rid else None
        return target

    @app.callback(
        Output("url", "pathname"),
        Output("url", "search"),
        Output("lab-market", "value"),
        Input({"type": "row", "index": ALL}, "n_clicks"),
        Input({"type": "fx", "index": ALL}, "n_clicks"),
        State("url", "pathname"),
        State("market", "value"),
        prevent_initial_call=True,
    )
    def open_from_research(_rows, _cards, path, market=None):
        """Selecting a match in the research list opens it in the Match Lab, with the
        latest data (Phase 8 CP3A-3); the list itself stays as it was."""
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not any(t["value"] for t in ctx.triggered):
            raise PreventUpdate  # rows were re-rendered, not clicked
        if norm_path(path) != PORTFOLIO:
            raise PreventUpdate
        query = "?" + lab_href(int(trig["index"]), RESEARCH).split("?", 1)[1]
        return LAB, query, (market or no_update)

    # ------------------------------------------------------------- My Challenge tabs
    @app.callback(
        Output({"t": "me", "i": ALL}, "style"),
        Output({"t": "me-hist", "i": ALL}, "style"),
        Output({"t": "me-hist", "i": ALL}, "children"),
        Output({"t": "me-ach", "i": ALL}, "style"),
        Output({"t": "me-ach", "i": ALL}, "children"),
        Input(c.T("me-tab", ALL), "value"),
        prevent_initial_call=True,
    )
    def my_challenge_tab(tab):
        """Current, History (Stage E) or Achievements (Phase 7). History and
        Achievements are rendered each time they are opened, from the authoritative
        read services, so they are never stale."""
        if not tab:
            raise PreventUpdate  # wildcard outputs: a bare no_update is rejected by Dash
        from . import achievements_ui, history_ui

        hide, show = {"display": "none"}, {}
        if tab[0] == "history":
            return [hide], [show], [history_ui.section(service, local)], [hide], [no_update]
        if tab[0] == "achievements":
            return [hide], [hide], [no_update], [show], [achievements_ui.section(service, local)]
        return [show], [hide], [no_update], [hide], [no_update]

    @app.callback(
        Output({"t": "me-abody", "i": ALL}, "children"),
        Input(c.T("me-astream", ALL), "value"),
        prevent_initial_call=True,
    )
    def my_achievements(stream):
        """Another stream's achievements (streams never mix, D-3)."""
        from . import achievements_ui

        if not stream:
            raise PreventUpdate  # wildcard outputs: a bare no_update is rejected by Dash
        return [achievements_ui.body(service, stream[0])]

    @app.callback(
        Output({"t": "me-hbody", "i": ALL}, "children"),
        Output({"t": "me-hscope", "i": ALL}, "options"),
        Output({"t": "me-hscope", "i": ALL}, "value"),
        Input(c.T("me-hstream", ALL), "value"),
        Input(c.T("me-hscope", ALL), "value"),
        Input({"t": "hist-goto", "i": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def my_history(stream, scope, _goto):
        from . import history_ui

        if not stream or not scope:
            raise PreventUpdate  # wildcard outputs: a bare no_update is rejected by Dash
        trig = ctx.triggered_id or {}
        kind = trig.get("t") if isinstance(trig, dict) else None
        s = stream[0]
        if kind == "hist-goto":
            if not ctx.triggered or not ctx.triggered[0].get("value"):
                raise PreventUpdate  # wildcard outputs: a bare no_update is rejected by Dash
            return ([history_ui.body(service, local, s, scope[0], trig.get("i") or 1)],
                    [no_update] * len(scope), [no_update] * len(scope))  # fmt: skip
        if kind == "me-hstream":
            opts = history_ui.scope_options(service, s)
            return ([history_ui.body(service, local, s, history_ui.ALL, 1)], [opts] * len(scope),
                    [history_ui.ALL] * len(scope))  # fmt: skip
        return ([history_ui.body(service, local, s, scope[0], 1)], [no_update] * len(scope),
                [no_update] * len(scope))  # fmt: skip

    @app.callback(
        Output({"t": "me-hdetail", "i": ALL}, "children"),
        Input({"t": "hist-open", "i": ALL}, "n_clicks"),
        State(c.T("me-hstream", ALL), "value"),
        prevent_initial_call=True,
    )
    def my_history_detail(_clicks, stream):
        """One entry's drill-down, loaded on demand (the 6C.4 results panel)."""
        from . import history_ui

        trig = ctx.triggered_id or {}
        if not isinstance(trig, dict) or not ctx.triggered or not ctx.triggered[0].get("value"):
            return [no_update] * len(ctx.outputs_list)
        s = stream[0] if stream else "beta"
        return [history_ui.detail(service, local, s, trig.get("i"))] * len(ctx.outputs_list)

    @app.callback(
        Output({"t": "lb-body", "i": ALL}, "children"),
        Output({"t": "lb-round-wrap", "i": ALL}, "style"),
        Output({"t": "lb-round", "i": ALL}, "options"),
        Output({"t": "lb-round", "i": ALL}, "value"),
        Input(c.T("lb-tab", ALL), "value"),
        Input(c.T("lb-stream", ALL), "value"),
        Input(c.T("lb-round", ALL), "value"),
        Input({"t": "lbw-goto", "i": ALL}, "n_clicks"),
        Input({"t": "lbc-goto", "i": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def leaderboard(tab, stream, rnd, _gw, _gc):
        """Demonstration leaderboards in prototype mode; otherwise the real ones
        (Stage E): a tab or stream change resets the selector to its default, a
        selector change shows page 1, a pager button shows its page."""
        if not tab:
            return [], [], [], []
        t = tab[0]
        n_round = len(rnd)
        if persist.backend_of(service) is None:
            style = {"display": "none"} if t == "championship" else {}
            return ([pages.leaderboard_body(t, rnd[0] if rnd else None)], [style],
                    [no_update] * n_round, [no_update] * n_round)  # fmt: skip
        from . import leaderboards_ui as lbu

        trig = ctx.triggered_id or {}
        kind = trig.get("t") if isinstance(trig, dict) else None
        s = stream[0] if stream else "beta"
        if kind in ("lbw-goto", "lbc-goto"):
            if not ctx.triggered or not ctx.triggered[0].get("value"):
                raise PreventUpdate  # wildcard outputs: a bare no_update is rejected by Dash
            page_no = lbu.goto_page(trig.get("i"))
            value = rnd[0] if rnd else None
            return ([lbu.body(service, t, s, value, page_no)], [],
                    [no_update] * n_round, [no_update] * n_round)  # fmt: skip
        if kind == "lb-round":
            value = rnd[0] if rnd else None
            return ([lbu.body(service, t, s, value, 1)], [], [no_update] * n_round,
                    [no_update] * n_round)  # fmt: skip
        options, value = lbu.selector_options(service, t, s)
        return ([lbu.body(service, t, s, value, 1)], [], [options] * n_round,
                [value] * n_round)  # fmt: skip


__all__ = ["apply_action", "key_str", "Decimal"]
