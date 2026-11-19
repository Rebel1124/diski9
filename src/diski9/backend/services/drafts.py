"""Private portfolio drafts (Phase 6C.3, Stage C).

A draft is a participant's work in progress for one published round: an ordered
list of outcome keys ``{fixture_id, market, outcome}`` from that round's frozen
snapshot. It follows the participant across sessions and devices. It is never an
entry: confirmation (Stage E) re-validates everything from the snapshot.

Rules:

* the owner is always ``principal.user_id`` from the server session;
* every selection is checked against the frozen snapshot with the builder's
  own rules (``structured.selection_blocks``); an invalid save is refused as a
  whole, never truncated or repaired;
* optimistic concurrency: a save names the version it was based on; an older
  tab or device gets :class:`~.common.VersionConflict` with the latest saved
  draft and nothing is merged;
* a save that changes nothing writes nothing (retries and callback reruns);
* only while the round is open and before its deadline (database clock; a
  trigger enforces the same); afterwards the draft stays readable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import NoResultFound

from diski9.challenge.config import DEFAULT_CONFIG, get_config
from diski9.challenge.roundsheet import RoundSnapshot
from diski9.challenge.structured import SelectionBlock, selection_blocks

from ..auth.permissions import Capability, Principal, authorize
from ..db import db_now, read_only, transaction
from ..db.schema import portfolio_drafts, rounds
from ..repositories import rounds as rounds_repo
from . import snapshots
from .common import (
    NotFound,
    RoundClosed,
    ValidationFailed,
    VersionConflict,
    map_db_errors,
    require_active,
)

MAX_SELECTIONS = sum(DEFAULT_CONFIG.sizes)  # 4 + 3 + 2

REASONS = {
    "malformed": "This selection could not be read.",
    "not_on_sheet": "This outcome is not in this round's frozen snapshot.",
    "duplicate": "This outcome is listed twice.",
    SelectionBlock.INELIGIBLE: "This outcome is not eligible in this round.",
    SelectionBlock.FIXTURE_TAKEN: "Another outcome from this match is already selected.",
    SelectionBlock.BUCKET_FULL: "That risk bucket is already full.",
    SelectionBlock.WOULD_BLOCK_COMPLETION: (
        "Adding this would make a full 4/3/2 portfolio impossible."
    ),
    "too_many": "A portfolio has at most nine predictions.",
}


@dataclass(frozen=True)
class DraftView:
    round_id: UUID
    selections: tuple[dict, ...]
    version: int  # 0 when nothing has been saved yet
    updated_at: datetime | None
    snapshot_fingerprint: str | None
    editable: bool

    @property
    def keys(self) -> list[str]:
        """Selections in the prototype's ``fixture|market|outcome`` form."""
        return [f"{s['fixture_id']}|{s['market']}|{s['outcome']}" for s in self.selections]


def parse_selections(raw: Iterable[Any]) -> list[dict]:
    """Normalise client input (dicts or ``fixture|market|outcome`` strings) into
    outcome keys. Only keys are kept: any odds, bucket or probability a client
    sends is ignored."""
    out, issues = [], []
    items = list(raw or [])
    for pos, item in enumerate(items):
        try:
            if isinstance(item, str):
                fid, market, outcome = item.split("|")
            else:
                fid, market, outcome = item["fixture_id"], item["market"], item["outcome"]
            if isinstance(fid, bool):
                raise ValueError
            fid = int(fid)
            if not (isinstance(market, str) and isinstance(outcome, str)) or fid <= 0:
                raise ValueError
            out.append({"fixture_id": fid, "market": market, "outcome": outcome})
        except (KeyError, TypeError, ValueError, AttributeError):
            issues.append({"position": pos, "reason": "malformed", "message": REASONS["malformed"]})
    if len(items) > MAX_SELECTIONS:
        issues.append({"position": None, "reason": "too_many", "message": REASONS["too_many"]})
    if issues:
        raise ValidationFailed("Some selections could not be saved.", issues)
    return out


def validate_selections(snap: RoundSnapshot, selections: list[dict], config=DEFAULT_CONFIG):
    """The snapshot outcomes for ``selections``, checked in order with the
    builder's rules; raises :class:`ValidationFailed` listing every problem."""
    chosen, issues, seen = [], [], set()
    for pos, s in enumerate(selections):
        key = (s["fixture_id"], s["market"], s["outcome"])
        o = snap.outcome(key)
        if key in seen:
            reason = "duplicate"
        elif o is None:
            reason = "not_on_sheet"
        else:
            reason = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, config).get(o.key)
        seen.add(key)
        if reason is None:
            chosen.append(o)
        else:
            issues.append(
                {
                    "position": pos,
                    "key": f"{key[0]}|{key[1]}|{key[2]}",
                    "reason": str(reason),
                    "message": REASONS[reason],
                }
            )
    if issues:
        raise ValidationFailed("Some selections are not valid for this round.", issues)
    return chosen


def _view(row, round_id: UUID, editable: bool) -> DraftView:
    if row is None:
        return DraftView(round_id, (), 0, None, None, editable)
    return DraftView(
        round_id,
        tuple(dict(s) for s in row.selections),
        row.version,
        row.updated_at,
        row.snapshot_fingerprint,
        editable,
    )


def _round(conn: Connection, round_id: UUID, *, for_share: bool):
    if for_share:
        try:
            return rounds_repo.lock_round_for_submission(conn, round_id)
        except NoResultFound as exc:
            raise NotFound("No such round.") from exc
    r = conn.execute(
        select(rounds.c.id, rounds.c.status, rounds.c.deadline_at).where(rounds.c.id == round_id)
    ).one_or_none()
    if r is None:
        raise NotFound("No such round.")
    return r


def _editable(r, now) -> bool:
    return r.status == "open" and r.deadline_at is not None and now < r.deadline_at


def get_draft(engine: Engine, principal: Principal, round_id: UUID) -> DraftView:
    """The participant's saved draft for a published round (empty if none)."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    with read_only(engine) as conn:
        r = _round(conn, round_id, for_share=False)
        if r.status == "draft":
            raise NotFound("This round has not been published.")
        row = conn.execute(
            select(portfolio_drafts).where(
                portfolio_drafts.c.user_id == principal.user_id,
                portfolio_drafts.c.round_id == round_id,
            )
        ).one_or_none()
        return _view(row, round_id, _editable(r, db_now(conn)))


def save_draft(
    engine: Engine,
    principal: Principal,
    round_id: UUID,
    selections: Iterable[Any],
    *,
    expected_version: int,
) -> DraftView:
    """Save the participant's draft (0–9 selections) if it is valid and still
    based on the latest saved version."""
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    sels = parse_selections(selections)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ValidationFailed("Missing draft version.", [{"reason": "version"}])
    uid = principal.user_id
    with map_db_errors(), transaction(engine) as conn:
        require_active(conn, uid)
        r = _round(conn, round_id, for_share=True)
        if not _editable(r, db_now(conn)):
            raise RoundClosed("This round is closed; your saved draft can no longer change.")
        snap = snapshots.CACHE.get(conn, round_id)
        cfg = conn.execute(
            select(rounds.c.config_version).where(rounds.c.id == round_id)
        ).scalar_one()
        validate_selections(snap, sels, get_config(cfg))
        row = conn.execute(
            select(portfolio_drafts)
            .where(portfolio_drafts.c.user_id == uid, portfolio_drafts.c.round_id == round_id)
            .with_for_update()
        ).one_or_none()
        if row is not None and list(row.selections) == sels:
            return _view(row, round_id, True)  # nothing changed: no write
        current = row.version if row is not None else 0
        if expected_version != current:
            raise VersionConflict(
                "This draft was changed in another tab or on another device. "
                "Load the latest saved draft to continue.",
                _view(row, round_id, True),
            )
        if row is None:
            new = conn.execute(
                pg_insert(portfolio_drafts)
                .values(
                    user_id=uid,
                    round_id=round_id,
                    selections=sels,
                    snapshot_fingerprint=snap.fingerprint,
                    version=1,
                )
                .on_conflict_do_nothing()
                .returning(portfolio_drafts)
            ).one_or_none()
            if new is None:  # another device created it a moment ago
                latest = conn.execute(
                    select(portfolio_drafts).where(
                        portfolio_drafts.c.user_id == uid, portfolio_drafts.c.round_id == round_id
                    )
                ).one_or_none()
                raise VersionConflict(
                    "This draft was saved on another device a moment ago. "
                    "Load the latest saved draft to continue.",
                    _view(latest, round_id, True),
                )
            return _view(new, round_id, True)
        new = conn.execute(
            update(portfolio_drafts)
            .where(
                portfolio_drafts.c.user_id == uid,
                portfolio_drafts.c.round_id == round_id,
                portfolio_drafts.c.version == expected_version,
            )
            .values(
                selections=sels,
                snapshot_fingerprint=snap.fingerprint,
                version=portfolio_drafts.c.version + 1,
            )
            .returning(portfolio_drafts)
        ).one()
        return _view(new, round_id, True)


def clear_draft(
    engine: Engine, principal: Principal, round_id: UUID, *, expected_version: int
) -> DraftView:
    """Empty the draft. The row and its version remain, so a version number is never
    reused by a later save (no lost update after a reset)."""
    return save_draft(engine, principal, round_id, [], expected_version=expected_version)
