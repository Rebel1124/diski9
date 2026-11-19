"""Phase 6A.2.1 research: revised points, competition-ranked ties, championship series."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from diski9.research import championship as ch

D = Decimal
ROOT = Path(__file__).parents[1]


def fp(*gross):
    return ch.final_points([D(str(g)) for g in gross])


def test_revised_schedule_and_floor():
    field = [300 - 10 * i for i in range(12)] + [100, D("99.99"), 0]
    p = fp(*field)
    assert p[:10] == [150, 135, 125, 120, 115, 110, 105, 100, 95, 90]
    assert p[10:13] == [75, 75, 75]  # 11th+ with gross >= 100, including exactly 100.00
    assert p[13:] == [0, 0]
    assert max(ch.REVISED_TOP10) <= ch.REVISED_FLOOR * 2  # recovery worth half the maximum


def test_exactly_100_qualifies_and_failed_recovery_scores_zero():
    assert fp("100.00") == [150]
    assert fp("99.99") == [0]
    assert fp(95, 90, 80) == [0, 0, 0]  # nobody recovers: first place still scores 0


def test_non_additive_first_place():
    assert fp(250, 100) == [150, 135]  # first receives 150 in total, not 150 + 75


def test_two_tied_first_get_full_points_and_rank_three_follows():
    assert fp(350, 350, 290, 250, 210) == [150, 150, 125, 120, 115]


def test_tie_across_top_ten_boundary_brief_example():
    lead = [500 - i for i in range(8)]  # ranks 1-8
    p = fp(*lead, 130, 120, 120, 120, 110)
    assert ch.competition_ranks([D(x) for x in [*lead, 130, 120, 120, 120, 110]])[8:] == [
        9,
        10,
        10,
        10,
        13,
    ]
    assert p[8:] == [95, 90, 90, 90, 75]  # eleven entrants receive top-ten points


def test_standard_competition_ranking():
    g = [D(x) for x in (10, 30, 30, 20, 30, 5)]
    assert ch.competition_ranks(g) == [5, 1, 1, 4, 1, 6]


def test_identical_qualifying_payouts_all_rank_first():
    assert fp(*([150] * 30)) == [150] * 30


def test_tied_below_100_score_zero():
    assert fp(300, 80, 80) == [150, 0, 0]


def test_points_are_integers():
    p = fp(300, 300, 300, 200, 150, 120, 120)
    assert all(type(x) is int for x in p)


def test_scenario_rules_match_reference_functions():
    g = [D(x) for x in (400, 400, 300, 250, 250, 250, 200, 180, 160, 140, 120, 120, 110, 90)]
    assert ch.position_points(g, ch.PROPOSED_TOP10, 50, "average") == ch.proposed_points(g)
    assert ch.position_points(g, ch.REVISED_TOP10, 75, "competition") == ch.final_points(g)
    with pytest.raises(ValueError):
        ch.position_points(g, ties="random")
    # without ties the two tie rules coincide
    distinct = [D(x) for x in (400, 300, 200, 150, 120, 90)]
    assert ch.position_points(distinct, ties="average") == ch.position_points(distinct)


# ----------------------------------------------------------- championships
def _series_round(s, rid, results):
    return s.record_round(rid, list(results.items()))


def test_ten_recoveries_beat_five_wins_on_tie_break():
    s = ch.ChampionshipSeries()
    others = {f"o{i}": 300 - i for i in range(10)}  # ten players always ahead of "steady"
    for r in range(10):
        res = dict(others)
        res["steady"] = 100
        if r < 5:
            res["winner"] = 1000
        else:
            res["winner"] = 50
        _series_round(s, r, res)
    t = s.archive[0].table
    assert t["steady"].points == 750 and t["winner"].points == 750
    st = {w: pos for pos, w, _ in ch.standings(t)}
    assert st["steady"] < st["winner"]  # 10 recoveries beat 5


def test_championship_tie_break_hierarchy_and_joint_champions():
    t = {
        "a": ch.Record(600, 5, recoveries=6, qualifying_top10=4),
        "b": ch.Record(600, 5, recoveries=6, qualifying_top10=4),
        "c": ch.Record(600, 5, recoveries=6, qualifying_top10=3),
        "d": ch.Record(600, 5, recoveries=5, qualifying_top10=6),
    }
    st = [(pos, w) for pos, w, _ in ch.standings(t)]
    assert st == [(1, "a"), (1, "b"), (3, "c"), (4, "d")]  # competition ranking


def test_practice_round_excluded_and_counter_not_advanced():
    s = ch.ChampionshipSeries()
    assert _series_round(s, "p1", {"a": 500, "b": 120, "c": 90, "d": 80}) == "practice"
    assert s.current.rounds == [] and s.current.table == {}
    assert s.practice_rounds[0][0] == "p1"
    assert _series_round(s, "r1", {k: 120 for k in "abcde"}) == "championship"
    assert s.current.rounds == ["r1"]


def test_duplicate_submissions_count_once():
    s = ch.ChampionshipSeries()
    subs = [("a", 100), ("a", 200), ("b", 100), ("c", 100), ("d", 100), ("d", 50)]
    assert ch.ChampionshipSeries.valid_entries(subs) == {
        "a": D(200),
        "b": D(100),
        "c": D(100),
        "d": D(50),
    }
    assert s.record_round("r", subs) == "practice"  # four distinct entrants, not six


def test_void_round_does_not_count():
    s = ch.ChampionshipSeries()
    assert s.record_round("x", [(k, 100) for k in "abcdef"], cancelled=True) == "void"
    assert s.void_rounds == ["x"] and s.current.rounds == []


def test_ten_round_completion_reset_and_pause():
    s = ch.ChampionshipSeries()
    for r in range(10):
        _series_round(s, r, {"a": 300, "b": 200, "c": 150, "d": 120, "e": 110})
        if r == 4:  # an off-season practice round mid-championship: pause, then resume
            _series_round(s, "break", {"a": 999})
    first = s.archive[0]
    assert first.status == "complete" and len(first.rounds) == 10
    assert first.champions == ("a",) and first.table["a"].points == 1500
    assert s.current.number == 2 and s.current.table == {}  # reset, nothing carried
    _series_round(s, 10, {"a": 50, "b": 120, "c": 120, "d": 120, "e": 120})
    assert s.current.table["b"].points == 150 and s.current.table["a"].points == 0


def test_joint_champions_recorded():
    s = ch.ChampionshipSeries()
    for r in range(10):
        _series_round(s, r, {"a": 200, "b": 200, "c": 150, "d": 120, "e": 110})
    assert s.archive[0].champions == ("a", "b")


# ------------------------------------------------------------ simulation
def _sim_module():
    spec = importlib.util.spec_from_file_location(
        "refine", ROOT / "scripts" / "research_championship_refinement.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_simulation_is_deterministic_and_uses_common_inputs():
    m = _sim_module()
    a = m.simulate((8, 0, 123, False))
    b = m.simulate((8, 0, 123, False))
    assert a == b
    # scenarios share settled inputs: weekly tie statistics are scenario-free, and
    # A vs E (same schedule and floor) differ only through tie handling
    if a["weekly"]["tie_groups"] == 0:
        assert a["scen"]["A"]["credit"] == a["scen"]["E"]["credit"]
    assert set(a["scen"]) == set("ABCDE")


def test_scenario_definitions():
    m = _sim_module()
    assert m.SCENARIOS["A"] == (ch.PROPOSED_TOP10, 50, "average")
    assert m.SCENARIOS["B"] == (ch.PROPOSED_TOP10, 75, "average")
    assert m.SCENARIOS["C"] == (ch.REVISED_TOP10, 75, "average")
    assert m.SCENARIOS["D"] == (ch.REVISED_TOP10, 75, "competition")
    assert m.SCENARIOS["E"] == (ch.PROPOSED_TOP10, 50, "competition")
