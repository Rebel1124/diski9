"""Result observations and settlement alerts (Phase 6C.4).

Observations are insert-only evidence. Provider and synthetic rows are deduplicated
against the observation that **precedes** them in receipt order for the same
fixture and scope, under a transaction-scoped advisory lock, so identical repeated
deliveries add nothing while a genuine return to an earlier state (A -> B -> A)
is recorded (S-05). Ordering is by our receipt time ``observed_at`` (then ``id``),
so an older fetch that commits late never becomes the latest evidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, and_, insert, select, text

from ...challenge.settle import Alert, Observation
from ..db.schema import result_observations, settlement_alert_resolutions, settlement_alerts

RO = result_observations


def _lock_fixture(conn: Connection, fixture_id: int, scope: UUID | None) -> None:
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"diski9:observation:{fixture_id}:{scope or 'real'}"},
    )


def _predecessor_hash(
    conn: Connection, fixture_id: int, sources: Sequence[str], scope: UUID | None, at: datetime
) -> str | None:
    scope_cond = RO.c.scope_round_id.is_(None) if scope is None else RO.c.scope_round_id == scope
    return conn.execute(
        select(RO.c.raw_hash)
        .where(
            RO.c.fixture_id == fixture_id,
            RO.c.source.in_(sources),
            scope_cond,
            RO.c.observed_at <= at,
        )
        .order_by(RO.c.observed_at.desc(), RO.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def record_evidence(
    conn: Connection,
    *,
    source: str,
    fixture_id: int,
    observed_at: datetime,
    raw: Any,
    raw_hash: str,
    fields: dict[str, Any],
    scope_round_id: UUID | None = None,
    job_run_id: int | None = None,
) -> int | None:
    """Insert a provider (``api-football``) or ``synthetic`` observation unless it
    is identical to the one preceding it in receipt order. Returns the new ID, or
    ``None`` when nothing changed."""
    if source not in ("api-football", "synthetic"):
        raise ValueError(f"not an evidence source: {source}")
    _lock_fixture(conn, fixture_id, scope_round_id)
    if _predecessor_hash(conn, fixture_id, (source,), scope_round_id, observed_at) == raw_hash:
        return None
    return conn.execute(
        insert(RO)
        .values(
            fixture_id=fixture_id,
            observed_at=observed_at,
            source=source,
            status_short=fields.get("status_short"),
            kickoff_at=fields.get("kickoff_at"),
            ft_home=fields.get("ft_home"),
            ft_away=fields.get("ft_away"),
            provider_first_half_at=fields.get("provider_first_half_at"),
            raw=raw,
            raw_hash=raw_hash,
            job_run_id=job_run_id,
            scope_round_id=scope_round_id,
        )
        .returning(RO.c.id)
    ).scalar_one()


def insert_operator_observation(
    conn: Connection,
    *,
    fixture_id: int,
    observed_at: datetime,
    actor: UUID,
    reason: str,
    evidence: str | None,
    raw: dict,
    raw_hash: str,
    status_short: str | None = None,
    kickoff_at: datetime | None = None,
    ft_home: int | None = None,
    ft_away: int | None = None,
    actual_kickoff_at: datetime | None = None,
    completed_at: datetime | None = None,
    corrects_observation_id: int | None = None,
    withdraws_correction_id: int | None = None,
    original_values: dict | None = None,
    scope_round_id: UUID | None = None,
) -> int:
    return conn.execute(
        insert(RO)
        .values(
            fixture_id=fixture_id,
            observed_at=observed_at,
            source="operator",
            status_short=status_short,
            kickoff_at=kickoff_at,
            ft_home=ft_home,
            ft_away=ft_away,
            actual_kickoff_at=actual_kickoff_at,
            completed_at=completed_at,
            raw=raw,
            raw_hash=raw_hash,
            corrects_observation_id=corrects_observation_id,
            withdraws_correction_id=withdraws_correction_id,
            original_values=original_values,
            actor_user_id=actor,
            reason=reason,
            evidence=evidence,
            scope_round_id=scope_round_id,
        )
        .returning(RO.c.id)
    ).scalar_one()


def _mode_condition(mode: str, round_id: UUID):
    """Real mode reads provider rows and unscoped operator rows only; synthetic
    mode reads only rows scoped to this development round. Never both (S-08)."""
    if mode == "real":
        return and_(RO.c.scope_round_id.is_(None), RO.c.source.in_(("api-football", "operator")))
    if mode == "synthetic":
        return and_(RO.c.scope_round_id == round_id, RO.c.source.in_(("synthetic", "operator")))
    raise ValueError(f"unknown result mode {mode!r}")


def observation_rows(
    conn: Connection, fixture_ids: Iterable[int], *, mode: str, round_id: UUID
) -> list:
    ids = sorted(set(fixture_ids))
    if not ids:
        return []
    return list(
        conn.execute(
            select(RO)
            .where(RO.c.fixture_id.in_(ids), _mode_condition(mode, round_id))
            .order_by(RO.c.fixture_id, RO.c.observed_at, RO.c.id)
        )
    )


def to_observation(row) -> Observation:
    return Observation(
        id=row.id,
        source=row.source,
        observed_at=row.observed_at,
        status=row.status_short,
        scheduled_kickoff=row.kickoff_at,
        ft_home=row.ft_home,
        ft_away=row.ft_away,
        provider_first_half_at=row.provider_first_half_at,
        actual_kickoff_at=row.actual_kickoff_at,
        completed_at=row.completed_at,
        corrects_id=row.corrects_observation_id,
        withdraws_id=row.withdraws_correction_id,
    )


def latest_evidence_row(conn: Connection, fixture_id: int, *, mode: str, round_id: UUID):
    """The latest non-operator observation of a fixture in this mode (what an
    operator correction corrects)."""
    src = "api-football" if mode == "real" else "synthetic"
    cond = _mode_condition(mode, round_id)
    return conn.execute(
        select(RO)
        .where(RO.c.fixture_id == fixture_id, RO.c.source == src, cond)
        .order_by(RO.c.observed_at.desc(), RO.c.id.desc())
        .limit(1)
    ).one_or_none()


def get_observation(conn: Connection, observation_id: int):
    return conn.execute(select(RO).where(RO.c.id == observation_id)).one_or_none()


# ------------------------------------------------------------------ alerts
SA, SR = settlement_alerts, settlement_alert_resolutions


def raise_alerts(
    conn: Connection, round_id: UUID, run_id: int | None, alerts: Iterable[Alert]
) -> list[int]:
    """Insert alerts not already recorded for the round (same fingerprint)."""
    new = []
    for a in alerts:
        rid = conn.execute(
            text(
                "INSERT INTO app.settlement_alerts (round_id, fixture_id, run_id, code, blocking, "
                "fingerprint, detail) VALUES (:r, :f, :run, :c, :b, :fp, CAST(:d AS jsonb)) "
                "ON CONFLICT (round_id, fingerprint) DO NOTHING RETURNING id"
            ),
            {
                "r": round_id,
                "f": a.fixture_id,
                "run": run_id,
                "c": a.code,
                "b": a.blocking,
                "fp": a.fingerprint,
                "d": _json(a.detail),
            },
        ).scalar_one_or_none()
        if rid is not None:
            new.append(rid)
    return new


def _json(d: dict) -> str:
    return json.dumps(d, sort_keys=True, default=str)


def open_alerts(conn: Connection, round_id: UUID, *, blocking_only: bool = False) -> list:
    q = (
        select(SA)
        .outerjoin(SR, SR.c.alert_id == SA.c.id)
        .where(SA.c.round_id == round_id, SR.c.id.is_(None))
        .order_by(SA.c.id)
    )
    if blocking_only:
        q = q.where(SA.c.blocking)
    return list(conn.execute(q))


def resolve_alert(
    conn: Connection,
    alert_id: int,
    *,
    resolution: str,
    reason: str,
    actor: UUID | None,
    observation_id: int | None = None,
) -> int:
    return conn.execute(
        insert(SR)
        .values(
            alert_id=alert_id,
            resolution=resolution,
            actor_user_id=actor,
            reason=reason,
            observation_id=observation_id,
        )
        .returning(SR.c.id)
    ).scalar_one()


def alerts_by_fingerprint(conn: Connection, round_id: UUID, fingerprints: Iterable[str]) -> list:
    fps = list(fingerprints)
    if not fps:
        return []
    return list(
        conn.execute(select(SA).where(SA.c.round_id == round_id, SA.c.fingerprint.in_(fps)))
    )


__all__ = [
    "alerts_by_fingerprint",
    "get_observation",
    "insert_operator_observation",
    "latest_evidence_row",
    "observation_rows",
    "open_alerts",
    "raise_alerts",
    "record_evidence",
    "resolve_alert",
    "to_observation",
]
