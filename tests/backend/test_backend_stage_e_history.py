"""Phase 6C.5 Stage E: My Challenge History, personal statistics (§9.4), chart
series, the weekly round selector and their privacy, on their own PostgreSQL
database (two-round championships for this database only).

Viewer u0:
* R1 competitive: wins (150).
* R2 practice (three entries): wins.
* R3 competitive: refunded (all nine predictions void).
* R4 void (D-32b).
* R5 competitive: does not recover.
* R6 competitive: not entered (missed).

Championship A = R1, R2 (practice), R3. Championship B = R4 (void), R5, R6."""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from champ_helpers import (
    REFUND,
    WIN,
    build,
    drop,
    finalise,
    fresh,
    isolated_engine,
    lose,
    operator,
    owner,
    prepare,
    set_required,
    users,
    void_majority,
    winner,
)
from svc_helpers import principal

from diski9.backend.auth.permissions import GUEST
from diski9.backend.db import transaction
from diski9.backend.services import challenge_history as ch
from diski9.backend.services import corrections as co
from diski9.backend.services import leaderboards as lb
from diski9.backend.services.common import NotFound

DB = "diski9_stage_e_hist_test"
A, B = "Championship Nov-26", "Championship Nov-26 (2)"


@pytest.fixture(scope="module")
def world(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    set_required(eng, 2)
    op = operator(eng)
    u = users(eng, 6)

    def comp(mine, win):
        return [(u[0], mine)] + [(u[i], WIN if i == win else lose(i)) for i in range(1, 6)]

    plan = [
        comp(WIN, None),  # R1
        [(u[0], WIN), (u[1], lose(1)), (u[2], lose(2))],  # R2 practice
        comp(REFUND, 1),  # R3
        comp(lose(0), 2),  # R4 (void)
        comp(lose(0), 2),  # R5
        [(u[i], WIN if i == 3 else lose(i)) for i in range(1, 6)],  # R6: u0 missed
    ]
    made = build(eng, plan)
    prepare(eng, op, made, [winner, winner, winner, void_majority, winner, winner])
    for w in made:
        finalise(eng, op, w)
    codes = []
    with transaction(eng) as conn:
        for w in made:
            codes.append(conn.execute(sa.text("SELECT code FROM app.rounds WHERE id = :r"),
                                      {"r": w["round"]}).scalar_one())  # fmt: skip
    yield {"engine": eng, "op": op, "u": u, "w": made, "codes": codes}
    eng.dispose()
    drop(pg_url, DB)


def me(world, i=0):
    return principal(world["engine"], user_id=world["u"][i])


def counts(eng):
    with transaction(eng) as conn:
        return conn.execute(sa.text(
            "SELECT (SELECT count(*) FROM app.score_sets), (SELECT count(*) FROM "
            "app.championship_versions), (SELECT count(*) FROM app.audit_log)")).one()  # fmt: skip


def test_statistics_follow_the_approved_definitions(world):
    eng = world["engine"]
    before = counts(eng)
    s = ch.my_statistics(eng, me(world), stream="development", include_development=True)
    assert (s.counted_rounds, s.played, s.missed, s.refunded_entries) == (4, 2, 1, 1)
    assert s.recoveries == 1 and s.recovery_rate == Decimal("0.5000")  # refunds excluded
    assert s.qualifying_top10 == 1 and s.allocated == Decimal("200.00")
    assert s.net == s.returned - s.allocated
    assert s.roi == (s.net / s.allocated).quantize(Decimal("0.0001"))  # aggregate, not averaged
    assert (s.practice_entries, s.practice_recoveries, s.void_rounds) == (1, 1, 1)
    assert s.awaiting_results == 0 and not s.under_review
    assert [x.name for x in s.standings] == [B, A]  # each championship separately, newest first
    a = next(x for x in s.standings if x.name == A)
    assert (a.rank, a.points, a.status) == (1, 150, "completed")
    # chart 1: the competitive population only (R1 and R5), cumulative
    assert [p.value_a for p in s.allocation_series] == [Decimal("100.00"), Decimal("200.00")]
    assert s.allocation_series[-1].value_b == s.returned
    # chart 2 (all championships): the newest championship only, never summed across two
    assert s.points_championship == B
    assert [x.detail for x in s.points_series] == ["0 points", "not entered"]
    assert counts(eng) == before  # read-only


def test_statistics_for_one_championship(world):
    eng = world["engine"]
    s = ch.my_statistics(eng, me(world), stream="development", championship=A,
                         include_development=True)  # fmt: skip
    assert (s.counted_rounds, s.played, s.missed, s.refunded_entries) == (2, 1, 0, 1)
    assert s.recovery_rate == Decimal("1.0000") and s.points_championship == A
    assert [(p.value_a, p.detail) for p in s.points_series] == [
        (Decimal(150), "150 points"),
        (Decimal(150), "refunded"),
    ]
    with pytest.raises(NotFound):
        ch.my_statistics(eng, me(world), stream="development", championship="Championship Jan-99",
                         include_development=True)  # fmt: skip


def test_zero_denominators_give_no_percentage(world):
    eng = world["engine"]
    nobody = principal(eng)  # a signed-in participant with no entries
    s = ch.my_statistics(eng, nobody, stream="development", include_development=True)
    assert (s.played, s.recovery_rate, s.roi, s.allocated) == (0, None, None, Decimal("0.00"))
    assert s.allocation_series == () and s.points_series == () and s.standings == ()


def test_history_lists_every_own_entry_newest_first(world):
    eng = world["engine"]
    h = ch.my_history(eng, me(world), stream="development", include_development=True)
    c = world["codes"]
    assert h.total == 5 and [r.round_code for r in h.rows] == [c[4], c[3], c[2], c[1], c[0]]
    r5, r4, r3, r2, r1 = h.rows
    assert (r1.classification, r1.rank, r1.weekly_points, r1.recovery) == (
        "competitive", 1, 150, "recovered")  # fmt: skip
    assert r1.championship == A and r1.counts_toward_championship is True
    assert (r2.classification, r2.weekly_points, r2.championship_role) == (
        "practice", None, "practice")  # fmt: skip
    assert r3.entry_refunded and r3.recovery == "refunded" and r3.rank is None
    assert r4.round_void and r4.recovery == "round_refund" and r4.championship_role == "void"
    assert r5.recovery == "not_recovered" and r5.weekly_points == 0
    assert all(r.state == "final" and r.published for r in h.rows)
    # bounded pages
    p = ch.my_history(eng, me(world), stream="development", page=2, page_size=2,
                      include_development=True)  # fmt: skip
    assert (p.page, p.pages, len(p.rows)) == (2, 3, 2)
    assert ch.my_history(eng, me(world), stream="development", championship=B,
                         include_development=True).total == 2  # fmt: skip


def test_history_is_private_and_stream_isolated(world):
    eng = world["engine"]
    c = world["codes"]
    assert ch.my_history(eng, GUEST, stream="development", include_development=True) is None
    assert ch.my_statistics(eng, GUEST, stream="development", include_development=True) is None
    with pytest.raises(NotFound):  # development is not visible without the setting
        ch.my_history(eng, me(world), stream="development")
    assert ch.my_history(eng, me(world), stream="beta").total == 0  # no beta entries
    # drill-down codes resolve only for the viewer's own entries, in the right stream
    assert (
        ch.my_round_code_visible(
            eng, me(world), c[0], stream="development", include_development=True
        )
        == world["w"][0]["round"]
    )
    assert (
        ch.my_round_code_visible(
            eng, me(world), c[5], stream="development", include_development=True
        )
        is None
    )  # not entered
    assert ch.my_round_code_visible(eng, me(world), c[0], stream="beta") is None
    assert (
        ch.my_round_code_visible(eng, GUEST, c[0], stream="development", include_development=True)
        is None
    )
    other = ch.my_history(eng, me(world, 3), stream="development", include_development=True)
    assert all(r.round_code in c for r in other.rows) and other.total == 5  # its own entries


def test_weekly_round_selector(world):
    eng = world["engine"]
    rounds = lb.round_list(eng, stream="development", include_development=True)
    assert [r.code for r in rounds] == list(reversed(world["codes"]))  # newest deadline first
    assert all(r.has_results and r.status == "final" for r in rounds)
    assert lb.default_round(rounds).code == world["codes"][-1]
    assert lb.default_round(()) is None
    assert (
        lb.round_id_for(eng, world["codes"][0], stream="development", include_development=True)
        == world["w"][0]["round"]
    )
    assert lb.round_id_for(eng, world["codes"][0], stream="beta") is None  # other stream
    with pytest.raises(NotFound):
        lb.round_list(eng, stream="development")
    assert lb.stream_options(eng) == ("beta",)
    assert lb.stream_options(eng, include_development=True) == ("beta", "development")
    wb = lb.weekly_board(eng, world["w"][0]["round"], include_development=True)
    assert (wb.championship, wb.championship_round, wb.championship_rounds_required) == (A, 1, 2)


def test_reopened_round_is_marked_under_review_with_published_values(world):
    eng, op = world["engine"], world["op"]
    o = fresh(eng, owner(eng))
    rid = world["w"][4]["round"]
    imp = co.preview_reopen(eng, o, rid)
    co.reopen_round(eng, o, rid, reason="review", evidence="statement", confirmation=imp.token)
    h = ch.my_history(eng, me(world), stream="development", include_development=True)
    r5 = h.rows[0]
    assert r5.state == "under_review" and r5.published and r5.weekly_points == 0
    assert r5.current_gross is not None  # current settlement, labelled separately in the UI
    s = ch.my_statistics(eng, me(world), stream="development", include_development=True)
    assert s.under_review and s.played == 2  # published values still used
    finalise(eng, fresh(eng, op), world["w"][4])
