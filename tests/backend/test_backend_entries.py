"""Phase 6C.3 Stage E: confirm, replace, withdraw and re-enter on real PostgreSQL,
including genuine multi-connection races."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text, update
from svc_helpers import principal, publish_dev, valid_keys, wait_until

from diski9.backend.auth.permissions import GUEST, AuthorizationError
from diski9.backend.db import transaction
from diski9.backend.db.schema import entries, portfolio_drafts, submissions, users
from diski9.backend.repositories import rounds as rounds_repo
from diski9.backend.services import drafts
from diski9.backend.services import entries as es
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import (
    AccountInactive,
    PersistenceFailed,
    RoundClosed,
    ValidationFailed,
    VersionConflict,
)
from diski9.challenge.config import DEFAULT_CONFIG, ProbabilitySource
from diski9.challenge.structured import evaluate_portfolio, validate_portfolio


def key() -> str:
    return "confirm-" + uuid.uuid4().hex


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture(scope="module")
def rnd(engine, op):
    return publish_dev(engine, op)


def ready(engine, view, snap, n=9, p=None, offset=0):
    """A participant with a saved draft of ``n`` selections."""
    p = p or principal(engine)
    keys = valid_keys(snap, 9 + offset)[offset:][:n] if offset else valid_keys(snap, n)
    d = drafts.save_draft(engine, p, view.id, keys, expected_version=0)
    return p, d


def confirm(engine, p, view, d, version=0, **kw):
    return es.confirm_entry(
        engine,
        p,
        view.id,
        draft_version=d.version,
        expected_entry_version=version,
        idempotency_key=kw.pop("k", key()),
        **kw,
    )


def count(engine, table, **where):
    with transaction(engine) as conn:
        q = select(func.count()).select_from(table)
        for col, v in where.items():
            q = q.where(getattr(table.c, col) == v)
        return conn.execute(q).scalar_one()


# ------------------------------------------------------------------ confirmation
def test_confirmation_stores_snapshot_values_and_engine_evaluation(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    e = confirm(engine, p, view, d)
    assert e.active and e.state == "confirmed" and e.current.version == 1
    sels = e.current.selections
    assert [s["bucket"] for s in sels] == ["A"] * 4 + ["B"] * 3 + ["C"] * 2
    assert len({s["fixture_id"] for s in sels}) == 9
    for s in sels:  # every value comes from the frozen snapshot, at full precision
        o = snap.outcome((s["fixture_id"], s["market"], s["outcome"]))
        assert s["market_prob"] == o.market_probability
        assert s["model_prob"] == o.model_probability
        assert s["consensus_odds"] == str(o.reference_odds)
    outs = [snap.outcome((s["fixture_id"], s["market"], s["outcome"])) for s in sels]
    pf = validate_portfolio(outs, snap.snapshot_at, DEFAULT_CONFIG, pool=snap.outcomes)
    market = evaluate_portfolio(pf, ProbabilitySource.MARKET)
    model = evaluate_portfolio(pf, ProbabilitySource.MODEL)
    assert e.current.p_recover_market == market.p_recover
    assert e.current.expected_gross_market == market.expected_gross
    assert e.current.p_recover_model == model.p_recover
    assert e.current.max_gross == market.max_gross
    assert [h.kind for h in e.history] == ["confirmed"]
    assert es.get_entry(engine, p, view.id) == e


def test_incomplete_or_tampered_drafts_cannot_be_confirmed(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap, n=8)
    with pytest.raises(ValidationFailed, match="exactly 4 Foundation"):
        confirm(engine, p, view, d)
    assert count(engine, entries, user_id=p.user_id) == 0  # nothing left behind
    p2, d2 = ready(engine, view, snap)
    forged = [*d2.selections[:8], {"fixture_id": 1, "market": "1X2", "outcome": "HOME"}]
    with transaction(engine) as conn:  # a saved draft altered behind the service
        conn.execute(
            update(portfolio_drafts)
            .where(portfolio_drafts.c.user_id == p2.user_id)
            .values(selections=forged)
        )
    with pytest.raises(ValidationFailed):
        confirm(engine, p2, view, d2)
    assert count(engine, submissions, user_id=p2.user_id) == 0


def test_confirm_needs_the_draft_version_the_page_showed(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap, n=8)
    keys = valid_keys(snap)
    full = drafts.save_draft(engine, p, view.id, keys, expected_version=d.version)
    with pytest.raises(VersionConflict, match="Review it again"):
        confirm(engine, p, view, d)  # the page still shows the 8-pick version
    assert confirm(engine, p, view, full).active


def test_duplicate_requests_create_one_submission(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    k = key()
    first = confirm(engine, p, view, d, k=k)
    again = confirm(engine, p, view, d, k=k)  # retried after a network error
    assert again.current.id == first.current.id
    assert count(engine, submissions, user_id=p.user_id) == 1
    with pytest.raises(es.AlreadyEntered):  # a second click with a new key
        confirm(engine, p, view, d, version=first.version)


def test_reusing_a_key_for_different_content_is_refused(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    k = key()
    e = confirm(engine, p, view, d, k=k)
    keys = valid_keys(snap, 9)
    other = drafts.save_draft(engine, p, view.id, keys[::-1], expected_version=d.version)
    with pytest.raises(es.IdempotencyMismatch):
        confirm(engine, p, view, other, version=e.version, k=k, replace=True)


def test_editing_the_draft_never_changes_the_confirmed_entry(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    e = confirm(engine, p, view, d)
    drafts.save_draft(engine, p, view.id, valid_keys(snap, 4), expected_version=d.version)
    assert es.get_entry(engine, p, view.id).current == e.current


# ------------------------------------------------------------------ replacement
def test_replacement_creates_a_new_version_and_keeps_the_old(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    e1 = confirm(engine, p, view, d)
    keys = list(e1.current.keys)
    swapped = [*keys[1:4], keys[0], *keys[4:]]  # same picks, different order: new content
    d2 = drafts.save_draft(engine, p, view.id, swapped, expected_version=d.version)
    with pytest.raises(es.AlreadyEntered):
        confirm(engine, p, view, d2, version=e1.version)
    e2 = confirm(engine, p, view, d2, version=e1.version, replace=True)
    assert e2.current.version == 2 and e2.current.id != e1.current.id
    assert [h.kind for h in e2.history] == ["confirmed", "replaced"]
    assert count(engine, submissions, entry_id=e2.entry_id) == 2
    with transaction(engine) as conn:  # the first version is still there, unchanged
        v1 = conn.execute(
            select(submissions.c.version, submissions.c.inputs_hash).where(
                submissions.c.id == e1.current.id
            )
        ).one()
    assert v1.version == 1


def test_failed_replacement_keeps_the_active_entry(engine, rnd, monkeypatch):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    e1 = confirm(engine, p, view, d)
    d8 = drafts.save_draft(engine, p, view.id, valid_keys(snap, 8), expected_version=d.version)
    with pytest.raises(ValidationFailed):
        confirm(engine, p, view, d8, version=e1.version, replace=True)
    full = drafts.save_draft(
        engine, p, view.id, list(reversed(e1.current.keys)), expected_version=d8.version
    )
    real = es.repo.add_event

    def boom(conn, *a, **kw):
        real(conn, *a, **kw)
        conn.execute(text("SELECT 1/0"))  # fails after the new version was written

    monkeypatch.setattr(es.repo, "add_event", boom)
    with pytest.raises(PersistenceFailed):
        confirm(engine, p, view, full, version=e1.version, replace=True)
    monkeypatch.undo()
    now = es.get_entry(engine, p, view.id)
    assert now.current == e1.current and now.version == e1.version
    assert count(engine, submissions, entry_id=e1.entry_id) == 1
    assert drafts.get_draft(engine, p, view.id).version == full.version  # draft kept


# ------------------------------------------------------------------ withdrawal
def test_withdrawal_and_re_entry(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    e1 = confirm(engine, p, view, d)
    w = es.withdraw_entry(engine, p, view.id, expected_entry_version=e1.version)
    assert w.state == "withdrawn" and w.current is None
    assert count(engine, submissions, entry_id=e1.entry_id) == 1  # history kept
    with pytest.raises(ValidationFailed):
        es.withdraw_entry(engine, p, view.id, expected_entry_version=w.version)
    e2 = confirm(engine, p, view, d, version=w.version)
    assert e2.active and e2.current.version == 2
    assert [h.kind for h in e2.history] == ["confirmed", "withdrawn", "confirmed"]


def test_stale_entry_versions_are_refused(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    e1 = confirm(engine, p, view, d)
    es.withdraw_entry(engine, p, view.id, expected_entry_version=e1.version)
    with pytest.raises(VersionConflict):  # another tab still shows the confirmed entry
        confirm(engine, p, view, d, version=e1.version)


# ------------------------------------------------------------------ deadline and lock
def test_nothing_changes_after_the_deadline_and_lock_counts_active_entries(engine, op):
    view, snap = publish_dev(engine, op, deadline_in=timedelta(seconds=5))
    a, da = ready(engine, view, snap)
    ea = confirm(engine, a, view, da)
    b, db = ready(engine, view, snap)
    eb = confirm(engine, b, view, db)
    es.withdraw_entry(engine, b, view.id, expected_entry_version=eb.version)
    c, dc = ready(engine, view, snap)
    wait_until(engine, view.deadline_at)
    with pytest.raises(RoundClosed):
        confirm(engine, c, view, dc)
    with pytest.raises(RoundClosed):
        confirm(engine, a, view, da, version=ea.version, replace=True)
    with pytest.raises(RoundClosed):
        es.withdraw_entry(engine, a, view.id, expected_entry_version=ea.version)
    res = svc.lock_round(engine, svc.SYSTEM, view.id)
    assert (res.locked_entries, res.designation) == (1, "practice")
    assert es.get_entry(engine, a, view.id).locked


@pytest.fixture
def patient(pg_url):
    """An engine whose lock timeout outlasts the waits in these tests."""
    from diski9.backend.db import BackendDatabaseSettings, make_app_engine

    eng = make_app_engine(
        BackendDatabaseSettings(environment="test", lock_timeout_ms=20000), url=pg_url
    )
    yield eng
    eng.dispose()


def test_waiting_for_the_lock_job_cannot_extend_the_window(engine, op, patient):
    """A confirmation that starts before the deadline but has to wait for another
    transaction holding the round (as the lock job does) re-checks the deadline
    after the wait and is refused once the deadline has passed."""
    view, snap = publish_dev(engine, op, deadline_in=timedelta(seconds=4))
    p, d = ready(engine, view, snap)
    holder = engine.connect()
    trans = holder.begin()
    rounds_repo.lock_round_for_change(holder, view.id)  # FOR UPDATE, like the lock job
    result = []

    def attempt():
        try:
            result.append(confirm(patient, p, view, d))
        except Exception as exc:  # noqa: BLE001
            result.append(exc)

    t = threading.Thread(target=attempt)
    t.start()  # starts (and takes its transaction time) before the deadline
    wait_until(engine, view.deadline_at)
    trans.rollback()
    holder.close()
    t.join(timeout=10)
    assert isinstance(result[0], RoundClosed)
    assert count(engine, entries, user_id=p.user_id) == 0


def test_waiting_for_another_device_cannot_extend_the_window(engine, op, patient):
    view, snap = publish_dev(engine, op, deadline_in=timedelta(seconds=4))
    p, d = ready(engine, view, snap)
    e = confirm(engine, p, view, d)
    holder = engine.connect()
    trans = holder.begin()
    holder.execute(select(entries).where(entries.c.id == e.entry_id).with_for_update())
    result = []
    t = threading.Thread(
        target=lambda: result.append(
            _try(lambda: es.withdraw_entry(patient, p, view.id, expected_entry_version=e.version))
        )
    )
    t.start()
    wait_until(engine, view.deadline_at)
    trans.rollback()
    holder.close()
    t.join(timeout=10)
    assert isinstance(result[0], RoundClosed)
    assert es.get_entry(engine, p, view.id).active


def _try(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return exc


# ------------------------------------------------------------------ concurrency
def _race(*fns):
    barrier = threading.Barrier(len(fns))
    out = [None] * len(fns)

    def run(i, fn):
        barrier.wait()
        out[i] = _try(fn)

    ts = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def test_simultaneous_confirmations_from_two_devices(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    out = _race(lambda: confirm(engine, p, view, d), lambda: confirm(engine, p, view, d))
    ok = [o for o in out if isinstance(o, es.EntryView)]
    assert len(ok) == 1, out
    assert all(isinstance(o, VersionConflict | es.AlreadyEntered) for o in out if o not in ok)
    assert count(engine, entries, user_id=p.user_id) == 1
    assert count(engine, submissions, user_id=p.user_id) == 1


def test_concurrent_replacements_and_withdrawal(engine, rnd):
    view, snap = rnd
    p, d = ready(engine, view, snap)
    e = confirm(engine, p, view, d)
    out = _race(
        lambda: confirm(engine, p, view, d, version=e.version, replace=True),
        lambda: confirm(engine, p, view, d, version=e.version, replace=True),
        lambda: es.withdraw_entry(engine, p, view.id, expected_entry_version=e.version),
    )
    ok = [o for o in out if isinstance(o, es.EntryView)]
    assert len(ok) == 1 and all(isinstance(o, VersionConflict) for o in out if o not in ok)
    final = es.get_entry(engine, p, view.id)
    assert final == ok[0]
    with transaction(engine) as conn:  # exactly one current version or none
        row = conn.execute(select(entries).where(entries.c.id == e.entry_id)).one()
    assert (row.current_submission_id is None) == (final.state == "withdrawn")


# ------------------------------------------------------------------ access
def test_guests_suspended_and_other_accounts(engine, rnd):
    view, snap = rnd
    with pytest.raises(AuthorizationError):
        es.confirm_entry(
            engine, GUEST, view.id, draft_version=1, expected_entry_version=0, idempotency_key=key()
        )
    with pytest.raises(AuthorizationError):
        es.get_entry(engine, GUEST, view.id)
    a, da = ready(engine, view, snap)
    confirm(engine, a, view, da)
    b = principal(engine)
    assert es.get_entry(engine, b, view.id).state == "none"
    s, ds = ready(engine, view, snap)
    with transaction(engine) as conn:
        conn.execute(update(users).where(users.c.id == s.user_id).values(status="suspended"))
    with pytest.raises(AccountInactive):
        confirm(engine, s, view, ds)


def test_private_analysis_is_never_read(engine, rnd, monkeypatch):
    from diski9.backend.services import your_view

    def forbidden(*a, **kw):
        raise AssertionError("Your View must not be read by entries")

    for name in ("get_your_view", "get_many", "_row", "_resolve"):
        monkeypatch.setattr(your_view, name, forbidden)
    view, snap = rnd
    p, d = ready(engine, view, snap)
    assert confirm(engine, p, view, d).active
