"""Backup, restore and recovery records in the competition database (Phase 6C.6
Stage F2). Each record is one completed ``app.job_runs`` row (insert-only; the Stage
D guard on running rows is untouched). Arguments hold file names, sizes, SHA-256
prefixes and labels only: never a path, URL, host name or credential.

Evidence levels are kept strictly apart (safeguard B):

=====================  ======================  ==========================================
Level                  Record                  Established by
=====================  ======================  ==========================================
1 local created        ``ops.backup_store`` /  this application (the backup command)
                       ``ops.backup_postgres``
2 local verified       same row, verified=true this application: integrity + checksum
                                               (store); dump header + checksum (PostgreSQL)
3 off-host copy        ``ops.backup_offhost``  *reported* by the host's copy hook after it
                                               succeeded; not verified by Diski 9
4 off-host restore     ``ops.restore_drill``   a restore drill; the restored content is
  drill                                        checked against a recorded backup checksum,
                                               the off-host origin is operator-declared
=====================  ======================  ==========================================

A competition-database restore (``ops.restore_postgres``) places a **provider hold**:
the scheduler makes no provider calls (results imports, refresh) until an
authenticated operator records ``ops.provider_resume`` after reconciliation
(safeguard D), whatever ``DISKI9_JOBS_PROVIDER_CALLS`` says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, func, insert, select

BACKUP_STORE = "ops.backup_store"
BACKUP_POSTGRES = "ops.backup_postgres"
BACKUP_OFFHOST = "ops.backup_offhost"
RESTORE_STORE = "ops.restore_store"
RESTORE_DRILL = "ops.restore_drill"
RESTORE_POSTGRES = "ops.restore_postgres"
PROVIDER_RESUME = "ops.provider_resume"
RECORD_JOBS = (BACKUP_STORE, BACKUP_POSTGRES, BACKUP_OFFHOST, RESTORE_STORE, RESTORE_DRILL,
               RESTORE_POSTGRES, PROVIDER_RESUME)  # fmt: skip

LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")


def safe_label(value: str | None, what: str = "label") -> str | None:
    """A short free-text label (destination nickname, note): letters, digits, space,
    ``_ . -``, at most 40 characters, so a URL or credential cannot be recorded."""
    if value is None:
        return None
    value = value.strip()
    if not LABEL_RE.fullmatch(value):
        raise ValueError(f"{what} must be 1-40 characters of letters, digits, space, '_', '.' "
                         "or '-' (no URLs, paths or credentials)")  # fmt: skip
    return value


def record(conn: Connection, job: str, args: dict, *, ok: bool = True,
           detail: str | None = None, host: str | None = None) -> int:  # fmt: skip
    """Insert one completed record and return its id."""
    from diski9.backend.db.schema import job_runs

    assert job in RECORD_JOBS, job
    now = func.clock_timestamp()
    return conn.execute(
        insert(job_runs)
        .values(
            job=job,
            scope="",
            args=args,
            started_at=now,
            finished_at=now,
            status="succeeded" if ok else "failed",
            api_requests=0,
            error=detail,
            host=host,
        )  # fmt: skip
        .returning(job_runs.c.id)
    ).scalar_one()


@dataclass(frozen=True)
class Rec:
    id: int
    job: str
    at: datetime
    ok: bool
    args: dict
    detail: str | None


def latest(conn: Connection, job: str, *, ok: bool | None = True,
           where: dict | None = None) -> Rec | None:  # fmt: skip
    from diski9.backend.db.schema import job_runs

    jr = job_runs.c
    q = select(jr.id, jr.job, jr.finished_at, jr.status, jr.args, jr.error).where(jr.job == job)
    if ok is not None:
        q = q.where(jr.status == ("succeeded" if ok else "failed"))
    for k, v in (where or {}).items():
        q = q.where(jr.args[k].astext == str(v))
    r = conn.execute(q.order_by(jr.finished_at.desc(), jr.id.desc()).limit(1)).one_or_none()
    if r is None:
        return None
    return Rec(r.id, r.job, r.finished_at, r.status == "succeeded", dict(r.args), r.error)


def matches_recorded_backup(conn: Connection, sha256: str) -> bool:
    """Whether a verified backup with this checksum was recorded (store or dump)."""
    from diski9.backend.db.schema import job_runs

    jr = job_runs.c
    return (
        conn.execute(
            select(func.count())
            .select_from(job_runs)
            .where(
                jr.job.in_((BACKUP_STORE, BACKUP_POSTGRES)),
                jr.status == "succeeded",
                jr.args["sha256_prefix"].astext == sha256[:16],
            )  # fmt: skip
        ).scalar_one()
        > 0
    )


@dataclass(frozen=True)
class ProviderHold:
    restore: Rec

    def describe(self) -> str:
        a = self.restore.args
        return (f"provider calls are held since the competition-database restore recorded "
                f"{self.restore.at:%Y-%m-%d %H:%M} UTC (dump {a.get('file', '?')}): reconcile, "
                "then an operator runs `diski9 ops provider-resume`")  # fmt: skip


def provider_hold(conn: Connection) -> ProviderHold | None:
    """The active hold, if the latest PostgreSQL restore is newer than the latest
    operator resume."""
    restored = latest(conn, RESTORE_POSTGRES)
    if restored is None:
        return None
    resumed = latest(conn, PROVIDER_RESUME)
    if resumed is not None and resumed.id > restored.id:
        return None
    return ProviderHold(restored)


def store_restore_cutoff(conn: Connection) -> datetime | None:
    """When the football store was last restored for recovery: data refresh sweeps
    started before this no longer count as current (consistency safeguard)."""
    r = latest(conn, RESTORE_STORE)
    return r.at if r is not None else None


@dataclass(frozen=True)
class Evidence:
    """The latest record of each kind, for ``ops status`` and the backup findings."""

    store_ok: Rec | None
    store_last: Rec | None  # latest attempt, successful or not
    postgres_ok: Rec | None
    postgres_last: Rec | None
    offhost: Rec | None
    drill: Rec | None
    drill_offhost: Rec | None
    store_restore: Rec | None
    postgres_restore: Rec | None
    hold: ProviderHold | None


def evidence(conn: Connection) -> Evidence:
    return Evidence(
        store_ok=latest(conn, BACKUP_STORE),
        store_last=latest(conn, BACKUP_STORE, ok=None),
        postgres_ok=latest(conn, BACKUP_POSTGRES),
        postgres_last=latest(conn, BACKUP_POSTGRES, ok=None),
        offhost=latest(conn, BACKUP_OFFHOST),
        drill=latest(conn, RESTORE_DRILL),
        drill_offhost=latest(conn, RESTORE_DRILL, where={"source_origin": "offhost"}),
        store_restore=latest(conn, RESTORE_STORE),
        postgres_restore=latest(conn, RESTORE_POSTGRES),
        hold=provider_hold(conn),
    )
