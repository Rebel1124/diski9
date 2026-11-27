"""Guest-work adoption after sign-in (T-15, extended at the 6C.3 checkpoint).

When a guest signs in with work in the tab and chooses **Keep** (``account.js``),
the store ``d9-adopt`` is ``"pending"`` and this panel reviews the work against
the account: what can be saved, what would replace different saved work (one
clear choice for all of it), and what cannot be adopted and why. Nothing is saved
until **Save to my account**; **Discard guest work** removes it from the tab.
Saving is one transaction (``services.adoption``): all or nothing, and never a
confirmation.
"""

from __future__ import annotations

from uuid import UUID

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from . import components as c
from . import lab_persist, persist


def _guest_payload(service, data, state, lab):
    from diski9.app.lab_context import frozen_key

    found = persist.backend_of(service).published()
    view, snap = found if found else (None, None)
    s = dict(state or {})
    draft = None
    if s.get("selections") and s.get("mode") != "demo":
        draft = {
            "round_id": str(view.id) if view and s.get("round_id") == view.code else None,
            "fingerprint": s.get("fp"),
            "selections": list(s["selections"]),
        }
    views = []
    stamps = (lab or {}).get("_ctx") or {}
    for key, st in (lab or {}).items():
        if key.startswith("_") or not isinstance(st, dict):
            continue
        if key.startswith("r:"):
            _, code, fid = key.split(":", 2)
            rid = str(view.id) if view and code == view.code else None
            label = _label(snap, data, fid)
            if rid and key == frozen_key(view.code, fid):
                views.append(
                    {
                        "kind": "round",
                        "round_id": rid,
                        "fixture_id": int(fid),
                        "stamp": stamps.get(key),
                        "state": st,
                        "label": label,
                    }
                )
            else:
                views.append(
                    {
                        "kind": "round",
                        "round_id": None,
                        "fixture_id": int(fid),
                        "stamp": stamps.get(key),
                        "state": st,
                        "label": label,
                    }
                )
        elif key.isdigit():
            views.append(
                {
                    "kind": "live",
                    "fixture_id": int(key),
                    "stamp": stamps.get(key),
                    "state": st,
                    "label": _label(None, data, key),
                }
            )
    return draft, views


def _label(snap, data, fid) -> str:
    try:
        if snap is not None:
            fx = snap.fixture(int(fid))
            return f"{fx.home} v {fx.away}"
    except KeyError:
        pass
    r, _, _ = data.detail(int(fid))
    return f"{r['fixture']['home']} v {r['fixture']['away']}" if r else "a match"


def _live_stamp(data):
    from diski9.app import lab, lab_context

    def stamp(fid: int):
        r, ov, _ = data.detail(fid)
        if r is None:
            return None
        r = lab_context.with_live_starting_point(r, ov)  # State B: market-implied stamp
        if lab.starting_point(r) is None:
            return None
        return lab.model_context(r)

    return stamp


def _describe(item) -> str:
    if item.kind == "draft":
        return item.label or "Weekly Challenge portfolio"
    where = "Weekly Challenge" if item.kind == "round" else "latest available data"
    return f"Your View: {item.label or 'a match'} ({where})"


def panel(plan, message: str | None = None) -> html.Div:
    ready = [i for i in plan.items if i.status == "ready"]
    conflicts = plan.conflicts
    rejected = plan.rejected
    same = [i for i in plan.items if i.status == "same"]
    blocks = [
        html.H2("Save your guest work to your account?", className="ch-modal-title plain"),
        html.P(
            "Nothing is saved until you choose. Saving never confirms an entry, and your "
            "confirmed entry (if any) is not changed.",
            className="muted small",
        ),
    ]
    if message:
        blocks.append(html.Div(message, className="ch-flash warn", role="status"))
    if ready:
        blocks += [html.Strong("Can be saved"),
                   html.Ul([html.Li(_describe(i)) for i in ready], className="small")]  # fmt: skip
    if conflicts:
        blocks += [
            html.Strong("Different from what your account already has"),
            html.Ul([html.Li(_describe(i)) for i in conflicts], className="small"),
            dcc.RadioItems(
                id={"t": "adopt-replace", "i": 0},
                options=[
                    {"label": "Keep my account's saved work", "value": "keep"},
                    {"label": "Replace it with my guest work", "value": "replace"},
                ],
                value="keep",
                className="small adopt-choice",
            ),
        ]
    if same:
        blocks += [html.P(f"{len(same)} item(s) already match your account.",
                          className="muted small")]  # fmt: skip
    if rejected:
        blocks += [
            html.Strong("Cannot be saved"),
            html.Ul([html.Li(f"{_describe(i)}: {i.reason}") for i in rejected], className="small"),
        ]
    if not (ready or conflicts):
        blocks.append(html.P("There is nothing new to save.", className="small"))
    blocks.append(
        html.Div(
            [
                html.Button(
                    "Discard guest work",
                    id={"t": "adopt-discard", "i": 0},
                    n_clicks=0,
                    className="ch-btn ghost",
                ),
                html.Button(
                    [c.icon("check", "ic-sm"), " Save to my account"],
                    id={"t": "adopt-save", "i": 0},
                    n_clicks=0,
                    disabled=not (ready or conflicts),
                    className="ch-btn primary",
                ),
            ],
            className="ch-actions",
        )  # fmt: skip
    )
    return html.Div(
        html.Div(
            blocks,
            className="ch-modal adopt-panel",
            role="dialog",
            **{"aria-modal": "true", "aria-label": "Save guest work"},
        ),  # fmt: skip
        className="ch-modal-backdrop",
    )


def _finish(service, lab) -> tuple:
    """After a decision: the account's work in the tab, guest work gone."""
    fresh_state = persist.hydrate(service, {}, force=True) or {}
    clean_lab = {k: v for k, v in (lab or {}).items() if k in ("_tab",)}
    clean_lab["_owner"] = lab_persist._owner()
    fresh_lab = lab_persist.load_round(service, clean_lab) or clean_lab
    return fresh_state, fresh_lab


def register(app, data, service) -> None:
    from diski9.backend.services import adoption

    @app.callback(
        Output("adopt-root", "children"),
        Input("d9-adopt", "data"),
        Input("url", "pathname"),
        State("ch-session", "data"),
        State("lab-store", "data"),
    )
    def show(adopt, _path, state, lab):
        p = persist.participant(service)
        if adopt != "pending" or p is None:
            return None
        draft, views = _guest_payload(service, data, state, lab)
        plan = adoption.plan_adoption(
            service.backend.engine,
            p,
            guest_draft=draft,
            guest_views=views,
            live_stamp=_live_stamp(data),
        )
        return panel(plan)

    @app.callback(
        Output("d9-adopt", "data"),
        Output("ch-session", "data", allow_duplicate=True),
        Output("lab-store", "data", allow_duplicate=True),
        Output("adopt-root", "children", allow_duplicate=True),
        Output("ch-flash", "data", allow_duplicate=True),
        Input({"t": "adopt-save", "i": ALL}, "n_clicks"),
        Input({"t": "adopt-discard", "i": ALL}, "n_clicks"),
        State({"t": "adopt-replace", "i": ALL}, "value"),
        State("ch-session", "data"),
        State("lab-store", "data"),
        prevent_initial_call=True,
    )
    def decide(save_clicks, discard_clicks, replace, state, lab):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not any(t.get("value") for t in ctx.triggered):
            return (no_update,) * 5
        p = persist.participant(service)
        if p is None:
            return (no_update,) * 5
        if trig["t"] == "adopt-discard":
            fresh_state, fresh_lab = _finish(service, lab)
            return (
                "done",
                fresh_state,
                fresh_lab,
                None,
                {"text": "Your guest work was discarded.", "kind": "info"},
            )
        draft, views = _guest_payload(service, data, state, lab)
        stamp = _live_stamp(data)
        eng = service.backend.engine
        plan = adoption.plan_adoption(
            eng, p, guest_draft=draft, guest_views=views, live_stamp=stamp
        )
        from diski9.backend.services.common import ServiceError

        try:
            res = adoption.adopt(
                eng,
                p,
                plan,
                guest_draft=draft,
                guest_views=views,
                live_stamp=stamp,
                replace_conflicts=(replace or ["keep"])[0] == "replace",
            )
        except ServiceError as exc:
            fresh = adoption.plan_adoption(
                eng, p, guest_draft=draft, guest_views=views, live_stamp=stamp
            )
            return no_update, no_update, no_update, panel(fresh, exc.message), no_update
        fresh_state, fresh_lab = _finish(service, lab)
        parts = [f"Saved {len(res.saved)} item(s) to your account."]
        if res.kept_account:
            parts.append(f"Kept your account's saved work for {len(res.kept_account)} item(s).")
        if res.rejected:
            parts.append(f"{len(res.rejected)} item(s) could not be saved.")
        return "done", fresh_state, fresh_lab, None, {"text": " ".join(parts), "kind": "ok"}


__all__ = ["register", "UUID"]
