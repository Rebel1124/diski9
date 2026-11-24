"""Schedule resolution by validity interval (Scenario A3, Checkpoint 4A).

A schedule row (``app.round_schedules``) is valid on the half-open interval
``[active_from, active_to)``; ``active_to`` NULL means open-ended. A round is bound to
the row of its schedule code that is valid **at its creation time**, and that time
is the database transaction timestamp: the same instant ``rounds.created_at``
receives in the same transaction, so the choice can always be re-checked.

Rules:

* exactly one row must be valid at the instant; none or several raise
  :class:`ScheduleUnavailable` (fail safe). There is never a fallback to the latest
  version or to the first row;
* every value a round needs from its schedule (window rule, publication rule,
  configuration, deadline buffer, series, settlement hours) comes from that one row;
* the comparison happens in PostgreSQL on ``timestamptz`` values, so neither the
  server's nor the application's time zone takes part; naive datetimes are refused.

Database-level guarantees (no overlaps, no gaps, one open-ended row per code,
immutable referenced rows, validity checked at round insertion, coordination with
schedule migrations) are **not** provided here; they are planned for Checkpoint 4B.
Until then two overlapping rows are detected and refused at resolution time only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, or_, select

from diski9.challenge.config import ChallengeConfig, ConfigError, get_config

from ..db import db_now
from ..db.schema import championship_series, round_schedules
from .common import ServiceError, ValidationFailed


class ScheduleUnavailable(ServiceError):
    """No single schedule row of the code is valid at the instant (none, or an
    overlap). Round creation and anything that depends on it is refused."""

    code = "schedule_unavailable"


def _aware(at: datetime) -> datetime:
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ValidationFailed(
            "Schedule instants must be timezone-aware (UTC recommended).",
            [{"field": "at", "reason": "naive"}],
        )
    return at


def valid_at_clause(at: datetime):
    """SQL condition: the row is valid at ``at`` (half-open interval)."""
    return (round_schedules.c.active_from <= at) & or_(
        round_schedules.c.active_to.is_(None), round_schedules.c.active_to > at
    )


def schedule_at(conn: Connection, code: str, at: datetime) -> Any:
    """The single row of schedule ``code`` valid at ``at`` (with its series code as
    ``series``). Raises :class:`ScheduleUnavailable` for none or several."""
    _aware(at)
    rows = conn.execute(
        select(round_schedules, championship_series.c.code.label("series"))
        .join(championship_series, championship_series.c.id == round_schedules.c.series_id)
        .where(round_schedules.c.code == code, valid_at_clause(at))
        .order_by(round_schedules.c.version)
    ).all()
    if not rows:
        raise ScheduleUnavailable(
            f"No {code!r} schedule is valid at {at.isoformat()}; nothing was created."
        )
    if len(rows) > 1:
        versions = ", ".join(str(r.version) for r in rows)
        raise ScheduleUnavailable(
            f"Schedule {code!r} has overlapping versions valid at {at.isoformat()} "
            f"(versions {versions}); nothing was created."
        )
    return rows[0]


def current_schedule(conn: Connection, code: str) -> Any:
    """The row of ``code`` valid at this transaction's database timestamp: the row a
    round created in this transaction is bound to."""
    return schedule_at(conn, code, db_now(conn))


def schedule_versions(conn: Connection, code: str | None = None) -> list[Any]:
    """Every schedule row (optionally of one code), ordered by code and version."""
    q = select(round_schedules, championship_series.c.code.label("series")).join(
        championship_series, championship_series.c.id == round_schedules.c.series_id
    )
    if code is not None:
        q = q.where(round_schedules.c.code == code)
    return list(conn.execute(q.order_by(round_schedules.c.code, round_schedules.c.version)))


@dataclass(frozen=True)
class ConfigResolution:
    """Whether a stored configuration version resolves in this build."""

    version: str
    config: ChallengeConfig | None
    error: str | None

    @property
    def registered(self) -> bool:
        return self.config is not None


def resolve_config(version: str) -> ConfigResolution:
    try:
        return ConfigResolution(version, get_config(version), None)
    except ConfigError as exc:
        return ConfigResolution(version, None, str(exc))


# ------------------------------------------------------------------ inspection (read-only)
def _row_dict(r: Any, now: datetime) -> dict[str, Any]:
    res = resolve_config(r.config_version)
    valid_now = r.active_from <= now and (r.active_to is None or now < r.active_to)
    return {
        "schedule_id": r.id,
        "code": r.code,
        "version": r.version,
        "series": r.series,
        "active_from": r.active_from,
        "active_to": r.active_to,
        "valid_now": valid_now,
        "config_version": r.config_version,
        "config_registered": res.registered,
        "config_fingerprint": res.config.fingerprint() if res.config else None,
        "config_error": res.error,
        "rules_version": r.rules_version,
        "scoring_version": r.scoring_version,
        "deadline_buffer_minutes": r.deadline_buffer_minutes,
        "publish_rule": r.publish_rule,
    }


def _selection(conn: Connection, code: str, at: datetime) -> dict[str, Any]:
    try:
        r = schedule_at(conn, code, at)
        return {"at": at, "schedule_id": r.id, "version": r.version,
                "config_version": r.config_version, "problem": None}  # fmt: skip
    except ScheduleUnavailable as exc:
        return {"at": at, "schedule_id": None, "version": None, "config_version": None,
                "problem": str(exc)}  # fmt: skip


def schedule_report(
    conn: Connection, code: str | None = None, at: datetime | None = None
) -> dict[str, Any]:
    """Read-only inspection: every schedule version with its validity interval and
    whether its configuration resolves in this build, and the row selected now
    (database clock) and, optionally, at ``at``. Writes nothing."""
    if at is not None:
        _aware(at)
    now = db_now(conn)
    rows = schedule_versions(conn, code)
    codes = sorted({r.code for r in rows})
    out: dict[str, Any] = {"now": now, "at": at, "codes": {}}
    for c in codes:
        out["codes"][c] = {
            "versions": [_row_dict(r, now) for r in rows if r.code == c],
            "selected_now": _selection(conn, c, now),
            "selected_at": None if at is None else _selection(conn, c, at),
        }
    return out


def report_lines(rep: dict[str, Any]) -> list[str]:
    def ts(v):
        return "open-ended" if v is None else v.isoformat()

    lines = [f"database clock {rep['now'].isoformat()}"
             + (f"; requested instant {rep['at'].isoformat()}" if rep["at"] else "")]  # fmt: skip
    if not rep["codes"]:
        lines.append("no schedules")
    for code, c in rep["codes"].items():
        lines.append(f"schedule {code}:")
        for v in c["versions"]:
            reg = ("registered " + v["config_fingerprint"][:12]) if v["config_registered"] \
                else f"NOT REGISTERED ({v['config_error']})"  # fmt: skip
            lines.append(
                f"  v{v['version']} [{v['active_from'].isoformat()}, {ts(v['active_to'])})"
                f"{'  <- valid now' if v['valid_now'] else ''}"
            )
            lines.append(
                f"      config {v['config_version']} ({reg}); rules {v['rules_version']}; "
                f"scoring {v['scoring_version']}; series {v['series']}; deadline buffer "
                f"{v['deadline_buffer_minutes']} min"
            )
        for label, sel in (("now", c["selected_now"]), ("at the requested instant",
                                                         c["selected_at"])):  # fmt: skip
            if sel is None:
                continue
            if sel["problem"]:
                lines.append(f"  selected {label}: NONE - {sel['problem']}")
            else:
                lines.append(f"  selected {label}: v{sel['version']} ({sel['config_version']})")
    lines.append("read-only: nothing was changed")
    return lines
