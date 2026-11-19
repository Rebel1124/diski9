"""Phase 6C.4 Stage C: deterministic development settlement scenarios and
development result-mode isolation (S-08), on real PostgreSQL."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from settle_helpers import DEFAULT_ENTRY, provider_item, settlement_worlds
from svc_helpers import principal, wait_until

from diski9.backend import settlement_scenarios as sc
from diski9.backend.db import transaction
from diski9.backend.db.schema import result_observations as RO
from diski9.backend.db.schema import selection_verdicts
from diski9.backend.repositories import results as repo
from diski9.backend.services import results as rs
from diski9.backend.services import settlement as st
from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

EXTRA = ("isolation-synthetic", "isolation-real")


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


@pytest.fixture(scope="module")
def worlds(engine, op):
    names = list(sc.SCENARIOS) + list(EXTRA)
    made = settlement_worlds(engine, [[DEFAULT_ENTRY]] * len(names), development=True,
                             cutoff_after=timedelta(hours=1))  # fmt: skip
    out = dict(zip(names, made, strict=True))
    for name, w in out.items():
        rs.set_result_mode(
            engine, op, w["round"], "real" if name == "isolation-real" else "synthetic"
        )
        if name in sc.SCENARIOS:
            w["stored"] = sc.apply_scenario(engine, op, w["round"], name)
    return out


def settle_after(engine, op, w, delta=timedelta(hours=2)):
    return st.settle_round(engine, op, w["round"], as_of=w["cutoff"] + delta)


def entry(engine, w):
    with transaction(engine) as conn:
        return st._current_entry_settlements(conn, w["round"])[w["entries"][0]]


def verdict(engine, w, i):
    with transaction(engine) as conn:
        return conn.execute(
            sa.select(selection_verdicts)
            .where(selection_verdicts.c.fixture_id == w["fixtures"][i])
            .order_by(selection_verdicts.c.revision.desc())
        ).first()


def alert_codes(engine, w):
    with transaction(engine) as conn:
        return {a.code for a in repo.open_alerts(conn, w["round"], blocking_only=True)}


def test_unknown_scenario_is_refused():
    with pytest.raises(ValueError):
        sc.build("monte-carlo", deadline=None, cutoff=None, entries=[[]])


def test_all_correct(engine, op, worlds):
    w = worlds["all-correct"]
    res = settle_after(engine, op, w)
    s = entry(engine, w)
    assert res.outcome == "pass" and s.complete and s.basis == "settled"
    assert s.gross == Decimal("123.27") + Decimal("206.55") + Decimal("208.01") + Decimal("2206.77")


def test_all_incorrect(engine, op, worlds):
    w = worlds["all-incorrect"]
    settle_after(engine, op, w)
    s = entry(engine, w)
    assert s.complete and s.gross == Decimal("0.00") and s.net == Decimal("-100.00")


def test_one_bucket_wins(engine, op, worlds):
    w = worlds["one-bucket-wins"]
    settle_after(engine, op, w)
    assert entry(engine, w).gross == Decimal("123.27")


def test_partial_void_and_bucket_all_void(engine, op, worlds):
    settle_after(engine, op, worlds["partial-void"])
    accs = {a["code"]: a for a in entry(engine, worlds["partial-void"]).legs["accumulators"]}
    assert accs["A"]["payout"] == "94.10"  # 40 x 1.32 x 1.33 x 1.34 = 94.10496
    w = worlds["bucket-all-void"]
    settle_after(engine, op, w)
    accs = {a["code"]: a for a in entry(engine, w).legs["accumulators"]}
    assert accs["B"]["status"] == "won" and accs["B"]["payout"] == "30.00"  # stake returned
    assert Decimal(accs["NINE"]["effective_odds"]) == (
        Decimal("1.31") * Decimal("1.32") * Decimal("1.33") * Decimal("1.34") * Decimal("3.22")
        * Decimal("3.23")
    )  # fmt: skip


def test_all_nine_void(engine, op, worlds):
    w = worlds["all-nine-void"]
    settle_after(engine, op, w)
    s = entry(engine, w)
    assert (s.gross, s.basis) == (Decimal("100.00"), "all_void")


def test_round_invalid_majority(engine, op, worlds):
    res = settle_after(engine, op, worlds["round-invalid-majority"])
    assert res.outcome == "fail_majority" and res.designation == "void"


def test_pending_then_catch_all_at_the_cutoff(engine, op, worlds):
    w = worlds["pending"]
    mid = w["deadline"] + (w["cutoff"] - w["deadline"]) * 3 / 4
    res = st.settle_round(engine, op, w["round"], as_of=mid)
    assert res.outcome == "not_evaluated" and not entry(engine, w).complete
    res = settle_after(engine, op, w)
    assert verdict(engine, w, 8).rule == "V1-catch-all" and res.outcome != "not_evaluated"


def test_cutoff_boundary(engine, op, worlds):
    w = worlds["cutoff-boundary"]
    settle_after(engine, op, w)
    fids = sorted(w["fixtures"][:9])
    v0 = verdict(engine, w, w["fixtures"].index(fids[0]))
    v1 = verdict(engine, w, w["fixtures"].index(fids[1]))
    assert v0.verdict == "won"  # final recorded exactly at the cutoff
    assert (v1.verdict, v1.rule) == ("void", "V1-catch-all")  # one second after
    assert "late_notification" in alert_codes(engine, w)


def test_late_notification_is_void_and_stable_whenever_settled(engine, op, worlds):
    w = worlds["late-notification"]
    settle_after(engine, op, w)
    assert "late_notification" in alert_codes(engine, w)
    again = settle_after(engine, op, w, timedelta(days=30))
    assert again.changed_verdicts == 0 and not again.material


def test_provider_correction_conflict_keeps_first_score(engine, op, worlds):
    w = worlds["provider-correction"]
    settle_after(engine, op, w)
    assert "score_conflict" in alert_codes(engine, w)


def test_status_regression_and_early_start_are_held_pending(engine, op, worlds):
    settle_after(engine, op, worlds["status-regression"])
    assert "status_regression" in alert_codes(engine, worlds["status-regression"])
    settle_after(engine, op, worlds["early-start-unverified"])
    assert "early_start_unverified" in alert_codes(engine, worlds["early-start-unverified"])


def test_repeat_stores_identical_deliveries_once(engine, op, worlds):
    assert worlds["repeat"]["stored"] == worlds["all-correct"]["stored"]
    settle_after(engine, op, worlds["repeat"])
    assert entry(engine, worlds["repeat"]).gross == entry(engine, worlds["all-correct"]).gross


# ------------------------------------------------------------------ mode isolation
def _real_final(engine, fid, w):
    wait_until(engine, w["deadline"] + timedelta(seconds=2))  # receipt never after recording
    item = provider_item(fid, "FT", ko=w["deadline"] + timedelta(seconds=1), h=1, a=0)
    with transaction(engine) as conn:
        repo.record_evidence(
            conn, source="api-football", fixture_id=fid,
            observed_at=w["deadline"] + timedelta(seconds=2), raw=item,
            raw_hash=canonical_hash(item), fields=evidence_fields(item),
        )  # fmt: skip


def test_synthetic_mode_never_falls_back_to_real_results(engine, op, worlds):
    w = worlds["isolation-synthetic"]
    for fid in w["fixtures"][:9]:
        _real_final(engine, fid, w)  # real evidence exists for the same fixture IDs
    settle_after(engine, op, w)
    assert verdict(engine, w, 0).rule == "V1-catch-all"  # no synthetic evidence: void
    assert entry(engine, w).basis == "all_void"


def test_real_mode_development_round_reads_real_and_never_synthetic(engine, op, worlds):
    w = worlds["isolation-real"]
    for fid in w["fixtures"][:9]:
        _real_final(engine, fid, w)
    with transaction(engine) as conn:  # synthetic rows of another round, same fixture IDs
        assert conn.execute(sa.select(sa.func.count()).select_from(RO).where(
            RO.c.source == "synthetic", RO.c.fixture_id.in_(w["fixtures"]))).scalar_one() == 0  # fmt: skip
    settle_after(engine, op, w)
    assert verdict(engine, w, 0).verdict == "won"
    with pytest.raises(rs.ResultsRefused):
        sc.apply_scenario(engine, op, w["round"], "all-correct")
