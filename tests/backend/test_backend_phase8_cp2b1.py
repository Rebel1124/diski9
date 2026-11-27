"""Phase 8 CP2B.1 on real PostgreSQL: a published round fixture frozen without
independent estimated goals gets its frozen market-implied starting point as its Your
View context (computed on the server from the stored snapshot), saving and reading
Your View works against it, the stored snapshot is unchanged, and a fixture without a
reliable frozen fit still has no baseline (State C)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from pg_helpers import unique
from svc_helpers import principal

from diski9.backend.db import db_now, transaction
from diski9.backend.devdata import _odds, dev_snapshot
from diski9.backend.services import rounds as svc
from diski9.backend.services import your_view as yv
from diski9.backend.services.common import ValidationFailed
from diski9.screener import goal_model as gm
from diski9.screener import market_fit as mf

KEYS = {"HOME": "home", "DRAW": "draw", "AWAY": "away", "BTTS_YES": "btts_yes",
        "BTTS_NO": "btts_no", "OVER_2_5": "over", "UNDER_2_5": "under"}  # fmt: skip


@pytest.fixture(scope="module")
def op(engine):
    return principal(engine, role="operator")


def _prepare(snap, consistent, incoherent):
    """``consistent``: no model, market priced from one Poisson pair (a reliable fit).
    ``incoherent``: no model, the development data's independent random prices."""
    p = gm.markets(1.65, 1.05)
    outs = []
    for o in snap.outcomes:
        if o.fixture_id == consistent:
            q = p[KEYS[str(o.outcome)]]
            o = dataclasses.replace(o, market_probability=q, reference_odds=_odds(q),
                                    model_probability=None)  # fmt: skip
        elif o.fixture_id == incoherent:
            o = dataclasses.replace(o, model_probability=None)
        outs.append(o)
    fixtures = tuple(
        dataclasses.replace(f, estimated_goals=None) if f.fixture_id in (consistent, incoherent)
        else f
        for f in snap.fixtures
    )  # fmt: skip
    return dataclasses.replace(snap, fixtures=fixtures, outcomes=tuple(outs))


def _publish(engine, op):
    with transaction(engine) as conn:
        now = db_now(conn)
        config = svc.schedule_config(conn)
    code = unique("dev-p8b")
    snap = dev_snapshot(code, now, now + timedelta(hours=3), seed=8201, config=config)
    ids = [f.fixture_id for f in snap.fixtures]
    consistent = ids[0]
    probe = _prepare(snap, consistent, ids[1])
    incoherent = next(  # a model-absent fixture whose frozen prices do not fit reliably
        (fid for fid in ids[1:] if not mf.frozen_fit(_prepare(snap, consistent, fid), fid)
         .reliable), None)  # fmt: skip
    assert incoherent is not None
    probe = _prepare(snap, consistent, incoherent)
    v = svc.create_round(engine, op, code=code, window_start=probe.window[0],
                         window_end=probe.window[1], development=True)  # fmt: skip
    svc.publish_round(engine, op, v.id, probe, source="development")
    return v, probe, consistent, incoherent, ids[2]


def test_frozen_market_implied_your_view_context(engine, op):
    v, sent, consistent, incoherent, modelled = _publish(engine, op)
    stored = svc.published_snapshot(engine, v.id)
    assert stored.fingerprint == sent.fingerprint
    expect = mf.frozen_fit(stored, consistent)
    assert expect.reliable and expect.context == "frozen"
    ctx = yv.RoundContext(v.id, consistent)
    stamp = yv.resolved_context(engine, ctx)
    assert stamp == expect.stamp() and stamp.startswith("mi1.0:")
    # the modelled fixture keeps its Goal Model stamp; the incoherent one has no baseline
    assert not yv.resolved_context(engine, yv.RoundContext(v.id, modelled)).startswith("mi")
    with pytest.raises(ValidationFailed) as exc:
        yv.resolved_context(engine, yv.RoundContext(v.id, incoherent))
    assert exc.value.issues == [{"reason": "no_baseline"}]
    # Your View saves and reads back against the market-implied starting point
    user = principal(engine)
    state = yv.zero_state()
    state["manual"]["home"] = 0.25
    saved = yv.save_your_view(engine, user, ctx, state, expected_version=0)
    got = yv.get_your_view(engine, user, ctx)
    assert got.status == yv.ACTIVE and got.state["manual"]["home"] == 0.25
    assert got.stored_context == stamp and saved.version == got.version
    assert yv.saved_round_fixtures(engine, user, v.id) == {consistent}
    many = yv.get_many(engine, user, [ctx, yv.RoundContext(v.id, incoherent)])
    assert set(many) == {ctx} and many[ctx].status == yv.ACTIVE
    # nothing about the stored snapshot changed; model fields stay NULL
    again = svc.published_snapshot(engine, v.id)
    assert again.fingerprint == sent.fingerprint
    assert again.fixture(consistent).estimated_goals is None
    assert all(o.model_probability is None for o in again.outcomes
               if o.fixture_id == consistent)  # fmt: skip
