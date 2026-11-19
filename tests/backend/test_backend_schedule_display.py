"""Phase 6C.3 Stage G: publication schedules and SAST display (D-11 revised, T-19).

* Friday 08:00 SAST is the default publication target; an alternative schedule
  (another code with its own window and publication rule) is still supported.
* The deadline is always the earliest included kickoff minus the schedule's
  15-minute buffer, whatever day publication happens.
* Pages show the stored snapshot and deadline times converted to SAST; no page
  hard-codes a weekday that could misrepresent a stored time.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from pg_helpers import unique
from sqlalchemy import insert, select
from svc_helpers import principal

from diski9.app.challenge import pages
from diski9.app.data import ScreenerData
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import round_schedules, rounds
from diski9.backend.devdata import dev_snapshot
from diski9.backend.services import rounds as svc

SAST = ZoneInfo("Africa/Johannesburg")
APP = Path(__file__).resolve().parents[2] / "src/diski9/app"


def _local():
    """The app's own SAST formatter (ScreenerData.local) without a football store."""
    holder = SimpleNamespace(tz=SAST)
    return lambda dt, fmt="%a %d %b, %H:%M": ScreenerData.local(holder, dt, fmt)


def test_sast_conversion_of_stored_utc_times():
    local = _local()
    assert local(datetime(2026, 11, 20, 6, 0, tzinfo=UTC)) == "Fri 20 Nov, 08:00"
    assert local("2026-11-21T22:30:00+00:00") == "Sun 22 Nov, 00:30"  # crosses midnight
    assert local(datetime(2026, 6, 19, 6, 0, tzinfo=UTC)) == "Fri 19 Jun, 08:00"  # no DST


def test_round_times_show_the_stored_frozen_time_and_deadline_in_sast():
    rv = SimpleNamespace(
        snapshot_at=datetime(2026, 11, 20, 5, 47, tzinfo=UTC),  # not "Friday 08:00"
        deadline_at=datetime(2026, 11, 20, 17, 15, tzinfo=UTC),
    )
    assert pages.round_times(rv, _local()) == [
        ("Frozen", "Fri 20 Nov, 07:47 SAST"),
        ("Deadline", "Fri 20 Nov, 19:15 SAST"),
    ]
    rv = SimpleNamespace(snapshot_at=datetime(2026, 11, 24, 9, 3, tzinfo=UTC), deadline_at=None)
    assert pages.round_times(rv, _local()) == [("Frozen", "Tue 24 Nov, 11:03 SAST")]


def test_no_page_hard_codes_a_publication_weekday():
    pattern = re.compile(r"\b(Thursday|Friday)\b")
    offenders = [
        f"{p.relative_to(APP)}:{i}"
        for p in APP.rglob("*.py")
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


def test_alternative_schedule_is_supported_with_the_same_deadline_rule(engine):
    op = principal(engine, role="operator")
    with transaction(engine) as conn:
        base = conn.execute(
            select(round_schedules)
            .where(round_schedules.c.code == "weekend")
            .order_by(round_schedules.c.version.desc())
            .limit(1)
        ).one()
        code = unique("midweek")
        row = {k: v for k, v in base._mapping.items() if k not in ("id", "active_to")}
        row.update(
            code=code,
            version=1,
            window_rule={
                "start": {"weekday": "tuesday", "time": "00:00", "tz": "Africa/Johannesburg"},
                "end": {"weekday": "friday", "time": "00:00", "tz": "Africa/Johannesburg"},
            },
            publish_rule={"weekday": "monday", "time": "12:00", "tz": "Africa/Johannesburg"},
        )
        conn.execute(insert(round_schedules).values(**row))
        now = db_now(conn)
    start, end = svc.schedule_window(engine, 2026, 49, code=code)
    assert start == datetime(2026, 11, 30, 22, 0, tzinfo=UTC)  # Tue 1 Dec 00:00 SAST
    assert end == datetime(2026, 12, 3, 22, 0, tzinfo=UTC)  # Fri 4 Dec 00:00 SAST
    # A round on the alternative schedule: same 15-minute deadline rule.
    rcode = unique("dev-mw")
    snap = dev_snapshot(rcode, now, now + timedelta(hours=5), seed=5)
    v = svc.create_round(engine, op, code=rcode, window_start=snap.window[0],
                         window_end=snap.window[1], schedule_code=code,
                         development=True)  # fmt: skip
    view = svc.publish_round(engine, op, v.id, snap, source="development")
    assert view.deadline_at == snap.earliest_kickoff - timedelta(minutes=15)
    with transaction(engine) as conn:
        sid = conn.execute(select(rounds.c.schedule_id).where(rounds.c.id == v.id)).scalar_one()
        assert (
            conn.execute(
                select(round_schedules.c.code).where(round_schedules.c.id == sid)
            ).scalar_one()
            == code
        )
    # The default is still Friday 08:00 SAST.
    with transaction(engine) as conn:
        default = conn.execute(
            select(round_schedules.c.publish_rule)
            .where(round_schedules.c.code == "weekend")
            .order_by(round_schedules.c.version.desc())
            .limit(1)
        ).scalar_one()
    assert default == {"weekday": "friday", "time": "08:00", "tz": "Africa/Johannesburg"}


def test_friday_evening_fixtures_shorten_the_participation_window():
    """Documented consequence of D-11 revised (no rule changed): publication at
    Friday 08:00 SAST and a Friday 21:00 SAST kickoff leave 12 h 45 min."""
    publish = datetime(2026, 11, 27, 8, 0, tzinfo=SAST)
    kickoff = datetime(2026, 11, 27, 21, 0, tzinfo=SAST)
    deadline = kickoff - timedelta(minutes=15)
    assert deadline - publish == timedelta(hours=12, minutes=45)
