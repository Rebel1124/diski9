"""Phase 6B.1: bucket progress stats, probability sources and the 512-state analysis."""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diski9.challenge import analysis as pa
from diski9.challenge.config import BROAD60_432_V1  # explicit: v1 behaviour (A3 4A)
from diski9.challenge.portfolio import round_credits
from diski9.challenge.roundsheet import snapshot_from_research_pool
from diski9.challenge.structured import (
    assess_outcome,
    evaluate_market_and_model,
    make_outcome,
    payout_distribution,
    selection_blocks,
    validate_portfolio,
)

CFG = BROAD60_432_V1  # v1 analysis tests (pinned when A3 became the default, 4C)
D = Decimal
ROOT = Path(__file__).parents[1]
SNAP = snapshot_from_research_pool(
    json.loads((ROOT / "docs/research/weekly_challenge_risk/pool_weekend.json").read_text()),
    "demo",
    {},
    config=BROAD60_432_V1,
)
T0 = datetime(2026, 11, 17, tzinfo=UTC)
COMB = [1, 9, 36, 84, 126, 126, 84, 36, 9, 1]


def oc(fid, p, odds, model=None, outcome="HOME"):
    return make_outcome(fid, "1X2", outcome, p, odds, model if model is not None else p, 5, T0, 39)


def synthetic():
    a = [oc(1, 0.80, "1.20", 0.75), oc(2, 0.70, "1.36", 0.72), oc(3, 0.65, "1.47", 0.60),
         oc(4, 0.62, "1.55", 0.66)]  # fmt: skip
    b = [oc(5, 0.55, "1.75", 0.50), oc(6, 0.48, "2.00", 0.52), oc(7, 0.42, "2.30", 0.45)]
    c = [oc(8, 0.35, "2.75", 0.30), oc(9, 0.25, "3.80", 0.33)]
    return validate_portfolio(a + b + c, T0, config=BROAD60_432_V1)


def random_real_portfolios(n, seed=4):
    rnd = random.Random(seed)
    by = {c: [o for o in SNAP.outcomes if assess_outcome(o, SNAP.snapshot_at, CFG).eligible
              and CFG.classify(o.market_probability) == c] for c in "ABC"}  # fmt: skip
    out = []
    while len(out) < n:
        sel = []
        for c, k in zip("ABC", (4, 3, 2), strict=True):
            for _ in range(k):
                blocks = selection_blocks(sel, SNAP.outcomes, SNAP.snapshot_at, CFG)
                cands = [o for o in by[c] if o.key not in blocks]
                if not cands:
                    break
                sel.append(rnd.choice(cands))
        if len(sel) == 9:
            out.append(
                validate_portfolio(sel, SNAP.snapshot_at, pool=SNAP.outcomes, config=BROAD60_432_V1)
            )
    return out


PORTFOLIOS = [synthetic(), *random_real_portfolios(12)]


# ------------------------------------------------------------- 512 states
@pytest.mark.parametrize("port", PORTFOLIOS)
@pytest.mark.parametrize("source", ["market", "model", "personal"])
def test_512_states_reconcile_with_eight_state_engine(port, source):
    prob = pa.probability_for(
        source, {port.selections[0].key: 0.9} if source == "personal" else None
    )
    cc = pa.correct_count_analysis(port, prob)
    ev = pa.evaluate_with(port, prob)
    assert len(cc.states) == 512 and len({s.correct for s in cc.states}) == 512
    assert [r.combinations for r in cc.rows] == COMB == [math.comb(9, k) for k in range(10)]
    assert math.isclose(sum(s.probability for s in cc.states), 1.0, abs_tol=1e-12)
    assert math.isclose(sum(r.probability for r in cc.rows), 1.0, abs_tol=1e-12)
    probs = [prob(o) for o in port.selections]
    assert math.isclose(cc.expected_correct, sum(probs), rel_tol=1e-12)
    assert math.isclose(cc.expected_gross, ev.expected_gross, rel_tol=1e-12, abs_tol=1e-9)
    assert math.isclose(cc.p_recover, ev.p_recover, rel_tol=1e-12, abs_tol=1e-15)
    assert math.isclose(cc.p_zero, ev.p_zero, rel_tol=1e-12, abs_tol=1e-15)
    # aggregating by payout reproduces the engine's exact payout distribution
    dist = cc.payout_distribution()
    eng = {p.gross: p.probability for p in payout_distribution(ev)}
    assert set(dist) == set(eng)
    for v, p in eng.items():
        assert math.isclose(dist[v], p, rel_tol=1e-12, abs_tol=1e-15)
    # all nine correct = the nine-fold
    top = cc.rows[9]
    assert math.isclose(top.probability, ev.nine_fold.win_probability, rel_tol=1e-12)
    assert top.min_gross == top.max_gross == ev.max_gross
    # payouts follow D-15 rounding: every state gross is a sum of rounded accumulators
    pays = [b.payout for b in ev.buckets]
    for s in cc.states:
        assert s.gross == s.gross.quantize(D("0.01"))
        expect = sum((pays[j] for j, w in enumerate(s.buckets_won) if w), D(0))
        expect += ev.nine_fold.payout if all(s.buckets_won) else 0
        assert s.gross == expect
    # unconditional contributions add up to E[gross]; conditional values are consistent
    assert math.isclose(sum(r.contribution for r in cc.rows), ev.expected_gross, rel_tol=1e-12)
    for r in cc.rows:
        if r.probability > 0:
            assert math.isclose(r.expected_gross * r.probability, r.contribution, rel_tol=1e-9,
                                abs_tol=1e-12)  # fmt: skip
            assert float(r.min_gross) - 1e-9 <= r.expected_gross <= float(r.max_gross) + 1e-9
            assert 0 <= r.p_recover <= 1


def test_payouts_identical_across_sources():
    port = PORTFOLIOS[1]
    evs = pa.evaluate_sources(port, {port.selections[2].key: 0.99})
    grosses = {s: [x.gross for x in ev.states] for s, ev in evs.items()}
    assert grosses["market"] == grosses["model"] == grosses["personal"]
    m, d = evaluate_market_and_model(port)
    assert [s.probability for s in evs["market"].states] == [s.probability for s in m.states]
    assert [s.probability for s in evs["model"].states] == [s.probability for s in d.states]
    # Your View falls back to Diski 9 where the participant made no adjustment
    plain = pa.evaluate_with(port, pa.probability_for("personal", {}))
    assert [s.probability for s in plain.states] == [s.probability for s in d.states]


def test_more_correct_does_not_mean_more_payout():
    port = synthetic()
    cc = pa.correct_count_analysis(port)
    two = [s for s in cc.states if s.n_correct == 2 and s.buckets_won == (False, False, True)]
    six_nothing = [s for s in cc.states if s.n_correct == 6 and s.gross == 0]
    assert two and two[0].gross >= D(100)  # both Challenger picks: a recovery
    assert six_nothing  # six correct spread across buckets, none complete: nothing back
    assert cc.rows[2].max_gross > cc.rows[6].min_gross == 0


def test_conditioning_on_impossible_counts_is_safe():
    sels = [oc(i, 0.9 if i <= 4 else 0.5 if i <= 7 else 0.3, "2.00") for i in range(1, 10)]
    port = validate_portfolio(sels, T0, config=BROAD60_432_V1)
    cc = pa.correct_count_analysis(port, lambda o: 1.0)  # every prediction certain
    assert cc.rows[9].probability == 1.0 and cc.most_likely == 9
    for r in cc.rows[:9]:
        assert r.probability == 0.0 and r.expected_gross is None and r.p_recover is None
    assert cc.expected_correct == 9.0


def test_fraction_reference_for_correct_counts():
    port = synthetic()
    cc = pa.correct_count_analysis(port)
    ps = [Fraction(o.market_probability) for o in port.selections]
    poly = [Fraction(1)]
    for p in ps:  # Poisson-binomial by polynomial multiplication, exact rationals
        poly = [a * (1 - p) + (poly[i - 1] * p if i else 0) for i, a in enumerate(poly + [0])]
    for r, exact in zip(cc.rows, poly, strict=True):
        assert math.isclose(r.probability, float(exact), rel_tol=1e-12, abs_tol=1e-15)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.floats(0.01, 0.99), min_size=9, max_size=9))
def test_property_random_probabilities(ps):
    port = synthetic()
    by = {o.key: p for o, p in zip(port.selections, ps, strict=True)}
    prob = pa.probability_for("personal", by)
    cc = pa.correct_count_analysis(port, prob)
    ev = pa.evaluate_with(port, prob)
    assert math.isclose(cc.p_recover, ev.p_recover, rel_tol=1e-9, abs_tol=1e-12)
    assert math.isclose(cc.expected_gross, ev.expected_gross, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(cc.expected_correct, sum(ps), rel_tol=1e-12)


# ---------------------------------------------------------- bucket progress
def test_bucket_stats_partial_and_complete():
    port = synthetic()
    sel = list(port.selections)
    stats, nine = pa.bucket_stats([], pa.market_probability, config=BROAD60_432_V1)
    assert all(s.selected == 0 and s.combined_probability is None for s in stats)
    assert nine.combined_probability is None and nine.required == 9
    stats, nine = pa.bucket_stats(
        sel[:2] + sel[7:8], config=BROAD60_432_V1
    )  # two Foundation, one Challenger
    a, b, c = stats
    assert (a.selected, a.required, a.complete) == (2, 4, False)
    assert math.isclose(a.combined_probability, 0.80 * 0.70)
    assert a.combined_odds == D("1.20") * D("1.36") and a.payout == round_credits(
        40 * a.combined_odds
    )
    assert b.combined_probability is None and c.selected == 1
    assert nine.selected == 3 and nine.payout == round_credits(
        10 * D("1.20") * D("1.36") * D("2.75")
    )
    stats, nine = pa.bucket_stats(sel, pa.model_probability, config=BROAD60_432_V1)
    ev = pa.evaluate_with(port, pa.model_probability)
    for s, acc in zip(stats, ev.buckets, strict=True):
        assert s.complete and s.payout == acc.payout and s.combined_odds == acc.combined_odds
        assert math.isclose(s.combined_probability, acc.win_probability, rel_tol=1e-12)
    assert nine.payout == ev.nine_fold.payout and nine.complete


def test_probability_sources_never_change_classification_or_odds():
    port = synthetic()
    personal = {o.key: 0.05 for o in port.selections}  # wildly different personal view
    for source in pa.SOURCES:
        stats, _ = pa.bucket_stats(
            port.selections, pa.probability_for(source, personal), config=BROAD60_432_V1
        )
        assert [s.selected for s in stats] == [4, 3, 2]  # buckets come from the market only
    assert [o.reference_odds for o in port.selections] == [
        o.reference_odds for o in synthetic().selections
    ]
    with pytest.raises(ValueError):
        pa.probability_for("crowd")


def test_state_labels():
    assert pa.state_label((0, 0, 0), config=BROAD60_432_V1) == "No buckets complete"
    assert pa.state_label((1, 0, 0), config=BROAD60_432_V1) == "Foundation only"
    assert pa.state_label((1, 0, 1), config=BROAD60_432_V1) == "Foundation + Challenger"
    assert pa.state_label((1, 1, 1), config=BROAD60_432_V1) == "All nine correct"
