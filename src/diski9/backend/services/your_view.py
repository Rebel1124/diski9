"""Private Your View storage (Phase 6C.3, Stage D; T-10 and D-41).

One row per participant and fixture holds the **current numerical** Match Lab
state - Section B ``context``, Section C ``cats`` and Section D ``manual``, each
per team - plus the model-context stamp it was made against. No notes, reasons,
history or attribution are stored (D-41).

* The owner is always ``principal.user_id``; nothing here is ever read by
  rounds, drafts, submission, settlement or leaderboards.
* The caller passes the model context computed **on the server**
  (``app.lab.model_context`` for the live Match Lab, :func:`frozen_context` for a
  published round). A stored state is ``active`` only in that same context;
  otherwise it is reported ``incompatible``, not returned for use, and not
  rewritten by being read.
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

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from diski9.challenge.roundsheet import RoundSnapshot

from ..auth.permissions import Capability, Principal, authorize
from ..db import read_only, transaction
from ..db.schema import your_view_adjustments
from .common import ValidationFailed, VersionConflict, map_db_errors, require_active

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
    state: dict | None  # only when active
    version: int  # 0 when nothing is stored
    updated_at: datetime | None
    stored_context: str | None  # the context the stored numbers belong to


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


def _view(row, fixture_id: int, context: str) -> YourView:
    if row is None:
        return YourView(fixture_id, NONE, None, 0, None, None)
    if row.model_context != context:
        return YourView(
            fixture_id, INCOMPATIBLE, None, row.version, row.updated_at, row.model_context
        )
    state = clean_state(row.state)
    status = ACTIVE if has_adjustment(state) else NONE
    return YourView(fixture_id, status, state, row.version, row.updated_at, row.model_context)


def get_your_view(engine: Engine, principal: Principal, fixture_id: int, context: str) -> YourView:
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    fid = _fixture(fixture_id)
    _check_context(fid, context)
    with read_only(engine) as conn:
        row = conn.execute(
            select(your_view_adjustments).where(
                your_view_adjustments.c.user_id == principal.user_id,
                your_view_adjustments.c.fixture_id == fid,
            )
        ).one_or_none()
    return _view(row, fid, context)


def get_many(
    engine: Engine, principal: Principal, contexts: Mapping[int, str]
) -> dict[int, YourView]:
    """Your View for several fixtures in one query (for portfolio analysis)."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    for fid, ctx in contexts.items():
        _check_context(_fixture(fid), ctx)
    if not contexts:
        return {}
    with read_only(engine) as conn:
        rows = {
            r.fixture_id: r
            for r in conn.execute(
                select(your_view_adjustments).where(
                    your_view_adjustments.c.user_id == principal.user_id,
                    your_view_adjustments.c.fixture_id.in_(list(contexts)),
                )
            )
        }
    return {fid: _view(rows.get(fid), fid, ctx) for fid, ctx in contexts.items()}


def save_your_view(
    engine: Engine,
    principal: Principal,
    fixture_id: int,
    context: str,
    state: Any,
    *,
    expected_version: int,
) -> YourView:
    """Store the current numbers for this fixture in this model context. A reset
    stores zeros (the row and its version remain)."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    fid = _fixture(fixture_id)
    _check_context(fid, context)
    clean = clean_state(state)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ValidationFailed("Missing version.", [{"reason": "version"}])
    uid = principal.user_id
    with map_db_errors(), transaction(engine) as conn:
        require_active(conn, uid)
        row = conn.execute(
            select(your_view_adjustments)
            .where(
                your_view_adjustments.c.user_id == uid, your_view_adjustments.c.fixture_id == fid
            )
            .with_for_update()
        ).one_or_none()
        if row is not None and row.model_context == context and row.state == clean:
            return _view(row, fid, context)  # nothing changed: no write
        current = row.version if row is not None else 0
        if expected_version != current:
            raise VersionConflict(
                "Your View for this match was changed in another tab or on another device. "
                "Reload it to continue.",
                _view(row, fid, context),
            )
        if row is None:
            new = conn.execute(
                pg_insert(your_view_adjustments)
                .values(user_id=uid, fixture_id=fid, model_context=context, state=clean, version=1)
                .on_conflict_do_nothing()
                .returning(your_view_adjustments)
            ).one_or_none()
            if new is None:
                latest = conn.execute(
                    select(your_view_adjustments).where(
                        your_view_adjustments.c.user_id == uid,
                        your_view_adjustments.c.fixture_id == fid,
                    )
                ).one_or_none()
                raise VersionConflict(
                    "Your View for this match was saved on another device a moment ago.",
                    _view(latest, fid, context),
                )
            return _view(new, fid, context)
        new = conn.execute(
            update(your_view_adjustments)
            .where(
                your_view_adjustments.c.user_id == uid,
                your_view_adjustments.c.fixture_id == fid,
                your_view_adjustments.c.version == expected_version,
            )
            .values(
                model_context=context,
                state=clean,
                version=your_view_adjustments.c.version + 1,
                updated_at=func.transaction_timestamp(),
            )
            .returning(your_view_adjustments)
        ).one()
        return _view(new, fid, context)


def reset_your_view(
    engine: Engine, principal: Principal, fixture_id: int, context: str, *, expected_version: int
) -> YourView:
    return save_your_view(
        engine, principal, fixture_id, context, zero_state(), expected_version=expected_version
    )
