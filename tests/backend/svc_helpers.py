"""Helpers for the Phase 6C.3 service tests (real PostgreSQL)."""

from __future__ import annotations

import time
from datetime import timedelta

from pg_helpers import make_user, unique
from sqlalchemy import insert

from diski9.backend.auth.permissions import Principal
from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import user_roles
from diski9.backend.devdata import dev_snapshot
from diski9.backend.services import rounds as svc
from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.structured import selection_blocks


def principal(engine, *, role: str | None = None, user_id=None) -> Principal:
    """A server-built principal for a new (or given) onboarded account."""
    with transaction(engine) as conn:
        uid = user_id or make_user(conn)
        if role:
            conn.execute(insert(user_roles).values(user_id=uid, role=role))
        now = db_now(conn)
    return Principal(
        user_id=uid,
        roles=frozenset({role} if role else ()),
        onboarded=True,
        authenticated_at=now,
        now=now,
    )


def publish_dev(engine, op: Principal, *, deadline_in=timedelta(hours=2), seed=2026, **kw):
    """Create and publish a development round through the services."""
    with transaction(engine) as conn:
        now = db_now(conn)
    code = unique("dev-t")
    snap = dev_snapshot(code, now, now + deadline_in + timedelta(minutes=15), seed=seed, **kw)
    v = svc.create_round(
        engine,
        op,
        code=code,
        window_start=snap.window[0],
        window_end=snap.window[1],
        development=True,
    )
    return svc.publish_round(engine, op, v.id, snap, source="development"), snap


def valid_keys(snap, n: int = 9) -> list[dict]:
    """A completable selection list of ``n`` outcomes (the builder's own rules)."""
    chosen = []
    for o in snap.outcomes:
        if len(chosen) == n:
            break
        blocks = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, DEFAULT_CONFIG)
        if blocks.get(o.key) is None:
            chosen.append(o)
    return [
        {"fixture_id": o.fixture_id, "market": str(o.market), "outcome": str(o.outcome)}
        for o in chosen
    ]


def wait_until(engine, moment) -> None:
    while True:
        with transaction(engine) as conn:
            if db_now(conn) >= moment:
                return
        time.sleep(0.2)
