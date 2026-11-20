"""Phase 6C.5 Stage B: the settlement-to-scoring adapter (pure; no database).

The ranking, points, recovery gating and all-void refunds are the unchanged
``challenge.scoring`` engine; these tests check that authoritative settlement
records reach it correctly and that its decisions are what official weekly results
store (decisions D-15, D-26, D-31, D-32b, D-33, CH-12)."""

from __future__ import annotations

import random
import uuid
from decimal import Decimal

import pytest

from diski9.backend.services import competition as comp
from diski9.challenge import scoring

D = Decimal


def rec(gross: str, basis: str = "settled", complete: bool = True) -> comp.EntryRecord:
    return comp.EntryRecord(uuid.uuid4(), uuid.uuid4(), D(gross), basis, complete)


def score(designation: str, records):
    rr = comp.round_result(uuid.uuid4(), designation, "points-150-75-v2", list(records))
    return rr, scoring.score_round(rr)


def by_gross(s):
    return [(str(x.gross), x.rank, x.points) for x in s.scores]


def test_standard_ranking_and_competition_gaps():
    _, s = score(
        "championship", [rec(g) for g in ("350.00", "350.00", "290.00", "120.00", "99.99")]
    )
    assert by_gross(s) == [
        ("350.00", 1, 150), ("350.00", 1, 150), ("290.00", 3, 125), ("120.00", 4, 120),
        ("99.99", 5, 0),
    ]  # fmt: skip


def test_several_first_places_share_full_points():
    _, s = score("championship", [rec("200.00") for _ in range(4)] + [rec("150.00")])
    assert [x.rank for x in s.scores] == [1, 1, 1, 1, 5]
    assert [x.points for x in s.scores] == [150, 150, 150, 150, 115]


def test_shared_tenth_place_gets_ninety_each_and_the_next_rank_skips():
    grosses = [f"{300 - i}.00" for i in range(9)] + ["150.00"] * 3 + ["140.00"]
    _, s = score("championship", [rec(g) for g in grosses])
    tenth = [x for x in s.scores if x.gross == D("150.00")]
    assert {x.rank for x in tenth} == {10} and {x.points for x in tenth} == {90}
    last = s.scores[-1]
    assert last.rank == 13 and last.points == 75  # rank 11+ with recovery
    assert all(x.qualifying_top10 for x in tenth) and not last.qualifying_top10


def test_recovery_boundary_exactly_100_and_just_below():
    records = [rec(g) for g in ("400.00", "300.00", "250.00", "220.00", "210.00", "205.00",
                                "204.00", "203.00", "202.00", "201.00", "100.00", "99.99",
                                "0.00")]  # fmt: skip
    _, s = score("championship", records)
    row = {str(x.gross): x for x in s.scores}
    assert row["100.00"].rank == 11 and row["100.00"].recovered and row["100.00"].points == 75
    assert row["99.99"].rank == 12 and not row["99.99"].recovered and row["99.99"].points == 0
    assert row["0.00"].rank == 13 and row["0.00"].points == 0  # zero returns stay ranked


def test_no_recoveries_means_no_points_but_ranks_remain():
    _, s = score("championship", [rec(g) for g in ("99.00", "50.00", "50.00", "10.00", "0.00")])
    assert [x.rank for x in s.scores] == [1, 2, 2, 4, 5]
    assert {x.points for x in s.scores} == {0} and not any(x.recovered for x in s.scores)


def test_all_void_entry_is_refunded_unranked_and_others_ranked_as_if_absent():
    refund = rec("100.00", basis="all_void")
    others = [rec(g) for g in ("180.00", "120.00", "110.00", "90.00", "80.00")]
    rr, s = score("championship", [refund, *others])
    r = next(x for x in s.scores if x.participant_id == str(refund.entry_id))
    assert r.refunded and r.rank is None and r.points == 0 and not r.recovered
    assert not r.qualifying_top10 and comp.score_status(s.classification, r) == "void_refunded"
    assert sorted(x.rank for x in s.scores if x.rank) == [1, 2, 3, 4, 5]
    # the refund is the allocation even if a stored settlement gross were different
    odd = comp.round_result(uuid.uuid4(), "championship", "points-150-75-v2",
                            [rec("37.00", basis="all_void"), *others])  # fmt: skip
    assert odd.entries[0].gross == D("100.00")
    assert rr.entries[0].basis is scoring.SettlementBasis.ALL_SELECTIONS_VOID


def test_practice_round_ranks_without_points():
    _, s = score("practice", [rec("300.00"), rec("300.00"), rec("50.00")])
    assert [x.rank for x in s.scores] == [1, 1, 3]
    assert {x.points for x in s.scores} == {0} and not any(x.qualifying_top10 for x in s.scores)
    assert s.scores[0].recovered and not s.scores[2].recovered  # informational
    assert comp.KIND_OF[s.classification] == "practice"


def test_invalidated_round_refunds_everyone_with_no_ranks():
    rr, s = score("void", [rec(g) for g in ("300.00", "12.00", "0.00", "100.00", "101.00")])
    assert {e.gross for e in rr.entries} == {D("100.00")}
    assert all(x.rank is None and x.points == 0 and not x.recovered for x in s.scores)
    assert {comp.score_status(s.classification, x) for x in s.scores} == {"round_void"}


def test_incomplete_settlement_is_never_published():
    with pytest.raises(comp.PublicationRefused, match="completely settled"):
        score("championship", [rec("100.00") for _ in range(4)] + [rec("80.00", complete=False)])


@pytest.mark.parametrize("designation", ["postponed", "", "official"])
def test_unknown_designations_are_refused(designation):
    with pytest.raises(comp.PublicationRefused):
        score(designation, [rec("100.00")])


def test_output_order_is_deterministic_whatever_the_input_order():
    records = [rec(g) for g in ("150.00", "150.00", "150.00", "120.00", "99.00", "99.00")]
    rid = uuid.uuid4()
    first = scoring.score_round(comp.round_result(rid, "championship", "points-150-75-v2", records))
    for seed in range(5):
        shuffled = records[:]
        random.Random(seed).shuffle(shuffled)
        again = scoring.score_round(
            comp.round_result(rid, "championship", "points-150-75-v2", shuffled)
        )
        assert again == first
    assert [x.display_order for x in first.scores] == list(range(1, 7))


def test_precision_is_exact_to_the_cent():
    _, s = score("championship", [rec(g) for g in ("100.01", "100.00", "100.00", "99.99", "1.00")])
    assert [x.rank for x in s.scores] == [1, 2, 2, 4, 5]
    with pytest.raises(scoring.ScoringInputError, match="0.01"):  # never rounded silently
        score("championship", [rec("100.005")] + [rec("1.00") for _ in range(4)])


def test_competitive_classification_must_match_the_locked_count():
    """The adapter never reclassifies a round; the engine refuses an inconsistent
    one (a competitive round needs five valid entries; D-28)."""
    with pytest.raises(scoring.ScoringInputError):
        score("championship", [rec("100.00") for _ in range(4)])
    with pytest.raises(scoring.ScoringInputError):
        score("practice", [rec("100.00") for _ in range(5)])


def test_the_neutral_championship_label_is_only_a_calculation_label():
    rr, s = score("championship", [rec("100.00") for _ in range(5)])
    assert rr.championship_id == comp.UNASSIGNED == s.championship_id
    rr, _ = score("practice", [rec("100.00")])
    assert rr.championship_id is None


def test_streams():
    assert comp.stream_of(True, "beta") == "development"
    assert comp.stream_of(True, "official") == "development"
    assert comp.stream_of(False, "beta") == "beta"
    assert comp.stream_of(False, "official") == "official"
