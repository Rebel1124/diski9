"""A3 Checkpoint 4C pre-implementation concurrency experiment (disposable DB only).

Target: cluster 127.0.0.1:54329 (created for this experiment under
/var/tmp/diski9_4c_exp_cluster), database diski9_4c_lockexp_test, migrated with the
real chain to app_0008. Not a test suite; evidence for the 4C report.

Each scenario uses its own schedule code shaped exactly like ``weekend`` (v1 closed,
v2 open on broad60-432-v1, copied attributes) so the real code-generic app_0008
triggers apply; E7 repeats activation and cancellation on the real ``weekend`` code.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
from sqlalchemy import create_engine, insert, pool, text

from diski9.backend.auth.permissions import Principal
from diski9.backend.db.schema import rounds
from diski9.backend.services import rounds as rounds_svc
from diski9.backend.services.schedules import current_schedule, lock_for_round_creation

HOST = "host=127.0.0.1 port=54329 dbname=diski9_4c_lockexp_test"
EXPECTED_DB = "diski9_4c_lockexp_test"
OWNER = f"{HOST} user=lockexp_owner"
WEB = f"{HOST} user=lockexp_web"
ADMIN = f"{HOST} user=postgres"  # monitoring only (pg_stat_activity / pg_locks)
SA_WEB = "postgresql+psycopg://lockexp_web@127.0.0.1:54329/diski9_4c_lockexp_test"
LOCK_KEY = "hashtextextended('diski9.round_schedules', 0)"

RESULTS: list[dict] = []
admin = psycopg.connect(ADMIN, autocommit=True)
assert admin.execute("select current_database()").fetchone()[0] == EXPECTED_DB
sa_web = create_engine(SA_WEB, poolclass=pool.NullPool)


# ------------------------------------------------------------------ helpers
def say(*a):
    print(*a, flush=True)


def record(exp, name, ok, **detail):
    RESULTS.append({"exp": exp, "case": name, "pass": bool(ok), **detail})
    say(f"  [{'PASS' if ok else 'FAIL'}] {exp} {name} {json.dumps(detail, default=str)}")


def sqlstate(e):
    s = getattr(e, "sqlstate", None)
    if s is None and getattr(e, "orig", None) is not None:
        s = getattr(e.orig, "sqlstate", None)
    return s


def msg(e):
    m = str(getattr(e, "orig", e)).strip().splitlines()
    return m[0][:220] if m else type(e).__name__


class Bg(threading.Thread):
    def __init__(self, fn):
        super().__init__(daemon=True)
        self.fn, self.res, self.err, self.done_at = fn, None, None, None

    def run(self):
        try:
            self.res = self.fn()
        except Exception as e:  # noqa: BLE001
            self.err = e
        self.done_at = time.monotonic()


def oconn(dsn=OWNER):
    c = psycopg.connect(dsn)  # autocommit off: explicit transactions
    assert c.execute("show transaction_isolation").fetchone()[0] == "read committed"
    return c


def pid(c):
    return c.info.backend_pid


def wait_blocked(p, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = admin.execute(
            "select wait_event_type, wait_event from pg_stat_activity where pid=%s", (p,)
        ).fetchone()
        if r and r[0] == "Lock":
            return r
        time.sleep(0.02)
    return None


def waiting_locks(p):
    return admin.execute(
        "select locktype, mode, coalesce(relation::regclass::text, "
        "'key ' || classid || '/' || objid) from pg_locks where pid=%s and not granted",
        (p,),
    ).fetchall()


def held_locks(p):
    return admin.execute(
        "select locktype, mode, coalesce(relation::regclass::text, "
        "'key ' || classid || '/' || objid) from pg_locks where pid=%s and granted "
        "and (locktype='advisory' or relation in ('app.rounds'::regclass, "
        "'app.round_schedules'::regclass))",
        (p,),
    ).fetchall()


def db_clock():
    return admin.execute("select clock_timestamp()").fetchone()[0]


def sleep_until(t, extra=0.05):
    d = (t - db_clock()).total_seconds() + extra
    if d > 0:
        time.sleep(d)


def state(code):
    sched = admin.execute(
        "select id, version, config_version, active_from, active_to from app.round_schedules "
        "where code=%s order by version",
        (code,),
    ).fetchall()
    rnds = admin.execute(
        "select r.code, s.version, r.created_at from app.rounds r join app.round_schedules s "
        "on s.id=r.schedule_id where s.code=%s order by r.created_at",
        (code,),
    ).fetchall()
    aud = admin.execute(
        "select count(*) from app.audit_log where target_type='round_schedule' and target_id "
        "like %s",
        (code + "/%",),
    ).fetchone()[0]
    return {"schedules": sched, "rounds": rnds, "audit": aud}


def violations():
    """Global integrity: overlaps, contiguity, rounds outside validity (app_0008 audit)."""
    o = admin.execute(
        "select count(*) from app.round_schedules a join app.round_schedules b on a.code=b.code "
        "and a.version<b.version where tstzrange(a.active_from,a.active_to,'[)') && "
        "tstzrange(b.active_from,b.active_to,'[)')"
    ).fetchone()[0]
    g = admin.execute(
        "with o as (select code, version, active_to, lead(active_from) over w nf, "
        "lead(version) over w nv from app.round_schedules window w as (partition by code "
        "order by version)) select count(*) from o where (nv is null and active_to is not null) "
        "or (nv is not null and (active_to is null or active_to<>nf))"
    ).fetchone()[0]
    r = admin.execute(
        "select count(*) from app.rounds r join app.round_schedules s on s.id=r.schedule_id "
        "where not (s.active_from<=r.created_at and (s.active_to is null or r.created_at<s.active_to))"
    ).fetchone()[0]
    return {"overlaps": o, "gaps": g, "rounds_outside_validity": r}


OWNER_USER = None


def setup_owner_user():
    global OWNER_USER
    with oconn() as c:
        OWNER_USER = c.execute("insert into app.users default values returning id").fetchone()[0]
        c.commit()


def make_code(code):
    """A schedule code shaped like weekend: v1 closed, v2 open on broad60 (copied
    attributes), v2 valid now."""
    with oconn() as c:
        c.execute("select app.schedule_write_lock()")
        cols = ("timezone, eligible_competitions, window_rule, publish_rule, "
                "deadline_buffer_minutes, settle_cutoff_hours, correction_window_hours, "
                "config_version, rules_version, scoring_version, series_id")
        c.execute(
            f"insert into app.round_schedules (code, version, {cols}, active_from, active_to) "
            f"select %s, 1, {cols}, '2026-11-01Z', '2026-11-10Z' from app.round_schedules "
            "where code='weekend' and version=2",
            (code,),
        )
        c.execute(
            f"insert into app.round_schedules (code, version, {cols}, active_from) "
            f"select %s, 2, {cols}, '2026-11-10Z' from app.round_schedules "
            "where code='weekend' and version=2",
            (code,),
        )
        c.commit()


COPIED = ("timezone", "eligible_competitions", "window_rule", "publish_rule",
          "deadline_buffer_minutes", "settle_cutoff_hours", "correction_window_hours",
          "rules_version", "scoring_version", "series_id")


# ------------------------------------------------------------------ activation steps
def tx_setup(c, lock_timeout="10s", statement_timeout="30s", idle=None):
    c.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
    c.execute(f"SET LOCAL statement_timeout = '{statement_timeout}'")
    if idle:
        c.execute(f"SET LOCAL idle_in_transaction_session_timeout = '{idle}'")


def act_lock(c):
    c.execute("SELECT app.schedule_write_lock()")


def act_validate(c, code):
    rows = c.execute(
        "select id, version, config_version, active_to from app.round_schedules where code=%s "
        "order by version",
        (code,),
    ).fetchall()
    open_rows = [r for r in rows if r[3] is None]
    if len(open_rows) != 1 or open_rows[0][1] != 2 or open_rows[0][2] != "broad60-432-v1":
        raise RuntimeError(f"precondition: unexpected schedule state {rows}")
    return open_rows[0][0]


def act_close(c, v2, T):
    n = c.execute(
        "update app.round_schedules set active_to=%s where id=%s and active_to is null", (T, v2)
    ).rowcount
    assert n == 1


def act_insert(c, v2, T, delta=timedelta(0)):
    cols = ", ".join(COPIED)
    return c.execute(
        f"insert into app.round_schedules (code, version, {cols}, config_version, active_from) "
        f"select code, 3, {cols}, 'a3-432-v1', %s from app.round_schedules where id=%s "
        "returning id",
        (T + delta, v2),
    ).fetchone()[0]


def act_audit(c, code, action, after):
    c.execute(
        "insert into app.audit_log (actor_user_id, actor_role, action, target_type, target_id, "
        "reason, after) values (%s, 'owner', %s, 'round_schedule', %s, 'experiment', %s)",
        (OWNER_USER, action, f"{code}/v3", json.dumps(after, default=str)),
    )


def activate(code, T, *, pause_after_lock=0.0, pause_before_commit=0.0, lock_timeout="10s"):
    """The proposed activation, in one transaction. Returns v3 id."""
    with oconn() as c:
        tx_setup(c, lock_timeout=lock_timeout)
        act_lock(c)
        time.sleep(pause_after_lock)
        v2 = act_validate(c, code)
        act_close(c, v2, T)
        v3 = act_insert(c, v2, T)
        act_audit(c, code, "schedule.activate", {"T": T, "v3": v3})
        time.sleep(pause_before_commit)
        c.commit()
        return v3


MARGIN = timedelta(seconds=2)  # experiment-scale stand-in for a conservative margin


def cancel(code, v3_id, T, *, margin=MARGIN, pause_after_lock=0.0, pause_before_commit=0.0,
           idle=None, final_check=True, lock_timeout="10s"):
    """The proposed pre-T cancellation: exact identity (id AND activation time), lock,
    clock checks after the lock and immediately before COMMIT, no references."""
    with oconn() as c:
        tx_setup(c, lock_timeout=lock_timeout, idle=idle)
        act_lock(c)
        time.sleep(pause_after_lock)
        r = c.execute(
            "select id, active_from from app.round_schedules where code=%s and version=3 "
            "and id=%s and active_from=%s and config_version='a3-432-v1' and active_to is null",
            (code, v3_id, T),
        ).fetchone()
        if r is None:
            raise RuntimeError("refused: the identified transition does not exist (stale or "
                               "conflicting cancellation instruction)")
        ok = c.execute("select clock_timestamp() < %s", (T - margin,)).fetchone()[0]
        if not ok:
            raise RuntimeError("refused: at or too close to/after the activation time")
        if c.execute("select exists(select 1 from app.rounds where schedule_id=%s)",
                     (v3_id,)).fetchone()[0]:
            raise RuntimeError("refused: a round references the transition")
        c.execute("delete from app.round_schedules where id=%s", (v3_id,))
        c.execute(
            "update app.round_schedules set active_to=null where code=%s and version=2", (code,)
        )
        act_audit(c, code, "schedule.activation_cancel", {"T": T, "v3": v3_id})
        time.sleep(pause_before_commit)
        if final_check:
            ok = c.execute("select clock_timestamp() < %s", (T - margin,)).fetchone()[0]
            if not ok:
                raise RuntimeError("refused at final check: too close to/after T")
        c.commit()


# ------------------------------------------------------------------ creators
def app_creator_steps(code, *, begin_hook=None, before_lock=0.0, hold_after_insert=0.0,
                      stale_schedule_id=None):
    """The application pattern (rounds.create_round), step by step with the real
    lock_for_round_creation and current_schedule, as the runtime role."""
    out = {}
    with sa_web.connect() as conn:
        with conn.begin():
            out["created_at"] = conn.execute(text("select transaction_timestamp()")).scalar_one()
            if begin_hook:
                begin_hook(conn)
            time.sleep(before_lock)
            lock_for_round_creation(conn)
            out["locked_at"] = conn.execute(text("select clock_timestamp()")).scalar_one()
            sched = current_schedule(conn, code)
            out["resolved_version"] = sched.version
            conn.execute(insert(rounds).values(
                code=f"r-{uuid.uuid4().hex[:10]}", schedule_id=stale_schedule_id or sched.id,
                series_id=sched.series_id, window_start_at=datetime(2027, 1, 1, tzinfo=UTC),
                window_end_at=datetime(2027, 1, 2, tzinfo=UTC)))
            time.sleep(hold_after_insert)
        out["committed_at"] = db_clock()
    return out


def direct_insert(code, version, *, c=None, commit=True):
    own = c is None
    c = c or psycopg.connect(WEB)
    sid, series = c.execute(
        "select id, series_id from app.round_schedules where code=%s and version=%s",
        (code, version),
    ).fetchone()
    created = c.execute("select transaction_timestamp()").fetchone()[0]
    c.execute(
        "insert into app.rounds (code, schedule_id, series_id, window_start_at, window_end_at) "
        "values (%s, %s, %s, '2027-01-01Z', '2027-01-02Z')",
        (f"d-{uuid.uuid4().hex[:10]}", sid, series),
    )
    if commit:
        c.commit()
        if own:
            c.close()
    return created


def operator_principal():
    now = datetime.now(UTC)
    return Principal(user_id=OWNER_USER, session_hash="x", roles=frozenset({"operator"}),
                     onboarded=True, authenticated_at=now, reauthenticated_at=now, now=now)


# ================================================================== E1
def e1():
    say("E1 advisory lock timeout")
    code = "e1"
    make_code(code)
    before = state(code)
    holder = psycopg.connect(WEB)
    holder.execute(f"select pg_advisory_xact_lock_shared({LOCK_KEY})")  # a creator
    # (a) lock_timeout 1s, statement_timeout 30s
    c = oconn()
    tx_setup(c, lock_timeout="1s", statement_timeout="30s")
    t0 = time.monotonic()
    try:
        act_lock(c)
        record("E1", "lock_timeout_applies", False, note="acquired unexpectedly")
    except psycopg.Error as e:
        el = time.monotonic() - t0
        record("E1", "lock_timeout_applies", sqlstate(e) == "55P03" and 0.9 < el < 2.0,
               sqlstate=sqlstate(e), elapsed_s=round(el, 3), error=msg(e))
    st = c.info.transaction_status.name
    c.rollback()
    ok_after = c.execute("select 1").fetchone()[0] == 1
    c.rollback()
    record("E1", "aborted_then_usable", st == "INERROR" and ok_after, tx_status_after_error=st)
    # (b) statement_timeout shorter than lock_timeout: the wait is cancelled by 57014
    tx_setup(c, lock_timeout="5s", statement_timeout="500ms")
    t0 = time.monotonic()
    try:
        act_lock(c)
    except psycopg.Error as e:
        record("E1", "short_statement_timeout_obscures", sqlstate(e) == "57014",
               sqlstate=sqlstate(e), elapsed_s=round(time.monotonic() - t0, 3), error=msg(e))
    c.rollback()
    # (c) lock_timeout below statement_timeout: lock timeout reported, not statement timeout
    tx_setup(c, lock_timeout="700ms", statement_timeout="5s")
    t0 = time.monotonic()
    try:
        act_lock(c)
    except psycopg.Error as e:
        record("E1", "lock_timeout_wins_when_shorter", sqlstate(e) == "55P03",
               sqlstate=sqlstate(e), elapsed_s=round(time.monotonic() - t0, 3))
    c.rollback()
    # (d) the statement trigger path (direct UPDATE without calling the function) too
    tx_setup(c, lock_timeout="1s")
    t0 = time.monotonic()
    try:
        c.execute("update app.round_schedules set active_to=active_to where code=%s", (code,))
    except psycopg.Error as e:
        record("E1", "statement_trigger_lock_also_bounded", sqlstate(e) == "55P03",
               sqlstate=sqlstate(e), elapsed_s=round(time.monotonic() - t0, 3), error=msg(e))
    c.rollback()
    # (e) an exclusive holder (another schedule writer) also bounds it
    holder.rollback()
    w = oconn()
    w.execute("select app.schedule_write_lock()")
    tx_setup(c, lock_timeout="1s")
    try:
        act_lock(c)
    except psycopg.Error as e:
        record("E1", "exclusive_holder_bounded", sqlstate(e) == "55P03", sqlstate=sqlstate(e))
    c.rollback()
    w.rollback()
    # (f) default lock_timeout 0 waits indefinitely: observe it is genuinely blocked
    holder.execute(f"select pg_advisory_xact_lock_shared({LOCK_KEY})")
    c2 = oconn()
    bg = Bg(lambda: act_lock(c2))
    bg.start()
    blk = wait_blocked(pid(c2))
    wl = waiting_locks(pid(c2))
    holder.rollback()
    bg.join(5)
    c2.rollback()
    record("E1", "no_timeout_means_unbounded_wait_observed", blk is not None and bg.err is None,
           wait=blk, waiting_lock=wl)
    holder.close(), c.close(), c2.close(), w.close()
    record("E1", "schedule_state_unchanged", state(code) == before)


# ================================================================== E2
def e2():
    say("E2 activation vs application round creation")
    # (a) creator holds the shared lock first (resolved v2, inserted, not committed)
    code = "e2a"
    make_code(code)
    T = db_clock() + timedelta(seconds=30)
    go = threading.Event()
    cr = Bg(lambda: app_creator_steps(code, hold_after_insert=1.5))
    cr.start()
    time.sleep(0.4)
    ac = Bg(lambda: activate(code, T))
    ac.start()
    # find the activation backend: the one waiting on an advisory lock
    time.sleep(0.3)
    waiting = admin.execute(
        "select a.pid, l.locktype, l.mode from pg_locks l join pg_stat_activity a using (pid) "
        "where not l.granted and a.usename='lockexp_owner'"
    ).fetchall()
    cr.join(10), ac.join(10)
    s = state(code)
    record("E2", "creator_first_serialises", cr.err is None and ac.err is None
           and cr.res["resolved_version"] == 2 and ac.done_at > cr.done_at
           and [r[1] for r in s["schedules"]] == [1, 2, 3] and s["audit"] == 1,
           activation_waited_on=waiting, creator=cr.res, rounds=s["rounds"])
    # (b) activation holds the exclusive lock first; creator starts after T has NOT yet
    #     come (binds v2) — and a second creator starting after T (binds v3)
    code = "e2b"
    make_code(code)
    T = db_clock() + timedelta(seconds=2)
    ac = Bg(lambda: activate(code, T, pause_after_lock=1.0))
    ac.start()
    time.sleep(0.3)
    cr1 = Bg(lambda: app_creator_steps(code))  # begins before T, waits for the lock
    cr1.start()
    time.sleep(0.2)
    blocked = admin.execute(
        "select count(*) from pg_stat_activity where usename='lockexp_web' and "
        "wait_event_type='Lock'"
    ).fetchone()[0]
    ac.join(10), cr1.join(10)
    sleep_until(T)
    cr2 = Bg(lambda: app_creator_steps(code))
    cr2.start(), cr2.join(10)
    s = state(code)
    record("E2", "activation_first_serialises_and_binds_by_created_at",
           ac.err is None and cr1.err is None and cr2.err is None and blocked >= 1
           and cr1.res["resolved_version"] == 2 and cr1.res["created_at"] < T
           and cr1.res["locked_at"] > cr1.res["created_at"]
           and cr2.res["resolved_version"] == 3 and cr2.res["created_at"] >= T,
           creator_blocked_count=blocked, creator1=cr1.res, creator2=cr2.res,
           rounds=s["rounds"])
    # (c) the real rounds.create_round service waits behind an activation holding the lock
    code = "e2c"
    make_code(code)
    T = db_clock() + timedelta(seconds=30)
    ac = Bg(lambda: activate(code, T, pause_after_lock=1.0))
    ac.start()
    time.sleep(0.3)
    sv = Bg(lambda: rounds_svc.create_round(
        sa_web, operator_principal(), code="svc-e2c-1",
        window_start=datetime(2027, 1, 1, tzinfo=UTC),
        window_end=datetime(2027, 1, 2, tzinfo=UTC), schedule_code=code))
    t0 = time.monotonic()
    sv.start()
    ac.join(10), sv.join(10)
    s = state(code)
    record("E2", "real_create_round_waits_then_binds_v2_before_T",
           ac.err is None and sv.err is None and sv.done_at > ac.done_at
           and [r[1] for r in s["rounds"]] == [2],
           service_error=None if sv.err is None else msg(sv.err),
           waited_s=round(sv.done_at - t0, 2) if sv.done_at else None, rounds=s["rounds"])


# ================================================================== E3
def e3():
    say("E3 activation vs direct SQL round insertion")
    # (a) activation first, then direct insert (table lock, then trigger shared lock)
    code = "e3a"
    make_code(code)
    T = db_clock() + timedelta(seconds=30)
    a = oconn()
    tx_setup(a)
    act_lock(a)
    d = psycopg.connect(WEB)
    di = Bg(lambda: direct_insert(code, 2, c=d))
    di.start()
    w = wait_blocked(pid(d))
    dwait, dheld = waiting_locks(pid(d)), held_locks(pid(d))
    try:
        v2 = act_validate(a, code)
        act_close(a, v2, T)  # row guard reads app.rounds: no conflict with the inserter
        act_insert(a, v2, T)
        act_audit(a, code, "schedule.activate", {"T": T})
        a.commit()
        aerr = None
    except psycopg.Error as e:
        aerr = e
        a.rollback()
    di.join(10)
    s = state(code)
    record("E3", "activation_first_no_deadlock", aerr is None and di.err is None
           and w is not None and [r[1] for r in s["rounds"]] == [2],
           inserter_wait=w, inserter_waiting=dwait, inserter_held=dheld,
           rounds=s["rounds"], schedules=[r[1] for r in s["schedules"]])
    # (b) direct insert first (holds RowExclusive on rounds + shared advisory), activation waits
    code = "e3b"
    make_code(code)
    T = db_clock() + timedelta(seconds=30)
    d = psycopg.connect(WEB)
    direct_insert(code, 2, c=d, commit=False)
    held = held_locks(pid(d))
    ac_conn = oconn()

    def run_act():
        tx_setup(ac_conn)
        act_lock(ac_conn)
        v2 = act_validate(ac_conn, code)
        act_close(ac_conn, v2, T)
        act_insert(ac_conn, v2, T)
        ac_conn.commit()

    ac = Bg(run_act)
    ac.start()
    w = wait_blocked(pid(ac_conn))
    awaiting = waiting_locks(pid(ac_conn))
    d.commit()
    ac.join(10)
    s = state(code)
    record("E3", "insert_first_activation_waits_then_succeeds", ac.err is None
           and w is not None and [r[1] for r in s["schedules"]] == [1, 2, 3],
           inserter_held=held, activation_waiting=awaiting, rounds=s["rounds"])
    d.close()
    # (c) NEGATIVE CONTROL: advisory exclusive, then SHARE ROW EXCLUSIVE on rounds
    code = "e3c"
    make_code(code)
    a = oconn()
    tx_setup(a, lock_timeout="20s")
    act_lock(a)
    d = psycopg.connect(WEB)
    di = Bg(lambda: direct_insert(code, 2, c=d))
    di.start()
    wait_blocked(pid(d))
    t0 = time.monotonic()
    try:
        a.execute("LOCK TABLE app.rounds IN SHARE ROW EXCLUSIVE MODE")
        neg = ("no deadlock", None)
        a.rollback()
    except psycopg.Error as e:
        neg = (sqlstate(e), msg(e))
        a.rollback()
    di.join(10)
    record("E3", "negative_control_advisory_then_table_lock_deadlocks",
           neg[0] == "40P01" or (di.err is not None and sqlstate(di.err) == "40P01"),
           activation_result=neg, inserter_result=None if di.err is None else
           (sqlstate(di.err), msg(di.err)), elapsed_s=round(time.monotonic() - t0, 2),
           note="whichever backend the detector picks gets 40P01")
    a.close(), d.close()


# ================================================================== E4
def e4():
    say("E4 transactions crossing the activation boundary")
    # (a) pre-T transaction, lock after activation commits and after T: binds v2
    code = "e4a"
    make_code(code)
    T = db_clock() + timedelta(seconds=2)
    gate = threading.Event()
    cr = Bg(lambda: app_creator_steps(code, begin_hook=lambda c: gate.wait(10)))
    cr.start()
    time.sleep(0.3)  # creator transaction has begun (created_at < T)
    v3 = activate(code, T)
    sleep_until(T, 0.3)
    gate.set()
    cr.join(10)
    s = state(code)
    record("E4", "pre_T_tx_binds_v2_even_committing_after_T", cr.err is None
           and cr.res["resolved_version"] == 2 and cr.res["created_at"] < T
           and cr.res["committed_at"] > T, creator=cr.res, T=T)
    # (b) post-T creators while activation (late) holds the exclusive lock
    code = "e4b"
    make_code(code)
    T = db_clock() + timedelta(seconds=1)
    a = oconn()
    tx_setup(a)
    act_lock(a)
    v2 = act_validate(a, code)
    act_close(a, v2, T)
    act_insert(a, v2, T)
    sleep_until(T, 0.2)  # now past T, activation still uncommitted
    cr = Bg(lambda: app_creator_steps(code))
    cr.start()
    d = psycopg.connect(WEB)
    stale = Bg(lambda: direct_insert(code, 2, c=d))  # stale v2 id, created_at >= T
    stale.start()
    time.sleep(0.4)
    a.commit()
    cr.join(10), stale.join(10)
    s = state(code)
    record("E4", "post_T_app_creator_resolves_v3_after_commit", cr.err is None
           and cr.res["resolved_version"] == 3 and cr.res["created_at"] >= T, creator=cr.res)
    record("E4", "post_T_direct_insert_with_stale_v2_refused_not_rebound",
           stale.err is not None and sqlstate(stale.err) == "23000"
           and all(r[1] == 3 for r in s["rounds"]),
           sqlstate=None if stale.err is None else sqlstate(stale.err),
           error=None if stale.err is None else msg(stale.err), rounds=s["rounds"])
    d.close()
    # (c) post-T creator holds the shared lock first and binds v2: activation refused
    code = "e4c"
    make_code(code)
    T = db_clock() + timedelta(seconds=1)
    sleep_until(T, 0.2)
    before = state(code)
    cr = Bg(lambda: app_creator_steps(code, hold_after_insert=1.0))
    cr.start()
    time.sleep(0.3)
    try:
        activate(code, T)
        res = ("activated", None)
    except psycopg.Error as e:
        res = (sqlstate(e), msg(e))
    cr.join(10)
    s = state(code)
    record("E4", "activation_refused_when_v2_round_created_at_or_after_T",
           res[0] == "23000" and cr.res["resolved_version"] == 2
           and [r[1] for r in s["schedules"]] == [1, 2] and s["schedules"][1][4] is None
           and s["audit"] == 0, activation=res, creator=cr.res,
           schedules_unchanged=s["schedules"] == before["schedules"])
    # (d) same refusal when the offending v2 round is already committed
    code = "e4d"
    make_code(code)
    T = db_clock() + timedelta(seconds=1)
    sleep_until(T, 0.1)
    direct_insert(code, 2)
    before = state(code)
    try:
        activate(code, T)
        res = ("activated", None)
    except psycopg.Error as e:
        res = (sqlstate(e), msg(e))
    record("E4", "activation_refused_committed_v2_round_after_T",
           res[0] == "23000" and state(code) == before, activation=res)


# ================================================================== E5
def e5():
    say("E5 pre-T cancellation")
    # (a) intended, unreferenced, pre-T: succeeds; then a re-activation with new T
    code = "e5a"
    make_code(code)
    T1 = db_clock() + timedelta(seconds=60)
    v3a = activate(code, T1)
    cancel(code, v3a, T1)
    s = state(code)
    ok_a = [r[1] for r in s["schedules"]] == [1, 2] and s["schedules"][1][4] is None
    T2 = db_clock() + timedelta(seconds=90)
    v3b = activate(code, T2)
    record("E5", "cancel_success_then_reactivation_new_identity", ok_a and v3b != v3a,
           v3_cancelled=v3a, v3_recreated=v3b, audit_rows=state(code)["audit"])
    # (b) stale instruction (old id and old T) cannot cancel the replacement
    before = state(code)
    for ident in ((v3a, T1), (v3a, T2), (v3b, T1)):
        try:
            cancel(code, *ident)
            r = "cancelled"
        except RuntimeError as e:
            r = str(e)
        record("E5", f"stale_identity_refused id={ident[0]} T_matches={ident[1] == T2}",
               r.startswith("refused") and state(code) == before, result=r)
    # (c) referenced transition: service refuses; raw DELETE refused by the row guard
    code = "e5c"
    make_code(code)
    T = db_clock() + timedelta(seconds=1)
    v3 = activate(code, T)
    sleep_until(T, 0.1)
    app_creator_steps(code)  # binds v3
    before = state(code)
    try:
        cancel(code, v3, T, margin=timedelta(0))
        r = "cancelled"
    except RuntimeError as e:
        r = str(e)
    with oconn() as c:
        c.execute("select app.schedule_write_lock()")
        try:
            c.execute("delete from app.round_schedules where id=%s", (v3,))
            raw = "deleted"
        except psycopg.Error as e:
            raw = (sqlstate(e), msg(e))
        c.rollback()
    record("E5", "referenced_transition_cannot_be_removed",
           r.startswith("refused") and isinstance(raw, tuple) and raw[0] == "42501"
           and state(code) == before, service_check=r, raw_delete=raw)
    # (d) elapsed but unreferenced: refused by the clock check
    code = "e5d"
    make_code(code)
    T = db_clock() + timedelta(seconds=1)
    v3 = activate(code, T)
    sleep_until(T, 0.1)
    before = state(code)
    try:
        cancel(code, v3, T, margin=timedelta(0))
        r = "cancelled"
    except RuntimeError as e:
        r = str(e)
    record("E5", "elapsed_unreferenced_refused", r.startswith("refused")
           and state(code) == before, result=r)
    # (e) cancellation acquires the lock only after T (waits behind a creator): refused
    code = "e5e"
    make_code(code)
    T = db_clock() + timedelta(seconds=3)
    v3 = activate(code, T)
    holder = psycopg.connect(WEB)
    holder.execute(f"select pg_advisory_xact_lock_shared({LOCK_KEY})")
    cc = Bg(lambda: cancel(code, v3, T, margin=timedelta(0)))
    cc.start()
    sleep_until(T, 0.3)
    holder.rollback()
    cc.join(10)
    record("E5", "lock_acquired_after_T_refused", isinstance(cc.err, RuntimeError)
           and "refused" in str(cc.err) and [r[1] for r in state(code)["schedules"]] == [1, 2, 3],
           result=str(cc.err))
    holder.close()
    # (f) lock before T, delayed past T before COMMIT, final check present: refused
    code = "e5f"
    make_code(code)
    T = db_clock() + timedelta(seconds=4)
    v3 = activate(code, T)
    try:
        cancel(code, v3, T, margin=timedelta(seconds=1), pause_before_commit=4.0)
        r = "cancelled"
    except RuntimeError as e:
        r = str(e)
    record("E5", "delay_past_T_caught_by_final_check", "final check" in r
           and [x[1] for x in state(code)["schedules"]] == [1, 2, 3], result=r)
    # (g) LIMITATION: the final check passes, then the client stalls before COMMIT;
    #     without an idle timeout the commit lands after T
    code = "e5g"
    make_code(code)
    T = db_clock() + timedelta(seconds=3)
    v3 = activate(code, T)
    c = oconn()
    tx_setup(c)
    act_lock(c)
    c.execute("delete from app.round_schedules where id=%s", (v3,))
    c.execute("update app.round_schedules set active_to=null where code=%s and version=2", (code,))
    passed = c.execute("select clock_timestamp() < %s", (T,)).fetchone()[0]
    sleep_until(T, 0.3)  # client stalls between the final check and COMMIT
    c.commit()
    committed_after = db_clock() > T
    record("E5", "limitation_commit_after_final_check_can_land_after_T",
           passed and committed_after and [x[1] for x in state(code)["schedules"]] == [1, 2],
           note="demonstrates why a pre-commit check alone is not a guarantee")
    c.close()
    # (h) mitigation: SET LOCAL idle_in_transaction_session_timeout terminates the stall
    code = "e5h"
    make_code(code)
    T = db_clock() + timedelta(seconds=4)
    v3 = activate(code, T)
    c = oconn()
    tx_setup(c, idle="1s")
    act_lock(c)
    c.execute("delete from app.round_schedules where id=%s", (v3,))
    c.execute("update app.round_schedules set active_to=null where code=%s and version=2", (code,))
    time.sleep(2.0)  # stall longer than the idle timeout
    try:
        c.commit()
        r = "committed"
    except psycopg.Error as e:
        r = (sqlstate(e), msg(e))
    record("E5", "idle_in_transaction_timeout_set_local_terminates_stall",
           r != "committed" and [x[1] for x in state(code)["schedules"]] == [1, 2, 3],
           result=r, connection_closed=c.closed)
    # (i) creator concurrent with a successful pre-T cancel: waits, then binds v2
    code = "e5i"
    make_code(code)
    T = db_clock() + timedelta(seconds=60)
    v3 = activate(code, T)
    cc = Bg(lambda: cancel(code, v3, T, pause_after_lock=1.0))
    cc.start()
    time.sleep(0.3)
    cr = Bg(lambda: app_creator_steps(code))
    cr.start()
    cc.join(10), cr.join(10)
    s = state(code)
    record("E5", "creator_during_cancel_waits_and_binds_v2", cc.err is None and cr.err is None
           and cr.done_at > cc.done_at and cr.res["resolved_version"] == 2
           and [x[1] for x in s["schedules"]] == [1, 2], creator=cr.res)


# ================================================================== E6
def e6():
    say("E6 atomicity and failure recovery")
    code = "e6"
    make_code(code)
    direct_insert(code, 2)
    before = state(code)
    T = db_clock() + timedelta(seconds=60)
    # (a) error after closing v2 and inserting v3 and the audit row, before commit
    c = oconn()
    tx_setup(c)
    act_lock(c)
    v2 = act_validate(c, code)
    act_close(c, v2, T)
    act_insert(c, v2, T)
    act_audit(c, code, "schedule.activate", {"T": T})
    mid = c.execute("select count(*) from app.round_schedules where code=%s", (code,)).fetchone()
    try:
        c.execute("select 1/0")
    except psycopg.Error as e:
        err = sqlstate(e)
    c.rollback()
    usable = c.execute("select 1").fetchone()[0] == 1
    c.rollback()
    record("E6", "error_mid_transition_rolls_back_everything", err == "22012"
           and state(code) == before and usable and mid[0] == 3,
           sqlstate=err, rows_seen_inside_tx=mid[0], after=state(code))
    # (b) deferred contiguity failure at COMMIT (v3 starts 1s after v2 ends: a gap)
    tx_setup(c)
    act_lock(c)
    act_close(c, v2, T)
    act_insert(c, v2, T, delta=timedelta(seconds=1))
    act_audit(c, code, "schedule.activate", {"T": T})
    try:
        c.commit()
        r = "committed"
    except psycopg.Error as e:
        r = (sqlstate(e), msg(e))
    usable = c.execute("select 1").fetchone()[0] == 1
    c.rollback()
    record("E6", "deferred_contiguity_failure_at_commit", isinstance(r, tuple)
           and r[0] == "23000" and state(code) == before and usable, result=r)
    # (c) immediate exclusion failure: inserting v3 BEFORE closing v2 (wrong order)
    tx_setup(c)
    act_lock(c)
    try:
        act_insert(c, v2, T)
        r = "inserted"
    except psycopg.Error as e:
        r = (sqlstate(e), msg(e))
    c.rollback()
    record("E6", "wrong_order_insert_before_close_refused_immediately",
           isinstance(r, tuple) and state(code) == before, result=r)
    c.close()
    record("E6", "global_integrity", violations() == {"overlaps": 0, "gaps": 0,
                                                       "rounds_outside_validity": 0},
           **violations())


# ================================================================== E7 (weekend) + 4.1/4.2 probes
def e7():
    say("E7 real weekend code: activation, exact repeat detection, cancel; safeguard probes")
    before = state("weekend")
    T = db_clock() + timedelta(days=10)
    v3 = activate("weekend", T)
    w = state("weekend")
    with oconn() as c:
        rows = c.execute(
            f"select version, config_version, active_from, active_to, {', '.join(COPIED)} "
            "from app.round_schedules where code='weekend' and version in (2,3) order by version"
        ).fetchall()
    copied_equal = rows[0][4:] == rows[1][4:]
    record("E7", "weekend_v2_to_v3_copied_attributes", copied_equal and rows[0][3] == T
           and rows[1][2] == T and rows[1][3] is None and rows[1][1] == "a3-432-v1",
           v2_active_to=rows[0][3], v3=(rows[1][0], rows[1][1], rows[1][2]))
    try:  # a second activation attempt (not exact-no-op logic: shows the database refusal)
        activate("weekend", T)
        r = "activated twice"
    except (RuntimeError, psycopg.Error) as e:
        r = str(e)[:160]
    record("E7", "second_activation_refused_by_precondition", r.startswith("precondition"),
           result=r)
    cancel("weekend", v3, T)
    record("E7", "weekend_cancel_restores_rows", state("weekend")["schedules"]
           == before["schedules"], audit_rows=state("weekend")["audit"])
    # 4.1 privileges, individually
    priv = admin.execute(
        "select r, p, has_table_privilege(r, 'app.round_schedules', p) from "
        "unnest(array['lockexp_owner','diski9_app','lockexp_web']) r, "
        "unnest(array['SELECT','INSERT','UPDATE','DELETE']) p order by 1, 2"
    ).fetchall()
    fn = admin.execute(
        "select r, has_function_privilege(r, 'app.schedule_write_lock()', 'EXECUTE'), "
        "has_table_privilege(r, 'app.audit_log', 'INSERT') from "
        "unnest(array['lockexp_owner','diski9_app','lockexp_web']) r order by 1"
    ).fetchall()
    record("E7", "privileges_individual", True, table=priv, write_lock_fn_and_audit=fn)
    with psycopg.connect(WEB) as c:
        try:
            c.execute("update app.round_schedules set active_to=active_to where code='weekend'")
            r = "updated"
        except psycopg.Error as e:
            r = (sqlstate(e), msg(e))
    record("E7", "runtime_role_cannot_write_schedules", isinstance(r, tuple)
           and r[0] == "42501", result=r)
    # 4.2 bypass conditions for the owner (non-superuser)
    with oconn() as c:
        try:
            c.execute("set session_replication_role = replica")
            r = "set"
        except psycopg.Error as e:
            r = (sqlstate(e), msg(e))
        c.rollback()
    record("E7", "owner_cannot_set_session_replication_role", isinstance(r, tuple), result=r)
    with oconn() as c:
        c.execute("alter table app.round_schedules disable trigger round_schedules_row_guard")
        st = c.execute(
            "select tgname, tgenabled from pg_trigger where tgrelid='app.round_schedules'::regclass"
            " and tgname='round_schedules_row_guard'"
        ).fetchone()
        c.rollback()  # never committed: DDL is transactional
    record("E7", "owner_can_disable_triggers_detectable_via_tgenabled", st[1] == "D",
           observed_inside_rolled_back_tx=st,
           after=admin.execute("select tgenabled from pg_trigger where tgname="
                               "'round_schedules_row_guard'").fetchone())


if __name__ == "__main__":
    setup_owner_user()
    only = sys.argv[1:] or ["e1", "e2", "e3", "e4", "e5", "e6", "e7"]
    for name in only:
        globals()[name]()
    say("GLOBAL", json.dumps(violations()))
    fails = [r for r in RESULTS if not r["pass"]]
    say(f"SUMMARY {len(RESULTS) - len(fails)}/{len(RESULTS)} passed")
    with open(__file__.replace(".py", f"_results_{'_'.join(only)}.json"), "w") as f:
        json.dump(RESULTS, f, default=str, indent=1)
