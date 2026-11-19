"""Phase 6C.4 Stage D: corrections, materiality, alert resolution, invalidation,
finalisation and owner-only reopening, on real PostgreSQL."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from settle_helpers import (
    DEFAULT_ENTRY,
    provider_item,
    settlement_world,
    settlement_worlds,
    shifted,
)
from svc_helpers import principal, wait_until

from diski9.backend import settlement_scenarios as sc
from diski9.backend.auth.permissions import Forbidden, RecentAuthenticationRequired
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    audit_log,
    designations,
    rounds,
    selection_verdicts,
    settlement_versions,
)
from diski9.backend.repositories import results as repo
from diski9.backend.services import corrections as co
from diski9.backend.services import results as rs
from diski9.backend.services import settlement as st
from diski9.backend.services.rounds import SYSTEM
from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

WIN = {"HOME": (1, 0), "BTTS_YES": (1, 1), "UNDER_2_5": (0, 0), "AWAY": (0, 1)}


def fresh(p):
    """The same principal with the password just re-entered (T-14)."""
    with transaction(ENGINE[0]) as conn:
        now = db_now(conn)
    return replace(p, authenticated_at=now, reauthenticated_at=now, now=now)


ENGINE: list = []


@pytest.fixture(scope="module", autouse=True)
def _engine(engine):
    ENGINE[:] = [engine]


@pytest.fixture(scope="module")
def op(engine):
    return fresh(principal(engine, role="operator"))


@pytest.fixture(scope="module")
def owner(engine):
    return fresh(principal(engine, role="owner"))


def record(engine, fid, at, status, ko, h=None, a=None):
    wait_until(engine, at)
    item = provider_item(fid, status, ko=ko, h=h, a=a)
    with transaction(engine) as conn:
        return repo.record_evidence(
            conn, source="api-football", fixture_id=fid, observed_at=at, raw=item,
            raw_hash=canonical_hash(item), fields=evidence_fields(item),
        )  # fmt: skip


def finish(engine, w, spec, outcome_of):
    at = w["deadline"] + timedelta(milliseconds=1500)
    ko = w["deadline"] + timedelta(seconds=1)
    for i, _m, o in spec:
        res = outcome_of(o)
        if res == "CANC":
            record(engine, w["fixtures"][i], at, "CANC", ko)
        else:
            record(engine, w["fixtures"][i], at, "FT", ko, *res)


def versions(engine, rid):
    with transaction(engine) as conn:
        return conn.execute(
            sa.select(settlement_versions.c.version, settlement_versions.c.kind,
                      settlement_versions.c.material)
            .where(settlement_versions.c.round_id == rid).order_by(settlement_versions.c.version)
        ).all()  # fmt: skip


def gross(engine, w, k=0):
    with transaction(engine) as conn:
        return st._current_entry_settlements(conn, w["round"])[w["entries"][k]]


def verdict(engine, w, i):
    with transaction(engine) as conn:
        return conn.execute(
            sa.select(selection_verdicts).where(selection_verdicts.c.fixture_id == w["fixtures"][i])
            .order_by(selection_verdicts.c.revision.desc())
        ).first()  # fmt: skip


def correct(engine, actor, w, c, reason="league report", evidence="official match report"):
    imp = co.preview_correction(engine, actor, w["round"], c)
    return imp, co.correct_result(engine, actor, w["round"], c, reason=reason, evidence=evidence,
                                  confirmation=imp.token)  # fmt: skip


# ------------------------------------------------------------------ corrections
@pytest.fixture(scope="module")
def settled(engine, op):
    w = settlement_world(engine, cutoff_after=timedelta(seconds=3))
    finish(engine, w, DEFAULT_ENTRY, WIN.get)
    wait_until(engine, w["cutoff"] + timedelta(milliseconds=200))
    st.settle_round(engine, op, w["round"])
    return w


def test_non_material_score_correction_is_recorded_but_keeps_the_window(engine, op, settled):
    w = settled
    before = versions(engine, w["round"])
    imp, res = correct(engine, op, w, co.CorrectionInput(w["fixtures"][0], "FT", 3, 0))
    assert not imp.material and not res.material and res.version is None
    assert versions(engine, w["round"]) == before  # window not restarted
    v = verdict(engine, w, 0)
    assert v.verdict == "won" and not v.material and v.evidence["score"] == "3-0"
    with transaction(engine) as conn:
        a = conn.execute(sa.select(audit_log).where(audit_log.c.action == "result.correct")
                         .order_by(audit_log.c.id.desc())).first()  # fmt: skip
    assert a.reason == "league report" and a.after["correction"]["ft_home"] == 3
    assert "password" not in str(a.after).lower()


def test_material_correction_changes_verdict_payout_and_version(engine, op, settled):
    w = settled
    old = gross(engine, w).gross
    imp, res = correct(engine, op, w, co.CorrectionInput(w["fixtures"][7], "FT", 1, 0))
    assert imp.material and res.material and res.version is not None
    assert verdict(engine, w, 7).verdict == "lost"
    assert gross(engine, w).gross == old - Decimal("208.01") - Decimal("2206.77")


def test_correction_of_an_unselected_fixture_is_not_material(engine, op, settled):
    w = settled
    imp, res = correct(engine, op, w, co.CorrectionInput(w["fixtures"][15], "FT", 0, 0))
    assert not imp.material and res.version is None


def test_withdrawing_a_correction_restores_the_provider_result(engine, op, settled):
    w = settled
    with transaction(engine) as conn:
        corr = conn.execute(sa.text(
            "SELECT id FROM app.result_observations WHERE fixture_id=:f AND source='operator' "
            "ORDER BY id DESC LIMIT 1"), {"f": w["fixtures"][7]}).scalar_one()  # fmt: skip
    res = co.withdraw_correction(engine, op, w["round"], corr, reason="entered in error")
    assert res.material and verdict(engine, w, 7).verdict == "won"


def test_stale_or_concurrent_confirmations_are_refused(engine, op, settled):
    w = settled
    c = co.CorrectionInput(w["fixtures"][8], "FT", 2, 0)
    imp = co.preview_correction(engine, op, w["round"], c)
    errors, ok = [], []

    def go():
        try:
            ok.append(co.correct_result(engine, op, w["round"], c, reason="r", evidence="e",
                                        confirmation=imp.token))  # fmt: skip
        except co.ConfirmationMismatch as exc:
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 1 and len(errors) == 2


def test_corrections_need_the_right_person_and_recent_authentication(engine, op, settled):
    w = settled
    c = co.CorrectionInput(w["fixtures"][1], "FT", 1, 0)
    with pytest.raises(Forbidden):
        co.preview_correction(engine, fresh(principal(engine)), w["round"], c)
    stale = replace(op, reauthenticated_at=None)
    with pytest.raises(RecentAuthenticationRequired):
        co.preview_correction(engine, stale, w["round"], c)
    with pytest.raises(co.CorrectionRefused):
        co.correct_result(engine, SYSTEM, w["round"], c, reason="r", evidence="e", confirmation="x")
    imp = co.preview_correction(engine, op, w["round"], c)
    for reason, evidence in (("", "e"), ("r", " ")):
        with pytest.raises(co.CorrectionRefused):
            co.correct_result(engine, op, w["round"], c, reason=reason, evidence=evidence,
                              confirmation=imp.token)  # fmt: skip


# ------------------------------------------------------------------ late notification
@pytest.fixture(scope="module")
def late(engine, op):
    made = settlement_worlds(engine, [[DEFAULT_ENTRY]] * 2, cutoff_after=timedelta(seconds=3))
    for w in made:
        finish(engine, w, DEFAULT_ENTRY[1:], WIN.get)
        record(engine, w["fixtures"][0], w["deadline"] + timedelta(seconds=1), "1H",
               w["deadline"] + timedelta(seconds=1))  # fmt: skip
    wait_until(engine, max(w["cutoff"] for w in made) + timedelta(milliseconds=300))
    for w in made:
        with transaction(engine) as conn:
            at = db_now(conn)
        record(engine, w["fixtures"][0], at, "FT", w["deadline"] + timedelta(seconds=1), 1, 0)
        st.settle_round(engine, op, w["round"])
    return made


def _open(engine, w, blocking=True):
    with transaction(engine) as conn:
        return repo.open_alerts(conn, w["round"], blocking_only=blocking)


def test_late_notification_confirmed_void(engine, op, late):
    w = late[0]
    (alert,) = _open(engine, w)
    assert alert.code == "late_notification" and verdict(engine, w, 0).verdict == "void"
    assert (
        co.resolve_alert(engine, op, w["round"], alert.id, reason="kicked off late") == "confirmed"
    )
    assert not _open(engine, w) and verdict(engine, w, 0).verdict == "void"


def test_late_notification_corrected_with_verified_completion(engine, op, late):
    w = late[1]
    c = co.CorrectionInput(
        w["fixtures"][0], "FT", 1, 0, completed_at=w["cutoff"] - timedelta(seconds=1)
    )
    imp, res = correct(engine, op, w, c, evidence="league timeline: full time before cutoff")
    assert imp.material and verdict(engine, w, 0).verdict == "won" and not _open(engine, w)


def test_blocking_conflicts_cannot_be_dismissed_without_a_correction(engine, op):
    dev = settlement_world(engine, development=True)
    rs.set_result_mode(engine, op, dev["round"], "synthetic")
    sc.apply_scenario(engine, op, dev["round"], "status-regression")
    st.settle_round(engine, op, dev["round"], as_of=dev["cutoff"] + timedelta(hours=1))
    (alert,) = _open(engine, dev)
    with pytest.raises(co.CorrectionRefused):
        co.resolve_alert(engine, op, dev["round"], alert.id, reason="ignore")


# ------------------------------------------------------------------ D-32b and invalidation
@pytest.fixture(scope="module")
def validity(engine, op):
    competitive = [DEFAULT_ENTRY] * 4 + [shifted(9)]
    made = settlement_worlds(engine, [competitive, competitive], cutoff_after=timedelta(seconds=3))
    for w in made:
        finish(engine, w, DEFAULT_ENTRY, WIN.get)
        finish(engine, w, shifted(9), lambda o: "CANC")
    wait_until(engine, max(w["cutoff"] for w in made) + timedelta(milliseconds=200))
    for w in made:
        st.settle_round(engine, op, w["round"])
    return made


def _designation(engine, w):
    with transaction(engine) as conn:
        return st.current_designation(conn, w["round"])


def test_operator_full_time_without_verified_completion_stays_void(engine, op, validity):
    w = validity[0]
    imp = co.preview_correction(
        engine, op, w["round"], co.CorrectionInput(w["fixtures"][9], "FT", 1, 0)
    )
    assert imp.designation_after == "void"  # no evidence of completion by the cutoff


def test_correction_changes_d33_and_restores_then_invalidates_validity(engine, op, validity):
    w = validity[0]
    assert _designation(engine, w).designation == "void"  # 4 rank-eligible entries
    assert gross(engine, w, 4).basis == "all_void"
    done = w["cutoff"] - timedelta(seconds=1)  # verified completion (completion-based cutoff)
    c = co.CorrectionInput(w["fixtures"][9], "FT", 1, 0, completed_at=done)  # entry 5 plays
    imp, res = correct(engine, op, w, c)
    assert imp.designation_after == "championship" and res.designation == "championship"
    assert gross(engine, w, 4).basis == "settled"  # D-33 classification changed
    d = _designation(engine, w)
    assert d.basis == "d32b" and d.provisional
    # and back: a correction that invalidates the round again
    imp, res = correct(engine, op, w, co.CorrectionInput(w["fixtures"][9], "CANC"))
    assert res.designation == "void"
    with transaction(engine) as conn:
        rows = conn.execute(sa.select(designations.c.designation).where(
            designations.c.round_id == w["round"]).order_by(designations.c.id)).scalars().all()  # fmt: skip
    assert rows == ["championship", "void", "championship", "void"]  # history, never rewritten


def test_operator_invalidation_is_audited_and_not_undone_by_d32b(engine, op, validity):
    w = validity[1]
    done = w["cutoff"] - timedelta(seconds=1)
    correct(engine, op, w, co.CorrectionInput(w["fixtures"][9], "FT", 1, 0, completed_at=done))
    assert _designation(engine, w).designation == "championship"
    with pytest.raises(Forbidden):
        co.preview_invalidation(engine, fresh(principal(engine)), w["round"], reason="x")
    imp = co.preview_invalidation(engine, op, w["round"], reason="stadium power failure")
    res = co.invalidate_round(engine, op, w["round"], reason="stadium power failure",
                              confirmation=imp.token)  # fmt: skip
    assert res.designation == "void" and res.material
    d = _designation(engine, w)
    assert d.basis == "operator" and d.actor_user_id == op.user_id
    st.settle_round(engine, op, w["round"])  # D-32b passes, but the operator void stands
    assert _designation(engine, w).designation == "void"
    me = principal(engine, user_id=w["users"][0])
    pr = st.personal_result(engine, me, w["round"])
    assert pr.round_void and pr.gross == Decimal("100.00") and pr.recovered is False


# ------------------------------------------------------------------ finalisation and reopening
@pytest.fixture(scope="module")
def final_world(engine, op):
    w = settlement_world(engine, development=True, cutoff_after=timedelta(seconds=3))
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    sc.apply_scenario(engine, op, w["round"], "all-correct")
    wait_until(engine, w["cutoff"] + timedelta(milliseconds=200))
    res = st.settle_round(engine, op, w["round"])
    w["earliest"] = res.earliest_finalisation
    return w


def test_earliest_finalisation_is_cutoff_or_last_change_plus_24_hours(engine, final_world):
    w = final_world
    with transaction(engine) as conn:
        last = st.last_material_change(conn, w["round"])
    assert w["earliest"] == max(w["cutoff"], last) + timedelta(hours=24)


def test_finalisation_boundary_at_exactly_24_hours(engine, op, final_world):
    w = final_world
    early = co.finalise_round(
        engine, op, w["round"], as_of=w["earliest"] - timedelta(microseconds=1)
    )
    assert not early.finalised and "window" in early.reason
    done = co.finalise_round(engine, op, w["round"], as_of=w["earliest"])
    assert done.finalised and done.version is not None
    with transaction(engine) as conn:
        r = conn.execute(sa.select(rounds).where(rounds.c.id == w["round"])).one()
        d = st.current_designation(conn, w["round"])
    assert r.status == "final" and r.finalised_at == w["earliest"] and not d.provisional
    assert versions(engine, w["round"])[-1][1] == "final"


def test_final_round_cannot_be_corrected_and_imports_only_alert(engine, op, final_world):
    w = final_world
    with pytest.raises(co.CorrectionRefused):
        co.preview_correction(engine, op, w["round"], co.CorrectionInput(w["fixtures"][0], "CANC"))
    with transaction(engine) as conn:
        now = db_now(conn)
    rs.record_synthetic_observation(engine, op, w["round"], w["fixtures"][0], observed_at=now,
                                    status="CANC")  # fmt: skip
    before = versions(engine, w["round"])
    res = st.settle_round(engine, op, w["round"])
    assert res.post_final_change and res.run_id is None
    assert versions(engine, w["round"]) == before  # finalised results never mutated
    with transaction(engine) as conn:
        assert conn.execute(sa.select(rounds.c.status).where(rounds.c.id == w["round"])
                            ).scalar_one() == "final"  # fmt: skip
    assert any(a.code == "post_final_change" for a in _open(engine, w, blocking=False))


def test_only_the_owner_with_recent_authentication_can_reopen(engine, op, owner, final_world):
    w = final_world
    with pytest.raises(Forbidden):
        co.preview_reopen(engine, op, w["round"])
    with pytest.raises(RecentAuthenticationRequired):
        co.preview_reopen(engine, replace(owner, reauthenticated_at=None), w["round"])
    imp = co.preview_reopen(engine, owner, w["round"])
    assert imp.material  # the post-final evidence (V2) would change the result
    for reason, evidence in (("", "e"), ("r", "")):
        with pytest.raises(co.CorrectionRefused):
            co.reopen_round(engine, owner, w["round"], reason=reason, evidence=evidence,
                            confirmation=imp.token)  # fmt: skip
    res = co.reopen_round(engine, owner, w["round"], reason="match cancelled by league",
                          evidence="league statement 3 Dec", confirmation=imp.token)  # fmt: skip
    assert res.material and verdict(engine, w, 0).rule == "V2"
    kinds = [k for _, k, _ in versions(engine, w["round"])]
    assert kinds[-3:] == ["final", "reopened", "provisional"]  # the final version is kept
    assert not any(a.code == "post_final_change" for a in _open(engine, w, blocking=False))
    with transaction(engine) as conn:
        a = conn.execute(sa.select(audit_log).where(audit_log.c.action == "round.reopen")
                         .order_by(audit_log.c.id.desc())).first()  # fmt: skip
        assert conn.execute(sa.select(rounds.c.status).where(rounds.c.id == w["round"])
                            ).scalar_one() == "settling"  # fmt: skip
    assert a.actor_user_id == owner.user_id and a.after["evidence"] == "league statement 3 Dec"


def test_real_round_finalisation_has_no_time_override(engine, op, settled):
    with pytest.raises(st.SettlementRefused):
        co.finalise_round(engine, op, settled["round"], as_of=settled["cutoff"] + timedelta(days=2))
    res = co.finalise_round(engine, SYSTEM, settled["round"])
    assert not res.finalised and "window" in res.reason
