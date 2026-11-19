"""Private Your View storage (Phase 6C.3, Stage D; T-10 and D-41).

One row per participant, fixture and **analytical context** holds the current
numerical Match Lab state - Section B ``context``, Section C ``cats`` and Section D
``manual``, each per team - plus the model-context stamp it was made against.
The contexts (approved at the 6C.3 checkpoint) are the live Match Lab
(:class:`LiveContext`) and a published round's frozen snapshot
(:class:`RoundContext`); saving or resetting one never touches the other. Only the
current numbers per context are kept: no notes, reasons, history or attribution
(D-41).

* The owner is always ``principal.user_id``; nothing here is ever read by
  rounds, drafts, submission, settlement or leaderboards.
* The context is determined on the server: the live stamp comes from the
  server's current data, and a round context is looked up from the database
  (snapshot identity and frozen baseline). A stored state is ``active`` only when
  its stamp equals the context's; otherwise it is ``incompatible``, not returned
  for use, and not rewritten by being read.
* Values are validated against the Match Lab's own limits; legacy note fields
  are dropped without changing any number.
* Optimistic versions as for drafts: an older tab cannot overwrite newer work.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from diski9.challenge.roundsheet import RoundSnapshot

from ..auth.permissions import Capability, Principal, authorize
from ..db import read_only, transaction
from ..db.schema import round_snapshots, rounds, snapshot_fixtures, your_view_adjustments
from .common import (
    NotFound,
    ValidationFailed,
    VersionConflict,
    Writer,
    map_db_errors,
    require_active,
    save_decision,
)

# The Match Lab's limits (diski9.app.lab; a test keeps them identical).
SIDES = ("home", "away")
CATEGORY_KEYS = ("squad", "fitness", "tactics", "conditions")
CONTEXT_MAX = 1.0
CATEGORY_MAX = 2.0
ADJUST_MAX = 10.0
# Section D stores final - baseline - B - C, so it stays within this range.
MANUAL_MAX = ADJUST_MAX + CONTEXT_MAX + CATEGORY_MAX * len(CATEGORY_KEYS)
_CONTEXT_RE = re.compile(r"^[^|\s]{1,32}\|(\d{1,19})\|\d{1,2}\.\d{2}\|\d{1,2}\.\d{2}$")

ACTIVE, INCOMPATIBLE, NONE = "active", "incompatible", "none"


@dataclass(frozen=True)
class YourView:
    fixture_id: int
    status: str  # active | incompatible | none
    state: dict | None  # only when compatible with the requested context
    version: int  # 0 when nothing is stored for this context
    updated_at: datetime | None
    stored_context: str | None  # the model-context stamp the stored numbers belong to
    context_kind: str = "live"  # live | round
    snapshot_id: int | None = None


def zero_state() -> dict:
    return {
        "context": {"home": 0.0, "away": 0.0},
        "cats": {k: {"home": 0.0, "away": 0.0} for k in CATEGORY_KEYS},
        "manual": {"home": 0.0, "away": 0.0},
    }


def has_adjustment(state: Mapping) -> bool:
    return any(
        abs(state["context"][s]) > 1e-9
        or abs(state["manual"][s]) > 1e-9
        or any(abs(state["cats"][k][s]) > 1e-9 for k in CATEGORY_KEYS)
        for s in SIDES
    )


def frozen_context(snapshot: RoundSnapshot, fixture_id: int, model_version: str) -> str | None:
    """The model context of a fixture in a published round (its frozen baseline),
    in the same format as the live Match Lab stamp. ``model_version`` is the
    round's (``goal-model-1.0`` or ``1.0``)."""
    try:
        f = snapshot.fixture(fixture_id)
    except KeyError:
        return None
    if f.estimated_goals is None:
        return None
    version = model_version.removeprefix("goal-model-")
    h, a = (round(x, 2) for x in f.estimated_goals)
    return f"{version}|{fixture_id}|{h:.2f}|{a:.2f}"


def _number(v, limit: float, where: str, issues: list) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        issues.append({"field": where, "reason": "not_a_number"})
        return 0.0
    f = float(v)
    if abs(f) > limit + 1e-9:
        issues.append({"field": where, "reason": "out_of_range", "limit": limit})
    if abs(f * 100 - round(f * 100)) > 1e-6:
        issues.append({"field": where, "reason": "too_precise"})
    return round(f, 2)


def clean_state(raw: Any) -> dict:
    """The numeric state, validated. Legacy note and reason fields are dropped;
    numbers are never changed; unknown factors are refused."""
    if not isinstance(raw, Mapping):
        raise ValidationFailed("Your View could not be read.", [{"reason": "malformed"}])
    issues: list[dict] = []
    out = zero_state()
    for section, limit in (("context", CONTEXT_MAX), ("manual", MANUAL_MAX)):
        part = raw.get(section) or {}
        if not isinstance(part, Mapping):
            issues.append({"field": section, "reason": "malformed"})
            continue
        for s in SIDES:
            out[section][s] = _number(part.get(s, 0.0), limit, f"{section}.{s}", issues)
    cats = raw.get("cats") or {}
    if not isinstance(cats, Mapping):
        issues.append({"field": "cats", "reason": "malformed"})
        cats = {}
    for key, part in cats.items():
        if key not in CATEGORY_KEYS:
            issues.append({"field": f"cats.{key}", "reason": "unknown_factor"})
            continue
        if not isinstance(part, Mapping):
            issues.append({"field": f"cats.{key}", "reason": "malformed"})
            continue
        for s in SIDES:  # any "note" beside the numbers is ignored (D-41)
            out["cats"][key][s] = _number(part.get(s, 0.0), CATEGORY_MAX, f"cats.{key}.{s}", issues)
    if issues:
        raise ValidationFailed("Some adjustments are outside the allowed range.", issues)
    return out


def _check_context(fixture_id: int, context: str) -> None:
    m = _CONTEXT_RE.match(context or "")
    if not m or int(m.group(1)) != fixture_id:
        raise ValidationFailed(
            "The model context does not match this fixture.", [{"reason": "context"}]
        )


def _fixture(fixture_id) -> int:
    if isinstance(fixture_id, bool) or not isinstance(fixture_id, int) or fixture_id <= 0:
        raise ValidationFailed("Unknown fixture.", [{"reason": "fixture"}])
    return fixture_id


# ------------------------------------------------------------------ contexts
@dataclass(frozen=True)
class LiveContext:
    """The live Match Lab (All Upcoming Fixtures). ``model_context`` must be computed
    on the server from the current data (``app.lab.model_context``)."""

    fixture_id: int
    model_context: str


@dataclass(frozen=True)
class RoundContext:
    """A published round's frozen context. The snapshot and the frozen baseline
    are looked up in the database; nothing about them comes from the caller."""

    round_id: UUID
    fixture_id: int


Context = LiveContext | RoundContext


@dataclass(frozen=True)
class _Resolved:
    kind: str  # live | round
    fixture_id: int
    snapshot_id: int | None
    model_context: str


def _resolve(conn: Connection, ctx: Context, cache: dict | None = None) -> _Resolved:
    if isinstance(ctx, LiveContext):
        fid = _fixture(ctx.fixture_id)
        _check_context(fid, ctx.model_context)
        return _Resolved("live", fid, None, ctx.model_context)
    if not isinstance(ctx, RoundContext):
        raise ValidationFailed("Unknown analysis context.", [{"reason": "context"}])
    fid = _fixture(ctx.fixture_id)
    key = ("round", ctx.round_id)
    if cache is None or key not in cache:
        head = conn.execute(
            select(round_snapshots.c.id, rounds.c.model_version, rounds.c.status)
            .join(rounds, rounds.c.id == round_snapshots.c.round_id)
            .where(round_snapshots.c.round_id == ctx.round_id)
        ).one_or_none()
        if head is None or head.status == "draft":
            raise NotFound("This round has no published snapshot.")
        fixtures = {
            r.fixture_id: r
            for r in conn.execute(
                select(
                    snapshot_fixtures.c.fixture_id,
                    snapshot_fixtures.c.estimated_goals_home,
                    snapshot_fixtures.c.estimated_goals_away,
                ).where(snapshot_fixtures.c.snapshot_id == head.id)
            )
        }
        found = (head, fixtures)
        if cache is not None:
            cache[key] = found
    else:
        found = cache[key]
    head, fixtures = found
    f = fixtures.get(fid)
    if f is None:
        raise NotFound("This match is not part of the round's snapshot.")
    if f.estimated_goals_home is None or f.estimated_goals_away is None:
        raise ValidationFailed(
            "This match has no frozen baseline to adjust.", [{"reason": "no_baseline"}]
        )
    version = (head.model_version or "").removeprefix("goal-model-")
    stamp = (
        f"{version}|{fid}|{round(f.estimated_goals_home, 2):.2f}|"
        f"{round(f.estimated_goals_away, 2):.2f}"
    )
    return _Resolved("round", fid, head.id, stamp)


def _row(conn: Connection, uid: UUID, r: _Resolved, *, for_update: bool = False):
    q = select(your_view_adjustments).where(
        your_view_adjustments.c.user_id == uid,
        your_view_adjustments.c.fixture_id == r.fixture_id,
        your_view_adjustments.c.context_kind == r.kind,
        your_view_adjustments.c.snapshot_id.is_not_distinct_from(r.snapshot_id),
    )
    if for_update:
        q = q.with_for_update()
    return conn.execute(q).one_or_none()


def _view(row, r: _Resolved) -> YourView:
    if row is None:
        return YourView(r.fixture_id, NONE, None, 0, None, None, r.kind, r.snapshot_id)
    if row.model_context != r.model_context:
        return YourView(
            r.fixture_id,
            INCOMPATIBLE,
            None,
            row.version,
            row.updated_at,
            row.model_context,
            r.kind,
            r.snapshot_id,
        )
    state = clean_state(row.state)
    status = ACTIVE if has_adjustment(state) else NONE
    return YourView(
        r.fixture_id,
        status,
        state,
        row.version,
        row.updated_at,
        row.model_context,
        r.kind,
        r.snapshot_id,
    )


def resolved_context(engine: Engine, ctx: Context) -> str:
    """The model-context stamp the server uses for ``ctx`` (for display and tests)."""
    with read_only(engine) as conn:
        return _resolve(conn, ctx).model_context


def get_your_view(engine: Engine, principal: Principal, ctx: Context) -> YourView:
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    with read_only(engine) as conn:
        r = _resolve(conn, ctx)
        return _view(_row(conn, principal.user_id, r), r)


def get_many(engine: Engine, principal: Principal, contexts) -> dict:
    """Your View for several contexts in one transaction ({context: YourView})."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    contexts = list(contexts)
    if not contexts:
        return {}
    with read_only(engine) as conn:
        cache: dict = {}
        out = {}
        for ctx in contexts:
            try:
                r = _resolve(conn, ctx, cache)
            except (NotFound, ValidationFailed):
                continue
            out[ctx] = _view(_row(conn, principal.user_id, r), r)
        return out


def write_in(
    conn: Connection,
    uid: UUID,
    ctx: Context,
    state: Any,
    expected_version: int,
    writer: Writer | None = None,
) -> YourView:
    """Save inside an open transaction (also used by guest adoption)."""
    r = _resolve(conn, ctx)
    clean = clean_state(state)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ValidationFailed("Missing version.", [{"reason": "version"}])
    row = _row(conn, uid, r, for_update=True)
    if row is not None and row.model_context == r.model_context and row.state == clean:
        return _view(row, r)  # nothing changed: no write
    decision = save_decision(row, expected_version, writer)
    if decision == "superseded":
        return _view(row, r)  # an older request from this tab: ignored
    if decision == "conflict":
        raise VersionConflict(
            "Your View for this match was changed in another tab or on another device. "
            "Reload it to continue.",
            _view(row, r),
        )
    if row is None:
        new = conn.execute(
            pg_insert(your_view_adjustments)
            .values(
                user_id=uid,
                fixture_id=r.fixture_id,
                context_kind=r.kind,
                snapshot_id=r.snapshot_id,
                model_context=r.model_context,
                state=clean,
                version=1,
                writer_tab=writer.tab if writer else None,
                writer_seq=writer.seq if writer else None,
            )
            .on_conflict_do_nothing(constraint="uq_your_view_context")
            .returning(your_view_adjustments)
        ).one_or_none()
        if new is None:
            raise VersionConflict(
                "Your View for this match was saved on another device a moment ago.",
                _view(_row(conn, uid, r), r),
            )
        return _view(new, r)
    new = conn.execute(
        update(your_view_adjustments)
        .where(
            your_view_adjustments.c.id == row.id,
            your_view_adjustments.c.version == row.version,
        )
        .values(
            model_context=r.model_context,
            state=clean,
            version=your_view_adjustments.c.version + 1,
            updated_at=func.transaction_timestamp(),
            writer_tab=writer.tab if writer else None,
            writer_seq=writer.seq if writer else None,
        )
        .returning(your_view_adjustments)
    ).one()
    return _view(new, r)


def save_your_view(
    engine: Engine,
    principal: Principal,
    ctx: Context,
    state: Any,
    *,
    expected_version: int,
    writer: Writer | None = None,
) -> YourView:
    """Store the current numbers for this context only. A reset stores zeros (the
    row and its version remain). The other context of the same match is never
    touched."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    clean_state(state)  # validate before opening a transaction
    with map_db_errors(), transaction(engine) as conn:
        require_active(conn, principal.user_id)
        return write_in(conn, principal.user_id, ctx, state, expected_version, writer)


def reset_your_view(
    engine: Engine,
    principal: Principal,
    ctx: Context,
    *,
    expected_version: int,
    writer: Writer | None = None,
) -> YourView:
    return save_your_view(
        engine, principal, ctx, zero_state(), expected_version=expected_version, writer=writer
    )
