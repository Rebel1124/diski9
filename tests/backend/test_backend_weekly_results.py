"""Phase 6C.5 Stage B: official weekly results and provisional standings on real
PostgreSQL, through the real Phase 6C.4 settlement, finalisation and reopening
services (development rounds with synthetic results and the development time
override; nothing is mocked except where a failure is injected on purpose)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from settle_helpers import DEFAULT_ENTRY, settlement_world, settlement_worlds, shifted
from svc_helpers import principal, wait_until

from diski9.backend.auth import accounts
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import (
    audit_log,
    domain_events,
    entries,
    round_scores,
    rounds,
    score_sets,
    settlement_versions,
)
from diski9.backend.services import competition as comp
from diski9.backend.services import corrections as co
from diski9.backend.services import leaderboards as lb
from diski9.backend.services import results as rs
from diski9.backend.services import settlement as st
from diski9.backend.services.common import NotFound
from diski9.challenge import scoring

ENGINE: list = []


def rot(r: int) -> tuple:
    """The default 4/3/2 structure rotated over fixtures 0..8 (distinct portfolios
    on the same nine matches)."""
    return tuple(((j + r) % 9, m, o) for j, (_, m, o) in enumerate(DEFAULT_ENTRY))


def mixed(i: int):
    return [(1, 0), (1, 1), (0, 1), (0, 0)][i % 4]


WINNER = {0: (1, 0), 1: (1, 0), 2: (1, 0), 3: (1, 0), 4: (1, 1), 5: (1, 1), 6: (0, 0),
          7: (0, 1), 8: (0, 1)}  # fmt: skip


def winner(i: int):
    """Every prediction of ``rot(0)`` wins (a large return); other rotations mostly lose."""
    return WINNER.get(i, (1, 0))


def fresh(p):
    with transaction(ENGINE[0]) as conn:
        now = db_now(conn)
    return replace(p, authenticated_at=now, reauthenticated_at=now, now=now)


@pytest.fixture(scope="module", autouse=True)
def _engine(engine):
    ENGINE[:] = [engine]
    lb.clear_cache()


@pytest.fixture(scope="module")
def op(engine):
    return fresh(principal(engine, role="operator"))


@pytest.fixture(scope="module")
def owner(engine):
    return fresh(principal(engine, role="owner"))


def record_results(engine, op, w, result_of, *, settle=True):
    """Synthetic results for every fixture (``None`` = no result yet), then settle."""
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    at = w["deadline"] + timedelta(milliseconds=1500)
    ko = w["deadline"] + timedelta(seconds=1)
    wait_until(engine, at)
    for i, fid in enumerate(w["fixtures"]):
        res = result_of(i)
        if res is None:
            continue
        if res == "CANC":
            rs.record_synthetic_observation(engine, op, w["round"], fid, observed_at=at,
                                            status="CANC", kickoff_at=ko)  # fmt: skip
        else:
            rs.record_synthetic_observation(engine, op, w["round"], fid, observed_at=at,
                                            status="FT", kickoff_at=ko, ft_home=res[0],
                                            ft_away=res[1])  # fmt: skip


def settle(engine, op, w):
    wait_until(engine, w["cutoff"] + timedelta(milliseconds=200))
    res = st.settle_round(engine, op, w["round"])
    w["earliest"] = res.earliest_finalisation
    return res


def finalise(engine, op, w):
    with transaction(engine) as conn:
        earliest = st.earliest_finalisation(
            conn, conn.execute(sa.select(rounds).where(rounds.c.id == w["round"])).one()
        )
    out = co.finalise_round(engine, op, w["round"], as_of=earliest)
    assert out.finalised, out.reason
    return out


def score_sets_of(engine, rid):
    with transaction(engine) as conn:
        return conn.execute(
            sa.select(score_sets)
            .where(score_sets.c.round_id == rid)
            .order_by(score_sets.c.revision)
        ).all()


def scores_of(engine, set_id):
    with transaction(engine) as conn:
        return conn.execute(
            sa.select(round_scores).where(round_scores.c.score_set_id == set_id)
            .order_by(round_scores.c.display_order)
        ).all()  # fmt: skip


def expected(engine, rid):
    """An independent recomputation from the authoritative settlement tables."""
    with transaction(engine) as conn:
        d = comp.current_designation_row(conn, rid)
        recs = comp.locked_records(conn, rid)
    return scoring.score_round(comp.round_result(rid, d.designation, "points-150-75-v2", recs))


def same(engine, set_id, rid):
    rows = scores_of(engine, set_id)
    exp = expected(engine, rid)
    assert [(str(r.entry_id), r.gross, r.rank, r.points, r.recovered, r.qualifying_top10,
             r.display_order) for r in rows] == [
        (s.participant_id, s.gross, s.rank, s.points, s.recovered, s.qualifying_top10,
         s.display_order) for s in exp.scores]  # fmt: skip
    return rows


# ------------------------------------------------------------------ worlds
COMPETITIVE = [rot(r) for r in range(9)] + [rot(0), rot(0), rot(3)]  # 12 entries, ties
REFUND = [rot(r) for r in range(5)] + [shifted(9)]  # the last entry's matches are all cancelled
PRACTICE = [rot(0), rot(0), rot(4)]
VOID = [rot(r) for r in range(5)]
MECH = [rot(r) for r in range(5)]


@pytest.fixture(scope="module")
def worlds(engine, op):
    made = settlement_worlds(
        engine,
        [COMPETITIVE, REFUND, PRACTICE, VOID, MECH, MECH, PRACTICE],
        development=True,
        cutoff_after=timedelta(seconds=4),
    )
    names = ["competitive", "refund", "practice", "void", "mech", "conc", "legacy"]
    w = dict(zip(names, made, strict=True))
    for k in ("competitive", "mech", "conc"):
        record_results(engine, op, w[k], winner)
    for k in ("practice", "legacy"):
        record_results(engine, op, w[k], mixed)
    record_results(engine, op, w["refund"], lambda i: "CANC" if i >= 9 else mixed(i))
    record_results(engine, op, w["void"], lambda i: "CANC" if i < 6 else mixed(i))
    for k in names:
        settle(engine, op, w[k])
    return w


# ------------------------------------------------------------------ publication
def test_nothing_is_published_before_finalisation(engine, op, worlds):
    w = worlds["competitive"]
    assert score_sets_of(engine, w["round"]) == []
    early = co.finalise_round(engine, op, w["round"],
                              as_of=w["earliest"] - timedelta(seconds=1))  # fmt: skip
    assert not early.finalised and score_sets_of(engine, w["round"]) == []


def test_competitive_round_publishes_exactly_the_engine_result(engine, op, worlds):
    w = worlds["competitive"]
    out = finalise(engine, op, w)
    (ss,) = score_sets_of(engine, w["round"])
    rows = same(engine, ss.id, w["round"])
    assert ss.kind == "championship" and ss.revision == 1 and ss.final
    assert ss.scoring_version == "points-150-75-v2" and ss.actor_user_id == op.user_id
    with transaction(engine) as conn:
        v = conn.execute(sa.select(settlement_versions).where(
            settlement_versions.c.id == ss.settlement_version_id)).one()  # fmt: skip
        assert (v.kind, v.version, v.run_id) == ("final", out.version, ss.run_id)
        assert (
            conn.execute(
                sa.select(audit_log.c.after).where(
                    audit_log.c.action == "competition.publish",
                    audit_log.c.target_id == str(w["round"]),
                )
            ).scalar_one()["score_set_id"]
            == ss.id
        )
        assert conn.execute(sa.select(sa.func.count()).select_from(domain_events).where(
            domain_events.c.kind == "weekly_results_published",
            domain_events.c.round_id == w["round"])).scalar_one() == 1  # fmt: skip
    assert len(rows) == len(COMPETITIVE)
    # identical portfolios have identical returns, so they share a rank and its points
    by_entry = {r.entry_id: r for r in rows}
    twins = [by_entry[w["entries"][k]] for k in (0, 9, 10)]
    assert len({(t.gross, t.rank, t.points) for t in twins}) == 1
    assert all(r.points == 0 for r in rows if r.gross < Decimal("100.00"))
    top = [r for r in rows if r.rank == 1]
    assert len(top) == 3 and {r.points for r in top} == {150}  # three shared first places
    assert all((r.gross >= Decimal("100.00")) == r.recovered for r in rows)


def test_refunded_entry_is_published_unranked(engine, op, worlds):
    w = worlds["refund"]
    finalise(engine, op, w)
    (ss,) = score_sets_of(engine, w["round"])
    rows = same(engine, ss.id, w["round"])
    refund = next(r for r in rows if r.entry_id == w["entries"][5])
    assert refund.status == "void_refunded" and refund.rank is None and refund.points == 0
    assert refund.gross == Decimal("100.00") and not refund.recovered
    assert sorted(r.rank for r in rows if r.rank) == sorted(
        scoring.competition_ranks([r.gross for r in rows if r.status == "ranked"])
    )


def test_practice_round_has_ranks_but_no_points(engine, op, worlds):
    w = worlds["practice"]
    finalise(engine, op, w)
    (ss,) = score_sets_of(engine, w["round"])
    rows = same(engine, ss.id, w["round"])
    assert ss.kind == "practice" and {r.points for r in rows} == {0}
    by_entry = {r.entry_id: r for r in rows}
    assert by_entry[w["entries"][0]].rank == by_entry[w["entries"][1]].rank  # identical portfolios


def test_invalidated_round_refunds_everyone(engine, op, worlds):
    w = worlds["void"]
    finalise(engine, op, w)
    (ss,) = score_sets_of(engine, w["round"])
    rows = same(engine, ss.id, w["round"])
    assert ss.kind == "void"
    assert {(r.status, r.gross, r.rank, r.points, r.recovered) for r in rows} == {
        ("round_void", Decimal("100.00"), None, 0, False)
    }


def test_publication_is_idempotent_and_never_duplicated(engine, op, worlds):
    w = worlds["competitive"]
    (ss,) = score_sets_of(engine, w["round"])
    with pytest.raises(co.CorrectionRefused):  # a final round is never finalised again
        co.finalise_round(engine, op, w["round"], as_of=w["earliest"] + timedelta(days=1))
    with transaction(engine) as conn:  # direct re-publication of the same version: no-op
        p = comp.publish_finalised(conn, w["round"], ss.settlement_version_id, actor=op.user_id)
    assert not p.created and p.score_set_id == ss.id
    assert len(score_sets_of(engine, w["round"])) == 1


def test_failure_during_publication_rolls_back_the_finalisation(engine, op, worlds, monkeypatch):
    w = worlds["mech"]

    def boom(conn, rows):
        raise RuntimeError("injected failure after the score set insert")

    monkeypatch.setattr(comp, "_insert_scores", boom)
    with pytest.raises(RuntimeError, match="injected"):
        finalise(engine, op, w)
    with transaction(engine) as conn:
        r = conn.execute(sa.select(rounds).where(rounds.c.id == w["round"])).one()
        kinds = conn.execute(sa.select(settlement_versions.c.kind).where(
            settlement_versions.c.round_id == w["round"])).scalars().all()  # fmt: skip
    assert r.status == "settling" and r.finalised_at is None and "final" not in kinds
    assert score_sets_of(engine, w["round"]) == []
    monkeypatch.undo()
    finalise(engine, op, w)  # a retry succeeds
    (ss,) = score_sets_of(engine, w["round"])
    same(engine, ss.id, w["round"])


def test_concurrent_finalisation_publishes_once(engine, op, worlds):
    w = worlds["conc"]
    with transaction(engine) as conn:
        earliest = st.earliest_finalisation(
            conn, conn.execute(sa.select(rounds).where(rounds.c.id == w["round"])).one()
        )
    outcomes = []

    def go():
        try:
            outcomes.append(co.finalise_round(engine, op, w["round"], as_of=earliest).finalised)
        except co.CorrectionRefused:
            outcomes.append("refused")

    threads = [threading.Thread(target=go) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count(True) == 1 and outcomes.count("refused") == 2
    assert len(score_sets_of(engine, w["round"])) == 1


def test_publication_refuses_non_authoritative_states(engine, op, worlds):
    w = worlds["mech"]
    (ss,) = score_sets_of(engine, w["round"])
    other = worlds["competitive"]
    with pytest.raises(comp.PublicationRefused), transaction(engine) as conn:
        comp.publish_finalised(conn, other["round"], ss.settlement_version_id, actor=None)
    with transaction(engine) as conn:  # a provisional version is never published
        prov = conn.execute(sa.select(settlement_versions.c.id).where(
            settlement_versions.c.round_id == w["round"],
            settlement_versions.c.kind == "provisional")).scalars().first()  # fmt: skip
    with (
        pytest.raises(comp.PublicationRefused, match="final settlement version"),
        transaction(engine) as conn,
    ):
        comp.publish_finalised(conn, w["round"], prov, actor=None)
    assert len(score_sets_of(engine, w["round"])) == 1


def test_database_refuses_inconsistent_results(engine, worlds):
    w = worlds["competitive"]
    (ss,) = score_sets_of(engine, w["round"])
    row = scores_of(engine, ss.id)[0]
    bad = [
        {"points": 80},  # not a D-31 value
        {"status": "round_void"},  # round_void only in a void set
        {"rank": None, "status": "void_refunded", "gross": Decimal("12.00")},
    ]
    for change in bad:
        values = (
            {c: getattr(row, c) for c in row._fields}
            | change
            | {"score_set_id": ss.id, "entry_id": w["entries"][1], "display_order": 999}
        )
        with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
            conn.execute(sa.insert(round_scores).values(**values))
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(
            sa.update(round_scores).where(round_scores.c.score_set_id == ss.id).values(points=150)
        )  # history is insert-only
    with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
        conn.execute(sa.update(score_sets).where(score_sets.c.id == ss.id).values(revision=9))


# ------------------------------------------------------------------ reads
def test_official_board_pages_with_shared_ranks_and_my_position(engine, worlds):
    w = worlds["competitive"]
    (ss,) = score_sets_of(engine, w["round"])
    rows = scores_of(engine, ss.id)
    me_user = w["users"][w["entries"].index(rows[-1].entry_id)]  # the last row
    me = principal(engine, user_id=me_user)
    pages = []
    for page in (1, 2, 3):
        b = lb.weekly_board(engine, w["round"], viewer=me, page=page, page_size=5,
                            include_development=True)  # fmt: skip
        assert (
            b.state == "final" and b.classification == "competitive" and b.stream == "development"
        )
        assert (b.total, b.pages, b.page) == (12, 3, page) and b.revision == 1 and not b.corrected
        pages.append(b)
    flat = [r for b in pages for r in b.rows]
    assert [r.position for r in flat] == [r.rank for r in rows]
    assert [r.points for r in flat] == [r.points for r in rows]
    counts = {}
    for r in rows:
        counts[r.rank] = counts.get(r.rank, 0) + 1
    assert [f.shared for f in flat] == [counts[r.rank] > 1 for r in rows]
    assert pages[0].me == pages[2].me and pages[0].me.is_me and pages[0].me_page == 3
    assert sum(r.is_me for r in flat) == 1
    clamped = lb.weekly_board(engine, w["round"], page=99, page_size=5, include_development=True)
    assert clamped.page == 3 and clamped.me is None and clamped.me_status is None  # guest


def test_practice_and_void_boards(engine, worlds):
    p = lb.weekly_board(engine, worlds["practice"]["round"], include_development=True)
    assert p.classification == "practice" and {r.points for r in p.rows} == {None}
    assert [r.position for r in p.rows] == scoring.competition_ranks([r.returned for r in p.rows])
    assert sum(r.shared for r in p.rows) >= 2  # the identical portfolios
    member = principal(engine, user_id=worlds["void"]["users"][0])
    v = lb.weekly_board(engine, worlds["void"]["round"], viewer=member, include_development=True)
    assert v.round_void and v.void_basis == "d32b" and v.rows == () and v.total == 0
    assert v.me.recovery == "round_refund" and v.me.returned == Decimal("100.00")
    r = lb.weekly_board(engine, worlds["refund"]["round"],
                        viewer=principal(engine, user_id=worlds["refund"]["users"][5]),
                        include_development=True)  # fmt: skip
    assert r.me.status == "refunded" and r.me.position is None and r.me_status == "refunded"
    outsider = principal(engine, role="operator")
    assert lb.weekly_board(engine, worlds["refund"]["round"], viewer=outsider,
                           include_development=True).me_status == "not_entered"  # fmt: skip


def test_development_rounds_are_hidden_unless_enabled(engine, worlds):
    with pytest.raises(NotFound):
        lb.weekly_board(engine, worlds["competitive"]["round"])
    with pytest.raises(NotFound):
        lb.weekly_board(engine, uuid.uuid4(), include_development=True)


def test_rows_carry_no_identifiers_or_contact_details(engine, worlds):
    w = worlds["competitive"]
    me = principal(engine, user_id=w["users"][0])
    b = lb.weekly_board(engine, w["round"], viewer=me, include_development=True)
    ids = {str(x) for x in (*w["users"], *w["entries"], w["round"])}
    names = {f.name for f in fields(lb.WeeklyRow)}
    assert names == {"position", "shared", "name", "returned", "net", "recovery", "points",
                     "settled", "pending", "status", "is_me"}  # fmt: skip
    text = repr(b)
    assert not any(i in text for i in ids) and "@" not in text


def test_retroactive_anonymity_applies_to_published_results(engine, worlds):
    w = worlds["practice"]
    with transaction(engine) as conn:
        alias = conn.execute(sa.text("SELECT anonymous_alias FROM app.profiles WHERE user_id=:u"),
                             {"u": w["users"][2]}).scalar_one()  # fmt: skip
        accounts.set_privacy(conn, w["users"][2], "anonymous", retroactive=True)
    b = lb.weekly_board(engine, w["round"], include_development=True)
    assert alias in [r.name for r in b.rows]
    with transaction(engine) as conn:
        items = [
            accounts.LockedName(e.user_id, e.locked_at, e.public_name_at_lock,
                                e.privacy_mode_at_lock)
            for e in conn.execute(sa.select(entries).where(entries.c.round_id == w["round"]))
        ]  # fmt: skip
        many = accounts.leaderboard_names(conn, items)
        one = [accounts.leaderboard_name(conn, user_id=i.user_id, locked_at=i.locked_at,
                                         public_name_at_lock=i.public_name_at_lock,
                                         privacy_mode_at_lock=i.privacy_mode_at_lock)
               for i in items]  # fmt: skip
    assert many == one


def test_unpublished_final_round_is_not_shown_as_official(engine, op, worlds, monkeypatch):
    """A round finalised before official results existed (an upgraded database)
    shows no results until it is published (backfill, Stage C)."""
    w = worlds["legacy"]
    monkeypatch.setattr(comp, "publish_finalised", lambda *a, **k: None)
    finalise(engine, op, w)
    monkeypatch.undo()
    b = lb.weekly_board(engine, w["round"], include_development=True)
    assert b.state == "unpublished" and b.rows == ()


def test_reads_write_nothing_and_never_call_the_provider(engine, worlds, monkeypatch):
    import diski9.api_football.client as client

    def no_provider(*a, **k):
        raise AssertionError("a leaderboard read must not construct the football client")

    monkeypatch.setattr(client.ApiFootballClient, "__init__", no_provider)
    tables = ["score_sets", "round_scores", "settlement_runs", "entry_settlements",
              "audit_log", "domain_events", "result_observations"]  # fmt: skip

    def counts():
        with transaction(engine) as conn:
            return [conn.execute(sa.text(f"SELECT count(*) FROM app.{t}")).scalar_one()
                    for t in tables]  # fmt: skip

    before = counts()
    for k in ("competitive", "practice", "void", "refund"):
        lb.weekly_board(engine, worlds[k]["round"], include_development=True)
    assert counts() == before


# ------------------------------------------------------------------ provisional
@pytest.fixture(scope="module")
def provisional(engine, op):
    w = settlement_world(engine, [rot(r) for r in range(5)] + [rot(0)], development=True,
                         cutoff_after=timedelta(minutes=10))  # fmt: skip
    record_results(engine, op, w, lambda i: mixed(i) if i < 4 else None)
    st.settle_round(engine, op, w["round"])  # before the cutoff: some predictions pending
    return w


def test_provisional_standings_never_decide_pending_results(engine, provisional):
    w = provisional
    b = lb.weekly_board(engine, w["round"], viewer=principal(engine, user_id=w["users"][0]),
                        include_development=True)  # fmt: skip
    assert b.state == "provisional" and b.revision is None and b.total == 6
    assert b.pending_predictions > 0 and b.settled_predictions > 0
    assert b.settled_predictions + b.pending_predictions == 6 * 9
    for r in b.rows:
        assert r.points is None  # no points, estimated or otherwise
        assert r.recovery == "undecided" and r.net is None  # nothing decided while pending
        assert r.returned is not None and r.returned >= 0  # settled so far, never "lost"
        assert r.settled + r.pending == 9
    assert [r.position for r in b.rows] == scoring.competition_ranks([r.returned for r in b.rows])
    twins = [r for r in b.rows if r.is_me] + [b.me]
    assert b.me is not None and b.me.is_me and twins[0] == b.me
    assert score_sets_of(engine, w["round"]) == []  # provisional standings are never stored


def test_provisional_reads_are_cached_per_settlement_run(engine, op, provisional):
    lb.clear_cache()
    first = lb.weekly_board(engine, provisional["round"], include_development=True)
    assert len(lb._CACHE) == 1
    again = lb.weekly_board(engine, provisional["round"], include_development=True)
    assert again == first and len(lb._CACHE) == 1


# ------------------------------------------------------------------ reopening (6C.4 path)
def test_reopening_keeps_the_last_published_results_until_refinalised(engine, op, owner, worlds):
    w = worlds["mech"]
    (first,) = score_sets_of(engine, w["round"])
    before = [tuple(r) for r in scores_of(engine, first.id)]
    published = lb.weekly_board(engine, w["round"], include_development=True)
    with transaction(engine) as conn:
        now = db_now(conn)
    # evidence arriving after finalisation only raises an alert (6C.4) ...
    rs.record_synthetic_observation(engine, op, w["round"], w["fixtures"][0], observed_at=now,
                                    status="CANC")  # fmt: skip
    st.settle_round(engine, op, w["round"])
    # ... and the owner reopens the round (S-06, T-14)
    imp = co.preview_reopen(engine, owner, w["round"])
    co.reopen_round(engine, owner, w["round"], reason="match cancelled by league",
                    evidence="league statement", confirmation=imp.token)  # fmt: skip
    review = lb.weekly_board(engine, w["round"], include_development=True)
    assert review.state == "under_review" and review.revision == 1
    assert review.rows == published.rows  # retained: the last published results
    assert len(score_sets_of(engine, w["round"])) == 1  # nothing published while reopened
    finalise(engine, op, w)
    first_again, second = score_sets_of(engine, w["round"])
    assert second.revision == 2 and second.settlement_version_id != first.settlement_version_id
    same(engine, second.id, w["round"])  # the whole round re-scored from settlement
    assert [tuple(r) for r in scores_of(engine, first.id)] == before  # history kept
    after = lb.weekly_board(engine, w["round"], include_development=True)
    assert after.state == "final" and after.revision == 2 and after.corrected
    assert [r.returned for r in after.rows] != [r.returned for r in published.rows]


# ------------------------------------------------------------------ championship tables (Stage C)
def test_championship_tables_protect_identity_and_membership(engine, worlds):
    """Stage B creates the Stage C tables only; their database guards are checked
    here (identity, name and membership can never change or be deleted)."""
    w = worlds["practice"]
    with transaction(engine) as conn:
        sid = conn.execute(sa.text("SELECT id FROM app.championship_series WHERE code='beta'")
                           ).scalar_one()  # fmt: skip
        cid = conn.execute(sa.text(
            "INSERT INTO app.championships (stream, series_id, ordinal, start_date, display_name) "
            "VALUES ('development', :s, 900001, '2026-11-28', 'Championship Nov-26 (99)') "
            "RETURNING id"), {"s": sid}).scalar_one()  # fmt: skip
        conn.execute(
            sa.text(
                "INSERT INTO app.championship_rounds (round_id, championship_id, "
                "role) VALUES (:r, :c, 'practice')"
            ),
            {"r": w["round"], "c": cid},
        )
        conn.execute(sa.text("UPDATE app.championships SET status='in_progress' WHERE id=:c"),
                     {"c": cid})  # status may change (publication only)  # fmt: skip
    forbidden = [
        "UPDATE app.championships SET display_name='Championship Dec-26 (98)' WHERE id=:c",
        "UPDATE app.championships SET start_date='2026-12-01' WHERE id=:c",
        "DELETE FROM app.championships WHERE id=:c",
        "UPDATE app.championship_rounds SET championship_id=gen_random_uuid() "
        "WHERE championship_id=:c",
        "DELETE FROM app.championship_rounds WHERE championship_id=:c",
        "INSERT INTO app.championships (stream, series_id, ordinal, start_date, display_name) "
        "SELECT 'development', series_id, 900002, start_date, 'Championship 2026-11' "
        "FROM app.championships WHERE id=:c",
        "INSERT INTO app.championships (stream, series_id, ordinal, start_date, display_name) "
        "SELECT 'development', series_id, 900003, start_date, display_name "
        "FROM app.championships WHERE id=:c",  # the same name twice in a stream
    ]
    for sql in forbidden:
        with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
            conn.execute(sa.text(sql), {"c": cid})


def test_runtime_role_privileges_on_competition_tables(engine):
    """The application role can publish (insert) and read results, update the
    guarded championship projections, and never delete or rewrite history."""
    with transaction(engine) as conn:

        def can(table, priv):
            return conn.execute(sa.text("SELECT has_table_privilege('diski9_app', :t, :p)"),
                                {"t": f"app.{table}", "p": priv}).scalar()  # fmt: skip

        for t in ("score_sets", "round_scores", "championship_versions", "championship_standings"):
            assert can(t, "INSERT") and can(t, "SELECT"), t
            assert not can(t, "UPDATE") and not can(t, "DELETE") and not can(t, "TRUNCATE"), t
        for t in ("championships", "championship_rounds"):
            assert can(t, "INSERT") and can(t, "SELECT") and can(t, "UPDATE"), t
            assert not can(t, "DELETE") and not can(t, "TRUNCATE"), t
        for role in ("anon", "authenticated"):
            for t in ("score_sets", "round_scores", "championships", "championship_standings"):
                assert not conn.execute(
                    sa.text("SELECT has_table_privilege(:r, :t, 'SELECT')"),
                    {"r": role, "t": f"app.{t}"},
                ).scalar(), (role, t)
