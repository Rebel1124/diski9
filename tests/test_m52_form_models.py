"""Milestone 5.2 research: Form Score candidates A-D (research only)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from types import SimpleNamespace

import pytest

from diski9.research.form_models import (
    MODELS,
    Window,
    build_rows,
    features,
    positive_gd_component,
    score,
    symmetric_gd_component,
)
from diski9.screener.calc import diski_form_score
from diski9.screener.engine import Match, MatchStore, compute_fixture

T = datetime(2025, 8, 1, 15, tzinfo=UTC)


def random_window(rng, n=None):
    n = rng.randint(1, 5) if n is None else n
    return [(rng.randint(0, 5), rng.randint(0, 5)) for _ in range(n)]


@pytest.mark.parametrize("model", MODELS)
def test_scores_bounded_0_to_5(model):
    rng = random.Random(1)
    for _ in range(3000):
        s = score(model, random_window(rng))
        assert 0 <= s <= 5
    assert score(model, [(5, 0)] * 5) == 5  # perfect window reaches the maximum
    assert score(model, [(0, 5)] * 5) == 0  # worst window reaches the minimum


@pytest.mark.parametrize("model", MODELS)
def test_missing_window_is_unavailable_not_zero(model):
    assert score(model, []) is None


@pytest.mark.parametrize("model", MODELS)
def test_better_result_never_reduces_score(model):
    """Turning one result into a better one (loss -> draw -> win, by one more goal
    scored or one fewer conceded) never lowers the score, all else equal."""
    rng = random.Random(2)
    for _ in range(3000):
        w = random_window(rng)
        i = rng.randrange(len(w))
        f, a = w[i]
        better = list(w)
        better[i] = (f + 1, a) if rng.random() < 0.5 or a == 0 else (f, a - 1)
        assert score(model, better) >= score(model, w), (model, w, better)


def test_component_monotonicity():
    for gd in range(-15, 15):
        assert symmetric_gd_component(gd + 1) >= symmetric_gd_component(gd)
        assert positive_gd_component(gd + 1) >= positive_gd_component(gd)
    w = Window(5, 7, 6, 6, False)
    assert score("d", []) is None
    for pts in range(0, 15):
        lo = Window(5, pts, 6, 6, False)
        hi = Window(5, pts + 1, 6, 6, False)
        from diski9.research.form_models import score_c, score_d

        assert score_d(hi) > score_d(lo) and score_c(hi) > score_c(lo)
    assert w.goal_difference == 0


def test_negative_zero_positive_goal_difference():
    # B (and production A) cannot tell -1 from -12; C and D can
    assert positive_gd_component(-1) == positive_gd_component(-12) == 0
    assert symmetric_gd_component(-12) == symmetric_gd_component(-9) == 0
    assert symmetric_gd_component(-1) < symmetric_gd_component(0) == Fraction(5, 4)
    assert symmetric_gd_component(0) < symmetric_gd_component(1)
    assert symmetric_gd_component(9) == symmetric_gd_component(12) == Fraction(5, 2)
    minus1 = [(0, 1), (1, 1), (1, 1), (1, 1), (1, 1)]  # 4 pts, GD -1
    minus8 = [(0, 8), (1, 1), (1, 1), (1, 1), (1, 1)]  # 4 pts, GD -8
    assert score("a", minus1) == score("a", minus8)
    assert score("b", minus1) == score("b", minus8)
    assert score("c", minus1) > score("c", minus8)
    assert score("d", minus1) > score("d", minus8)


def test_bonuses_applied_correctly():
    # same points (12) and GD (+3) with and without the three bonuses
    plain = [(1, 0), (0, 1), (2, 2), (3, 2), (2, 0)]  # no bonus
    w = Window.of(plain)
    assert (w.points, w.goal_difference) == (10, 3)
    bonus_free = score("c", plain)
    all_bonus = [(3, 0), (3, 1), (2, 1), (0, 0), (3, 0)]  # 3 wins first, 11 scored, 2 conceded
    wb = Window.of(all_bonus)
    assert wb.won_last_three and wb.goals_for == 11 and wb.goals_against == 2
    from diski9.research.form_models import bonuses

    assert bonuses(wb) == Fraction(3, 2) and bonuses(w) == 0
    # D ignores bonuses entirely: equal points and GD -> equal D score
    same_totals_no_bonus = [(0, 0), (3, 0), (3, 1), (2, 1), (3, 0)]  # last-3 not all wins
    assert Window.of(same_totals_no_bonus).points == wb.points
    assert score("d", same_totals_no_bonus) == score("d", all_bonus)
    # only the won-last-three bonus differs: exactly 0.5 raw = 0.5 x 5 / 6.5
    assert score("c", all_bonus) - score("c", same_totals_no_bonus) == Fraction(
        1, 2
    ) * 5 / Fraction(13, 2)
    assert score("c", plain) == (
        Fraction(5, 2) * 10 / 15 + Fraction(5, 4) + Fraction(5, 4) * 3 / 9
    ) * 5 / Fraction(13, 2)
    assert bonus_free == score("c", plain)


def test_partial_window_rules():
    two_wins = [(2, 0), (2, 0)]
    # no prorating: actual totals of the two matches
    assert score("b", two_wins) == (
        Fraction(5, 2) * 6 / 15 + Fraction(5, 2) * 4 / 9
    ) * 5 / Fraction(13, 2)
    assert score("d", two_wins) == Fraction(5, 2) * 6 / 15 + Fraction(5, 4) + Fraction(5, 4) * 4 / 9
    # won-last-three needs three matches; conceded <= 2 needs five
    from diski9.research.form_models import bonuses

    assert bonuses(Window.of(two_wins)) == 0
    assert bonuses(Window.of([(1, 0)] * 3)) == Fraction(1, 2)
    assert bonuses(Window.of([(1, 0)] * 4)) == Fraction(1, 2)
    assert bonuses(Window.of([(1, 0)] * 5)) == Fraction(1)
    # a partial window cannot reach the maximum
    assert score("c", [(5, 0)] * 4) < 5


def test_model_a_is_production_unchanged():
    rng = random.Random(3)
    for _ in range(500):
        w = random_window(rng)
        assert score("a", w) == diski_form_score(w).score


# ------------------------------------------------------------ point in time
def m(fid, days, comp, season, h, a, hg, ag, eligible=True, venue="verified"):
    return Match(
        fid,
        T + timedelta(days=days),
        comp,
        season,
        h,
        a,
        hg,
        ag,
        venue,
        eligible,
        None,
        None,
        "FT",
        str(fid),
    )


def store_of(matches):
    return MatchStore.from_matches(
        matches, {i: f"T{i}" for i in range(1, 20)}, {39: "EPL", 40: "Ch"}
    )


def synthetic():
    ms = [
        m(1, -400, 40, 2024, 1, 9, 2, 0),  # team 1 in the Championship last season
        m(2, 0, 39, 2025, 1, 2, 1, 0),
        m(3, 7, 39, 2025, 2, 1, 0, 0),
        m(4, 14, 39, 2025, 1, 2, 3, 1),
        m(5, 14, 39, 2025, 3, 4, 2, 2),  # same kickoff as fixture 4
        m(6, 21, 39, 2025, 2, 1, 1, 1, eligible=False),  # awarded: never used
        m(7, 28, 39, 2025, 1, 2, 0, 2),
    ]
    return ms


def test_rows_use_only_matches_before_kickoff():
    store = store_of(synthetic())
    rows = build_rows(store, (39,), (2025,))
    by = {(r.fixture_id, r.basis): r for r in rows}
    # fixture 4: team 1 overall window = fixtures 3 and 2 and the Championship match
    r4 = by[(4, "overall")]
    assert r4.home_n == 3 and r4.other_division_in_window
    # same-kickoff match 5 never leaks into fixture 4 (teams 3/4 are not in it anyway);
    # recomputing from a store truncated at kickoff gives identical scores
    for r in rows:
        trunc = build_rows(store.truncated(r.kickoff + timedelta(seconds=1)), (39,), (2025,))
        same = [x for x in trunc if x.fixture_id == r.fixture_id and x.basis == r.basis][0]
        assert same.scores == r.scores
    # adding a later result never changes an earlier row
    later = store_of(synthetic() + [m(8, 60, 39, 2025, 1, 2, 9, 0)])
    rows2 = {(r.fixture_id, r.basis): r for r in build_rows(later, (39,), (2025,))}
    for k, r in by.items():
        assert rows2[k].scores == r.scores


def test_awarded_and_ineligible_fixtures_excluded():
    rows = build_rows(store_of(synthetic()), (39,), (2025,))
    assert 6 not in {r.fixture_id for r in rows}
    r7 = [r for r in rows if r.fixture_id == 7 and r.basis == "overall"][0]
    # team 2's window skips the awarded match 6
    assert r7.away_n == 3


def test_no_duplicate_rows_and_promoted_flag():
    rows = build_rows(store_of(synthetic()), (39,), (2025,))
    keys = [(r.fixture_id, r.basis) for r in rows]
    assert len(keys) == len(set(keys))
    r2 = [r for r in rows if r.fixture_id == 2][0]
    assert r2.changed_division  # team 1 played the Championship last season
    r5 = [r for r in rows if r.fixture_id == 5][0]
    assert not r5.changed_division


def test_row_a_score_matches_production_engine():
    store = store_of(synthetic())
    rows = build_rows(store, (39,), (2025,))
    fx = SimpleNamespace(
        id=7,
        competition_id=39,
        season=2025,
        home_team_id=1,
        away_team_id=2,
        kickoff_utc=T + timedelta(days=28),
    )
    for basis in ("venue", "overall"):
        prod = compute_fixture(store, fx, fx.kickoff_utc + timedelta(days=1), basis)
        row = [r for r in rows if r.fixture_id == 7 and r.basis == basis][0]
        assert row.scores["a"] == (
            prod["match_result"]["home_form"],
            prod["match_result"]["away_form"],
        )


def test_features_unavailable_when_window_missing():
    rows = build_rows(store_of(synthetic()), (39,), (2025,))
    first = [r for r in rows if r.fixture_id == 5][0]  # teams 3 and 4 have no history
    assert first.diff("a") is None
    for f in ("a", "ppg", "gd", "ppg_gd", "venue_ppg", "d_plus_bonuses"):
        assert features(first, f) is None
