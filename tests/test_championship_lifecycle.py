"""Phase 6C.5 Stage C: championship naming, round roles and deadline-order
assignment with slot reservation (pure; no database). Decisions CH-02, CH-03."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from diski9.backend.services import championships as ch
from diski9.challenge import scoring

T0 = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)


def fact(i: int, role: str = "pending", published: datetime | None = None) -> ch.RoundFact:
    d = T0 + timedelta(days=7 * i)
    return ch.RoundFact(uuid.UUID(int=i + 1), d + timedelta(days=1), published or d, role)


# ------------------------------------------------------------------ naming
def test_names_use_the_sast_month_of_publication():
    assert ch.base_name(datetime(2026, 11, 28, 6, 0, tzinfo=UTC))[1] == "Championship Nov-26"
    # 31 Oct 21:30 UTC is 23:30 SAST (October); 22:30 UTC is 00:30 on 1 Nov SAST
    d, n = ch.base_name(datetime(2026, 10, 31, 21, 30, tzinfo=UTC))
    assert (d.isoformat(), n) == ("2026-10-31", "Championship Oct-26")
    d, n = ch.base_name(datetime(2026, 10, 31, 22, 30, tzinfo=UTC))
    assert (d.isoformat(), n) == ("2026-11-01", "Championship Nov-26")
    assert ch.base_name(datetime(2027, 1, 1, 0, 0, tzinfo=UTC))[1] == "Championship Jan-27"
    assert ch.base_name(datetime(2026, 12, 31, 22, 0, tzinfo=UTC))[1] == "Championship Jan-27"


def test_same_month_collisions_get_suffixes():
    assert ch.unique_name("Championship Nov-26", []) == "Championship Nov-26"
    assert ch.unique_name("Championship Nov-26", ["Championship Nov-26"]) == (
        "Championship Nov-26 (2)"
    )
    names = ["Championship Nov-26", "Championship Nov-26 (2)", "Championship Dec-26"]
    assert ch.unique_name("Championship Nov-26", names) == "Championship Nov-26 (3)"
    assert ch.unique_name("Championship Dec-26", names) == "Championship Dec-26 (2)"


# ------------------------------------------------------------------ roles
def test_roles_from_authoritative_state():
    assert ch.role_of("open", None, None) == "pending"
    assert ch.role_of("locked", "championship", None) == "pending"
    assert ch.role_of("locked", "practice", None) == "practice"  # released at the lock
    assert ch.role_of("settling", "championship", None) == "pending"
    assert ch.role_of("final", "championship", "championship") == "counted"
    assert ch.role_of("final", "championship", "void") == "void"
    assert ch.role_of("final", "practice", "void") == "practice"  # a void practice round
    assert ch.role_of("final", "championship", None) == "pending"  # final, not yet published
    assert ch.role_of("settling", "championship", "championship") == "counted"  # reopened
    assert ch.role_of("postponed", None, None) == "void"
    assert ch.role_of("open", None, "championship") == "pending"  # only final/reopened count


# ------------------------------------------------------------------ assignment
def plan(facts, champs=None, required=10):
    champs = [] if champs is None else champs
    return ch.plan_assignments(facts, champs, required), champs


def test_first_round_creates_the_first_championship_named_from_its_publication():
    p, champs = plan([fact(0)])
    assert len(p.created) == 1 and champs[0].name == "Championship Nov-26"
    assert champs[0].ordinal == 1 and p.assignments[0][0] == fact(0).round_id


def test_rounds_join_at_publication_while_slots_remain_then_wait():
    facts = [fact(i) for i in range(12)]
    p, champs = plan(facts)
    assert len(champs) == 1 and len(p.assignments) == 10
    assert p.waiting == tuple(f.round_id for f in facts[10:])  # last slots reserved


def test_practice_and_void_release_reserved_slots():
    facts = [fact(i) for i in range(10)] + [fact(10)]
    facts[3] = fact(3, "practice")
    facts[5] = fact(5, "void")
    p, champs = plan(facts)
    assert len(champs) == 1 and not p.waiting and len(p.assignments) == 11


def test_waiting_round_starts_the_next_championship_when_the_last_slot_counts():
    facts = [fact(i, "counted") for i in range(9)] + [fact(9), fact(10)]
    p, champs = plan(facts)
    assert p.waiting == (fact(10).round_id,)
    # the reserved tenth round becomes counted: the open championship completes
    p2 = ch.plan_assignments(
        [*facts[:9], fact(9, "counted"), fact(10)],
        [ch.ChampModel(champs[0].key, 1, champs[0].name, champs[0].start_date, 10,
                       {f.round_id: "counted" for f in facts[:10]})],
    )  # fmt: skip
    (new,) = p2.created
    assert new.ordinal == 2 and p2.assignments == ((fact(10).round_id, new),)
    assert len(p2.newly_fixed) == 1 and p2.newly_fixed[0].fixed


def test_waiting_round_joins_the_open_championship_when_the_reserved_slot_is_void():
    facts = [fact(i, "counted") for i in range(9)] + [fact(9, "void"), fact(10, "counted")]
    p, champs = plan(facts)
    assert len(champs) == 1 and champs[0].counted == 10 and not p.waiting


def test_later_round_finalising_first_never_jumps_the_queue():
    # round 9 (the last slot) is still pending; round 10 is already final and valid
    facts = [fact(i, "counted") for i in range(9)] + [fact(9), fact(10, "counted")]
    p, champs = plan(facts)
    assert p.waiting == (fact(10).round_id,) and champs[0].counted == 9


def test_first_associated_round_names_the_championship_even_if_practice():
    first = fact(10, "practice", published=datetime(2026, 11, 28, 6, tzinfo=UTC))
    counted = [fact(i, "counted") for i in range(10)]
    p, champs = plan([*counted, first, fact(11, "counted", datetime(2026, 12, 5, 6, tzinfo=UTC))])
    assert [c.name for c in champs] == ["Championship Nov-26", "Championship Nov-26 (2)"]
    assert champs[1].roles == {first.round_id: "practice", fact(11).round_id: "counted"}


def test_more_than_ten_weeks_and_no_more_than_ten_counted():
    facts = []
    for i in range(30):
        facts.append(fact(i, "practice" if i % 3 == 0 else "counted"))
    p, champs = plan(facts)
    assert [c.counted for c in champs] == [10, 10]
    assert all(c.counted <= 10 for c in champs)
    assert champs[0].fixed and not champs[1].fixed


def test_planning_is_idempotent():
    facts = [fact(i, "counted") for i in range(13)]
    p, champs = plan(facts)
    again = ch.plan_assignments(facts, champs)
    assert again.assignments == () and again.created == ()


# ------------------------------------------------------------------ standings (engine)
def rr(rid, winners, players, champ="c"):
    return scoring.RoundResult(
        rid, champ, scoring.RoundClassification.COMPETITIVE,
        tuple(scoring.EntryResult(p, scoring.Decimal("300.00") if p in winners
                                  else scoring.Decimal("0.00")) for p in players),
        "points-150-75-v2",
    )  # fmt: skip


def gross_round(rid, grosses: dict[str, str]):
    return scoring.RoundResult(
        rid, "c", scoring.RoundClassification.COMPETITIVE,
        tuple(scoring.EntryResult(p, scoring.Decimal(g)) for p, g in grosses.items()),
        "points-150-75-v2",
    )  # fmt: skip


def test_championship_tiebreakers_points_then_recoveries_then_top_tens():
    """The unchanged engine used by Stage C orders: points, recoveries, qualifying
    top tens, then a shared rank (D-27, L-07)."""
    xs = {f"x{i}": f"{400 - i}.00" for i in range(10)}  # ranks 1..10, all recover
    fill = {f"f{i}": "0.00" for i in range(4)}
    rounds = [
        gross_round("r1", {"A": "300.00", **fill}),  # A: 150 (1 recovery, 1 top ten)
        gross_round("r2", {**xs, "B": "200.00"}),  # B: rank 11 -> 75
        gross_round("r3", {**xs, "B": "200.00"}),  # B: 150 total, 2 recoveries, 0 top tens
        gross_round("r4", {"C": "300.00", "D": "250.00", **dict(list(fill.items())[:3])}),
        gross_round("r5", {**dict(list(xs.items())[:9]), "D": "391.00", "C": "200.00"}),
    ]
    t = scoring.aggregate_championship("c", rounds)
    row = {s.participant_id: s for s in t.standings}
    assert (row["A"].points, row["A"].recoveries) == (150, 1)
    assert (row["B"].points, row["B"].recoveries, row["B"].qualifying_top10) == (150, 2, 0)
    assert row["B"].rank < row["A"].rank  # equal points: more recoveries first
    assert (row["C"].points, row["C"].recoveries, row["C"].qualifying_top10) == (225, 2, 1)
    assert (row["D"].points, row["D"].recoveries, row["D"].qualifying_top10) == (225, 2, 2)
    assert row["D"].rank < row["C"].rank  # equal points and recoveries: more top tens first
    zero = [s for s in t.standings if s.points == 0]
    assert len({s.rank for s in zero}) == 1  # still level: a shared rank


def test_joint_champions_and_shared_ranks():
    players = [f"p{i}" for i in range(5)]
    t = scoring.aggregate_championship("c", [rr("r1", {"p0", "p1"}, players),
                                             rr("r2", {"p0", "p1"}, players)])  # fmt: skip
    top = [s for s in t.standings if s.rank == 1]
    assert {s.participant_id for s in top} == {"p0", "p1"} and {s.points for s in top} == {300}
    assert {s.rank for s in t.standings if s.participant_id not in ("p0", "p1")} == {3}
