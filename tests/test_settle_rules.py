"""`settle/v1` (amended 19 Nov 2026) as pure rules: verdict order, completion-based
cutoff, V3 branches, evidence handling and alerts. No database, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from diski9.challenge.settle import (
    KNOWN_STATUSES,
    Observation,
    SettlementInputError,
    outcome_wins,
    resolve_fixture,
)

D = datetime(2026, 11, 27, 18, 45, tzinfo=UTC)  # deadline
C = datetime(2026, 11, 30, 21, 0, tzinfo=UTC)  # settlement cutoff
KO = D + timedelta(hours=20)  # scheduled kickoff (after the deadline)
SEL = (("1X2", "HOME"), ("BTTS", "BTTS_YES"), ("OU25", "UNDER_2_5"))
_ids = iter(range(1, 10_000))


def obs(at, status, *, ko=KO, h=None, a=None, src="api-football", **kw):
    return Observation(next(_ids), src, at, status, ko, h, a, **kw)


def op(at, status, *, h=None, a=None, **kw):
    return Observation(next(_ids), "operator", at, status, kw.pop("ko", None), h, a, **kw)


def resolve(observations, *, at=C + timedelta(days=1), sel=SEL):
    return resolve_fixture(7, observations, sel, deadline_at=D, settle_cutoff_at=C, evaluated_at=at)


def codes(r):
    return {a.code for a in r.alerts}


def blocking(r):
    return {a.code for a in r.alerts if a.blocking}


# ------------------------------------------------------------------ markets
@pytest.mark.parametrize(
    ("h", "a", "won"),
    [
        (2, 1, {"HOME", "BTTS_YES", "OVER_2_5"}),
        (1, 1, {"DRAW", "BTTS_YES", "UNDER_2_5"}),
        (0, 0, {"DRAW", "BTTS_NO", "UNDER_2_5"}),
        (0, 3, {"AWAY", "BTTS_NO", "OVER_2_5"}),
        (3, 0, {"HOME", "BTTS_NO", "OVER_2_5"}),
        (1, 2, {"AWAY", "BTTS_YES", "OVER_2_5"}),
        (2, 0, {"HOME", "BTTS_NO", "UNDER_2_5"}),
    ],
)
def test_all_seven_outcomes_on_the_90_minute_score(h, a, won):
    allx = {
        ("1X2", "HOME"), ("1X2", "DRAW"), ("1X2", "AWAY"), ("BTTS", "BTTS_YES"),
        ("BTTS", "BTTS_NO"), ("OU25", "OVER_2_5"), ("OU25", "UNDER_2_5"),
    }  # fmt: skip
    assert {o for m, o in allx if outcome_wins(m, o, h, a)} == won


def test_unsupported_outcomes_and_negative_scores_are_refused():
    with pytest.raises(SettlementInputError):
        outcome_wins("1X2", "OVER_2_5", 1, 0)
    with pytest.raises(SettlementInputError):
        outcome_wins("1X2", "HOME", -1, 0)


def test_aet_and_pen_settle_on_the_90_minute_score():
    for st in ("AET", "PEN"):
        r = resolve([obs(KO + timedelta(hours=3), st, h=1, a=1)])
        assert r.rule == "settle" and r.verdict_for("1X2", "HOME").verdict == "lost"


# ------------------------------------------------------------------ completion by the cutoff
def test_ordinary_match_settles_without_any_actual_kickoff_evidence():
    r = resolve([obs(KO - timedelta(hours=1), "NS"), obs(KO + timedelta(hours=2), "FT", h=2, a=1)])
    assert r.rule == "settle" and not r.alerts
    assert [v.verdict for v in r.verdicts] == ["won", "won", "lost"]


def test_final_recorded_exactly_at_the_cutoff_completes_it():
    r = resolve([obs(C, "FT", h=0, a=0)])
    assert r.rule == "settle"


def test_final_recorded_one_second_after_the_cutoff_is_void_with_a_blocking_alert():
    r = resolve([obs(C - timedelta(hours=1), "2H"), obs(C + timedelta(seconds=1), "FT", h=0, a=0)])
    assert r.rule == "V1-catch-all"  # still in play at the cutoff
    assert "late_notification" in blocking(r) and "catch_all_void" in codes(r)
    assert all(v.verdict == "void" and v.void_code == "V1" for v in r.verdicts)


def test_match_started_before_cutoff_and_completed_after_is_void():
    r = resolve(
        [obs(C - timedelta(minutes=50), "1H"), obs(C + timedelta(minutes=70), "FT", h=1, a=0)]
    )
    assert r.rule == "V1-catch-all" and "late_notification" in blocking(r)


def test_delayed_notification_settles_only_after_an_audited_verified_completion():
    late = [obs(C - timedelta(days=1), "NS"), obs(C + timedelta(hours=6), "FT", h=2, a=0)]
    assert resolve(late).rule == "V1-catch-all"
    corrected = late + [
        op(C + timedelta(hours=7), "FT", h=2, a=0, completed_at=C - timedelta(hours=5),
           corrects_id=late[-1].id)
    ]  # fmt: skip
    r = resolve(corrected)
    assert r.rule == "settle" and r.verdict_for("1X2", "HOME").verdict == "won"
    assert "late_notification" not in codes(r)


def test_operator_completion_after_the_cutoff_does_not_make_it_eligible():
    late = [obs(C + timedelta(hours=6), "FT", h=2, a=0)]
    r = resolve(late + [op(C + timedelta(hours=7), "FT", h=2, a=0,
                           completed_at=C + timedelta(minutes=1))])  # fmt: skip
    assert r.verdicts[0].verdict == "void"


def test_same_evidence_gives_the_same_result_whenever_it_is_evaluated():
    ev = [
        obs(C - timedelta(hours=3), "PST"),
        obs(C + timedelta(hours=1), "FT", h=3, a=1),
        obs(C + timedelta(days=2), "FT", h=3, a=1),
    ]
    results = {
        (r.rule, tuple(v.verdict for v in r.verdicts), frozenset(codes(r)))
        for r in (resolve(ev, at=C + timedelta(days=d)) for d in (3, 10, 400))
    }
    assert len(results) == 1


def test_evaluation_before_the_cutoff_never_voids_for_lateness():
    r = resolve([obs(D + timedelta(hours=30), "PST")], at=C - timedelta(seconds=1))
    assert r.rule == "pending" and not r.alerts


def test_status_at_the_cutoff_decides_the_void_rule():
    pst = resolve([obs(C - timedelta(hours=1), "PST"), obs(C + timedelta(hours=1), "ABD")])
    assert pst.rule == "V1"
    susp = resolve([obs(C - timedelta(hours=1), "SUSP"), obs(C + timedelta(hours=1), "PST")])
    assert susp.rule == "V4"
    for st in ("ABD", "INT"):
        assert resolve([obs(C - timedelta(hours=1), st)]).rule == "V4"


def test_rescheduled_beyond_the_cutoff_is_v1():
    r = resolve([obs(C - timedelta(days=2), "NS", ko=C + timedelta(days=4))])
    assert r.rule == "V1"


def test_nothing_recorded_is_pending_before_and_catch_all_after():
    assert resolve([], at=C).rule == "pending"
    r = resolve([])
    assert r.rule == "V1-catch-all" and "catch_all_void" in codes(r)
    assert not blocking(r)


def test_v5_completed_after_postponement_or_suspension():
    ev = [
        obs(KO, "PST"),
        obs(KO + timedelta(days=1), "SUSP"),
        obs(C - timedelta(hours=1), "FT", h=0, a=2),
    ]
    r = resolve(ev)
    assert r.rule == "settle-v5" and r.verdict_for("1X2", "HOME").verdict == "lost"


# ------------------------------------------------------------------ V2 and precedence
@pytest.mark.parametrize("st", ["CANC", "AWD", "WO"])
def test_no_genuine_result_is_v2_even_before_the_cutoff(st):
    r = resolve([obs(KO, st, h=3, a=0)], at=KO + timedelta(hours=1))
    assert r.rule == "V2"


def test_v3_precedes_v2_and_settlement():
    ev = [obs(D - timedelta(minutes=1), "1H"), obs(KO, "FT", h=1, a=0)]
    assert resolve(ev).rule == "V3-started"
    ev = [obs(D - timedelta(minutes=1), "1H"), obs(KO, "CANC")]
    assert resolve(ev).rule == "V3-started"


# ------------------------------------------------------------------ V3 branches
def test_in_play_recorded_before_the_deadline_is_v3_started():
    r = resolve([obs(D - timedelta(seconds=1), "HT"), obs(KO, "FT", h=1, a=1)])
    assert r.rule == "V3-started" and all(v.void_code == "V3" for v in r.verdicts)


def test_in_play_recorded_exactly_at_the_deadline_is_not_before_it():
    r = resolve([obs(D, "1H"), obs(D + timedelta(hours=2), "FT", h=1, a=1)])
    assert r.rule == "settle"


def test_consistent_revised_schedule_before_the_deadline_is_v3_rescheduled():
    early = D - timedelta(hours=2)
    r = resolve(
        [
            obs(D - timedelta(days=1), "NS", ko=early),
            obs(D + timedelta(hours=1), "FT", ko=early, h=1, a=0),
        ]
    )
    assert r.rule == "V3-rescheduled" and not blocking(r)


def test_contradictory_schedules_hold_pending_with_a_blocking_alert():
    ev = [
        obs(D - timedelta(days=1), "NS", ko=D - timedelta(hours=2)),
        obs(D + timedelta(hours=1), "NS", ko=KO),
        obs(KO + timedelta(hours=2), "FT", h=2, a=2),
    ]
    r = resolve(ev)
    assert r.rule == "pending" and "schedule_conflict" in blocking(r)
    fixed = ev + [op(KO + timedelta(hours=3), "FT", h=2, a=2, ko=KO,
                     corrects_id=ev[-1].id)]  # fmt: skip
    assert resolve(fixed).rule == "settle"


def test_first_half_start_alone_never_decides_v3():
    ev = [
        obs(D + timedelta(hours=1), "NS", provider_first_half_at=D - timedelta(minutes=5)),
        obs(KO + timedelta(hours=2), "FT", h=1, a=0),
    ]
    r = resolve(ev)
    assert r.rule == "pending" and "early_start_unverified" in blocking(r)
    confirmed = ev + [op(KO + timedelta(hours=3), "FT", h=1, a=0,
                         actual_kickoff_at=D - timedelta(minutes=5))]  # fmt: skip
    assert resolve(confirmed).rule == "V3-started"
    rejected = ev + [op(KO + timedelta(hours=3), "FT", h=1, a=0, actual_kickoff_at=KO)]
    assert resolve(rejected).rule == "settle"


def test_first_half_start_corroborated_by_our_observation_is_v3_without_alert():
    ev = [obs(D - timedelta(minutes=2), "1H", provider_first_half_at=D - timedelta(minutes=10))]
    r = resolve(ev)
    assert r.rule == "V3-started" and not r.alerts


def test_matching_scheduled_first_half_is_not_treated_as_evidence_of_a_breach():
    r = resolve([obs(KO + timedelta(hours=2), "FT", h=1, a=0, provider_first_half_at=KO)])
    assert r.rule == "settle" and not r.alerts


# ------------------------------------------------------------------ conflicts and quirks
def test_unknown_status_is_pending_and_blocking_before_the_cutoff():
    r = resolve([obs(KO, "XYZ")], at=KO + timedelta(hours=1))
    assert r.rule == "pending" and "unknown_status" in blocking(r)
    assert "XYZ" not in KNOWN_STATUSES


def test_unknown_status_after_the_cutoff_is_catch_all_and_still_blocking():
    r = resolve([obs(C - timedelta(hours=1), "XYZ")])
    assert r.rule == "V1-catch-all" and "unknown_status" in blocking(r)


def test_final_without_score_stays_pending_with_a_blocking_alert():
    r = resolve([obs(KO + timedelta(hours=2), "FT")])
    assert r.rule == "pending" and "missing_score" in blocking(r)


def test_final_score_arriving_after_the_cutoff_still_settles():
    r = resolve([obs(C - timedelta(hours=1), "FT"), obs(C + timedelta(hours=1), "FT", h=0, a=1)])
    assert r.rule == "settle" and r.score == (0, 1)


def test_regression_from_final_to_not_started_is_held_pending():
    r = resolve([obs(KO + timedelta(hours=2), "FT", h=1, a=0), obs(KO + timedelta(hours=3), "NS")])
    assert r.rule == "pending" and "status_regression" in blocking(r)


def test_a_b_a_sequence_resolves_on_the_latest_state():
    ev = [
        obs(KO + timedelta(hours=2), "FT", h=1, a=0),
        obs(KO + timedelta(hours=3), "NS"),
        obs(KO + timedelta(hours=4), "FT", h=1, a=0),
    ]
    r = resolve(ev)
    assert r.rule == "settle" and not blocking(r)


def test_material_score_conflict_keeps_the_first_score_and_blocks():
    ev = [
        obs(KO + timedelta(hours=2), "FT", h=1, a=0),
        obs(KO + timedelta(hours=3), "FT", h=1, a=1),
    ]
    r = resolve(ev)
    assert r.score == (1, 0) and "score_conflict" in blocking(r)
    assert r.verdict_for("1X2", "HOME").verdict == "won"


def test_score_change_that_alters_no_selected_verdict_is_informational():
    ev = [
        obs(KO + timedelta(hours=2), "FT", h=2, a=0),
        obs(KO + timedelta(hours=3), "FT", h=3, a=0),
    ]
    r = resolve(ev, sel=(("1X2", "HOME"),))
    assert r.score == (3, 0) and codes(r) == {"score_corrected"} and not blocking(r)


def test_out_of_order_commit_cannot_override_newer_evidence():
    newer = obs(KO + timedelta(hours=3), "FT", h=2, a=2)
    older = Observation(newer.id + 1, "api-football", KO + timedelta(hours=1), "2H", KO)
    r = resolve([newer, older])  # older committed later (higher id) but observed earlier
    assert r.rule == "settle" and r.deciding_observation_id == newer.id


def test_withdrawn_operator_correction_no_longer_applies():
    base = obs(KO + timedelta(hours=2), "FT", h=0, a=0)
    corr = op(KO + timedelta(hours=3), "FT", h=1, a=0, corrects_id=base.id)
    wd = op(KO + timedelta(hours=4), None, withdraws_id=corr.id)
    assert resolve([base, corr]).score == (1, 0)
    assert resolve([base, corr, wd]).score == (0, 0)


def test_evidence_after_the_evaluation_time_is_ignored():
    ev = [obs(KO + timedelta(hours=2), "FT", h=1, a=0)]
    assert resolve(ev, at=KO + timedelta(hours=1)).rule == "pending"


def test_unselected_fixture_resolves_with_no_verdicts():
    r = resolve([obs(KO + timedelta(hours=2), "FT", h=1, a=0)], sel=())
    assert r.rule == "settle" and r.verdicts == ()


def test_deadline_must_precede_cutoff():
    with pytest.raises(SettlementInputError):
        resolve_fixture(1, [], (), deadline_at=C, settle_cutoff_at=D, evaluated_at=C)
