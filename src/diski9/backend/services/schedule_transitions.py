"""The A3 schedule transition: activation and pre-T cancellation (Scenario A3,
Checkpoint 4C).

The one authorised transition: ``weekend`` v2 on ``broad60-432-v1`` → v3 on
``a3-432-v1``, effective at an explicitly approved UTC instant **T**. It is an
administrative operation, not a migration: the migration head stays ``app_0008``,
whose safeguards decide whether the writes are valid.

Separation of authority:
* **database**: the executing role needs, individually checked, SELECT, INSERT and
  UPDATE on ``app.round_schedules`` (plus DELETE to cancel), EXECUTE on
  ``app.schedule_write_lock()``, and SELECT and INSERT on ``app.audit_log``. In
  practice this is the migration owner; the runtime role must have none of the
  schedule write privileges;
* **application**: a password-verified owner (S-07) with ``schedule.activate``.
  The owner role is checked again inside the write transaction, and the role and
  account rows are held ``FOR SHARE`` until commit, so a revocation or suspension
  cannot slip in between. Database credentials are never authorisation on their
  own.

Transaction (one per operation; experiment-validated lock order):
1. READ COMMITTED check; ``SET LOCAL`` lock (10 s), statement (30 s) and
   idle-in-transaction (5 s) timeouts;
2. ``app.schedule_write_lock()``: exclusive advisory lock. Nothing before it reads
   schedule or round data, and **no table locks are taken**, because an explicit
   table lock after the advisory lock deadlocks against direct SQL round inserts
   (SQLSTATE 40P01, reproduced in the 4C experiment);
3. every authoritative check: safeguards, privileges, owner, schedule state, rounds
   and audit evidence;
4. writes (close v2 at T, then insert v3, in that order, because the exclusion
   constraint and the one-open-row index are immediate) and the audit row;
5. cancellation only: a final wall-clock check immediately before COMMIT;
6. COMMIT, which runs the deferred contiguity check. A failure the server reports
   means it rolled back. A lost connection during COMMIT means the outcome is
   **uncertain**: :class:`TransitionUncertain`, never retried automatically.

Round binding keeps transaction-timestamp semantics (``rounds.created_at``). Wall
clock (``clock_timestamp()``) is used only for the cancellation safety margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from diski9.challenge.config import ConfigError, get_config

from ..auth.permissions import Capability, Principal, authorize
from ..db import read_only
from ..repositories.ops import record_audit
from .common import ServiceError

SCHEDULE_CODE = "weekend"
FROM_VERSION = 2
TO_VERSION = 3
FROM_CONFIG = "broad60-432-v1"
TO_CONFIG = "a3-432-v1"
RULES_VERSION = "settle/v1"
SCORING_VERSION = "points-150-75-v2"
APPROVED_FINGERPRINTS = {
    FROM_CONFIG: "b8cb7c0372e6aac15b1638e100be35955dacfd3f11c1f3654ad52c9263cbba94",
    TO_CONFIG: "91dba48a002a4fed3dc340764ef1717228f7dea61401f29621e799de401b094e",
}
EXPECTED_REVISION = "app_0008"
LOCK_TIMEOUT = "10s"
STATEMENT_TIMEOUT = "30s"  # longer than the lock timeout, so 55P03 is reported, not 57014
IDLE_TIMEOUT = "5s"
CANCEL_MARGIN = timedelta(minutes=10)  # owner-approved technical safety margin
LEAD_TIME_POLICY = timedelta(hours=72)  # operational policy: warned about, never enforced
ACTIVATE_ACTION = "schedule.activate"
CANCEL_ACTION = "schedule.activation_cancel"
AUDIT_TARGET = "round_schedule"  # target_id = the v3 schedule id
RUNTIME_ROLE = "diski9_app"
COPIED = ("timezone", "eligible_competitions", "window_rule", "publish_rule",
          "deadline_buffer_minutes", "settle_cutoff_hours", "correction_window_hours",
          "rules_version", "scoring_version", "series_id")  # fmt: skip

# expected app_0008 triggers: (table, function, pg_trigger.tgtype, deferrable+deferred)
# tgtype bits: 1 row, 2 before, 4 insert, 8 delete, 16 update, 32 truncate
EXPECTED_TRIGGERS = {
    "round_schedules_write_lock": ("app.round_schedules", "app.round_schedules_write_lock()",
                                   2 | 4 | 8 | 16 | 32, False),
    "round_schedules_row_guard": ("app.round_schedules", "app.round_schedules_row_guard()",
                                  1 | 2 | 8 | 16, False),
    "round_schedules_contiguous": ("app.round_schedules", "app.round_schedules_contiguity()",
                                   1 | 4 | 8 | 16, True),
    "rounds_schedule_valid": ("app.rounds", "app.round_schedule_valid()", 1 | 2 | 4, False),
    "rounds_identity_immutable": ("app.rounds", "app.set_once()", 1 | 2 | 16, False),
}  # fmt: skip
EXPECTED_FUNCTIONS = ("app.schedule_write_lock()", "app.schedule_read_lock()",
                      "app.require_read_committed(text)", "app.check_schedule_contiguity(text)")  # fmt: skip


class TransitionRefused(ServiceError):
    """Refused; nothing was changed. ``details`` lists every reason."""

    code = "transition_refused"


class TransitionUncertain(ServiceError):
    """The outcome is not known (connection lost during COMMIT, or the post-commit
    verification could not confirm the result). Do not retry or reverse: reconcile
    read-only first (``round schedules``, ``audit``, the plan command)."""

    code = "transition_outcome_uncertain"


class CancellationIncident(ServiceError):
    """The cancellation committed, but the clock observed after COMMIT was at or past
    T (the residual timing limitation). Report it as an operational incident; do
    not reverse or retry automatically."""

    code = "cancellation_incident"


# ------------------------------------------------------------------ inputs
def parse_utc_instant(value: str | datetime) -> datetime:
    """An explicit UTC instant: ISO 8601 ending in ``Z`` or ``+00:00`` (or an aware
    datetime with a zero offset). Naive, non-UTC and invalid values are refused."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = (value or "").strip()
        if not (s.endswith("Z") or s.endswith("+00:00")):
            raise TransitionRefused("The activation time must be given in UTC (ending in Z or "
                                    "+00:00), for example 2027-03-01T10:00:00Z.",
                                    details=["not_utc"])  # fmt: skip
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise TransitionRefused(f"{s!r} is not a valid ISO 8601 instant.",
                                    details=["invalid"]) from None  # fmt: skip
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise TransitionRefused("The activation time must be timezone-aware UTC.",
                                details=["naive"])  # fmt: skip
    if dt.utcoffset() != timedelta(0):
        raise TransitionRefused("The activation time must be UTC (offset +00:00).",
                                details=["not_utc"])  # fmt: skip
    return dt.astimezone(UTC)


def _require_text(**fields: str | None) -> None:
    missing = [k for k, v in fields.items() if not (v and v.strip())]
    if missing:
        raise TransitionRefused(f"Required: {', '.join(missing)}.", details=missing)


def config_problems() -> list[str]:
    """Both configurations registered with their approved fingerprints."""
    out = []
    for version, expected in APPROVED_FINGERPRINTS.items():
        try:
            fp = get_config(version).fingerprint()
        except ConfigError:
            out.append(f"configuration {version} is not registered in this build")
            continue
        if fp != expected:
            out.append(f"configuration {version} has fingerprint {fp[:16]}…, not the approved "
                       f"{expected[:16]}…")  # fmt: skip
    return out


# ------------------------------------------------------------------ database checks
def safeguard_problems(conn: Connection) -> list[str]:
    """The app_0008 safeguards are present and effective for this session."""
    out = []
    rev = conn.execute(text("SELECT version_num FROM public.app_alembic_version")).scalars().all()
    if rev != [EXPECTED_REVISION]:
        out.append(f"schema revision is {rev or 'unknown'}, expected {EXPECTED_REVISION}")
    iso = conn.execute(text("SELECT current_setting('transaction_isolation')")).scalar_one()
    if iso != "read committed":
        out.append(f"transaction isolation is {iso}, READ COMMITTED is required")
    srr = conn.execute(text("SELECT current_setting('session_replication_role')")).scalar_one()
    if srr != "origin":
        out.append(f"session_replication_role is {srr}: ordinary triggers would not fire")
    for fn in EXPECTED_FUNCTIONS:
        if conn.execute(text("SELECT to_regprocedure(:f)"), {"f": fn}).scalar_one() is None:
            out.append(f"function {fn} is missing")
    trig = {r.tgname: r for r in conn.execute(text(
        "SELECT t.tgname, t.tgrelid::regclass::text AS tbl, t.tgfoid::regprocedure::text AS fn, "
        "t.tgenabled, t.tgdeferrable, t.tginitdeferred, t.tgtype FROM pg_trigger t "
        "WHERE NOT t.tgisinternal AND t.tgname = ANY(:names)"), {"names": list(EXPECTED_TRIGGERS)})}  # fmt: skip
    for name, (tbl, fn, tgtype, deferred) in EXPECTED_TRIGGERS.items():
        r = trig.get(name)
        if r is None:
            out.append(f"trigger {name} is missing")
            continue
        if r.tbl != tbl or r.fn != fn or r.tgtype != tgtype:
            out.append(f"trigger {name} is not the app_0008 definition ({r.tbl}, {r.fn}, "
                       f"type {r.tgtype})")  # fmt: skip
        if r.tgenabled not in ("O", "A"):
            out.append(f"trigger {name} is disabled (tgenabled={r.tgenabled})")
        if (bool(r.tgdeferrable) and bool(r.tginitdeferred)) != deferred:
            out.append(f"trigger {name} deferral differs from app_0008")
    con = conn.execute(text(
        "SELECT contype, convalidated FROM pg_constraint WHERE conname = "
        "'round_schedules_no_overlap' AND conrelid = 'app.round_schedules'::regclass")).first()  # fmt: skip
    if con is None or con.contype != "x" or not con.convalidated:
        out.append("exclusion constraint round_schedules_no_overlap is missing or not validated")
    idx = conn.execute(text(
        "SELECT i.indisunique, i.indisvalid, i.indisready, i.indpred IS NOT NULL AS partial, "
        "i.indrelid = 'app.round_schedules'::regclass AS on_table FROM pg_index i "
        "WHERE i.indexrelid = to_regclass('app.round_schedules_one_open')")).first()  # fmt: skip
    if idx is None or not (idx.indisunique and idx.indisvalid and idx.indisready
                           and idx.partial and idx.on_table):  # fmt: skip
        out.append("unique index round_schedules_one_open is missing, invalid or not partial")
    return out


def privilege_problems(conn: Connection, *, cancel: bool = False) -> list[str]:
    """Every privilege the operation needs, checked one by one for the executing
    role (inherited privileges count), and no schedule write privilege for the
    runtime role."""
    need = [("app.round_schedules", p) for p in ("SELECT", "INSERT", "UPDATE")]
    if cancel:
        need.append(("app.round_schedules", "DELETE"))
    need += [("app.rounds", "SELECT"), ("app.audit_log", "SELECT"), ("app.audit_log", "INSERT"),
             ("app.users", "SELECT"), ("app.user_roles", "SELECT"),
             ("app.users", "UPDATE"), ("app.user_roles", "UPDATE")]  # FOR SHARE needs UPDATE
    out = []
    for table, priv in need:
        ok = conn.execute(text("SELECT has_table_privilege(current_user, :t, :p)"),
                          {"t": table, "p": priv}).scalar_one()  # fmt: skip
        if not ok:
            out.append(f"the database role lacks {priv} on {table}")
    if not conn.execute(text("SELECT has_function_privilege(current_user, "
                             "'app.schedule_write_lock()', 'EXECUTE')")).scalar_one():  # fmt: skip
        out.append("the database role cannot execute app.schedule_write_lock()")
    if conn.execute(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :r)"),
                    {"r": RUNTIME_ROLE}).scalar_one():  # fmt: skip
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            if conn.execute(text("SELECT has_table_privilege(:r, 'app.round_schedules', :p)"),
                            {"r": RUNTIME_ROLE, "p": priv}).scalar_one():  # fmt: skip
                out.append(f"privilege drift: the runtime role {RUNTIME_ROLE} has {priv} on "
                           "app.round_schedules")  # fmt: skip
        if conn.execute(text("SELECT has_function_privilege(:r, 'app.schedule_write_lock()', "
                             "'EXECUTE')"), {"r": RUNTIME_ROLE}).scalar_one():  # fmt: skip
            out.append(f"privilege drift: the runtime role {RUNTIME_ROLE} can take the schedule "
                       "write lock")  # fmt: skip
    return out


def owner_problems(conn: Connection, actor: Principal) -> list[str]:
    """The actor is still an active owner, re-read inside the write transaction. The
    account and role rows are held FOR SHARE until commit, so a concurrent
    revocation or suspension waits instead of interleaving. Those transactions
    never take the schedule lock, so there is no lock cycle."""
    if actor.user_id is None:
        return ["no verified actor"]
    status = conn.execute(text("SELECT status FROM app.users WHERE id = :u FOR SHARE"),
                          {"u": actor.user_id}).scalar_one_or_none()  # fmt: skip
    role = conn.execute(text("SELECT 1 FROM app.user_roles WHERE user_id = :u AND role = 'owner' "
                             "FOR SHARE"), {"u": actor.user_id}).first()  # fmt: skip
    out = []
    if status != "active":
        out.append("the acting account is not active")
    if role is None:
        out.append("the acting account no longer holds the owner role")
    return out


# ------------------------------------------------------------------ state
def _rows(conn: Connection, code: str) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in conn.execute(text(
        "SELECT id, code, version, config_version, active_from, active_to, created_at, "
        f"{', '.join(COPIED)} FROM app.round_schedules WHERE code = :c ORDER BY version"),
        {"c": code})]  # fmt: skip


def _audits(conn: Connection, schedule_id: int) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in conn.execute(text(
        "SELECT id, at, action, actor_user_id, reason, after FROM app.audit_log "
        "WHERE target_type = :tt AND target_id = :t AND action IN (:a, :c) ORDER BY id"),
        {"tt": AUDIT_TARGET, "t": str(schedule_id), "a": ACTIVATE_ACTION, "c": CANCEL_ACTION})]  # fmt: skip


def _round_stats(conn: Connection, schedule_id: int, T: datetime | None) -> dict[str, Any]:
    r = conn.execute(text(
        "SELECT count(*) AS n, max(created_at) AS last, "
        "count(*) FILTER (WHERE created_at >= :t) AS at_or_after "
        "FROM app.rounds WHERE schedule_id = :s"), {"s": schedule_id, "t": T}).one()  # fmt: skip
    return {"rounds": r.n, "last_created_at": r.last, "at_or_after_T": r.at_or_after or 0}


def _wallclock(conn: Connection) -> datetime:
    """The database wall clock (cancellation margin only; seam for tests)."""
    return conn.execute(text("SELECT clock_timestamp()")).scalar_one()


def _db_now(conn: Connection) -> datetime:
    return conn.execute(text("SELECT transaction_timestamp()")).scalar_one()


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _jsonable(row: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if row is None else {k: _iso(v) for k, v in row.items()}


def _parse(v) -> datetime | None:
    try:
        return datetime.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


# ------------------------------------------------------------------ assessment
@dataclass
class ActivationAssessment:
    outcome: str  # "activate", "already_installed" or "refused"
    T: datetime
    reasons: list[str] = field(default_factory=list)
    v2: dict[str, Any] | None = None
    v3: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    v2_rounds: dict[str, Any] | None = None
    activation_audit: dict[str, Any] | None = None


def _installed_problems(conn, v2, v3, T, approval_ref) -> tuple[list[str], dict | None]:
    """Exact idempotence: every element of an installed transition must agree with
    the request, including its audit evidence."""
    p = []
    if v3["config_version"] != TO_CONFIG:
        p.append(f"conflicting configuration: v3 uses {v3['config_version']}")
    if v3["active_from"] != T:
        p.append(f"conflicting activation time: v3 is installed for "
                 f"{v3['active_from'].isoformat()}")  # fmt: skip
    if v3["active_to"] is not None:
        p.append("v3 is not open-ended")
    if v2 is None:
        return p + ["v2 is missing"], None
    if v2["active_to"] != v3["active_from"]:
        p.append("v2 does not close exactly when v3 opens")
    if (v2["config_version"], v2["rules_version"], v2["scoring_version"]) != (
            FROM_CONFIG, RULES_VERSION, SCORING_VERSION):  # fmt: skip
        p.append("v2 is not the expected broad60 / settle/v1 / points-150-75-v2 row")
    diff = [c for c in COPIED if v2[c] != v3[c]]
    if diff:
        p.append(f"v3 differs from v2 in {', '.join(diff)}")
    audits = _audits(conn, v3["id"])
    acts = [a for a in audits if a["action"] == ACTIVATE_ACTION]
    if any(a["action"] == CANCEL_ACTION for a in audits):
        p.append(f"v3 (schedule {v3['id']}) has a cancellation record but still exists")
    if len(acts) != 1:
        p.append(f"unexplained transition: {len(acts)} activation audit record(s) for schedule "
                 f"{v3['id']} (exactly one is required)")  # fmt: skip
        return p, None
    after = acts[0]["after"] or {}
    if after.get("approval_ref") != approval_ref:
        p.append(f"conflicting approval reference: installed under {after.get('approval_ref')!r}")
    if _parse(after.get("active_from")) != v3["active_from"]:
        p.append("the activation audit record's T does not match v3")
    if (after.get("to_schedule") or {}).get("id") != v3["id"] or (
            after.get("from_schedule") or {}).get("id") != v2["id"]:  # fmt: skip
        p.append("the activation audit record does not match the installed schedule rows")
    return p, acts[0]


def assess_activation(conn: Connection, T: datetime, approval_ref: str, *,
                      schedule_code: str = SCHEDULE_CODE, from_version: int = FROM_VERSION,
                      config_version: str = TO_CONFIG) -> ActivationAssessment:  # fmt: skip
    """Classify an activation request against the current state (read-only)."""
    a = ActivationAssessment("refused", T)
    if (schedule_code, from_version, config_version) != (SCHEDULE_CODE, FROM_VERSION, TO_CONFIG):
        a.reasons.append(f"only {SCHEDULE_CODE} v{FROM_VERSION} ({FROM_CONFIG}) → "
                         f"v{TO_VERSION} ({TO_CONFIG}) is authorised")  # fmt: skip
        return a
    a.reasons += config_problems()
    a.rows = _rows(conn, SCHEDULE_CODE)
    by_v = {r["version"]: r for r in a.rows}
    a.v2, a.v3 = by_v.get(FROM_VERSION), by_v.get(TO_VERSION)
    later = sorted(v for v in by_v if v > TO_VERSION)
    if later:
        a.reasons.append(f"unexpected later schedule version(s) {later}")
    if a.v2 is None:
        a.reasons.append(f"{SCHEDULE_CODE} v{FROM_VERSION} does not exist")
        return a
    a.v2_rounds = _round_stats(conn, a.v2["id"], T)
    if a.v3 is not None:  # an installed transition: exact no-op, or refuse
        probs, audit = _installed_problems(conn, a.v2, a.v3, T, approval_ref)
        a.reasons += probs
        a.activation_audit = audit
        a.outcome = "already_installed" if not a.reasons else "refused"
        return a
    open_rows = [r for r in a.rows if r["active_to"] is None]
    if len(open_rows) != 1 or open_rows[0]["version"] != FROM_VERSION:
        a.reasons.append(f"expected exactly one open-ended {SCHEDULE_CODE} row, v{FROM_VERSION}; "
                         f"found {[r['version'] for r in open_rows]}")  # fmt: skip
    if a.v2["config_version"] != FROM_CONFIG:
        a.reasons.append(f"v{FROM_VERSION} uses {a.v2['config_version']}, not {FROM_CONFIG}")
    if a.v2["rules_version"] != RULES_VERSION:
        a.reasons.append(f"v{FROM_VERSION} rules are {a.v2['rules_version']}, not {RULES_VERSION}")
    if a.v2["scoring_version"] != SCORING_VERSION:
        a.reasons.append(f"v{FROM_VERSION} scoring is {a.v2['scoring_version']}, "
                         f"not {SCORING_VERSION}")  # fmt: skip
    if T <= a.v2["active_from"]:
        a.reasons.append(f"T must be later than v{FROM_VERSION}'s start "
                         f"({a.v2['active_from'].isoformat()})")  # fmt: skip
    if a.v2_rounds["at_or_after_T"]:
        a.reasons.append(f"{a.v2_rounds['at_or_after_T']} round(s) bound to v{FROM_VERSION} were "
                         f"created at or after T (latest {_iso(a.v2_rounds['last_created_at'])}); "
                         "their binding cannot change")  # fmt: skip
    a.outcome = "activate" if not a.reasons else "refused"
    return a


@dataclass
class CancellationAssessment:
    outcome: str  # "cancel" or "refused"
    schedule_id: int
    T: datetime
    clock: datetime
    reasons: list[str] = field(default_factory=list)
    v2: dict[str, Any] | None = None
    v3: dict[str, Any] | None = None
    activation_audit: dict[str, Any] | None = None
    referenced_by: int = 0
    timing: str = "eligible"  # eligible | within_margin | elapsed


def cancellation_timing(clock: datetime, T: datetime) -> str:
    if clock >= T:
        return "elapsed"
    if clock >= T - CANCEL_MARGIN:  # exactly T - 10 min is refused
        return "within_margin"
    return "eligible"


def assess_cancellation(conn: Connection, schedule_id: int, T: datetime,
                        clock: datetime) -> CancellationAssessment:  # fmt: skip
    """Classify a cancellation request: the exact identified transition (schedule id
    AND activation time), its audit evidence, the wall clock and references."""
    c = CancellationAssessment("refused", schedule_id, T, clock)
    rows = _rows(conn, SCHEDULE_CODE)
    by_id = {r["id"]: r for r in rows}
    by_v = {r["version"]: r for r in rows}
    v3 = by_id.get(schedule_id)
    if v3 is None or v3["version"] != TO_VERSION or v3["active_from"] != T:
        c.reasons.append(f"no {SCHEDULE_CODE} v{TO_VERSION} with schedule id {schedule_id} and "
                         f"activation time {T.isoformat()} exists (stale or conflicting "
                         "cancellation instruction)")  # fmt: skip
        return c
    c.v3, c.v2 = v3, by_v.get(FROM_VERSION)
    if v3["config_version"] != TO_CONFIG or v3["active_to"] is not None:
        c.reasons.append("the identified row is not an open-ended a3-432-v1 transition")
    if c.v2 is None or c.v2["active_to"] != T:
        c.reasons.append(f"v{FROM_VERSION} does not close at T")
    if any(v > TO_VERSION for v in by_v):
        c.reasons.append("unexpected later schedule versions exist")
    audits = _audits(conn, schedule_id)
    acts = [a for a in audits if a["action"] == ACTIVATE_ACTION]
    if len(acts) != 1 or any(a["action"] == CANCEL_ACTION for a in audits):
        c.reasons.append(f"audit evidence for schedule {schedule_id} is inconsistent "
                         f"({len(acts)} activation record(s))")  # fmt: skip
    else:
        c.activation_audit = acts[0]
        if _parse((acts[0]["after"] or {}).get("active_from")) != T:
            c.reasons.append("the activation audit record's T does not match")
    c.timing = cancellation_timing(clock, T)
    if c.timing == "elapsed":
        c.reasons.append("T has passed: cancellation is prohibited; any reversal must be a "
                         "separately approved forward-only schedule version")  # fmt: skip
    elif c.timing == "within_margin":
        c.reasons.append(f"less than {int(CANCEL_MARGIN.total_seconds() // 60)} minutes before T "
                         "(the cancellation safety margin): cancellation is prohibited")  # fmt: skip
    c.referenced_by = _round_stats(conn, schedule_id, None)["rounds"]
    if c.referenced_by:
        c.reasons.append(f"{c.referenced_by} round(s) are bound to schedule {schedule_id}; "
                         "historical bindings are immutable")  # fmt: skip
    c.outcome = "cancel" if not c.reasons else "refused"
    return c


# ------------------------------------------------------------------ transaction plumbing
def _begin_locked(conn: Connection) -> None:
    """Transaction setup, then the exclusive schedule write lock; nothing reads
    schedule or round data before it."""
    iso = conn.execute(text("SELECT current_setting('transaction_isolation')")).scalar_one()
    if iso != "read committed":
        raise TransitionRefused(f"The operation must run at READ COMMITTED (this transaction is "
                                f"{iso}). Nothing was changed.", details=["isolation"])  # fmt: skip
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL idle_in_transaction_session_timeout = '{IDLE_TIMEOUT}'"))
    if conn.execute(text("SELECT to_regprocedure('app.schedule_write_lock()')")).scalar_one() is None:
        raise TransitionRefused("The app_0008 schedule safeguards are not installed "
                                "(app.schedule_write_lock() is missing). Nothing was changed.",
                                details=["safeguards"])  # fmt: skip
    try:
        conn.execute(text("SELECT app.schedule_write_lock()"))
    except DBAPIError as exc:
        if _sqlstate(exc) == "55P03":
            raise TransitionRefused(f"The schedule lock was not available within {LOCK_TIMEOUT} "
                                    "(round creation or another schedule change in progress). "
                                    "Nothing was changed.", details=["lock_timeout"]) from None  # fmt: skip
        raise


def _sqlstate(exc: BaseException) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


def _commit(trans) -> None:
    """COMMIT (a seam for tests that simulate a lost connection)."""
    trans.commit()


def _commit_or_uncertain(trans, what: str) -> None:
    try:
        _commit(trans)
    except DBAPIError as exc:
        state = _sqlstate(exc)
        if state is not None and not state.startswith(("08", "57")):
            # the server reported the failure: the transaction was rolled back
            raise TransitionRefused(f"The {what} was rolled back by the database at commit "
                                    f"({state}): {str(exc.orig).splitlines()[0]}. Nothing was "
                                    "changed.", details=[state]) from exc  # fmt: skip
        raise TransitionUncertain(f"The connection failed while committing the {what}; whether it "
                                  "committed is unknown. Do not retry or reverse it: reconcile "
                                  "read-only first (round schedules, the plan command, the audit "
                                  "log).", details=[state]) from exc  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - any non-database failure: equally unknown
        raise TransitionUncertain(f"Committing the {what} failed unexpectedly "
                                  f"({type(exc).__name__}); the outcome is unknown. Reconcile "
                                  "read-only before any further action.") from exc  # fmt: skip


def _refuse_if(reasons: list[str], what: str) -> None:
    if reasons:
        raise TransitionRefused(f"{what} refused; nothing was changed: " + "; ".join(reasons),
                                details=reasons)  # fmt: skip


def _rollback_quietly(trans) -> None:
    try:
        if trans.is_active:
            trans.rollback()
    except Exception:  # noqa: BLE001 - a broken connection rolls back on its own
        pass


def _to_refusal(exc: DBAPIError, what: str) -> TransitionRefused:
    first = str(getattr(exc, "orig", exc)).splitlines()[0]
    return TransitionRefused(f"The database refused the {what} ({_sqlstate(exc)}): {first}. "
                             "Nothing was changed.", details=[_sqlstate(exc)])  # fmt: skip


# ------------------------------------------------------------------ results
@dataclass(frozen=True)
class ActivationResult:
    status: str  # "activated" or "already_installed"
    T: datetime
    from_schedule_id: int
    to_schedule_id: int
    audit_id: int | None
    clock_after: datetime | None
    lead_time: timedelta | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CancellationResult:
    status: str  # "cancelled"
    schedule_id: int
    T: datetime
    audit_id: int
    clock_after: datetime


def lead_time_warnings(lead: timedelta) -> list[str]:
    if lead <= timedelta(0):
        return [f"T is in the past (by {-lead}); only disposable test databases or explicitly "
                "approved recovery/historical replay may use a past T"]  # fmt: skip
    if lead < LEAD_TIME_POLICY:
        return [f"T is only {lead} away: below the 72-hour operational lead time (operational "
                "approval required; not enforced by the software)"]  # fmt: skip
    return []


# ------------------------------------------------------------------ activation
def activate(engine: Engine, actor: Principal, *, active_from: str | datetime,
             approval_ref: str, reason: str, schedule_code: str = SCHEDULE_CODE,
             from_version: int = FROM_VERSION, config_version: str = TO_CONFIG,
             build: dict[str, Any] | None = None) -> ActivationResult:  # fmt: skip
    """Close weekend v2 at T and open v3 on a3-432-v1, atomically with its audit
    record, or recognise the exact same transition as already installed (no write)."""
    T = parse_utc_instant(active_from)
    _require_text(approval_ref=approval_ref, reason=reason)
    authorize(actor, Capability.SCHEDULE_ACTIVATE)
    if build is None:
        from diski9.buildinfo import identity_for_records

        build = identity_for_records("cli")
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            _begin_locked(conn)
            reasons = safeguard_problems(conn) + privilege_problems(conn)
            reasons += owner_problems(conn, actor)
            a = assess_activation(conn, T, approval_ref.strip(), schedule_code=schedule_code,
                                  from_version=from_version, config_version=config_version)  # fmt: skip
            _refuse_if(reasons + a.reasons, "Activation")
            now = _db_now(conn)
            if a.outcome == "already_installed":
                trans.rollback()
                return ActivationResult("already_installed", T, a.v2["id"], a.v3["id"],
                                        a.activation_audit["id"], None, T - now, ())  # fmt: skip
            v2 = a.v2
            conn.execute(text("UPDATE app.round_schedules SET active_to = :t "
                              "WHERE id = :id AND active_to IS NULL"), {"t": T, "id": v2["id"]})  # fmt: skip
            cols = ", ".join(COPIED)
            new = conn.execute(text(
                f"INSERT INTO app.round_schedules (code, version, {cols}, config_version, "
                f"active_from) SELECT code, :v, {cols}, :cfg, :t FROM app.round_schedules "
                "WHERE id = :id RETURNING id, created_at"),
                {"v": TO_VERSION, "cfg": TO_CONFIG, "t": T, "id": v2["id"]}).one()  # fmt: skip
            v3 = {**{c: v2[c] for c in COPIED}, "id": new.id, "code": SCHEDULE_CODE,
                  "version": TO_VERSION, "config_version": TO_CONFIG, "active_from": T,
                  "active_to": None, "created_at": new.created_at}  # fmt: skip
            lead = T - now
            audit_id = record_audit(
                conn, action=ACTIVATE_ACTION, target_type=AUDIT_TARGET, target_id=str(new.id),
                actor=actor.user_id, actor_role="owner", reason=reason.strip(),
                before={"from_schedule": _jsonable(v2)},
                after={"schedule_code": SCHEDULE_CODE, "approval_ref": approval_ref.strip(),
                       "active_from": T.isoformat(),
                       "from_schedule": {**_jsonable(v2), "active_to": T.isoformat(),
                                         "fingerprint": APPROVED_FINGERPRINTS[FROM_CONFIG]},
                       "to_schedule": {**_jsonable(v3),
                                       "fingerprint": APPROVED_FINGERPRINTS[TO_CONFIG]},
                       "fingerprints": dict(APPROVED_FINGERPRINTS),
                       "lead_time_seconds": int(lead.total_seconds()),
                       "build": build})  # fmt: skip
        except DBAPIError as exc:
            _rollback_quietly(trans)
            raise _to_refusal(exc, "activation") from exc
        except BaseException:
            _rollback_quietly(trans)
            raise
        _commit_or_uncertain(trans, "activation")
    # post-commit verification (read-only): the result must be exactly installed
    try:
        with read_only(engine) as conn:
            check = assess_activation(conn, T, approval_ref.strip())
            clock = _wallclock(conn)
    except Exception as exc:  # noqa: BLE001
        raise TransitionUncertain("The activation committed but could not be verified "
                                  f"({type(exc).__name__}). Reconcile read-only before any "
                                  "further action.") from exc  # fmt: skip
    if check.outcome != "already_installed" or check.v3["id"] != new.id:
        raise TransitionUncertain("The activation committed but post-commit verification did not "
                                  "confirm it: " + "; ".join(check.reasons),
                                  details=check.reasons)  # fmt: skip
    return ActivationResult("activated", T, v2["id"], new.id, audit_id, clock, lead,
                            tuple(lead_time_warnings(lead)))  # fmt: skip


# ------------------------------------------------------------------ cancellation
def cancel_activation(engine: Engine, actor: Principal, *, schedule_id: int,
                      active_from: str | datetime, approval_ref: str, reason: str,
                      build: dict[str, Any] | None = None) -> CancellationResult:  # fmt: skip
    """Remove the exact, unreferenced, scheduled transition (identified by its
    schedule id AND activation time) and reopen v2, strictly before T − 10 min.
    Both wall-clock checks (after the lock, and immediately before COMMIT) enforce
    the margin. The margin bounds the residual risk: it cannot absolutely
    guarantee that COMMIT completes before T. The clock observed after COMMIT is
    checked and an incident is raised if it is at or past T."""
    T = parse_utc_instant(active_from)
    _require_text(approval_ref=approval_ref, reason=reason)
    if not isinstance(schedule_id, int) or isinstance(schedule_id, bool):
        raise TransitionRefused("The exact schedule id is required.", details=["schedule_id"])
    authorize(actor, Capability.SCHEDULE_ACTIVATE)
    if build is None:
        from diski9.buildinfo import identity_for_records

        build = identity_for_records("cli")
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            _begin_locked(conn)
            reasons = safeguard_problems(conn) + privilege_problems(conn, cancel=True)
            reasons += owner_problems(conn, actor)
            c = assess_cancellation(conn, schedule_id, T, _wallclock(conn))
            _refuse_if(reasons + c.reasons, "Cancellation")
            n = conn.execute(text("DELETE FROM app.round_schedules WHERE id = :id"),
                             {"id": schedule_id}).rowcount  # fmt: skip
            m = conn.execute(text("UPDATE app.round_schedules SET active_to = NULL "
                                  "WHERE id = :id AND active_to = :t"),
                             {"id": c.v2["id"], "t": T}).rowcount  # fmt: skip
            if (n, m) != (1, 1):
                raise TransitionRefused("Cancellation refused: the schedule rows changed "
                                        "unexpectedly. Nothing was changed.")  # fmt: skip
            audit_id = record_audit(
                conn, action=CANCEL_ACTION, target_type=AUDIT_TARGET, target_id=str(schedule_id),
                actor=actor.user_id, actor_role="owner", reason=reason.strip(),
                before={"cancelled_schedule": _jsonable(c.v3)},
                after={"schedule_code": SCHEDULE_CODE, "approval_ref": approval_ref.strip(),
                       "cancelled_schedule_id": schedule_id, "active_from": T.isoformat(),
                       "activation_audit_id": c.activation_audit["id"],
                       "reopened_schedule_id": c.v2["id"], "margin_minutes":
                       int(CANCEL_MARGIN.total_seconds() // 60), "build": build})  # fmt: skip
            final = cancellation_timing(_wallclock(conn), T)  # immediately before COMMIT
            if final != "eligible":
                raise TransitionRefused("Cancellation refused at the final check: the safety "
                                        "margin before T has been reached. Nothing was changed.",
                                        details=[final])  # fmt: skip
        except DBAPIError as exc:
            _rollback_quietly(trans)
            raise _to_refusal(exc, "cancellation") from exc
        except BaseException:
            _rollback_quietly(trans)
            raise
        _commit_or_uncertain(trans, "cancellation")
    try:
        with read_only(engine) as conn:
            clock = _wallclock(conn)
            gone = conn.execute(text("SELECT NOT EXISTS (SELECT 1 FROM app.round_schedules "
                                     "WHERE id = :id)"), {"id": schedule_id}).scalar_one()  # fmt: skip
            reopened = conn.execute(text("SELECT active_to IS NULL FROM app.round_schedules "
                                         "WHERE id = :id"), {"id": c.v2["id"]}).scalar_one()  # fmt: skip
            audited = any(a["id"] == audit_id for a in _audits(conn, schedule_id))
    except Exception as exc:  # noqa: BLE001
        raise TransitionUncertain("The cancellation committed but could not be verified "
                                  f"({type(exc).__name__}). Reconcile read-only before any "
                                  "further action.") from exc  # fmt: skip
    if not (gone and reopened and audited):
        raise TransitionUncertain("The cancellation committed but post-commit verification did "
                                  "not confirm the expected state. Reconcile read-only.")  # fmt: skip
    if clock >= T:
        raise CancellationIncident(
            f"OPERATIONAL INCIDENT: the cancellation committed, but the database clock read "
            f"after COMMIT ({clock.isoformat()}) is at or past T ({T.isoformat()}). That "
            "observation is not the exact commit time. Follow the incident procedure; do not "
            "reverse or retry automatically.", details={"clock_after": clock.isoformat(),
                                                        "audit_id": audit_id})  # fmt: skip
    return CancellationResult("cancelled", schedule_id, T, audit_id, clock)


# ------------------------------------------------------------------ read-only plans
@dataclass
class Plan:
    kind: str  # "activation" or "cancellation"
    outcome: str
    clock: datetime
    lines: list[str]
    reasons: list[str]
    warnings: list[str]


ADVISORY = ("ADVISORY PLAN (read-only, no lock taken): nothing was changed. A successful "
            "plan does not guarantee execution: every check is repeated under the exclusive "
            "schedule lock when the operation is confirmed.")  # fmt: skip


def _row_line(r: dict[str, Any]) -> str:
    to = "open-ended" if r["active_to"] is None else r["active_to"].isoformat()
    return (f"  {r['code']} v{r['version']} (schedule id {r['id']}) "
            f"[{r['active_from'].isoformat()}, {to}) {r['config_version']}")


def plan_activation(engine: Engine, *, active_from: str | datetime, approval_ref: str,
                    schedule_code: str = SCHEDULE_CODE, from_version: int = FROM_VERSION,
                    config_version: str = TO_CONFIG) -> Plan:  # fmt: skip
    T = parse_utc_instant(active_from)
    with read_only(engine) as conn:
        clock = _wallclock(conn)
        reasons = safeguard_problems(conn) + privilege_problems(conn)
        a = assess_activation(conn, T, (approval_ref or "").strip(), schedule_code=schedule_code,
                              from_version=from_version, config_version=config_version)  # fmt: skip
    reasons += a.reasons
    lead = T - clock
    warnings = lead_time_warnings(lead)
    lines = [ADVISORY, f"database clock {clock.isoformat()}; requested T {T.isoformat()}; "
             f"lead time {lead}", "current rows:"] + [_row_line(r) for r in a.rows]  # fmt: skip
    if a.v2_rounds:
        lines.append(f"rounds bound to v{FROM_VERSION}: {a.v2_rounds['rounds']} (latest created "
                     f"{_iso(a.v2_rounds['last_created_at']) or '-'}); at or after T: "
                     f"{a.v2_rounds['at_or_after_T']}")  # fmt: skip
    if a.outcome == "already_installed" and not reasons:
        outcome = "already_installed"
        lines.append(f"already installed exactly (schedule id {a.v3['id']}): confirming is a "
                     "no-op")  # fmt: skip
    elif not reasons:
        outcome = "would_activate"
        lines += ["proposed result:",
                  f"  {SCHEDULE_CODE} v{FROM_VERSION} closes at {T.isoformat()}",
                  f"  {SCHEDULE_CODE} v{TO_VERSION} opens at {T.isoformat()} on {TO_CONFIG} "
                  "(every other attribute copied from v2, including series)",
                  "  rounds created before T keep v2 (broad60) even if published after T"]  # fmt: skip
    else:
        outcome = "would_refuse"
    lines += [f"WARNING: {w}" for w in warnings] + [f"REFUSAL: {r}" for r in reasons]
    lines.append("authorisation (owner identity and database privileges) is verified at "
                 "execution")  # fmt: skip
    return Plan("activation", outcome, clock, lines, reasons, warnings)


def plan_cancellation(engine: Engine, *, schedule_id: int, active_from: str | datetime) -> Plan:
    T = parse_utc_instant(active_from)
    with read_only(engine) as conn:
        clock = _wallclock(conn)
        reasons = safeguard_problems(conn) + privilege_problems(conn, cancel=True)
        c = assess_cancellation(conn, schedule_id, T, clock)
        rows = _rows(conn, SCHEDULE_CODE)
    reasons += c.reasons
    lines = [ADVISORY, f"database clock {clock.isoformat()}; identified transition: schedule "
             f"id {schedule_id}, T {T.isoformat()}; time to T {T - clock}; cancellation "
             f"allowed only before T − {CANCEL_MARGIN} ({(T - CANCEL_MARGIN).isoformat()})",
             "current rows:"] + [_row_line(r) for r in rows]  # fmt: skip
    if not reasons:
        lines += ["proposed result:", f"  schedule {schedule_id} (v{TO_VERSION}) is deleted",
                  f"  {SCHEDULE_CODE} v{FROM_VERSION} is reopened (open-ended)",
                  "  the activation audit record is kept; a cancellation record is added"]  # fmt: skip
    lines += [f"REFUSAL: {r}" for r in reasons]
    return Plan("cancellation", "would_cancel" if not reasons else "would_refuse", clock, lines,
                reasons, [])  # fmt: skip


# ------------------------------------------------------------------ inspection
@dataclass(frozen=True)
class TransitionStatus:
    state: str  # absent | scheduled | active | unexpected
    schedule_id: int | None
    T: datetime | None
    referenced_by: int
    timing: str | None  # eligible | within_margin | elapsed (for scheduled/active)
    detail: str

    def summary(self) -> str:
        return self.detail


def transition_status(conn: Connection) -> TransitionStatus:
    """Read-only: is the A3 transition absent, scheduled (T in the future) or active?"""
    rows = _rows(conn, SCHEDULE_CODE)
    later = [r for r in rows if r["version"] > FROM_VERSION]
    clock = _wallclock(conn)
    if not later:
        open_rows = [r for r in rows if r["active_to"] is None]
        cfg = open_rows[0]["config_version"] if len(open_rows) == 1 else "?"
        return TransitionStatus("absent", None, None, 0, None,
                                f"A3 transition: not installed ({SCHEDULE_CODE} runs on {cfg})")  # fmt: skip
    v3 = next((r for r in later if r["version"] == TO_VERSION), None)
    if len(later) != 1 or v3 is None or v3["config_version"] != TO_CONFIG:
        return TransitionStatus("unexpected", None, None, 0, None,
                                "A3 transition: UNEXPECTED schedule state (versions "
                                f"{[r['version'] for r in rows]}); inspect before acting")  # fmt: skip
    refs = _round_stats(conn, v3["id"], None)["rounds"]
    timing = cancellation_timing(clock, v3["active_from"])
    if timing == "elapsed":
        return TransitionStatus("active", v3["id"], v3["active_from"], refs, timing,
                                f"A3 transition: ACTIVE since {v3['active_from'].isoformat()} "
                                f"(schedule id {v3['id']}; {refs} round(s) bound to it)")  # fmt: skip
    return TransitionStatus("scheduled", v3["id"], v3["active_from"], refs, timing,
                            f"A3 transition: SCHEDULED for {v3['active_from'].isoformat()} "
                            f"(schedule id {v3['id']}; in {v3['active_from'] - clock}; "
                            f"cancellable: {'yes' if timing == 'eligible' else 'no, inside the 10-minute safety margin'})")  # fmt: skip
