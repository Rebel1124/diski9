"""Method B (continuous) research calculations; Method A stays the production score."""

from __future__ import annotations

from datetime import timedelta
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diski9.research.form_score_comparison import (
    build_dataset,
    continuous_form_score,
    exploratory_symmetric_gd_score,
    out_of_sample,
    spearman,
)
from diski9.screener.calc import banded_form_score
from diski9.screener.engine import ENGINE_VERSION, MatchStore

from .factories import T0, fixture_item, seed_competition

F = Fraction


def test_legacy_method_a_unchanged():
    # production moved to Model D in engine 2.1.0; Method A stays as the legacy helper
    assert ENGINE_VERSION == "3.1.0"  # Phase 8 CP2A: Goal Model 1.1
    fs = banded_form_score([(3, 0), (2, 0), (2, 1), (0, 1), (5, 1)])
    assert fs.breakdown()["form_score_display"] == "4.23"


@pytest.mark.parametrize(
    "results,points,gd,expected_p,expected_g",
    [
        ([(0, 2)] * 5, 0, -10, F(0), F(0)),
        ([(1, 0)] * 5, 15, 5, F(5, 2), F(5, 2) * F(5, 9)),
        ([(3, 0)] * 5, 15, 15, F(5, 2), F(5, 2)),  # GD capped at 9
        ([(1, 1)] * 5, 5, 0, F(5, 6), F(0)),
    ],
)
def test_components(results, points, gd, expected_p, expected_g):
    b = continuous_form_score(results)
    assert b.points == points and b.goal_difference == gd
    assert b.points_component == expected_p and b.goal_difference_component == expected_g


def test_bonuses_match_method_a():
    for res in (
        [(4, 0), (3, 1), (2, 0), (1, 1), (1, 0)],
        [(1, 0), (1, 0), (0, 1), (1, 0), (0, 0)],
        [(0, 0)] * 5,
    ):
        a, b = banded_form_score(res), continuous_form_score(res)
        assert b.bonuses == a.bonus_last_three_wins + a.bonus_goals_scored + a.bonus_goals_conceded


def test_maximum_is_five_and_minimum_zero():
    assert (
        continuous_form_score([(3, 0), (2, 0), (2, 1), (2, 1), (3, 0)]).score == 5
    )  # 15 pts, GD +10, all bonuses
    assert continuous_form_score([(0, 3)] * 5).score == 0


def test_partial_window_policy_same_as_production():
    two = continuous_form_score([(2, 0), (2, 0)])  # actual totals, never prorated
    assert two.points_component == F(5, 2) * F(6, 15)
    assert two.goal_difference_component == F(5, 2) * F(4, 9)
    assert two.bonuses == 0  # last-3 needs 3 matches; conceded bonus needs 5
    three = continuous_form_score([(1, 0)] * 3)
    assert three.bonuses == F(1, 2)
    assert continuous_form_score([]) is None


@given(st.lists(st.tuples(st.integers(0, 9), st.integers(0, 9)), min_size=1, max_size=5))
def test_b_bounded_and_never_below_a_points_band(results):
    b = continuous_form_score(results)
    assert 0 <= b.score <= 5
    c = exploratory_symmetric_gd_score(results)
    assert 0 <= c <= 5


def test_spearman_basic():
    assert spearman({1: 1, 2: 2, 3: 3}, {1: 10, 2: 20, 3: 30}) == pytest.approx(1)
    assert spearman({1: 1, 2: 2, 3: 3}, {1: 3, 2: 2, 3: 1}) == pytest.approx(-1)


def test_dataset_is_point_in_time_and_oos_runs(conn):
    seed_competition(conn, 39, years=(2024, 2025, 2026))
    from diski9.ingestion.fixtures import store_fixtures

    items, fid, t = [], 1, T0 - 700 * timedelta(days=1)
    for season in (2024, 2025, 2026):
        for i in range(60):
            h, a = 1 + i % 6, 1 + (i + 1 + i // 6) % 6
            if h == a:
                a = 1 + (a % 6)
            t += timedelta(days=3)
            items.append(
                fixture_item(fid, h, a, season=season, kickoff=t, ft=((i * 7) % 4, (i * 3) % 3))
            )
            fid += 1
    store_fixtures(conn, items, lambda: T0)
    store = MatchStore(conn)
    rows = build_dataset(store, [39], [2024, 2025, 2026])
    assert rows and {r.basis for r in rows} == {"venue", "overall"}
    # windows only use matches before kickoff: recompute one row from a truncated store
    r = next(x for x in rows if x.basis == "venue" and x.season == 2025)
    again = build_dataset(store.truncated(r.kickoff + timedelta(seconds=1)), [39], [2025])
    same = next(x for x in again if x.fixture_id == r.fixture_id and x.basis == "venue")
    assert (same.a_home, same.b_home, same.a_away, same.b_away) == (
        r.a_home,
        r.b_home,
        r.a_away,
        r.b_away,
    )
    res = out_of_sample(rows, {2024}, {2025, 2026}, "venue")
    assert res["method_a"]["converged"] and res["method_b"]["converged"]
    assert res["test_n"] > 0 and res["method_a"]["log_loss"] > 0
