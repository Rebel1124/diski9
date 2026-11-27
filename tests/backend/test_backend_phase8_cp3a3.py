"""Phase 8 CP3A-3 on real PostgreSQL (accounts enabled): a Match Lab challenge link
records the real published round and its snapshot fingerprint; a link to another
round fails safely; and once the round is locked, Portfolio Build still shows its
published fixtures read-only, while picks are refused."""

from __future__ import annotations

from datetime import timedelta

import pytest
from auth_helpers import FakeProvider, make_settings
from svc_helpers import principal, publish_dev, wait_until

from diski9.app import ScreenerData, create_app, lab_context
from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import pages
from diski9.backend.auth.web import AuthRuntime
from diski9.backend.services import rounds as svc
from diski9.db import make_engine, upgrade


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture
def store(tmp_path):
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    yield eng
    eng.dispose()


def _app_for(engine, store, round_id):
    app = create_app(ScreenerData(store), auth=AuthRuntime.create(engine, make_settings(),
                                                                   FakeProvider()))  # fmt: skip
    service = app.server.config["DISKI9_CHALLENGE"]
    found = (svc.get_round(engine, round_id), svc.published_snapshot(engine, round_id))
    service.backend.published = lambda: found  # this round, whatever else the database holds
    return app, service, found[1]


def _named(app, name):
    funcs = [v["callback"].__wrapped__ for v in app.callback_map.values() if "callback" in v]
    return next(f for f in funcs if f.__name__ == name)


def test_challenge_link_records_round_and_snapshot(engine, op, store):
    v, _ = publish_dev(engine, op, deadline_in=timedelta(hours=2), seed=8501)
    app, service, snap = _app_for(engine, store, v.id)
    fid = snap.fixtures[0].fixture_id
    # builder links carry the snapshot's own round identifier (lab_href(..., snap.round_id))
    target = _named(app, "open_lab")("/lab", f"?fixture={fid}&ctx=challenge&round={snap.round_id}")
    assert target == {"fixture": fid, "ctx": "challenge", "round": str(snap.round_id),
                      "fp": snap.fingerprint}  # fmt: skip
    other = _named(app, "open_lab")("/lab", f"?fixture={fid}&ctx=challenge&round=elsewhere")
    assert other["fp"] is None
    data = app.server.config["DISKI9_DATA"]
    assert lab_context.resolve_target(service, data, other) == (None, lab_context.CHALLENGE_GONE)


def test_locked_round_is_viewable_read_only(engine, op, store):
    v, _ = publish_dev(engine, op, deadline_in=timedelta(seconds=4), seed=8502)
    wait_until(engine, svc.get_round(engine, v.id).deadline_at)
    svc.lock_round(engine, svc.SYSTEM, v.id)
    app, service, snap = _app_for(engine, store, v.id)
    data = app.server.config["DISKI9_DATA"]
    state = {"mode": "live"}
    mode, snap_now, avail, _ = pages.current(service, state)
    assert pages.locked(avail) and snap_now.fingerprint == snap.fingerprint
    view = pages.stage_body(service, state, None, data.local)
    text = _json(view)
    assert pages.LOCKED_NOTICE in text and "Published fixtures" in text
    picks = _pick_buttons(view)
    assert picks and all(b.get("disabled") is True for b in picks)  # read-only
    assert f"round={snap.round_id}" in text and "ctx=challenge" in text
    key = "|".join(map(str, snap.outcomes[0].key))
    new, flash = cb.apply_action(service, state, "pick", key)
    assert "locked" in flash["text"] and key not in (new.get("selections") or [])


def _pick_buttons(component) -> list[dict]:
    import json

    found = []

    def walk(node):
        if isinstance(node, dict):
            props = node.get("props", {})
            if isinstance(props.get("id"), dict) and props["id"].get("t") == "pick":
                found.append(props)
            for v in props.values():
                walk(v)
        elif isinstance(node, list):
            for n in node:
                walk(n)

    walk(json.loads(_json(component)))
    return found


def _json(component) -> str:
    import json

    import plotly

    return json.dumps(component, cls=plotly.utils.PlotlyJSONEncoder)
