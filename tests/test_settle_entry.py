"""Settlement of entries and D-32b as pure functions: the adapter over the engine
agrees with independent D-15 / D-32 arithmetic and with the confirmed submission's
eight engine states for every verdict combination (property tests)."""

from __future__ import annotations

import itertools
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.settle import Leg, evaluate_round, settle_entry
from diski9.challenge.structured import evaluate_groups

BUCKETS = ["A"] * 4 + ["B"] * 3 + ["C"] * 2
STAKES = {"A": 40, "B": 30, "C": 20}
odds_st = st.integers(min_value=101, max_value=2500).map(lambda c: Decimal(c) / 100)


def legs_for(odds):
    return [
        Leg(i, 100 + i, "1X2", "HOME", b, o)
        for i, (b, o) in enumerate(zip(BUCKETS, odds, strict=True))
    ]


def q(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def independent(odds, verdicts):
    eff = {b: Decimal(1) for b in "ABC"}
    alive = {b: True for b in "ABC"}
    for b, o, v in zip(BUCKETS, odds, verdicts, strict=True):
        alive[b] &= v != "lost"
        eff[b] *= Decimal("1.00") if v == "void" else o
    g = sum((q(STAKES[b] * eff[b]) for b in "ABC" if alive[b]), Decimal("0.00"))
    return g + (q(10 * eff["A"] * eff["B"] * eff["C"]) if all(alive.values()) else 0)


@settings(max_examples=300, deadline=None)
@given(
    st.lists(odds_st, min_size=9, max_size=9),
    st.lists(st.sampled_from(["won", "lost", "void"]), min_size=9, max_size=9),
)
def test_settlement_equals_independent_arithmetic(odds, verdicts):
    legs = legs_for(odds)
    es = settle_entry(
        legs, {(x.fixture_id, "1X2", "HOME"): v for x, v in zip(legs, verdicts, strict=True)}
    )
    assert es.complete and es.gross == independent(odds, verdicts)
    assert es.all_void == all(v == "void" for v in verdicts)


@settings(max_examples=100, deadline=None)
@given(st.lists(odds_st, min_size=9, max_size=9))
def test_every_win_vector_equals_the_stored_engine_state(odds):
    groups = [[(0.5, o) for b, o in zip(BUCKETS, odds, strict=True) if b == c] for c in "ABC"]
    ev = evaluate_groups(groups, DEFAULT_CONFIG.stakes, DEFAULT_CONFIG.nine_fold_credits,
                         codes=DEFAULT_CONFIG.bucket_codes)  # fmt: skip
    stored = {s.wins: s.gross for s in ev.states}
    legs = legs_for(odds)
    for wins in itertools.product((0, 1), repeat=3):
        verdicts = []
        for b in BUCKETS:
            w = wins["ABC".index(b)]
            verdicts.append("won" if w else "lost")
        es = settle_entry(
            legs, {(x.fixture_id, "1X2", "HOME"): v for x, v in zip(legs, verdicts, strict=True)}
        )
        assert es.gross == stored[wins] and es.win_vector == wins


def test_all_nine_void_returns_exactly_one_hundred():
    legs = legs_for([Decimal("7.77")] * 9)
    es = settle_entry(legs, {(x.fixture_id, "1X2", "HOME"): "void" for x in legs})
    assert es.gross == Decimal("100.00") and es.all_void and es.rank_eligible is False
    assert es.recovered is False


def test_pending_buckets_are_never_zero_and_losses_are_certain():
    legs = legs_for([Decimal("2.00")] * 9)
    v = {(x.fixture_id, "1X2", "HOME"): "won" for x in legs}
    v[(100, "1X2", "HOME")] = "pending"  # Foundation pending
    v[(107, "1X2", "HOME")] = "lost"  # Challenger lost
    es = settle_entry(legs, v)
    accs = {a.code: a for a in es.accumulators}
    assert accs["A"].status == "pending" and accs["A"].payout is None
    assert accs["C"].status == "lost" and accs["C"].payout == Decimal("0.00")
    assert accs["NINE"].status == "lost"
    assert es.gross == Decimal("240.00") and not es.complete and es.recovered is None


def _entry(verdicts):
    legs = legs_for([Decimal("2.00")] * 9)
    return settle_entry(
        legs, {(x.fixture_id, "1X2", "HOME"): v for x, v in zip(legs, verdicts, strict=True)}
    )


@pytest.mark.parametrize(
    ("played_per_entry", "entries", "competitive", "outcome"),
    [
        (5, 1, False, "pass"),  # 10 > 9
        (4, 1, False, "fail_majority"),  # 8 > 9 false
        (5, 5, True, "pass"),
        (5, 4, True, "fail_ranked"),
        (5, 4, False, "pass"),  # practice: no five-entry rule
    ],
)
def test_d32b_integer_thresholds(played_per_entry, entries, competitive, outcome):
    es = [_entry(["won"] * played_per_entry + ["void"] * (9 - played_per_entry))] * entries
    assert evaluate_round(es, competitive=competitive).outcome == outcome


def test_d32b_exactly_half_fails_and_pending_is_not_evaluated():
    half = [_entry(["won"] * 5 + ["void"] * 4), _entry(["won"] * 4 + ["void"] * 5)]
    r = evaluate_round(half, competitive=False)
    assert (r.played, r.total, r.outcome) == (9, 18, "fail_majority")
    pend = [_entry(["pending"] + ["won"] * 8)]
    assert evaluate_round(pend, competitive=False).outcome == "not_evaluated"


def test_d32b_counts_all_void_entries_as_not_rank_eligible():
    es = [_entry(["won"] * 9)] * 4 + [_entry(["void"] * 9)]
    r = evaluate_round(es, competitive=True)
    assert (r.ranked, r.played, r.total, r.outcome) == (4, 36, 45, "fail_ranked")
