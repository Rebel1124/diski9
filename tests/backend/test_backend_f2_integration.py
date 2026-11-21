"""Phase 6C.5 Stage F2: integration tests that add coverage the earlier suites do
not have, on their own PostgreSQL database (two-round championships here).

* Privacy and participant isolation across the read services *and* the rendered
  Dash components built from real database results: another participant's round
  codes, championships, pages and streams reveal nothing; public payloads carry no
  user ids, e-mail addresses, identity subjects or selections; a deleted account
  is shown by its alias with its standing preserved.
* Weekly lifecycle with a withdrawal on each side of the five-entry boundary
  (competitive vs practice), provisional boards without points, finalisation,
  and practice rounds excluded from championship progress.
* Stream isolation in one database: development and beta championships progress
  independently; nothing reaches the official stream; development stays hidden
  unless enabled.

Lower-level rules (scoring, D-32b, corrections, D-30a, repair, concurrency) keep
their own suites; see ``docs/architecture/phase6c5_implementation.md`` §7.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import (
    WIN,
    drop,
    finalise,
    isolated_engine,
    lose,
    operator,
    results,
    set_required,
    settle,
    users,
    winner,
)
from plotly.utils import PlotlyJSONEncoder
from settle_helpers import confirm_entry, make_settlement_round, provider_item
from svc_helpers import principal, wait_until

from diski9.app.challenge import history_ui as hu
from diski9.app.challenge import leaderboards_ui as lbu
from diski9.backend.db import transaction
from diski9.backend.db.schema import entries as entries_t
from diski9.backend.db.schema import score_sets
from diski9.backend.repositories import results as results_repo
from diski9.backend.services import challenge_history as chist
from diski9.backend.services import championships as ch
from diski9.backend.services import entries as esvc
from diski9.backend.services import leaderboards as lb
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import NotFound
from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

DB = "diski9_f2_integration_test"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def as_principal(engine, uid):
    return principal(engine, user_id=uid)


def dump(obj) -> str:
    if dataclasses.is_dataclass(obj):
        obj = dataclasses.asdict(obj)
    return json.dumps(obj, cls=PlotlyJSONEncoder, default=str, ensure_ascii=False)


def real_results(engine, w, result_of) -> None:
    """Provider evidence for a genuine (beta) round: real rounds never take synthetic
    results."""
    at = w["deadline"] + timedelta(milliseconds=1500)
    ko = w["deadline"] + timedelta(seconds=1)
    wait_until(engine, at)
    for i, fid in enumerate(w["fixtures"]):
        res = result_of(i)
        item = (provider_item(fid, "CANC", ko=ko) if res == "CANC"
                else provider_item(fid, "FT", ko=ko, h=res[0], a=res[1]))  # fmt: skip
        with transaction(engine) as conn:
            results_repo.record_evidence(
                conn, source="api-football", fixture_id=fid, observed_at=at, raw=item,
                raw_hash=canonical_hash(item), fields=evidence_fields(item),
            )  # fmt: skip


def make_rounds(engine, plan, *, development=True, withdraw=()):
    """Rounds in deadline order with confirmed entries; ``withdraw`` = [(k, user)]
    withdrawn through the entry service before the deadline; then locked."""
    made = []
    with transaction(engine) as conn:
        for k, ents in enumerate(plan):
            rid, snap, fids, deadline, cutoff = make_settlement_round(
                conn, deadline_in=timedelta(seconds=4, milliseconds=10 * k),
                cutoff_after=timedelta(seconds=4), development=development,
            )  # fmt: skip
            for u, spec in ents:
                confirm_entry(conn, rid, snap, fids, u, spec)
            made.append({"round": rid, "fixtures": fids, "deadline": deadline, "cutoff": cutoff,
                         "users": [u for u, _ in ents]})  # fmt: skip
    for k, u in withdraw:
        rid = made[k]["round"]
        with transaction(engine) as conn:
            v = conn.execute(
                sa.select(entries_t.c.version).where(
                    entries_t.c.round_id == rid, entries_t.c.user_id == u
                )
            ).scalar_one()
        esvc.withdraw_entry(engine, as_principal(engine, u), rid, expected_entry_version=v)
    wait_until(engine, max(w["deadline"] for w in made))
    for w in made:
        w["lock"] = svc.lock_round(engine, svc.SYSTEM, w["round"])
        with transaction(engine) as conn:
            w["code"] = conn.execute(
                sa.text("SELECT code FROM app.rounds WHERE id = :r"), {"r": w["round"]}
            ).scalar_one()
    return made


@pytest.fixture(scope="module")
def world(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    set_required(eng, 2)
    with transaction(eng) as conn:
        conn.execute(sa.text("UPDATE app.championship_series SET rounds_per_championship = 2 "
                             "WHERE code IN ('beta', 'official')"))  # fmt: skip
    op = operator(eng)
    u = users(eng, 8)
    emails = {}
    with transaction(eng) as conn:
        for i, uid in enumerate(u):
            emails[uid] = f"f2-private-{i}@example.com"
            conn.execute(
                sa.text(
                    "INSERT INTO app.user_private (user_id, email, email_verified, updated_at) "
                    "VALUES (:u, :e, true, now()) ON CONFLICT (user_id) DO UPDATE SET email = :e"
                ),
                {"u": uid, "e": emails[uid]},
            )
    six = [0, 1, 2, 3, 4, 5]
    plan = [
        # D1: six enter, u5 withdraws -> 5 valid -> competitive (u0 wins)
        [(u[i], WIN if i == 0 else lose(i)) for i in six],
        # D2: five enter, u4 withdraws -> 4 valid -> practice
        [(u[i], WIN if i == 1 else lose(i)) for i in range(5)],
        # D3: five + u6 (only here): u1 and u6 win -> shared rank 1
        [(u[i], WIN if i in (1, 6) else lose(i)) for i in (0, 1, 2, 3, 6)],
        # D4: settled, not finalised (provisional)
        [(u[i], WIN if i == 2 else lose(i)) for i in range(5)],
    ]
    made = make_rounds(eng, plan, withdraw=[(0, u[5]), (1, u[4])])
    for w in made:
        results(eng, op, w, winner)
    for w in made:
        settle(eng, op, w)
    for w in made[:3]:
        finalise(eng, op, w)
    yield {"engine": eng, "op": op, "u": u, "emails": emails, "d": made}
    eng.dispose()
    drop(pg_url, DB)


# ------------------------------------------------------------------ lifecycle
def test_withdrawal_on_each_side_of_the_five_entry_boundary(world):
    d = world["d"]
    assert d[0]["lock"].locked_entries == 5 and d[0]["lock"].designation == "championship"
    assert d[1]["lock"].locked_entries == 4 and d[1]["lock"].designation == "practice"
    eng, u = world["engine"], world["u"]
    b0 = lb.weekly_board(eng, d[0]["round"], include_development=True)
    assert b0.classification == "competitive" and b0.entries == 5
    assert all(r.points is not None for r in b0.rows)
    names = {r.name for r in b0.rows}
    with transaction(eng) as conn:
        withdrawn = conn.execute(
            sa.text("SELECT username FROM app.profiles WHERE user_id = :u"), {"u": u[5]}
        ).scalar_one()
    assert withdrawn not in names  # a withdrawn entry is not on the board
    b1 = lb.weekly_board(eng, d[1]["round"], include_development=True)
    assert b1.classification == "practice"
    assert all(r.points is None for r in b1.rows)


def test_provisional_board_has_no_points_and_final_boards_share_ranks(world):
    eng, d = world["engine"], world["d"]
    prov = lb.weekly_board(eng, d[3]["round"], include_development=True)
    assert prov.state == "provisional"
    assert all(r.points is None for r in prov.rows)
    final = lb.weekly_board(eng, d[2]["round"], include_development=True)
    top = [r for r in final.rows if r.position == 1]
    assert len(top) == 2 and all(r.shared for r in top)
    assert len({r.points for r in top}) == 1 and top[0].points > 0
    # weekly score sets exist only for finalised rounds, once each
    with transaction(eng) as conn:
        counts = dict(conn.execute(
            sa.select(score_sets.c.round_id, sa.func.count()).group_by(score_sets.c.round_id)
        ).all())  # fmt: skip
    assert d[3]["round"] not in counts
    assert all(counts.get(w["round"], 0) == 1 for w in (d[0], d[2]))


def test_practice_round_is_excluded_from_championship_progress(world):
    eng = world["engine"]
    cb = lb.championship_board(eng, stream="development", include_development=True)
    # D1 and D3 counted (2 of 2); D2 practice not counted; D4 not final
    first = cb.championships[-1]
    assert first.counted_rounds == 2 and first.status == "completed"
    with transaction(eng) as conn:
        assert ch.verify_stream(conn, "development") == []


# ------------------------------------------------------------------ privacy
def test_other_participants_rounds_pages_and_streams_reveal_nothing(world):
    eng, u, d = world["engine"], world["u"], world["d"]
    six = as_principal(eng, u[6])  # entered only D3
    zero = as_principal(eng, u[0])
    kw = {"stream": "development", "include_development": True}
    assert chist.my_round_code_visible(eng, six, d[0]["code"], **kw) is None
    assert chist.my_round_code_visible(eng, zero, d[0]["code"], **kw) == d[0]["round"]
    assert chist.my_round_code_visible(eng, six, d[0]["code"], stream="beta") is None
    assert lb.my_round_result(eng, six, d[0]["round"], include_development=True) is None
    for page in (-3, 0, 1, 999):
        h = chist.my_history(eng, six, page=page, **kw)
        assert h.total == 1 and [r.round_code for r in h.rows] == [d[2]["code"]]
    assert chist.my_history(eng, None, **kw) is None
    with pytest.raises(NotFound):
        chist.my_history(eng, six, stream="development")  # hidden unless enabled
    with pytest.raises(NotFound):
        chist.my_history(eng, six, championship="Championship Nov-26", stream="beta")
    with pytest.raises(NotFound):
        chist.my_history(eng, six, championship="No such one", **kw)
    with pytest.raises(NotFound):
        lb.weekly_board(eng, d[0]["round"])  # development hidden from ordinary viewers
    stats = chist.my_statistics(eng, six, **kw)
    assert stats.played == 1 and stats.missed == 1


def test_public_payloads_carry_no_identifiers_emails_or_selections(world):
    eng, u, d, emails = world["engine"], world["u"], world["d"], world["emails"]
    with transaction(eng) as conn:
        subjects = conn.execute(sa.text("SELECT subject FROM app.user_identities")).scalars().all()
        fids = [str(f) for w in d for f in w["fixtures"]]
    forbidden = [str(x) for x in u] + list(emails.values()) + list(subjects)
    me = as_principal(eng, u[0])
    for viewer in (None, me):
        wb = lb.weekly_board(eng, d[2]["round"], viewer=viewer, include_development=True)
        cb = lb.championship_board(eng, stream="development", viewer=viewer,
                                   include_development=True)  # fmt: skip
        ui = [lbu.weekly_header(wb, "development"), lbu.weekly_you(wb), lbu.weekly_banner(wb),
              lbu.weekly_podium(wb), lbu.weekly_table(wb), lbu.championship_header(cb, "development"),
              lbu.championship_notices(cb), lbu.championship_you(cb),
              lbu.championship_table(cb)]  # fmt: skip
        for blob in (dump(wb), dump(cb), dump(ui)):
            assert not UUID.search(blob)
            assert "@" not in blob
            for f in forbidden:
                assert f not in blob
            for fid in fids:  # no fixture ids, so no selections
                assert fid not in blob
    assert {f.name for f in dataclasses.fields(lb.WeeklyRow)} == {
        "position", "shared", "name", "returned", "net", "recovery", "points", "settled",
        "pending", "status", "is_me"}  # fmt: skip


def test_history_ui_payload_is_scoped_and_identifier_free(world):
    eng, u = world["engine"], world["u"]
    six = as_principal(eng, u[6])
    h = chist.my_history(eng, six, stream="development", include_development=True)
    blob = dump(hu.history_table(h, lambda iso: iso))
    assert not UUID.search(blob) and "@" not in blob
    assert world["d"][0]["code"] not in blob and world["d"][2]["code"] in blob


def test_deleted_account_keeps_its_standing_under_an_alias(world):
    eng, u, d = world["engine"], world["u"], world["d"]
    before_w = lb.weekly_board(eng, d[2]["round"], include_development=True)
    before_c = lb.championship_board(eng, stream="development", include_development=True,
                                     name=lb.championship_board(
                                         eng, stream="development",
                                         include_development=True).championships[-1].name)  # fmt: skip
    with transaction(eng) as conn:
        name, alias = conn.execute(
            sa.text("SELECT username, anonymous_alias FROM app.profiles WHERE user_id = :u"),
            {"u": u[6]},
        ).one()
        conn.execute(sa.text("UPDATE app.users SET status = 'deleted', deleted_at = now() "
                             "WHERE id = :u"), {"u": u[6]})  # fmt: skip
    try:
        lb.clear_cache()
        after_w = lb.weekly_board(eng, d[2]["round"], include_development=True)
        after_c = lb.championship_board(eng, stream="development", include_development=True,
                                        name=before_c.name)  # fmt: skip
        rows_b = {r.name: r for r in before_w.rows}
        rows_a = {r.name: r for r in after_w.rows}
        assert name in rows_b and name not in rows_a and alias in rows_a
        assert (rows_a[alias].position, rows_a[alias].points) == (
            rows_b[name].position, rows_b[name].points)  # fmt: skip
        assert [(r.position, r.points) for r in after_c.rows] == [
            (r.position, r.points) for r in before_c.rows]  # fmt: skip
        assert name not in dump(after_c) and name not in dump(after_w)
    finally:
        with transaction(eng) as conn:
            conn.execute(sa.text("UPDATE app.users SET status = 'active', deleted_at = NULL WHERE id = :u"),
                         {"u": u[6]})  # fmt: skip
        lb.clear_cache()


# ------------------------------------------------------------------ streams
def test_beta_and_development_championships_are_independent(world):
    eng, op, u = world["engine"], world["op"], world["u"]
    dev_before = lb.championship_board(eng, stream="development", include_development=True)
    beta = make_rounds(eng, [[(u[i], WIN if i == 3 else lose(i)) for i in range(5)]],
                       development=False)  # fmt: skip
    real_results(eng, beta[0], winner)
    settle(eng, op, beta[0])
    # a genuine round cannot be finalised before cutoff + 24 h and takes no time
    # override, so the beta round stays provisional here (the approved rule)
    wb = lb.weekly_board(eng, beta[0]["round"])
    assert wb.stream == "beta" and wb.state == "provisional"
    assert all(r.points is None for r in wb.rows)
    bcb = lb.championship_board(eng, stream="beta")
    assert bcb.stream == "beta" and bcb.counted_rounds == 0 and bcb.status != "completed"
    dev_after = lb.championship_board(eng, stream="development", include_development=True)
    assert [(c.name, c.counted_rounds, c.status) for c in dev_after.championships] == [
        (c.name, c.counted_rounds, c.status) for c in dev_before.championships]  # fmt: skip
    off = lb.championship_board(eng, stream="official")
    assert off.name is None and off.rows == ()
    with transaction(eng) as conn:
        streams = conn.execute(sa.text("SELECT DISTINCT stream FROM app.championships")).scalars()
        assert set(streams) <= {"beta", "development"}
        # no championship holds a round of another stream
        crossed = conn.execute(sa.text(
            "SELECT count(*) FROM app.championship_rounds cr "
            "JOIN app.championships c ON c.id = cr.championship_id "
            "JOIN app.rounds r ON r.id = cr.round_id "
            "WHERE (c.stream = 'development') <> r.is_development")).scalar()  # fmt: skip
        assert crossed == 0
        assert ch.verify_stream(conn, "beta") == []
        assert ch.verify_stream(conn, "development") == []
    # an ordinary viewer's history of beta shows the beta entry only, labelled beta
    h = chist.my_history(eng, as_principal(eng, u[3]), stream="beta")
    assert [r.round_code for r in h.rows] == [beta[0]["code"]]
    assert "development" not in lb.stream_options(eng)
