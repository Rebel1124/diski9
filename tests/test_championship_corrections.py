"""Phase 6C.5 Stage D: championship corrections on the pure model (no database).

* ``resolve_roles``: invalidation (L-32 / L-33 / L-34), restoration with and
  without capacity (CH-05, spec §23.5), reserved slots, deadline-order
  reconsideration of restored rounds, operator-invalidated rounds staying void;
* ``expected_status``: L-33 return to in progress, D-30a historical completion;
* property-based lifecycle sequences (Hypothesis) over the pure planner and role
  resolution, checking the Stage D invariants after every step against an
  independent reference model of capacity and membership."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from diski9.backend.services import championships as ch

T0 = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)


def rid(i: int) -> uuid.UUID:
    return uuid.UUID(int=i + 1)


def order_of(n: int) -> dict:
    return {rid(i): (T0 + timedelta(days=7 * i), str(rid(i))) for i in range(n)}


def model(roles: dict[int, str], required: int = 10, fixed: bool = False) -> ch.ChampModel:
    return ch.ChampModel("c", 1, "Championship Nov-26", T0.date(), required,
                         {rid(i): r for i, r in roles.items()}, fixed)  # fmt: skip


def outcomes(**by_index) -> dict:
    return {rid(int(k[1:])): v for k, v in by_index.items()}


# ------------------------------------------------------------------ invalidation
def test_counted_round_invalidated_removes_it_and_frees_capacity():
    m = model({i: "counted" for i in range(7)})
    changes = ch.resolve_roles(m, outcomes(r3="void"), order_of(7))
    assert [(c.round_id, c.kind) for c in changes] == [(rid(3), "invalidated")]
    assert m.counted == 6 and m.commitment == 6  # L-32: continues until ten


def test_status_rules_l33_and_d30a():
    assert ch.expected_status(9, 10, fixed=False, started=True) == "in_progress"  # L-33
    assert ch.expected_status(9, 10, fixed=True, started=True) == "completed"  # D-30a
    assert ch.expected_status(0, 10, fixed=True, started=True) == "completed"  # all invalidated
    assert ch.expected_status(0, 10, fixed=False, started=True) == "in_progress"
    assert ch.expected_status(0, 10, fixed=False, started=False) == "upcoming"
    assert ch.expected_status(10, 10, fixed=False, started=True) == "completed"


def test_reopened_round_keeps_its_published_role():
    # a reopened counted round's latest publication is still competitive
    assert ch.role_of("settling", "championship", "championship") == "counted"
    m = model({0: "counted", 1: "void"})
    assert ch.resolve_roles(m, outcomes(r0="counted", r1="void"), order_of(2)) == []


# ------------------------------------------------------------------ restoration (CH-05)
def test_restored_round_counts_when_capacity_remains():
    m = model({0: "counted", 1: "void", 2: "counted"})
    (c,) = ch.resolve_roles(m, outcomes(r1="counted"), order_of(3))
    assert c.kind == "restored" and m.roles[rid(1)] == "counted" and m.counted == 3


def test_restored_round_without_capacity_is_not_counted_and_displaces_nothing():
    roles = {i: "counted" for i in range(10)} | {10: "void"}
    m = model(roles)
    (c,) = ch.resolve_roles(m, outcomes(r10="counted"), order_of(11))
    assert c.kind == "not_counted" and m.counted == 10
    assert all(m.roles[rid(i)] == "counted" for i in range(10))


def test_reserved_slots_are_not_taken_by_a_restored_round():
    roles = {i: "counted" for i in range(9)} | {9: "pending", 10: "void"}
    m = model(roles)
    out = outcomes(r9="pending", r10="counted")
    (c,) = ch.resolve_roles(m, out, order_of(11))
    assert c.kind == "not_counted" and m.roles[rid(9)] == "pending"
    # the reserved round becomes void: the restored round is reconsidered and counts
    out[rid(9)] = "void"
    changes = ch.resolve_roles(m, out, order_of(11))
    assert {(x.round_id, x.after) for x in changes} == {(rid(9), "void"), (rid(10), "counted")}
    assert m.counted == 10


def test_several_restored_rounds_take_capacity_in_deadline_order():
    roles = {i: "counted" for i in range(8)} | {8: "void", 9: "void", 10: "void"}
    m = model(roles)
    changes = ch.resolve_roles(m, outcomes(r8="counted", r9="counted", r10="counted"),
                               order_of(11))  # fmt: skip
    assert [(c.round_id, c.after) for c in changes] == [
        (rid(8), "counted"), (rid(9), "counted"), (rid(10), "not_counted")]  # fmt: skip
    # independent of dictionary order
    m2 = model(dict(reversed(list(roles.items()))))
    ch.resolve_roles(m2, outcomes(r10="counted", r9="counted", r8="counted"), order_of(11))
    assert m2.roles == m.roles


def test_not_counted_round_takes_capacity_freed_by_a_later_invalidation():
    roles = {i: "counted" for i in range(10)} | {10: "not_counted"}
    m = model(roles, fixed=True)  # historical: still within its own championship
    out = outcomes(r10="counted", r4="void")
    changes = ch.resolve_roles(m, out, order_of(11))
    assert {(c.round_id, c.after) for c in changes} == {(rid(4), "void"), (rid(10), "counted")}
    assert m.counted == 10


def test_not_counted_round_invalidated_again_and_operator_voids_stay_void():
    m = model({0: "counted", 1: "not_counted", 2: "void"})
    changes = ch.resolve_roles(m, outcomes(r1="void", r2="void"), order_of(3))
    assert [(c.round_id, c.kind) for c in changes] == [(rid(1), "excluded")]
    assert m.roles[rid(2)] == "void"


def test_practice_never_changes_and_pending_keeps_its_reservation():
    m = model({0: "practice", 1: "pending"})
    changes = ch.resolve_roles(m, outcomes(r0="counted", r1="counted"), order_of(2))
    assert [(c.round_id, c.after) for c in changes] == [(rid(1), "counted")]
    assert m.roles[rid(0)] == "practice"


def test_more_than_ten_counted_is_an_integrity_error():
    m = model({i: "counted" for i in range(11)})
    with pytest.raises(ch.ChampionshipIntegrityError):
        ch.resolve_roles(m, {}, order_of(11))


# ------------------------------------------------------------------ property-based
# A stream of N rounds in deadline order; each step applies one legitimate
# operation to the authoritative outcomes, then processes the stream exactly as
# process_stream does (resolve roles, then assign). Allowed transitions follow
# 6C.4: lock fixes practice; first finalisation decides valid or void; a final
# round can be re-finalised valid<->void, except that an operator invalidation
# can never be restored.
N = 14
REQUIRED = 3  # small championships so that rollover and history happen often


def _process(champs, outcome, order, published):
    for m in champs:
        ch.resolve_roles(m, outcome, order)
    facts = [ch.RoundFact(rid(i), order[rid(i)][0], order[rid(i)][0], outcome[rid(i)])
             for i in range(N) if i < published]  # fmt: skip
    return ch.plan_assignments(facts, champs, REQUIRED)


def _check(champs, outcome, history, operator_void, plan):
    member = {}
    for k, m in enumerate(champs):
        assert m.counted <= m.required  # never more than the maximum
        for r, role in m.roles.items():
            assert r not in member  # no duplicate membership
            member[r] = k
            out = outcome[r]  # roles agree with authoritative outcomes
            if role == "pending":
                assert out == "pending"
            elif role == "practice":
                assert out == "practice"
            elif role == "void":
                assert out == "void"
            else:  # counted / not_counted: valid
                assert out == "counted"
                if r in operator_void:
                    raise AssertionError("an operator invalidation was restored")
            if role == "not_counted":  # only when no capacity remains
                assert m.commitment >= m.required
        if k < len(champs) - 1:
            assert m.fixed  # a successor exists: boundary fixed
            assert not any(v == "pending" for v in m.roles.values())
        status = ch.expected_status(m.counted, m.required, m.fixed, True)
        if not m.fixed and m.counted < m.required:
            assert status != "completed"  # no premature completion
    # membership is immutable: once assigned, a round never changes championship
    for r, k in member.items():
        assert history.setdefault(r, k) == k
    # deadline order: championships hold consecutive deadline ranges
    ks = [member[rid(i)] for i in range(N) if rid(i) in member]
    assert ks == sorted(ks)
    # waiting rounds: only when the open championship's commitment is full
    if plan.waiting:
        open_ = champs[-1]
        assert open_.commitment >= open_.required and open_.counted < open_.required


def _applicable(outcome, operator_void, published):
    """Every legitimate (operation, round) pair in the current state."""
    out = [("publish", None)] if published < N else []
    for i in range(published):
        r, cur = rid(i), outcome[rid(i)]
        if cur == "pending":
            out += [("lock_practice", i), ("finalise_valid", i), ("finalise_void", i),
                    ("operator_void", i)]  # fmt: skip
        elif cur == "counted":
            out += [("refinalise_void", i), ("operator_void", i)]
        elif cur == "void" and r not in operator_void:
            out.append(("refinalise_valid", i))  # a D-32b void restored by owner reopening
    return out


@settings(max_examples=500, deadline=None, derandomize=True,
          suppress_health_check=[HealthCheck.too_slow])  # fmt: skip
@given(st.data())
def test_generated_correction_sequences_preserve_the_invariants(data):
    order = {rid(i): (T0 + timedelta(days=7 * i), str(rid(i))) for i in range(N)}
    outcome = {rid(i): "pending" for i in range(N)}
    operator_void: set = set()
    champs: list[ch.ChampModel] = []
    history: dict = {}
    published = 1
    for _ in range(data.draw(st.integers(5, 70), label="steps")):
        choices = _applicable(outcome, operator_void, published)
        if not choices:
            break
        op, i = data.draw(st.sampled_from(choices), label="op")
        if op == "publish":
            published += 1
        elif op == "lock_practice":
            outcome[rid(i)] = "practice"
        elif op in ("finalise_valid", "refinalise_valid"):
            outcome[rid(i)] = "counted"
        else:
            outcome[rid(i)] = "void"
            if op == "operator_void":
                operator_void.add(rid(i))
        plan = _process(champs, outcome, order, published)
        _check(champs, outcome, history, operator_void, plan)
        # idempotent: processing again changes nothing
        snapshot = [dict(m.roles) for m in champs]
        again = _process(champs, outcome, order, published)
        assert [dict(m.roles) for m in champs] == snapshot and again.assignments == ()


@settings(max_examples=200, deadline=None, derandomize=True)
@given(st.permutations(list(range(6))))
def test_restoration_outcome_independent_of_processing_batch(perm):
    """Several restored rounds resolved in one processing step get the same roles
    whatever order their facts arrive in (no race decides who counts)."""
    roles = {i: "counted" for i in range(8)} | {i: "void" for i in range(8, 14)}
    out = {rid(i): "counted" for i in range(14)}
    m1 = model(roles)
    ch.resolve_roles(m1, out, order_of(14))
    shuffled = {8 + p: "void" for p in perm} | {i: "counted" for i in range(8)}
    m2 = model(shuffled)
    ch.resolve_roles(m2, out, order_of(14))
    assert m1.roles == m2.roles
    assert [m1.roles[rid(i)] for i in range(8, 14)] == ["counted", "counted"] + ["not_counted"] * 4
