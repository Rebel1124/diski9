"""Phase 8 CP3A-4 on real PostgreSQL: for a signed-in participant, the frozen and the
latest-data Your View of the same challenge match are separate account rows (round
context versus live context); saving one never changes the other, and each is loaded
back into its own browser key. A locked round keeps both views readable while
selection changes are refused."""

from __future__ import annotations

from datetime import timedelta

import pytest
from svc_helpers import principal, publish_dev, wait_until
from test_app_persistence import as_user, make_service  # noqa: F401  (fixture)

from diski9.app import lab, lab_context
from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import lab_persist
from diski9.backend.services import rounds as rsvc


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _detail(fid):
    return (
        {
            "fixture": {"id": fid},
            "goal_model": {
                "available": True,
                "estimated_goals": {"home": 1.5, "away": 1.1},  # the "latest" estimate
                "probabilities": {},
            },
        },
        None,
        None,
    )


def _targets(snap):
    t = {"fixture": snap.fixtures[0].fixture_id, "ctx": "challenge", "round": snap.round_id,
         "fp": snap.fingerprint}  # fmt: skip
    return t, {**t, "latest": True}


def test_frozen_and_latest_your_view_are_separate_account_rows(engine, op, as_user):  # noqa: F811
    view, snap = publish_dev(engine, op, deadline_in=timedelta(hours=3), seed=8701)
    service = make_service(engine, view.id, detail=_detail)
    as_user(principal(engine))
    frozen_t, latest_t = _targets(snap)
    frozen, p1 = lab_context.resolve_target(service, service.data, frozen_t)
    latest, p2 = lab_context.resolve_target(service, service.data, latest_t)
    assert p1 is None and p2 is None and frozen.kind == "round" and latest.kind == "live"
    assert frozen.round_id == view.id and frozen.key != latest.key
    s_frozen = lab.normalise_state({"manual": {"home": 0.3}})
    s_latest = lab.normalise_state({"manual": {"home": -0.2}})
    store, problem = lab_persist.save(service, {}, frozen, s_frozen)
    assert problem is None
    store, problem = lab_persist.save(service, store, latest, s_latest)
    assert problem is None
    # another device: an empty browser store loads each context from the account
    a = lab_persist.load(service, {}, frozen)
    b = lab_persist.load(service, {}, latest)
    assert a[frozen.key] == s_frozen and latest.key not in a
    assert b[latest.key] == s_latest and frozen.key not in b
    # saving the latest view again never touches the frozen one
    store, _ = lab_persist.save(service, store, latest,
                                lab.normalise_state({"manual": {"home": 0.5}}))  # fmt: skip
    assert lab_persist.load(service, {}, frozen)[frozen.key] == s_frozen


def test_locked_round_stays_read_only_in_both_modes(engine, op):
    view, snap = publish_dev(engine, op, deadline_in=timedelta(seconds=4), seed=8702)
    wait_until(engine, rsvc.get_round(engine, view.id).deadline_at)
    rsvc.lock_round(engine, rsvc.SYSTEM, view.id)
    service = make_service(engine, view.id, detail=_detail)
    frozen_t, latest_t = _targets(snap)
    for t in (frozen_t, latest_t):  # both views stay available for analysis
        lc, problem = lab_context.resolve_target(service, service.data, t)
        assert problem is None and lc is not None
    assert not cb.competitive(latest_t)  # no selection controls with the latest data
    key = "|".join(map(str, snap.outcomes[0].key))
    new, flash = cb.apply_action(service, {"mode": "live"}, "pick", key)
    assert "locked" in flash["text"] and key not in (new.get("selections") or [])
