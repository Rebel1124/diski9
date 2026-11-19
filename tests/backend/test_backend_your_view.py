"""Phase 6C.3 Stage D: private, numerical Your View persistence (D-41, T-10) on
real PostgreSQL."""

from __future__ import annotations

import random
import threading
from dataclasses import replace

import pytest
from sqlalchemy import select, update
from svc_helpers import principal, publish_dev, valid_keys

from diski9.app import lab
from diski9.backend.auth.permissions import GUEST, AuthorizationError
from diski9.backend.db import BackendDatabaseSettings, make_app_engine, transaction
from diski9.backend.db.schema import users, your_view_adjustments
from diski9.backend.services import drafts, snapshots
from diski9.backend.services import rounds as svc
from diski9.backend.services import your_view as yv
from diski9.backend.services.common import (
    AccountInactive,
    NotFound,
    ValidationFailed,
    VersionConflict,
)

FID = 1_234_567
CTX = f"1.0|{FID}|1.45|0.98"
CTX_NEW = f"1.0|{FID}|1.52|0.98"  # the model was refitted: a different baseline
LIVE = yv.LiveContext(FID, CTX)
LIVE_NEW = yv.LiveContext(FID, CTX_NEW)


def adjusted() -> dict:
    s = yv.zero_state()
    s["context"]["home"] = 0.25
    s["cats"]["squad"]["away"] = -0.4
    s["cats"]["conditions"]["home"] = -0.15
    s["manual"]["away"] = 0.07
    return s


def test_limits_match_the_match_lab():
    assert yv.SIDES == lab.SIDES and yv.CATEGORY_KEYS == lab.CATEGORY_KEYS
    assert (yv.CONTEXT_MAX, yv.CATEGORY_MAX, yv.ADJUST_MAX) == (
        lab.CONTEXT_MAX,
        lab.CATEGORY_MAX,
        lab.ADJUST_MAX,
    )
    assert yv.zero_state() == lab.new_state()


def test_save_and_retrieve_numbers_only(engine):
    p = principal(engine)
    assert yv.get_your_view(engine, p, LIVE).status == yv.NONE
    saved = yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0)
    assert saved.status == yv.ACTIVE and saved.version == 1 and saved.state == adjusted()
    assert yv.get_your_view(engine, p, LIVE) == saved
    with transaction(engine) as conn:
        stored = conn.execute(
            select(your_view_adjustments.c.state).where(
                your_view_adjustments.c.user_id == p.user_id
            )
        ).scalar_one()
    assert set(stored) == {"context", "cats", "manual"}  # no notes, no reasons


def test_states_produced_by_the_match_lab_round_trip_exactly(engine):
    """Random Match Lab states (Section B and C steps of 0.05, Section D to 0.01)
    are stored and returned without any change."""
    p = principal(engine)
    rng = random.Random(41)
    version = 0
    for i in range(40):
        s = lab.new_state()
        for side in lab.SIDES:
            s["context"][side] = round(rng.randint(-20, 20) * 0.05, 2)
            for k in lab.CATEGORY_KEYS:
                s["cats"][k][side] = round(rng.randint(-40, 40) * 0.05, 2)
            s["manual"][side] = round(rng.uniform(-9, 9), 2)
        out = yv.save_your_view(
            engine,
            p,
            yv.LiveContext(FID + i, f"1.0|{FID + i}|1.10|1.20"),
            s,
            expected_version=version if i == 0 else 0,
        )
        assert out.state == s
        assert lab.breakdown({"home": 1.1, "away": 1.2}, out.state) == lab.breakdown(
            {"home": 1.1, "away": 1.2}, s
        )


def test_legacy_notes_are_dropped_and_numbers_kept(engine):
    p = principal(engine)
    legacy = adjusted()
    legacy["context"]["note"] = "derby"
    legacy["cats"]["squad"]["note"] = "striker injured"
    legacy["notes"] = ["old journal"]
    legacy["reason"] = "gut feeling"
    saved = yv.save_your_view(engine, p, LIVE, legacy, expected_version=0)
    assert saved.state == adjusted()
    assert lab.normalise_state(legacy) == saved.state  # the Match Lab reads it the same


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda s: s["context"].__setitem__("home", 1.05), "out_of_range"),
        (lambda s: s["cats"]["fitness"].__setitem__("away", -2.5), "out_of_range"),
        (lambda s: s["manual"].__setitem__("home", 25.0), "out_of_range"),
        (lambda s: s["context"].__setitem__("away", 0.123), "too_precise"),
        (lambda s: s["cats"].__setitem__("weather", {"home": 0.1, "away": 0}), "unknown_factor"),
        (lambda s: s["manual"].__setitem__("away", float("nan")), "not_a_number"),
        (lambda s: s["manual"].__setitem__("away", "0.5"), "not_a_number"),
        (lambda s: s["manual"].__setitem__("away", True), "not_a_number"),
    ],
)
def test_out_of_range_or_malformed_values_are_refused(engine, mutate, reason):
    p = principal(engine)
    s = adjusted()
    mutate(s)
    with pytest.raises(ValidationFailed) as exc:
        yv.save_your_view(engine, p, LIVE, s, expected_version=0)
    assert reason in {i["reason"] for i in exc.value.issues}
    assert yv.get_your_view(engine, p, LIVE).version == 0


def test_context_must_belong_to_the_fixture(engine):
    p = principal(engine)
    for bad in ("", "1.0|999|1.00|1.00", "nonsense", f"1.0|{FID}|1.4|0.98"):
        with pytest.raises(ValidationFailed):
            yv.save_your_view(engine, p, yv.LiveContext(FID, bad), adjusted(), expected_version=0)


def test_a_different_model_context_is_not_applied_or_rewritten(engine):
    p = principal(engine)
    saved = yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0)
    other = yv.get_your_view(engine, p, LIVE_NEW)
    assert other.status == yv.INCOMPATIBLE and other.state is None
    assert other.stored_context == CTX
    assert yv.get_your_view(engine, p, LIVE) == saved  # reading changed nothing
    # a new adjustment made in the new context replaces it, only from the current version
    with pytest.raises(VersionConflict):
        yv.save_your_view(engine, p, LIVE_NEW, adjusted(), expected_version=0)
    fresh = yv.zero_state()
    fresh["manual"]["home"] = 0.3
    new = yv.save_your_view(engine, p, LIVE_NEW, fresh, expected_version=saved.version)
    assert new.status == yv.ACTIVE and new.state == fresh
    assert yv.get_your_view(engine, p, LIVE).status == yv.INCOMPATIBLE


def test_reset_stores_zeros_and_keeps_the_version_moving(engine):
    p = principal(engine)
    s1 = yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0)
    r = yv.reset_your_view(engine, p, LIVE, expected_version=s1.version)
    assert r.status == yv.NONE and r.state == yv.zero_state() and r.version == 2
    with pytest.raises(VersionConflict):  # a tab still at v1 cannot bring back old numbers
        yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=1)


def test_identical_saves_write_nothing(engine):
    p = principal(engine)
    s1 = yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0)
    again = yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0)
    assert again.version == 1 and again.updated_at == s1.updated_at


def test_concurrent_saves_one_wins_one_conflicts(engine):
    p = principal(engine)
    yv.save_your_view(engine, p, LIVE, yv.zero_state(), expected_version=0)
    a, b = adjusted(), adjusted()
    b["manual"]["home"] = 0.5
    results, barrier = [], threading.Barrier(2)

    def device(state):
        barrier.wait()
        try:
            results.append(yv.save_your_view(engine, p, LIVE, state, expected_version=1))
        except VersionConflict as exc:
            results.append(exc)

    ts = [threading.Thread(target=device, args=(s,)) for s in (a, b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(type(r).__name__ for r in results) == ["VersionConflict", "YourView"]


def test_private_to_each_account(engine):
    a, b = principal(engine), principal(engine)
    yv.save_your_view(engine, a, LIVE, adjusted(), expected_version=0)
    assert yv.get_your_view(engine, b, LIVE).status == yv.NONE
    assert yv.get_many(engine, b, [LIVE])[LIVE].state is None
    yv.save_your_view(engine, b, LIVE, yv.zero_state(), expected_version=0)
    assert yv.get_your_view(engine, a, LIVE).state == adjusted()


def test_another_device_or_restarted_app_sees_the_same_state(pg_url, engine):
    p = principal(engine)
    saved = yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0)
    other = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)
    try:
        assert yv.get_your_view(other, p, LIVE) == saved
    finally:
        other.dispose()


def test_guests_and_suspended_accounts(engine):
    with pytest.raises(AuthorizationError):
        yv.get_your_view(engine, GUEST, LIVE)
    with pytest.raises(AuthorizationError):
        yv.save_your_view(
            engine,
            replace(principal(engine), onboarded=False),
            LIVE,
            adjusted(),
            expected_version=0,
        )
    p = principal(engine)
    with transaction(engine) as conn:
        conn.execute(update(users).where(users.c.id == p.user_id).values(status="suspended"))
    with pytest.raises(AccountInactive):
        yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0)


def test_frozen_context_and_no_effect_on_the_competition(engine):
    """A round context takes its snapshot and frozen baseline from the database and
    changes nothing shared: snapshot, odds, probabilities, buckets, drafts."""
    op = principal(engine, role="operator")
    view, snap = publish_dev(engine, op)
    f = snap.fixtures[0]
    rc = yv.RoundContext(view.id, f.fixture_id)
    h, a = (round(x, 2) for x in f.estimated_goals)
    assert yv.resolved_context(engine, rc) == f"1.0|{f.fixture_id}|{h:.2f}|{a:.2f}"
    assert yv.resolved_context(engine, rc) == yv.frozen_context(
        snap, f.fixture_id, view.model_version
    )
    p = principal(engine)
    with pytest.raises(NotFound):
        yv.save_your_view(engine, p, yv.RoundContext(view.id, 1), adjusted(), expected_version=0)
    keys = valid_keys(snap, 3)
    d = drafts.save_draft(engine, p, view.id, keys, expected_version=0)
    s = adjusted()
    s["manual"]["home"] = 2.0
    yv.save_your_view(engine, p, rc, s, expected_version=0)
    snapshots.CACHE.clear()
    after = svc.published_snapshot(engine, view.id)
    assert after.fingerprint == snap.fingerprint and after.outcomes == snap.outcomes
    assert drafts.get_draft(engine, p, view.id) == d
    other = yv.RoundContext(view.id, snap.fixtures[1].fixture_id)
    many = yv.get_many(engine, p, [rc, other])
    assert many[rc].status == yv.ACTIVE and many[other].status == yv.NONE


def test_your_view_saves_from_one_tab_are_ordered(engine):
    from diski9.backend.services.common import Writer

    p = principal(engine)
    t = "tab-" + "c" * 20
    yv.save_your_view(engine, p, LIVE, adjusted(), expected_version=0, writer=Writer(t, 0))
    newer = adjusted()
    newer["manual"]["home"] = 0.4
    yv.save_your_view(engine, p, LIVE, newer, expected_version=0, writer=Writer(t, 5))
    late = yv.save_your_view(
        engine, p, LIVE, yv.zero_state(), expected_version=0, writer=Writer(t, 4)
    )
    assert late.state == newer
    with pytest.raises(VersionConflict):
        yv.save_your_view(
            engine,
            p,
            LIVE,
            yv.zero_state(),
            expected_version=0,
            writer=Writer("tab-" + "d" * 20, 6),
        )
