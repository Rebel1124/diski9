from __future__ import annotations

import pytest

from diski9.ingestion.classify import (
    TeamGround,
    classify_round,
    classify_venue,
    is_final,
    modal_home_venue,
    stats_exclusion_reason,
)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Regular Season - 12", "regular"),
        ("Playoffs - 1", "playoff"),
        ("Finals - 1", "playoff"),
        ("Semi-finals", "playoff"),
        ("Final", "playoff"),
        ("Relegation Round - 1", "relegation"),
        ("Promotion Play-off", "promotion"),
        ("Group A - 1", "other"),
        (None, "other"),
    ],
)
def test_classify_round(label, expected):
    assert classify_round(label) == expected


@pytest.mark.parametrize(
    "status,round_type,ft,reason",
    [
        ("FT", "regular", (1, 0), None),
        ("AET", "regular", (1, 1), None),
        ("PEN", "regular", (0, 0), None),
        ("FT", "playoff", (1, 0), "playoff_round"),
        ("FT", "relegation", (1, 0), "relegation_round"),
        ("FT", "other", (1, 0), "non_regular_round"),
        ("AWD", "regular", (3, 0), "awarded"),
        ("WO", "regular", (None, None), "walkover"),
        ("CANC", "regular", (None, None), "cancelled"),
        ("PST", "regular", (None, None), "postponed"),
        ("ABD", "regular", (None, None), "abandoned"),
        ("NS", "regular", (None, None), "not_started"),
        ("2H", "regular", (None, None), "in_progress"),
        ("FT", "regular", (None, None), "missing_score"),
        ("XYZ", "regular", (1, 0), "unknown_status"),
    ],
)
def test_stats_exclusion_reason(status, round_type, ft, reason):
    assert stats_exclusion_reason(status, round_type, *ft) == reason


def test_awarded_is_never_final():
    assert not is_final("AWD", 3, 0)
    assert is_final("FT", 0, 0)
    assert not is_final("FT", None, 0)


def test_modal_home_venue():
    assert modal_home_venue([1, 1, 1, 2, None]) == 1
    assert modal_home_venue([1, 2, 3, 4]) is None  # no dominant ground
    assert modal_home_venue([1, 1]) is None  # too few matches
    assert modal_home_venue([None, None]) is None


def test_classify_venue():
    home = TeamGround(registered_venue_id=10, modal_venue_id=11)
    away = TeamGround(registered_venue_id=20)
    assert classify_venue(10, home, away) == ("home_ground", "registered_ground")
    assert classify_venue(11, home, away) == ("home_ground", "usual_ground")
    assert classify_venue(20, home, away) == ("unverified_venue", "away_team_ground")
    assert classify_venue(99, home, away) == ("unverified_venue", "not_home_team_ground")
    assert classify_venue(None, home, away) == ("unknown", "venue_missing")
    assert classify_venue(10, TeamGround(), away) == ("unknown", "home_ground_unknown")
    assert classify_venue(10, home, away, override="neutral") == ("neutral", "explicit_override")
    # ground share: venue is both teams' ground -> home ground
    assert classify_venue(20, TeamGround(registered_venue_id=20), away)[0] == "home_ground"


def test_approved_home_ground_and_unknown_vs_unverified():
    home = TeamGround(registered_venue_id=10)
    away = TeamGround(registered_venue_id=20)
    assert classify_venue(30, home, away, approved=frozenset({30})) == (
        "home_ground",
        "approved_home_ground",
    )
    assert classify_venue(30, home, away) == (
        "unverified_venue",
        "not_home_team_ground",
    )  # flagged, not neutral
    # approval works even when registered/usual grounds are unknown
    assert classify_venue(30, TeamGround(), away, approved=frozenset({30}))[0] == "home_ground"
