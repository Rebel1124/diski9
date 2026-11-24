"""Scenario A3 Checkpoint 4A: the demonstration round, the prototype and the general
rules text follow the schedule valid now when a competition database is configured,
and the library default is used only when none is configured. Errors never fall back
to another configuration. (The PostgreSQL side of ``Backend.schedule_config`` is in
tests/backend/test_backend_schedule_resolution.py.)"""

from __future__ import annotations

from diski9.app.challenge import pages
from diski9.app.challenge.service import ChallengeService, ScheduleConfigUnavailable
from diski9.challenge.config import A3_432_V1, BROAD60_432_V1, DEFAULT_CONFIG
from diski9.challenge.roundsheet import RoundStatus

from .test_app import data, populated  # noqa: F401


class FakeBackend:
    def __init__(self, config):
        self.config = config
        self.calls = 0

    def schedule_config(self, code="weekend"):
        self.calls += 1
        if isinstance(self.config, Exception):
            raise self.config
        return self.config


def test_without_a_competition_database_the_default_applies(data):  # noqa: F811
    svc = ChallengeService(data)
    assert svc.rules_config() is DEFAULT_CONFIG
    assert pages.rules_config(None, svc) is DEFAULT_CONFIG
    assert pages.rules_config(None) is DEFAULT_CONFIG
    assert svc.demo().config is DEFAULT_CONFIG


def test_demo_and_rules_follow_the_schedule_and_rebuild_on_change(data):  # noqa: F811
    be = FakeBackend(A3_432_V1)
    svc = ChallengeService(data, backend=be)
    assert pages.rules_config(None, svc) is A3_432_V1
    d1 = svc.demo()
    assert d1.config is A3_432_V1 and d1.is_demo
    assert svc.demo() is d1  # unchanged configuration: the same frozen snapshot
    be.config = BROAD60_432_V1
    d2 = svc.demo()
    assert d2.config is BROAD60_432_V1 and d2 is not d1


def test_a_real_round_always_uses_its_own_configuration(data):  # noqa: F811
    svc = ChallengeService(data, backend=FakeBackend(A3_432_V1))
    v1_round = ChallengeService(data).demo()  # a snapshot bound to broad60
    assert v1_round.config is BROAD60_432_V1
    assert pages.rules_config(v1_round, svc) is BROAD60_432_V1


def test_errors_never_fall_back_to_another_configuration(data):  # noqa: F811
    svc = ChallengeService(data, backend=FakeBackend(ScheduleConfigUnavailable("down")))
    assert svc.demo() is None and svc.demo_error == "down"
    avail = svc.availability("demo")
    assert avail.status is RoundStatus.NO_ROUND
    assert avail.title == "Demonstration round temporarily unavailable"
    try:
        pages.rules_config(None, svc)
        raise AssertionError("expected ScheduleConfigUnavailable")
    except ScheduleConfigUnavailable:
        pass
    notice = pages._rules_or_notice(svc, None)
    assert "temporarily unavailable" in str(notice) and "Foundation" not in str(notice)
    # recovery: the next request builds the demonstration round again
    svc.backend.config = A3_432_V1
    assert svc.demo().config is A3_432_V1 and svc.demo_error is None
