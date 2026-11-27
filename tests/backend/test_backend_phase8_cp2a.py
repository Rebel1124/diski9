"""Phase 8 CP2A on real PostgreSQL: a round whose pool includes fixtures without an
independent Goal Model prediction publishes with NULL model values, an entry on such
picks stores NULL Diski 9 aggregates, and publication refuses competitions outside the
bound schedule's ``eligible_competitions``."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import timedelta

import pytest
from pg_helpers import unique
from sqlalchemy import text
from svc_helpers import principal, valid_keys

from diski9.backend.db import db_now, transaction
from diski9.backend.devdata import dev_snapshot
from diski9.backend.services import drafts
from diski9.backend.services import entries as es
from diski9.backend.services import rounds as svc
from diski9.backend.services.common import PublicationRefused


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _strip(snap, ids):
    ids = set(ids)
    return dataclasses.replace(
        snap,
        fixtures=tuple(
            dataclasses.replace(f, estimated_goals=None) if f.fixture_id in ids else f
            for f in snap.fixtures
        ),
        outcomes=tuple(
            dataclasses.replace(o, model_probability=None) if o.fixture_id in ids else o
            for o in snap.outcomes
        ),
    )


def _draft_round(engine, op, seed, mutate=None):
    with transaction(engine) as conn:
        now = db_now(conn)
        config = svc.schedule_config(conn)
    code = unique("dev-p8")
    snap = dev_snapshot(code, now, now + timedelta(hours=3), seed=seed, config=config)
    if mutate:
        snap = mutate(snap)
    v = svc.create_round(engine, op, code=code, window_start=snap.window[0],
                         window_end=snap.window[1], development=True)  # fmt: skip
    return v, snap


def test_publish_with_model_absent_fixtures_stores_nulls(engine, op):
    holder = {}

    def mutate(snap):
        holder["ids"] = [f.fixture_id for f in snap.fixtures[::2]]
        return _strip(snap, holder["ids"])

    v, snap = _draft_round(engine, op, 8101, mutate)
    view = svc.publish_round(engine, op, v.id, snap, source="development")
    assert view.status == "open"
    with transaction(engine) as conn:
        rows = conn.execute(
            text("SELECT f.fixture_id, f.estimated_goals_home, f.estimated_goals_away "
                 "FROM app.snapshot_fixtures f JOIN app.round_snapshots s ON s.id = f.snapshot_id "
                 "WHERE s.round_id = :r"), {"r": v.id}).all()  # fmt: skip
        offers = conn.execute(
            text(
                "SELECT o.fixture_id, o.model_prob, o.market_prob FROM app.snapshot_offers o "
                "JOIN app.round_snapshots s ON s.id = o.snapshot_id WHERE s.round_id = :r"
            ),
            {"r": v.id},
        ).all()
    stripped = set(holder["ids"])
    for fid, h, a in rows:
        assert (h is None and a is None) == (fid in stripped)
    for fid, model, market in offers:
        assert (model is None) == (fid in stripped)  # NULL, never market-filled
        assert market is not None
    # the frozen snapshot reloads identically (fingerprint and NULLs preserved)
    again = svc.published_snapshot(engine, v.id)
    assert again.fingerprint == snap.fingerprint
    assert all((o.model_probability is None) == (o.fixture_id in stripped) for o in again.outcomes)


def test_entry_on_model_absent_picks_stores_null_model_aggregates(engine, op):
    v, snap = _draft_round(engine, op, 8102)
    keys = valid_keys(snap, 9)
    first = keys[0]["fixture_id"]
    snap = _strip(snap, [first])
    svc.publish_round(engine, op, v.id, snap, source="development")
    user = principal(engine)
    d = drafts.save_draft(engine, user, v.id, keys, expected_version=0)
    e = es.confirm_entry(engine, user, v.id, draft_version=d.version,
                         expected_entry_version=0, idempotency_key=uuid.uuid4().hex)  # fmt: skip
    with transaction(engine) as conn:
        sub = conn.execute(
            text("SELECT p_recover_market, p_recover_model, expected_gross_market, "
                 "expected_gross_model, states->'model' AS model_states FROM app.submissions "
                 "WHERE entry_id = :e"), {"e": e.entry_id}).one()  # fmt: skip
        sels = conn.execute(
            text(
                "SELECT fixture_id, model_prob FROM app.submission_selections ss "
                "JOIN app.submissions s ON s.id = ss.submission_id WHERE s.entry_id = :e"
            ),
            {"e": e.entry_id},
        ).all()
    assert sub.p_recover_market is not None and sub.expected_gross_market is not None
    assert sub.p_recover_model is None and sub.expected_gross_model is None
    assert sub.model_states is None or sub.model_states == "null"
    for fid, model in sels:
        assert (model is None) == (fid == first)


def test_publication_refuses_competition_outside_schedule(engine, op):
    def euro(snap):  # one fixture relabelled as the Champions League
        f0, o_ids = snap.fixtures[0], snap.fixtures[0].fixture_id
        return dataclasses.replace(
            snap,
            fixtures=(dataclasses.replace(f0, league_id=2), *snap.fixtures[1:]),
            outcomes=tuple(
                dataclasses.replace(o, league_id=2) if o.fixture_id == o_ids else o
                for o in snap.outcomes
            ),
        )

    v, snap = _draft_round(engine, op, 8103, euro)
    with pytest.raises(PublicationRefused) as exc:
        svc.publish_round(engine, op, v.id, snap, source="development")
    assert "does not allow" in str(exc.value)
    with transaction(engine) as conn:
        assert svc.round_competitions(conn, v.id) == (39, 40, 288, 289, 140, 61, 78, 135)
        status = conn.execute(text("SELECT status FROM app.rounds WHERE id = :r"),
                              {"r": v.id}).scalar_one()  # fmt: skip
    assert status == "draft"  # nothing was published
