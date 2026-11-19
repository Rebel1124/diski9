"""Phase 6C.3 Stage G: application-level regression tests that drive the Dash page
code (``app.challenge.persist``, ``pages``, ``app.lab_context``) against the real
competition database, for the defects found in Stage F and the most recent locked
entry. The principal is injected the way the request middleware sets it (no
browser); the services, transactions and triggers are real."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from svc_helpers import principal, publish_dev, valid_keys, wait_until

from diski9.app import lab_context
from diski9.app.challenge import pages, persist
from diski9.app.challenge.service import ChallengeService
from diski9.backend.auth import web
from diski9.backend.auth.permissions import GUEST
from diski9.backend.services import drafts
from diski9.backend.services import entries as es
from diski9.backend.services import rounds as rsvc

SAST = ZoneInfo("Africa/Johannesburg")


def text(component) -> str:
    if component is None:
        return ""
    if isinstance(component, str | int | float):
        return str(component)
    if isinstance(component, list | tuple):
        return " ".join(text(c) for c in component)
    return text(getattr(component, "children", None))


def local(dt) -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.astimezone(SAST).strftime("%a %d %b, %H:%M")


class PinnedBackend(persist.Backend):
    """The real Backend, pinned to one round (other test modules publish rounds in
    the same database, so "the current round" is chosen explicitly here; the
    current-round rule itself is tested in ``test_backend_rounds``)."""

    def __init__(self, engine, round_id):
        super().__init__(engine, show_development=True, ttl=0)
        self.round_id = round_id

    def published(self):
        return rsvc.get_round(self.engine, self.round_id), rsvc.published_snapshot(
            self.engine, self.round_id
        )


def make_service(engine, round_id, detail=None):
    data = SimpleNamespace(
        clock=lambda: datetime.now(UTC),
        detail=detail or (lambda fid: (None, None, None)),
        snapshot=lambda: SimpleNamespace(cache_calculated_at=datetime(2026, 11, 19, 6, tzinfo=UTC)),
    )
    return ChallengeService(data, backend=PinnedBackend(engine, round_id))


@pytest.fixture
def as_user(monkeypatch):
    """Sign in as a principal for the page code (``None`` = guest)."""

    def sign_in(p):
        monkeypatch.setattr(web, "current_principal", lambda: p or GUEST)
        monkeypatch.setattr(web, "owner_tag", lambda: str(p.user_id)[:12] if p else "guest")

    return sign_in


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture(scope="module")
def rnd(engine, op):
    return publish_dev(engine, op, deadline_in=timedelta(hours=3), seed=31)


def keys_of(snap, n):
    return [f"{k['fixture_id']}|{k['market']}|{k['outcome']}" for k in valid_keys(snap, n)]


# ------------------------------------------------------------------ hydration and guest work
def test_guest_work_is_never_replaced_before_the_keep_or_discard_choice(engine, rnd, as_user):
    view, snap = rnd
    p = principal(engine)
    drafts.save_draft(engine, p, view.id, valid_keys(snap, 2), expected_version=0)
    service = make_service(engine, view.id)
    guest_state = {"selections": keys_of(snap, 4)[2:4], "fp": snap.fingerprint}
    as_user(p)
    assert persist.has_guest_work(guest_state)
    assert persist.hydrate(service, guest_state) is None  # nothing replaced
    forced = persist.hydrate(service, guest_state, force=True)  # after an explicit choice
    assert forced["selections"] == keys_of(snap, 2)


def test_unsaved_changes_survive_navigation_and_saved_work_is_restored(engine, rnd, as_user):
    view, snap = rnd
    p = principal(engine)
    service = make_service(engine, view.id)
    as_user(p)
    s = persist.hydrate(service, {})
    assert s["selections"] == [] and s["acct"]["dv"] == 0
    s["selections"] = keys_of(snap, 3)
    s, flash = persist.save_selections(service, s)
    assert flash is None and s["acct"]["status"] == "saved" and s["acct"]["dv"] == 1
    # A fresh tab (new page load) restores the saved draft from the database.
    assert persist.hydrate(service, {})["selections"] == keys_of(snap, 3)
    # Unsaved (dirty) work in this tab is kept, not replaced by the database copy.
    s["selections"] = keys_of(snap, 4)
    s["acct"]["dirty"] = True
    assert persist.hydrate(service, s)["selections"] == keys_of(snap, 4)


def test_stale_device_gets_a_conflict_and_never_silently_takes_the_other_draft(
    engine, rnd, as_user
):
    view, snap = rnd
    p = principal(engine)
    service = make_service(engine, view.id)
    as_user(p)
    dev1, dev2 = persist.hydrate(service, {}), persist.hydrate(service, {})
    dev1["selections"] = keys_of(snap, 2)
    dev1, _ = persist.save_selections(service, dev1)
    dev2["selections"] = keys_of(snap, 5)[2:5]  # works on its own (stale) version
    dev2, flash = persist.save_selections(service, dev2)
    assert flash["recover"] == "reload" and dev2["acct"]["status"] == "conflict"
    assert dev2["selections"] == keys_of(snap, 5)[2:5]  # its own work is still shown
    assert drafts.get_draft(engine, p, view.id).keys == keys_of(snap, 2)  # not overwritten
    reloaded = persist.hydrate(service, dev2, force=True)  # "Load latest saved portfolio"
    assert reloaded["selections"] == keys_of(snap, 2)


def test_overlapping_saves_from_one_tab_keep_the_newest(engine, rnd, as_user):
    view, snap = rnd
    p = principal(engine)
    service = make_service(engine, view.id)
    as_user(p)
    s = persist.hydrate(service, {})
    newer = dict(s, selections=keys_of(snap, 3), acct=dict(s["acct"]))
    older = dict(s, selections=keys_of(snap, 1), acct=dict(s["acct"]))
    w_old, w_new = persist.writer(s), persist.writer(s)  # older request started first
    d = drafts.save_draft(engine, p, view.id, newer["selections"], expected_version=0,
                          writer=w_new)  # fmt: skip
    late = drafts.save_draft(engine, p, view.id, older["selections"], expected_version=0,
                             writer=w_old)  # fmt: skip
    assert late.keys == d.keys == keys_of(snap, 3)  # superseded request wrote nothing


def test_account_switch_in_the_same_tab_clears_the_other_accounts_work(engine, rnd, as_user):
    view, snap = rnd
    a, b = principal(engine), principal(engine)
    service = make_service(engine, view.id)
    as_user(a)
    s = persist.hydrate(service, {})
    s["selections"] = keys_of(snap, 3)
    s, _ = persist.save_selections(service, s)
    as_user(b)
    sb = persist.hydrate(service, s)
    assert sb["selections"] == [] and sb["acct"]["owner"] != s["acct"]["owner"]


# ------------------------------------------------------------------ Match Lab context
def _detail(fid):
    return (
        {
            "goal_model": {
                "available": True,
                "estimated_goals": {"home": 9.99, "away": 9.99},  # "latest" values
                "probabilities": {},
            }
        },
        None,
        None,
    )


def test_match_lab_frozen_context_uses_the_snapshot_baseline(engine, rnd):
    view, snap = rnd
    service = make_service(engine, view.id, detail=_detail)
    fx = snap.fixtures[0]
    ctx = lab_context.resolve(service, service.data, fx.fixture_id, "challenge")
    assert ctx.kind == "round" and ctx.key == f"r:{view.code}:{fx.fixture_id}"
    assert ctx.round_id == view.id and ctx.frozen_at == snap.snapshot_at
    eg = ctx.r["goal_model"]["estimated_goals"]
    assert (eg["home"], eg["away"]) == fx.estimated_goals  # frozen, not 9.99
    live = lab_context.resolve(service, service.data, fx.fixture_id, "all")
    assert live.kind == "live" and live.key == str(fx.fixture_id)
    assert live.r["goal_model"]["estimated_goals"]["home"] == 9.99
    # A fixture not on the round falls back to the latest data even from the challenge.
    other = lab_context.resolve(service, service.data, 123456789, "challenge")
    assert other.kind == "live"


# ------------------------------------------------------------------ most recent locked entry
@pytest.fixture(scope="module")
def locked_world(engine, op):
    short, short_snap = publish_dev(engine, op, deadline_in=timedelta(seconds=5), seed=41)
    a, b, c = principal(engine), principal(engine), principal(engine)
    for p in (a, b):
        d = drafts.save_draft(engine, p, short.id, valid_keys(short_snap, 9), expected_version=0)
        e = es.confirm_entry(engine, p, short.id, draft_version=d.version,
                             expected_entry_version=0, idempotency_key=uuid.uuid4().hex)  # fmt: skip
    es.withdraw_entry(engine, b, short.id, expected_entry_version=e.version)
    wait_until(engine, short.deadline_at)
    current, current_snap = publish_dev(engine, op, deadline_in=timedelta(hours=3), seed=43)
    return SimpleNamespace(short=short, short_snap=short_snap, current=current,
                           current_snap=current_snap, a=a, b=b, c=c)  # fmt: skip


def body_text(engine, round_id, state=None):
    service = make_service(engine, round_id)
    s = persist.hydrate(service, state or {}) or {}
    return text(pages.my_challenge_body(service, s, local)), service, s


def test_my_challenge_shows_the_locked_entry_beside_another_open_round(
    engine, locked_world, as_user
):
    w = locked_world
    as_user(w.a)
    out, _, _ = body_text(engine, w.current.id)
    assert "Most recent locked entry" in out and w.short.code in out
    assert "Deadline passed" in out and "waiting to be locked" in out  # lock not run yet
    assert "Show the nine predictions in" in out
    assert "40 / 30 / 20 / 10" in out and "Not available yet" in out  # no results invented
    assert "Withdraw" not in out.split("Most recent locked entry")[1]
    # Frozen odds and the original nine predictions from the stored submission.
    sub = es.get_entry(engine, w.a, w.short.id).current
    for s in sub.selections:
        assert s["consensus_odds"] in out
    rsvc.lock_round(engine, rsvc.SYSTEM, w.short.id)
    out, _, _ = body_text(engine, w.current.id)
    assert "This entry is locked. It cannot be edited, replaced or withdrawn." in out


def test_current_round_draft_changes_do_not_alter_the_locked_card(engine, locked_world, as_user):
    w = locked_world
    as_user(w.a)
    before, service, s = body_text(engine, w.current.id)
    s["selections"] = keys_of(w.current_snap, 4)
    s, _ = persist.save_selections(service, s)
    after = text(pages.my_challenge_body(service, s, local)).split("Most recent locked entry")[1]
    assert (
        before.split("Most recent locked entry")[1].split("Championship")[0]
        == after.split("Championship")[0]
    )


def test_locked_round_shown_as_current_is_not_duplicated(engine, locked_world, as_user):
    w = locked_world
    as_user(w.a)
    out, _, _ = body_text(engine, w.short.id)
    assert "Most recent locked entry" not in out  # the main card already shows it
    assert w.short.code in out


def test_withdrawn_guest_and_other_accounts_see_no_locked_entry(engine, locked_world, as_user):
    w = locked_world
    for p in (w.b, w.c, None):  # withdrawn, never entered, guest
        as_user(p)
        out, _, _ = body_text(engine, w.current.id)
        assert "Most recent locked entry" not in out
        assert w.short.code not in out


def test_current_round_after_the_deadline_says_deadline_passed_until_locked(engine, op, as_user):
    view, snap = publish_dev(engine, op, deadline_in=timedelta(seconds=4), seed=47)
    p = principal(engine)
    d = drafts.save_draft(engine, p, view.id, valid_keys(snap, 9), expected_version=0)
    es.confirm_entry(engine, p, view.id, draft_version=d.version, expected_entry_version=0,
                     idempotency_key=uuid.uuid4().hex)  # fmt: skip
    wait_until(engine, view.deadline_at)
    as_user(p)
    out, _, _ = body_text(engine, view.id)
    assert "Deadline passed" in out and "lock pending" in out
    rsvc.lock_round(engine, rsvc.SYSTEM, view.id)
    out, _, _ = body_text(engine, view.id)
    assert "Your entry is locked." in out and "lock pending" not in out
