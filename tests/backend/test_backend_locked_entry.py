"""Phase 6C.3 Stage G: the participant's most recent locked entry (read-only), on
real PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from svc_helpers import principal, publish_dev, valid_keys, wait_until

from diski9.backend.auth.permissions import GUEST, AuthorizationError
from diski9.backend.services import drafts
from diski9.backend.services import entries as es
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import RoundClosed


def _key() -> str:
    return "locked-" + uuid.uuid4().hex


def _confirm(engine, p, view, snap, n_offset=0, version=0, replace=False, dv=0):
    keys = valid_keys(snap, 9)
    if n_offset:
        keys = list(reversed(keys))  # same outcomes, different order is still a change
    d = drafts.save_draft(engine, p, view.id, keys, expected_version=dv)
    return es.confirm_entry(
        engine,
        p,
        view.id,
        draft_version=d.version,
        expected_entry_version=version,
        idempotency_key=_key(),
        replace=replace,
    ), d


def latest(engine, p, **kw):
    kw.setdefault("include_development", True)
    return es.latest_locked_entry(engine, p, **kw)


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture(scope="module")
def world(engine, op):
    """Two short rounds that pass their deadlines (older and newer), one still open.
    A confirms in both short rounds (replacing once in the newer one); B confirms
    and withdraws; C never enters."""
    old, old_snap = publish_dev(engine, op, deadline_in=timedelta(seconds=4))
    new, new_snap = publish_dev(engine, op, deadline_in=timedelta(seconds=8), seed=7)
    a, b, c = principal(engine), principal(engine), principal(engine)
    _confirm(engine, a, old, old_snap)
    e1, d1 = _confirm(engine, a, new, new_snap)
    e2, d2 = _confirm(engine, a, new, new_snap, n_offset=1, version=e1.version, replace=True,
                      dv=d1.version)  # fmt: skip
    eb, _ = _confirm(engine, b, new, new_snap)
    es.withdraw_entry(engine, b, new.id, expected_entry_version=eb.version)
    wait_until(engine, new.deadline_at)
    current, current_snap = publish_dev(engine, op, deadline_in=timedelta(hours=3), seed=11)
    return dict(old=old, new=new, new_snap=new_snap, current=current,
                current_snap=current_snap, a=a, b=b, c=c, e2=e2, d2=d2)  # fmt: skip


def test_deadline_passed_before_lock_is_reported_truthfully(engine, world):
    view, entry = latest(engine, world["a"], exclude_round_id=world["current"].id)
    assert view.id == world["new"].id  # the most recent deadline, not the older round
    assert view.status == "open" and not entry.locked  # lock job has not run yet


def test_most_recent_locked_entry_is_the_stored_current_version(engine, world):
    svc.lock_round(engine, svc.SYSTEM, world["new"].id)
    view, entry = latest(engine, world["a"], exclude_round_id=world["current"].id)
    assert view.id == world["new"].id and view.status == "locked" and entry.locked
    assert entry.active and entry.current.version == 2  # the replacement, not v1
    assert entry.current.keys == world["e2"].current.keys
    assert len(entry.current.selections) == 9
    from collections import Counter

    assert sorted(Counter(s["bucket"] for s in entry.current.selections).values()) == [2, 3, 4]


def test_open_current_round_does_not_hide_it_and_never_duplicates(engine, world):
    # Another round is open: the locked entry is still returned beside it.
    assert latest(engine, world["a"], exclude_round_id=world["current"].id) is not None
    # When the page already shows the locked round, it is excluded (the older one may
    # be returned instead, but never the same round twice).
    found = latest(engine, world["a"], exclude_round_id=world["new"].id)
    assert found is not None and found[0].id == world["old"].id


def test_current_round_draft_changes_do_not_alter_the_locked_entry(engine, world):
    a, cur = world["a"], world["current"]
    drafts.save_draft(engine, a, cur.id, valid_keys(world["current_snap"], 5), expected_version=0)
    _, entry = latest(engine, a, exclude_round_id=cur.id)
    assert entry.current.keys == world["e2"].current.keys


def test_no_mutation_after_the_deadline(engine, world):
    a, new, e2, d2 = world["a"], world["new"], world["e2"], world["d2"]
    with pytest.raises(RoundClosed):
        drafts.save_draft(engine, a, new.id, valid_keys(world["new_snap"], 3),
                          expected_version=d2.version)  # fmt: skip
    with pytest.raises(RoundClosed):
        es.confirm_entry(engine, a, new.id, draft_version=d2.version,
                         expected_entry_version=e2.version, idempotency_key=_key(),
                         replace=True)  # fmt: skip
    with pytest.raises(RoundClosed):
        es.withdraw_entry(engine, a, new.id, expected_entry_version=e2.version)
    _, entry = latest(engine, a, exclude_round_id=world["current"].id)
    assert entry.current.version == 2


def test_withdrawn_entries_and_accounts_without_entries(engine, world):
    assert latest(engine, world["b"]) is None  # withdrawn before the deadline
    assert latest(engine, world["c"]) is None  # never entered


def test_owner_scoped_and_guests_refused(engine, world):
    # Each account sees only its own row: C gets nothing although A has entries.
    assert latest(engine, world["c"], exclude_round_id=world["current"].id) is None
    with pytest.raises(AuthorizationError):
        es.latest_locked_entry(engine, GUEST)


def test_development_rounds_hidden_unless_asked(engine, world):
    assert es.latest_locked_entry(engine, world["a"]) is None
