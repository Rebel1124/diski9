"""Stage E.1a: the upcoming competition week, from the weekend schedule (no database).

The rules are the seeded ``weekend`` schedule version 2 (window Friday 00:00 UTC to
Tuesday 00:00 UTC exclusive; publication target Friday 08:00 Africa/Johannesburg).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diski9.backend.jobs.prepare import category, decode, encode, publication_target, week_at

WINDOW = {
    "start": {"weekday": "friday", "time": "00:00", "tz": "UTC"},
    "end": {"weekday": "tuesday", "time": "00:00", "tz": "UTC", "exclusive": True},
}
PUBLISH = {"weekday": "friday", "time": "08:00", "tz": "Africa/Johannesburg"}
LEAD = timedelta(hours=78)


def utc(*a) -> datetime:
    return datetime(*a, tzinfo=UTC)


def test_week_runs_from_one_tuesday_to_the_next():
    w = week_at(utc(2026, 11, 24, 0, 0), WINDOW, PUBLISH, LEAD)  # a Tuesday
    assert (w.iso_year, w.iso_week, w.code) == (2026, 48, "2026-W48-weekend")
    assert w.period_start == utc(2026, 11, 24)
    assert w.window_start == utc(2026, 11, 27) and w.window_end == utc(2026, 12, 1)
    assert w.target == utc(2026, 11, 27, 6, 0)  # Friday 08:00 SAST
    assert w.create_at == utc(2026, 11, 24)  # 78 h before the target
    before = week_at(utc(2026, 11, 23, 23, 59), WINDOW, PUBLISH, LEAD)  # Monday night
    assert before.code == "2026-W47-weekend" and before.window_end == utc(2026, 11, 24)
    sunday = week_at(utc(2026, 11, 29, 12), WINDOW, PUBLISH, LEAD)  # inside the window
    assert sunday.code == "2026-W48-weekend"


def test_every_instant_belongs_to_exactly_one_week():
    t = utc(2026, 11, 1)
    while t < utc(2026, 12, 20):
        w = week_at(t, WINDOW, PUBLISH, LEAD)
        assert w.period_start <= t < w.window_end, t
        assert w.window_start - w.period_start == timedelta(days=3)
        t += timedelta(hours=1)


def test_iso_year_boundaries():
    w53 = week_at(utc(2026, 12, 29, 12), WINDOW, PUBLISH, LEAD)
    assert w53.code == "2026-W53-weekend"
    assert w53.window_start == utc(2027, 1, 1) and w53.window_end == utc(2027, 1, 5)
    w01 = week_at(utc(2027, 1, 5, 0, 0), WINDOW, PUBLISH, LEAD)
    assert w01.code == "2027-W01-weekend" and w01.window_start == utc(2027, 1, 8)
    w52 = week_at(utc(2027, 12, 28, 1), WINDOW, PUBLISH, LEAD)
    assert w52.code == "2027-W52-weekend"


def test_european_dst_does_not_move_the_utc_window_or_the_sast_target():
    # Europe leaves summer time on 25 Oct 2026; South Africa has no daylight saving
    for t in (utc(2026, 10, 20, 3), utc(2026, 10, 27, 3)):
        w = week_at(t, WINDOW, PUBLISH, LEAD)
        assert (w.window_start.hour, w.window_end.hour, w.target.astimezone(UTC).hour) == (
            0,
            0,
            6,
        )
        assert w.window_start.weekday() == 4 and w.window_end.weekday() == 1


def test_create_lead_is_bounded_by_the_period_start():
    w = week_at(utc(2026, 11, 24, 1), WINDOW, PUBLISH, timedelta(hours=6))
    assert w.create_at == utc(2026, 11, 27, 0, 0)
    assert week_at(utc(2026, 11, 24, 1), WINDOW, PUBLISH, timedelta(hours=200)).create_at == utc(
        2026, 11, 24
    )
    assert publication_target(PUBLISH, 2026, 48) == utc(2026, 11, 27, 6)


class _Rd:
    def __init__(self, ready=False, problem=None, details=None):
        self.ready, self.problem, self.details = ready, problem, details or {}
        self.report = {"eligible_outcomes_by_bucket": {"A": 9, "B": 5, "C": 3},
                       "eligible_fixtures": 16, "eligible_leagues": 4}  # fmt: skip
        self.required_by_bucket = {"A": 4, "B": 3, "C": 2}
        self.fixtures = 20
        self.earliest_kickoff = utc(2026, 11, 27, 19)
        self.deadline_at = utc(2026, 11, 27, 18, 45)
        self.diagnostics = {}  # as PublicationReadiness (pool diagnostics; Phase 8 CP2A)


@pytest.mark.parametrize(
    ("problem", "details", "expected"),
    [
        ("Not enough eligible fixtures: ...", {"status": "insufficient"}, "opening_checks"),
        ("A full portfolio is not possible: ...", {"status": "infeasible"}, "opening_checks"),
        ("Reference odds are out of date: ...", {"status": "stale_odds"}, "stale_odds"),
        ("Not enough market data: ...", {"status": "missing_markets"}, "missing_markets"),
        ("No supported fixtures in the round window.", {}, "no_fixtures"),
        ("The submission deadline for these fixtures has already passed.",
         {"deadline": "2026-11-27T18:45:00+00:00"}, "deadline_passed"),
        ("The round is already open; a published snapshot never changes.", {}, "not_draft"),
        ("The snapshot is too old to publish; build a fresh one.", {}, "snapshot"),
        ("Something else.", {}, "other"),
    ],
)  # fmt: skip
def test_readiness_categories_come_from_the_validators_own_result(problem, details, expected):
    rd = _Rd(problem=problem, details=details)
    assert category(rd) == expected
    v = decode(encode(rd, 1.25), utc(2026, 11, 27))
    assert not v.ready and v.category == expected and v.problem.startswith(problem[:20])
    assert v.summary["buckets"] == "A9/4,B5/3,C3/2" and v.summary["secs"] == "1.2"


def test_ready_record_round_trips_and_fits_the_column():
    v = decode(encode(_Rd(ready=True), 0.5), utc(2026, 11, 27))
    assert v.ready and v.category is None and v.summary["fixtures"] == "20"
    long = _Rd(problem="x" * 2000, details={"status": "insufficient"})
    assert len(encode(long, 1.0)) <= 500
    assert decode(None, utc(2026, 11, 27)) is None
    assert decode("retryable_failure: provider error", utc(2026, 11, 27)) is None
