"""Phase 6C.6 Stage E.1b: the provider ledger — request classes, the protected results
reserve, persisted pacing, cooldowns and quota observations (isolated PostgreSQL).

Pacing is exercised with the real database clock and real (short) sleeps: every
reservation commits its send slot before anyone sleeps, so a second caller —
another thread, another tick or a restarted process — is always placed at least the
minimum interval after it."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import drop, isolated_engine

from diski9.backend.db import transaction
from diski9.backend.jobs import locking
from diski9.backend.jobs.locking import (
    PREPARATION,
    RESULTS,
    BudgetExhausted,
    Caps,
    PacingBacklog,
    ProviderCooldown,
)

CAPS = Caps(per_tick=20, per_day=30, nonessential=12, results_reserve=10)


@pytest.fixture
def db(pg_url, request):
    name = f"diski9_rb_{request.node.name[:33].lower()}_test".replace("[", "_").replace("]", "")
    eng, url = isolated_engine(pg_url, name)
    try:
        yield eng
    finally:
        eng.dispose()
        drop(pg_url, name)


def res(eng, token="t1", klass=RESULTS, caps=CAPS, **kw):
    return locking.reserve(eng, token=token, tick_id=1, scope="s", per_tick=caps.per_tick,
                           per_day=caps.per_day, klass=klass, caps=caps, **kw)  # fmt: skip


def ledger(eng):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT args, started_at FROM app.job_runs WHERE job = 'scheduler.provider' "
            "ORDER BY started_at, id")).all()  # fmt: skip


def gaps(rows):
    t = [r.started_at for r in rows]
    return [(b - a).total_seconds() for a, b in zip(t, t[1:], strict=False)]


# ------------------------------------------------------------------ classes and reserve
def test_preparation_can_never_use_the_results_reserve(db):
    for _ in range(12):
        res(db, klass=PREPARATION)
    with pytest.raises(BudgetExhausted, match="non-essential cap"):
        res(db, klass=PREPARATION)
    for _ in range(8):  # results still have 30 - 12 = 18; the reserve is untouched
        res(db, token="t2")
    # 20 used in 24 h: preparation would now enter the reserve (30 - 10 = 20)
    with pytest.raises(BudgetExhausted):
        res(db, token="t3", klass=PREPARATION, caps=Caps(20, 30, None, 10))
    for _ in range(10):
        res(db, token="t4")  # results may use the whole 24-hour cap
    with pytest.raises(BudgetExhausted, match="24-hour cap"):
        res(db, token="t5")


def test_reserve_limits_preparation_before_its_own_cap(db):
    caps = Caps(per_tick=50, per_day=30, nonessential=100, results_reserve=10)
    for _ in range(15):
        res(db, token="r", caps=caps)  # results traffic first
    for _ in range(5):
        res(db, token="p", klass=PREPARATION, caps=caps)
    with pytest.raises(BudgetExhausted, match="results reserve"):
        res(db, token="p", klass=PREPARATION, caps=caps)  # 20 used = 30 - 10
    assert locking.allowance(db, "x", 50, 30, klass=PREPARATION, caps=caps) == (
        0,
        "results reserve",
    )
    assert locking.allowance(db, "x", 50, 30)[0] == 10  # results: the reserve remains


def test_per_tick_cap_counts_every_class(db):
    caps = Caps(per_tick=3, per_day=100, nonessential=50, results_reserve=10)
    res(db, caps=caps)
    res(db, klass=PREPARATION, caps=caps)
    res(db, klass=PREPARATION, caps=caps)
    with pytest.raises(BudgetExhausted, match="per-tick cap"):
        res(db, caps=caps)


def test_rows_without_a_class_count_as_results(db):
    """D-2: ledger rows written before E.1b carry no class."""
    with transaction(db) as conn:
        for _ in range(5):
            conn.execute(sa.text(
                "INSERT INTO app.job_runs (job, scope, args, status, started_at, finished_at, "
                "api_requests) VALUES ('scheduler.provider', 'old', "
                "'{\"run_token\": \"old\"}'::jsonb, 'succeeded', now(), now(), 1)"))  # fmt: skip
        tick, day, prep = locking.usage_by_class(conn, "x")
    assert (tick, day, prep) == (0, 5, 0)
    assert all(r.args.get("class") is None for r in ledger(db))


def test_every_reservation_records_its_class(db):
    res(db)
    res(db, klass=PREPARATION)
    assert [r.args["class"] for r in ledger(db)] == ["results", "preparation"]


# ------------------------------------------------------------------ pacing
INTERVAL = 0.4


def test_sequential_reservations_get_spaced_send_slots(db):
    for _ in range(4):
        wait = res(db, interval=INTERVAL, max_wait=5)
        time.sleep(wait)
    assert all(g >= INTERVAL - 0.01 for g in gaps(ledger(db)))


def test_pacing_holds_across_ticks_and_process_restarts(db):
    """Two ticks (different run tokens) and a fresh engine (a restarted process):
    the next slot is computed from the ledger, not from process memory."""
    res(db, token="tick-1", interval=INTERVAL, max_wait=5)  # not slept: crashed before send
    restarted = sa.create_engine(db.url)
    try:
        wait = res(restarted, token="tick-2", interval=INTERVAL, max_wait=5)
    finally:
        restarted.dispose()
    assert wait >= INTERVAL - 0.05
    assert gaps(ledger(db)) == [pytest.approx(INTERVAL, abs=0.01)]


def test_concurrent_reservations_receive_distinct_spaced_slots(db):
    waits: list[float] = []
    errors: list[BaseException] = []

    def worker(token):
        try:
            for _ in range(3):
                w = res(db, token=token, interval=INTERVAL, max_wait=10)
                waits.append(w)
                time.sleep(w)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors
    rows = ledger(db)
    assert len(rows) == 9 and len({r.started_at for r in rows}) == 9
    assert all(g >= INTERVAL - 0.01 for g in gaps(rows))


def test_a_sleeping_holder_cannot_be_bypassed(db):
    """The first caller reserves and then sleeps outside the transaction (here far
    longer than the interval before sending); the second is still placed after it."""
    res(db, token="a", interval=INTERVAL, max_wait=5)
    second = res(db, token="b", interval=INTERVAL, max_wait=5)
    assert second >= INTERVAL - 0.05
    first, other = ledger(db)
    assert (other.started_at - first.started_at).total_seconds() >= INTERVAL - 0.01


def test_future_slots_queue_and_a_backlog_is_refused_without_recording(db):
    res(db, interval=2.0, max_wait=5)
    assert res(db, interval=2.0, max_wait=5) == pytest.approx(2.0, abs=0.1)
    assert res(db, interval=2.0, max_wait=5) == pytest.approx(4.0, abs=0.1)
    with pytest.raises(PacingBacklog):
        res(db, interval=2.0, max_wait=5)  # the next slot is ~6 s away
    assert len(ledger(db)) == 3  # nothing recorded for the refused attempt


def test_a_clock_moved_backwards_keeps_the_wait_bounded(db):
    with transaction(db) as conn:  # a slot an hour in the future (clock went back)
        conn.execute(sa.text(
            "INSERT INTO app.job_runs (job, scope, args, status, started_at, finished_at, "
            "api_requests) VALUES ('scheduler.provider', 'x', '{\"class\": \"results\"}', "
            "'succeeded', clock_timestamp() + interval '1 hour', "
            "clock_timestamp() + interval '1 hour', 1)"))  # fmt: skip
    wait = res(db, interval=INTERVAL, max_wait=5)
    assert wait == pytest.approx(INTERVAL, abs=0.05)  # never an hour; never zero


# ------------------------------------------------------------------ cooldown
def test_a_cooldown_holds_back_results_and_preparation(db):
    until = locking.record_cooldown(db, 120, "s", "provider rate limit")
    for klass in (RESULTS, PREPARATION):
        with pytest.raises(ProviderCooldown) as err:
            res(db, klass=klass)
        assert err.value.until == until
    assert ledger(db) == []  # nothing reserved during a cooldown


def test_an_expired_cooldown_releases(db):
    locking.record_cooldown(db, 1, "s", "provider rate limit")
    time.sleep(1.2)
    assert res(db) == 0.0


# ------------------------------------------------------------------ quota observations
def test_quota_observations_are_fresh_same_day_and_lowest_wins(db):
    locking.record_quota(db, 7000, 7500, "header")
    locking.record_quota(db, 6500, 7500, "status")
    with transaction(db) as conn:
        obs = locking.quota_observations(conn, timedelta(minutes=30))
        assert min(o.remaining for o in obs) == 6500
        assert locking.limit_today(conn) == 7500
        # an observation from the previous UTC day is never used (midnight reset), even
        # when it is lower and younger than the age limit would allow
        conn.execute(sa.text(
            "INSERT INTO app.job_runs (job, scope, args, status, started_at, finished_at, "
            "api_requests) VALUES ('scheduler.provider_quota', 'provider', "
            "'{\"remaining\": 10, \"limit\": 100, \"source\": \"header\"}'::jsonb, "
            "'succeeded', date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') "
            "AT TIME ZONE 'UTC' - interval '1 second', date_trunc('day', clock_timestamp() "
            "AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' - interval '1 second', 0)"))  # fmt: skip
    with transaction(db) as conn:
        assert {o.remaining for o in locking.quota_observations(conn, timedelta(days=2))} == {
            7000, 6500}  # fmt: skip
        assert locking.limit_today(conn) == 7500
        assert locking.quota_observations(conn, timedelta(seconds=0)) == []  # stale by age
