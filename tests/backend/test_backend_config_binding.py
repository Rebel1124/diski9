"""Scenario A3 Checkpoint 1: rounds stay bound to their own configuration version on
real PostgreSQL. A draft keeps the configuration of the schedule row it was created
under even after a newer schedule version exists, publishes normally with a snapshot
built for that configuration, and an unknown version fails instead of falling back.

The tests use their own schedule codes (never ``weekend``) and the registered but
inactive ``a3-432-v1`` configuration (A3 Checkpoint 2); no production schedule or
configuration is changed."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pg_helpers import unique
from sqlalchemy import text
from svc_helpers import principal

from diski9.backend.db import db_now, transaction
from diski9.backend.devdata import dev_snapshot
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import PublicationRefused
from diski9.challenge.config import A3_432_V1, BROAD60_432_V1, ConfigError


@pytest.fixture
def variant():
    """The registered (but inactive) a3-432-v1 configuration, used only on test-only
    schedule codes; the active weekend schedule is never changed."""
    return A3_432_V1


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _add_schedule(engine, code: str, version: int, config_version: str) -> None:
    """A copy of the current weekend schedule under a test-only code."""
    with transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO app.round_schedules (code, version, timezone, eligible_competitions,"
                " window_rule, publish_rule, deadline_buffer_minutes, settle_cutoff_hours,"
                " correction_window_hours, config_version, rules_version, scoring_version,"
                " series_id, active_from)"
                " SELECT :code, :version, timezone, eligible_competitions, window_rule,"
                " publish_rule, deadline_buffer_minutes, settle_cutoff_hours,"
                " correction_window_hours, :cfg, rules_version, scoring_version, series_id, now()"
                " FROM app.round_schedules WHERE code = 'weekend'"
                " ORDER BY version DESC LIMIT 1"
            ),
            {"code": code, "version": version, "cfg": config_version},
        )


def _draft(engine, op, schedule_code: str):
    with transaction(engine) as conn:
        now = db_now(conn)
    code = unique("dev-bind")
    window = (now, now + timedelta(days=3))
    v = svc.create_round(
        engine,
        op,
        code=code,
        window_start=window[0],
        window_end=window[1],
        schedule_code=schedule_code,
        development=True,
    )
    return v, now


def test_draft_keeps_its_schedule_configuration_after_a_newer_schedule(engine, op, variant):
    sched = unique("bind").replace("-", "")
    _add_schedule(engine, sched, 1, BROAD60_432_V1.version)
    draft, now = _draft(engine, op, sched)
    _add_schedule(engine, sched, 2, variant.version)  # a newer version exists now
    with transaction(engine) as conn:
        assert svc.round_config(conn, draft.id) is BROAD60_432_V1  # the draft's own row
        assert svc.schedule_config(conn, sched) is variant  # what a NEW round would get
        config = svc.round_config(conn, draft.id)
    # the draft publishes normally (no recreation) with a snapshot built for its config
    snap = dev_snapshot(draft.code, now, now + timedelta(hours=3), config=config)
    view = svc.publish_round(engine, op, draft.id, snap, source="development")
    assert view.status == "open" and view.config_version == BROAD60_432_V1.version


def test_snapshot_for_another_configuration_is_refused(engine, op, variant):
    sched = unique("bind").replace("-", "")
    _add_schedule(engine, sched, 1, BROAD60_432_V1.version)
    draft, now = _draft(engine, op, sched)
    wrong = dev_snapshot(draft.code, now, now + timedelta(hours=3), config=variant)
    with pytest.raises(PublicationRefused, match="different competition configuration"):
        svc.publish_round(engine, op, draft.id, wrong, source="development")


def test_unknown_round_configuration_fails_instead_of_falling_back(engine, op):
    sched = unique("bind").replace("-", "")
    _add_schedule(engine, sched, 1, "not-a-registered-version")
    draft, _ = _draft(engine, op, sched)
    with transaction(engine) as conn, pytest.raises(ConfigError):
        svc.round_config(conn, draft.id)
    with transaction(engine) as conn, pytest.raises(ConfigError):
        svc.schedule_config(conn, sched)


def test_v1_and_a3_rounds_coexist_without_changing_the_active_schedule(engine, op, variant):
    """A3 Checkpoint 2: a draft on a test-only A3 schedule publishes under A3 while the
    active weekend schedule (and every round created on it) stays broad60-432-v1."""
    sched = unique("bind").replace("-", "")
    _add_schedule(engine, sched, 1, variant.version)
    draft, now = _draft(engine, op, sched)
    with transaction(engine) as conn:
        assert svc.schedule_config(conn, "weekend") is BROAD60_432_V1  # active: unchanged
        config = svc.round_config(conn, draft.id)
    assert config is variant
    snap = dev_snapshot(draft.code, now, now + timedelta(hours=3), config=config)
    view = svc.publish_round(engine, op, draft.id, snap, source="development")
    assert view.config_version == "a3-432-v1"
    v1_draft, now = _draft(engine, op, "weekend")
    with transaction(engine) as conn:
        assert svc.round_config(conn, v1_draft.id) is BROAD60_432_V1
