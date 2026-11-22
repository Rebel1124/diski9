"""Backup-health findings and status lines (Phase 6C.6 Stage F2, SF-10, safeguard B).

Off unless ``DISKI9_OPS_BACKUP_EXPECTED=on`` (an INFO finding says so). Each evidence
level is reported for exactly what was recorded: a local backup that was created and
verified says nothing about an off-host copy, and a reported off-host copy says
nothing about whether it can be restored. Only a recorded restore drill whose
restored content matched a recorded backup counts as restore evidence, and its
off-host origin is always described as operator-declared.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .checks import Severity


def _age(now: datetime, then: datetime | None) -> str:
    if then is None:
        return "never"
    h = (now - then).total_seconds() / 3600
    return f"{h:.0f} h ago" if h < 72 else f"{h / 24:.0f} d ago"


def _stale(add, now, rec, code, subject, what, warn: timedelta, crit: timedelta) -> None:
    if rec is None:
        add(Severity.CRITICAL, "backup", code, subject, f"no {what} has been recorded")
    elif now - rec.at > crit:
        add(Severity.CRITICAL, "backup", code, subject,
            f"the last {what} was recorded {_age(now, rec.at)} "
            f"(critical after {crit})")  # fmt: skip
    elif now - rec.at > warn:
        add(Severity.WARNING, "backup", code, subject,
            f"the last {what} was recorded {_age(now, rec.at)} "
            f"(warning after {warn})")  # fmt: skip


def backup_findings(snap, ops, add) -> None:
    ev = snap.backups
    now = snap.now
    if ev is None:
        return
    # the provider hold is reported whether or not backup monitoring is on
    if ev.hold is not None:
        add(Severity.WARNING, "backup", "provider_hold_after_restore", "provider",
            ev.hold.describe())  # fmt: skip
    if ev.store_restore is not None and now - ev.store_restore.at <= timedelta(days=7):
        add(Severity.INFO, "backup", "store_restored", "football_store",
            f"the football store was restored for recovery {_age(now, ev.store_restore.at)} "
            f"({ev.store_restore.args.get('target', '?')}); refresh sweeps before it no "
            "longer count as current")  # fmt: skip
    if not ops.backup_expected:
        add(Severity.INFO, "backup", "backup_monitoring_off", "backup",
            "backup monitoring is off (DISKI9_OPS_BACKUP_EXPECTED); no backup evidence is "
            "being checked")  # fmt: skip
        return
    w, c = ops.backup_warning, ops.backup_critical
    if (
        ev.store_last is not None
        and not ev.store_last.ok
        and (ev.store_ok is None or ev.store_last.id > ev.store_ok.id)
    ):
        add(Severity.WARNING, "backup", "backup_failed", "football_store",
            f"the latest football-store backup failed verification "
            f"{_age(now, ev.store_last.at)}")  # fmt: skip
    _stale(add, now, ev.store_ok, "backup_store_stale", "football_store",
           "verified local football-store backup", w, c)  # fmt: skip
    if (
        ev.postgres_last is not None
        and not ev.postgres_last.ok
        and (ev.postgres_ok is None or ev.postgres_last.id > ev.postgres_ok.id)
    ):
        add(Severity.WARNING, "backup", "backup_failed", "postgres",
            "the latest PostgreSQL dump record failed its checks")  # fmt: skip
    _stale(add, now, ev.postgres_ok, "backup_postgres_stale", "postgres",
           "local PostgreSQL dump (header and checksum)", w, c)  # fmt: skip
    _stale(add, now, ev.offhost, "backup_offhost_stale", "offhost",
           "off-host copy (reported by the host copy hook; not verified by Diski 9)",
           w, c)  # fmt: skip
    drill = ev.drill_offhost if ev.drill_offhost is not None and \
        ev.drill_offhost.args.get("matches_recorded_backup") else None  # fmt: skip
    if drill is None:
        add(Severity.WARNING, "backup", "offhost_restore_unverified", "offhost",
            "off-host recovery is NOT verified: no restore drill of an off-host copy matching "
            "a recorded backup has been recorded")  # fmt: skip
    elif now - drill.at > ops.drill_max_age:
        add(Severity.WARNING, "backup", "restore_drill_stale", "offhost",
            f"the last off-host restore drill was {_age(now, drill.at)} (expected every "
            f"{ops.drill_max_age.days} days)")  # fmt: skip


def evidence_lines(snap, ops) -> list[str]:
    ev = snap.backups
    if ev is None:
        return []
    now = snap.now

    def rec(r, extra=""):
        return f"{_age(now, r.at)}{extra}" if r is not None else "never recorded"

    drill = ev.drill_offhost
    drill_txt = "never recorded" if drill is None else (
        f"{_age(now, drill.at)} ({drill.args.get('store', '?')}; origin operator-declared; "
        "matches a recorded backup: "
        f"{'yes' if drill.args.get('matches_recorded_backup') else 'no'})"
    )  # fmt: skip
    lines = [
        f"backups (monitoring {'on' if ops.backup_expected else 'off'}):",
        f"  1-2 football store, created and verified locally: {rec(ev.store_ok)}",
        f"  1-2 PostgreSQL dump, created locally (header and checksum): {rec(ev.postgres_ok)}",
        f"  3 off-host copy (reported, not verified by Diski 9): {rec(ev.offhost)}",
        f"  4 off-host copy restored in a drill: {drill_txt}",
    ]
    if ev.hold is not None:
        lines.append(f"  PROVIDER HOLD: {ev.hold.describe()}")
    return lines
