"""Phase 6C.3 checkpoint refinements on real PostgreSQL: Your View per analytical
context, guest-work adoption, snapshot construction age, the Friday schedule
(D-11 revision), development-round isolation and competitive versus official
classification."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError
from svc_helpers import principal, publish_dev, unique, valid_keys

from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, migrate, transaction
from diski9.backend.db.schema import (
    championship_series,
    entries,
    round_schedules,
    rounds,
    your_view_adjustments,
)
from diski9.backend.devdata import dev_snapshot
from diski9.backend.services import adoption, drafts
from diski9.backend.services import rounds as svc
from diski9.backend.services import your_view as yv
from diski9.backend.services.common import NotFound, PersistenceFailed, VersionConflict
from diski9.challenge.config import BROAD60_432_V1  # explicit: v1 behaviour (A3 4A)


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture(scope="module")
def rnd(engine, op):
    return publish_dev(engine, op)


def nums(home=0.0, away=0.0) -> dict:
    s = yv.zero_state()
    s["manual"] = {"home": home, "away": away}
    return s


def live_for(snap, fid):
    """A live context whose baseline equals the frozen one (identical baselines)."""
    f = snap.fixture(fid)
    h, a = (round(x, 2) for x in f.estimated_goals)
    return yv.LiveContext(fid, f"1.0|{fid}|{h:.2f}|{a:.2f}")


# ------------------------------------------------------------ contextual Your View
def test_live_and_frozen_states_coexist_and_reset_independently(engine, rnd):
    view, snap = rnd
    fid = snap.fixtures[0].fixture_id
    p = principal(engine)
    frozen, live = yv.RoundContext(view.id, fid), live_for(snap, fid)
    f1 = yv.save_your_view(engine, p, frozen, nums(0.2, -0.1), expected_version=0)
    l1 = yv.save_your_view(engine, p, live, nums(0.1, -0.05), expected_version=0)
    assert yv.get_your_view(engine, p, frozen).state == nums(0.2, -0.1)
    assert yv.get_your_view(engine, p, live).state == nums(0.1, -0.05)
    yv.reset_your_view(engine, p, live, expected_version=l1.version)
    assert yv.get_your_view(engine, p, live).status == yv.NONE
    assert yv.get_your_view(engine, p, frozen) == f1  # untouched
    yv.reset_your_view(engine, p, frozen, expected_version=f1.version)
    assert yv.get_your_view(engine, p, frozen).status == yv.NONE


def test_identical_baselines_do_not_make_contexts_interchangeable(engine, rnd):
    view, snap = rnd
    fid = snap.fixtures[1].fixture_id
    p = principal(engine)
    live = live_for(snap, fid)
    assert live.model_context == yv.resolved_context(engine, yv.RoundContext(view.id, fid))
    yv.save_your_view(engine, p, live, nums(0.3), expected_version=0)
    assert yv.get_your_view(engine, p, yv.RoundContext(view.id, fid)).status == yv.NONE


def test_version_protection_is_per_context(engine, rnd):
    view, snap = rnd
    fid = snap.fixtures[2].fixture_id
    p = principal(engine)
    frozen, live = yv.RoundContext(view.id, fid), live_for(snap, fid)
    yv.save_your_view(engine, p, frozen, nums(0.1), expected_version=0)
    yv.save_your_view(engine, p, frozen, nums(0.2), expected_version=1)
    yv.save_your_view(engine, p, live, nums(0.4), expected_version=0)  # live starts at 0
    with pytest.raises(VersionConflict):
        yv.save_your_view(engine, p, frozen, nums(0.9), expected_version=1)
    assert yv.get_your_view(engine, p, live).version == 1


def test_development_rounds_with_reused_fixture_ids_do_not_share_state(engine, op, rnd):
    view, snap = rnd
    other, other_snap = publish_dev(engine, op)  # same seed: same fixture IDs
    fid = snap.fixtures[3].fixture_id
    assert other_snap.fixtures[3].fixture_id == fid
    p = principal(engine)
    yv.save_your_view(engine, p, yv.RoundContext(view.id, fid), nums(0.5), expected_version=0)
    assert yv.get_your_view(engine, p, yv.RoundContext(other.id, fid)).status == yv.NONE


def test_round_context_is_resolved_by_the_server(engine, op, rnd):
    view, snap = rnd
    p = principal(engine)
    with pytest.raises(NotFound):  # not on this snapshot
        yv.get_your_view(engine, p, yv.RoundContext(view.id, 42))
    with transaction(engine) as conn:
        now = db_now(conn)
    unpublished = svc.create_round(
        engine,
        op,
        code=unique("dev-np"),
        window_start=now,
        window_end=now + timedelta(days=2),
        development=True,
    )
    with pytest.raises(NotFound):
        yv.get_your_view(engine, p, yv.RoundContext(unpublished.id, snap.fixtures[0].fixture_id))
    # the database also refuses a frozen row for a fixture outside the snapshot
    with pytest.raises(DBAPIError), transaction(engine) as conn:
        sid = conn.execute(
            text("SELECT id FROM app.round_snapshots WHERE round_id = :r"), {"r": view.id}
        ).scalar_one()
        conn.execute(
            insert(your_view_adjustments).values(
                user_id=p.user_id,
                fixture_id=42,
                context_kind="round",
                snapshot_id=sid,
                model_context="1.0|42|1.00|1.00",
                state=yv.zero_state(),
                version=1,
            )
        )


def test_contexts_are_private_per_account(engine, rnd):
    view, snap = rnd
    fid = snap.fixtures[4].fixture_id
    a, b = principal(engine), principal(engine)
    for ctx in (yv.RoundContext(view.id, fid), live_for(snap, fid)):
        yv.save_your_view(engine, a, ctx, nums(0.25), expected_version=0)
        assert yv.get_your_view(engine, b, ctx).status == yv.NONE


def test_existing_rows_are_preserved_as_unassigned_through_the_migration(fresh_url):
    """Rows saved before app_0004 cannot be told apart (live or frozen), so they are
    kept unchanged as ``unassigned`` and never applied; downgrade and re-upgrade keep
    them. Runs on a separate database: the session database may hold Phase 6C.4
    settlement data, whose downgrade is refused by design."""
    pg_url = fresh_url
    migrate.upgrade(pg_url)
    engine = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)
    p = principal(engine)
    migrate.downgrade(pg_url, "app_0003")
    try:
        with transaction(engine) as conn:
            conn.execute(
                text(
                    "INSERT INTO app.your_view_adjustments (user_id, fixture_id, model_context, "
                    "state, version) VALUES (:u, 777, '1.0|777|1.20|0.90', CAST(:s AS jsonb), 3)"
                ),
                {
                    "u": p.user_id,
                    "s": '{"context": {"home": 0.2, "away": 0}, '
                    '"cats": {}, "manual": {"home": 0, "away": 0}}',
                },
            )
    finally:
        migrate.upgrade(pg_url)
    with transaction(engine) as conn:
        row = conn.execute(
            select(your_view_adjustments).where(your_view_adjustments.c.user_id == p.user_id)
        ).one()
    assert (row.context_kind, row.snapshot_id, row.version, row.model_context) == (
        "unassigned",
        None,
        3,
        "1.0|777|1.20|0.90",
    )
    assert row.state["context"]["home"] == 0.2
    live = yv.LiveContext(777, "1.0|777|1.20|0.90")  # same stamp, still not applied
    assert yv.get_your_view(engine, p, live).status == yv.NONE
    yv.save_your_view(engine, p, live, nums(0.1), expected_version=0)  # coexists
    with transaction(engine) as conn:
        kinds = sorted(
            conn.execute(
                select(your_view_adjustments.c.context_kind).where(
                    your_view_adjustments.c.user_id == p.user_id
                )
            ).scalars()
        )
    assert kinds == ["live", "unassigned"]
    engine.dispose()


# ------------------------------------------------------------ guest adoption
def stamp(fid):
    return f"1.0|{fid}|1.45|0.98"


def guest_views(view, snap, *fids, live=(), state=None):
    out = []
    for fid in fids:
        out.append(
            {
                "kind": "round",
                "round_id": str(view.id),
                "fixture_id": fid,
                "stamp": yv.frozen_context(snap, fid, view.model_version),
                "state": state or nums(0.2),
            }
        )
    for fid in live:
        out.append(
            {"kind": "live", "fixture_id": fid, "stamp": stamp(fid), "state": state or nums(-0.1)}
        )
    return out


def guest_draft(view, snap, n=3, fingerprint=None):
    return {
        "round_id": str(view.id),
        "fingerprint": fingerprint or snap.fingerprint,
        "selections": [
            f"{k['fixture_id']}|{k['market']}|{k['outcome']}" for k in valid_keys(snap, n)
        ],
    }


def _adopt(engine, p, draft, views, replace_conflicts=False):
    plan = adoption.plan_adoption(engine, p, guest_draft=draft, guest_views=views, live_stamp=stamp)
    res = adoption.adopt(
        engine,
        p,
        plan,
        guest_draft=draft,
        guest_views=views,
        live_stamp=stamp,
        replace_conflicts=replace_conflicts,
    )
    return plan, res


def test_adopt_portfolio_only_and_never_confirm(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    plan, res = _adopt(engine, p, guest_draft(view, snap), [])
    assert [i.status for i in plan.items] == ["ready"] and len(res.saved) == 1
    assert len(drafts.get_draft(engine, p, view.id).selections) == 3
    with transaction(engine) as conn:
        assert conn.execute(select(entries).where(entries.c.user_id == p.user_id)).first() is None


def test_adopt_your_view_only_live_and_frozen(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    f0, f1 = snap.fixtures[0].fixture_id, snap.fixtures[1].fixture_id
    plan, res = _adopt(engine, p, None, guest_views(view, snap, f0, live=[555]))
    assert sorted(i.kind for i in plan.items) == ["live", "round"] and len(res.saved) == 2
    assert yv.get_your_view(engine, p, yv.RoundContext(view.id, f0)).state == nums(0.2)
    assert yv.get_your_view(engine, p, yv.LiveContext(555, stamp(555))).state == nums(-0.1)
    assert yv.get_your_view(engine, p, yv.RoundContext(view.id, f1)).status == yv.NONE


def test_adopt_both_and_report_what_could_not_be_adopted(engine, op, rnd):
    view, snap = rnd
    old, old_snap = publish_dev(engine, op, seed=5)
    p = principal(engine)
    f0 = snap.fixtures[0].fixture_id
    views = guest_views(view, snap, f0, live=[556])
    views.append(
        {**views[0], "fixture_id": snap.fixtures[1].fixture_id, "stamp": "1.0|1|9.99|9.99"}
    )  # made against another baseline
    views.append(
        {"kind": "live", "fixture_id": 557, "stamp": "1.0|557|0.50|0.50", "state": nums(0.1)}
    )
    views.append(
        {
            "kind": "round",
            "round_id": str(view.id),
            "fixture_id": f0 + 999,
            "stamp": "x",
            "state": nums(0.1),
        }
    )
    bad = nums(0.1)
    bad["context"]["home"] = 5.0
    views.append(
        {
            **views[0],
            "fixture_id": snap.fixtures[2].fixture_id,
            "state": bad,
            "stamp": yv.frozen_context(snap, snap.fixtures[2].fixture_id, "1.0"),
        }
    )
    draft = guest_draft(old, old_snap)
    draft["fingerprint"] = snap.fingerprint  # claims the current snapshot
    plan, res = _adopt(engine, p, draft, views)
    reasons = sorted(i.reason for i in plan.rejected)
    assert len(res.saved) == 2 and len(plan.rejected) == 5
    assert adoption.REASONS["context_changed"] in reasons
    assert adoption.REASONS["other_round"] in reasons
    assert adoption.REASONS["invalid_values"] in reasons
    assert drafts.get_draft(engine, p, old.id).selections == ()


def test_wrong_round_and_closed_round_drafts_are_not_adopted(engine, op, rnd):
    view, snap = rnd
    p = principal(engine)
    stale = guest_draft(view, snap, fingerprint="0" * 16)
    plan, res = _adopt(engine, p, stale, [])
    assert plan.items[0].reason == adoption.REASONS["other_round"] and res.saved == ()
    closed, csnap = publish_dev(engine, op, deadline_in=timedelta(seconds=2))
    from svc_helpers import wait_until

    wait_until(engine, closed.deadline_at)
    plan, _ = _adopt(engine, p, guest_draft(closed, csnap), [])
    assert plan.items[0].reason == adoption.REASONS["round_closed"]


def test_existing_account_work_is_kept_unless_replacement_is_chosen(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    keys = valid_keys(snap, 5)
    mine = drafts.save_draft(engine, p, view.id, keys[3:5], expected_version=0)
    f0 = snap.fixtures[0].fixture_id
    yv.save_your_view(engine, p, yv.RoundContext(view.id, f0), nums(0.6), expected_version=0)
    draft, views = guest_draft(view, snap), guest_views(view, snap, f0)
    plan, res = _adopt(engine, p, draft, views, replace_conflicts=False)
    assert sorted(i.status for i in plan.items) == ["conflict", "conflict"]
    assert res.saved == () and len(res.kept_account) == 2
    assert drafts.get_draft(engine, p, view.id) == mine
    assert yv.get_your_view(engine, p, yv.RoundContext(view.id, f0)).state == nums(0.6)
    _, res = _adopt(engine, p, draft, views, replace_conflicts=True)
    assert len(res.saved) == 2
    assert len(drafts.get_draft(engine, p, view.id).selections) == 3
    assert yv.get_your_view(engine, p, yv.RoundContext(view.id, f0)).state == nums(0.2)
    plan, res = _adopt(engine, p, draft, views)  # adopting again changes nothing
    assert sorted(i.status for i in plan.items) == ["same", "same"] and res.saved == ()


def test_account_change_between_review_and_adoption_saves_nothing(engine, rnd):
    view, snap = rnd
    p = principal(engine)
    f0 = snap.fixtures[0].fixture_id
    draft, views = guest_draft(view, snap), guest_views(view, snap, f0)
    plan = adoption.plan_adoption(engine, p, guest_draft=draft, guest_views=views, live_stamp=stamp)
    drafts.save_draft(engine, p, view.id, valid_keys(snap, 1), expected_version=0)  # phone
    with pytest.raises(adoption.AdoptionStale):
        adoption.adopt(
            engine,
            p,
            plan,
            guest_draft=draft,
            guest_views=views,
            live_stamp=stamp,
            replace_conflicts=True,
        )
    assert yv.get_your_view(engine, p, yv.RoundContext(view.id, f0)).status == yv.NONE
    assert len(drafts.get_draft(engine, p, view.id).selections) == 1


def test_a_failed_adoption_write_saves_nothing(engine, rnd, monkeypatch):
    view, snap = rnd
    p = principal(engine)
    f0 = snap.fixtures[0].fixture_id
    draft, views = guest_draft(view, snap), guest_views(view, snap, f0)
    plan = adoption.plan_adoption(engine, p, guest_draft=draft, guest_views=views, live_stamp=stamp)
    real = yv.write_in

    def broken(conn, *a, **kw):
        real(conn, *a, **kw)
        conn.execute(text("SELECT 1/0"))  # fails after the Your View write

    monkeypatch.setattr(yv, "write_in", broken)
    with pytest.raises(PersistenceFailed):
        adoption.adopt(
            engine,
            p,
            plan,
            guest_draft=draft,
            guest_views=views,
            live_stamp=stamp,
            replace_conflicts=False,
        )
    monkeypatch.undo()
    assert drafts.get_draft(engine, p, view.id).selections == ()  # draft rolled back too
    assert yv.get_your_view(engine, p, yv.RoundContext(view.id, f0)).status == yv.NONE


def test_adoption_never_touches_another_account(engine, rnd):
    view, snap = rnd
    a, b = principal(engine), principal(engine)
    drafts.save_draft(engine, a, view.id, valid_keys(snap, 2), expected_version=0)
    _adopt(engine, b, guest_draft(view, snap, 4), guest_views(view, snap, live=[558]))
    assert len(drafts.get_draft(engine, a, view.id).selections) == 2
    assert yv.get_your_view(engine, a, yv.LiveContext(558, stamp(558))).status == yv.NONE


# ------------------------------------------------------------ snapshot construction age
class _R:
    status, is_development, code = "draft", True, "dev-x"


def _problem(snap, now, limit=timedelta(hours=1)):
    r = _R()
    r.code = snap.round_id
    r.window_start_at, r.window_end_at = snap.window

    class S:
        config_version = snap.config_version

    return svc._publication_problem(r, S, snap, "development", now, limit)[0]


def test_construction_age_boundaries():
    from datetime import UTC, datetime

    t = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)
    snap = dev_snapshot("dev-age", t, t + timedelta(hours=10), config=BROAD60_432_V1)
    assert _problem(snap, t) is None
    assert _problem(snap, t + timedelta(hours=1)) is None  # exactly the limit
    assert "too old" in _problem(snap, t + timedelta(hours=1, microseconds=1))
    assert "future" in _problem(snap, t - timedelta(microseconds=1))


def test_construction_age_configuration(monkeypatch):
    monkeypatch.delenv(svc.MAX_SNAPSHOT_AGE_ENV, raising=False)
    assert svc.max_snapshot_age() == timedelta(hours=1)
    monkeypatch.setenv(svc.MAX_SNAPSHOT_AGE_ENV, "30")
    assert svc.max_snapshot_age() == timedelta(minutes=30)
    for bad in ("0", "181", "abc", "-5"):
        monkeypatch.setenv(svc.MAX_SNAPSHOT_AGE_ENV, bad)
        with pytest.raises(ValueError):
            svc.max_snapshot_age()


def test_a_fresh_snapshot_with_stale_odds_is_refused(engine, op):
    """Construction age and odds freshness are separate: a snapshot built a moment
    ago whose quotes are 24 hours and one second old does not open."""
    from diski9.challenge.structured import make_outcome

    with transaction(engine) as conn:
        now = db_now(conn)
    snap = dev_snapshot(unique("dev-st"), now, now + timedelta(hours=3), config=BROAD60_432_V1)
    old = now - timedelta(hours=24, seconds=1)
    outs = tuple(
        make_outcome(
            o.fixture_id,
            o.market,
            o.outcome,
            o.market_probability,
            o.reference_odds,
            o.model_probability,
            o.bookmaker_groups,
            old,
            o.league_id,
        )
        for o in snap.outcomes
    )
    stale = replace(snap, outcomes=outs)
    v = svc.create_round(
        engine,
        op,
        code=stale.round_id,
        window_start=stale.window[0],
        window_end=stale.window[1],
        development=True,
    )
    with pytest.raises(svc.PublicationRefused) as exc:
        svc.publish_round(engine, op, v.id, stale, source="development")
    assert exc.value.details["report"]["eligible_outcomes"] == 0
    edge = replace(
        snap,
        outcomes=tuple(
            make_outcome(
                o.fixture_id,
                o.market,
                o.outcome,
                o.market_probability,
                o.reference_odds,
                o.model_probability,
                o.bookmaker_groups,
                now - timedelta(hours=24),
                o.league_id,
            )
            for o in snap.outcomes
        ),
    )
    assert edge.opening_report().opens  # exactly 24 hours is still fresh


def test_published_snapshot_never_expires(engine, op):
    view, snap = publish_dev(engine, op)
    later = svc.published_snapshot(engine, view.id)
    assert later.fingerprint == snap.fingerprint  # loading applies no age rule


# ------------------------------------------------------------ schedule, series, terminology
def test_friday_publication_schedule_is_the_default(engine, op):
    with transaction(engine) as conn:
        latest = conn.execute(
            select(round_schedules)
            .where(round_schedules.c.code == "weekend")
            .order_by(round_schedules.c.version.desc())
            .limit(1)
        ).one()
    assert latest.publish_rule == {
        "weekday": "friday",
        "time": "08:00",
        "tz": "Africa/Johannesburg",
    }
    assert latest.deadline_buffer_minutes == 15 and latest.settle_cutoff_hours == 48
    view, _ = publish_dev(engine, op)
    with transaction(engine) as conn:
        assert (
            conn.execute(select(rounds.c.schedule_id).where(rounds.c.id == view.id)).scalar_one()
            == latest.id
        )
    start, end = svc.schedule_window(engine, 2026, 48)  # window rule unchanged
    assert (start.weekday(), end.weekday()) == (4, 1)


def test_development_rounds_cannot_join_the_official_series(engine, op):
    view, _ = publish_dev(engine, op)
    with transaction(engine) as conn:
        official = conn.execute(
            select(championship_series.c.id).where(championship_series.c.code == "official")
        ).scalar_one()
    with pytest.raises(DBAPIError), transaction(engine) as conn:
        conn.execute(rounds.update().where(rounds.c.id == view.id).values(series_id=official))


def test_competitive_classification_is_not_official_championship_membership(engine):
    from pg_helpers import confirm, make_round, make_user
    from svc_helpers import wait_until

    with transaction(engine) as conn:
        rid, snap, fids = make_round(conn, deadline_in=timedelta(seconds=3))
        for _ in range(5):
            uid = make_user(conn)
            confirm(conn, rid, snap, fids, uid)
    wait_until(engine, svc.get_round(engine, rid).deadline_at)
    res = svc.lock_round(engine, svc.SYSTEM, rid)
    assert res.round.designation == "championship"  # legacy stored name
    assert res.round.classification == "competitive"
    assert res.round.series == "beta"
    assert res.round.counts_toward_official_championship is False
