"""Explicit adoption of guest work into a signed-in account (T-15; guest Your View
approved at the 6C.3 checkpoint).

Guest work lives only in the browser tab and is **untrusted**: selections are
re-checked against the current published snapshot, and each numerical Your View
state against the context the server computes (live data, or the round's frozen
snapshot). Signing in alone saves nothing.

Two steps:

1. :func:`plan_adoption` (read-only) says, for the draft and each Your View
   state, whether it can be saved (``ready``), is already identical (``same``),
   would replace different saved account work (``conflict``) or cannot be adopted
   (``rejected``, with a reason). It records the account versions it saw.
2. :func:`adopt` re-runs the same checks and writes everything in **one
   transaction**, using the versions from the plan. Conflicting account work is
   replaced only when the participant chose to replace it; otherwise it is kept.
   If anything changed in the account since the plan, or any write fails, nothing
   is saved and the caller is told so (no partial adoption, no false success).

Nothing is ever confirmed, and an existing confirmed entry is never touched.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select

from ..auth.permissions import Capability, Principal, authorize
from ..db import db_now, read_only, transaction
from ..db.schema import portfolio_drafts, rounds
from . import drafts as drafts_svc
from . import snapshots
from . import your_view as yv
from .common import (
    NotFound,
    ServiceError,
    ValidationFailed,
    VersionConflict,
    map_db_errors,
    require_active,
)

LiveStamp = Callable[[int], str | None]  # server-side live model context, or None

REASONS = {
    "round_closed": "The round is closed, so this portfolio can no longer be saved.",
    "other_round": "This portfolio was built for a different or earlier round.",
    "invalid": "Some predictions are no longer valid for this round.",
    "no_round": "There is no published round to save this portfolio to.",
    "context_changed": "The model baseline for this match has changed since you made it.",
    "unknown_match": "This match is not available any more.",
    "invalid_values": "These adjustments are outside the allowed range.",
}


@dataclass(frozen=True)
class AdoptionItem:
    kind: str  # draft | live | round
    key: str  # stable identifier within the plan
    status: str  # ready | same | conflict | rejected | empty
    reason: str | None = None
    account_version: int = 0
    label: str = ""


@dataclass(frozen=True)
class AdoptionPlan:
    items: tuple[AdoptionItem, ...]
    versions: dict = field(default_factory=dict)

    @property
    def conflicts(self) -> list[AdoptionItem]:
        return [i for i in self.items if i.status == "conflict"]

    @property
    def adoptable(self) -> list[AdoptionItem]:
        return [i for i in self.items if i.status in ("ready", "conflict")]

    @property
    def rejected(self) -> list[AdoptionItem]:
        return [i for i in self.items if i.status == "rejected"]


@dataclass(frozen=True)
class AdoptionResult:
    saved: tuple[str, ...]
    kept_account: tuple[str, ...]
    rejected: tuple[AdoptionItem, ...]


def _draft_item(conn: Connection, uid: UUID, guest: Mapping | None) -> AdoptionItem | None:
    if not guest or not guest.get("selections"):
        return None
    rid = guest.get("round_id")
    try:
        rid = UUID(str(rid))
    except (TypeError, ValueError):
        return AdoptionItem("draft", "draft", "rejected", REASONS["other_round"])
    r = conn.execute(
        select(rounds.c.status, rounds.c.deadline_at).where(rounds.c.id == rid)
    ).one_or_none()
    if r is None or r.status == "draft":
        return AdoptionItem("draft", "draft", "rejected", REASONS["no_round"])
    if r.status != "open" or db_now(conn) >= r.deadline_at:
        return AdoptionItem("draft", f"draft:{rid}", "rejected", REASONS["round_closed"])
    snap = snapshots.CACHE.get(conn, rid)
    if guest.get("fingerprint") != snap.fingerprint:
        return AdoptionItem("draft", f"draft:{rid}", "rejected", REASONS["other_round"])
    try:
        sels = drafts_svc.parse_selections(guest["selections"])
        drafts_svc.validate_selections(snap, sels, snap.config)
    except ValidationFailed:
        return AdoptionItem("draft", f"draft:{rid}", "rejected", REASONS["invalid"])
    row = conn.execute(
        select(portfolio_drafts).where(
            portfolio_drafts.c.user_id == uid, portfolio_drafts.c.round_id == rid
        )
    ).one_or_none()
    label = f"Weekly Challenge portfolio ({len(sels)}/9)"
    if row is None or not row.selections:
        return AdoptionItem(
            "draft", f"draft:{rid}", "ready", None, row.version if row else 0, label
        )
    if list(row.selections) == sels:
        return AdoptionItem("draft", f"draft:{rid}", "same", None, row.version, label)
    return AdoptionItem("draft", f"draft:{rid}", "conflict", None, row.version, label)


def _view_context(item: Mapping, live_stamp: LiveStamp):
    fid = item.get("fixture_id")
    if item.get("kind") == "round":
        return yv.RoundContext(UUID(str(item["round_id"])), int(fid))
    stamp = live_stamp(int(fid))
    if stamp is None:
        raise NotFound("unknown match")
    return yv.LiveContext(int(fid), stamp)


def _view_item(conn: Connection, uid: UUID, item: Mapping, live_stamp: LiveStamp):
    kind = "round" if item.get("kind") == "round" else "live"
    key = f"{kind}:{item.get('round_id') or ''}:{item.get('fixture_id')}"
    label = str(item.get("label") or "")[:80]
    try:
        ctx = _view_context(item, live_stamp)
        resolved = yv._resolve(conn, ctx)
        state = yv.clean_state(item.get("state"))
    except (NotFound, KeyError, TypeError, ValueError):
        return AdoptionItem(kind, key, "rejected", REASONS["unknown_match"], label=label), None
    except ValidationFailed as exc:
        reason = "invalid_values" if any("field" in i for i in exc.issues) else "unknown_match"
        return AdoptionItem(kind, key, "rejected", REASONS[reason], label=label), None
    if not yv.has_adjustment(state):
        return AdoptionItem(kind, key, "empty", label=label), None
    if item.get("stamp") != resolved.model_context:  # made against another baseline
        return AdoptionItem(kind, key, "rejected", REASONS["context_changed"], label=label), None
    row = yv._row(conn, uid, resolved)
    current = yv._view(row, resolved)
    if row is None or current.status != yv.ACTIVE:
        return AdoptionItem(kind, key, "ready", None, current.version, label), (ctx, state)
    if current.state == state:
        return AdoptionItem(kind, key, "same", None, current.version, label), (ctx, state)
    return AdoptionItem(kind, key, "conflict", None, current.version, label), (ctx, state)


def _plan(conn, uid, guest_draft, guest_views, live_stamp):
    items, work = [], {}
    d = _draft_item(conn, uid, guest_draft)
    if d is not None:
        items.append(d)
        if d.status in ("ready", "conflict"):
            work[d.key] = ("draft", guest_draft)
    for raw in list(guest_views or [])[:200]:
        if not isinstance(raw, Mapping):
            continue
        it, payload = _view_item(conn, uid, raw, live_stamp)
        if it.status == "empty":
            continue
        items.append(it)
        if it.status in ("ready", "conflict"):
            work[it.key] = ("view", payload)
    return AdoptionPlan(tuple(items), {i.key: i.account_version for i in items}), work


def plan_adoption(
    engine: Engine,
    principal: Principal,
    *,
    guest_draft: Mapping | None,
    guest_views: Iterable[Mapping[str, Any]] | None,
    live_stamp: LiveStamp,
) -> AdoptionPlan:
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    with read_only(engine) as conn:
        plan, _ = _plan(conn, principal.user_id, guest_draft, guest_views, live_stamp)
        return plan


class AdoptionStale(ServiceError):
    code = "adoption_stale"


def adopt(
    engine: Engine,
    principal: Principal,
    plan: AdoptionPlan,
    *,
    guest_draft: Mapping | None,
    guest_views: Iterable[Mapping[str, Any]] | None,
    live_stamp: LiveStamp,
    replace_conflicts: bool,
) -> AdoptionResult:
    """Save the adoptable guest work in one transaction (see the module notes)."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    uid = principal.user_id
    saved, kept = [], []
    try:
        with map_db_errors(), transaction(engine) as conn:
            require_active(conn, uid)
            now_plan, work = _plan(conn, uid, guest_draft, guest_views, live_stamp)
            for item in now_plan.items:
                if plan.versions.get(item.key, item.account_version) != item.account_version:
                    raise AdoptionStale(
                        "Your account's saved work changed while you were deciding. "
                        "Nothing was saved; please review again."
                    )
            for item in now_plan.adoptable:
                if item.status == "conflict" and not replace_conflicts:
                    kept.append(item.key)
                    continue
                kind, payload = work[item.key]
                if kind == "draft":
                    _save_draft_in(conn, uid, payload, item.account_version)
                else:
                    ctx, state = payload
                    yv.write_in(conn, uid, ctx, state, item.account_version)
                saved.append(item.key)
            rejected = tuple(now_plan.rejected)
    except VersionConflict:
        raise AdoptionStale(
            "Your account's saved work changed while you were deciding. "
            "Nothing was saved; please review again."
        ) from None
    return AdoptionResult(tuple(saved), tuple(kept), rejected)


def _save_draft_in(conn: Connection, uid: UUID, guest: Mapping, expected: int) -> None:
    """Write the adopted draft inside the adoption transaction (same rules as
    :func:`drafts.save_draft`, which validated it in the plan)."""
    from sqlalchemy import update
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rid = UUID(str(guest["round_id"]))
    r = drafts_svc._round(conn, rid, for_share=True)
    conn.execute(
        select(portfolio_drafts.c.version)
        .where(portfolio_drafts.c.user_id == uid, portfolio_drafts.c.round_id == rid)
        .with_for_update()
    )
    drafts_svc.ensure_before_deadline(conn, r)
    snap = snapshots.CACHE.get(conn, rid)
    sels = drafts_svc.parse_selections(guest["selections"])
    drafts_svc.validate_selections(snap, sels, snap.config)
    if expected == 0:
        row = conn.execute(
            pg_insert(portfolio_drafts)
            .values(
                user_id=uid,
                round_id=rid,
                selections=sels,
                snapshot_fingerprint=snap.fingerprint,
                version=1,
            )
            .on_conflict_do_nothing()
            .returning(portfolio_drafts.c.version)
        ).one_or_none()
    else:
        row = conn.execute(
            update(portfolio_drafts)
            .where(
                portfolio_drafts.c.user_id == uid,
                portfolio_drafts.c.round_id == rid,
                portfolio_drafts.c.version == expected,
            )
            .values(
                selections=sels,
                snapshot_fingerprint=snap.fingerprint,
                version=portfolio_drafts.c.version + 1,
            )
            .returning(portfolio_drafts.c.version)
        ).one_or_none()
    if row is None:
        raise VersionConflict("draft changed", None)
