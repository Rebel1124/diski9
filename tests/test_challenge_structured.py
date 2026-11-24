"""Phase 6A.3: risk-structured portfolio configuration, validation, feasibility and maths."""

from __future__ import annotations

import ast
import dataclasses
import itertools
import json
import math
import random
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diski9.challenge import config as cf
from diski9.challenge import portfolio as legacy
from diski9.challenge import structured as sx
from diski9.challenge.config import BROAD60_432_V1 as CFG
from diski9.challenge.config import ProbabilitySource as Src
from diski9.challenge.structured import IssueCode
from diski9.research import risk_structure as rs

D = Decimal
ROOT = Path(__file__).parents[1]
POOL = json.loads((ROOT / "docs/research/weekly_challenge_risk/pool_weekend.json").read_text())
SNAP = datetime.fromisoformat(POOL["as_of"])
REG = json.loads((ROOT / "tests/fixtures/challenge/phase5b_regression.json").read_text())


def pool_outcomes(pool=POOL, observed=None):
    """Round-sheet outcomes from the research pool (observation time = pool as_of)."""
    seen = observed or datetime.fromisoformat(pool["as_of"])
    out = []
    for f in pool["fixtures"]:
        for o in f["outcomes"]:
            if o["odds"] is None:
                continue
            out.append(sx.make_outcome(f["fixture_id"], o["market"], o["outcome"], o["p_market"],
                                       o["odds"], o["p_model"], o["groups"], seen, f["league_id"]))  # fmt: skip
    return out


REAL = pool_outcomes()


def oc(fid, p, odds="2.00", model=None, market="1X2", outcome="HOME", groups=5, seen=SNAP, lg=39):
    return sx.make_outcome(fid, market, outcome, p, odds, model if model is not None else p,
                           groups, seen, lg)  # fmt: skip


def sample_portfolio():
    """Four Foundation, three Balanced, two Challenger picks on nine fixtures."""
    a = [oc(1, 0.80, "1.20", 0.75), oc(2, 0.70, "1.36", 0.72), oc(3, 0.65, "1.47", 0.60),
         oc(4, 0.62, "1.55", 0.66)]  # fmt: skip
    b = [oc(5, 0.55, "1.75", 0.50), oc(6, 0.48, "2.00", 0.52), oc(7, 0.42, "2.30", 0.45)]
    c = [oc(8, 0.35, "2.75", 0.30), oc(9, 0.25, "3.80", 0.33)]
    return a + b + c


# ------------------------------------------------------------ configuration
def test_approved_configuration():
    assert CFG.version == "broad60-432-v1"
    assert CFG.bucket_codes == ("A", "B", "C")
    assert [b.name for b in CFG.buckets] == ["Foundation", "Balanced", "Challenger"]
    assert CFG.sizes == (4, 3, 2) and CFG.stakes == (40, 30, 20) and CFG.nine_fold_credits == 10
    assert CFG.nine_fold_name == "The Diski 9" and CFG.recovery_target == D("100.00")
    assert cf.get_config("broad60-432-v1") is CFG
    with pytest.raises(dataclasses.FrozenInstanceError):
        CFG.nine_fold_credits = 20  # type: ignore[misc]


def test_odds_requirements_equal_existing_consensus_rules():
    from diski9.odds.consensus import ConsensusRules

    r = ConsensusRules()
    assert CFG.odds.min_bookmaker_groups == r.min_bookmakers == 3
    assert CFG.odds.max_quote_age == r.max_quote_age == timedelta(hours=24)
    assert (CFG.opening.min_eligible_fixtures, CFG.opening.min_eligible_leagues) == (15, 3)


def _variant(**kw):
    base = dict(version="t-v1", buckets=CFG.buckets, nine_fold_name="N", nine_fold_credits=10)
    base.update(kw)
    return cf.ChallengeConfig(**base)


@pytest.mark.parametrize(
    "kw, match",
    [
        ({"version": ""}, "version"),
        ({"version": " x"}, "version"),
        ({"buckets": ()}, "bucket"),
        ({"nine_fold_credits": 0}, "nine_fold_credits"),
        ({"nine_fold_credits": 20}, "Allocated"),
        ({"total_credits": 90}, "100"),
        ({"required_selections": 8}, "9 selections"),
        ({"classification_source": Src.MODEL}, "market"),
        ({"supported_sources": (Src.MODEL,)}, "supported"),
        ({"recovery_target": D("90.00")}, "recovery_target"),
    ],
)
def test_invalid_configurations(kw, match):
    with pytest.raises(cf.ConfigError, match=match):
        _variant(**kw)


def _buckets(*specs):
    return tuple(cf.BucketSpec(c, c, cf.ProbabilityBand(*band), n, s) for c, band, n, s in specs)


def test_bucket_and_band_validation():
    ok = (("A", (0.6, 0.95, True, True), 4, 40), ("B", (0.4, 0.6), 3, 30), ("C", (0.2, 0.4), 2, 20))
    _variant(buckets=_buckets(*ok))
    bad_overlap = (("A", (0.55, 0.95, True, True), 4, 40), *ok[1:])
    with pytest.raises(cf.ConfigError, match="overlap"):
        _variant(buckets=_buckets(*bad_overlap))
    touching_both_inclusive = (("A", (0.6, 0.95, True, True), 4, 40),
                               ("B", (0.4, 0.6, True, True), 3, 30), ok[2])  # fmt: skip
    with pytest.raises(cf.ConfigError, match="overlap"):
        _variant(buckets=_buckets(*touching_both_inclusive))
    with pytest.raises(cf.ConfigError, match="sum"):
        _variant(buckets=_buckets(ok[0], ok[1], ("C", (0.2, 0.4), 3, 20)))
    with pytest.raises(cf.ConfigError, match="positive integer"):
        _variant(buckets=_buckets(ok[0], ok[1], ("C", (0.2, 0.4), True, 20)))
    with pytest.raises(cf.ConfigError, match="positive integer"):
        _variant(buckets=_buckets(ok[0], ok[1], ("C", (0.2, 0.4), 2, 0)))
    with pytest.raises(cf.ConfigError, match="unique"):
        _variant(buckets=_buckets(ok[0], ok[1], ("A", (0.2, 0.4), 2, 20)))
    for band in ((0.5, 0.4), (-0.1, 0.2), (0.2, 1.1), (float("nan"), 0.3)):
        with pytest.raises(cf.ConfigError):
            cf.ProbabilityBand(*band)


def test_registry_refuses_a_changed_meaning_for_a_version():
    other = _variant(version="broad60-432-v1", nine_fold_name="Different")
    with pytest.raises(cf.ConfigError, match="already registered"):
        cf.register_config(other)
    assert cf.register_config(CFG) is CFG
    with pytest.raises(cf.ConfigError, match="Unknown"):
        cf.get_config("nope")


# ----------------------------------------------------------- classification
@pytest.mark.parametrize(
    "p, bucket",
    [
        (0.95, "A"), (0.60, "A"), (0.80, "A"),
        (0.5999999999999999, "B"), (0.40, "B"), (0.55, "B"),
        (0.3999999999999999, "C"), (0.20, "C"),
        (0.19999999999999998, None), (0.9500000000000001, None), (0.0, None), (1.0, None),
    ],
)  # fmt: skip
def test_exact_boundaries(p, bucket):
    assert sx.classify_probability(p, config=CFG) == bucket


def test_boundary_neighbours_use_full_precision():
    for edge, below, above in ((0.2, None, "C"), (0.4, "C", "B"), (0.6, "B", "A"),
                               (0.95, "A", None)):  # fmt: skip
        assert sx.classify_probability(math.nextafter(edge, 0), config=CFG) == below
        assert sx.classify_probability(math.nextafter(edge, 1), config=CFG) == above
    # 0.59996 displays as "60.0%" but is Balanced; display rounding never classifies
    assert f"{0.59996:.1%}" == "60.0%" and sx.classify_probability(0.59996, config=CFG) == "B"


# ------------------------------------------------------------ input checks
@pytest.mark.parametrize(
    "kw, match",
    [
        ({"market_probability": 1.2}, "within"),
        ({"market_probability": float("nan")}, "within"),
        ({"market_probability": True}, "number"),
        ({"model_probability": -0.1}, "within"),
        ({"reference_odds": 2.0}, "float"),
        ({"reference_odds": "1.00"}, "within"),
        ({"reference_odds": "abc"}, "number"),
        ({"reference_odds": "Infinity"}, "within"),
        ({"market": "BTTS"}, "does not belong"),
        ({"market": "XX"}, "unknown"),
        ({"fixture_id": ""}, "fixture_id"),
        ({"fixture_id": None}, "fixture_id"),
        ({"bookmaker_groups": -1}, "bookmaker_groups"),
        ({"latest_observation_at": datetime(2026, 11, 17)}, "timezone"),
        ({"league_id": "39"}, "league_id"),
    ],
)
def test_invalid_outcomes_rejected(kw, match):
    base = dict(fixture_id=1, market="1X2", outcome="HOME", market_probability=0.5,
                reference_odds="1.90", model_probability=0.5, bookmaker_groups=4,
                latest_observation_at=SNAP, league_id=39)  # fmt: skip
    base.update(kw)
    with pytest.raises(sx.ChallengeInputError, match=match):
        sx.make_outcome(**base)


def test_assessment_odds_rules_and_ranges():
    codes = lambda o: {i.code for i in sx.assess_outcome(o, SNAP, config=CFG).issues}  # noqa: E731
    assert codes(oc(1, 0.5)) == set()
    assert codes(oc(1, 0.5, groups=2)) == {IssueCode.ODDS_TOO_FEW_GROUPS}
    assert codes(oc(1, 0.5, seen=SNAP - timedelta(hours=24))) == set()  # exactly 24 h is fresh
    assert codes(oc(1, 0.5, seen=SNAP - timedelta(hours=24, seconds=1))) == {IssueCode.ODDS_STALE}
    assert codes(oc(1, 0.5, seen=SNAP + timedelta(seconds=1))) == {IssueCode.ODDS_STALE}
    no_time = sx.make_outcome(1, "1X2", "HOME", 0.5, "2.00", 0.5, 5, None)
    assert codes(no_time) == {IssueCode.ODDS_MISSING_TIMESTAMP}
    assert codes(oc(1, 0.1)) == {IssueCode.PROBABILITY_BELOW_RANGE}
    assert codes(oc(1, 0.97)) == {IssueCode.PROBABILITY_ABOVE_RANGE}
    with pytest.raises(sx.ChallengeInputError, match="timezone"):
        sx.assess_outcome(oc(1, 0.5), datetime(2026, 11, 17), config=CFG)


# ----------------------------------------------------------- partial progress
def test_progress_empty_partial_and_complete():
    p = sx.portfolio_progress([], SNAP, config=CFG)
    assert p.selected == {"A": 0, "B": 0, "C": 0} and p.remaining == {"A": 4, "B": 3, "C": 2}
    assert p.total_selected == 0 and p.total_required == 9 and not p.is_complete and p.is_valid
    assert p.can_complete is None
    sel = sample_portfolio()
    p = sx.portfolio_progress(sel[:5], SNAP, config=CFG)
    assert p.selected == {"A": 4, "B": 1, "C": 0} and p.remaining == {"A": 0, "B": 2, "C": 2}
    assert [i.code for i in p.issues] == [IssueCode.INCOMPLETE]
    p = sx.portfolio_progress(sel, SNAP, config=CFG)
    assert p.is_complete and p.issues == () and p.total_selected == 9


def test_progress_reports_conflicts():
    sel = sample_portfolio()
    dup_fixture = sel[:8] + [oc(1, 0.30, market="BTTS", outcome="BTTS_YES")]
    p = sx.portfolio_progress(dup_fixture, SNAP, config=CFG)
    assert p.issues_of(IssueCode.DUPLICATE_FIXTURE) and not p.is_valid and not p.is_complete
    p = sx.portfolio_progress(sel + [sel[0]], SNAP, config=CFG)
    assert p.issues_of(IssueCode.DUPLICATE_OUTCOME)
    over = sel[:4] + [oc(10, 0.9, "1.10")] + sel[4:8]
    p = sx.portfolio_progress(over, SNAP, config=CFG)
    assert p.issues_of(IssueCode.BUCKET_OVER_CAPACITY)[0].bucket == "A"
    assert p.selected["A"] == 5 and p.remaining["A"] == 0
    p = sx.portfolio_progress(sel[:8] + [oc(9, 0.15, "6.00")], SNAP, config=CFG)
    assert p.issues_of(IssueCode.PROBABILITY_BELOW_RANGE) and p.selected["C"] == 1
    p = sx.portfolio_progress(sel[:8] + [oc(9, 0.25, "3.80", groups=1)], SNAP, config=CFG)
    assert p.issues_of(IssueCode.ODDS_TOO_FEW_GROUPS)


def test_partial_feasibility_against_a_pool():
    pool = sample_portfolio() + [oc(20, 0.3, "3.10"), oc(21, 0.5, "1.95")]
    p = sx.portfolio_progress(pool[:3], SNAP, pool=pool, config=CFG)
    assert p.can_complete is True
    # Using both Challenger-capable fixtures as Balanced/other picks blocks completion:
    blockers = [oc(8, 0.35, "2.75"), oc(9, 0.25, "3.80"), oc(20, 0.3, "3.10")]
    small = sample_portfolio()[:7] + blockers
    p = sx.portfolio_progress(
        sample_portfolio()[:4], SNAP, pool=small[:7] + blockers[:1], config=CFG
    )
    assert p.can_complete is False and p.issues_of(IssueCode.CANNOT_COMPLETE)
    off_sheet = [oc(99, 0.7, "1.40")]
    p = sx.portfolio_progress(off_sheet, SNAP, pool=pool, config=CFG)
    assert p.issues_of(IssueCode.NOT_IN_POOL) and p.can_complete is False


def test_incomplete_or_invalid_portfolios_never_evaluate():
    with pytest.raises(sx.PortfolioValidationError) as e:
        sx.validate_portfolio(sample_portfolio()[:8], SNAP, config=CFG)
    assert e.value.issues[0].code is IssueCode.INCOMPLETE
    with pytest.raises(sx.PortfolioValidationError):
        sx.evaluate_portfolio(sample_portfolio())  # raw selections are not a portfolio


def test_buckets_are_derived_not_chosen():
    sel = sample_portfolio()
    port = sx.validate_portfolio(list(reversed(sel)), SNAP, config=CFG)
    assert [len(b) for b in port.buckets] == [4, 3, 2]
    assert all(CFG.classify(o.market_probability) == c
               for c, b in zip("ABC", port.buckets, strict=True) for o in b)  # fmt: skip


# ----------------------------------------------------------- feasibility
def _brute_exists(outs):
    cfg = rs.Config("Broad-60", "4/3/2", "40/30/20/10")
    research = [rs.Outcome(o.fixture_id, str(o.market), str(o.outcome), o.model_probability,
                           o.market_probability, o.reference_odds) for o in outs]  # fmt: skip
    return rs.count_portfolios(research, cfg, "p_market") > 0


def test_exact_feasibility_matches_exhaustive_count():
    fixtures = sorted({o.fixture_id for o in REAL})
    rnd = random.Random(7)
    seen = set()
    for size in (6, 8, 9, 10, 12):
        for _ in range(30):
            sub = set(rnd.sample(fixtures, size))
            outs = [o for o in REAL if o.fixture_id in sub]
            got = sx.portfolio_feasible(outs, SNAP, config=CFG)
            assert got == _brute_exists(
                [o for o in outs if sx.assess_outcome(o, SNAP, config=CFG).eligible]
            )
            seen.add(got)
    assert seen == {True, False}


def test_multi_band_fixtures_fill_only_one_slot():
    outs = []
    for f in range(6):  # each fixture has an A, a B and a C outcome
        outs += [oc(f, 0.7, outcome="HOME"), oc(f, 0.5, outcome="DRAW"), oc(f, 0.3, outcome="AWAY")]
    assert not sx.portfolio_feasible(outs, SNAP, config=CFG)  # six fixtures cannot hold nine picks
    for f in range(6, 9):
        outs.append(oc(f, 0.7))
    assert sx.portfolio_feasible(outs, SNAP, config=CFG)


def test_round_opening_report_on_real_pool():
    r = sx.round_opening_report(REAL, SNAP, config=CFG)
    assert r.eligible_fixtures == 60 and r.eligible_leagues == 6 and r.portfolio_feasible
    assert r.opens and sum(r.eligible_outcomes_by_bucket.values()) == r.eligible_outcomes
    epl = [o for o in REAL if o.league_id == 39]
    r = sx.round_opening_report(epl, SNAP, config=CFG)
    assert not r.opens and not r.checks["min_eligible_leagues"]
    late = sx.round_opening_report(REAL, SNAP + timedelta(hours=25), config=CFG)  # odds now stale
    assert late.eligible_outcomes == 0 and not late.opens


# ----------------------------------------------------------- mathematics
def _fraction_reference(port, src):
    """Independent exact-rational reference for P(recover) and E[gross]."""
    buckets = [[(Fraction(o.probability(src)), o.reference_odds) for o in b] for b in port.buckets]
    stakes = (40, 30, 20)
    pay = [sx.round_credits(s * math.prod((o for _, o in b), start=D(1)))
           for s, b in zip(stakes, buckets, strict=True)]  # fmt: skip
    pay9 = sx.round_credits(10 * math.prod((o for b in buckets for _, o in b), start=D(1)))
    P = [math.prod(p for p, _ in b) for b in buckets]
    rec, exp = Fraction(0), Fraction(0)
    for w in itertools.product((0, 1), repeat=3):
        pr = math.prod(P[j] if w[j] else 1 - P[j] for j in range(3))
        g = sum((pay[j] for j in range(3) if w[j]), D(0)) + (pay9 if all(w) else 0)
        rec += pr if g >= D(100) else 0
        exp += pr * Fraction(g)
    return float(rec), float(exp)


def test_sample_portfolio_metrics_and_eight_states():
    port = sx.validate_portfolio(sample_portfolio(), SNAP, config=CFG)
    mk, md = sx.evaluate_market_and_model(port)
    assert len(mk.states) == 8 and [s.wins for s in mk.states] == list(
        itertools.product((0, 1), repeat=3)
    )
    a, b, c = mk.buckets
    assert (a.stake, b.stake, c.stake, mk.nine_fold.stake) == (40, 30, 20, 10)
    assert a.combined_odds == D("1.20") * D("1.36") * D("1.47") * D("1.55")
    assert mk.nine_fold.combined_odds == a.combined_odds * b.combined_odds * c.combined_odds
    assert a.payout == sx.round_credits(40 * a.combined_odds)
    for s in mk.states:  # nine-fold pays only when all three buckets win
        base = sum((x.payout for x, w in zip(mk.buckets, s.wins, strict=True) if w), D(0))
        assert s.gross == base + (mk.nine_fold.payout if all(s.wins) else 0)
    assert mk.max_gross == a.payout + b.payout + c.payout + mk.nine_fold.payout
    assert math.isclose(mk.nine_fold.win_probability,
                        a.win_probability * b.win_probability * c.win_probability)  # fmt: skip
    for ev, src in ((mk, Src.MARKET), (md, Src.MODEL)):
        rec, exp = _fraction_reference(port, src)
        assert math.isclose(ev.p_recover, rec, rel_tol=1e-12)
        assert math.isclose(ev.expected_gross, exp, rel_tol=1e-12)
        assert math.isclose(ev.expected_net, exp - 100, rel_tol=1e-9, abs_tol=1e-9)
        p_none = math.prod(1 - x.win_probability for x in ev.buckets)
        assert math.isclose(ev.p_zero, p_none, rel_tol=1e-12)
    assert [s.gross for s in mk.states] == [s.gross for s in md.states]  # same payouts
    assert mk.p_recover != md.p_recover and mk.source is Src.MARKET and md.source is Src.MODEL


def test_payout_distribution_contract():
    port = sx.validate_portfolio(sample_portfolio(), SNAP, config=CFG)
    for ev in sx.evaluate_market_and_model(port):
        dist = ev.distribution()
        assert math.isclose(sum(p.probability for p in dist), 1.0, abs_tol=1e-12)
        assert dist[0].gross == 0 and dist[0].at_least == 1.0 and ev.at_least(0) == 1.0
        assert all(x.at_least >= y.at_least for x, y in zip(dist, dist[1:], strict=False))
        assert ev.at_least(D("100.00")) == ev.p_recover == ev.at_least(100)
        for p in dist:  # attainable payouts are included at the threshold
            assert ev.at_least(p.gross) == p.at_least >= p.probability
        assert ev.at_least(ev.max_gross + D("0.01")) == 0.0
        with pytest.raises(sx.ChallengeInputError):
            ev.at_least(-1)
        with pytest.raises(sx.ChallengeInputError):
            ev.at_least(100.0)


def test_equal_payout_states_are_aggregated():
    legs = [[(0.5, D("1.00"))] * 4, [(0.5, D("4.00"))] * 3, [(0.5, D("2.00"))] * 2]
    ev = sx.evaluate_groups(legs, (40, 30, 20), 10)
    # 40 x 1.00 = 40 and 20 x 2^2 = 80 ... build a deliberate tie instead:
    tie = sx.evaluate_groups([[(0.5, D("1.50"))], [(0.5, D("2.00"))], [(0.5, D("3.00"))]],
                             (40, 30, 20), 10)  # fmt: skip
    dist = sx.payout_distribution(tie)  # A pays 60, B pays 60, C pays 60
    sixty = next(p for p in dist if p.gross == D("60.00"))
    assert len(sixty.states) == 3 and math.isclose(sixty.probability, 3 / 8)
    assert len(dist) < 8 and math.isclose(sum(p.probability for p in sx.payout_distribution(ev)), 1)


def test_half_up_rounding_and_recovery_threshold():
    # 40 x 2.5000125 = 100.0005 -> 100.00 (recovers); 40 x 2.4998625 = 99.9945 -> 99.99
    ev = sx.evaluate_groups([[(0.5, D("2.5000125"))], [(0.1, D("1.01"))], [(0.1, D("1.01"))]],
                            (40, 30, 20), 10)  # fmt: skip
    assert ev.buckets[0].payout == D("100.00") and ev.buckets[0].recovers_alone
    ev2 = sx.evaluate_groups([[(0.5, D("2.4998625"))], [(0.1, D("1.01"))], [(0.1, D("1.01"))]],
                             (40, 30, 20), 10)  # fmt: skip
    assert ev2.buckets[0].payout == D("99.99") and not ev2.buckets[0].recovers_alone
    assert sx.round_credits(D("0.005")) == D("0.01") and sx.round_credits(D("0.0049")) == D("0.00")
    # 40 x 1.250125 = 50.005 -> 50.01 and 30 x 1.6664 = 49.992 -> 49.99: the rounded sum is
    # exactly 100.00 (unrounded 99.997), so the state recovers under D-15
    ev3 = sx.evaluate_groups([[(1.0, D("1.250125"))], [(1.0, D("1.6664"))], [(0.0, D("1.01"))]],
                             (40, 30, 20), 10)  # fmt: skip
    assert ev3.buckets[0].payout + ev3.buckets[1].payout == D("100.00")
    assert ev3.p_recover == 1.0


def test_matches_research_reference_on_real_pool_portfolios():
    rnd = random.Random(42)
    by_bucket = {c: [o for o in REAL if sx.assess_outcome(o, SNAP, config=CFG).eligible
                     and CFG.classify(o.market_probability) == c] for c in "ABC"}  # fmt: skip
    for _ in range(50):
        used, sel = set(), []
        for c, n in zip("ABC", (4, 3, 2), strict=True):
            cands = [o for o in by_bucket[c] if o.fixture_id not in used]
            for o in rnd.sample(cands, n):
                sel.append(o)
                used.add(o.fixture_id)
            if len({o.fixture_id for o in sel}) != len(sel):
                break
        if len({o.fixture_id for o in sel}) != 9:
            continue
        port = sx.validate_portfolio(sel, SNAP, pool=REAL, config=CFG)
        for src in (Src.MARKET, Src.MODEL):
            ev = sx.evaluate_portfolio(port, src)
            ref = rs.evaluate([[(o.probability(src), o.reference_odds) for o in b]
                               for b in port.buckets], (40, 30, 20, 10))  # fmt: skip
            assert math.isclose(ev.p_recover, ref.p_recover, rel_tol=1e-12, abs_tol=1e-15)
            assert math.isclose(ev.expected_gross, ref.expected, rel_tol=1e-12)
            assert ev.max_gross == ref.max_payout and ev.p_zero == pytest.approx(ref.p_zero)


# ------------------------------------------------------- legacy regression
@pytest.mark.parametrize("precision", [legacy.Precision.SETTLEMENT, legacy.Precision.EXACT])
def test_generalised_evaluator_reproduces_phase6a_exactly(precision):
    n = 0
    for slate in REG["slates"]:
        sels = [legacy.make_selection(x["selection_id"], x["fixture_id"], x["p"], x["odds"])
                for x in slate["selections"]]  # fmt: skip
        for part in legacy.partitions():
            old = legacy.evaluate_partition(sels, part, precision)
            groups = [[(sels[i].probability, sels[i].odds) for i in g] for g in part]
            new = sx.evaluate_groups(groups, (30, 30, 30), 10, D("100.00"), precision,
                                     nine_fold_legs=[(s.probability, s.odds) for s in sels])  # fmt: skip
            assert [(s.wins, s.probability, s.gross) for s in new.states] == [
                (s.wins, s.probability, s.gross) for s in old.states
            ]
            for nb, ob in zip(new.buckets, old.buckets, strict=True):
                assert (nb.combined_odds, nb.win_probability, nb.payout, nb.recovers_alone) == (
                    ob.combined_odds,
                    ob.win_probability,
                    ob.payout,
                    ob.recovers_alone,
                )
            assert (new.nine_fold.combined_odds, new.nine_fold.win_probability,
                    new.nine_fold.payout) == (old.nine_fold.combined_odds,
                                              old.nine_fold.win_probability, old.nine_fold.payout)  # fmt: skip
            assert new.p_recover == old.p_recover and new.p_zero == old.p_zero
            assert new.expected_gross == old.expected_gross and new.max_gross == old.max_gross
            assert new.p_profit == old.p_profit
            n += 1
    assert n == 17 * 280


# ------------------------------------------------------------- properties
leg = st.tuples(st.floats(0.01, 0.99), st.decimals("1.01", "20.00", places=2))


@settings(max_examples=150, deadline=None)
@given(st.lists(leg, min_size=4, max_size=4), st.lists(leg, min_size=3, max_size=3),
       st.lists(leg, min_size=2, max_size=2))  # fmt: skip
def test_distribution_properties_for_random_portfolios(a, b, c):
    ev = sx.evaluate_groups([a, b, c], (40, 30, 20), 10)
    dist = sx.payout_distribution(ev)
    assert math.isclose(sum(p.probability for p in dist), 1.0, abs_tol=1e-12)
    assert dist[0].at_least == 1.0
    assert all(x.at_least >= y.at_least for x, y in zip(dist, dist[1:], strict=False))
    assert sx.probability_at_least(ev, D("100.00")) == ev.p_recover
    assert math.isclose(ev.expected_gross, sum(float(p.gross) * p.probability for p in dist),
                        rel_tol=1e-9, abs_tol=1e-9)  # fmt: skip
    assert ev.max_gross == dist[-1].gross and all(s.gross >= 0 for s in ev.states)
    assert 0 <= ev.p_zero <= 1 and ev.p_recover <= 1


# --------------------------------------------------------------- hygiene
def test_engine_modules_are_pure_and_offline():
    allowed = {"__future__", "itertools", "math", "collections.abc", "dataclasses", "decimal",
               "enum", "datetime", "hashlib", "json", "diski9.api_football.markets",
               "diski9.challenge.config", "diski9.challenge.portfolio"}  # fmt: skip
    for mod in (cf, sx):
        tree = ast.parse(Path(mod.__file__).read_text())
        names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert names <= allowed, (mod.__name__, names - allowed)
    tree = ast.parse(Path(sx.__file__).read_text())  # no partition / frontier API exposed
    defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not defs & {"partitions", "evaluate_all", "efficient_mask", "recommend"}


def test_goal_model_unchanged():
    from diski9.screener import goal_model as gm

    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.m0, gm.GOAL_MODEL_VERSION) == (
        12,
        96,
        30,
        "1.0",
    )
