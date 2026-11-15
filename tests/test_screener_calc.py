"""Pure calculations, including the worked examples in Specification v1.2."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from diski9.screener.calc import (
    Rate,
    combined_indicator,
    display,
    form_score,
    limited_data_reasons,
    pooled_benchmark,
    rate,
    venue_adjusted_difference,
)

F = Fraction


def test_spec_4_3_form_score_example():
    # W-D-W-L-W with total goal difference +5 -> spec 2.50, +1 scale offset -> 3.50
    fs = form_score([(2, 0), (1, 1), (2, 0), (0, 1), (2, 0)])
    assert (fs.wins, fs.draws, fs.losses, fs.points) == (3, 1, 1, 10)
    assert fs.ppg == 2 and fs.goal_difference == 5 and fs.gd_per_game == 1
    assert fs.gd_contribution == F(1, 2)
    assert fs.score == F(7, 2) and display(fs.score) == "3.50"
    assert fs.score - 1 == F(5, 2)  # the spec v1.2 value before the offset


def test_spec_4_6_venue_adjusted_example():
    # spec values on the old scale ...
    raw = F("2.80") - F("1.80")
    vad = venue_adjusted_difference(F("2.80"), F("1.80"), F("1.70"), F("1.00"))
    assert raw == 1 and vad == F("0.30")
    # ... and the same teams/benchmarks on the 0-5 scale: differences identical
    assert F("3.80") - F("2.80") == raw
    assert venue_adjusted_difference(F("3.80"), F("2.80"), F("2.70"), F("2.00")) == vad


def test_spec_5_2_btts_example():
    combined = combined_indicator(Rate(8, 10), Rate(6, 10))
    assert combined == F(7, 10) and 1 - combined == F(3, 10)
    assert Rate(8, 10).as_dict()["display"] == "8/10 (80%)"


def test_spec_6_2_over_under_example():
    combined = combined_indicator(Rate(8, 10), Rate(4, 10))
    assert combined == F(3, 5) and 1 - combined == F(2, 5)


def test_spec_10_5_small_samples():
    assert Rate(3, 4).as_dict()["display"] == "3/4 (75%)"
    fs = form_score([(2, 0), (1, 1), (1, 0), (0, 1)])  # 1 + 7/4 + 0.5 x 2/4 = 3.00
    assert display(fs.score) == "3.00"
    fs = form_score([(3, 0), (1, 1), (1, 0), (0, 1)])  # 1 + 1.75 + 0.375 = 3.125
    assert fs.matches == 4 and display(fs.score) == "3.13"


def test_zero_denominator_gives_no_indicator():
    assert form_score([]) is None
    assert rate([]) is None
    assert combined_indicator(Rate(1, 2), None) is None
    assert pooled_benchmark(39, 2025, []) is None


def test_bounds_extremes():
    assert form_score([(9, 0)] * 5).score == 5  # GD capped at +2
    assert form_score([(0, 9)] * 5).score == 0
    assert form_score([(0, 0)] * 5).score == 2


@given(st.lists(st.tuples(st.integers(0, 12), st.integers(0, 12)), min_size=1, max_size=10))
def test_form_score_always_within_bounds(results):
    fs = form_score(results)
    assert 0 <= fs.score <= 5
    assert -2 <= fs.capped_gd_per_game <= 2


def test_gd_cap_applied_before_weighting():
    fs = form_score([(6, 0), (5, 0)])  # GD/G = 5.5 -> capped 2 -> +1.0
    assert fs.capped_gd_per_game == 2 and fs.gd_contribution == 1 and fs.score == 5


def test_pooled_benchmark_uses_league_totals_not_team_scores():
    # Two matches: home wins 5-0 and draws 0-0. Pooled: PPG 2.0, GD/G 2.5 -> capped 2
    b = pooled_benchmark(39, 2025, [(5, 0), (0, 0)])
    assert b.home.ppg == 2 and b.home.capped_gd_per_game == 2 and b.home.score == 4
    assert b.away.ppg == F(1, 2) and b.away.score == F(1, 2)  # 1 + 0.5 - 1
    assert b.draw_rate == F(1, 2)


@given(st.lists(st.tuples(st.integers(0, 4), st.integers(0, 4)), min_size=20, max_size=60))
def test_spec_4_7_benchmarks_sum_to_five_minus_draw_rate(scores):
    # spec: home + away benchmarks = 3 - draw rate; with +1 on each, 5 - draw rate
    b = pooled_benchmark(39, 2025, scores)
    if abs(b.home.gd_per_game) <= 2:  # cap not reached (the spec's stated condition)
        assert b.home.score + b.away.score == 5 - b.draw_rate


def test_spec_10_4_limited_data_examples():
    # BTTS based on 4/4 matches -> flagged (fewer than six)
    assert "fewer_than_6_matches" in limited_data_reasons(4, 4, 6)
    # ten matches, only two from the current division -> flagged
    assert limited_data_reasons(10, 2, 6) == ["fewer_than_3_current_division_matches"]
    # Form Score on four current-division matches -> not flagged
    assert limited_data_reasons(4, 4, 3) == []
    # conditions are independent
    assert len(limited_data_reasons(2, 1, 3)) == 2


def test_display_rounds_half_up():
    assert display(F(2505, 1000)) == "2.51"
    assert display(F(-1, 200)) == "-0.01"  # half away from zero
    assert display(None) is None


@given(
    st.lists(st.tuples(st.integers(0, 6), st.integers(0, 6)), min_size=1, max_size=5),
    st.lists(st.tuples(st.integers(0, 6), st.integers(0, 6)), min_size=1, max_size=5),
    st.lists(st.tuples(st.integers(0, 4), st.integers(0, 4)), min_size=1, max_size=40),
)
def test_scale_offset_leaves_differences_unchanged(home, away, league):
    """Raw and venue-adjusted differences equal their spec v1.2 (unshifted) values."""
    h, a, b = form_score(home), form_score(away), pooled_benchmark(39, 2025, league)
    old = lambda fs: fs.ppg + fs.gd_contribution  # noqa: E731 - spec v1.2 score
    assert h.score - a.score == old(h) - old(a)
    assert venue_adjusted_difference(h.score, a.score, b.home.score, b.away.score) == (
        (old(h) - old(b.home)) - (old(a) - old(b.away))
    )


def test_breakdown_reports_offset():
    bd = form_score([(1, 0)]).breakdown()
    assert bd["scale_offset"] == 1.0 and bd["form_score"] == 4.5  # 1 + 3 + 0.5 x 1
