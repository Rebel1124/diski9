"""Development mirror rounds: the fixture cap (``round dev-open --fixtures``)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from diski9.backend import devdata
from diski9.challenge.config import BROAD60_432_V1  # explicit: v1 behaviour (A3 4A)
from diski9.screener import cache

T0 = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)


def _row(i: int, hours: float, league: int) -> dict:
    return {
        "fixture": {
            "id": 1000 + i,
            "competition_id": league,
            "competition": f"L{league}",
            "home": f"H{i}",
            "away": f"A{i}",
            "kickoff": (T0 + timedelta(hours=hours)).isoformat(),
        },
        "goal_model": {
            "available": True,
            "estimated_goals": {"home": 1.4, "away": 1.1},
            "probabilities": {
                "home": 0.45,
                "draw": 0.27,
                "away": 0.28,
                "btts_yes": 0.52,
                "btts_no": 0.48,
                "over": 0.5,
                "under": 0.5,
            },
        },
    }


class _Engine:
    @contextmanager
    def connect(self):
        yield None


@pytest.fixture
def rows(monkeypatch):
    # 40 fixtures: one every 3 hours (5 days), three leagues; one 9 days out.
    data = [_row(i, 3 * i, (39, 40, 288)[i % 3]) for i in range(40)] + [_row(99, 24 * 9, 39)]
    monkeypatch.setattr(cache, "cached", lambda conn, basis: data)
    return data


def _snap(fixtures):
    return devdata.mirror_snapshot(
        "dev-mirror-t",
        T0 - timedelta(days=1),
        _Engine(),
        earliest_kickoff=T0,
        fixtures=fixtures,
        config=BROAD60_432_V1,
    )


def test_default_cap_is_twenty_earliest_first(rows):
    s = _snap(20)
    assert [f.fixture_id for f in s.fixtures] == [1000 + i for i in range(20)]


def test_zero_means_every_fixture_within_seven_days(rows):
    s = _snap(0)
    assert len(s.fixtures) == 40  # the fixture nine days out is left out
    assert 1099 not in {f.fixture_id for f in s.fixtures}
    assert {f.league_id for f in s.fixtures} == {39, 40, 288}
    assert len(s.outcomes) == 40 * 7  # 1X2, BTTS and over/under 2.5 per fixture


def test_fixtures_before_the_earliest_kickoff_are_skipped(rows):
    s = devdata.mirror_snapshot(
        "dev-mirror-t",
        T0,
        _Engine(),
        earliest_kickoff=T0 + timedelta(hours=30),
        fixtures=0,
        config=BROAD60_432_V1,
    )
    assert min(f.kickoff for f in s.fixtures) >= T0 + timedelta(hours=30)
