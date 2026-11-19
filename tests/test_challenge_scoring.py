"""Phase 6A.3: production weekly and championship scoring (points-150-75-v2)."""

from __future__ import annotations

import random
from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diski9.challenge import scoring as sc
from diski9.challenge.config import ConfigError
from diski9.challenge.scoring import POINTS_150_75_V2 as CFG
from diski9.challenge.scoring import RoundClassification as RC
from diski9.challenge.scoring import SettlementBasis as SB
from diski9.research import championship as ref

D = Decimal
V = CFG.version


def entries(*gross, prefix="p"):
    return tuple(sc.EntryResult(f"{prefix}{i:02d}", D(str(g))) for i, g in enumerate(gross))


def rnd_result(rid, gross, cls=RC.COMPETITIVE, champ="c1", final=True, ents=None):
    return sc.RoundResult(rid, champ, cls, ents if ents is not None else entries(*gross), V, final)


def pts(*gross):
    s = sc.score_round(rnd_result("r", gross))
    return [s.score_of(f"p{i:02d}").points for i in range(len(gross))]


def ranks(*gross):
    s = sc.score_round(rnd_result("r", gross))
    return [s.score_of(f"p{i:02d}").rank for i in range(len(gross))]


# ------------------------------------------------------------- config
def test_scoring_configuration():
    assert V == "points-150-75-v2"
    assert CFG.top_points == (150, 135, 125, 120, 115, 110, 105, 100, 95, 90)
    assert CFG.recovery_points == 75 and CFG.max_weekly_points == 150
    assert CFG.max_championship_points == 1500 and CFG.min_competitive_entries == 5
    assert sc.get_scoring_config(V) is CFG
    with pytest.raises(ConfigError):
        sc.get_scoring_config("points-150-50-v1")
    for bad in (
        dict(top_points=(150, 160)),
        dict(top_points=(200,)),
        dict(recovery_points=95),
        dict(top_points=()),
        dict(recovery_target=D("90.00")),
    ):
        kw = dict(version="x", top_points=CFG.top_points, recovery_points=75) | bad
        with pytest.raises(ConfigError):
            sc.ScoringConfig(**kw)


# ------------------------------------------------------------- weekly points
def test_every_position_in_the_schedule():
    field = [300 - 10 * i for i in range(12)] + [100, D("99.99"), 0]
    assert pts(*field) == [150, 135, 125, 120, 115, 110, 105, 100, 95, 90, 75, 75, 75, 0, 0]
    assert ranks(*field) == list(range(1, 16))


def test_recovery_threshold_is_exactly_100():
    assert pts("100.00", 50, 40, 30, 20) == [150, 0, 0, 0, 0]
    assert pts("99.99", 50, 40, 30, 20) == [0] * 5
    s = sc.score_round(rnd_result("r", ("99.99", 50, 40, 30, 20)))
    assert s.score_of("p00").rank == 1 and not s.score_of("p00").recovered


def test_non_additive_first_place():
    assert pts(900, 100, 0, 0, 0)[:2] == [150, 135]


def test_joint_first_and_shared_ranks():
    assert ranks(350, 350, 290, 250, 210) == [1, 1, 3, 4, 5]
    assert pts(350, 350, 290, 250, 210) == [150, 150, 125, 120, 115]
    assert ranks(200, 200, 200, 150, 120) == [1, 1, 1, 4, 5]
    assert pts(200, 200, 200, 150, 120) == [150, 150, 150, 120, 115]


def test_ties_crossing_tenth_place():
    lead = [500 - i for i in range(8)]
    g = [*lead, 130, 120, 120, 120, 110]
    assert ranks(*g)[8:] == [9, 10, 10, 10, 13]
    assert pts(*g)[8:] == [95, 90, 90, 90, 75]
    s = sc.score_round(rnd_result("r", g))
    assert sum(x.qualifying_top10 for x in s.scores) == 12  # more than ten top-ten finishes


def test_everyone_identical_or_nobody_recovers():
    assert pts(*([150] * 30)) == [150] * 30
    assert pts(95, 95, 80, 10, 0) == [0] * 5
    assert pts(300, 80, 80, 80, 80) == [150, 0, 0, 0, 0]  # tied below 100: zero


def test_points_are_integers_and_bounded():
    s = sc.score_round(rnd_result("r", (300, 300, 200, 150, 120, 120, 100, 50)))
    assert all(type(x.points) is int and 0 <= x.points <= 150 for x in s.scores)
    assert all(x.net == x.gross - 100 for x in s.scores)


def test_display_order_is_deterministic_but_not_competitive():
    ents = (sc.EntryResult("zed", D(200)), sc.EntryResult("amy", D(200)),
            sc.EntryResult("bob", D(300)), sc.EntryResult("cat", D(50)),
            sc.EntryResult("dan", D(120)))  # fmt: skip
    s = sc.score_round(rnd_result("r", (), ents=ents))
    assert [x.participant_id for x in s.scores] == ["bob", "amy", "zed", "dan", "cat"]
    assert s.score_of("amy").rank == s.score_of("zed").rank == 2
    assert s.score_of("amy").points == s.score_of("zed").points == 135


# --------------------------------------------------------- round classes
def test_round_classification_rules():
    assert sc.classify_round(4, False) is RC.PRACTICE
    assert sc.classify_round(5, False) is RC.COMPETITIVE
    assert sc.classify_round(50, True) is RC.VOID
    with pytest.raises(sc.ScoringInputError):
        sc.classify_round(-1, False)


def test_practice_round_awards_nothing():
    s = sc.score_round(rnd_result("r", (300, 120, 50), cls=RC.PRACTICE, champ=None))
    assert [x.rank for x in s.scores] == [1, 2, 3]  # a weekly leaderboard is still shown
    assert all(x.points == 0 and not x.counts_for_championship and not x.qualifying_top10
               for x in s.scores)  # fmt: skip
    assert s.score_of("p00").recovered  # informational only
    with pytest.raises(sc.ScoringInputError, match="competitive, not practice"):
        sc.score_round(rnd_result("r", (1, 2, 3, 4, 5), cls=RC.PRACTICE))
    with pytest.raises(sc.ScoringInputError, match="practice round"):
        sc.score_round(rnd_result("r", (1, 2, 3, 4)))


def test_void_round_awards_nothing():
    s = sc.score_round(rnd_result("r", (100, 100, 100, 100, 100, 100), cls=RC.VOID))
    assert all(x.rank is None and x.points == 0 and not x.recovered and not x.counts_for_championship
               for x in s.scores)  # fmt: skip


def test_ineligible_entry_is_unranked_and_does_not_displace_others():
    ents = entries(300, 250, 200, 150, 120) + (
        sc.EntryResult("dq", D(999), championship_eligible=False, ineligible_reason="rules breach"),
    )
    s = sc.score_round(rnd_result("r", (), ents=ents))
    assert s.score_of("dq").rank is None and s.score_of("dq").points == 0
    assert s.score_of("p00").rank == 1 and s.score_of("p00").points == 150
    with pytest.raises(sc.ScoringInputError, match="reason"):
        sc.score_round(rnd_result("r", (), ents=entries(1, 2, 3, 4) +
                                  (sc.EntryResult("x", D(5), championship_eligible=False),)))  # fmt: skip


def _policy(policy):
    return sc.ScoringConfig(version=V, top_points=CFG.top_points, recovery_points=75,
                            all_void_policy=policy)  # fmt: skip


def test_all_void_entries_are_distinguishable_and_policy_driven():
    ents = entries(300, 250, 90, 80) + (sc.EntryResult("v", D("100.00"), SB.ALL_SELECTIONS_VOID),)
    # literal rule: exactly 100.00 recovers and earns points at its rank
    s = sc.score_round(rnd_result("r", (), ents=ents), _policy(sc.AllVoidPolicy.SCORE_AS_SETTLED))
    v = s.score_of("v")
    assert v.basis is SB.ALL_SELECTIONS_VOID and v.rank == 3 and v.points == 125 and v.recovered
    # ranked but no points
    s2 = sc.score_round(rnd_result("r", (), ents=ents), _policy(sc.AllVoidPolicy.NO_POINTS))
    v2 = s2.score_of("v")
    assert v2.rank == 3 and v2.points == 0 and not v2.recovered and not v2.qualifying_top10
    assert s2.score_of("p02").rank == 4
    with pytest.raises(sc.ScoringInputError, match="exactly 100.00"):
        sc.score_round(rnd_result("r", (), ents=entries(1, 2, 3, 4) +
                                  (sc.EntryResult("v", D("99.00"), SB.ALL_SELECTIONS_VOID),)))  # fmt: skip


def test_d33_refund_unranked_is_the_proposed_default():
    assert CFG.all_void_policy is sc.AllVoidPolicy.REFUND_UNRANKED
    ents = entries(300, 250, 90, 80, 70) + (
        sc.EntryResult("v", D("100.00"), SB.ALL_SELECTIONS_VOID),
    )
    s = sc.score_round(rnd_result("r", (), ents=ents))
    v = s.score_of("v")
    assert v.refunded and v.rank is None and v.points == 0 and not v.recovered
    assert not v.qualifying_top10 and not v.counts_for_championship and v.net == 0
    assert "Void \u2014 Refunded" in v.note
    # other entrants are ranked as if the refunded entry were absent
    assert [s.score_of(f"p{i:02d}").rank for i in range(5)] == [1, 2, 3, 4, 5]
    assert [s.score_of(f"p{i:02d}").points for i in range(5)] == [150, 135, 0, 0, 0]
    assert s.scores[-1].participant_id == "v"  # listed separately, after ranked entries
    # the round stays competitive and the refund does not count for the championship
    t = sc.aggregate_championship("c1", [rnd_result("r", (), ents=ents)])
    assert "v" not in {x.participant_id for x in t.standings}
    # a refunded entry still counts toward the five valid entries fixed at the deadline
    four_plus_void = entries(300, 250, 90, 80) + (
        sc.EntryResult("v", D("100.00"), SB.ALL_SELECTIONS_VOID),
    )
    assert sc.score_round(rnd_result("r", (), ents=four_plus_void)).awards_points


def test_genuine_100_recovery_differs_from_refund():
    ents = entries(300, "100.00", 90, 80) + (
        sc.EntryResult("v", D("100.00"), SB.ALL_SELECTIONS_VOID),
    )
    s = sc.score_round(rnd_result("r", (), ents=ents))
    real, void = s.score_of("p01"), s.score_of("v")
    assert real.gross == void.gross == D("100.00")
    assert real.recovered and real.points == 135 and real.rank == 2
    assert not void.recovered and void.points == 0 and void.rank is None


# ------------------------------------------------------- input validation
@pytest.mark.parametrize(
    "result, match",
    [
        (sc.RoundResult("r", "c", RC.COMPETITIVE, entries(1, 2, 3, 4, 5) + entries(9, prefix="p"),
                        V), "duplicate"),
        (sc.RoundResult("r", "c", RC.COMPETITIVE, entries(1, 2, 3, 4, "5.001"), V), "0.01"),
        (sc.RoundResult("r", "c", RC.COMPETITIVE, entries(1, 2, 3, 4, -5), V), "non-negative"),
        (sc.RoundResult("r", "c", RC.COMPETITIVE, entries(1, 2, 3, 4, 5), "points-x"), "version"),
        (sc.RoundResult("", "c", RC.COMPETITIVE, entries(1, 2, 3, 4, 5), V), "round_id"),
        (sc.RoundResult("r", None, RC.COMPETITIVE, entries(1, 2, 3, 4, 5), V), "championship"),
        (sc.RoundResult("r", "c", RC.COMPETITIVE,
                        entries(1, 2, 3, 4) + (sc.EntryResult("u", None),), V), "unsettled"),
    ],
)  # fmt: skip
def test_invalid_round_inputs(result, match):
    with pytest.raises(sc.ScoringInputError, match=match):
        sc.score_round(result)


# ------------------------------------------------------------ championship
def _season(n_rounds=10, field=None):
    field = field or {"a": 300, "b": 200, "c": 150, "d": 120, "e": 110}
    return [sc.RoundResult(f"r{i}", "c1", RC.COMPETITIVE,
                           tuple(sc.EntryResult(p, D(g)) for p, g in field.items()), V)
            for i in range(n_rounds)]  # fmt: skip


def test_ten_round_championship_and_maximum():
    t = sc.aggregate_championship("c1", _season())
    assert t.is_complete and t.completed_rounds == 10 and t.champions == ("a",)
    top = t.standings[0]
    assert (top.points, top.recoveries, top.qualifying_top10, top.rounds_entered) == (
        1500,
        10,
        10,
        10,
    )
    assert top.points == CFG.max_championship_points
    partial = sc.aggregate_championship("c1", _season(7))
    assert not partial.is_complete and partial.champions == () and partial.leaders == ("a",)
    with pytest.raises(sc.ScoringInputError, match="exactly 10"):
        sc.aggregate_championship("c1", _season(11))


def test_ten_recoveries_beat_five_wins():
    rounds = []
    for i in range(10):
        field = {f"o{k}": 300 - k for k in range(10)} | {"steady": 100,
                                                         "winner": 1000 if i < 5 else 50}  # fmt: skip
        rounds.append(sc.RoundResult(f"r{i}", "c1", RC.COMPETITIVE,
                                     tuple(sc.EntryResult(p, D(g)) for p, g in field.items()), V))  # fmt: skip
    t = sc.aggregate_championship("c1", rounds)
    s = {x.participant_id: x for x in t.standings}
    assert s["steady"].points == s["winner"].points == 750
    assert s["steady"].rank < s["winner"].rank  # recoveries break the tie


def test_tie_break_hierarchy_and_joint_champions():
    # a and b identical every round -> joint champions with shared rank 1
    t = sc.aggregate_championship("c1", _season(field={"a": 200, "b": 200, "c": 150,
                                                       "d": 120, "e": 90}))  # fmt: skip
    ranks_ = {x.participant_id: x.rank for x in t.standings}
    assert ranks_ == {"a": 1, "b": 1, "c": 3, "d": 4, "e": 5} and t.champions == ("a", "b")
    # equal points and recoveries, separated by qualifying top-ten finishes
    r1 = sc.RoundResult("x1", "c1", RC.COMPETITIVE, entries(*([300] * 9), 101, 101, prefix="q"), V)
    # q09/q10 are rank 10 (90 points each) in x1; build x2 where only q10 recovers outside top ten
    t2 = sc.aggregate_championship("c1", [r1])
    assert {x.participant_id: x.rank for x in t2.standings}["q09"] == 10


def test_qualifying_top10_used_after_recoveries():
    # p and q: equal points and recoveries; p has 2 top-ten finishes, q has 1
    # construct an exact points tie: p = 90 + 90, q = 105 + 75
    r_a = sc.RoundResult("a", "c1", RC.COMPETITIVE, (
        *[sc.EntryResult(f"f{k}", D(500 - k)) for k in range(9)],
        sc.EntryResult("p", D(150)), sc.EntryResult("q", D(120))), V)  # fmt: skip
    r_b = sc.RoundResult("b", "c1", RC.COMPETITIVE, (
        *[sc.EntryResult(f"f{k}", D(500 - k)) for k in range(6)],
        sc.EntryResult("q", D(300)), sc.EntryResult("g1", D(250)), sc.EntryResult("g2", D(240)),
        sc.EntryResult("p", D(200)), sc.EntryResult("h", D(190)),
        sc.EntryResult("z", D(110))), V)  # fmt: skip
    t = sc.aggregate_championship("c1", [r_a, r_b])
    s = {x.participant_id: x for x in t.standings}
    assert s["p"].points == s["q"].points
    assert s["p"].recoveries == s["q"].recoveries == 2
    assert s["p"].qualifying_top10 > s["q"].qualifying_top10 and s["p"].rank < s["q"].rank


def test_practice_and_void_rounds_excluded_and_mid_championship_entry():
    rounds = _season(5)
    rounds.append(sc.RoundResult("prac", None, RC.PRACTICE, entries(900, 800, prefix="a"), V))
    rounds.append(sc.RoundResult("void", "c1", RC.VOID, entries(*([100] * 6)), V))
    rounds += [sc.RoundResult(f"s{i}", "c1", RC.COMPETITIVE,
                              tuple(sc.EntryResult(p, D(g)) for p, g in
                                    {"a": 300, "b": 200, "c": 150, "d": 120, "late": 500}.items()), V)
               for i in range(3)]  # fmt: skip
    t = sc.aggregate_championship("c1", rounds)
    s = {x.participant_id: x for x in t.standings}
    assert t.completed_rounds == 8 and set(t.ignored_round_ids) == {"prac", "void"}
    assert s["late"].rounds_entered == 3 and s["late"].points == 450
    assert s["e"].rounds_entered == 5 and s["e"].points == 5 * 115  # missed rounds: no change
    assert "a00" not in s and "p00" not in s  # practice/void participants earn nothing
    assert s["a"].points == 5 * 150 + 3 * 135


def test_duplicate_and_foreign_rounds_rejected():
    r = _season(2)
    with pytest.raises(sc.ScoringInputError, match="more than once"):
        sc.aggregate_championship("c1", [r[0], r[0]])
    other = sc.RoundResult("o", "c2", RC.COMPETITIVE, entries(1, 2, 3, 4, 5), V)
    with pytest.raises(sc.ScoringInputError, match="belongs"):
        sc.aggregate_championship("c1", [r[0], other])


def test_corrected_settlement_recomputes_deterministically():
    rounds = _season(10)
    before = sc.aggregate_championship("c1", rounds)
    corrected = list(rounds)
    corrected[3] = sc.RoundResult("r3", "c1", RC.COMPETITIVE, tuple(
        sc.EntryResult(p, D(g)) for p, g in
        {"a": 90, "b": 200, "c": 150, "d": 120, "e": 110}.items()), V)  # fmt: skip
    after = sc.aggregate_championship("c1", corrected)
    a_before = before.standings[0]
    a_after = next(x for x in after.standings if x.participant_id == "a")
    assert a_before.points - a_after.points == 150 and a_after.recoveries == 9
    assert sc.aggregate_championship("c1", corrected) == after  # reproducible
    assert sc.aggregate_championship("c1", list(reversed(corrected))).standings == after.standings


def test_provisional_rounds_mark_the_table():
    rounds = _season(10)
    rounds[-1] = sc.RoundResult("r9", "c1", RC.COMPETITIVE, rounds[-1].entries, V, final=False)
    t = sc.aggregate_championship("c1", rounds)
    assert t.provisional and not t.is_complete and t.champions == ()


# ------------------------------------------- agreement with the research code
def test_weekly_points_match_research_reference():
    rng = random.Random(5)
    for _ in range(400):
        n = rng.randint(5, 40)
        gross = [D(rng.choice([0, 50, 99.99, 100, 100.01, 120, 150, 150, 300, 1000]))
                 .quantize(D("0.01")) for _ in range(n)]  # fmt: skip
        s = sc.score_round(rnd_result("r", gross))
        got = [s.score_of(f"p{i:02d}").points for i in range(n)]
        assert got == ref.final_points(gross)
        assert [s.score_of(f"p{i:02d}").rank for i in range(n)] == ref.competition_ranks(gross)


def test_championship_matches_research_series():
    rng = random.Random(9)
    for trial in range(30):
        people = [f"u{k}" for k in range(rng.randint(5, 30))]
        series = ref.ChampionshipSeries()
        rounds = []
        for r in range(10):
            entrants = [p for p in people if rng.random() < 0.85]
            while len(entrants) < 5:
                entrants.append(rng.choice([p for p in people if p not in entrants]))
            g = {p: D(rng.choice([0, 80, 100, 110, 130, 150, 220, 400])) for p in entrants}
            series.record_round(r, list(g.items()))
            rounds.append(sc.RoundResult(f"t{trial}r{r}", "c1", RC.COMPETITIVE,
                                         tuple(sc.EntryResult(p, v) for p, v in g.items()), V))  # fmt: skip
        t = sc.aggregate_championship("c1", rounds)
        research = series.archive[0]
        assert t.champions == tuple(sorted(research.champions))
        rpos = {w: pos for pos, w, _ in ref.standings(research.table)}
        for s in t.standings:
            rec = research.table[s.participant_id]
            assert (s.points, s.recoveries, s.qualifying_top10, s.rounds_entered) == (
                rec.points,
                rec.recoveries,
                rec.qualifying_top10,
                rec.entered,
            )
            assert s.rank == rpos[s.participant_id]


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(0, 40000), min_size=5, max_size=60))
def test_ranking_properties(cents):
    gross = [D(c) / 100 for c in cents]
    s = sc.score_round(rnd_result("r", gross))
    for x in s.scores:
        better = sum(g > x.gross for g in gross)
        assert x.rank == 1 + better
        assert (x.points > 0) == (x.gross >= 100)
        if x.points:
            assert x.points == (CFG.top_points[x.rank - 1] if x.rank <= 10 else 75)
    assert Fraction(sum(x.points for x in s.scores)).denominator == 1


def test_worked_example_script_runs(capsys):
    import runpy
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts" / "example_weekly_challenge.py"
    runpy.run_path(str(path), run_name="__main__")
    out = capsys.readouterr().out
    assert "Champion(s): Lee, Sipho" in out and "P(recover 100) 36.9820%" in out
