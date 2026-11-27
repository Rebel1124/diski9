"""Phase 6A.2 research: championship scoring rules and round feasibility."""

from __future__ import annotations

import json
import random
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from diski9.research import championship as ch
from diski9.research import risk_structure as rs

D = Decimal
POOL = json.loads(
    (
        Path(__file__).parents[1] / "docs/research/weekly_challenge_risk/pool_weekend.json"
    ).read_text()
)
BROAD60 = rs.BAND_SETS["Broad-60"]


def pts(*gross):
    return ch.proposed_points([D(str(g)) for g in gross])


# ------------------------------------------------------- proposed weekly rule
def test_brief_examples():
    field = [250, 200, 180, 170, 160, 150, 140, 130, 120, 110, 109, 108, 107, 106, 100, 90, 0]
    p = pts(*field)
    assert p[0] == 150  # first with 250 credits: 150, not 200 (non-additive)
    assert p[9] == 75  # tenth with 110 credits
    assert p[14] == 50  # fifteenth with exactly 100.00: the recovery floor
    assert p[15] == 0 and p[16] == 0  # below 100: no recovery, no points
    assert max(p) == 150


def test_fifth_place_without_recovery_scores_zero():
    p = pts(95, 94, 93, 92, 90, 50)  # nobody recovers: all zero, whatever the position
    assert all(x == 0 for x in p)


def test_two_qualifying_players_tied_first_share_average():
    p = pts(300, 300, 150)
    assert p[0] == p[1] == Fraction(150 + 135, 2) == Fraction(285, 2)
    assert p[2] == 120  # the next player takes third place


def test_tie_crossing_tenth_place_boundary_respects_floor():
    top8 = [500 - i for i in range(8)]
    p = pts(*top8, 120, 120, 120, 120, 101)  # positions 9-12 tied, 13th alone
    share = Fraction(80 + 75 + 50 + 50, 4)
    assert p[8:12] == [share] * 4 and share == Fraction(255, 4)  # 63.75
    assert all(x >= ch.RECOVERY_FLOOR for x in p[8:12])
    assert p[12] == 50


def test_three_way_tie_keeps_exact_fraction():
    p = pts(200, 200, 200)
    assert p[0] == Fraction(150 + 135 + 120, 3) == Fraction(135)
    q = pts(500, 200, 200, 200)
    assert q[1] == Fraction(135 + 120 + 110, 3)  # 121.666... kept exact
    assert q[1].denominator == 3


def test_recovery_is_inclusive_at_exactly_100():
    assert pts(D("100.00"))[0] == 150
    assert pts(D("99.99"))[0] == 0


def test_everyone_recovers_and_identical_payouts():
    p = pts(*([150] * 12))
    assert len(set(p)) == 1 and p[0] == Fraction(sum(ch.PROPOSED_TOP10) + 2 * 50, 12)
    q = pts(*range(300, 100, -10))  # 20 players, all recover
    assert q[:10] == list(ch.PROPOSED_TOP10) and q[10:] == [50] * 10


def test_single_participant_and_small_fields():
    assert pts(120)[0] == 150 and pts(80)[0] == 0
    assert pts(130, 110, 105) == [150, 135, 120]  # with < 11 players every recovery is top ten


def test_recoverers_always_rank_above_non_recoverers():
    rnd = random.Random(3)
    for _ in range(200):
        gross = [
            D(rnd.choice([0, 50, 99, 100, 101, 150, 400, 2000])) for _ in range(rnd.randint(1, 30))
        ]
        p = ch.proposed_points(gross)
        for g, x in zip(gross, p, strict=True):
            assert (x == 0) == (g < ch.TARGET)
            assert g < ch.TARGET or x >= ch.RECOVERY_FLOOR


# --------------------------------------------------------- other systems
def test_f1_percentile_and_net():
    g = [D(x) for x in (300, 200, 200, 50)]
    assert ch.f1_points(g) == [25, Fraction(18 + 15, 2), Fraction(33, 2), 12]
    assert ch.percentile_points(g) == [100, 50, 50, 0]
    assert ch.percentile_points([D(10)]) == [100]
    assert ch.net_points(g) == [200, 100, 100, -50]


# ------------------------------------------------------- championship table
def _season(rounds, system="proposed"):
    table = {}
    for entrants, gross in rounds:
        ch.add_round(table, entrants, [D(str(x)) for x in gross], system)
    return table


def test_championship_totals_from_brief():
    # recover every round but never top ten: 10 x 50 = 500
    field = list(range(300, 190, -10))  # 11 players ahead of "steady"
    rounds = [([*range(11), "steady"], [*field, 100])] * 10
    t = _season(rounds)
    assert t["steady"].points == 500 and t["steady"].recoveries == 10
    # win three rounds, fail to recover in seven: 3 x 150 = 450
    rounds = [(["w", "x"], [500, 120])] * 3 + [(["w", "x"], [50, 120])] * 7
    t = _season(rounds)
    assert t["w"].points == 450 and t["w"].qualifying_top10 == 3
    # maximum over ten rounds
    t = _season([(["solo"], [200])] * 10)
    assert t["solo"].points == 1500


def test_championship_tie_break_hierarchy():
    t = {
        "a": ch.Record(Fraction(300), 5, recoveries=4, qualifying_top10=2),
        "b": ch.Record(Fraction(300), 5, recoveries=5, qualifying_top10=0),
        "c": ch.Record(Fraction(300), 5, recoveries=4, qualifying_top10=3),
        "d": ch.Record(Fraction(300), 5, recoveries=4, qualifying_top10=3),
        "e": ch.Record(Fraction(310), 2, recoveries=2, qualifying_top10=2),
    }
    st = {w: pos for pos, w, _ in ch.standings(t)}
    assert st["e"] == 1  # points first
    assert st["b"] == 2  # then recoveries
    assert st["c"] == st["d"] == 3  # then top-ten finishes; still equal: joint
    assert st["a"] == 5


def test_missed_rounds_and_mid_championship_entry_score_zero():
    rounds = [(["a", "b"], [150, 120]), (["a"], [150]), (["a", "b", "late"], [80, 130, 200])]
    t = _season(rounds)
    assert t["b"].entered == 2 and t["b"].points == 135 + 135
    assert t["late"].entered == 1 and t["late"].points == 150
    assert t["a"].points == 150 + 150 + 0


# ---------------------------------------------------------- feasibility
def _cls(o):
    return rs.classify(o.p_market, BROAD60)


def test_max_flow_matches_exact_count_on_random_subpools():
    outs_all = rs.pool_outcomes(POOL)
    fixtures = sorted({o.fixture_id for o in outs_all})
    rnd = random.Random(11)
    cfg = rs.Config("Broad-60", "4/3/2", "40/30/20/10")
    agree = set()
    for size in (6, 8, 9, 10, 12):
        for _ in range(40):
            sub = set(rnd.sample(fixtures, size))
            outs = [o for o in outs_all if o.fixture_id in sub]
            exists = ch.strict_portfolio_exists(outs, _cls)
            assert exists == (rs.count_portfolios(outs, cfg, "p_market") > 0)
            agree.add(exists)
    assert agree == {True, False}  # both outcomes exercised


def test_outcome_counts_alone_are_not_enough():
    # Six fixtures; three of them hold outcomes for every band. Per-bucket
    # outcome counts are A6 B6 C6, but nine distinct fixtures are impossible.
    outs = []
    for f in range(6):
        for k, p in (("home", 0.7), ("draw", 0.5), ("away", 0.3)):
            outs.append(rs.Outcome(f, "1X2", k, p, p, D("2.00")))
    assert not ch.strict_portfolio_exists(outs, _cls)


def test_round_feasibility_minimums():
    league = {f["fixture_id"]: f["league_id"] for f in POOL["fixtures"]}
    outs = rs.pool_outcomes(POOL)
    r = ch.round_feasibility(outs, _cls, league)
    assert r == {
        "eligible_fixtures": 60,
        "eligible_leagues": 6,
        "portfolio_exists": True,
        "opens": True,
    }
    epl = {f for f, lg in league.items() if lg == 39}
    r = ch.round_feasibility([o for o in outs if o.fixture_id in epl], _cls, league)
    assert not r["opens"] and r["eligible_leagues"] == 1  # fewer than 15 fixtures and 3 leagues


def test_goal_model_unchanged():
    from diski9.screener import goal_model as gm

    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.competition_min, gm.GOAL_MODEL_VERSION) == (
        12,
        96,
        20,
        "1.1",
    )  # Goal Model 1.1 (Phase 8 CP2A)
