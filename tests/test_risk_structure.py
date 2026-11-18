# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Phase 6A.1 research: risk-structured Weekly Challenge (research code only)."""

from __future__ import annotations

import itertools
import json
import math
import random
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from diski9.challenge import portfolio as pf
from diski9.research import risk_structure as rs

from .test_app import populated  # noqa: F401

POOLS = Path(__file__).parents[1] / "docs" / "research" / "weekly_challenge_risk"
WEEKEND = json.loads((POOLS / "pool_weekend.json").read_text())
D = Decimal


# ------------------------------------------------------------------- bands
@pytest.mark.parametrize("name", list(rs.BAND_SETS))
def test_bands_are_non_overlapping_and_ordered(name):
    a, b, c = rs.BAND_SETS[name]
    assert c.hi <= b.lo + 1e-12 and b.hi <= a.lo + 1e-12  # C below B below A
    grid = [i / 1000 for i in range(1001)]
    for p in grid:
        assert sum(band.contains(p) for band in (a, b, c)) <= 1, (name, p)


def test_boundary_assignment():
    broad = rs.BAND_SETS["Broad"]
    assert rs.classify(0.65, broad) == 0 and rs.classify(0.95, broad) == 0  # A closed
    assert rs.classify(0.6499, broad) == 1 and rs.classify(0.40, broad) == 1
    assert rs.classify(0.3999, broad) == 2 and rs.classify(0.20, broad) == 2
    assert rs.classify(0.1999, broad) is None and rs.classify(0.951, broad) is None


# ---------------------------------------------------------------- feasibility
def _toy_pool(seed=1, n_fixtures=12):
    rnd = random.Random(seed)
    outs = []
    for f in range(n_fixtures):
        for k in ("home", "draw", "away"):
            p = rnd.uniform(0.15, 0.85)
            outs.append(rs.Outcome(f, "1X2", k, p, p, D(f"{1 / p * 1.05:.2f}")))
    return outs


@pytest.mark.parametrize("sizes", list(rs.SIZES))
def test_portfolio_count_matches_brute_force(sizes):
    outs = _toy_pool(3, 10)
    cfg = rs.Config("Broad", sizes, "30/30/30/10")
    na, nb, nc = cfg.size_tuple
    by = [[o for o in outs if rs.classify(o.p_model, cfg.band_tuple) == i] for i in range(3)]
    brute = 0
    for A in itertools.combinations(by[0], na):
        fa = {o.fixture_id for o in A}
        if len(fa) < na:
            continue
        for B in itertools.combinations([o for o in by[1] if o.fixture_id not in fa], nb):
            fb = {o.fixture_id for o in B}
            if len(fb) < nb:
                continue
            rest = [o for o in by[2] if o.fixture_id not in fa | fb]
            brute += sum(
                1 for C in itertools.combinations(rest, nc) if len({o.fixture_id for o in C}) == nc
            )
    assert rs.count_portfolios(outs, cfg) == brute


# -------------------------------------------------------- portfolio maths
def test_evaluate_matches_phase6a_engine_for_333_at_30_30_30_10():
    """Reuse evidence: the generalised evaluator reproduces the production engine."""
    rnd = random.Random(5)
    for _ in range(20):
        ps = [rnd.uniform(0.1, 0.9) for _ in range(9)]
        odds = [D(rnd.randint(105, 900)) / 100 for _ in range(9)]
        sels = [
            pf.make_selection(f"s{i}", i, p, o)
            for i, (p, o) in enumerate(zip(ps, odds, strict=True))
        ]
        r = pf.evaluate_partition(sels, "012|345|678")
        m = rs.evaluate([[(ps[i], odds[i]) for i in g] for g in ((0, 1, 2), (3, 4, 5), (6, 7, 8))],
                        (30, 30, 30, 10))  # fmt: skip
        assert m.p_recover == pytest.approx(r.p_recover, abs=1e-15)
        assert m.expected == pytest.approx(r.expected_gross, rel=1e-12)
        assert m.p_zero == pytest.approx(r.p_zero, abs=1e-15)
        assert m.max_payout == r.max_gross
        assert list(m.payout_bucket) == [b.payout for b in r.buckets]
        assert [v for v, _ in m.dist] == [o.gross for o in pf.payout_distribution(r)]


@pytest.mark.parametrize("sizes", list(rs.SIZES))
@pytest.mark.parametrize("alloc", list(rs.ALLOCATIONS))
def test_evaluate_invariants_any_size_and_allocation(sizes, alloc):
    rnd = random.Random(hash((sizes, alloc)) % 1000)
    n = rs.SIZES[sizes]
    legs = [[(rnd.uniform(0.1, 0.9), D(rnd.randint(105, 900)) / 100) for _ in range(k)] for k in n]
    stakes = rs.ALLOCATIONS[alloc]
    assert sum(stakes) == 100
    m = rs.evaluate(legs, stakes)
    assert sum(p for _, p in m.dist) == pytest.approx(1.0, abs=1e-12)
    assert sum(m.p_wins) == pytest.approx(1.0, abs=1e-12)
    assert m.p_nine == pytest.approx(math.prod(m.p_bucket))
    assert m.p_wins[3] == pytest.approx(m.p_nine)
    assert m.median <= m.q75 <= m.q90 <= m.max_payout
    assert m.expected == pytest.approx(sum(float(v) * p for v, p in m.dist), rel=1e-12)
    for j, b in enumerate(legs):
        odds = math.prod((x for _, x in b), start=D(1))
        assert m.payout_bucket[j] == pf.round_credits(stakes[j] * odds)  # D-15
    assert m.a_alone_recovers == (m.payout_bucket[0] >= D("100"))


# ----------------------------------------------------------------- builders
@pytest.mark.parametrize("strategy", rs.STRATEGIES)
@pytest.mark.parametrize("bands", ["Broad", "Broad-60", "Broad-55"])
@pytest.mark.parametrize("sizes", list(rs.SIZES))
def test_structured_portfolios_respect_rules_on_real_pool(strategy, bands, sizes):
    outs = rs.pool_outcomes(WEEKEND)
    cfg = rs.Config(bands, sizes, "40/30/20/10")
    picks = rs.build_structured(outs, cfg, strategy, random.Random(1))
    assert picks is not None
    assert [len(b) for b in picks] == list(cfg.size_tuple)
    fixtures = [o.fixture_id for b in picks for o in b]
    assert len(fixtures) == 9 == len(set(fixtures))  # nine distinct fixtures
    for i, b in enumerate(picks):
        assert all(rs.classify(o.p_model, cfg.band_tuple) == i for o in b)


def test_infeasible_configurations_return_none_and_count_zero():
    outs = rs.pool_outcomes(WEEKEND)
    for sizes in rs.SIZES:
        cfg = rs.Config("Conservative", sizes, "30/30/30/10")
        assert rs.count_portfolios(outs, cfg) == 0  # no model outcome reaches 80%
        assert rs.build_structured(outs, cfg, "random", random.Random(0)) is None


def test_free_builder_and_flexible_rules():
    outs = rs.pool_outcomes(WEEKEND)
    picks = rs.build_free(outs, "favourite", random.Random(0))
    assert len({o.fixture_id for o in picks}) == 9
    f1, f2 = rs.FLEX_RULES
    assert f1.ok([0.6] * 4 + [0.4] * 3 + [0.25, 0.2]) and not f1.ok([0.6] * 3 + [0.4] * 6)
    assert not f1.ok([0.6] * 4 + [0.4] * 4 + [0.1])  # floor
    assert f2.ok([0.5] * 3 + [0.2] * 6) and not f2.ok([0.5] * 3 + [0.19] + [0.3] * 5)


# ------------------------------------------------------------ data integrity
def test_real_pool_snapshot_integrity():
    assert WEEKEND["as_of"].startswith("2026-11-17T22:00")
    for f in WEEKEND["fixtures"]:
        by_market = {}
        for o in f["outcomes"]:
            if o["eligible"]:
                assert o["groups"] >= 3 and o["odds"] is not None and o["p_model"] is not None
                by_market.setdefault(o["market"], []).append(o["p_market"])
        for m, ps in by_market.items():
            assert len(ps) == {"1X2": 3, "BTTS": 2, "OU25": 2}[m]
            assert sum(ps) == pytest.approx(1.0, abs=1e-9)  # complete, margin removed


def test_pool_builder_is_read_only(populated):
    from datetime import timedelta

    from diski9.db.schema import forecast_snapshots, odds_quotes, screener_results
    from diski9.research.risk_pool import build_pool

    from .factories import T0

    def counts():
        with populated.connect() as c:
            return [c.execute(select(func.count()).select_from(t)).scalar()
                    for t in (forecast_snapshots, odds_quotes, screener_results)]  # fmt: skip

    before = counts()
    pool = build_pool(populated, T0, T0, T0 + timedelta(days=30))
    assert counts() == before and pool["fixtures"]


def test_goal_model_and_engine_unchanged():
    from diski9.screener import goal_model as gm

    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.m0, gm.GOAL_MODEL_VERSION) == (
        12,
        96,
        30,
        "1.0",
    )
    assert pf.ALLOCATION_VERSION == "30-30-30-10/v1" and pf.ENGINE_VERSION == "portfolio/1.0"
