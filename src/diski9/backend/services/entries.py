"""Confirmed entries: confirm, replace, withdraw and re-enter (Phase 6C.3, Stage E;
T-09, R-04).

* **Confirmation** turns the participant's *saved draft* (at the version the
  page shows) into an immutable submission. Everything is re-derived on the
  server from the round's frozen snapshot: the nine outcomes, their buckets
  (exactly 4/3/2), odds and market and model probabilities, the fixed credits,
  and the engine's evaluation stored with the submission. Nothing numerical
  comes from the client.
* **Replacement** is an explicit confirmation over an active entry: a new
  submission version becomes current in the same transaction; earlier versions
  stay (insert-only) and an ``entry_events`` row records the change. If anything
  fails, the previous version stays current.
* **Withdrawal** clears the current pointer and records the event; history is
  never deleted. A withdrawn participant can confirm again before the deadline.
* **Concurrency:** the round row ``FOR SHARE`` (the lock job's ``FOR UPDATE``
  waits for it, and vice versa), the entry row ``FOR UPDATE``, an optimistic
  entry version, a draft version, and a per-user idempotency key. The deadline is
  checked with ``clock_timestamp()`` *after* the locks are held, so waiting for
  another transaction can never extend the window; the insert trigger checks it
  again.
* Your View is never read: private analysis is not an input to entries.

**Rolling entry** (rules ``rolling/v1``, Phase 8 CP3A-R R1; see
:mod:`~diski9.backend.services.rolling`): the first confirmation is the participant's
one irrevocable final submission. Replacement, withdrawal and resubmission are
refused (:class:`SubmissionFinal`); a retried request with the same key still
returns the stored entry. Each selected fixture must kick off more than the
schedule's buffer (15 minutes) after ``clock_timestamp()`` read after the locks
(:class:`FixtureClosed`). Earlier rules versions are unchanged.

**Price editions (R2).** A rolling confirmation uses the round's *current* edition,
resolved after the round lock (an edition writer needs a conflicting lock, so the
edition cannot change before the commit). Every selected price must be fresh at the
actual time (:func:`~.editions.offer_problem`, :class:`PriceExpired`) and the
participant's reviewed items must match (:mod:`~.review`, :class:`ReviewChanged`).
The request identity is the reviewed selections and review fingerprint, so a retry
returns the stored submission even after a new edition or the close. The database
sets ``submitted_at`` to ``clock_timestamp()`` at insert and checks the close, the
current edition, each fixture's cutoff and every copied value (``app_0010``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import NoResultFound

from diski9.challenge.config import ProbabilitySource, get_config
from diski9.challenge.structured import (
    ENGINE_VERSION,
    ChallengeInputError,
    PortfolioValidationError,
    evaluate_portfolio,
    validate_portfolio,
)

from ..auth.permissions import Capability, Principal, authorize
from ..db import read_only, transaction
from ..db.schema import (
    entries,
    entry_events,
    portfolio_drafts,
    round_schedules,
    rounds,
    submission_selections,
    submissions,
)
from ..repositories import portfolios as repo
from ..repositories import rounds as rounds_repo
from . import drafts as drafts_svc
from . import editions, rolling, snapshots
from . import review as review_svc
from .common import (
    NotFound,
    RoundClosed,
    ServiceError,
    ValidationFailed,
    VersionConflict,
    map_db_errors,
    require_active,
)

KEY_MIN, KEY_MAX = 16, 128


class AlreadyEntered(ServiceError):
    code = "already_entered"


class IdempotencyMismatch(ServiceError):
    code = "idempotency_mismatch"


class SubmissionFinal(ServiceError):
    """Rolling entry: the participant's final submission already exists, so it cannot
    be replaced, withdrawn or submitted again."""

    code = "submission_final"


class PriceExpired(ValidationFailed):
    """Rolling entry (R2): a selected price's evidence is too old at the actual
    confirmation time (observation over 6 h or provider update over 24 h) or missing.
    ``issues`` names the positions; nothing was written and the draft is unchanged."""

    code = "price_expired"


class ReviewChanged(ServiceError):
    """Rolling entry (R2): a reviewed value of the participant's own selections
    changed in the current edition. ``details`` lists the changed positions and the
    current review; the participant must review again. Nothing was written."""

    code = "review_changed"


class FixtureClosed(ValidationFailed):
    """Rolling entry: a selected fixture is within its pre-kickoff cutoff (or has
    started). ``details["fixtures"]`` lists them; nothing was written."""

    code = "fixture_closed"


@dataclass(frozen=True)
class SubmissionView:
    id: UUID
    version: int
    submitted_at: datetime
    selections: tuple[dict, ...]  # position order; values copied from the snapshot
    p_recover_market: float
    p_recover_model: float | None
    expected_gross_market: float
    expected_gross_model: float | None
    max_gross: Decimal

    @property
    def keys(self) -> list[str]:
        return [f"{s['fixture_id']}|{s['market']}|{s['outcome']}" for s in self.selections]


@dataclass(frozen=True)
class EntryEvent:
    kind: str
    at: datetime
    submission_version: int | None


@dataclass(frozen=True)
class EntryView:
    round_id: UUID
    entry_id: UUID | None
    state: str  # none | confirmed | withdrawn
    version: int
    current: SubmissionView | None
    locked: bool
    history: tuple[EntryEvent, ...]

    @property
    def active(self) -> bool:
        return self.state == "confirmed" and self.current is not None


# ------------------------------------------------------------------ reads
def _submission(conn: Connection, sub_id: UUID | None) -> SubmissionView | None:
    if sub_id is None:
        return None
    s = conn.execute(select(submissions).where(submissions.c.id == sub_id)).one()
    sels = conn.execute(
        select(submission_selections)
        .where(submission_selections.c.submission_id == sub_id)
        .order_by(submission_selections.c.position)
    ).all()
    return SubmissionView(
        s.id,
        s.version,
        s.submitted_at,
        tuple(
            {
                "fixture_id": r.fixture_id,
                "market": r.market,
                "outcome": r.outcome,
                "bucket": r.bucket,
                "consensus_odds": str(r.consensus_odds),
                "market_prob": r.market_prob,
                "model_prob": r.model_prob,
            }
            for r in sels
        ),
        s.p_recover_market,
        s.p_recover_model,
        s.expected_gross_market,
        s.expected_gross_model,
        s.max_gross,
    )


def _entry_view(conn: Connection, round_id: UUID, user_id: UUID) -> EntryView:
    e = conn.execute(
        select(entries).where(entries.c.round_id == round_id, entries.c.user_id == user_id)
    ).one_or_none()
    if e is None:
        return EntryView(round_id, None, "none", 0, None, False, ())
    events = conn.execute(
        select(entry_events.c.kind, entry_events.c.at, submissions.c.version)
        .select_from(entry_events)
        .outerjoin(submissions, submissions.c.id == entry_events.c.submission_id)
        .where(entry_events.c.entry_id == e.id)
        .order_by(entry_events.c.at, entry_events.c.id)
    ).all()
    state = e.state if e.current_submission_id is not None or e.state == "withdrawn" else "none"
    return EntryView(
        round_id,
        e.id,
        state,
        e.version,
        _submission(conn, e.current_submission_id),
        e.locked_at is not None,
        tuple(EntryEvent(k, at, v) for k, at, v in events),
    )


def get_entry(engine: Engine, principal: Principal, round_id: UUID) -> EntryView:
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    with read_only(engine) as conn:
        return _entry_view(conn, round_id, principal.user_id)


# ------------------------------------------------------------------ helpers
def _lock_round(conn: Connection, round_id: UUID):
    try:
        return rounds_repo.lock_round_for_submission(conn, round_id)
    except NoResultFound as exc:
        raise NotFound("No such round.") from exc


def _check_open(conn: Connection, r) -> None:
    """The deadline by ``clock_timestamp()``, checked while the locks are held (so a
    wait for the lock job or another device never extends the window)."""
    now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
    if r.status != "open" or r.deadline_at is None or now >= r.deadline_at:
        raise RoundClosed("The submission deadline has passed; entries can no longer change.")


FINAL_MESSAGE = (
    "Your portfolio has already been submitted. Entries in this round are final and "
    "cannot be changed, withdrawn or submitted again."
)


def _rolling(r) -> bool:
    return rolling.is_rolling(getattr(r, "rules_version", None))


def _check_fixture_cutoffs(conn: Connection, r, snap, fixture_ids) -> None:
    """Rolling entry: every selected fixture must kick off more than the schedule's
    buffer after ``clock_timestamp()``, read while the locks are held."""
    buffer = conn.execute(
        select(round_schedules.c.deadline_buffer_minutes).where(
            round_schedules.c.id == r.schedule_id
        )
    ).scalar_one()
    now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
    kickoffs = {int(f.fixture_id): f.kickoff for f in snap.fixtures}
    closed = rolling.closed_fixtures(kickoffs, fixture_ids, now, buffer)
    if closed:
        raise FixtureClosed(
            f"Some of your matches start within {buffer} minutes or have already started; "
            "replace them before submitting.",
            [{"reason": "fixture_closed", "fixture_id": f} for f in closed],
        )


def _check_rolling_review(conn, snap, config, model_version, outcomes, reviewed, round_id, uid):
    """Rolling entry (R2): every selected price must be fresh at the actual time, and
    the participant's reviewed items must equal the current edition's (display
    precision; accepted values are still copied at full precision)."""
    now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
    stale = [
        {"reason": why, "position": pos, "fixture_id": o.fixture_id}
        for pos, o in enumerate(outcomes)
        if (why := editions.offer_problem(o, now)) is not None
    ]
    if stale:
        raise PriceExpired(
            "Some prices in your portfolio are out of date; review your portfolio again "
            "once prices refresh, or choose other predictions.",
            stale,
        )
    items = review_svc.items_for(outcomes, config, model_version or "", snap)
    current = [review_svc.digest(i) for i in items]
    reviewed = list(reviewed or [])
    changed = review_svc.changed_positions(reviewed, current)
    if changed:
        raise ReviewChanged(
            "Prices for some of your predictions have changed since you reviewed them. "
            "Please review your portfolio again.",
            details={"positions": changed, "current": current,
                     "fingerprint": review_svc.fingerprint(current)},
        )  # fmt: skip


def _lock_or_create_entry(conn: Connection, round_id: UUID, user_id: UUID):
    conn.execute(
        pg_insert(entries)
        .values(round_id=round_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["round_id", "user_id"])
    )
    return repo.lock_entry(conn, round_id, user_id)


def _key(k) -> str:
    if not isinstance(k, str) or not KEY_MIN <= len(k) <= KEY_MAX:
        raise ValidationFailed("Missing or malformed request key.", [{"reason": "idempotency"}])
    return k


def _inputs_hash(round_id: UUID, fingerprint: str, sels: list[dict]) -> str:
    blob = json.dumps(
        {"round": str(round_id), "snapshot": fingerprint, "selections": sels},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _rolling_inputs_hash(round_id: UUID, sels: list[dict], reviewed: Sequence[str]) -> str:
    """Rolling entry: the request identity is the reviewed selections and the review
    fingerprint, never the edition, so a retried request still matches after a later
    edition, the close or the expiry of its prices."""
    blob = json.dumps(
        {"round": str(round_id), "selections": sels,
         "review": review_svc.fingerprint(list(reviewed or []))},
        separators=(",", ":"), sort_keys=True,
    )  # fmt: skip
    return hashlib.sha256(blob.encode()).hexdigest()


def _states(ev) -> list[dict]:
    return [{"wins": list(s.wins), "p": s.probability, "gross": str(s.gross)} for s in ev.states]


# ------------------------------------------------------------------ confirm
def confirm_entry(
    engine: Engine,
    principal: Principal,
    round_id: UUID,
    *,
    draft_version: int,
    expected_entry_version: int,
    idempotency_key: str,
    replace: bool = False,
    reviewed: Sequence[str] | None = None,
) -> EntryView:
    """Confirm the saved draft (first entry, re-entry after withdrawal, or - with
    ``replace=True`` - replacement of the active entry). Rolling entry (R2):
    ``reviewed`` is the nine item digests of :func:`~.review.review_portfolio` the
    participant accepted; the confirmation uses the current edition, read after the
    locks, and refuses expired prices or changed reviewed values."""
    authorize(principal, Capability.SUBMIT_ENTRY)
    key = _key(idempotency_key)
    uid = principal.user_id
    with map_db_errors(), transaction(engine) as conn:
        require_active(conn, uid)
        r = _lock_round(conn, round_id)
        e = _lock_or_create_entry(conn, round_id, uid)
        # the current edition, resolved after the round lock: an edition writer needs a
        # conflicting lock, so this edition cannot change before the commit (R2)
        snap_id, _, snap = snapshots.CACHE.current(conn, round_id)
        is_rolling = _rolling(r)
        draft = conn.execute(
            select(portfolio_drafts).where(
                portfolio_drafts.c.user_id == uid, portfolio_drafts.c.round_id == round_id
            )
        ).one_or_none()
        sels = list(draft.selections) if draft is not None else []
        digest = (
            _rolling_inputs_hash(round_id, sels, reviewed or [])
            if is_rolling
            else _inputs_hash(round_id, snap.fingerprint, sels)
        )
        prior = repo.find_submission_by_key(conn, uid, key)
        if prior is not None:  # a retried or duplicated request
            if prior.round_id == round_id and prior.inputs_hash == digest:
                return _entry_view(conn, round_id, uid)
            raise IdempotencyMismatch(
                "This request was already used for a different portfolio. Please try again."
            )
        _check_open(conn, r)
        if is_rolling and (replace or e.current_submission_id is not None or e.version > 0):
            # one final submission: any earlier submission (or a replace request) ends it
            raise SubmissionFinal(FINAL_MESSAGE, details=_entry_view(conn, round_id, uid))
        if e.version != expected_entry_version:
            raise VersionConflict(
                "Your entry was changed in another tab or on another device. "
                "Reload to see the latest entry.",
                _entry_view(conn, round_id, uid),
            )
        if draft is None or draft.version != draft_version:
            raise VersionConflict(
                "Your saved portfolio changed in another tab or on another device. "
                "Review it again before confirming.",
                _entry_view(conn, round_id, uid),
            )
        active = e.state == "confirmed" and e.current_submission_id is not None
        if active and not replace:
            raise AlreadyEntered("You already have a confirmed entry. Choose Replace to change it.")
        if not active and replace:
            raise ValidationFailed("There is no active entry to replace.", [{"reason": "replace"}])
        cfg_version = conn.execute(
            select(rounds.c.config_version, rounds.c.model_version, rounds.c.rules_version).where(
                rounds.c.id == round_id
            )
        ).one()
        config = get_config(cfg_version.config_version)
        parsed = drafts_svc.parse_selections(sels)
        outcomes = drafts_svc.validate_selections(snap, parsed, config)
        if is_rolling:
            _check_fixture_cutoffs(conn, r, snap, [o.fixture_id for o in outcomes])
            _check_rolling_review(conn, snap, config, cfg_version.model_version, outcomes,
                                  reviewed, round_id, uid)  # fmt: skip
        try:
            portfolio = validate_portfolio(outcomes, snap.snapshot_at, config, pool=snap.outcomes)
        except PortfolioValidationError as exc:
            raise ValidationFailed(
                "A confirmed entry needs exactly 4 Foundation, 3 Balanced and 2 Challenger "
                "predictions on nine different matches.",
                [{"reason": "incomplete", "detail": str(i.code)} for i in exc.issues],
            ) from None
        market = evaluate_portfolio(portfolio, ProbabilitySource.MARKET)
        try:
            model = evaluate_portfolio(portfolio, ProbabilitySource.MODEL)
        except ChallengeInputError:
            model = None
        next_version = (
            conn.execute(
                select(func.coalesce(func.max(submissions.c.version), 0)).where(
                    submissions.c.entry_id == e.id
                )
            ).scalar_one()
            + 1
        )
        rows = []
        for pos, o in enumerate(portfolio.selections):
            rows.append(
                {
                    "position": pos,
                    "fixture_id": o.fixture_id,
                    "market": str(o.market),
                    "outcome": str(o.outcome),
                    "bucket": config.classify(o.market_probability),
                    "model_prob": o.model_probability,
                    "consensus_odds": o.reference_odds,
                    "market_prob": o.market_probability,
                    "bookmaker_groups": o.bookmaker_groups,
                }
            )
        sub_id = repo.insert_submission(
            conn,
            {
                "entry_id": e.id,
                "round_id": round_id,
                "user_id": uid,
                "snapshot_id": snap_id,
                "version": next_version,
                "idempotency_key": key,
                "inputs_hash": digest,
                "p_recover_market": market.p_recover,
                "p_recover_model": model.p_recover if model else None,
                "expected_gross_market": market.expected_gross,
                "expected_gross_model": model.expected_gross if model else None,
                "max_gross": market.max_gross,
                "states": {
                    "market": _states(market),
                    "model": _states(model) if model else None,
                },
                "config_version": config.version,
                "calc_version": ENGINE_VERSION,
                "model_version": cfg_version.model_version,
                "rules_version": cfg_version.rules_version,
            },
            rows,
        )
        previous = e.current_submission_id
        if not repo.set_current_submission(conn, e.id, sub_id, e.version, "confirmed"):
            raise VersionConflict("Your entry changed while saving.", None)  # pragma: no cover
        repo.add_event(
            conn,
            e.id,
            "replaced" if active else "confirmed",
            submission_id=sub_id,
            previous_submission_id=previous,
            actor=uid,
        )
        return _entry_view(conn, round_id, uid)


def withdraw_entry(
    engine: Engine, principal: Principal, round_id: UUID, *, expected_entry_version: int
) -> EntryView:
    """Withdraw the active entry before the deadline (explicit; history kept)."""
    authorize(principal, Capability.SUBMIT_ENTRY)
    uid = principal.user_id
    with map_db_errors(), transaction(engine) as conn:
        require_active(conn, uid)
        r = _lock_round(conn, round_id)
        e = repo.lock_entry(conn, round_id, uid)
        _check_open(conn, r)  # after every lock is held
        if _rolling(r):
            raise SubmissionFinal(FINAL_MESSAGE, details=_entry_view(conn, round_id, uid))
        if e is None or e.state != "confirmed" or e.current_submission_id is None:
            raise ValidationFailed("There is no active entry to withdraw.", [{"reason": "none"}])
        if e.version != expected_entry_version:
            raise VersionConflict(
                "Your entry was changed in another tab or on another device. "
                "Reload to see the latest entry.",
                _entry_view(conn, round_id, uid),
            )
        if not repo.set_current_submission(conn, e.id, None, e.version, "withdrawn"):
            raise VersionConflict("Your entry changed while saving.", None)  # pragma: no cover
        repo.add_event(
            conn, e.id, "withdrawn", previous_submission_id=e.current_submission_id, actor=uid
        )
        # A withdrawal starts the participant afresh (as in the browser-only flow): the
        # saved predictions are cleared in the same transaction, so the withdrawn
        # portfolio is never shown as selected or resubmitted. The draft row and its
        # version remain (a version number is never reused); the withdrawn submission
        # itself stays in the entry history.
        conn.execute(
            update(portfolio_drafts)
            .where(
                portfolio_drafts.c.user_id == uid,
                portfolio_drafts.c.round_id == round_id,
                portfolio_drafts.c.selections != text("'[]'::jsonb"),
            )
            .values(
                selections=[],
                version=portfolio_drafts.c.version + 1,
                writer_tab=None,
                writer_seq=None,
            )
        )
        return _entry_view(conn, round_id, uid)


# ------------------------------------------------------------------ most recent locked entry
def latest_locked_entry(
    engine: Engine,
    principal: Principal,
    *,
    exclude_round_id: UUID | None = None,
    include_development: bool = False,
):
    """The participant's most recent **confirmed** entry in a round whose
    submission deadline has passed (database clock): ``(RoundView, EntryView)`` or
    None. Read-only and owner-scoped (the signed-in principal's own row only).

    * The values come from the stored immutable submission the entry points to,
      never from a working draft.
    * Withdrawn entries (no current submission) are not returned.
    * ``exclude_round_id`` leaves out the round the page already shows, so the
      same entry is never displayed twice.
    * A round past its deadline whose lock job has not run yet (status still
      ``open``) is included; ``RoundView.status`` tells the caller which it is.
    """
    authorize(principal, Capability.PERSIST_OWN_ANALYSIS)
    from ..db import db_now
    from . import rounds as rounds_svc

    with read_only(engine) as conn:
        now = db_now(conn)
        q = (
            select(rounds.c.id)
            .select_from(entries.join(rounds, rounds.c.id == entries.c.round_id))
            .where(
                entries.c.user_id == principal.user_id,
                entries.c.state == "confirmed",
                entries.c.current_submission_id.is_not(None),
                rounds.c.deadline_at <= now,
                rounds.c.status.in_(("open", "locked", "settling", "final")),
            )
            .order_by(rounds.c.deadline_at.desc())
            .limit(1)
        )
        if exclude_round_id is not None:
            q = q.where(rounds.c.id != exclude_round_id)
        if not include_development:
            q = q.where(rounds.c.is_development.is_(False))
        rid = conn.execute(q).scalar_one_or_none()
        if rid is None:
            return None
        return rounds_svc._view(conn, rid), _entry_view(conn, rid, principal.user_id)
