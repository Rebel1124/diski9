"""Phase 6C.3 Stage B: rounds, publication with frozen snapshots, and lock, on real
PostgreSQL. Entries for the lock tests are written through the repositories
(``pg_helpers.confirm``) because the confirmation service is Stage E."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pg_helpers import confirm, make_round, make_user, unique
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from svc_helpers import principal, publish_dev, wait_until, weekend_config

from diski9.backend.auth.permissions import AuthorizationError
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    designations,
    entries,
    entry_events,
    job_runs,
    portfolio_drafts,
    round_snapshots,
    rounds,
    snapshot_fixtures,
    snapshot_offers,
)
from diski9.backend.devdata import dev_snapshot
from diski9.backend.repositories import portfolios
from diski9.backend.services import rounds as svc
from diski9.backend.services import snapshots
from diski9.backend.services.common import LockRefused, PublicationRefused, ValidationFailed
from diski9.challenge.config import (
    BROAD60_432_V1,  # explicit: v1 behaviour (A3 4A)
)
from diski9.challenge.roundsheet import SnapshotKind, snapshot_from_research_pool
from diski9.challenge.structured import make_outcome
from tests.test_app import populated

POOL = Path(__file__).resolve().parents[2] / "docs/research/weekly_challenge_risk/pool_weekend.json"


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _now(engine):
    with transaction(engine) as conn:
        return db_now(conn)


def _draft_round(engine, op, snap):
    return svc.create_round(
        engine,
        op,
        code=snap.round_id,
        window_start=snap.window[0],
        window_end=snap.window[1],
        development=snap.round_id.startswith("dev-"),
    )


def _fresh(engine, **kw):
    now = _now(engine)
    code = unique("dev-p")
    return dev_snapshot(code, now, now + timedelta(hours=3), **kw)


# ------------------------------------------------------------------ authorisation
def test_participants_cannot_create_or_publish(engine):
    p = principal(engine)
    snap = _fresh(engine)
    with pytest.raises(AuthorizationError):
        _draft_round(engine, p, snap)


def test_create_requires_dev_prefix_rules(engine, op):
    now = _now(engine)
    with pytest.raises(ValidationFailed):
        svc.create_round(
            engine,
            op,
            code="dev-x" + unique(),
            window_start=now,
            window_end=now + timedelta(days=1),
            development=False,
        )
    with pytest.raises(ValidationFailed):
        svc.create_round(
            engine,
            op,
            code=unique("2026-W"),
            window_start=now,
            window_end=now + timedelta(days=1),
            development=True,
        )


# ------------------------------------------------------------------ publication
def test_publish_freezes_snapshot_deadline_and_cutoff(engine, op):
    view, snap = publish_dev(engine, op)
    assert view.status == "open" and view.is_development
    assert view.fingerprint == snap.fingerprint
    assert view.deadline_at == snap.earliest_kickoff - timedelta(minutes=15)
    latest = max(f.kickoff for f in snap.fixtures)
    assert view.settle_cutoff_at == latest + timedelta(hours=48)
    assert (view.config_version, view.rules_version, view.scoring_version) == (
        "a3-432-v1",  # new weekend rounds bind v3 (app_0009)
        "settle/v1",
        "points-150-75-v2",
    )
    assert view.model_version == svc.MODEL_VERSION
    with transaction(engine) as conn:
        assert view.published_at <= db_now(conn)
        meta = conn.execute(
            select(round_snapshots.c.feasibility).where(round_snapshots.c.round_id == view.id)
        ).scalar_one()
        assert meta["source"] == "development" and meta["report"]["opens"] is True
        offers = conn.execute(
            select(snapshot_offers)
            .join(round_snapshots, round_snapshots.c.id == snapshot_offers.c.snapshot_id)
            .where(round_snapshots.c.round_id == view.id)
        ).all()
    assert len(offers) == len(snap.outcomes)
    for o in offers:  # bucket and eligibility derived on the server at full precision
        src = snap.outcome((o.fixture_id, o.market, o.outcome))
        assert o.market_prob == src.market_probability  # exact float round trip
        assert o.consensus_odds == src.reference_odds
        assert o.eligible == (o.bucket is not None)
        assert o.bucket == snap.config.classify(src.market_probability)  # the round's


def test_published_snapshot_round_trips_with_identical_fingerprint(engine, op):
    view, snap = publish_dev(engine, op)
    snapshots.CACHE.clear()
    loaded = svc.published_snapshot(engine, view.id)
    assert loaded.fingerprint == snap.fingerprint == view.fingerprint
    assert loaded.outcomes == snap.outcomes and loaded.fixtures == snap.fixtures
    assert loaded.deadline == view.deadline_at


def test_snapshot_survives_new_engine_and_cleared_cache(pg_url, engine, op):
    from diski9.backend.db import BackendDatabaseSettings, make_app_engine

    view, snap = publish_dev(engine, op)
    snapshots.CACHE.clear()
    other = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)
    try:  # a restarted application process: new pool, empty cache
        assert svc.published_snapshot(other, view.id).fingerprint == snap.fingerprint
        assert svc.get_round(other, view.id).deadline_at == view.deadline_at
    finally:
        other.dispose()


def test_real_pool_round_trips_at_full_precision(engine, op):
    """The 17 Nov 2026 research pool (68 real fixtures) stored and reloaded: every
    probability and odds value and the fingerprint are identical."""
    pool = json.loads(POOL.read_text())
    code = unique("dev-pool")
    snap = replace(
        snapshot_from_research_pool(pool, code, {39: "EPL"}, config=BROAD60_432_V1),
        kind=SnapshotKind.LIVE,
    )
    view = _draft_round(engine, op, snap)
    with transaction(engine) as conn:
        snapshots.store_snapshot(
            conn,
            view.id,
            snap,
            BROAD60_432_V1,
            source="development",
            report=snap.opening_report(),
            model_version=svc.MODEL_VERSION,
        )
    with transaction(engine) as conn:
        loaded = snapshots.load_snapshot(conn, view.id)
    assert loaded.fingerprint == snap.fingerprint
    for a, b in zip(loaded.outcomes, snap.outcomes, strict=True):
        assert repr(a.market_probability) == repr(b.market_probability)
        assert repr(a.model_probability) == repr(b.model_probability)
        assert str(a.reference_odds) == str(b.reference_odds)


@pytest.fixture
def football(tmp_path):
    """The populated football store from the app tests (SQLite, no API)."""
    from diski9.db import make_engine, upgrade

    url = f"sqlite:///{tmp_path / 'football.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    yield populated._get_wrapped_function()(eng)
    eng.dispose()


def test_prototype_live_snapshot_fingerprint_is_preserved(engine, op, football):
    """The prototype's live builder (football store, no API) and the stored copy
    have the same fingerprint for the same inputs."""
    from diski9.challenge.roundsheet import build_live_snapshot
    from tests.factories import T0

    code = unique("dev-live")
    snap = build_live_snapshot(
        football, T0, T0, T0 + timedelta(days=30), code, {}, config=BROAD60_432_V1
    )
    assert snap.outcomes
    view = svc.create_round(
        engine, op, code=code, window_start=T0, window_end=T0 + timedelta(days=30), development=True
    )
    with transaction(engine) as conn:
        snapshots.store_snapshot(
            conn,
            view.id,
            snap,
            BROAD60_432_V1,
            source="development",
            report=snap.opening_report(),
            model_version=svc.MODEL_VERSION,
        )
    with transaction(engine) as conn:
        assert snapshots.load_snapshot(conn, view.id).fingerprint == snap.fingerprint


def _refused(engine, op, snap, **kw):
    view = _draft_round(engine, op, snap)
    with pytest.raises(PublicationRefused) as exc:
        svc.publish_round(engine, op, view.id, snap, source=kw.pop("source", "development"), **kw)
    after = svc.get_round(engine, view.id)
    assert after.status == "draft" and after.fingerprint is None  # nothing written
    return exc.value


def test_refuses_too_few_fixtures(engine, op):
    err = _refused(engine, op, _fresh(engine, fixtures=14))
    assert err.details["report"]["checks"]["min_eligible_fixtures"] is False
    assert "eligible fixtures" in err.message


def _rebuild(snap, *, leagues=None, groups=None, observed=None):
    outs = []
    lg = leagues or {}
    for o in snap.outcomes:
        outs.append(
            make_outcome(
                o.fixture_id,
                o.market,
                o.outcome,
                o.market_probability,
                o.reference_odds,
                o.model_probability,
                groups if groups is not None else o.bookmaker_groups,
                observed or o.latest_observation_at,
                lg.get(o.fixture_id, o.league_id),
            )
        )
    fx = tuple(replace(f, league_id=lg.get(f.fixture_id, f.league_id)) for f in snap.fixtures)
    return replace(snap, outcomes=tuple(outs), fixtures=fx)


def test_refuses_too_few_leagues(engine, op):
    snap = _fresh(engine)
    two = {f.fixture_id: (39 if i % 2 else 140) for i, f in enumerate(snap.fixtures)}
    err = _refused(engine, op, _rebuild(snap, leagues=two))
    assert err.details["report"]["checks"]["min_eligible_leagues"] is False


def test_refuses_insufficient_bookmaker_groups(engine, op):
    err = _refused(engine, op, _rebuild(_fresh(engine), groups=2))
    assert err.details["report"]["eligible_outcomes"] == 0


def test_refuses_stale_odds(engine, op):
    snap = _fresh(engine)
    err = _refused(engine, op, _rebuild(snap, observed=snap.snapshot_at - timedelta(hours=25)))
    assert err.details["report"]["eligible_outcomes"] == 0  # every quote is stale


def test_refuses_when_overlap_makes_432_infeasible(engine, op):
    """Enough fixtures and leagues, and enough Foundation outcomes in total, but the
    only Foundation and Challenger outcomes share fixtures: independent counts look
    fine, the exact matching does not."""
    snap = _fresh(engine, fixtures=16)
    fids = [f.fixture_id for f in snap.fixtures]
    special = set(fids[:3])  # only three fixtures carry A and C outcomes
    outs = []
    for o in snap.outcomes:
        p = o.market_probability
        if o.fixture_id in special:
            p = {"HOME": 0.7, "DRAW": 0.05, "AWAY": 0.25}.get(str(o.outcome), 0.5)
        elif str(o.market) == "1X2":
            p = {"HOME": 0.45, "DRAW": 0.15, "AWAY": 0.40}[str(o.outcome)]
        else:
            p = 0.5
        outs.append(
            make_outcome(
                o.fixture_id,
                o.market,
                o.outcome,
                p,
                Decimal("1.90"),
                o.model_probability,
                5,
                o.latest_observation_at,
                o.league_id,
            )
        )
    bad = replace(snap, outcomes=tuple(outs))
    report = bad.opening_report()
    assert report.eligible_outcomes_by_bucket["A"] >= 3
    err = _refused(engine, op, bad)
    assert err.details["report"]["checks"]["portfolio_feasible"] is False


def test_refuses_old_or_future_snapshots_and_wrong_round(engine, op):
    now = _now(engine)
    old = dev_snapshot(
        unique("dev-o"),
        now - timedelta(hours=2),
        now + timedelta(hours=3),
        config=weekend_config(engine),
    )
    assert "too old" in _refused(engine, op, old).message
    fut = dev_snapshot(
        unique("dev-f"),
        now + timedelta(minutes=10),
        now + timedelta(hours=3),
        config=weekend_config(engine),
    )
    assert "future" in _refused(engine, op, fut).message
    snap = _fresh(engine)
    view = _draft_round(engine, op, replace(snap, round_id=unique("dev-other")))
    with pytest.raises(PublicationRefused, match="different round"):
        svc.publish_round(engine, op, view.id, snap, source="development")


def test_refuses_past_deadline(engine, op):
    now = _now(engine)
    snap = dev_snapshot(unique("dev-d"), now, now + timedelta(minutes=10),
                        config=weekend_config(engine))  # fmt: skip
    assert "deadline" in _refused(engine, op, snap).message


def test_development_and_real_data_never_mix(engine, op):
    snap = _fresh(engine)
    assert "Development fixtures" in _refused(engine, op, snap, source="football-db").message
    now = _now(engine)
    real = svc.create_round(
        engine, op, code=unique("2099-W01-"), window_start=now, window_end=now + timedelta(days=5)
    )
    code_snap = replace(snap, round_id=real.code)
    with pytest.raises(PublicationRefused):
        svc.publish_round(engine, op, real.id, code_snap, source="development")


def test_demo_snapshots_cannot_be_published(engine, op):
    snap = replace(_fresh(engine), kind=SnapshotKind.DEMO)
    assert "demonstration" in _refused(engine, op, snap).message


def test_refused_publication_is_recorded_as_failed_job(engine, op):
    snap = _fresh(engine, fixtures=10)
    _refused(engine, op, snap)
    with transaction(engine) as conn:
        row = conn.execute(
            select(job_runs.c.status, job_runs.c.error).where(
                job_runs.c.job == "publish", job_runs.c.scope == snap.round_id
            )
        ).one()
    assert row.status == "failed" and row.error


def test_published_round_cannot_be_republished_or_altered(engine, op):
    view, snap = publish_dev(engine, op)
    with pytest.raises(PublicationRefused, match="already open"):
        svc.publish_round(engine, op, view.id, snap, source="development")
    with transaction(engine) as conn:
        snap_id = conn.execute(
            select(round_snapshots.c.id).where(round_snapshots.c.round_id == view.id)
        ).scalar_one()
    statements = [
        update(rounds)
        .where(rounds.c.id == view.id)
        .values(deadline_at=view.deadline_at + timedelta(hours=1)),
        update(rounds).where(rounds.c.id == view.id).values(is_development=False),
        update(snapshot_offers)
        .where(snapshot_offers.c.snapshot_id == snap_id)
        .values(market_prob=0.5),
        snapshot_offers.delete().where(snapshot_offers.c.snapshot_id == snap_id),
        update(round_snapshots).where(round_snapshots.c.id == snap_id).values(fingerprint="0" * 16),
        insert(snapshot_fixtures).values(
            snapshot_id=snap_id,
            fixture_id=1,
            competition_id=39,
            home_team="x",
            away_team="y",
            kickoff_at_publish=view.deadline_at + timedelta(hours=1),
        ),
    ]
    for stmt in statements:
        with pytest.raises(DBAPIError), transaction(engine) as conn:
            conn.execute(stmt)
    snapshots.CACHE.clear()
    assert svc.published_snapshot(engine, view.id).fingerprint == snap.fingerprint


def test_tampered_snapshot_content_is_detected(engine, op):
    """Defence in depth: if stored content and fingerprint ever disagree (for
    example a manual edit by a superuser), loading refuses the snapshot."""
    from diski9.backend.services.common import SnapshotIntegrityError

    view, snap = publish_dev(engine, op)
    with transaction(engine) as conn:
        conn.execute(text("ALTER TABLE app.snapshot_offers DISABLE TRIGGER USER"))
        conn.execute(
            text(
                "UPDATE app.snapshot_offers o SET market_prob = market_prob + 1e-12 "
                "FROM app.round_snapshots s WHERE s.id = o.snapshot_id AND s.round_id = :r "
                "AND o.outcome = 'HOME'"
            ),
            {"r": view.id},
        )
        conn.execute(text("ALTER TABLE app.snapshot_offers ENABLE TRIGGER USER"))
    with pytest.raises(SnapshotIntegrityError), transaction(engine) as conn:
        snapshots.load_snapshot(conn, view.id)


def test_live_data_changes_do_not_touch_published_snapshot(engine, op):
    """A newer build for the same round (new odds, new model estimates) is refused;
    the stored snapshot stays exactly as published."""
    view, snap = publish_dev(engine, op)
    newer = dev_snapshot(
        view.code, _now(engine), snap.fixtures[0].kickoff, seed=99, config=snap.config
    )
    assert newer.fingerprint != snap.fingerprint
    with pytest.raises(PublicationRefused):
        svc.publish_round(engine, op, view.id, newer, source="development")
    snapshots.CACHE.clear()
    assert svc.published_snapshot(engine, view.id).fingerprint == snap.fingerprint


def test_weekly_window_from_schedule_rule(engine):
    start, end = svc.schedule_window(engine, 2026, 48)
    assert start == datetime(2026, 11, 27, tzinfo=UTC)  # Friday
    assert end == datetime(2026, 12, 1, tzinfo=UTC)  # Tuesday, exclusive


# ------------------------------------------------------------------ lock
def _open_round(engine, deadline_in):
    with transaction(engine) as conn:
        return make_round(conn, deadline_in=deadline_in)


def test_lock_refused_before_deadline_and_for_participants(engine, op):
    rid, _snap, _f = _open_round(engine, timedelta(hours=1))
    with pytest.raises(LockRefused, match="not been reached"):
        svc.lock_round(engine, svc.SYSTEM, rid)
    with pytest.raises(AuthorizationError):
        svc.lock_round(engine, principal(engine), rid)
    assert svc.get_round(engine, rid).status == "open"


def _users_with_entries(engine, rid, snap, fids, n):
    out = []
    with transaction(engine) as conn:
        for _ in range(n):
            uid = make_user(conn)
            out.append((uid, *confirm(conn, rid, snap, fids, uid)))
    return out


def test_four_valid_entries_make_a_practice_round(engine):
    rid, snap, fids = _open_round(engine, timedelta(seconds=3))
    made = _users_with_entries(engine, rid, snap, fids, 5)
    with transaction(engine) as conn:  # one withdraws before the deadline
        uid, entry_id, sub = made[0]
        e = portfolios.lock_entry(conn, rid, uid)
        assert portfolios.set_current_submission(conn, entry_id, None, e.version, "withdrawn")
        portfolios.add_event(conn, entry_id, "withdrawn", previous_submission_id=sub, actor=uid)
        other = make_user(conn)  # a draft is not an entry
        conn.execute(
            insert(portfolio_drafts).values(user_id=other, round_id=rid, selections=[], version=1)
        )
    wait_until(engine, svc.get_round(engine, rid).deadline_at)
    res = svc.lock_round(engine, svc.SYSTEM, rid)
    assert (res.locked_entries, res.designation) == (4, "practice")
    assert res.round.status == "locked" and res.round.valid_entries == 4
    with transaction(engine) as conn:
        locked = conn.execute(
            select(
                entries.c.user_id, entries.c.public_name_at_lock, entries.c.privacy_mode_at_lock
            ).where(entries.c.round_id == rid, entries.c.locked_at.is_not(None))
        ).all()
    assert {r.user_id for r in locked} == {m[0] for m in made[1:]}
    assert all(r.public_name_at_lock and r.privacy_mode_at_lock == "public" for r in locked)


def test_five_valid_entries_make_a_championship_round_and_lock_is_idempotent(engine):
    rid, snap, fids = _open_round(engine, timedelta(seconds=3))
    made = _users_with_entries(engine, rid, snap, fids, 5)
    with transaction(engine) as conn:  # an incomplete submission never counts
        uid = make_user(conn)
        entry_id = portfolios.create_entry(conn, rid, uid)
        from pg_helpers import selections_for, submission_values

        sub = portfolios.insert_submission(
            conn, submission_values(entry_id, rid, uid, snap), selections_for(fids)[:8]
        )
        assert portfolios.set_current_submission(conn, entry_id, sub, expected_version=0)
    wait_until(engine, svc.get_round(engine, rid).deadline_at)
    first = svc.lock_round(engine, svc.SYSTEM, rid)
    assert (first.locked_entries, first.designation, first.already_locked) == (
        5,
        "championship",
        False,
    )
    again = svc.lock_round(engine, svc.SYSTEM, rid)
    assert again.already_locked and again.locked_entries == 5
    assert again.round.designation == "championship"
    with transaction(engine) as conn:
        assert (
            conn.execute(
                select(func.count()).select_from(designations).where(designations.c.round_id == rid)
            ).scalar_one()
            == 1
        )
        events = conn.execute(
            select(func.count())
            .select_from(entry_events)
            .where(
                entry_events.c.kind == "locked", entry_events.c.entry_id.in_([m[1] for m in made])
            )
        ).scalar_one()
    assert events == 5


def test_concurrent_lock_requests_lock_once(engine):
    rid, snap, fids = _open_round(engine, timedelta(seconds=2))
    _users_with_entries(engine, rid, snap, fids, 2)
    wait_until(engine, svc.get_round(engine, rid).deadline_at)
    results, errors = [], []

    def run():
        try:
            results.append(svc.lock_round(engine, svc.SYSTEM, rid))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(r.already_locked for r in results) == [False, True, True, True]
    with transaction(engine) as conn:
        assert (
            conn.execute(
                select(func.count()).select_from(designations).where(designations.c.round_id == rid)
            ).scalar_one()
            == 1
        )


def test_lock_waits_for_an_in_flight_submission(engine):
    """A submission that started before the deadline (holding the round FOR SHARE)
    finishes first; the lock then includes it. A late lock never reopens the
    window: inserting after the deadline is refused by the database clock."""
    from diski9.backend.repositories import rounds as rounds_repo

    rid, snap, fids = _open_round(engine, timedelta(seconds=3))
    with transaction(engine) as conn:
        uid = make_user(conn)
    deadline = svc.get_round(engine, rid).deadline_at
    holder = engine.connect()
    trans = holder.begin()
    rounds_repo.lock_round_for_submission(holder, rid)
    confirm(holder, rid, snap, fids, uid)
    done = []
    wait_until(engine, deadline)
    t = threading.Thread(target=lambda: done.append(svc.lock_round(engine, svc.SYSTEM, rid)))
    t.start()
    t.join(timeout=1.0)
    assert t.is_alive()  # the lock is waiting for the in-flight submission
    trans.commit()
    holder.close()
    t.join(timeout=10)
    assert done and done[0].locked_entries == 1
    with pytest.raises(DBAPIError), transaction(engine) as conn:  # after the deadline
        late = make_user(conn)
        confirm(conn, rid, snap, fids, late)


def test_lock_refuses_a_draft_round(engine, op):
    view = _draft_round(engine, op, _fresh(engine))
    with pytest.raises(LockRefused):
        svc.lock_round(engine, svc.SYSTEM, view.id)


def test_current_round_prefers_open_and_hides_development(engine, op):
    view, _ = publish_dev(engine, op)
    assert svc.current_round(engine, include_development=True) is not None
    cur = svc.current_round(engine)
    assert cur is None or not cur.is_development
    assert view.id in {r.id for r in svc.list_rounds(engine, limit=200)}


def test_current_round_prefers_an_open_round_before_its_deadline(engine, op):
    """An open round past its deadline (lock pending) yields to an open round whose
    deadline is still ahead; with none ahead, the past-deadline round is shown."""
    expired, _ = publish_dev(engine, op, deadline_in=timedelta(seconds=2))
    ahead, _ = publish_dev(engine, op, deadline_in=timedelta(hours=5))
    wait_until(engine, expired.deadline_at)
    cur = svc.current_round(engine, include_development=True)
    assert cur.id != expired.id and cur.deadline_at > expired.deadline_at
    assert cur.status == "open"


def test_current_round_tie_on_deadline_shows_the_most_recently_published(engine, op):
    from diski9.backend.devdata import dev_snapshot

    with transaction(engine) as conn:
        now = db_now(conn)
    first = now + timedelta(minutes=20)  # deadline 5 minutes ahead, the same for both
    views = []
    for _ in range(2):
        code = unique("dev-tie")
        snap = dev_snapshot(code, now, first, seed=3, config=weekend_config(engine))
        v = svc.create_round(engine, op, code=code, window_start=snap.window[0],
                             window_end=snap.window[1], development=True)  # fmt: skip
        views.append(svc.publish_round(engine, op, v.id, snap, source="development"))
    assert views[0].deadline_at == views[1].deadline_at
    assert svc.current_round(engine, include_development=True).id == views[1].id
