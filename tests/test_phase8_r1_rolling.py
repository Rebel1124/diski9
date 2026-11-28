"""Phase 8 CP3A-R R1: rolling-entry rules (pure; no database).

SAST boundaries with UTC storage, Friday-Sunday fixture membership, the Sunday
14:00 entry close, the per-fixture 15-minute cutoff and version selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from diski9.backend.jobs.prepare import publication_target
from diski9.backend.services import rolling
from diski9.backend.services.rounds import weekly_window

SAST = ZoneInfo("Africa/Johannesburg")


def test_only_the_rolling_rules_version_selects_rolling_entry():
    assert rolling.is_rolling("rolling/v1")
    for other in ("settle/v1", None, "", "rolling/v2", "ROLLING/V1"):
        assert not rolling.is_rolling(other)


def test_schedule_v4_window_is_friday_to_monday_sast_stored_in_utc():
    start, end = weekly_window(rolling.ROLLING_WINDOW_RULE, 2026, 49)
    assert start == datetime(2026, 12, 3, 22, 0, tzinfo=UTC)  # Fri 4 Dec 00:00 SAST
    assert end == datetime(2026, 12, 6, 22, 0, tzinfo=UTC)  # Mon 7 Dec 00:00 SAST
    assert start.astimezone(SAST).strftime("%a %H:%M") == "Fri 00:00"
    assert end.astimezone(SAST).strftime("%a %H:%M") == "Mon 00:00"


def test_friday_to_sunday_membership_excludes_monday_fixtures():
    start, end = weekly_window(rolling.ROLLING_WINDOW_RULE, 2026, 49)

    def inside(local: datetime) -> bool:  # the half-open window test the builder applies
        return start <= local.astimezone(UTC) < end

    assert inside(datetime(2026, 12, 4, 0, 0, tzinfo=SAST))  # Friday 00:00 included
    assert inside(datetime(2026, 12, 6, 23, 59, tzinfo=SAST))  # Sunday 23:59 included
    assert not inside(datetime(2026, 12, 7, 0, 0, tzinfo=SAST))  # Monday 00:00 excluded
    assert not inside(datetime(2026, 12, 7, 20, 0, tzinfo=SAST))  # Monday evening excluded
    assert not inside(datetime(2026, 12, 3, 23, 59, tzinfo=SAST))  # Thursday excluded
    # Thursday 22:00-23:59 UTC is Friday in SAST, hence included
    assert inside(datetime(2026, 12, 3, 22, 30, tzinfo=UTC))


def test_scheduled_publication_is_friday_0800_sast():
    target = publication_target(rolling.ROLLING_PUBLISH_RULE, 2026, 49)
    assert target == datetime(2026, 12, 4, 6, 0, tzinfo=UTC)


def test_entry_close_is_sunday_1400_sast_of_the_same_weekend():
    start, end = weekly_window(rolling.ROLLING_WINDOW_RULE, 2026, 49)
    close = rolling.entry_close(rolling.ROLLING_PUBLISH_RULE, start)
    assert close == datetime(2026, 12, 6, 12, 0, tzinfo=UTC)  # Sun 6 Dec 14:00 SAST
    assert close.astimezone(SAST).strftime("%a %H:%M") == "Sun 14:00"
    assert start < close < end
    # every week of a year (no daylight saving in SAST): always Sunday 14:00 SAST
    for week in range(1, 53):
        s, e = weekly_window(rolling.ROLLING_WINDOW_RULE, 2027, week)
        c = rolling.entry_close(rolling.ROLLING_PUBLISH_RULE, s)
        assert c.astimezone(SAST).strftime("%a %H:%M") == "Sun 14:00"
        assert c - s == timedelta(days=2, hours=14) and c < e


def test_entry_close_refuses_a_missing_or_malformed_rule():
    start = datetime(2026, 12, 3, 22, 0, tzinfo=UTC)
    for rule in ({}, {"weekday": "friday"}, {"entry_close": "sunday"},
                 {"entry_close": {"weekday": "sunday"}},
                 {"entry_close": {"weekday": "someday", "time": "14:00"}},
                 {"entry_close": {"weekday": "sunday", "time": "14"}}):  # fmt: skip
        with pytest.raises(rolling.RollingRuleError):
            rolling.entry_close(rule, start)
    with pytest.raises(rolling.RollingRuleError):
        rolling.entry_close(rolling.ROLLING_PUBLISH_RULE, start.replace(tzinfo=None))


def test_fixture_cutoff_is_strictly_more_than_fifteen_minutes_before_kickoff():
    ko = datetime(2026, 12, 5, 15, 0, tzinfo=UTC)
    buf = rolling.ROLLING_FIXTURE_CUTOFF_MINUTES
    assert rolling.fixture_cutoff(ko, buf) == ko - timedelta(minutes=15)
    kick = {1: ko}
    assert rolling.closed_fixtures(kick, [1], ko - timedelta(minutes=15, seconds=1), buf) == []
    assert rolling.closed_fixtures(kick, [1], ko - timedelta(minutes=15), buf) == [1]
    assert rolling.closed_fixtures(kick, [1], ko + timedelta(minutes=1), buf) == [1]
    assert rolling.closed_fixtures(kick, [2], ko - timedelta(days=1), buf) == [2]  # unknown


def test_friday_fixture_stays_selectable_on_friday_and_closes_before_kickoff():
    """A Friday 20:00 SAST fixture is open to a Friday-morning entrant and closed to a
    Saturday entrant, although both are before the Sunday close."""
    fri = datetime(2026, 12, 4, 20, 0, tzinfo=SAST)
    sat = datetime(2026, 12, 5, 15, 0, tzinfo=SAST)
    kick = {10: fri.astimezone(UTC), 11: sat.astimezone(UTC)}
    friday_morning = datetime(2026, 12, 4, 9, 0, tzinfo=SAST)
    saturday_noon = datetime(2026, 12, 5, 12, 0, tzinfo=SAST)
    assert rolling.closed_fixtures(kick, [10, 11], friday_morning, 15) == []
    assert rolling.closed_fixtures(kick, [10, 11], saturday_noon, 15) == [10]


# ------------------------------------------------------------------ R1 review refinements
def test_settlement_cutoff_is_the_later_of_latest_kickoff_and_close_plus_24_hours():
    close = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)  # Sunday 14:00 SAST
    h = rolling.ROLLING_SETTLE_CUTOFF_HOURS
    assert h == 24
    before = datetime(2026, 12, 6, 11, 0, tzinfo=UTC)  # last match Sunday 13:00 SAST
    after = datetime(2026, 12, 6, 15, 30, tzinfo=UTC)  # last match Sunday 17:30 SAST
    assert rolling.settle_cutoff(before, close, h) == close + timedelta(hours=24)
    assert rolling.settle_cutoff(after, close, h) == after + timedelta(hours=24)
    # Monday 17:30 SAST, so the earliest finalisation (cutoff + the unchanged 24 h
    # correction window, with no later material change) is Tuesday 17:30 SAST
    cutoff = rolling.settle_cutoff(after, close, h)
    assert cutoff.astimezone(SAST).strftime("%a %H:%M") == "Mon 17:30"
    assert (cutoff + timedelta(hours=24)).astimezone(SAST).strftime("%a %H:%M") == "Tue 17:30"


def test_an_unknown_or_malformed_time_zone_fails_safe():
    start = datetime(2026, 12, 3, 22, 0, tzinfo=UTC)
    for tz in ("Mars/Phobos", "Not a zone", "../etc/passwd", "", 42, None):
        rule = {"entry_close": {"weekday": "sunday", "time": "14:00", "tz": tz}}
        with pytest.raises(rolling.RollingRuleError):
            rolling.entry_close(rule, start)


def _obs(i, at, status, ko, **kw):
    from diski9.challenge.settle import Observation

    return Observation(i, kw.pop("source", "api-football"), at, status, ko, **kw)


def test_settlement_boundaries_at_the_24_hour_cutoff():
    """The existing cutoff rules applied at a rolling cutoff: completed by the cutoff
    settles; still unfinished or rescheduled past it is void; later evidence never
    changes that."""
    from diski9.challenge.settle import resolve_fixture

    close = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    ko = datetime(2026, 12, 6, 15, 30, tzinfo=UTC)
    cutoff = rolling.settle_cutoff(ko, close, rolling.ROLLING_SETTLE_CUTOFF_HOURS)
    ref = close - timedelta(days=1)  # a Saturday submission
    after = cutoff + timedelta(minutes=1)

    def res(observations, at=after):
        return resolve_fixture(1, observations, [("1X2", "HOME")], deadline_at=ref,
                               settle_cutoff_at=cutoff, evaluated_at=at)  # fmt: skip

    done = _obs(1, cutoff - timedelta(seconds=1), "FT", ko, ft_home=1, ft_away=0)
    assert res([done]).rule == "settle"
    suspended = _obs(2, ko + timedelta(hours=1), "SUSP", ko)
    assert res([suspended]).rule == "V4"
    moved = _obs(3, ko - timedelta(hours=2), "NS", cutoff + timedelta(hours=1))
    assert res([moved]).rule == "V1"
    late = _obs(4, cutoff + timedelta(seconds=30), "FT", ko, ft_home=1, ft_away=0)
    assert res([suspended, late]).verdicts[0].verdict == "void"  # late result: still void
    assert res([suspended], at=cutoff - timedelta(minutes=1)).rule == "pending"


def test_resolution_is_constant_within_a_v3_class():
    """The settlement refinement resolves a fixture once per V3 class: every reference
    in a class must give exactly the resolution of any other reference in it."""
    import random

    from diski9.challenge.settle import resolve_fixture, v3_breakpoints, v3_class

    rng = random.Random(8)
    base = datetime(2026, 12, 4, 6, 0, tzinfo=UTC)
    cutoff = base + timedelta(days=4)
    evaluated = cutoff + timedelta(hours=1)
    sel = [("1X2", "HOME"), ("BTTS", "BTTS_YES")]
    for trial in range(300):
        ko = base + timedelta(minutes=rng.randrange(0, 3 * 1440))
        obs, t = [], base
        for i in range(rng.randrange(1, 6)):
            t = t + timedelta(minutes=rng.randrange(1, 900))
            status = rng.choice(["NS", "1H", "HT", "FT", "PST", "SUSP"])
            sched = ko + timedelta(minutes=rng.choice([0, 0, -120, 90]))
            kw = {"ft_home": 1, "ft_away": 1} if status == "FT" else {}
            if rng.random() < 0.2:
                kw["provider_first_half_at"] = sched + timedelta(minutes=rng.randrange(-60, 60))
            obs.append(_obs(trial * 10 + i, t, status, sched, **kw))
        if rng.random() < 0.15:
            obs.append(_obs(trial * 10 + 9, t + timedelta(minutes=5), "FT", ko, source="operator",
                            ft_home=2, ft_away=0,
                            actual_kickoff_at=ko + timedelta(minutes=rng.randrange(-90, 30))))  # fmt: skip
        bp = v3_breakpoints(obs, evaluated)
        groups: dict[int, list] = {}
        for _ in range(12):
            ref = base + timedelta(seconds=rng.randrange(0, int(2.5 * 86400)))
            r = resolve_fixture(7, obs, sel, deadline_at=ref, settle_cutoff_at=cutoff,
                                evaluated_at=evaluated)  # fmt: skip
            sig = (r.rule, r.verdicts, r.score, r.deciding_observation_id, r.alerts, r.notes)
            groups.setdefault(v3_class(bp, ref), []).append(sig)
        for sigs in groups.values():
            assert all(s == sigs[0] for s in sigs), (trial, sigs)
