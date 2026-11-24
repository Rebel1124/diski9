"""Phase 6C.3 Stage C: private portfolio drafts on real PostgreSQL."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError
from svc_helpers import principal, publish_dev, valid_keys, wait_until

from diski9.backend.auth.permissions import GUEST, AuthorizationError
from diski9.backend.db import transaction
from diski9.backend.db.schema import portfolio_drafts, users
from diski9.backend.services import drafts
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import (
    AccountInactive,
    PersistenceFailed,
    RoundClosed,
    ValidationFailed,
    VersionConflict,
)


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture(scope="module")
def rnd(engine, op):
    view, snap = publish_dev(engine, op)
    return view, snap


def test_new_participant_has_an_empty_editable_draft(engine, rnd):
    view, _ = rnd
    d = drafts.get_draft(engine, principal(engine), view.id)
    assert (d.selections, d.version, d.editable) == ((), 0, True)


def test_save_retrieve_change_and_clear(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    d1 = drafts.save_draft(engine, p, view.id, keys[:3], expected_version=0)
    assert d1.version == 1 and list(d1.selections) == keys[:3]
    assert d1.snapshot_fingerprint == snap.fingerprint
    again = drafts.get_draft(engine, p, view.id)
    assert again == d1  # a later session sees exactly the saved draft
    d2 = drafts.save_draft(engine, p, view.id, [keys[0], keys[2]], expected_version=1)
    assert d2.version == 2 and len(d2.selections) == 2  # removal
    d3 = drafts.save_draft(engine, p, view.id, keys, expected_version=2)
    assert d3.version == 3 and len(d3.selections) == 9  # complete, still only a draft
    cleared = drafts.clear_draft(engine, p, view.id, expected_version=3)
    assert cleared.selections == () and cleared.version == 4  # the row keeps its version


def test_prototype_string_keys_are_accepted(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = [f"{k['fixture_id']}|{k['market']}|{k['outcome']}" for k in valid_keys(snap, 2)]
    d = drafts.save_draft(engine, p, view.id, keys, expected_version=0)
    assert d.keys == keys


def test_client_values_beyond_the_key_are_ignored(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    k = valid_keys(snap, 1)[0]
    forged = {**k, "bucket": "A", "odds": "99.00", "market_prob": 0.99, "credits": 1000}
    d = drafts.save_draft(engine, p, view.id, [forged], expected_version=0)
    assert list(d.selections) == [k]
    with transaction(engine) as conn:
        stored = conn.execute(
            select(portfolio_drafts.c.selections).where(portfolio_drafts.c.user_id == p.user_id)
        ).scalar_one()
    assert stored == [k]


def _issues(fn):
    with pytest.raises(ValidationFailed) as exc:
        fn()
    return [i["reason"] for i in exc.value.issues]


def test_invalid_selections_are_refused_whole(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    base = drafts.save_draft(engine, p, view.id, keys[:2], expected_version=0)
    keyset = {(k["fixture_id"], k["market"], k["outcome"]) for k in keys[:2]}
    same_fixture = next(
        o
        for o in snap.outcomes
        if o.fixture_id == keys[0]["fixture_id"] and o.key not in keyset and svc_bucket(o)
    )
    taken = {
        "fixture_id": same_fixture.fixture_id,
        "market": str(same_fixture.market),
        "outcome": str(same_fixture.outcome),
    }
    ineligible = next(
        o
        for o in snap.outcomes
        if svc_bucket(o) is None and o.fixture_id not in {k["fixture_id"] for k in keys}
    )
    cases = {
        "not_on_sheet": [*keys[:2], {"fixture_id": 1, "market": "1X2", "outcome": "HOME"}],
        "duplicate": [keys[0], keys[0]],
        "fixture_taken": [keys[0], taken],
        "ineligible": [
            {
                "fixture_id": ineligible.fixture_id,
                "market": str(ineligible.market),
                "outcome": str(ineligible.outcome),
            }
        ],
        "malformed": [{"fixture_id": "x", "market": "1X2", "outcome": "HOME"}],
        "too_many": keys + [keys[0]],
    }
    for reason, sels in cases.items():
        got = _issues(lambda s=sels: drafts.save_draft(engine, p, view.id, s, expected_version=1))
        assert reason in got, (reason, got)
    assert drafts.get_draft(engine, p, view.id) == base  # nothing was truncated or saved


def svc_bucket(o):
    from diski9.challenge.config import BROAD60_432_V1  # v1 rounds (explicit)

    return BROAD60_432_V1.classify(o.market_probability)


def test_bucket_overflow_is_refused(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    foundation = []
    used = set()
    for o in snap.outcomes:
        if svc_bucket(o) == "A" and o.fixture_id not in used:
            foundation.append(
                {"fixture_id": o.fixture_id, "market": str(o.market), "outcome": str(o.outcome)}
            )
            used.add(o.fixture_id)
    assert len(foundation) >= 5
    got = _issues(lambda: drafts.save_draft(engine, p, view.id, foundation[:5], expected_version=0))
    assert got[-1] in ("bucket_full", "would_block_completion")


def test_selections_from_another_round_are_refused(engine, op, rnd):
    view, _ = rnd
    _, other_snap = publish_dev(engine, op, seed=7)
    p = principal(engine)
    got = _issues(
        lambda: drafts.save_draft(engine, p, view.id, valid_keys(other_snap, 2), expected_version=0)
    )
    assert set(got) == {"not_on_sheet"}


def test_drafts_are_per_round(engine, op, rnd):
    view, snap = rnd
    other, other_snap = publish_dev(engine, op, seed=11)
    p = principal(engine)
    drafts.save_draft(engine, p, view.id, valid_keys(snap, 3), expected_version=0)
    assert drafts.get_draft(engine, p, other.id).selections == ()
    drafts.save_draft(engine, p, other.id, valid_keys(other_snap, 1), expected_version=0)
    assert len(drafts.get_draft(engine, p, view.id).selections) == 3


def test_stale_tab_gets_a_conflict_not_a_lost_update(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    drafts.save_draft(engine, p, view.id, keys[:1], expected_version=0)  # both tabs at v1
    phone = drafts.save_draft(engine, p, view.id, keys[:4], expected_version=1)  # v2
    with pytest.raises(VersionConflict) as exc:  # the laptop still thinks v1
        drafts.save_draft(engine, p, view.id, keys[:2], expected_version=1)
    assert exc.value.latest == phone  # the page can offer "load the latest saved draft"
    assert drafts.get_draft(engine, p, view.id) == phone
    reloaded = drafts.save_draft(engine, p, view.id, keys[:5], expected_version=phone.version)
    assert reloaded.version == 3


def test_reset_on_one_device_never_lets_an_old_version_overwrite(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    drafts.save_draft(engine, p, view.id, keys[:2], expected_version=0)  # v1 everywhere
    drafts.clear_draft(engine, p, view.id, expected_version=1)  # v2 on device A
    drafts.save_draft(engine, p, view.id, keys[:3], expected_version=2)  # v3 on device A
    with pytest.raises(VersionConflict):  # device B, still at v1
        drafts.save_draft(engine, p, view.id, keys[:1], expected_version=1)


def test_repeated_identical_saves_write_nothing(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap, 3)
    d = drafts.save_draft(engine, p, view.id, keys, expected_version=0)
    for expected in (1, 0, 1):  # double click, network retry with the old version, rerun
        again = drafts.save_draft(engine, p, view.id, keys, expected_version=expected)
        assert again.version == 1 and again.updated_at == d.updated_at


def test_concurrent_saves_from_two_devices(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    drafts.save_draft(engine, p, view.id, keys[:1], expected_version=0)
    outcomes, barrier = [], threading.Barrier(2)

    def device(sels):
        barrier.wait()
        try:
            outcomes.append(drafts.save_draft(engine, p, view.id, sels, expected_version=1))
        except VersionConflict as exc:
            outcomes.append(exc)

    ts = [threading.Thread(target=device, args=(s,)) for s in (keys[:3], keys[:4])]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    saved = [o for o in outcomes if not isinstance(o, Exception)]
    conflicts = [o for o in outcomes if isinstance(o, VersionConflict)]
    assert len(saved) == 1 and len(conflicts) == 1
    assert drafts.get_draft(engine, p, view.id) == saved[0]


def test_concurrent_first_saves(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    outcomes, barrier = [], threading.Barrier(2)

    def device(sels):
        barrier.wait()
        try:
            outcomes.append(drafts.save_draft(engine, p, view.id, sels, expected_version=0))
        except VersionConflict as exc:
            outcomes.append(exc)

    ts = [threading.Thread(target=device, args=(s,)) for s in (keys[:2], keys[:3])]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(type(o).__name__ for o in outcomes) == ["DraftView", "VersionConflict"]


def test_accounts_never_see_each_others_drafts(engine, rnd):
    view, snap = rnd
    a, b = principal(engine), principal(engine)
    drafts.save_draft(engine, a, view.id, valid_keys(snap, 4), expected_version=0)
    assert drafts.get_draft(engine, b, view.id).selections == ()
    drafts.save_draft(engine, b, view.id, valid_keys(snap, 1), expected_version=0)
    assert len(drafts.get_draft(engine, a, view.id).selections) == 4


def test_guests_and_unonboarded_accounts_are_rejected(engine, rnd):
    view, _ = rnd
    from dataclasses import replace

    with pytest.raises(AuthorizationError):
        drafts.get_draft(engine, GUEST, view.id)
    with pytest.raises(AuthorizationError):
        drafts.save_draft(engine, GUEST, view.id, [], expected_version=0)
    with pytest.raises(AuthorizationError):
        drafts.save_draft(
            engine, replace(principal(engine), onboarded=False), view.id, [], expected_version=0
        )


def test_suspended_account_cannot_save(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    with transaction(engine) as conn:
        conn.execute(update(users).where(users.c.id == p.user_id).values(status="suspended"))
    with pytest.raises(AccountInactive):
        drafts.save_draft(engine, p, view.id, valid_keys(snap, 1), expected_version=0)


def test_draft_is_read_only_after_the_deadline(engine, op):
    view, snap = publish_dev(engine, op, deadline_in=timedelta(seconds=3))
    p = principal(engine)
    keys = valid_keys(snap)
    saved = drafts.save_draft(engine, p, view.id, keys[:2], expected_version=0)
    wait_until(engine, view.deadline_at)
    with pytest.raises(RoundClosed):
        drafts.save_draft(engine, p, view.id, keys[:3], expected_version=1)
    kept = drafts.get_draft(engine, p, view.id)
    assert kept.selections == saved.selections and kept.editable is False
    with pytest.raises(DBAPIError), transaction(engine) as conn:  # the trigger agrees
        conn.execute(
            update(portfolio_drafts)
            .where(portfolio_drafts.c.user_id == p.user_id)
            .values(selections=[])
        )
    svc.lock_round(engine, svc.SYSTEM, view.id)
    assert drafts.get_draft(engine, p, view.id).selections == saved.selections  # preserved


def test_trigger_refuses_drafts_for_unpublished_rounds(engine, op):
    from svc_helpers import unique

    with transaction(engine) as conn:
        from diski9.backend.db import db_now

        now = db_now(conn)
    v = svc.create_round(
        engine,
        op,
        code=unique("dev-u"),
        window_start=now,
        window_end=now + timedelta(days=2),
        development=True,
    )
    p = principal(engine)
    with pytest.raises(DBAPIError), transaction(engine) as conn:
        conn.execute(
            insert(portfolio_drafts).values(
                user_id=p.user_id, round_id=v.id, selections=[], version=1
            )
        )
    with pytest.raises(RoundClosed):
        drafts.save_draft(engine, p, v.id, [], expected_version=0)


def test_a_failed_write_saves_nothing_and_says_so(engine, rnd, monkeypatch):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    d = drafts.save_draft(engine, p, view.id, keys[:1], expected_version=0)
    real = drafts.update

    def broken(*a, **kw):  # the UPDATE statement fails inside the transaction
        stmt = real(*a, **kw)
        return stmt.values(user_id=None)  # violates NOT NULL

    monkeypatch.setattr(drafts, "update", broken)
    with pytest.raises(PersistenceFailed) as exc:
        drafts.save_draft(engine, p, view.id, keys[:2], expected_version=1)
    assert "still on this page" in exc.value.message and "version" not in exc.value.message
    monkeypatch.undo()
    assert drafts.get_draft(engine, p, view.id) == d  # rolled back


def test_waiting_for_another_device_cannot_extend_the_draft_window(engine, op, pg_url):
    """A draft save that waits for another device's lock past the deadline is
    refused (the deadline is re-checked after the wait)."""
    import threading

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine

    view, snap = publish_dev(engine, op, deadline_in=timedelta(seconds=4))
    p = principal(engine)
    d = drafts.save_draft(engine, p, view.id, valid_keys(snap, 1), expected_version=0)
    patient = make_app_engine(
        BackendDatabaseSettings(environment="test", lock_timeout_ms=20000), url=pg_url
    )
    holder = engine.connect()
    trans = holder.begin()
    holder.execute(
        select(portfolio_drafts).where(portfolio_drafts.c.user_id == p.user_id).with_for_update()
    )
    out = []

    def attempt():
        try:
            out.append(
                drafts.save_draft(
                    patient, p, view.id, valid_keys(snap, 2), expected_version=d.version
                )
            )
        except Exception as exc:  # noqa: BLE001
            out.append(exc)

    t = threading.Thread(target=attempt)
    t.start()
    wait_until(engine, view.deadline_at)
    trans.rollback()
    holder.close()
    t.join(timeout=10)
    patient.dispose()
    assert isinstance(out[0], RoundClosed)
    assert drafts.get_draft(engine, p, view.id).version == d.version


def test_saves_from_one_tab_are_ordered_and_other_devices_still_conflict(engine, rnd):
    """The front end can send a newer save from the same tab before an older one
    finishes. The newer one wins whatever the arrival order; another device with
    an old version still gets a conflict."""
    from diski9.backend.services.common import Writer

    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap)
    tab = Writer("tab-" + "a" * 20, 0)
    d = drafts.save_draft(engine, p, view.id, keys[:1], expected_version=0, writer=tab)
    newer = drafts.save_draft(
        engine, p, view.id, keys[:3], expected_version=d.version, writer=Writer(tab.tab, 2)
    )
    late_old = drafts.save_draft(
        engine, p, view.id, keys[:2], expected_version=d.version, writer=Writer(tab.tab, 1)
    )
    assert late_old == newer  # the older request is ignored, not a conflict
    assert drafts.get_draft(engine, p, view.id).selections == newer.selections
    again = drafts.save_draft(
        engine, p, view.id, keys[:4], expected_version=d.version, writer=Writer(tab.tab, 3)
    )  # its own newer request
    assert len(again.selections) == 4
    with pytest.raises(VersionConflict):
        drafts.save_draft(
            engine,
            p,
            view.id,
            keys[:5],
            expected_version=d.version,
            writer=Writer("tab-" + "b" * 20, 9),
        )
    with pytest.raises(ValidationFailed):
        Writer("short", 1)
