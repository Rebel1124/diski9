"""Result evidence for competition settlement (Phase 6C.4, Stage B).

* :func:`import_results` — fetch the round's relevant fixtures by ID through the
  existing provider client and record each distinct provider state as an
  immutable observation (S-01, S-05). Optionally hands the same raw items to the
  existing football-store upsert (``store_fixtures``), whose behaviour is unchanged.
* :func:`record_synthetic_observation` — development rounds in synthetic result
  mode only; never in production; evidence scoped to that round (S-08).
* :func:`set_result_mode` — the explicit, frozen result mode of a development round.

Authorisation is checked here, on a server-built principal: routine evidence
collection needs ``jobs.run`` (an operator authenticated within 12 hours, T-12) or
the explicit scheduled-job actor :data:`SYSTEM`; nothing is granted by database
access alone. No automated scheduling is introduced (6C.6).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, select

from ...challenge.settle import FINAL_PLAYED, NO_GENUINE_RESULT
from ...ingestion.results_fetch import canonical_hash, evidence_fields
from ..auth.permissions import Capability, Principal, authorize
from ..db import BackendDatabaseSettings, db_now, transaction
from ..db.schema import (
    entries,
    round_snapshots,
    rounds,
    snapshot_fixtures,
    submission_selections,
)
from ..repositories import ops
from ..repositories import results as repo
from .common import NotFound, ServiceError
from .rounds import SYSTEM, System

#: Fetch only fixtures whose (latest known) kickoff is at most this far ahead.
POLL_LEAD = timedelta(minutes=30)
#: A fixture final with a score (or cancelled/awarded) for this long is not re-polled
#: unless a full re-check is requested.
STABLE_AFTER = timedelta(hours=6)
#: A provider response older than this when it reaches the database is refused, so a
#: stale replay can never be recorded as fresh evidence.
MAX_RECEIPT_AGE = timedelta(minutes=30)


class ResultsRefused(ServiceError):
    code = "results_refused"


@dataclass(frozen=True)
class ImportResult:
    round_id: UUID
    polled: tuple[int, ...]
    skipped: tuple[int, ...]
    received: int
    recorded: int
    unchanged: int
    requests: int


def environment() -> str:
    return BackendDatabaseSettings().environment


def actor_id(actor: Principal | System, capability: Capability) -> UUID | None:
    """The acting person's ID after authorisation, or ``None`` for the explicit
    scheduled-job actor. Callers decide whether :data:`SYSTEM` is acceptable."""
    if isinstance(actor, System):
        return None
    authorize(actor, capability)
    return actor.user_id


def round_row(conn, round_id: UUID, *, for_update: bool = False):
    q = select(rounds).where(rounds.c.id == round_id)
    if for_update:
        q = q.with_for_update(key_share=True)  # FOR NO KEY UPDATE (see repositories.rounds)
    row = conn.execute(q).one_or_none()
    if row is None:
        raise NotFound("No such round.")
    return row


def snapshot_id_of(conn, round_id: UUID) -> int:
    sid = conn.execute(
        select(round_snapshots.c.id).where(round_snapshots.c.round_id == round_id)
    ).scalar_one_or_none()
    if sid is None:
        raise NotFound("This round has no published snapshot.")
    return sid


def relevant_fixtures(conn, round_id: UUID) -> dict[int, set[tuple[str, str]]]:
    """Fixtures selected in the round's valid locked entries, with the outcomes
    picked on each (S-02: unselected fixtures are never relevant)."""
    rows = conn.execute(
        select(
            submission_selections.c.fixture_id,
            submission_selections.c.market,
            submission_selections.c.outcome,
        )
        .join(entries, entries.c.locked_submission_id == submission_selections.c.submission_id)
        .where(entries.c.round_id == round_id)
    )
    out: dict[int, set[tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(r.fixture_id, set()).add((r.market, r.outcome))
    return out


def poll_plan(
    fixtures: dict[int, datetime],
    latest: dict[int, object],
    now: datetime,
    *,
    full: bool = False,
) -> tuple[list[int], list[int]]:
    """Which relevant fixtures to fetch now: kickoff (latest provider schedule, else
    the frozen one) within :data:`POLL_LEAD`, and not already stable (final with a
    score, or cancelled/awarded, for :data:`STABLE_AFTER`) unless ``full``."""
    poll, skip = [], []
    for fid, frozen_ko in sorted(fixtures.items()):
        row = latest.get(fid)
        ko = (getattr(row, "kickoff_at", None) or frozen_ko) if row is not None else frozen_ko
        if ko - POLL_LEAD > now:
            skip.append(fid)
            continue
        if not full and row is not None:
            stable = (row.status_short in FINAL_PLAYED and row.ft_home is not None) or (
                row.status_short in NO_GENUINE_RESULT
            )
            if stable and now - row.observed_at >= STABLE_AFTER:
                skip.append(fid)
                continue
        poll.append(fid)
    return poll, skip


def import_results(
    engine: Engine,
    actor: Principal | System,
    round_id: UUID,
    fetch: Callable[[Sequence[int]], tuple[list[dict], int]],
    *,
    full: bool = False,
    football_store: Callable[[list[dict]], object] | None = None,
) -> ImportResult:
    """Fetch and record provider evidence for a real round's relevant fixtures.

    ``fetch(ids)`` returns ``(raw_items, requests)``; in production it is
    :func:`diski9.ingestion.results_fetch.fetch_fixtures_by_ids` bound to the
    existing client. ``football_store(items)``, when given, receives the same items
    (for example the unchanged ``store_fixtures`` on a football-store connection).
    Receipt time is the database clock read immediately after the response."""
    actor_id(actor, Capability.RUN_JOBS)
    with transaction(engine) as conn:
        r = round_row(conn, round_id)
        if r.result_mode != "real":
            raise ResultsRefused(
                "Provider results are imported only for rounds in real result mode."
            )
        if r.status not in ("locked", "settling", "final"):
            raise ResultsRefused("Results are collected only after the round has been locked.")
        relevant = relevant_fixtures(conn, round_id)
        frozen = dict(
            conn.execute(
                select(
                    snapshot_fixtures.c.fixture_id, snapshot_fixtures.c.kickoff_at_publish
                ).where(
                    snapshot_fixtures.c.snapshot_id == snapshot_id_of(conn, round_id),
                    snapshot_fixtures.c.fixture_id.in_(list(relevant) or [-1]),
                )
            ).all()
        )
        latest = {
            fid: repo.latest_evidence_row(conn, fid, mode="real", round_id=round_id)
            for fid in frozen
        }
        latest = {k: v for k, v in latest.items() if v is not None}
        poll, skip = poll_plan(frozen, latest, db_now(conn), full=full)
    if not poll:
        return ImportResult(round_id, (), tuple(skip), 0, 0, 0, 0)
    items, requests = fetch(poll)
    wanted = set(poll)
    with transaction(engine) as conn:
        observed_at = db_now(conn)  # receipt time: the database clock after the response
    with transaction(engine) as conn:
        now = db_now(conn)
        if now - observed_at > MAX_RECEIPT_AGE:
            raise ResultsRefused("The provider response is too old to record as evidence.")
        run = ops.start_job(conn, "results-import", str(round_id), {"fixtures": poll})
        recorded = unchanged = 0
        for item in items:
            fields = evidence_fields(item)
            if fields["fixture_id"] not in wanted:
                continue  # never record fixtures that were not asked for
            new = repo.record_evidence(
                conn,
                source="api-football",
                fixture_id=fields["fixture_id"],
                observed_at=observed_at,
                raw=item,
                raw_hash=canonical_hash(item),
                fields=fields,
                job_run_id=run,
            )
            recorded += new is not None
            unchanged += new is None
        ops.finish_job(conn, run, "succeeded", api_requests=requests)
    if football_store is not None and items:
        football_store([i for i in items if int(i["fixture"]["id"]) in wanted])
    return ImportResult(
        round_id, tuple(poll), tuple(skip), len(items), recorded, unchanged, requests
    )


# ------------------------------------------------------------------ development rounds
def _development_guard(r) -> None:
    if environment() == "production":
        raise ResultsRefused("Synthetic results and time overrides are disabled in production.")
    if not r.is_development:
        raise ResultsRefused("Synthetic results are only for development rounds.")


def set_result_mode(engine: Engine, actor: Principal, round_id: UUID, mode: str) -> str:
    """Freeze a development round's result mode (``real`` or ``synthetic``). Set once:
    the database refuses any later change. Real rounds are always ``real``. A
    person's choice: the scheduled-job actor is refused (S-07, Phase 6C.6)."""
    authorize(actor, Capability.RUN_JOBS)  # refuses SYSTEM (not a Principal)
    uid = actor.user_id
    if uid is None:
        raise ResultsRefused("Choosing a result mode needs an authenticated operator.")
    if mode not in ("real", "synthetic"):
        raise ResultsRefused("The result mode must be 'real' or 'synthetic'.")
    with transaction(engine) as conn:
        r = round_row(conn, round_id, for_update=True)
        if not r.is_development:
            raise ResultsRefused("Real rounds always settle on real results.")
        if mode == "synthetic":
            _development_guard(r)
        if r.result_mode == mode:
            return mode
        if r.result_mode is not None:
            raise ResultsRefused(f"This round's result mode is already {r.result_mode!r}.")
        conn.execute(rounds.update().where(rounds.c.id == round_id).values(result_mode=mode))
        ops.record_audit(
            conn,
            action="round.result_mode",
            target_type="round",
            target_id=str(round_id),
            actor=uid,
            actor_role="operator",
            reason=f"development result mode {mode}",
            after={"result_mode": mode},
        )
    return mode


def record_synthetic_observation(
    engine: Engine,
    actor: Principal,
    round_id: UUID,
    fixture_id: int,
    *,
    observed_at: datetime,
    status: str | None,
    kickoff_at: datetime | None = None,
    ft_home: int | None = None,
    ft_away: int | None = None,
    provider_first_half_at: datetime | None = None,
) -> int | None:
    """Record development evidence (development round, synthetic mode, not
    production). ``observed_at`` is the scenario's declared receipt time, so
    deterministic timelines (including cutoff boundaries) can be built."""
    uid = actor_id(actor, Capability.RUN_JOBS)
    if uid is None:
        raise ResultsRefused("Synthetic evidence needs an authenticated operator.")
    with transaction(engine) as conn:
        r = round_row(conn, round_id)
        _development_guard(r)
        if r.result_mode != "synthetic":
            raise ResultsRefused("This development round is not in synthetic result mode.")
        if fixture_id not in _snapshot_fixture_ids(conn, round_id):
            raise ResultsRefused("That fixture is not on this round's sheet.")
        fields = {
            "status_short": status,
            "kickoff_at": kickoff_at,
            "ft_home": ft_home,
            "ft_away": ft_away,
            "provider_first_half_at": provider_first_half_at,
        }
        raw = {"synthetic": True, "round_id": str(round_id), "fixture_id": fixture_id} | {
            k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in fields.items()
        }
        return repo.record_evidence(
            conn,
            source="synthetic",
            fixture_id=fixture_id,
            observed_at=observed_at,
            raw=raw,
            raw_hash=canonical_hash(raw),
            fields=fields,
            scope_round_id=round_id,
        )


def _snapshot_fixture_ids(conn, round_id: UUID) -> set[int]:
    return set(
        conn.execute(
            select(snapshot_fixtures.c.fixture_id).where(
                snapshot_fixtures.c.snapshot_id == snapshot_id_of(conn, round_id)
            )
        ).scalars()
    )


def observations_for(engine: Engine, round_id: UUID, fixture_ids: Iterable[int]) -> list:
    """Read-only helper for tests and operator inspection (no personal data)."""
    with transaction(engine) as conn:
        r = round_row(conn, round_id)
        return repo.observation_rows(conn, fixture_ids, mode=r.result_mode, round_id=round_id)


__all__ = [
    "ImportResult",
    "ResultsRefused",
    "SYSTEM",
    "import_results",
    "observations_for",
    "poll_plan",
    "record_synthetic_observation",
    "relevant_fixtures",
    "set_result_mode",
]
