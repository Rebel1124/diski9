"""Milestone 5 Diski Form Score: bands, bonuses, normalisation, partial windows."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diski9.screener.calc import diski_form_score, goal_difference_award, points_award

F = Fraction


@pytest.mark.parametrize(
    "points,award",
    [
        (0, 0),
        (2, 0),
        (3, 0.5),
        (5, 0.5),
        (6, 1.0),
        (8, 1.0),
        (9, 1.5),
        (11, 1.5),
        (12, 2.0),
        (14, 2.0),
        (15, 2.5),
    ],
)
def test_every_points_band(points, award):
    assert points_award(points) == F(award).limit_denominator()


@pytest.mark.parametrize(
    "gd,award",
    [
        (-7, 0),
        (0, 0),
        (1, 0.5),
        (2, 0.5),
        (3, 1.0),
        (4, 1.0),
        (5, 1.5),
        (6, 1.5),
        (7, 2.0),
        (8, 2.0),
        (9, 2.5),
        (20, 2.5),
    ],
)
def test_every_goal_difference_band(gd, award):
    assert goal_difference_award(gd) == F(award).limit_denominator()


def test_worked_example_423():
    # most recent first: W W W L W; 12 points; 12 scored, 3 conceded; GD +9
    fs = diski_form_score([(3, 0), (2, 0), (2, 1), (0, 1), (5, 1)])
    assert (fs.wins, fs.draws, fs.losses, fs.points) == (4, 0, 1, 12)
    assert (fs.goals_for, fs.goals_against, fs.goal_difference) == (12, 3, 9)
    assert fs.points_award == 2 and fs.goal_difference_award == F(5, 2)
    assert fs.bonus_last_three_wins == F(1, 2)
    assert fs.bonus_goals_scored == F(1, 2)
    assert fs.bonus_goals_conceded == 0
    assert fs.raw == F(11, 2)
    assert float(fs.score) == pytest.approx(4.230769230769)
    assert fs.breakdown()["form_score_display"] == "4.23"


def test_perfect_score_is_five():
    fs = diski_form_score([(3, 0), (2, 0), (2, 1), (2, 1), (3, 0)])  # 15 pts, 12-2 (GD +10)
    assert fs.raw == F(13, 2) and fs.score == 5
    assert fs.breakdown()["form_score_display"] == "5.00"


def test_minimum_score_is_zero_not_negative():
    fs = diski_form_score([(0, 3)] * 5)
    assert fs.raw == 0 and fs.score == 0


def test_each_bonus_independently():
    # last three won only: W W W L L, 9 pts (1.5), 6-6 GD 0 (0), 6 scored, 6 conceded
    a = diski_form_score([(1, 0), (1, 0), (1, 0), (0, 3), (3, 3)])
    assert (
        a.bonus_last_three_wins == F(1, 2)
        and a.bonus_goals_scored == 0
        and a.bonus_goals_conceded == 0
    )
    # goals scored only: 11 goals, losses, no defence
    b = diski_form_score([(2, 3), (2, 3), (2, 3), (2, 3), (3, 4)])
    assert (
        b.bonus_goals_scored == F(1, 2)
        and b.bonus_last_three_wins == 0
        and b.bonus_goals_conceded == 0
    )
    # goals conceded only: five 0-0 draws
    c = diski_form_score([(0, 0)] * 5)
    assert (
        c.bonus_goals_conceded == F(1, 2)
        and c.bonus_goals_scored == 0
        and c.bonus_last_three_wins == 0
    )
    assert c.points == 5 and c.raw == 1  # 0.5 (points) + 0 (GD) + 0.5 (defence bonus)


def test_all_bonuses_together():
    fs = diski_form_score(
        [(4, 0), (3, 1), (2, 0), (1, 1), (1, 0)]
    )  # W W W D W, 11 scored, 2 conceded
    assert fs.bonus_last_three_wins + fs.bonus_goals_scored + fs.bonus_goals_conceded == F(3, 2)


def test_three_most_recent_wins_only():
    recent = diski_form_score([(1, 0), (1, 0), (1, 0), (0, 1), (0, 1)])  # W W W L L
    elsewhere = diski_form_score([(0, 1), (1, 0), (1, 0), (1, 0), (0, 1)])  # L W W W L
    assert recent.bonus_last_three_wins == F(1, 2)
    assert elsewhere.bonus_last_three_wins == 0
    assert recent.points == elsewhere.points and recent.raw - elsewhere.raw == F(1, 2)


def test_missing_history_is_unavailable():
    assert diski_form_score([]) is None


def test_partial_windows_use_actual_matches_without_scaling():
    two = diski_form_score([(2, 0), (2, 0)])  # 6 pts -> 1.0, GD +4 -> 1.0
    assert two.matches == 2 and not two.full_window
    assert two.bonus_last_three_wins == 0  # fewer than three matches
    assert two.bonus_goals_conceded == 0  # needs a full five-match window
    assert two.raw == 2 and two.points_award == 1  # not scaled up to five matches
    three = diski_form_score([(1, 0), (1, 0), (1, 0)])
    assert three.bonus_last_three_wins == F(1, 2) and three.bonus_goals_conceded == 0
    four_scorers = diski_form_score(
        [(3, 0), (3, 0), (3, 0), (2, 0)]
    )  # 11 goals in 4: bonus allowed
    assert four_scorers.bonus_goals_scored == F(1, 2)
    b = two.breakdown()
    assert (
        b["bonus_last_three_wins_possible"] is False and b["bonus_goals_conceded_possible"] is False
    )


@given(st.lists(st.tuples(st.integers(0, 9), st.integers(0, 9)), min_size=1, max_size=5))
def test_always_between_zero_and_five(results):
    fs = diski_form_score(results)
    assert 0 <= fs.score <= 5
    assert fs.raw * 2 == int(fs.raw * 2)  # raw is always a multiple of 0.5
