"""Phase 6C.4: settlement under the least-privileged runtime role, browser-role
isolation, append-only protection and lifecycle integrity of the new tables,
cross-account isolation, and reconstruction from evidence manifests after a
restart (real PostgreSQL)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa
from settle_helpers import DEFAULT_ENTRY, settlement_world
from sqlalchemy import event, text
from svc_helpers import principal, wait_until

from diski9.backend import settlement_scenarios as sc
from diski9.backend.auth.permissions import GUEST
from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, transaction
from diski9.backend.db.schema import result_observations as RO
from diski9.backend.db.schema import settlement_runs, settlement_versions
from diski9.backend.repositories import results as repo
from diski9.backend.services import corrections as co
from diski9.backend.services import results as rs
from diski9.backend.services import settlement as st
from diski9.challenge.config import get_config
from diski9.challenge.settle import resolve_fixture, settle_entry

NEW_TABLES = ("settlement_versions", "settlement_alerts", "settlement_alert_resolutions")


@pytest.fixture
def app_engine(pg_url):
    eng = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)

    @event.listens_for(eng, "begin")
    def _as_runtime_role(conn):
        conn.exec_driver_sql("SET LOCAL ROLE diski9_app")

    yield eng
    eng.dispose()


def fresh(engine, p):
    with transaction(engine) as conn:
        now = db_now(conn)
    return replace(p, authenticated_at=now, reauthenticated_at=now, now=now)


def test_whole_settlement_lifecycle_as_the_runtime_role(engine, app_engine):
    op = fresh(engine, principal(engine, role="operator"))
    owner = fresh(engine, principal(engine, role="owner"))
    w = settlement_world(engine, development=True, cutoff_after=timedelta(seconds=3))
    with app_engine.connect() as conn, conn.begin():
        assert conn.execute(text("SELECT current_user")).scalar() == "diski9_app"
    rs.set_result_mode(app_engine, op, w["round"], "synthetic")
    sc.apply_scenario(app_engine, op, w["round"], "cutoff-boundary")
    wait_until(engine, w["cutoff"] + timedelta(milliseconds=1500))
    res = st.settle_round(app_engine, op, w["round"])
    assert res.version == 1 and res.open_blocking_alerts == 1
    with transaction(app_engine) as conn:
        (alert,) = repo.open_alerts(conn, w["round"], blocking_only=True)
    co.resolve_alert(app_engine, op, w["round"], alert.id, reason="confirmed late kickoff")
    imp = co.preview_correction(app_engine, op, w["round"],
                                co.CorrectionInput(w["fixtures"][2], "FT", 4, 0))  # fmt: skip
    co.correct_result(app_engine, op, w["round"], co.CorrectionInput(w["fixtures"][2], "FT", 4, 0),
                      reason="r", evidence="e", confirmation=imp.token)  # fmt: skip
    fin = co.finalise_round(app_engine, op, w["round"], as_of=res.earliest_finalisation)
    assert fin.finalised
    imp = co.preview_reopen(app_engine, owner, w["round"])
    co.reopen_round(app_engine, owner, w["round"], reason="review", evidence="league note",
                    confirmation=imp.token)  # fmt: skip
    with transaction(app_engine) as conn:
        kinds = conn.execute(sa.select(settlement_versions.c.kind).where(
            settlement_versions.c.round_id == w["round"]).order_by(settlement_versions.c.version)
        ).scalars().all()  # fmt: skip
    assert kinds[-2:] == ["final", "reopened"]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_roles_cannot_read_settlement_data(pg_url, role):
    eng = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)
    try:
        for table in (
            *NEW_TABLES,
            "result_observations",
            "entry_settlements",
            "selection_verdicts",
        ):
            with eng.connect() as conn, conn.begin():
                conn.execute(text(f"SET LOCAL ROLE {role}"))
                with pytest.raises(Exception, match="permission denied"):
                    conn.execute(text(f"SELECT count(*) FROM app.{table}"))
    finally:
        eng.dispose()


def test_new_history_tables_are_append_only_and_versions_follow_the_lifecycle(engine):
    w = settlement_world(engine)
    op = principal(engine, role="operator")
    st.settle_round(engine, op, w["round"])
    for table in NEW_TABLES[:2]:
        for stmt in (f"UPDATE app.{table} SET created_at = now()", f"DELETE FROM app.{table}"):
            with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
                conn.execute(text(stmt))
    bad = [
        {"version": 3, "kind": "provisional"},  # gap
        {"version": 2, "kind": "reopened"},  # reopened without a final version
    ]
    with transaction(engine) as conn:
        run = conn.execute(sa.select(settlement_runs.c.id).where(
            settlement_runs.c.round_id == w["round"])).scalars().first()  # fmt: skip
    for values in bad:
        with pytest.raises(sa.exc.DBAPIError), transaction(engine) as conn:
            conn.execute(sa.insert(settlement_versions).values(
                round_id=w["round"], run_id=run, material=True, effective_at=sa.func.now(),
                actor_user_id=op.user_id, reason="x", evidence="y", **values))  # fmt: skip


def test_participants_see_only_their_own_settlement(engine):
    w = settlement_world(engine, specs=(DEFAULT_ENTRY, DEFAULT_ENTRY))
    st.settle_round(engine, principal(engine, role="operator"), w["round"])
    a = principal(engine, user_id=w["users"][0])
    b = principal(engine, user_id=w["users"][1])
    stranger = principal(engine)
    assert st.personal_result(engine, a, w["round"]) is not None
    assert st.personal_result(engine, stranger, w["round"]) is None
    assert st.personal_result(engine, GUEST, w["round"]) is None
    ra, rb = st.personal_result(engine, a, w["round"]), st.personal_result(engine, b, w["round"])
    assert ra.legs == rb.legs  # same picks, each read through its own entry only
    with pytest.raises(TypeError):
        st.personal_result(engine, a, w["round"], user_id=w["users"][1])  # no such parameter


def test_restart_reconstructs_every_settlement_from_its_manifest(engine, pg_url):
    op = principal(engine, role="operator")
    w = settlement_world(engine, development=True, cutoff_after=timedelta(seconds=3))
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    sc.apply_scenario(engine, op, w["round"], "partial-void")
    st.settle_round(engine, op, w["round"], as_of=w["cutoff"] + timedelta(hours=1))
    eng2 = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)  # "restart"
    try:
        with transaction(eng2) as conn:
            run = conn.execute(sa.select(settlement_runs).where(
                settlement_runs.c.round_id == w["round"], settlement_runs.c.status == "succeeded")
                .order_by(settlement_runs.c.id.desc())).first()  # fmt: skip
            r = conn.execute(text("SELECT * FROM app.rounds WHERE id=:r"), {"r": w["round"]}).one()
            legs = st.locked_legs(conn, w["round"])
            stored = st._current_entry_settlements(conn, w["round"])
            obs = {o.id: repo.to_observation(o) for o in conn.execute(sa.select(RO).where(
                RO.c.id.in_([i for v in run.manifest.values() for i in v])))}  # fmt: skip
        selected = {}
        for _, ls, _ in legs.values():
            for x in ls:
                selected.setdefault(x.fixture_id, set()).add((x.market, x.outcome))
        verdicts = {}
        for fid, outs in selected.items():
            res = resolve_fixture(fid, [obs[i] for i in run.manifest[str(fid)]], sorted(outs),
                                  deadline_at=r.deadline_at, settle_cutoff_at=r.settle_cutoff_at,
                                  evaluated_at=run.evaluated_at)  # fmt: skip
            verdicts.update({(fid, v.market, v.outcome): v.verdict for v in res.verdicts})
        for entry_id, (_, ls, _) in legs.items():
            rebuilt = settle_entry(ls, verdicts, get_config(r.config_version))  # its round's
            assert rebuilt.gross == stored[entry_id].gross
            assert rebuilt.complete == stored[entry_id].complete
    finally:
        eng2.dispose()
