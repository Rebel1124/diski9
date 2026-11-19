"""The Phase 6C.3 services work under the least-privileged runtime role
(``diski9_app``, row-level security on), and the browser-facing roles still see
nothing (real PostgreSQL)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import event, text
from svc_helpers import principal, publish_dev, valid_keys, wait_until

from diski9.backend.db import BackendDatabaseSettings, make_app_engine
from diski9.backend.services import drafts, snapshots
from diski9.backend.services import rounds as svc
from diski9.backend.services import your_view as yv


@pytest.fixture
def app_engine(pg_url):
    eng = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)

    @event.listens_for(eng, "begin")
    def _as_runtime_role(conn):
        conn.exec_driver_sql("SET LOCAL ROLE diski9_app")

    yield eng
    eng.dispose()


def test_full_stage_b_to_d_flow_as_runtime_role(engine, app_engine):
    op = principal(engine, role="operator")
    p = principal(engine)
    snapshots.CACHE.clear()
    view, snap = publish_dev(app_engine, op, deadline_in=timedelta(seconds=4))
    with app_engine.connect() as conn, conn.begin():
        assert conn.execute(text("SELECT current_user")).scalar() == "diski9_app"
    d = drafts.save_draft(app_engine, p, view.id, valid_keys(snap, 4), expected_version=0)
    assert drafts.get_draft(app_engine, p, view.id) == d
    f = snap.fixtures[0]
    ctx = yv.frozen_context(snap, f.fixture_id, view.model_version)
    state = yv.zero_state()
    state["context"]["home"] = 0.2
    assert (
        yv.save_your_view(app_engine, p, f.fixture_id, ctx, state, expected_version=0).state
        == state
    )
    snapshots.CACHE.clear()
    assert svc.published_snapshot(app_engine, view.id).fingerprint == snap.fingerprint
    wait_until(app_engine, view.deadline_at)
    res = svc.lock_round(app_engine, svc.SYSTEM, view.id)
    assert res.designation == "practice" and res.round.status == "locked"


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_roles_cannot_touch_drafts_or_your_view(pg_url, role):
    eng = make_app_engine(BackendDatabaseSettings(environment="test"), url=pg_url)
    try:
        for table in ("portfolio_drafts", "your_view_adjustments", "rounds", "snapshot_offers"):
            with eng.connect() as conn, conn.begin():
                conn.execute(text(f"SET LOCAL ROLE {role}"))
                with pytest.raises(Exception, match="permission denied"):
                    conn.execute(text(f"SELECT count(*) FROM app.{table}"))
    finally:
        eng.dispose()
