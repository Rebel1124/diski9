"""Stage F (real PostgreSQL): the participant's own settlement for My Challenge
and its presentation rules (S-11). Numbers come from the stored settlement only."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from settle_helpers import DEFAULT_ENTRY, settlement_world, shifted
from sqlalchemy import func, select
from svc_helpers import principal, wait_until

from diski9.backend import settlement_scenarios as sc
from diski9.backend.auth.permissions import GUEST, Principal
from diski9.backend.db import transaction
from diski9.backend.db.schema import audit_log, entry_settlements, settlement_runs
from diski9.backend.services import corrections as co
from diski9.backend.services import results as rs
from diski9.backend.services import settlement as st
from diski9.backend.services.participant_results import my_settlement

PRAC = {"development": True, "cutoff_after": timedelta(seconds=5)}


def me(engine, w, i=0) -> Principal:
    return principal(engine, user_id=w["users"][i])


def fresh(p: Principal) -> Principal:
    """The same principal with a password check just now (T-14)."""
    return replace(p, reauthenticated_at=p.now)


def scenario(engine, w, name, op=None):
    op = fresh(op or principal(engine, role="operator"))
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    sc.apply_scenario(engine, op, w["round"], name, horizon=sc.PROMPT_HORIZON)
    wait_until(engine, w["deadline"] + timedelta(seconds=3))
    return op, st.settle_round(engine, op, w["round"])


def test_locked_before_any_settlement(engine):
    w = settlement_world(engine, **PRAC)
    r = my_settlement(engine, me(engine, w), w["round"])
    assert r.state == "locked" and not r.settled and r.gross is None and r.net is None


def test_partial_settlement_never_shows_pending_as_zero_or_incorrect(engine):
    w = settlement_world(engine, **PRAC)
    scenario(engine, w, "pending")
    r = my_settlement(engine, me(engine, w), w["round"])
    assert r.state == "in_progress" and not r.complete
    assert r.net is None and r.recovered is None  # not decided yet
    assert r.counts["pending"] > 0 and r.counts["lost"] == 0
    for a in r.accumulators:
        if "pending" in a.legs and "lost" not in a.legs:
            assert a.status == "pending" and a.payout is None
    settled = sum((a.payout for a in r.accumulators if a.payout is not None), Decimal("0"))
    assert r.gross == settled  # "settled so far" is exactly the paid accumulators
    assert all(p.verdict != "lost" for p in r.predictions if p.score is None)


def test_lost_leg_settles_its_accumulator_while_others_pend(engine):
    w = settlement_world(engine, **PRAC)
    op = fresh(principal(engine, role="operator"))
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    sc.apply_scenario(engine, op, w["round"], "pending", horizon=sc.PROMPT_HORIZON)
    wait_until(engine, w["deadline"] + timedelta(seconds=3))
    st.settle_round(engine, op, w["round"])
    r0 = my_settlement(engine, me(engine, w), w["round"])
    settled_fix = next(p for p in r0.predictions if p.verdict == "won")
    imp = co.preview_correction(
        engine, op, w["round"], co.CorrectionInput(settled_fix.fixture_id, "FT", 0, 6)
    )
    co.correct_result(engine, op, w["round"], co.CorrectionInput(settled_fix.fixture_id, "FT", 0, 6),
                      reason="report", evidence="report", confirmation=imp.token)  # fmt: skip
    r = my_settlement(engine, me(engine, w), w["round"])
    lost = [a for a in r.accumulators if "lost" in a.legs]
    assert lost and all(a.status == "lost" and a.payout == Decimal("0.00") for a in lost)
    assert r.corrected_at is not None


def test_complete_provisional_and_recovered(engine):
    w = settlement_world(engine, **PRAC)
    _, res = scenario(engine, w, "all-correct")
    r = my_settlement(engine, me(engine, w), w["round"])
    assert r.state == "provisional" and r.complete and r.recovered is True
    assert r.counts == {"won": 9, "lost": 0, "void": 0, "pending": 0}
    assert {a.status for a in r.accumulators} == {"won"}
    assert r.gross == sum(a.payout for a in r.accumulators)
    assert r.net == r.gross - Decimal("100.00")
    assert r.earliest_finalisation == res.earliest_finalisation
    assert all(p.score for p in r.predictions)


def test_all_nine_void_is_a_refund_not_a_recovery(engine):
    w = settlement_world(engine, [shifted(9), DEFAULT_ENTRY, shifted(1)], **PRAC)
    scenario(engine, w, "entry-all-void")  # entry 0 (fixtures 9-17) shares fewest matches
    r = my_settlement(engine, me(engine, w), w["round"])
    assert not r.round_void and r.entry_refunded and r.recovered is False
    assert r.state == "provisional"
    other = my_settlement(engine, me(engine, w, 1), w["round"])
    assert not other.entry_refunded and other.recovered is not None
    assert r.gross == Decimal("100.00") and r.net == Decimal("0.00")
    assert {a.status for a in r.accumulators} == {"refunded"}
    assert all(p.void_reason and p.void_reason.startswith("Void") for p in r.predictions)


def test_partial_void_keeps_success_and_explains_the_void(engine):
    w = settlement_world(engine, **PRAC)
    scenario(engine, w, "partial-void")
    r = my_settlement(engine, me(engine, w), w["round"])
    assert r.counts["void"] == 1 and r.counts["won"] == 8
    (v,) = [p for p in r.predictions if p.verdict == "void"]
    assert "cancelled" in v.void_reason
    found = next(a for a in r.accumulators if a.code == "A")
    assert found.status == "won"  # not "refunded": other legs won


def test_single_entry_all_nine_void_voids_the_round(engine):
    w = settlement_world(engine, **PRAC)
    scenario(engine, w, "all-nine-void")
    r = my_settlement(engine, me(engine, w), w["round"])
    assert r.round_void and r.gross == Decimal("100.00") and r.recovered is False


def test_round_void_refunds_everyone(engine):
    specs = [DEFAULT_ENTRY, shifted(1), shifted(2)]
    w = settlement_world(engine, specs, **PRAC)
    scenario(engine, w, "round-invalid-majority")
    for i in range(3):
        r = my_settlement(engine, me(engine, w, i), w["round"])
        assert r.round_void and r.round_void_basis == "d32b"
        assert r.gross == Decimal("100.00") and r.net == Decimal("0.00")
        assert r.recovered is False


def test_operator_invalidation_and_finalisation_and_reopening(engine):
    w = settlement_world(engine, **PRAC)
    op, res = scenario(engine, w, "all-correct")
    fin = co.finalise_round(engine, op, w["round"], as_of=res.earliest_finalisation)
    assert fin.finalised
    r = my_settlement(engine, me(engine, w), w["round"])
    assert r.state == "final" and r.version_kind == "final" and r.finalised_at is not None
    owner = fresh(principal(engine, role="owner"))
    imp = co.preview_reopen(engine, owner, w["round"])
    co.reopen_round(engine, owner, w["round"], reason="review", evidence="note",
                    confirmation=imp.token)  # fmt: skip
    r = my_settlement(engine, me(engine, w), w["round"])
    assert r.state == "provisional" and r.reopened_at is not None
    w2 = settlement_world(engine, **PRAC)
    op2, _ = scenario(engine, w2, "all-correct")
    imp = co.preview_invalidation(engine, op2, w2["round"], reason="pitch")
    co.invalidate_round(engine, op2, w2["round"], reason="pitch", confirmation=imp.token)
    r = my_settlement(engine, me(engine, w2), w2["round"])
    assert r.round_void and r.round_void_basis == "operator" and r.recovered is False


def test_only_the_owner_sees_their_result(engine):
    w = settlement_world(engine, [DEFAULT_ENTRY, shifted(1)], **PRAC)
    scenario(engine, w, "all-correct")
    a, b = me(engine, w, 0), me(engine, w, 1)
    ra, rb = my_settlement(engine, a, w["round"]), my_settlement(engine, b, w["round"])
    assert ra.predictions != rb.predictions  # each sees only their own entry
    stranger = principal(engine)
    assert my_settlement(engine, stranger, w["round"]) is None
    assert my_settlement(engine, GUEST, w["round"]) is None
    # a tampered round id (one the participant never entered) returns nothing
    other = settlement_world(engine, **PRAC)
    assert my_settlement(engine, a, other["round"]) is None
    # an expired or signed-out session is a guest; an un-onboarded one gets nothing
    assert my_settlement(engine, Principal(user_id=w["users"][0]), w["round"]) is None


def test_reads_write_nothing(engine):
    w = settlement_world(engine, **PRAC)
    scenario(engine, w, "pending")

    def counts():
        with transaction(engine) as conn:
            return tuple(
                conn.execute(select(func.count()).select_from(t)).scalar()
                for t in (entry_settlements, settlement_runs, audit_log)
            )

    before = counts()
    for _ in range(3):
        my_settlement(engine, me(engine, w), w["round"])
    assert counts() == before


# ------------------------------------------------------------------ presentation
def texts(component) -> str:
    out = []

    def walk(x):
        if isinstance(x, str | int | float):
            out.append(str(x))
        elif isinstance(x, list | tuple):
            for y in x:
                walk(y)
        elif x is not None and hasattr(x, "children"):
            walk(x.children)

    walk(component)
    return " ".join(out)


def local(v):
    return str(v)[:16]


@pytest.fixture
def partial(engine):
    w = settlement_world(engine, **PRAC)
    scenario(engine, w, "pending")
    return my_settlement(engine, me(engine, w), w["round"])


def test_panel_wording_for_partial_results(partial):
    from diski9.app.challenge import results_ui as ui

    body = texts(ui.panel(partial, {"picks": []}, local))
    assert "Partly settled" in body and "Returned so far" in body and "settled so far" in body
    assert "Not decided yet" in body and "Not final yet" in body
    assert "Pending" in body and "still pending" in body
    for a in partial.accumulators:  # a pending accumulator never shows 0.00
        if a.status == "pending":
            row = texts(ui.accumulators(partial))
            assert "Pending" in row
    assert "\N{GRINNING FACE}" not in body and not any(ord(ch) > 0x2FFF for ch in body)


def test_panel_wording_for_refunds(engine):
    from diski9.app.challenge import results_ui as ui

    w = settlement_world(engine, [shifted(9), DEFAULT_ENTRY, shifted(1)], **PRAC)
    scenario(engine, w, "entry-all-void")
    r = my_settlement(engine, me(engine, w), w["round"])
    body = texts(ui.panel(r, {"picks": []}, local))
    assert "Void · refunded" in body and "Refund (not a recovery)" in body
    assert "Recovered 100+" not in body and "Refunded" in body


def test_result_cards_keep_a_refund_distinct_from_a_recovery(engine):
    """Stage E final refinement: the Your Result cards use the statistics-card style;
    a refund is amber ("Refunded", "Refund (not a recovery)"), a recovery teal."""
    import json

    from diski9.app.challenge import results_ui as ui

    def result_cards(res):
        box = ui.summary(res, local).children
        return next(x for x in box if x is not None and "ch-res-metrics" in
                    (getattr(x, "className", "") or "")).children  # fmt: skip

    w = settlement_world(engine, [shifted(9), DEFAULT_ENTRY, shifted(1)], **PRAC)
    scenario(engine, w, "entry-all-void")
    r = my_settlement(engine, me(engine, w), w["round"])
    cards = result_cards(r)
    heads = [x.children[0].children for x in cards]
    cats = [x.className for x in cards]
    assert heads == ["Allocated", "Refunded", "Net", "Recovery"]
    assert cats == ["me-stat cat-violet", "me-stat cat-gold", "me-stat cat-blue",
                    "me-stat cat-gold"]  # fmt: skip
    assert "Refund (not a recovery)" in json.dumps(cards[3].to_plotly_json(), default=str)
    w2 = settlement_world(engine, **PRAC)
    scenario(engine, w2, "all-correct")
    r2 = my_settlement(engine, me(engine, w2), w2["round"])
    cards = result_cards(r2)
    assert [x.className for x in cards][1:] == ["me-stat cat-green", "me-stat cat-blue",
                                                "me-stat cat-teal"]  # fmt: skip
    assert "pos-val" in cards[2].children[1].children[0].className


def test_void_round_shows_no_accumulator_returns(engine):
    from diski9.app.challenge import results_ui as ui

    w = settlement_world(engine, **PRAC)
    op, _ = scenario(engine, w, "all-correct")
    imp = co.preview_invalidation(engine, op, w["round"], reason="pitch")
    co.invalidate_round(engine, op, w["round"], reason="pitch", confirmation=imp.token)
    r = my_settlement(engine, me(engine, w), w["round"])
    accs = texts(ui.accumulators(r))
    assert "Not paid" in accs and "Successful" not in accs
    body = texts(ui.panel(r, {"picks": []}, local))
    assert "Round void" in body and "Refund (not a recovery)" in body


def test_settled_entry_waits_for_the_round_check(engine):
    """An entry whose nine predictions are settled while other entries are pending:
    not 'partly settled', and neither net nor recovery is final (a void round would
    refund)."""
    from diski9.app.challenge import results_ui as ui

    w = settlement_world(engine, [DEFAULT_ENTRY, shifted(9)], **PRAC)
    scenario(engine, w, "pending")  # the later half of the fixtures stays in play
    r = my_settlement(engine, me(engine, w), w["round"])  # fixtures 0-8: all settled
    assert r.complete and r.counts["pending"] == 0
    assert r.state == "awaiting_round" and r.net is None and r.recovered is None
    body = texts(ui.panel(r, {"picks": []}, local))
    assert "round check pending" in body and "Not final yet" in body
    assert "Not decided yet" in body and "Partly settled" not in body
    other = my_settlement(engine, me(engine, w, 1), w["round"])
    assert other.state == "in_progress"
