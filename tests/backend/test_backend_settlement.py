"""Phase 6C.4 Stage C: entry and round settlement on real PostgreSQL.

Payouts are checked three ways: against an independent Decimal calculation, against
the confirmed submission's stored engine states, and through the D-32 / D-33 rules.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
import sqlalchemy as sa
from settle_helpers import (
    BY_KEY,
    DEFAULT_ENTRY,
    provider_item,
    settlement_world,
    settlement_worlds,
    shifted,
)
from svc_helpers import principal, wait_until

from diski9.backend.auth.permissions import AuthorizationError
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    designations,
    entry_settlements,
    round_evaluations,
    rounds,
    selection_verdicts,
    settlement_runs,
    settlement_versions,
)
from diski9.backend.repositories import results as repo
from diski9.backend.services import settlement as st
from diski9.backend.services.rounds import SYSTEM
from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

WIN = {"HOME": (1, 0), "BTTS_YES": (1, 1), "UNDER_2_5": (0, 0), "AWAY": (0, 1)}
LOSE = {"HOME": (0, 1), "BTTS_YES": (1, 0), "UNDER_2_5": (2, 1), "AWAY": (1, 0)}


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def q(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def expected_gross(spec, verdicts) -> Decimal:
    """Independent D-15 / D-32 arithmetic (not the engine)."""
    odds = {b: Decimal(1) for b in "ABC"}
    alive = {b: True for b in "ABC"}
    for (i, m, o), v in zip(spec, verdicts, strict=True):
        b, _, f = BY_KEY[(m, o)]
        if v == "lost":
            alive[b] = False
        odds[b] *= Decimal("1.00") if v == "void" else f(i)
    stakes = {"A": 40, "B": 30, "C": 20}
    gross = sum((q(stakes[b] * odds[b]) for b in "ABC" if alive[b]), Decimal("0.00"))
    if all(alive.values()):
        gross += q(10 * odds["A"] * odds["B"] * odds["C"])
    return gross


def record(engine, fid, at, status, ko, h=None, a=None):
    """Provider evidence received at ``at`` (waits until then: receipt can never be
    later than recording)."""
    wait_until(engine, at)
    item = provider_item(fid, status, ko=ko, h=h, a=a)
    with transaction(engine) as conn:
        return repo.record_evidence(
            conn, source="api-football", fixture_id=fid, observed_at=at, raw=item,
            raw_hash=canonical_hash(item), fields=evidence_fields(item),
        )  # fmt: skip


def finish(engine, w, spec, outcome_of, at=None, ko=None):
    """Record a final result for each fixture of ``spec`` (``outcome_of(outcome)``)."""
    at = at or w["deadline"] + timedelta(milliseconds=1500)
    ko = ko or w["deadline"] + timedelta(seconds=1)
    for i, _m, o in spec:
        res = outcome_of(o)
        if res == "CANC":
            record(engine, w["fixtures"][i], at, "CANC", ko)
        else:
            record(engine, w["fixtures"][i], at, "FT", ko, *res)


def es_rows(conn, entry):
    return list(
        conn.execute(
            sa.select(entry_settlements)
            .where(entry_settlements.c.entry_id == entry)
            .order_by(entry_settlements.c.revision)
        )
    )


# ------------------------------------------------------------------ payouts
@pytest.fixture(scope="module")
def payout_worlds(engine):
    return settlement_worlds(engine, [[DEFAULT_ENTRY]] * 4, cutoff_after=timedelta(seconds=4))


def test_all_correct_entry_matches_independent_arithmetic_and_stored_states(
    engine, op, payout_worlds
):
    w = payout_worlds[0]
    finish(engine, w, DEFAULT_ENTRY, WIN.get)
    res = st.settle_round(engine, op, w["round"])
    with transaction(engine) as conn:
        s = es_rows(conn, w["entries"][0])[-1]
    assert s.complete and s.basis == "settled"
    assert s.gross == expected_gross(DEFAULT_ENTRY, ["won"] * 9)
    assert s.gross == Decimal("123.27") + Decimal("206.55") + Decimal("208.01") + q(
        Decimal(10) * Decimal("3.08178024") * Decimal("6.884878") * Decimal("10.4006")
    )
    assert s.net == s.gross - Decimal("100.00") and res.version == 1


def test_one_wrong_leg_zeroes_its_bucket_and_the_nine_fold(engine, op, payout_worlds):
    w = payout_worlds[1]
    finish(engine, w, DEFAULT_ENTRY, lambda o: LOSE[o] if o == "UNDER_2_5" else WIN[o])
    st.settle_round(engine, op, w["round"])
    with transaction(engine) as conn:
        s = es_rows(conn, w["entries"][0])[-1]
    v = ["won"] * 6 + ["lost"] + ["won"] * 2
    assert s.gross == expected_gross(DEFAULT_ENTRY, v) == Decimal("123.27") + Decimal("208.01")
    accs = {a["code"]: a for a in s.legs["accumulators"]}
    assert accs["B"]["status"] == "lost" and accs["B"]["payout"] == "0.00"
    assert accs["NINE"]["status"] == "lost"


def test_partial_void_settles_the_leg_at_one(engine, op, payout_worlds):
    w = payout_worlds[2]
    finish(engine, w, DEFAULT_ENTRY[1:], WIN.get)
    finish(engine, w, DEFAULT_ENTRY[:1], lambda o: "CANC")
    st.settle_round(engine, op, w["round"])
    with transaction(engine) as conn:
        s = es_rows(conn, w["entries"][0])[-1]
        v0 = conn.execute(sa.select(selection_verdicts).where(
            selection_verdicts.c.fixture_id == w["fixtures"][0])).one()  # fmt: skip
    assert (v0.verdict, v0.rule, v0.void_code) == ("void", "V2", "V2")
    v = ["void"] + ["won"] * 8
    assert s.gross == expected_gross(DEFAULT_ENTRY, v)
    accs = {a["code"]: a for a in s.legs["accumulators"]}
    assert Decimal(accs["A"]["effective_odds"]) == Decimal("1.32") * Decimal("1.33") * Decimal(
        "1.34"
    )
    assert accs["A"]["payout"] == str(q(40 * Decimal("1.32") * Decimal("1.33") * Decimal("1.34")))


def test_all_nine_void_is_refunded_and_not_rank_eligible(engine, op, payout_worlds):
    w = payout_worlds[3]
    finish(engine, w, DEFAULT_ENTRY, lambda o: "CANC")
    st.settle_round(engine, op, w["round"])
    with transaction(engine) as conn:
        s = es_rows(conn, w["entries"][0])[-1]
    assert (s.gross, s.net, s.basis, s.complete) == (Decimal("100.00"), Decimal("0.00"),
                                                     "all_void", True)  # fmt: skip
    me = principal(engine, user_id=w["users"][0])
    pr = st.personal_result(engine, me, w["round"])
    assert pr.rank_eligible is False and pr.recovered is False


# ------------------------------------------------------------------ lifecycle and idempotency
@pytest.fixture(scope="module")
def life(engine):
    return settlement_world(engine, cutoff_after=timedelta(hours=1))


def test_first_run_with_no_evidence_is_pending_and_never_void(engine, op, life):
    res = st.settle_round(engine, op, life["round"])
    assert res.outcome == "not_evaluated" and res.phase == "before_cutoff" and res.version == 1
    with transaction(engine) as conn:
        assert conn.execute(sa.select(rounds.c.status).where(rounds.c.id == life["round"])
                            ).scalar_one() == "settling"  # fmt: skip
        s = es_rows(conn, life["entries"][0])[-1]
        verdicts = conn.execute(sa.select(selection_verdicts.c.verdict).where(
            selection_verdicts.c.round_id == life["round"])).scalars().all()  # fmt: skip
    assert set(verdicts) == {"pending"} and not s.complete and s.gross == Decimal("0.00")
    accs = {a["code"]: a for a in s.legs["accumulators"]}
    assert all(a["payout"] is None and a["status"] == "pending" for a in accs.values())
    pr = st.personal_result(engine, principal(engine, user_id=life["users"][0]), life["round"])
    assert pr.recovered is None and pr.rank_eligible is None


def test_rerun_with_the_same_evidence_writes_only_a_run_record(engine, op, life):
    with transaction(engine) as conn:
        before = conn.execute(sa.select(sa.func.count()).select_from(selection_verdicts).where(
            selection_verdicts.c.round_id == life["round"])).scalar_one()  # fmt: skip
    res = st.settle_round(engine, op, life["round"])
    assert res.version is None and not res.material and res.changed_verdicts == 0
    with transaction(engine) as conn:
        after = conn.execute(sa.select(sa.func.count()).select_from(selection_verdicts).where(
            selection_verdicts.c.round_id == life["round"])).scalar_one()  # fmt: skip
        runs = conn.execute(sa.select(settlement_runs).where(
            settlement_runs.c.round_id == life["round"]).order_by(settlement_runs.c.id)).all()  # fmt: skip
    assert before == after and len(runs) == 2 and runs[-1].inputs_hash == runs[0].inputs_hash


def test_partial_progress_shows_settled_so_far_and_certain_losses(engine, op, life):
    ko = life["deadline"] + timedelta(seconds=1)
    for i in (0, 1, 2, 3):  # Foundation complete and won
        record(engine, life["fixtures"][i], ko + timedelta(seconds=1), "FT", ko, 2, 0)
    record(engine, life["fixtures"][7], ko + timedelta(seconds=1), "FT", ko, 3, 0)  # C lost
    res = st.settle_round(engine, op, life["round"])
    assert res.material and res.version == 2
    with transaction(engine) as conn:
        s = es_rows(conn, life["entries"][0])[-1]
    accs = {a["code"]: a for a in s.legs["accumulators"]}
    assert accs["A"]["status"] == "won" and accs["A"]["payout"] == "123.27"
    assert accs["B"]["status"] == "pending" and accs["B"]["payout"] is None
    assert accs["C"]["status"] == "lost" and accs["NINE"]["status"] == "lost"
    assert s.gross == Decimal("123.27") and not s.complete


def test_runs_are_serialised_and_never_duplicate_versions(engine, op, life):
    record(engine, life["fixtures"][4], life["deadline"] + timedelta(seconds=3), "FT",
           life["deadline"] + timedelta(seconds=1), 1, 1)  # fmt: skip
    errors, results = [], []

    def go():
        try:
            results.append(st.settle_round(engine, op, life["round"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sum(1 for r in results if r.version is not None) == 1
    with transaction(engine) as conn:
        # in insertion order (id): without ORDER BY PostgreSQL may return any order
        versions = conn.execute(sa.select(settlement_versions.c.version).where(
            settlement_versions.c.round_id == life["round"])
            .order_by(settlement_versions.c.id)).scalars().all()  # fmt: skip
    assert versions == sorted(set(versions)) == list(range(1, len(versions) + 1))


def test_failure_rolls_back_everything_and_records_a_failed_run(engine, op, life, monkeypatch):
    record(engine, life["fixtures"][5], life["deadline"] + timedelta(seconds=4), "FT",
           life["deadline"] + timedelta(seconds=1), 2, 2)  # fmt: skip

    def boom(*a, **k):
        raise RuntimeError("injected")

    monkeypatch.setattr(st.results_repo, "raise_alerts", boom)
    with transaction(engine) as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(selection_verdicts)).scalar_one()
    with pytest.raises(RuntimeError):
        st.settle_round(engine, op, life["round"])
    with transaction(engine) as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(selection_verdicts)
                            ).scalar_one() == n  # fmt: skip
        last = conn.execute(sa.select(settlement_runs).where(
            settlement_runs.c.round_id == life["round"]).order_by(settlement_runs.c.id.desc())
        ).first()  # fmt: skip
    assert last.status == "failed" and last.error == "RuntimeError"


def test_authorisation_and_time_override_safeguards(engine, op, life):
    with pytest.raises(AuthorizationError):
        st.settle_round(engine, principal(engine), life["round"])
    assert st.settle_round(engine, SYSTEM, life["round"]).run_id is not None
    with pytest.raises(st.SettlementRefused):
        st.settle_round(engine, op, life["round"], as_of=life["cutoff"] + timedelta(days=1))
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(sa.insert(settlement_runs).values(round_id=life["round"], trigger="manual",
                                                       time_override=True))  # fmt: skip
    open_round = settlement_world(engine, lock=False, deadline_in=timedelta(hours=2))
    with pytest.raises(st.SettlementRefused):
        st.settle_round(engine, op, open_round["round"])


def test_preview_writes_nothing(engine, op, life):
    with transaction(engine) as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(settlement_runs)).scalar_one()
    plan = st.preview_settlement(engine, op, life["round"])
    assert plan.round_id == life["round"]
    with transaction(engine) as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(settlement_runs)
                            ).scalar_one() == n  # fmt: skip


# ------------------------------------------------------------------ cutoff on a real round
def test_late_result_on_a_real_round_stays_void_whenever_settled(engine, op):
    w = settlement_world(engine, cutoff_after=timedelta(seconds=2))
    ko = w["deadline"] + timedelta(seconds=1)
    finish(engine, w, DEFAULT_ENTRY[1:], WIN.get)  # eight fixtures complete in time
    record(engine, w["fixtures"][0], w["deadline"] + timedelta(seconds=1), "1H", ko)
    wait_until(engine, w["cutoff"] + timedelta(seconds=1))
    with transaction(engine) as conn:
        late_at = db_now(conn)
    record(engine, w["fixtures"][0], late_at, "FT", ko, 1, 0)  # first received after the cutoff
    first = st.settle_round(engine, op, w["round"])
    assert first.phase == "after_cutoff" and first.open_blocking_alerts == 1
    with transaction(engine) as conn:
        v = conn.execute(sa.select(selection_verdicts).where(
            selection_verdicts.c.fixture_id == w["fixtures"][0])).one()  # fmt: skip
    assert (v.verdict, v.rule, v.void_code) == ("void", "V1-catch-all", "V1")
    again = st.settle_round(engine, op, w["round"])  # later: same evidence, same verdict
    assert again.changed_verdicts == 0 and not again.material


# ------------------------------------------------------------------ D-32b
@pytest.fixture(scope="module")
def d32b(engine):
    competitive = [DEFAULT_ENTRY] * 4 + [shifted(9)]
    practice_half = [DEFAULT_ENTRY, shifted(3)]
    return settlement_worlds(engine, [competitive, competitive, practice_half, [DEFAULT_ENTRY]],
                             cutoff_after=timedelta(hours=2))  # fmt: skip


def _designation(engine, rid):
    with transaction(engine) as conn:
        return st.current_designation(conn, rid)


def test_competitive_round_with_four_rank_eligible_entries_is_void(engine, op, d32b):
    w = d32b[0]
    assert _designation(engine, w["round"]).designation == "championship"
    finish(engine, w, DEFAULT_ENTRY, WIN.get)
    finish(engine, w, shifted(9), lambda o: "CANC")
    res = st.settle_round(engine, op, w["round"])
    assert res.outcome == "fail_ranked" and res.designation == "void"
    d = _designation(engine, w["round"])
    assert d.basis == "d32b" and d.provisional
    with transaction(engine) as conn:
        ev = conn.execute(sa.select(round_evaluations).where(
            round_evaluations.c.round_id == w["round"]).order_by(round_evaluations.c.id.desc())
        ).first()  # fmt: skip
    assert (ev.total_predictions, ev.played_predictions, ev.ranked_entries) == (45, 36, 4)
    winner = st.personal_result(engine, principal(engine, user_id=w["users"][0]), w["round"])
    assert winner.round_void and winner.gross == Decimal("100.00") and winner.net == 0
    assert winner.recovered is False  # a void round records no recovery


def test_competitive_round_with_five_rank_eligible_entries_passes(engine, op, d32b):
    w = d32b[1]
    finish(engine, w, DEFAULT_ENTRY, WIN.get)
    finish(engine, w, shifted(9), WIN.get)
    res = st.settle_round(engine, op, w["round"])
    assert res.outcome == "pass" and res.designation == "championship"
    with transaction(engine) as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(designations).where(
            designations.c.round_id == w["round"])).scalar_one()  # fmt: skip
    assert n == 1  # only the lock's base designation: nothing changed
    pr = st.personal_result(engine, principal(engine, user_id=w["users"][0]), w["round"])
    assert pr.recovered is True and pr.rank_eligible is True


def test_exactly_half_played_fails_the_majority_rule(engine, op, d32b):
    w = d32b[2]  # practice: 18 prediction instances
    assert _designation(engine, w["round"]).designation == "practice"
    allfix = sorted(set(DEFAULT_ENTRY) | set(shifted(3)))
    void_ids = {0, 1, 2, 3, 4, 5}  # entry 1 loses 6, entry 2 loses 3: 9 of 18
    finish(engine, w, [x for x in allfix if x[0] in void_ids], lambda o: "CANC")
    finish(engine, w, [x for x in allfix if x[0] not in void_ids], WIN.get)
    res = st.settle_round(engine, op, w["round"])
    assert res.outcome == "fail_majority" and res.designation == "void"


def test_practice_round_has_no_five_entry_requirement(engine, op, d32b):
    w = d32b[3]
    finish(engine, w, DEFAULT_ENTRY[:5], WIN.get)
    finish(engine, w, DEFAULT_ENTRY[5:], lambda o: "CANC")  # 5 played of 9
    res = st.settle_round(engine, op, w["round"])
    assert res.outcome == "pass" and res.designation == "practice"
