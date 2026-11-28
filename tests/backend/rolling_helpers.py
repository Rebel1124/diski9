"""Helpers for rolling-entry (rules ``rolling/v1``) tests on real PostgreSQL (Phase 8
R2). Rolling schedules are created on their own codes in the disposable test
database only; no hosted database ever holds such a row before activation."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import timedelta
from decimal import Decimal

import sqlalchemy as sa
from pg_helpers import unique

from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import round_schedules
from diski9.backend.devdata import _odds, dev_snapshot
from diski9.backend.services import drafts, review, rolling
from diski9.backend.services import entries as es
from diski9.backend.services import rounds as svc
from diski9.challenge.config import get_config
from diski9.challenge.structured import selection_blocks


def key() -> str:
    return "r2-" + uuid.uuid4().hex


def now_of(engine):
    with transaction(engine) as conn:
        return db_now(conn)


def rolling_schedule(engine, *, close_at, buffer: int = 15) -> str:
    with transaction(engine) as conn:
        base = conn.execute(
            sa.select(round_schedules)
            .where(round_schedules.c.code == "weekend", round_schedules.c.active_to.is_(None))
        ).one()  # fmt: skip
        row = {k: v for k, v in base._mapping.items() if k not in ("id", "active_to")}
        code = unique("rolling")
        rule = dict(rolling.ROLLING_PUBLISH_RULE)
        rule["entry_close"] = {"weekday": rolling.WEEKDAYS[close_at.weekday()],
                               "time": close_at.strftime("%H:%M:%S"), "tz": "UTC"}  # fmt: skip
        row.update(code=code, version=1, rules_version=rolling.ROLLING_RULES_VERSION,
                   window_rule=rolling.ROLLING_WINDOW_RULE, publish_rule=rule,
                   deadline_buffer_minutes=buffer,
                   settle_cutoff_hours=rolling.ROLLING_SETTLE_CUTOFF_HOURS)  # fmt: skip
        conn.execute(sa.insert(round_schedules).values(**row))
    return code


def publish_rolling(engine, op, *, close_in=timedelta(days=1),
                    first_kickoff_in=timedelta(hours=1), seed=2026, fixtures=20):  # fmt: skip
    now = now_of(engine)
    close = (now + close_in).replace(microsecond=0)
    code = rolling_schedule(engine, close_at=close)
    rcode = unique("dev-r2")
    with transaction(engine) as conn:
        cfg = conn.execute(
            sa.select(round_schedules.c.config_version).where(round_schedules.c.code == code)
        ).scalar_one()
    snap = dev_snapshot(rcode, now, now + first_kickoff_in, seed=seed, config=get_config(cfg),
                        fixtures=fixtures)  # fmt: skip
    v = svc.create_round(engine, op, code=rcode, window_start=snap.window[0],
                         window_end=snap.window[1], schedule_code=code, development=True)  # fmt: skip
    return svc.publish_round(engine, op, v.id, snap, source="development"), snap, close


def reprice(snap, at, *, changes=None, observed=None, provider=None, drop=(), only=None):
    """A candidate edition of ``snap`` built at ``at``: market probabilities replaced
    for the keys in ``changes`` (odds follow), evidence timestamps set to ``observed``
    / ``provider`` (default: ``at`` minus one minute), fixtures in ``drop`` left out,
    ``only`` (keys) restricting which outcomes get the new evidence."""
    changes = changes or {}
    observed = observed or at - timedelta(minutes=1)
    provider = provider or observed
    outs = []
    for o in snap.outcomes:
        if o.fixture_id in drop:
            continue
        p = changes.get(o.key, o.market_probability)
        fresh = only is None or o.key in only
        outs.append(dataclasses.replace(
            o, market_probability=p,
            reference_odds=_odds(p) if o.key in changes else o.reference_odds,
            latest_observation_at=observed if fresh else o.latest_observation_at,
            oldest_observation_at=observed if fresh else o.oldest_observation_at,
            provider_updated_at=provider if fresh else o.provider_updated_at,
        ))  # fmt: skip
    return dataclasses.replace(
        snap, snapshot_at=at, outcomes=tuple(outs),
        fixtures=tuple(f for f in snap.fixtures if f.fixture_id not in drop),
    )  # fmt: skip


def keys_excluding(snap, exclude=frozenset(), n: int = 9) -> list[dict]:
    pool = [o for o in snap.outcomes if o.fixture_id not in exclude]
    chosen = []
    for o in pool:
        if len(chosen) == n:
            break
        if selection_blocks(chosen, pool, snap.snapshot_at, snap.config).get(o.key) is None:
            chosen.append(o)
    assert len(chosen) == n
    return [{"fixture_id": o.fixture_id, "market": str(o.market), "outcome": str(o.outcome)}
            for o in chosen]  # fmt: skip


def save(engine, p, view, keys, version=0):
    return drafts.save_draft(engine, p, view.id, keys, expected_version=version)


def reviewed(engine, p, view) -> list[str]:
    return list(review.review_portfolio(engine, p, view.id).digests)


def confirm(engine, p, view, d, version=0, **kw):
    if "reviewed" not in kw:
        kw["reviewed"] = reviewed(engine, p, view)
    return es.confirm_entry(engine, p, view.id, draft_version=d.version,
                            expected_entry_version=version,
                            idempotency_key=kw.pop("k", key()), **kw)  # fmt: skip


def bump(p: float, by: float = 0.02) -> float:
    """A probability moved enough to change its displayed value (and odds)."""
    return float(Decimal(repr(p)) + Decimal(repr(by)))
