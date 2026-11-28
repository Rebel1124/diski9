"""Rolling-entry methodology (Phase 8 CP3A-R, R1): rules version ``rolling/v1``.

A round follows rolling entry only when its ``rules_version`` (copied at publication
from the schedule row it is bound to) is :data:`ROLLING_RULES_VERSION`. Every other
round (``settle/v1``: schedule versions 1-3 and all historical rounds) keeps its
original methodology unchanged: the common deadline (earliest kickoff minus the
buffer), replacement and withdrawal, and round-level settlement rule V3.

Rolling-entry rounds (approved CP3A-R.1, §9 and §14 of
``docs/architecture/phase8_cp3ar1_refinement.md``):

* window Friday 00:00 to Monday 00:00 SAST (the schedule's ``window_rule``);
* scheduled publication Friday 08:00 SAST, still a manual action (``publish_rule``);
* one fixed entry close, Sunday 14:00 SAST (``publish_rule["entry_close"]``), stored
  as ``rounds.deadline_at`` at publication and enforced by the existing deadline
  checks (service and database);
* each selected fixture must kick off more than ``deadline_buffer_minutes`` (15)
  after the confirmation time (service level in R1; a database trigger follows in
  R2 with the edition migration);
* one irrevocable final submission per participant: no replacement, withdrawal or
  resubmission. Drafts stay editable until submission;
* settlement rule V3 uses **each entry's own submission time** as its reference
  instead of the round deadline;
* until official results are published (a ``score_sets`` row), the weekly board
  shows a participant only their own provisional row.

Nothing here writes. No hosted schedule row uses ``rolling/v1`` until a separately
authorised activation (an immediate data migration, the ``app_0009`` pattern), so
this code is dormant there. Tests create such rows only in disposable databases.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ROLLING_RULES_VERSION = "rolling/v1"
SAST = "Africa/Johannesburg"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# The approved schedule v4 rules (reference values for tests and for the future,
# separately authorised activation migration; not written anywhere by the app).
ROLLING_WINDOW_RULE: dict[str, Any] = {
    "start": {"weekday": "friday", "time": "00:00", "tz": SAST},
    "end": {"weekday": "monday", "time": "00:00", "tz": SAST, "exclusive": True},
}
ROLLING_PUBLISH_RULE: dict[str, Any] = {
    "weekday": "friday",
    "time": "08:00",
    "tz": SAST,
    "entry_close": {"weekday": "sunday", "time": "14:00", "tz": SAST},
}
ROLLING_FIXTURE_CUTOFF_MINUTES = 15  # the schedule's deadline_buffer_minutes


class RollingRuleError(ValueError):
    """A rolling-entry schedule rule that cannot be interpreted (fail safe)."""


def is_rolling(rules_version: str | None) -> bool:
    """True only for the rolling-entry rules version; everything else (including
    ``None`` for an unpublished draft) follows the historical methodology."""
    return rules_version == ROLLING_RULES_VERSION


def entry_close(publish_rule: dict[str, Any], window_start: datetime) -> datetime:
    """The fixed entry close of a rolling-entry round: the first ``entry_close``
    weekday and time (in its own time zone) at or after the window start. For schedule
    v4 the window starts Friday 00:00 SAST, so this is Sunday 14:00 SAST of the same
    weekend. ``time`` is ``HH:MM`` (``HH:MM:SS`` is accepted)."""
    spec = (publish_rule or {}).get("entry_close")
    if not isinstance(spec, dict):
        raise RollingRuleError("The rolling-entry schedule has no entry_close rule.")
    try:
        tz = ZoneInfo(spec.get("tz", "UTC"))
        parts = [int(x) for x in spec["time"].split(":")]
        if len(parts) not in (2, 3):
            raise ValueError(spec["time"])
        at = time(*parts)
        weekday = WEEKDAYS.index(spec["weekday"])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise RollingRuleError(f"Invalid entry_close rule: {spec!r}") from exc
    if window_start.tzinfo is None:
        raise RollingRuleError("The window start must be timezone-aware.")
    local = window_start.astimezone(tz)
    day = local.date() + timedelta(days=(weekday - local.weekday()) % 7)
    close = datetime.combine(day, at, tz)
    if close < window_start:
        close = datetime.combine(day + timedelta(days=7), at, tz)
    return close


def fixture_cutoff(kickoff: datetime, buffer_minutes: int) -> datetime:
    """The last instant (exclusive) a fixture may be selected: kickoff minus the
    buffer. A confirmation at or after it is refused."""
    return kickoff - timedelta(minutes=buffer_minutes)


def closed_fixtures(
    kickoffs: dict[int, datetime], fixture_ids, now: datetime, buffer_minutes: int
) -> list[int]:
    """The selected fixtures whose cutoff has passed at ``now`` (kickoff must be
    strictly later than ``now + buffer``). A fixture missing from ``kickoffs`` is
    treated as closed (fail safe)."""
    out = []
    for fid in fixture_ids:
        k = kickoffs.get(int(fid))
        if k is None or now >= fixture_cutoff(k, buffer_minutes):
            out.append(int(fid))
    return out


__all__ = [
    "ROLLING_FIXTURE_CUTOFF_MINUTES",
    "ROLLING_PUBLISH_RULE",
    "ROLLING_RULES_VERSION",
    "ROLLING_WINDOW_RULE",
    "RollingRuleError",
    "closed_fixtures",
    "entry_close",
    "fixture_cutoff",
    "is_rolling",
]
