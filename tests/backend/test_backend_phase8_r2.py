"""Phase 8 CP3A-R R2: price editions, freshness and rolling-entry integrity on real
PostgreSQL (migration ``app_0010``).

* immutable editions: numbering, universe, fixed deadline and cutoff, atomicity,
  database guards, consumer selection;
* freshness: the 6-hour observation and 24-hour provider limits from the oldest
  contributing timestamps, at the actual confirmation time; pause and recovery;
* confirmation: one coherent edition, the authoritative ``clock_timestamp()``
  submission time, database deadline / cutoff / copied-value enforcement, edition
  and confirmation races, concurrent writers, idempotent retries;
* the review fingerprint: no re-review for unchanged or unrelated values, named
  changed positions, drafts preserved;
* historical rounds unchanged.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from pg_helpers import make_round, make_user
from rolling_helpers import (
    bump,
    confirm,
    key,
    keys_excluding,
    now_of,
    publish_rolling,
    reprice,
    reviewed,
    save,
)
from settle_helpers import DEFAULT_ENTRY, confirm_entry, make_settlement_round, provider_item
from svc_helpers import principal, publish_dev, valid_keys, wait_until

from diski9.backend.db import transaction
from diski9.backend.db.schema import (
    round_snapshots,
    snapshot_offers,
    submission_selections,
    submissions,
)
from diski9.backend.repositories import portfolios
from diski9.backend.repositories import results as results_repo
from diski9.backend.repositories import rounds as rounds_repo
from diski9.backend.services import drafts, editions, review, rolling, snapshots
from diski9.backend.services import entries as es
from diski9.backend.services import results as results_svc
from diski9.backend.services import rounds as svc
from diski9.backend.services import settlement as st
from diski9.backend.services.common import RoundClosed, ServiceError, ValidationFailed
from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

WIN = {"HOME": (1, 0), "BTTS_YES": (1, 1), "UNDER_2_5": (0, 0), "AWAY": (0, 1)}


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def publish_edition(engine, view, snap, **kw):
    return editions.publish_edition(engine, svc.SYSTEM, view.id, reprice(snap, now_of(engine), **kw),
                                    source="development")  # fmt: skip


def count(engine, sql, **params) -> int:
    with transaction(engine) as conn:
        return conn.execute(sa.text(sql), params).scalar_one()


# ------------------------------------------------------------------ editions
def test_editions_are_numbered_immutable_and_never_move_deadline_or_cutoff(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4201)
    first = svc.get_round(engine, view.id)
    a = publish_edition(engine, view, snap)
    b = publish_edition(engine, view, snap)
    assert (a.edition, b.edition) == (2, 3) and a.snapshot_id < b.snapshot_id
    after = svc.get_round(engine, view.id)
    assert (
        after.deadline_at,
        after.settle_cutoff_at,
        after.rules_version,
        after.config_version,
    ) == (first.deadline_at, first.settle_cutoff_at, first.rules_version, first.config_version)
    assert after.fingerprint == first.fingerprint == snap.fingerprint  # edition 1 identity
    assert [e["edition"] for e in editions.editions(engine, view.id)] == [1, 2, 3]
    with transaction(engine) as conn:
        assert snapshots.universe_id(conn, view.id) < a.snapshot_id
        assert snapshots.current_edition(conn, view.id) == (b.snapshot_id, 3)
        assert snapshots.load_snapshot(conn, view.id).fingerprint == snap.fingerprint
    assert svc.current_snapshot(engine, view.id).fingerprint == b.fingerprint


def test_edition_outside_the_universe_is_refused_by_service_and_database(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4202)
    other, osnap = publish_dev(engine, op, seed=4299)
    foreign = reprice(snap, now_of(engine))
    foreign = foreign.__class__(**{**foreign.__dict__, "fixtures": foreign.fixtures + osnap.fixtures[:1],
                                   "outcomes": foreign.outcomes + osnap.outcomes[:3]})  # fmt: skip
    with pytest.raises(editions.EditionRefused, match="outside the published universe"):
        editions.publish_edition(engine, svc.SYSTEM, view.id, foreign, source="development")
    # the database refuses it even when the service is bypassed
    with pytest.raises(sa.exc.DBAPIError, match="outside the published universe"), \
            transaction(engine) as conn:  # fmt: skip
        rounds_repo.lock_round_for_change(conn, view.id)
        rounds_repo.insert_snapshot(
                conn, view.id, as_of=now_of(engine), fingerprint="f" * 16, model_version="m",
                feasibility={}, edition=2,
                fixtures=[{"fixture_id": osnap.fixtures[0].fixture_id, "competition_id": 39,
                           "home_team": "H", "away_team": "A",
                           "kickoff_at_publish": osnap.fixtures[0].kickoff}], offers=[])  # fmt: skip
    assert [e["edition"] for e in editions.editions(engine, view.id)] == [1]


def test_database_guards_on_editions(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4203)
    e2 = publish_edition(engine, view, snap)
    fid = snap.fixtures[0].fixture_id
    row = {"snapshot_id": e2.snapshot_id, "fixture_id": fid, "market": "1X2", "outcome": "HOME",
           "model_prob": 0.5, "consensus_odds": Decimal("2.00"), "market_prob": 0.5,
           "bookmaker_groups": 5, "eligible": False, "bucket": None}  # fmt: skip
    # an existing edition never gains rows, even while the round is open
    with pytest.raises(sa.exc.DBAPIError, match="written once"), transaction(engine) as conn:
        conn.execute(sa.delete(snapshot_offers).where(sa.false()))  # no-op; keeps the shape
        conn.execute(sa.insert(snapshot_offers).values(**row))
    # non-consecutive and duplicate edition numbers
    for edition, pattern in ((5, "does not follow"), (1, "written once")):
        with pytest.raises(sa.exc.DBAPIError, match=pattern), transaction(engine) as conn:
            conn.execute(sa.insert(round_snapshots).values(
                round_id=view.id, as_of=now_of(engine), fingerprint="e" * 16, model_version="m",
                feasibility={}, edition=edition))  # fmt: skip
    # a historical round never takes a later edition
    hist, _ = publish_dev(engine, op, seed=4204)
    with pytest.raises(sa.exc.DBAPIError, match="rolling-entry"), transaction(engine) as conn:
        conn.execute(sa.insert(round_snapshots).values(
            round_id=hist.id, as_of=now_of(engine), fingerprint="e" * 16, model_version="m",
            feasibility={}, edition=2))  # fmt: skip
    with pytest.raises(editions.EditionRefused, match="Only rolling-entry"):
        editions.publish_edition(engine, svc.SYSTEM, hist.id, snap, source="development")


def test_failed_edition_write_leaves_nothing_visible(engine, op, monkeypatch):
    view, snap, _ = publish_rolling(engine, op, seed=4205)
    real = rounds_repo.insert_snapshot

    def broken(conn, *a, **kw):
        real(conn, *a, **kw)
        raise RuntimeError("simulated failure after the rows were inserted")

    monkeypatch.setattr(snapshots.rounds_repo, "insert_snapshot", broken)
    with pytest.raises(RuntimeError):
        publish_edition(engine, view, snap)
    monkeypatch.undo()
    assert [e["edition"] for e in editions.editions(engine, view.id)] == [1]
    assert count(engine, "SELECT count(*) FROM app.snapshot_offers o JOIN app.round_snapshots s "
                 "ON s.id = o.snapshot_id WHERE s.round_id = :r", r=view.id) == len(snap.outcomes)  # fmt: skip
    assert publish_edition(engine, view, snap).edition == 2  # numbering unaffected


def test_edition_refused_after_close_and_empty_candidate(engine, op):
    view, snap, close = publish_rolling(engine, op, close_in=timedelta(seconds=4), seed=4206)
    with pytest.raises(editions.EditionRefused, match="no priced fixtures"):
        publish_edition(engine, view, snap, drop={f.fixture_id for f in snap.fixtures})
    wait_until(engine, close)
    with pytest.raises(editions.EditionRefused, match="not open"):
        publish_edition(engine, view, snap)


def test_consumers_read_the_right_edition(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4207)
    p = principal(engine)
    keys = keys_excluding(snap)
    d = save(engine, p, view, keys)
    dropped = keys[0]["fixture_id"]
    e2 = publish_edition(engine, view, snap, drop={dropped})
    with transaction(engine) as conn:
        uni = snapshots.universe_id(conn, view.id)
        assert results_svc.snapshot_id_of(conn, view.id) == uni  # results and corrections
        cur = snapshots.CACHE.current(conn, view.id)
    assert cur[0] == e2.snapshot_id and dropped not in {f.fixture_id for f in cur[2].fixtures}
    assert dropped in {f.fixture_id for f in svc.published_snapshot(engine, view.id).fixtures}
    # the saved draft is never changed; saving it again is refused against the current edition
    assert drafts.get_draft(engine, p, view.id).selections == d.selections
    with pytest.raises(ValidationFailed, match="not valid"):
        save(engine, p, view, keys, d.version)
    rv = review.review_portfolio(engine, p, view.id)
    assert rv.edition == 2 and rv.problems[0]["reason"] == "not_on_sheet" and not rv.ready


def test_historical_round_is_unchanged_by_editions(engine, op):
    view, snap = publish_dev(engine, op, seed=4208)
    with transaction(engine) as conn:
        assert snapshots.current_edition(conn, view.id)[1] == 1
        assert snapshots.universe_id(conn, view.id) == snapshots.current_edition(conn, view.id)[0]
    p = principal(engine)
    d = save(engine, p, view, valid_keys(snap))
    e = es.confirm_entry(
        engine, p, view.id, draft_version=d.version, expected_entry_version=0, idempotency_key=key()
    )  # no review needed: historical methodology
    with transaction(engine) as conn:
        sub = conn.execute(sa.select(submissions).where(submissions.c.id == e.current.id)).one()
        assert sub.submitted_at == conn.execute(
            sa.text("SELECT min(at) FROM app.entry_events WHERE submission_id = :s"),
            {"s": sub.id}).scalar_one()  # both the transaction timestamp (unchanged)  # fmt: skip
    e2 = es.confirm_entry(
        engine,
        p,
        view.id,
        draft_version=d.version,
        expected_entry_version=e.version,
        idempotency_key=key(),
        replace=True,
    )
    assert e2.current.version == 2  # replacement still allowed


# ------------------------------------------------------------------ submissions and history
def test_submission_keeps_its_own_edition_values_after_repricing(engine, op):
    view, snap, _ = publish_rolling(engine, op, close_in=timedelta(seconds=10), seed=4209)
    p = principal(engine)
    d = save(engine, p, view, keys_excluding(snap))
    e = confirm(engine, p, view, d)
    before = [dict(s) for s in e.current.selections]
    changes = {(s["fixture_id"], s["market"], s["outcome"]): bump(s["market_prob"])
               for s in before}  # fmt: skip
    publish_edition(engine, view, snap, changes=changes)
    assert [dict(s) for s in es.get_entry(engine, p, view.id).current.selections] == before
    wait_until(engine, svc.get_round(engine, view.id).deadline_at)
    locked = svc.lock_round(engine, svc.SYSTEM, view.id)
    assert locked.locked_entries == 1  # validity uses the submission's own edition


def test_copied_values_equal_the_authoritative_edition_at_full_precision(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4210)
    e2 = publish_edition(engine, view, snap, changes={o.key: o.market_probability + 1e-7
                                                      for o in snap.outcomes[:30]})  # fmt: skip
    p = principal(engine)
    d = save(
        engine,
        p,
        view,
        [
            dict(k, consensus_odds="99.00", market_prob=0.99, bucket="A")
            for k in keys_excluding(snap)
        ],
    )  # client values are ignored
    e = confirm(engine, p, view, d)
    with transaction(engine) as conn:
        sub = conn.execute(sa.select(submissions).where(submissions.c.id == e.current.id)).one()
        assert sub.snapshot_id == e2.snapshot_id
        rows = conn.execute(sa.text(
            "SELECT ss.consensus_odds = o.consensus_odds AND ss.market_prob = o.market_prob "
            "AND ss.model_prob IS NOT DISTINCT FROM o.model_prob AND ss.bucket = o.bucket "
            "AND ss.bookmaker_groups = o.bookmaker_groups AND o.eligible AS same "
            "FROM app.submission_selections ss JOIN app.snapshot_offers o ON o.snapshot_id = "
            "ss.snapshot_id AND o.fixture_id = ss.fixture_id AND o.market = ss.market AND "
            "o.outcome = ss.outcome WHERE ss.submission_id = :s"), {"s": sub.id}).scalars().all()  # fmt: skip
    assert rows == [True] * 9
    stored = {(s["fixture_id"], s["market"], s["outcome"]): s["market_prob"]
              for s in e.current.selections}  # fmt: skip
    cur = svc.current_snapshot(engine, view.id)
    assert all(cur.outcome(k).market_probability == v for k, v in stored.items())  # not rounded


def test_database_refuses_copied_values_that_differ_from_the_edition(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4211)
    with transaction(engine) as conn:
        sid = snapshots.universe_id(conn, view.id)
        uid = make_user(conn)
        entry = portfolios.create_entry(conn, view.id, uid)
    keys = keys_excluding(snap)
    rows = []
    for pos, k in enumerate(keys):
        o = snap.outcome((k["fixture_id"], k["market"], k["outcome"]))
        rows.append({"position": pos, "fixture_id": o.fixture_id, "market": k["market"],
                     "outcome": k["outcome"], "bucket": snap.config.classify(o.market_probability),
                     "model_prob": o.model_probability, "consensus_odds": o.reference_odds,
                     "market_prob": o.market_probability, "bookmaker_groups": o.bookmaker_groups})  # fmt: skip
    rows[3] = dict(rows[3], consensus_odds=rows[3]["consensus_odds"] + Decimal("0.01"))
    with (
        pytest.raises(sa.exc.DBAPIError, match="differ from the edition"),
        transaction(engine) as conn,
    ):
        portfolios.insert_submission(conn, _sub(entry, view.id, uid, sid), rows)


def _sub(entry, rid, uid, sid) -> dict:
    import hashlib
    import uuid

    return {"entry_id": entry, "round_id": rid, "user_id": uid, "snapshot_id": sid, "version": 1,
            "idempotency_key": "direct-" + uuid.uuid4().hex,
            "inputs_hash": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
            "p_recover_market": 0.3, "p_recover_model": None, "expected_gross_market": 90.0,
            "expected_gross_model": None, "max_gross": Decimal("500.00"), "states": {},
            "config_version": "a3-432-v1", "calc_version": "structured-1",
            "model_version": "goal-model-1.1", "rules_version": rolling.ROLLING_RULES_VERSION}  # fmt: skip


def test_database_refuses_an_old_edition_a_late_submission_and_a_closed_fixture(engine, op):
    view, snap, close = publish_rolling(engine, op, close_in=timedelta(seconds=8),
                                        first_kickoff_in=timedelta(minutes=10), seed=4212)  # fmt: skip
    with transaction(engine) as conn:
        e1 = snapshots.universe_id(conn, view.id)
        uid = make_user(conn)
        entry = portfolios.create_entry(conn, view.id, uid)
    publish_edition(engine, view, snap)
    with pytest.raises(sa.exc.DBAPIError, match="current edition"), transaction(engine) as conn:
        portfolios.insert_submission(conn, _sub(entry, view.id, uid, e1), [])
    with transaction(engine) as conn:
        e2 = snapshots.current_edition(conn, view.id)[0]
    first = snap.fixtures[0]  # kicks off in 10 minutes: inside the 15-minute cutoff
    cur = svc.current_snapshot(engine, view.id)
    o = next(x for x in cur.outcomes if x.fixture_id == first.fixture_id
             and cur.config.classify(x.market_probability))  # fmt: skip
    row = {"position": 0, "fixture_id": o.fixture_id, "market": str(o.market),
           "outcome": str(o.outcome), "bucket": cur.config.classify(o.market_probability),
           "model_prob": o.model_probability, "consensus_odds": o.reference_odds,
           "market_prob": o.market_probability, "bookmaker_groups": o.bookmaker_groups}  # fmt: skip
    with pytest.raises(sa.exc.DBAPIError, match="kicks off within 15 minutes"), \
            transaction(engine) as conn:  # fmt: skip
        portfolios.insert_submission(conn, _sub(entry, view.id, uid, e2), [row])
    wait_until(engine, close)
    with pytest.raises(sa.exc.DBAPIError, match="not open for submissions"), \
            transaction(engine) as conn:  # fmt: skip
        portfolios.insert_submission(conn, _sub(entry, view.id, uid, e2), [])


def test_submission_time_is_the_actual_clock_at_insert(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4213)
    with transaction(engine) as conn:
        sid = snapshots.universe_id(conn, view.id)
        uid = make_user(conn)
        entry = portfolios.create_entry(conn, view.id, uid)
    with transaction(engine) as conn:
        started = conn.execute(sa.text("SELECT transaction_timestamp()")).scalar_one()
        time.sleep(1.2)
        at = conn.execute(sa.insert(submissions).values(**_sub(entry, view.id, uid, sid))
                          .returning(submissions.c.submitted_at)).scalar_one()  # fmt: skip
    assert at - started >= timedelta(seconds=1.2)


# ------------------------------------------------------------------ freshness
def test_six_hour_observation_and_24_hour_provider_limits_at_confirmation(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4214)
    keys = keys_excluding(snap)
    now = now_of(engine)
    chosen = {(k["fixture_id"], k["market"], k["outcome"]) for k in keys}
    # edition built now; the selected prices were last genuinely observed 6 h - 3 s ago
    publish_edition(engine, view, snap, observed=now - timedelta(hours=6) + timedelta(seconds=3),
                    provider=now - timedelta(hours=1))  # fmt: skip
    p = principal(engine)
    d = save(engine, p, view, keys)
    rv = reviewed(engine, p, view)
    time.sleep(4)  # crosses the 6-hour boundary
    with pytest.raises(es.PriceExpired) as exc:
        confirm(engine, p, view, d, reviewed=rv)
    assert {i["reason"] for i in exc.value.issues} == {"stale_observation"}
    assert drafts.get_draft(engine, p, view.id).version == d.version  # draft preserved
    # provider timestamp 24 h + 1 s old (observation fresh)
    publish_edition(engine, view, snap, observed=now_of(engine) - timedelta(minutes=5),
                    provider=now_of(engine) - timedelta(hours=24, seconds=1))  # fmt: skip
    with pytest.raises(es.PriceExpired) as exc:
        confirm(engine, p, view, d)
    assert {i["reason"] for i in exc.value.issues} == {"stale_provider_update"}
    # fresh again: confirmation succeeds
    publish_edition(engine, view, snap)
    assert confirm(engine, p, view, d).active
    assert len(chosen) == 9


def test_missing_evidence_is_refused_and_the_oldest_timestamp_decides():
    from datetime import UTC, datetime

    from diski9.challenge.structured import make_outcome

    now = datetime(2026, 12, 5, 12, 0, tzinfo=UTC)
    base = dict(fixture_id=1, market="1X2", outcome="HOME", market_probability=0.6,
                reference_odds=Decimal("1.60"), model_probability=0.6, bookmaker_groups=4,
                latest_observation_at=now - timedelta(minutes=1))  # fmt: skip
    assert editions.offer_problem(make_outcome(**base), now) == "missing_evidence"
    # latest observation a minute ago, but the oldest contributing one 7 h ago: stale
    o = make_outcome(**base, oldest_observation_at=now - timedelta(hours=7),
                     provider_updated_at=now - timedelta(hours=1))  # fmt: skip
    assert editions.offer_problem(o, now) == "stale_observation"
    o = make_outcome(**base, oldest_observation_at=now - timedelta(hours=6),
                     provider_updated_at=now - timedelta(hours=24))  # fmt: skip
    assert editions.offer_problem(o, now) is None  # both limits are inclusive


def test_no_artificial_freshness_from_a_new_edition(engine, op):
    """A later edition carrying old evidence (a partial sweep that did not reach these
    fixtures) is not fresh just because it was built now."""
    view, snap, _ = publish_rolling(engine, op, seed=4215)
    now = now_of(engine)
    keys = keys_excluding(snap)
    sel = {(k["fixture_id"], k["market"], k["outcome"]) for k in keys}
    stale = now - timedelta(hours=7)
    cand = reprice(snap, now, observed=now - timedelta(minutes=2))
    cand = cand.__class__(**{**cand.__dict__, "outcomes": tuple(
        o.__class__(**{**o.__dict__, "oldest_observation_at": stale}) if o.key in sel else o
        for o in cand.outcomes)})  # fmt: skip
    editions.publish_edition(engine, svc.SYSTEM, view.id, cand, source="development")
    p = principal(engine)
    d = save(engine, p, view, keys)
    with pytest.raises(es.PriceExpired):
        confirm(engine, p, view, d)
    # the builder's own restriction drops such offers before an edition is written
    kept = editions.restrict_to_universe(cand, [f.fixture_id for f in snap.fixtures], now)
    assert not ({o.key for o in kept.outcomes} & sel)


def test_participation_pauses_and_recovers(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4216)
    assert editions.round_availability(engine, view.id).status == "open"
    old = now_of(engine) - timedelta(hours=7)
    publish_edition(engine, view, snap, observed=old)
    paused = editions.round_availability(engine, view.id)
    assert paused.status == "paused" and paused.problems.get("stale_observation")
    publish_edition(engine, view, snap)
    assert editions.round_availability(engine, view.id).status == "open"


# ------------------------------------------------------------------ review fingerprint
def test_review_survives_identical_and_unrelated_changes(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4217)
    keys = keys_excluding(snap)
    mine = {(k["fixture_id"], k["market"], k["outcome"]) for k in keys}
    other = next(o for o in snap.outcomes if o.fixture_id not in {k[0] for k in mine})
    p = principal(engine)
    d = save(engine, p, view, keys)
    rv = reviewed(engine, p, view)
    publish_edition(engine, view, snap)  # identical reviewed values, new edition number
    publish_edition(engine, view, snap, changes={other.key: bump(other.market_probability)})
    e = confirm(engine, p, view, d, reviewed=rv)
    assert e.active


def test_changed_reviewed_value_requires_review_and_names_the_position(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4218)
    keys = keys_excluding(snap)
    p = principal(engine)
    d = save(engine, p, view, keys)
    rv = reviewed(engine, p, view)
    k4 = (keys[4]["fixture_id"], keys[4]["market"], keys[4]["outcome"])
    publish_edition(engine, view, snap, changes={k4: bump(snap.outcome(k4).market_probability)})
    with pytest.raises(es.ReviewChanged) as exc:
        confirm(engine, p, view, d, reviewed=rv)
    assert exc.value.details["positions"] == [4]
    assert drafts.get_draft(engine, p, view.id).selections == d.selections
    assert count(engine, "SELECT count(*) FROM app.submissions WHERE user_id = :u",
                 u=p.user_id) == 0  # fmt: skip
    assert confirm(engine, p, view, d).active  # after reviewing again


def test_review_items_use_display_precision_only_for_comparison():
    from datetime import UTC, datetime

    from diski9.challenge.config import get_config
    from diski9.challenge.structured import make_outcome

    cfg = get_config("a3-432-v1")
    at = datetime(2026, 12, 5, 12, 0, tzinfo=UTC)
    a = make_outcome(1, "1X2", "HOME", 0.61234, Decimal("1.55"), 0.6, 4, at)
    b = make_outcome(1, "1X2", "HOME", 0.61236, Decimal("1.55"), 0.6, 4, at)  # same 61.2%
    c = make_outcome(1, "1X2", "HOME", 0.6127, Decimal("1.55"), 0.6, 4, at)  # 61.3%
    ia, ib, ic = (review.item(o, cfg, "goal-model-1.1") for o in (a, b, c))
    assert review.digest(ia) == review.digest(ib) != review.digest(ic)
    assert ia["p"] == "61.2" and ia["odds"] == "1.55" and ia["view"] is None
    assert ia["base"] == {"src": "goal_model", "ver": "goal-model-1.1", "eg": None, "bp": "60.0"}
    assert review.changed_positions(["x", "y"], ["x", "z", "w"]) == [1, 2]


# ------------------------------------------------------------------ concurrency
def test_confirmation_waiting_for_an_edition_uses_the_new_edition_only(engine, op):
    """An edition writer holds the round lock; a confirmation waits, then resolves the
    edition after the lock: reviewed values changed -> re-review, never a mix."""
    view, snap, _ = publish_rolling(engine, op, seed=4219)
    keys = keys_excluding(snap)
    p = principal(engine)
    d = save(engine, p, view, keys)
    rv = reviewed(engine, p, view)
    k0 = (keys[0]["fixture_id"], keys[0]["market"], keys[0]["outcome"])
    cand = reprice(snap, now_of(engine), changes={k0: bump(snap.outcome(k0).market_probability)})
    held, out = threading.Event(), []
    real = rounds_repo.lock_round_for_change

    def slow_writer():
        def lock_then_wait(conn, rid, nowait=False):
            r = real(conn, rid, nowait)
            held.set()
            time.sleep(1.0)
            return r

        rounds_repo_mod = editions.rounds_repo
        orig = rounds_repo_mod.lock_round_for_change
        rounds_repo_mod.lock_round_for_change = lock_then_wait
        try:
            out.append(editions.publish_edition(engine, svc.SYSTEM, view.id, cand,
                                                source="development"))  # fmt: skip
        finally:
            rounds_repo_mod.lock_round_for_change = orig

    t = threading.Thread(target=slow_writer)
    t.start()
    held.wait()
    with pytest.raises(es.ReviewChanged):
        confirm(engine, p, view, d, reviewed=rv)
    t.join()
    assert out and out[0].edition == 2
    e = confirm(engine, p, view, d)  # reviewed again against edition 2
    with transaction(engine) as conn:
        assert conn.execute(sa.select(submissions.c.snapshot_id).where(
            submissions.c.id == e.current.id)).scalar_one() == out[0].snapshot_id  # fmt: skip


def test_edition_waits_for_a_confirmation_in_progress(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4220)
    order, held = [], threading.Event()

    def confirmation():  # holds the confirmation lock (FOR SHARE) for a moment
        with transaction(engine) as conn:
            rounds_repo.lock_round_for_submission(conn, view.id)
            held.set()
            time.sleep(0.8)
            order.append("confirmation")

    t = threading.Thread(target=confirmation)
    t.start()
    held.wait()
    publish_edition(engine, view, snap)
    order.append("edition")
    t.join()
    assert order == ["confirmation", "edition"]


def test_concurrent_edition_writers_never_duplicate(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4221)
    results, barrier = [], threading.Barrier(3)

    def write():
        barrier.wait()
        try:
            results.append(publish_edition(engine, view, snap).edition)
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=write) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r for r in results if isinstance(r, int)) == [2, 3, 4], results
    assert [e["edition"] for e in editions.editions(engine, view.id)] == [1, 2, 3, 4]


def test_concurrent_confirmations_store_one_submission(engine, op):
    view, snap, _ = publish_rolling(engine, op, seed=4222)
    p = principal(engine)
    d = save(engine, p, view, keys_excluding(snap))
    rv = reviewed(engine, p, view)
    results, barrier = [], threading.Barrier(4)

    def attempt():
        barrier.wait()
        try:
            results.append(confirm(engine, p, view, d, reviewed=rv))
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(isinstance(r, es.EntryView) for r in results) == 1, results
    assert count(engine, "SELECT count(*) FROM app.submissions WHERE user_id = :u",
                 u=p.user_id) == 1  # fmt: skip


def test_retry_returns_the_stored_submission_after_new_edition_and_close(engine, op):
    view, snap, close = publish_rolling(engine, op, close_in=timedelta(seconds=8), seed=4223)
    p = principal(engine)
    keys = keys_excluding(snap)
    d = save(engine, p, view, keys)
    rv, k = reviewed(engine, p, view), key()
    e = confirm(engine, p, view, d, reviewed=rv, k=k)
    k0 = (keys[0]["fixture_id"], keys[0]["market"], keys[0]["outcome"])
    publish_edition(engine, view, snap, changes={k0: bump(snap.outcome(k0).market_probability)})
    assert confirm(engine, p, view, d, reviewed=rv, k=k).current.id == e.current.id
    with pytest.raises(es.IdempotencyMismatch):  # same key, different reviewed payload
        confirm(engine, p, view, d, reviewed=list(reversed(rv)), k=k)
    wait_until(engine, close)
    assert confirm(engine, p, view, d, reviewed=rv, k=k).current.id == e.current.id
    with pytest.raises(RoundClosed):
        confirm(engine, principal(engine), view, d, reviewed=rv)


def test_lock_wait_across_the_fixture_cutoff_is_refused(engine, op):
    view, snap, _ = publish_rolling(engine, op, first_kickoff_in=timedelta(minutes=15, seconds=8),
                                    seed=4224)  # fmt: skip
    first = snap.fixtures[0]
    p = principal(engine)
    keys = valid_keys(snap)
    assert first.fixture_id in {k["fixture_id"] for k in keys}
    d = save(engine, p, view, keys)
    rv = reviewed(engine, p, view)
    cutoff = first.kickoff - timedelta(minutes=15)
    wait_until(engine, cutoff - timedelta(milliseconds=800))
    held = threading.Event()

    def blocker():
        with transaction(engine) as conn:
            rounds_repo.lock_round_for_change(conn, view.id)
            held.set()
            time.sleep(1.5)

    t = threading.Thread(target=blocker)
    t.start()
    held.wait()
    with pytest.raises(es.FixtureClosed):
        confirm(engine, p, view, d, reviewed=rv)
    t.join()


# ------------------------------------------------------------------ R1 regression scenario
def record(engine, fid, at, status, ko, h=None, a=None):
    wait_until(engine, at)
    item = provider_item(fid, status, ko=ko, h=h, a=a)
    with transaction(engine) as conn:
        return results_repo.record_evidence(
            conn, source="api-football", fixture_id=fid, observed_at=at, raw=item,
            raw_hash=canonical_hash(item), fields=evidence_fields(item))  # fmt: skip


def test_kickoff_between_transaction_start_and_insert_is_void_for_that_entry(engine, op):
    """R1 review obligation: a transaction starts, the match actually kicks off early,
    then the submission row is inserted. The submission time is the insert time, so
    settlement V3 voids that leg for this entry."""
    with transaction(engine) as conn:
        rid, snap_id, fids, deadline, cutoff = make_settlement_round(
            conn, deadline_in=timedelta(seconds=6), rules_version=rolling.ROLLING_RULES_VERSION
        )
        uid = make_user(conn)
    obs_at = {}

    def early_kickoff():  # recorded while the submitting transaction is already open
        time.sleep(0.6)
        with transaction(engine) as c:
            obs_at["t"] = c.execute(sa.text("SELECT clock_timestamp()")).scalar_one()
        record(engine, fids[0], obs_at["t"], "1H", obs_at["t"] - timedelta(minutes=1))

    with transaction(engine) as conn:
        started = conn.execute(sa.text("SELECT transaction_timestamp()")).scalar_one()
        t = threading.Thread(target=early_kickoff)
        t.start()
        t.join()
        entry, sub = confirm_entry(conn, rid, snap_id, fids, uid, DEFAULT_ENTRY)
        at = conn.execute(sa.select(submissions.c.submitted_at).where(submissions.c.id == sub)
                          ).scalar_one()  # fmt: skip
    assert started < obs_at["t"] < at
    wait_until(engine, deadline)
    svc.lock_round(engine, svc.SYSTEM, rid)
    fin = deadline + timedelta(milliseconds=1500)
    for i, (_, _, o) in enumerate(DEFAULT_ENTRY):
        ko = obs_at["t"] - timedelta(minutes=1) if i == 0 else deadline + timedelta(seconds=1)
        record(engine, fids[i], fin, "FT", ko, *WIN[o])
    st.settle_round(engine, op, rid)
    with transaction(engine) as conn:
        legs = conn.execute(sa.text(
            "SELECT legs FROM app.entry_settlements WHERE entry_id = :e ORDER BY revision DESC "
            "LIMIT 1"), {"e": entry}).scalar_one()["legs"]  # fmt: skip
    assert legs[0]["verdict"] == "void"
    assert [leg["verdict"] for leg in legs[1:]] == ["won"] * 8


# ------------------------------------------------------------------ refresh planning
def test_competitive_slots_cover_the_weekend_overnight_and_stop_before_the_close():
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from diski9.backend.jobs.refresh import competitive_slots
    from diski9.backend.services.rounds import weekly_window

    sast = ZoneInfo("Africa/Johannesburg")
    start, _ = weekly_window(rolling.ROLLING_WINDOW_RULE, 2026, 49)
    close = rolling.entry_close(rolling.ROLLING_PUBLISH_RULE, start)
    slots = competitive_slots(start, close)
    labels = [s.at.astimezone(sast).strftime("%a %H:%M") for s in slots]
    assert len(slots) == 19
    assert labels[:6] == ["Fri 06:15", "Fri 09:15", "Fri 12:15", "Fri 15:15", "Fri 18:15",
                          "Fri 21:15"]  # fmt: skip
    assert labels[6:14] == ["Sat 00:15", "Sat 03:15", "Sat 06:15", "Sat 09:15", "Sat 12:15",
                            "Sat 15:15", "Sat 18:15", "Sat 21:15"]  # fmt: skip
    assert labels[14:] == ["Sun 00:15", "Sun 03:15", "Sun 06:15", "Sun 09:15", "Sun 12:15"]
    assert all(s.at < close for s in slots) and slots[-1].at == datetime(2026, 12, 6, 10, 15,
                                                                         tzinfo=UTC)  # fmt: skip


def test_request_caps_are_unchanged():
    from diski9.backend.jobs import locking, refresh
    from diski9.backend.jobs.config import SchedulerConfig

    cfg = SchedulerConfig()
    # the approved preparation cap and results reserve (the 450 total and 20 per tick are
    # the owner-approved activation values, set explicitly in the environment, D-1)
    assert (cfg.nonessential_per_day, cfg.results_reserve) == (300, 150)
    assert refresh.MAX_LEAGUE_NEED == 4 and locking.PREPARATION == "preparation"


def test_competitive_planner_sweeps_remaining_leagues_then_writes_one_edition(engine, op):
    from dataclasses import dataclass

    from diski9.backend.jobs import refresh
    from diski9.backend.jobs.config import SchedulerConfig
    from diski9.backend.repositories import ops

    view, snap, close = publish_rolling(engine, op, seed=4225)
    cfg = SchedulerConfig()
    with transaction(engine) as conn:
        row = refresh._round_row(conn, view.code)
    # the round was published just now; pretend its window started 6 h 15 min ago, so
    # its first competitive slot (Friday 06:15 SAST) is due now
    from types import SimpleNamespace

    rr = SimpleNamespace(**dict(row._mapping))
    rr.window_start_at = rr.published_at - timedelta(hours=6, minutes=15, milliseconds=500)
    rr.published_at = rr.published_at - timedelta(seconds=1)

    @dataclass
    class W:
        code: str

    week = W(view.code)
    now = now_of(engine)
    with transaction(engine) as conn:
        steps, _ = refresh.plan_competitive(conn, cfg, week, rr, now, now)
        leagues = refresh.competitive_leagues(conn, view.id, now)
    assert [s.kind for s in steps] == ["league"] * len(leagues) and leagues
    assert {s.league for s in steps} == set(leagues) and steps[0].slot.kind == "competitive"
    slot = steps[0].slot
    with transaction(engine) as conn:
        for lg in leagues:
            rid = ops.start_job(
                conn,
                refresh.PREPARE_REFRESH,
                f"{view.code}:{lg}",
                {"slot": slot.key(view.code), "at": now.isoformat()},
            )
            ops.finish_job(conn, rid, "succeeded")
        steps, _ = refresh.plan_competitive(conn, cfg, week, rr, now, now)
        assert [s.kind for s in steps] == ["screener"]
        rid = ops.start_job(
            conn,
            refresh.PREPARE_SCREENER,
            view.code,
            {"slot": slot.key(view.code), "kind": "complete"},
        )
        ops.finish_job(conn, rid, "succeeded")
        steps, _ = refresh.plan_competitive(conn, cfg, week, rr, now, now)
        assert [s.kind for s in steps] == ["edition"]
        rid = ops.start_job(conn, refresh.PREPARE_EDITION, view.code, {"slot": slot.key(view.code)})
        ops.finish_job(conn, rid, "skipped", error="skipped: edition not written")
        steps, why = refresh.plan_competitive(conn, cfg, week, rr, now, now)
        assert steps == [] and "edition attempted" in why
        steps, why = refresh.plan_competitive(conn, cfg, week, rr, close, close)
        assert steps == [] and "entry close" in why


def test_historical_round_refresh_still_stops_at_publication(engine, op):
    from dataclasses import dataclass

    from diski9.backend.jobs import refresh
    from diski9.backend.jobs.config import SchedulerConfig

    view, _ = publish_dev(engine, op, seed=4226)
    cfg = SchedulerConfig(
        enabled=True,
        prepare=True,
        prepare_refresh=True,
        provider_calls=True,
        prepare_streams=("beta",),
        streams=("beta",),
        max_requests_per_day=450,
        max_requests_per_tick=20,
    )

    @dataclass
    class W:
        code: str

    with transaction(engine) as conn:
        steps, why = refresh.plan(conn, cfg, W(view.code), "open", now_of(engine), now_of(engine))
    assert steps == [] and "stops at publication" in why


def test_service_errors_are_service_errors():
    assert issubclass(es.ReviewChanged, ServiceError) and issubclass(
        es.PriceExpired, ValidationFailed
    )
    assert make_round and submission_selections is not None


def test_candidate_built_from_a_football_store_is_restricted_and_refused_when_empty(
    engine, op, tmp_path
):
    from diski9.db.engine import make_engine
    from diski9.db.schema import metadata

    view, snap, _ = publish_rolling(engine, op, seed=4227)
    store = make_engine(f"sqlite:///{tmp_path / 'football.sqlite'}")
    metadata.create_all(store)
    try:
        cand = editions.build_candidate(store, engine, view.id, now_of(engine))
    finally:
        store.dispose()
    assert cand.round_id == view.code and cand.fixtures == () and cand.outcomes == ()
    with pytest.raises(editions.EditionRefused, match="no priced fixtures"):
        editions.publish_edition(engine, svc.SYSTEM, view.id, cand, source="development")


def test_consensus_reports_the_oldest_contributing_observation():
    """A partial sweep refreshes only the quotes it fetched: the market's oldest
    contributing observation stays the old one, so it is never freshened."""
    from datetime import UTC, datetime

    from diski9.api_football.markets import Market
    from diski9.odds.consensus import BookmakerInfo, QuoteEpisode, market_consensus

    at = datetime(2026, 12, 5, 12, 0, tzinfo=UTC)
    ko = at + timedelta(hours=6)
    books = {b: BookmakerInfo(b, f"B{b}", True, False, f"g{b}") for b in (1, 2, 3)}

    def q(book, outcome, odds, seen):
        return QuoteEpisode(
            bookmaker_id=book, market="1X2", outcome=outcome, decimal_odds=Decimal(odds),
            first_seen_at=seen - timedelta(hours=1), last_seen_at=seen,
            first_provider_updated_at=seen, last_provider_updated_at=seen,
        )  # fmt: skip

    fresh, old = at - timedelta(minutes=5), at - timedelta(hours=5)
    eps = [q(b, o, d, fresh if b != 3 else old) for b in (1, 2, 3)
           for o, d in (("HOME", "2.0"), ("DRAW", "3.4"), ("AWAY", "3.9"))]  # fmt: skip
    mc = market_consensus(7, Market.MATCH_RESULT, eps, books, ko, at)
    assert mc.challenge_eligible
    assert mc.latest_observation == fresh and mc.oldest_observation == old
    assert mc.oldest_provider_updated_at == old


def test_edition_step_records_its_job_and_a_refusal_writes_nothing(engine, op, tmp_path):
    from types import SimpleNamespace

    from diski9.backend.jobs import edition_step, refresh
    from diski9.backend.jobs.config import SchedulerConfig
    from diski9.db.engine import make_engine
    from diski9.db.schema import metadata

    view, snap, _ = publish_rolling(engine, op, seed=4228)
    url = f"sqlite:///{tmp_path / 'football.sqlite'}"
    fe = make_engine(url)
    metadata.create_all(fe)
    fe.dispose()
    run = SimpleNamespace(engine=engine, cfg=SchedulerConfig(), tick_id=None, token="t" * 16,
                          host="test", check=lambda: None,
                          lock=SimpleNamespace(verify=lambda: None),
                          store_factory=lambda: make_engine(url))  # fmt: skip
    slot = refresh.Slot(now_of(engine), "competitive")
    rep = edition_step.edition_step(run, SimpleNamespace(code=view.code), slot)
    assert rep.outcome == "skipped" and rep.detail.startswith("edition not written")
    with transaction(engine) as conn:
        job = conn.execute(sa.text(
            "SELECT status, error, args->>'slot' AS slot FROM app.job_runs WHERE job = "
            "'scheduler.prepare_edition' AND scope = :c"), {"c": view.code}).one()  # fmt: skip
    assert job.status == "skipped" and job.slot == slot.key(view.code)
    assert [e["edition"] for e in editions.editions(engine, view.id)] == [1]


def test_review_baseline_identity_distinguishes_goal_model_market_implied_and_none():
    """§14.4: the independent Goal Model and a reliable market-implied fit have distinct
    source and methodology identities in the item, with estimated goals at 2 decimals;
    a switch of source, or a displayed estimated-goals change, requires re-review."""
    import dataclasses
    from datetime import UTC, datetime

    from diski9.backend.devdata import dev_snapshot
    from diski9.challenge.config import get_config
    from diski9.screener import market_fit

    cfg = get_config("a3-432-v1")
    at = datetime(2026, 12, 5, 8, 0, tzinfo=UTC)
    snap = dev_snapshot(
        "dev-r2-base", at, at + timedelta(hours=4), seed=4290, config=cfg, fixtures=3
    )
    fa, fb, fc = (f.fixture_id for f in snap.fixtures)

    def strip(s, fid, groups=None):  # no independent model (and optionally thin coverage)
        outs = tuple(dataclasses.replace(o, model_probability=None,
                                         bookmaker_groups=groups or o.bookmaker_groups)
                     if o.fixture_id == fid else o for o in s.outcomes)  # fmt: skip
        fxs = tuple(dataclasses.replace(f, estimated_goals=None) if f.fixture_id == fid else f
                    for f in s.fixtures)  # fmt: skip
        return dataclasses.replace(s, outcomes=outs, fixtures=fxs)

    # fixture B's market prices are internally consistent (Poisson 1.60 / 1.10), so a
    # reliable market-implied fit exists for it (the synthetic dev prices are not)
    from diski9.screener import goal_model as gm

    mk = gm.markets(1.6, 1.1)
    names = {"HOME": "home", "DRAW": "draw", "AWAY": "away", "BTTS_YES": "btts_yes",
             "BTTS_NO": "btts_no", "OVER_2_5": "over", "UNDER_2_5": "under"}  # fmt: skip
    snap = dataclasses.replace(snap, outcomes=tuple(
        dataclasses.replace(o, market_probability=mk[names[str(o.outcome)]])
        if o.fixture_id == fb else o for o in snap.outcomes))  # fmt: skip
    snap2 = strip(strip(snap, fb), fc, groups=2)
    home = {f: snap2.outcome((f, "1X2", "HOME")) for f in (fa, fb, fc)}
    items = {f: review.item(home[f], cfg, "goal-model-1.1", snapshot=snap2) for f in home}
    eg = snap.fixture(fa).estimated_goals
    assert items[fa]["base"] == {
        "src": "goal_model", "ver": "goal-model-1.1",
        "eg": [f"{eg[0]:.2f}", f"{eg[1]:.2f}"], "bp": review._pct(home[fa].model_probability),
    }  # fmt: skip
    mf = market_fit.frozen_fit(snap2, fb)
    assert mf.reliable
    b = items[fb]["base"]
    assert b["src"] == "market_implied" and b["ver"] == mf.stamp_version
    assert b["ver"].startswith(f"mi{market_fit.FIT_VERSION}:")
    assert b["eg"] == [f"{mf.lambda_home:.2f}", f"{mf.lambda_away:.2f}"]
    assert b["bp"] == review._pct(mf.probabilities["home"])
    assert items[fc]["base"] == {"src": "none", "ver": None, "eg": None, "bp": None}
    # the same offer under another source is a different reviewed item
    as_model = review.item(snap.outcome((fb, "1X2", "HOME")), cfg, "goal-model-1.1", snapshot=snap)
    assert review.digest(as_model) != review.digest(items[fb])

    # estimated goals: a displayed (2-decimal) change requires re-review, a smaller one not
    def with_eg(goals):
        s = dataclasses.replace(snap, fixtures=tuple(
            dataclasses.replace(f, estimated_goals=goals) if f.fixture_id == fa else f
            for f in snap.fixtures))  # fmt: skip
        return review.digest(review.item(home[fa], cfg, "goal-model-1.1", snapshot=s))

    base = (round(eg[0], 2), round(eg[1], 2))
    assert (
        with_eg(base) == with_eg((base[0] + 0.001, base[1])) != with_eg((base[0] + 0.01, base[1]))
    )
    # a methodology version change is a different identity
    assert review.digest(review.item(home[fa], cfg, "goal-model-1.2", snapshot=snap2)) != \
        review.digest(items[fa])  # fmt: skip


def test_missed_competitive_slots_resume_with_the_current_slot_only(engine, op):
    """Review 2.1: after three consecutive missed sweeps the planner neither replays nor
    reconciles them: it works only the current slot (one sweep's requests, within the
    unchanged caps). Meanwhile prices age past six hours and entry pauses; a new edition
    carrying the old evidence stays paused; a fresh sweep's edition restores it."""
    from dataclasses import dataclass
    from types import SimpleNamespace

    from diski9.backend.jobs import refresh
    from diski9.backend.jobs.config import SchedulerConfig
    from diski9.backend.repositories import ops

    view, snap, _ = publish_rolling(engine, op, seed=4291)
    cfg = SchedulerConfig()
    with transaction(engine) as conn:
        row = refresh._round_row(conn, view.code)
    rr = SimpleNamespace(**dict(row._mapping))
    # four slots due (06:15, 09:15, 12:15, 15:15 after the window start), none worked
    rr.window_start_at = rr.published_at - timedelta(hours=15, minutes=15, milliseconds=500)
    rr.published_at = rr.window_start_at + timedelta(hours=6)

    @dataclass
    class W:
        code: str

    week, now = W(view.code), now_of(engine)
    due = [s for s in refresh.competitive_slots(rr.window_start_at, rr.deadline_at)
           if s.at <= now]  # fmt: skip
    assert len(due) == 4
    with transaction(engine) as conn:
        # a partial sweep of the first slot, then three missed slots
        lg0 = refresh.competitive_leagues(conn, view.id, now)[0]
        rid = ops.start_job(conn, refresh.PREPARE_REFRESH, f"{view.code}:{lg0}",
                            {"slot": due[0].key(view.code), "at": now.isoformat()})  # fmt: skip
        ops.finish_job(conn, rid, "succeeded")
        steps, _ = refresh.plan_competitive(conn, cfg, week, rr, now, now)
        leagues = refresh.competitive_leagues(conn, view.id, now)
    assert [s.kind for s in steps] == ["league"] * len(leagues)
    assert {s.slot.key(view.code) for s in steps} == {due[-1].key(view.code)}  # no replay
    assert len(steps) <= cfg.max_requests_per_tick  # one sweep, inside the per-tick cap
    # the prices the round still holds were observed before the outage: paused
    old = now - timedelta(hours=7)
    publish_edition(engine, view, snap, observed=old)
    assert editions.round_availability(engine, view.id).status == "paused"
    publish_edition(engine, view, snap, observed=old)  # a new edition is not new evidence
    assert editions.round_availability(engine, view.id).status == "paused"
    # the current slot's sweep completes and its edition carries fresh evidence: open
    publish_edition(engine, view, snap)
    assert editions.round_availability(engine, view.id).status == "open"


# ------------------------------------------------------------------ fixture membership
def _without_offers(fid):
    import dataclasses

    def t(snap):
        return dataclasses.replace(snap, outcomes=tuple(o for o in snap.outcomes
                                                        if o.fixture_id != fid))  # fmt: skip

    return t


def test_universe_fixture_unpriced_at_publication_becomes_selectable_and_can_pause(engine, op):
    """P8-MEMBER (freeze membership, not eligibility): a fixture with no eligible offer
    at publication still belongs to edition 1; it is unavailable until a later edition
    prices it with qualifying coverage, may lose eligibility again (two bookmaker
    groups) and recover. Nothing outside edition 1 is ever admitted."""
    import dataclasses

    seen = {}

    def unpriced_last(full):  # the latest kickoff ("Saturday") has no eligible offer yet
        seen["full"] = full
        seen["late"] = full.fixtures[-1].fixture_id
        return _without_offers(seen["late"])(full)

    view, snap, close = publish_rolling(engine, op, seed=4292, transform=unpriced_last)
    full, late = seen["full"], seen["late"]
    universe = count(engine, "SELECT count(*) FROM app.snapshot_fixtures f JOIN "
                     "app.round_snapshots s ON s.id = f.snapshot_id WHERE s.round_id = :r "
                     "AND s.edition = 1 AND f.fixture_id = :f", r=view.id, f=late)  # fmt: skip
    assert universe == 1 and not [o for o in snap.outcomes if o.fixture_id == late]
    # the settlement cutoff counts the unpriced fixture's kickoff (it is in the universe)
    with transaction(engine) as conn:
        cutoff = conn.execute(sa.text("SELECT settle_cutoff_at FROM app.rounds WHERE id = :r"),
                              {"r": view.id}).scalar_one()  # fmt: skip
    assert cutoff == max(full.fixtures[-1].kickoff, close) + timedelta(hours=24)
    # the planner still sweeps its league
    from diski9.backend.jobs import refresh

    with transaction(engine) as conn:
        assert full.fixtures[-1].league_id in refresh.competitive_leagues(
            conn, view.id, now_of(engine))  # fmt: skip
    p = principal(engine)
    # a valid A3 portfolio that includes the late fixture (its offers considered first)
    first = dataclasses.replace(full, outcomes=tuple(
        sorted(full.outcomes, key=lambda o: o.fixture_id != late)))  # fmt: skip
    chosen = keys_excluding(first)
    assert any(k["fixture_id"] == late for k in chosen)
    with pytest.raises(ValidationFailed):  # not selectable while it has no offer
        save(engine, p, view, chosen)
    # a Saturday sweep reaches three qualifying groups: a later edition offers it
    priced = full
    publish_edition(engine, view, priced)
    d = save(engine, p, view, chosen)
    r = review.review_portfolio(engine, p, view.id)
    assert r.ready, r.problems
    # coverage falls to two groups: unavailable again (the offer stays out of sync)
    thin = dataclasses.replace(priced, outcomes=tuple(
        dataclasses.replace(o, bookmaker_groups=2) if o.fixture_id == late else o
        for o in priced.outcomes))  # fmt: skip
    publish_edition(engine, view, thin)
    r = review.review_portfolio(engine, p, view.id)
    assert {x["reason"] for x in r.problems} == {"ineligible"}
    with pytest.raises(es.ValidationFailed):
        confirm(engine, p, view, d)
    # and recovers; the confirmation copies the current edition's values
    publish_edition(engine, view, priced)
    sub = confirm(engine, p, view, d)
    assert sub is not None
    assert count(engine, "SELECT count(*) FROM app.submission_selections ss JOIN "
                 "app.submissions s ON s.id = ss.submission_id WHERE s.round_id = :r "
                 "AND ss.fixture_id = :f", r=view.id, f=late) == 1  # fmt: skip
