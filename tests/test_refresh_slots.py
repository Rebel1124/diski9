"""Phase 6C.6 E.1b: the Balanced refresh schedule and its configuration (no database).

Week rules are the seeded ``weekend`` schedule v2 (window Friday 00:00 UTC to Tuesday
00:00 UTC; publication target Friday 08:00 Africa/Johannesburg = 06:00 UTC)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from diski9.backend.jobs.config import ConfigError, SchedulerConfig, load_config
from diski9.backend.jobs.prepare import week_at
from diski9.backend.jobs.refresh import current_and_previous, next_slot, slots

WINDOW = {
    "start": {"weekday": "friday", "time": "00:00", "tz": "UTC"},
    "end": {"weekday": "tuesday", "time": "00:00", "tz": "UTC", "exclusive": True},
}
PUBLISH = {"weekday": "friday", "time": "08:00", "tz": "Africa/Johannesburg"}
CFG = SchedulerConfig()  # defaults: 04:15 daily, Friday 04:15/05:15, hourly grace, 6 h


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def week(t):
    return week_at(t, WINDOW, PUBLISH, timedelta(hours=78))


W = week(utc(2026, 11, 24, 1))  # 2026-W48: Tue 24 Nov – Fri 27 Nov target 06:00 UTC


def test_balanced_schedule_slots():
    got = [(s.kind, s.at) for s in slots(W, CFG)]
    assert got == [
        ("daily", utc(2026, 11, 24, 4, 15)),
        ("daily", utc(2026, 11, 25, 4, 15)),
        ("daily", utc(2026, 11, 26, 4, 15)),
        ("publication", utc(2026, 11, 27, 4, 15)),
        ("publication", utc(2026, 11, 27, 5, 15)),
        *[("grace", utc(2026, 11, 27, h, 15)) for h in range(6, 12)],
    ]


@pytest.mark.parametrize(
    ("now", "cur", "prev"),
    [
        (utc(2026, 11, 24, 3, 0), None, None),
        (utc(2026, 11, 24, 4, 15), utc(2026, 11, 24, 4, 15), None),
        (utc(2026, 11, 26, 23, 0), utc(2026, 11, 26, 4, 15), utc(2026, 11, 25, 4, 15)),
        (utc(2026, 11, 27, 4, 20), utc(2026, 11, 27, 4, 15), utc(2026, 11, 26, 4, 15)),
        (utc(2026, 11, 27, 5, 59), utc(2026, 11, 27, 5, 15), utc(2026, 11, 27, 4, 15)),
        (utc(2026, 11, 27, 7, 40), utc(2026, 11, 27, 7, 15), utc(2026, 11, 27, 6, 15)),
        (utc(2026, 11, 27, 11, 59), utc(2026, 11, 27, 11, 15), utc(2026, 11, 27, 10, 15)),
        (utc(2026, 11, 27, 12, 0), None, utc(2026, 11, 27, 11, 15)),  # grace ended
    ],
)
def test_current_slot_is_the_latest_due_and_never_a_backlog(now, cur, prev):
    c, p = current_and_previous(W, CFG, now)
    assert (c.at if c else None, p.at if p else None) == (cur, prev)


def test_missed_ticks_resume_with_the_current_slot_only():
    # host down from Friday 04:00 to 07:40: the 04:15, 05:15 and 06:15 slots are not
    # replayed; the first tick works the 07:15 grace slot
    c, p = current_and_previous(W, CFG, utc(2026, 11, 27, 7, 40))
    assert c.label == "grace 2026-11-27T07:15Z" and p.at == utc(2026, 11, 27, 6, 15)
    assert next_slot(W, CFG, utc(2026, 11, 27, 7, 40)).at == utc(2026, 11, 27, 8, 15)
    assert next_slot(W, CFG, utc(2026, 11, 27, 12, 0)) is None


def test_european_dst_and_iso_year_boundary_keep_the_utc_slots():
    for t in (utc(2026, 10, 20, 3), utc(2026, 10, 27, 3)):  # around 25 Oct 2026
        w = week(t)
        assert {s.at.hour for s in slots(w, CFG) if s.kind != "grace"} == {4, 5}
    w53 = week(utc(2026, 12, 29, 12))  # 2026-W53: Friday 1 Jan 2027
    pub = [s.at for s in slots(w53, CFG) if s.kind == "publication"]
    assert pub == [utc(2027, 1, 1, 4, 15), utc(2027, 1, 1, 5, 15)]


def test_publication_times_at_or_after_the_target_are_ignored():
    cfg = replace(CFG, refresh_publication=(CFG.refresh_publication[0],
                                            datetime(2000, 1, 1, 6, 30).time()))  # fmt: skip
    assert [s.at for s in slots(W, cfg) if s.kind == "publication"] == [utc(2026, 11, 27, 4, 15)]


# ------------------------------------------------------------------ configuration
ON = {
    "DISKI9_JOBS_ENABLED": "on", "DISKI9_JOBS_STREAMS": "beta", "DISKI9_JOBS_PREPARE": "on",
    "DISKI9_JOBS_PREPARE_STREAMS": "beta", "DISKI9_JOBS_PROVIDER_CALLS": "on",
    "DISKI9_JOBS_PREPARE_REFRESH": "on",
}  # fmt: skip


def test_defaults_refresh_off_and_existing_caps_unchanged():
    cfg = load_config({}, environment="test")
    assert not cfg.prepare_refresh
    assert (cfg.max_requests_per_tick, cfg.max_requests_per_day) == (10, 100)  # D-1
    assert (cfg.nonessential_per_day, cfg.results_reserve) == (300, 150)
    assert (cfg.provider_min_interval, cfg.provider_max_wait) == (3.0, 30.0)
    assert cfg.prepare_provider_floor == 2000


def test_refresh_cannot_be_switched_on_with_the_pre_e1b_caps():
    with pytest.raises(ConfigError, match="at least 450"):
        load_config(ON, environment="test")
    cfg = load_config(ON | {"DISKI9_JOBS_MAX_REQUESTS_PER_TICK": "20",
                            "DISKI9_JOBS_MAX_REQUESTS_PER_DAY": "450"}, environment="test")  # fmt: skip
    assert cfg.prepare_refresh and cfg.worst_tick_seconds() < cfg.abandon_after.total_seconds()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"DISKI9_JOBS_PROVIDER_CALLS": "off"}, "PROVIDER_CALLS"),
        ({"DISKI9_JOBS_PREPARE": "off", "DISKI9_JOBS_PREPARE_STREAMS": ""}, "needs DISKI9_JOBS_PREPARE"),
        ({"DISKI9_JOBS_MAX_REQUESTS_PER_TICK": "100", "DISKI9_JOBS_MAX_REQUESTS_PER_DAY": "450"},
         "longest possible tick"),
        ({"DISKI9_JOBS_PREPARE_PROVIDER_FLOOR": "600", "DISKI9_API_FOOTBALL_DAILY_RESERVE": "800"},
         "exceed the client daily reserve"),
        ({"DISKI9_JOBS_PREPARE_REFRESH_DAILY": "4am"}, "HH:MM"),
        ({"DISKI9_JOBS_PROVIDER_MIN_INTERVAL_SECONDS": "0"}, "between 1 and 30"),
        ({"DISKI9_JOBS_PROVIDER_MAX_WAIT_SECONDS": "120"}, "between 5 and 60"),
    ],
)  # fmt: skip
def test_invalid_refresh_settings_fail_closed(extra, message):
    env = ON | {"DISKI9_JOBS_MAX_REQUESTS_PER_TICK": "20",
                "DISKI9_JOBS_MAX_REQUESTS_PER_DAY": "450"} | extra  # fmt: skip
    with pytest.raises(ConfigError, match=message):
        load_config(env, environment="test")


def test_official_can_never_be_refreshed():
    with pytest.raises(ConfigError):
        load_config(ON | {"DISKI9_JOBS_PREPARE_STREAMS": "official"}, environment="test")
    with pytest.raises(ConfigError):
        SchedulerConfig(enabled=True, streams=("beta",), prepare=True,
                        prepare_streams=("official",))  # fmt: skip
