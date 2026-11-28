"""Phase 8 CP3A-R R1: the rolling-entry lifecycle on real PostgreSQL.

Rolling-entry rounds (rules ``rolling/v1``) are created only in this disposable test
database, on their own schedule codes, so no other test and no hosted database sees
them. Every rolling behaviour is checked next to the unchanged historical
(``settle/v1``) behaviour:

* publication: one fixed entry close instead of the common deadline;
* confirmation: the per-fixture 15-minute cutoff, one irrevocable final submission
  (no replacement, withdrawal or resubmission), idempotent retries, concurrency,
  the deadline after lock acquisition, participant and round isolation;
* settlement: entry-level V3 (each entry's own submission time) against
  round-level V3 for historical rounds;
* privacy: the provisional board shows only the viewer's own row until official
  results are published.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from pg_helpers import make_user, unique
from settle_helpers import (
    DEFAULT_ENTRY,
    confirm_entry,
    make_settlement_round,
    provider_item,
    shifted,
)
from svc_helpers import principal, publish_dev, valid_keys, wait_until

from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    entries,
    entry_settlements,
    round_schedules,
    selection_verdicts,
    submissions,
)
from diski9.backend.devdata import dev_snapshot
from diski9.backend.repositories import results as results_repo
from diski9.backend.repositories import rounds as rounds_repo
from diski9.backend.services import corrections as co
from diski9.backend.services import drafts, review, rolling
from diski9.backend.services import entries as es
from diski9.backend.services import leaderboards as lb
from diski9.backend.services import participant_results as pr
from diski9.backend.services import results as rs
from diski9.backend.services import rounds as svc
from diski9.backend.services import settlement as st
from diski9.backend.services.common import PublicationRefused, RoundClosed
from diski9.challenge.config import get_config
from diski9.challenge.structured import selection_blocks
from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

WIN = {"HOME": (1, 0), "BTTS_YES": (1, 1), "UNDER_2_5": (0, 0), "AWAY": (0, 1)}


def key() -> str:
    return "r1-" + uuid.uuid4().hex


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


# ------------------------------------------------------------------ helpers
def rolling_schedule(engine, *, close_at=None, buffer: int = 15, publish_rule=None,
                     settle_hours: int = rolling.ROLLING_SETTLE_CUTOFF_HOURS) -> str:  # fmt: skip
    """A rolling-entry schedule on its own code (copied from the current weekend row).
    ``close_at``: the entry close as a weekday and time in UTC (tests run on any day);
    the production rule (Sunday 14:00 SAST) is covered by the pure tests."""
    with transaction(engine) as conn:
        base = conn.execute(
            sa.select(round_schedules)
            .where(round_schedules.c.code == "weekend", round_schedules.c.active_to.is_(None))
        ).one()  # fmt: skip
        row = {k: v for k, v in base._mapping.items() if k not in ("id", "active_to")}
        code = unique("rolling")
        if publish_rule is None:
            publish_rule = dict(rolling.ROLLING_PUBLISH_RULE)
            publish_rule["entry_close"] = {
                "weekday": rolling.WEEKDAYS[close_at.weekday()],
                "time": close_at.strftime("%H:%M:%S"),
                "tz": "UTC",
            }
        row.update(
            code=code,
            version=1,
            rules_version=rolling.ROLLING_RULES_VERSION,
            window_rule=rolling.ROLLING_WINDOW_RULE,
            publish_rule=publish_rule,
            deadline_buffer_minutes=buffer,
            settle_cutoff_hours=settle_hours,
        )
        conn.execute(sa.insert(round_schedules).values(**row))
    return code


def publish_rolling(engine, op, *, close_in=timedelta(days=1), first_kickoff_in=timedelta(hours=1),
                    seed=2026, publish_rule=None, settle_hours=None):  # fmt: skip
    """Create and publish a development rolling-entry round. Returns (view, snapshot,
    entry close)."""
    with transaction(engine) as conn:
        now = db_now(conn)
    close = (now + close_in).replace(microsecond=0)
    code = rolling_schedule(
        engine,
        close_at=close,
        publish_rule=publish_rule,
        settle_hours=settle_hours or rolling.ROLLING_SETTLE_CUTOFF_HOURS,
    )
    rcode = unique("dev-r1")
    with transaction(engine) as conn:
        cfg = conn.execute(
            sa.select(round_schedules.c.config_version).where(round_schedules.c.code == code)
        ).scalar_one()
    snap = dev_snapshot(rcode, now, now + first_kickoff_in, seed=seed, config=get_config(cfg))
    v = svc.create_round(engine, op, code=rcode, window_start=snap.window[0],
                         window_end=snap.window[1], schedule_code=code, development=True)  # fmt: skip
    return svc.publish_round(engine, op, v.id, snap, source="development"), snap, close


def keys_excluding(snap, exclude: set[int], n: int = 9) -> list[dict]:
    """A completable selection that avoids the given fixtures."""
    pool = [o for o in snap.outcomes if o.fixture_id not in exclude]
    chosen = []
    for o in pool:
        if len(chosen) == n:
            break
        if selection_blocks(chosen, pool, snap.snapshot_at, snap.config).get(o.key) is None:
            chosen.append(o)
    assert len(chosen) == n
    return [{"fixture_id": o.fixture_id, "market": str(o.market), "outcome": str(o.outcome)}
            for o in chosen]  # fmt: skip


def save(engine, p, view, keys, version=0):
    return drafts.save_draft(engine, p, view.id, keys, expected_version=version)


def confirm(engine, p, view, d, version=0, **kw):
    """Confirm as a participant would: rolling rounds first review the portfolio and
    send back the item digests they accepted (R2)."""
    if "reviewed" not in kw and view.rules_version == rolling.ROLLING_RULES_VERSION:
        kw["reviewed"] = list(review.review_portfolio(engine, p, view.id).digests)
    return es.confirm_entry(engine, p, view.id, draft_version=d.version,
                            expected_entry_version=version,
                            idempotency_key=kw.pop("k", key()), **kw)  # fmt: skip


def n_submissions(engine, round_id, user_id=None) -> int:
    with transaction(engine) as conn:
        q = sa.select(sa.func.count()).select_from(submissions)
        q = q.where(submissions.c.round_id == round_id)
        if user_id is not None:
            q = q.where(submissions.c.user_id == user_id)
        return conn.execute(q).scalar_one()


# ------------------------------------------------------------------ publication
def test_rolling_round_publishes_with_the_fixed_entry_close(engine, op):
    view, snap, close = publish_rolling(engine, op, close_in=timedelta(days=1))
    assert view.rules_version == rolling.ROLLING_RULES_VERSION
    assert view.deadline_at == close  # the entry close, not earliest kickoff - 15 min
    assert view.deadline_at > snap.earliest_kickoff  # fixtures kick off while entry is open
    assert view.settle_cutoff_at > view.deadline_at
    assert view.status == "open"


def test_historical_round_keeps_the_common_deadline(engine, op):
    view, snap = publish_dev(engine, op)
    assert view.rules_version == "settle/v1"
    assert view.deadline_at == snap.earliest_kickoff - timedelta(minutes=15)
    # unchanged 48-hour settlement allowance from the latest kickoff
    latest = max(f.kickoff for f in snap.fixtures)
    assert view.settle_cutoff_at == latest + timedelta(hours=48)


def test_rolling_cutoff_when_the_last_kickoff_is_before_the_close(engine, op):
    # 20 fixtures 2 h apart from +1 h: the last kicks off at +39 h, the close is +2 days
    view, snap, close = publish_rolling(engine, op, close_in=timedelta(days=2), seed=3105)
    latest = max(f.kickoff for f in snap.fixtures)
    assert latest < close
    assert view.settle_cutoff_at == close + timedelta(hours=24)


def test_rolling_cutoff_when_the_last_kickoff_is_after_the_close(engine, op):
    view, snap, close = publish_rolling(engine, op, close_in=timedelta(days=1), seed=3106)
    latest = max(f.kickoff for f in snap.fixtures)
    assert latest > close
    assert view.settle_cutoff_at == latest + timedelta(hours=24)


def test_rolling_schedule_with_another_settlement_allowance_is_refused(engine, op):
    with pytest.raises(PublicationRefused, match="settlement allowance must be 24 hours"):
        publish_rolling(engine, op, settle_hours=48, seed=3107)


def test_settlement_cutoff_is_fixed_at_publication(engine, op):
    view, _, _ = publish_rolling(engine, op, seed=3108)
    # set once (app_0003/app_0006 guard)
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(sa.text("UPDATE app.rounds SET settle_cutoff_at = settle_cutoff_at "
                                 "+ interval '1 hour' WHERE id = :r"), {"r": view.id})  # fmt: skip


def test_rolling_publication_fails_safe_on_a_bad_or_past_entry_close(engine, op):
    with pytest.raises(PublicationRefused, match="misconfigured"):
        publish_rolling(engine, op, publish_rule={"weekday": "friday", "time": "08:00"})
    with pytest.raises(PublicationRefused, match="already passed"):
        publish_rolling(engine, op, close_in=timedelta(seconds=-30))


def test_rolling_rounds_are_bound_through_the_normal_schedule_resolution(engine, op):
    """A round created under a rolling schedule row takes that row's rules version at
    publication; a draft under the weekend schedule is unaffected (dormant code)."""
    view, _, _ = publish_rolling(engine, op)
    with transaction(engine) as conn:
        bound = conn.execute(
            sa.text("SELECT s.rules_version FROM app.rounds r JOIN app.round_schedules s "
                    "ON s.id = r.schedule_id WHERE r.id = :r"), {"r": view.id}
        ).scalar_one()  # fmt: skip
        weekend = conn.execute(
            sa.text("SELECT rules_version FROM app.round_schedules WHERE code = 'weekend' "
                    "AND active_to IS NULL")
        ).scalar_one()  # fmt: skip
    assert bound == view.rules_version == rolling.ROLLING_RULES_VERSION
    assert weekend == "settle/v1"  # no rolling row on the standard schedule


# ------------------------------------------------------------------ confirmation
@pytest.fixture(scope="module")
def near(engine, op):
    """A rolling round whose first fixture kicks off in 10 minutes (inside its cutoff)."""
    return publish_rolling(engine, op, first_kickoff_in=timedelta(minutes=10), seed=3101)


def test_drafts_stay_editable_before_the_final_submission(engine, near):
    view, snap, _ = near
    p = principal(engine)
    first = valid_keys(snap, 4)
    d1 = save(engine, p, view, first)
    d2 = save(engine, p, view, keys_excluding(snap, {snap.fixtures[0].fixture_id}), d1.version)
    assert d2.version == d1.version + 1 and len(d2.selections) == 9
    assert n_submissions(engine, view.id, p.user_id) == 0


def test_a_fixture_inside_its_cutoff_is_refused_and_nothing_is_written(engine, near):
    view, snap, _ = near
    first = snap.fixtures[0].fixture_id
    p = principal(engine)
    keys = valid_keys(snap)
    assert first in {k["fixture_id"] for k in keys}
    d = save(engine, p, view, keys)
    with pytest.raises(es.FixtureClosed) as exc:
        confirm(engine, p, view, d)
    assert exc.value.code == "fixture_closed"
    assert [i["fixture_id"] for i in exc.value.issues] == [first]
    assert n_submissions(engine, view.id, p.user_id) == 0
    # the draft is never changed by the refusal; replacing the match lets it through
    d2 = save(engine, p, view, keys_excluding(snap, {first}), d.version)
    e = confirm(engine, p, view, d2)
    assert e.active and e.current.version == 1
    assert first not in {s["fixture_id"] for s in e.current.selections}


def test_final_submission_is_irrevocable_and_retries_are_idempotent(engine, near):
    view, snap, _ = near
    p = principal(engine)
    d = save(engine, p, view, keys_excluding(snap, {snap.fixtures[0].fixture_id}))
    k = key()
    e = confirm(engine, p, view, d, k=k)
    assert e.active and e.current.version == 1
    again = confirm(engine, p, view, d, k=k)  # the same request retried
    assert again.current.id == e.current.id
    with pytest.raises(es.SubmissionFinal):  # resubmission with a new request
        confirm(engine, p, view, d, version=e.version)
    with pytest.raises(es.SubmissionFinal):  # explicit replacement
        confirm(engine, p, view, d, version=e.version, replace=True)
    with pytest.raises(es.SubmissionFinal):  # withdrawal
        es.withdraw_entry(engine, p, view.id, expected_entry_version=e.version)
    # an edited draft cannot be resubmitted either
    d2 = save(engine, p, view, keys_excluding(snap, {snap.fixtures[0].fixture_id,
                                                     snap.fixtures[1].fixture_id}), d.version)  # fmt: skip
    with pytest.raises(es.SubmissionFinal):
        confirm(engine, p, view, d2, version=e.version)
    after = es.get_entry(engine, p, view.id)
    assert after.current.id == e.current.id and after.state == "confirmed"
    assert [x.kind for x in after.history] == ["confirmed"]
    assert n_submissions(engine, view.id, p.user_id) == 1


def test_concurrent_confirmations_from_one_participant_store_one_submission(engine, near):
    view, snap, _ = near
    p = principal(engine)
    d = save(engine, p, view, keys_excluding(snap, {snap.fixtures[0].fixture_id}))
    results, barrier = [], threading.Barrier(4)

    def attempt():
        barrier.wait()
        try:
            results.append(confirm(engine, p, view, d))
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ok = [r for r in results if isinstance(r, es.EntryView)]
    refused = [r for r in results if not isinstance(r, es.EntryView)]
    assert len(ok) == 1 and len(refused) == 3
    assert all(isinstance(r, es.SubmissionFinal | es.VersionConflict) for r in refused), refused
    assert n_submissions(engine, view.id, p.user_id) == 1


def test_participants_and_rounds_are_isolated(engine, op, near):
    view, snap, _ = near
    other, osnap, _ = publish_rolling(engine, op, seed=3102)
    a, b = principal(engine), principal(engine)
    keys = keys_excluding(snap, {snap.fixtures[0].fixture_id})
    confirm(engine, a, view, save(engine, a, view, keys))
    # another participant can still enter the same round
    eb = confirm(engine, b, view, save(engine, b, view, keys))
    assert eb.active
    # a final submission in one round does not affect the participant's next round
    ea2 = confirm(engine, a, other, save(engine, a, other, valid_keys(osnap)))
    assert ea2.active and ea2.current.version == 1
    assert n_submissions(engine, view.id, a.user_id) == n_submissions(engine, other.id, a.user_id)


def test_entry_closes_at_the_entry_close_checked_after_the_locks(engine, op):
    view, snap, close = publish_rolling(engine, op, close_in=timedelta(seconds=12),
                                        first_kickoff_in=timedelta(hours=2), seed=3103)  # fmt: skip
    keys = valid_keys(snap)
    early, waiter, late = principal(engine), principal(engine), principal(engine)
    e = confirm(engine, early, view, save(engine, early, view, keys))  # before the close
    assert e.active
    dw = save(engine, waiter, view, keys)
    dl = save(engine, late, view, keys)
    # a confirmation that starts before the close but waits on the round lock past it
    wait_until(engine, close - timedelta(milliseconds=900))
    held, out = threading.Event(), []

    def blocker():
        with transaction(engine) as conn:
            rounds_repo.lock_round_for_change(conn, view.id)
            held.set()
            time.sleep(1.6)  # releases about 0.7 s after the close (lock_timeout is 2 s)

    t = threading.Thread(target=blocker)
    t.start()
    held.wait()
    try:
        confirm(engine, waiter, view, dw)
    except Exception as exc:  # noqa: BLE001
        out.append(exc)
    t.join()
    assert len(out) == 1 and isinstance(out[0], RoundClosed), out
    with pytest.raises(RoundClosed):  # after the close
        confirm(engine, late, view, dl)
    locked = svc.lock_round(engine, svc.SYSTEM, view.id)
    assert locked.locked_entries == 1 and locked.designation == "practice"
    assert n_submissions(engine, view.id) == 1


def test_historical_round_still_allows_replacement_and_withdrawal(engine, op):
    view, snap = publish_dev(engine, op, seed=3104)
    p = principal(engine)
    d = save(engine, p, view, valid_keys(snap))
    e = confirm(engine, p, view, d)
    e2 = confirm(engine, p, view, d, version=e.version, replace=True)
    assert e2.current.version == 2
    w = es.withdraw_entry(engine, p, view.id, expected_entry_version=e2.version)
    assert w.state == "withdrawn"


# ------------------------------------------------------------------ settlement (V3)
def record(engine, fid, at, status, ko, h=None, a=None):
    wait_until(engine, at)
    item = provider_item(fid, status, ko=ko, h=h, a=a)
    with transaction(engine) as conn:
        return results_repo.record_evidence(
            conn, source="api-football", fixture_id=fid, observed_at=at, raw=item,
            raw_hash=canonical_hash(item), fields=evidence_fields(item),
        )  # fmt: skip


def legs_of(engine, entry_id):
    with transaction(engine) as conn:
        row = conn.execute(
            sa.select(entry_settlements).where(entry_settlements.c.entry_id == entry_id)
            .order_by(entry_settlements.c.revision.desc()).limit(1)
        ).one()  # fmt: skip
    return row, {leg["position"]: leg for leg in row.legs["legs"]}


@pytest.fixture(scope="module")
def v3(engine):
    """A rolling round with an early entrant (A) and a later entrant (B), and a
    historical round with the same structure. Fixtures 0-8 kick off between A's and
    B's submissions (fixture 2 with a recorded in-play status); 9-17 after the close.
    """
    with transaction(engine) as conn:
        roll = make_settlement_round(conn, deadline_in=timedelta(seconds=9),
                                     rules_version=rolling.ROLLING_RULES_VERSION)  # fmt: skip
        hist = make_settlement_round(conn, deadline_in=timedelta(seconds=9))
        ua, uh = make_user(conn), make_user(conn)
        ea, _ = confirm_entry(conn, roll[0], roll[1], roll[2], ua, DEFAULT_ENTRY)
        eh, _ = confirm_entry(conn, hist[0], hist[1], hist[2], uh, DEFAULT_ENTRY)
    with transaction(engine) as conn:
        ta = conn.execute(sa.select(submissions.c.submitted_at).join(
            entries, entries.c.current_submission_id == submissions.c.id
        ).where(entries.c.id == ea)).scalar_one()  # fmt: skip
    early_ko = ta + timedelta(seconds=1)
    record(engine, roll[2][2], early_ko + timedelta(milliseconds=300), "1H", early_ko)
    wait_until(engine, early_ko + timedelta(milliseconds=600))
    with transaction(engine) as conn:
        ub = make_user(conn)
        eb, _ = confirm_entry(conn, roll[0], roll[1], roll[2], ub, shifted(2))
    deadline = max(roll[3], hist[3])
    wait_until(engine, deadline)
    for w in (roll, hist):
        svc.lock_round(engine, svc.SYSTEM, w[0])
    at = deadline + timedelta(milliseconds=1500)
    late_ko = deadline + timedelta(seconds=1)
    for w in (roll, hist):
        fids = w[2]
        for i, (_, _, o) in enumerate(DEFAULT_ENTRY):
            record(engine, fids[i], at, "FT", early_ko, *WIN[o])
        for i in (9, 10):
            record(engine, fids[i], at, "FT", late_ko, *WIN["AWAY"])
    return {"roll": roll, "hist": hist, "A": ea, "B": eb, "H": eh, "ua": ua, "ub": ub,
            "ta": ta, "early_ko": early_ko}  # fmt: skip


def test_early_entry_on_a_fixture_that_starts_before_the_close_stays_valid(engine, op, v3):
    """A (Friday-style) entry whose matches kick off after its submission but before the
    entry close settles normally under entry-level V3."""
    st.settle_round(engine, op, v3["roll"][0])
    row, legs = legs_of(engine, v3["A"])
    assert v3["early_ko"] > v3["ta"] and v3["early_ko"] < v3["roll"][3]
    assert [legs[i]["verdict"] for i in range(9)] == ["won"] * 9
    assert not any("entry_rule" in leg for leg in legs.values())
    assert row.complete and row.gross > Decimal("100.00")


def test_later_entry_voids_only_the_matches_already_started_for_it(engine, op, v3):
    st.settle_round(engine, op, v3["roll"][0])
    _, legs = legs_of(engine, v3["B"])
    # B's positions 0-6 are fixtures 2-8 (kicked off before B submitted); 7-8 are 9-10
    assert [legs[i]["verdict"] for i in range(7)] == ["void"] * 7
    assert legs[0]["entry_rule"] == "V3-started"  # an in-play status recorded before B
    assert {legs[i]["entry_rule"] for i in range(1, 7)} == {"V3-rescheduled"}
    assert [legs[i]["verdict"] for i in (7, 8)] == ["won", "won"]
    # the same outcome is valid for A and void for B: the round-level verdict follows
    # the earliest entrant, the entry-level verdict is kept on B's own settlement
    with transaction(engine) as conn:
        v = conn.execute(sa.select(selection_verdicts).where(
            selection_verdicts.c.round_id == v3["roll"][0],
            selection_verdicts.c.fixture_id == v3["roll"][2][3],
        ).order_by(selection_verdicts.c.revision.desc()).limit(1)).one()  # fmt: skip
    assert (v.verdict, v.rule) == ("won", "settle")
    mine = pr.my_settlement(engine, principal(engine, user_id=v3["ub"]), v3["roll"][0])
    first = next(p for p in mine.predictions if p.position == 0)
    assert first.verdict == "void" and first.rule == "V3-started"
    assert "before your portfolio was submitted" in first.void_reason


def test_historical_round_keeps_round_level_v3(engine, op, v3):
    st.settle_round(engine, op, v3["hist"][0])
    row, legs = legs_of(engine, v3["H"])
    assert [legs[i]["verdict"] for i in range(9)] == ["void"] * 9  # started before deadline
    assert not any("entry_rule" in leg for leg in legs.values())
    assert row.basis == "all_void" and row.gross == Decimal("100.00")


def test_settlement_rerun_with_the_same_evidence_changes_nothing(engine, op, v3):
    st.settle_round(engine, op, v3["roll"][0])
    again = st.settle_round(engine, op, v3["roll"][0])
    assert again.changed_verdicts == 0 and not again.material


# ------------------------------------------------------------------ privacy
@pytest.fixture(scope="module")
def private(engine, op):
    """A development rolling round and a historical one, three entries each, settled
    with synthetic results (not yet finalised)."""
    worlds = {}
    with transaction(engine) as conn:
        for name, rules in (("roll", rolling.ROLLING_RULES_VERSION), ("hist", "settle/v1")):
            rid, snap, fids, deadline, cutoff = make_settlement_round(
                conn, deadline_in=timedelta(seconds=4), cutoff_after=timedelta(seconds=3),
                development=True, rules_version=rules,
            )  # fmt: skip
            users = [make_user(conn) for _ in range(3)]
            for u, spec in zip(users, (DEFAULT_ENTRY, shifted(1), shifted(2)), strict=True):
                confirm_entry(conn, rid, snap, fids, u, spec)
            worlds[name] = {"round": rid, "fixtures": fids, "deadline": deadline,
                            "cutoff": cutoff, "users": users}  # fmt: skip
    wait_until(engine, max(w["deadline"] for w in worlds.values()))
    for w in worlds.values():
        svc.lock_round(engine, svc.SYSTEM, w["round"])
        rs.set_result_mode(engine, op, w["round"], "synthetic")
    at = max(w["deadline"] for w in worlds.values()) + timedelta(milliseconds=1500)
    wait_until(engine, at)
    for w in worlds.values():
        for fid in w["fixtures"]:
            rs.record_synthetic_observation(engine, op, w["round"], fid, observed_at=at,
                                            status="FT", kickoff_at=w["deadline"] +
                                            timedelta(seconds=1), ft_home=1, ft_away=0)  # fmt: skip
    for w in worlds.values():
        wait_until(engine, w["cutoff"] + timedelta(milliseconds=200))
        st.settle_round(engine, op, w["round"])
    lb.clear_cache()
    return worlds


def board(engine, w, viewer=None):
    return lb.weekly_board(engine, w["round"], viewer=viewer, include_development=True)


def test_provisional_board_shows_only_my_own_row(engine, private):
    w = private["roll"]
    me = principal(engine, user_id=w["users"][0])
    b = board(engine, w, me)
    assert b.state == "provisional" and b.private_until_published
    assert len(b.rows) == 1 and b.rows[0].is_me and b.me is not None and b.me.is_me
    assert b.me.position is None and b.total == 1
    assert b.settled_predictions is None and b.pending_predictions is None
    assert b.me.returned is not None  # my own provisional progress stays visible


def test_guests_and_non_entrants_see_no_provisional_rows(engine, private):
    w = private["roll"]
    for viewer in (None, principal(engine)):
        b = board(engine, w, viewer)
        assert b.rows == () and b.me is None and b.private_until_published


def test_historical_provisional_board_is_unchanged(engine, private):
    w = private["hist"]
    b = board(engine, w, principal(engine, user_id=w["users"][0]))
    assert b.state == "provisional" and not b.private_until_published
    assert len(b.rows) == 3 and b.settled_predictions is not None


def test_published_results_become_visible_through_finalisation(engine, op, private):
    w = private["roll"]
    with transaction(engine) as conn:
        r = conn.execute(sa.text("SELECT * FROM app.rounds WHERE id = :r"),
                         {"r": w["round"]}).one()  # fmt: skip
        earliest = st.earliest_finalisation(conn, r)
        last = st.last_material_change(conn, w["round"])
    # finalisation never precedes cutoff + the unchanged 24-hour correction window
    assert r.correction_window_hours == 24
    assert earliest == max(r.settle_cutoff_at, last) + timedelta(hours=24)
    early = co.finalise_round(engine, op, w["round"], as_of=earliest - timedelta(seconds=1))
    assert not early.finalised and "correction window" in early.reason
    out = co.finalise_round(engine, op, w["round"], as_of=earliest)
    assert out.finalised, out.reason
    lb.clear_cache()
    b = board(engine, w, principal(engine, user_id=w["users"][0]))
    assert b.state == "final" and not b.private_until_published
    assert len(b.rows) == 3
    guest = board(engine, w)
    assert len(guest.rows) == 3
