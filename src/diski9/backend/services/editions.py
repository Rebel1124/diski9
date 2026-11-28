"""Immutable price editions and competitive freshness (Phase 8 CP3A-R, R2).

Architecture R (refinement §4, §14): a rolling-entry round's **edition 1** is the
manually published snapshot and the authoritative universe (fixtures, rules,
deadline, settlement cutoff). After publication, each successful competitive sweep
may write the **next edition**: the same builder, restricted to the universe,
repricing it. Editions never add fixtures, change rules, deadline or cutoff, or
modify earlier editions or submissions; the database enforces this (``app_0010``).

**Freshness** (refinement §14.3, §14.12), from stored evidence only:

* provider timestamp age at most 24 hours (the existing rule) and
* genuine observation age at most 6 hours (new for competitive use),

measured from each offer's **oldest** contributing observation and provider
timestamps, against the actual time (``clock_timestamp()`` at confirmation). The
edition's creation time, as-of time, a scheduled or attempted refresh time are
never used. A partial sweep therefore cannot make an unrefreshed price fresh: the
builder reads each quote's own last observation, and a fixture that was not
fetched keeps its older timestamps.

**Publication** (:func:`publish_edition`): the candidate is built outside any
transaction; publication takes the round row ``FOR NO KEY UPDATE`` (the lock
publication and the lock job use; confirmation holds ``FOR SHARE``, so an edition
can never commit part-way through a confirmation), re-validates the round and the
universe, allocates the next edition number and inserts the edition, its fixtures and
offers in one short transaction. A failure writes nothing.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, Engine, select, text

from diski9.challenge.config import ChallengeConfig, get_config
from diski9.challenge.roundsheet import RoundSnapshot
from diski9.challenge.structured import ChallengeOutcome, _match, assess_outcome

from ..auth.permissions import Capability, Principal, authorize
from ..db import transaction
from ..db.schema import round_schedules, round_snapshots, rounds, snapshot_fixtures
from ..repositories import ops
from ..repositories import rounds as rounds_repo
from . import rolling, snapshots
from .common import NotFound, ServiceError

OBSERVATION_MAX_AGE = timedelta(hours=6)
PROVIDER_MAX_AGE = timedelta(hours=24)
EDITION_JOB = "scheduler.prepare_edition"


class EditionRefused(ServiceError):
    """The candidate edition was not written (the reason says why; nothing changed)."""

    code = "edition_refused"


# ------------------------------------------------------------------ freshness
def offer_problem(o: ChallengeOutcome, now: datetime) -> str | None:
    """Why a competitive offer is not usable at ``now`` (None = usable). Missing
    evidence is refused, never assumed fresh."""
    if o.oldest_observation_at is None or o.provider_updated_at is None:
        return "missing_evidence"
    if now - o.oldest_observation_at > OBSERVATION_MAX_AGE:
        return "stale_observation"
    if now - o.provider_updated_at > PROVIDER_MAX_AGE:
        return "stale_provider_update"
    return None


@dataclass(frozen=True)
class Availability:
    """Whether a valid portfolio can still be built from the current edition at
    ``at`` (eligible, fresh, before the fixture cutoff). ``paused`` pauses competitive
    participation (research continues); it recovers when a fresh edition arrives."""

    at: datetime
    usable_outcomes: int
    usable_fixtures: int
    feasible: bool
    problems: dict[str, int]

    @property
    def status(self) -> str:
        return "open" if self.feasible else "paused"


def usable_outcomes(
    snap: RoundSnapshot, config: ChallengeConfig, now: datetime, buffer_minutes: int
) -> tuple[list[ChallengeOutcome], dict[str, int]]:
    kickoff = {f.fixture_id: f.kickoff for f in snap.fixtures}
    out, problems = [], {}
    for o in snap.outcomes:
        why = None
        if not assess_outcome(o, snap.snapshot_at, config).eligible:
            why = "ineligible"
        elif rolling.closed_fixtures(kickoff, [o.fixture_id], now, buffer_minutes):
            why = "fixture_closed"
        else:
            why = offer_problem(o, now)
        if why is None:
            out.append(o)
        else:
            problems[why] = problems.get(why, 0) + 1
    return out, problems


def availability(
    snap: RoundSnapshot, config: ChallengeConfig, now: datetime, buffer_minutes: int
) -> Availability:
    usable, problems = usable_outcomes(snap, config, now, buffer_minutes)
    bands: dict = {}
    for o in usable:
        b = config.classify(o.market_probability)
        if b is not None:
            bands.setdefault(o.fixture_id, set()).add(b)
    need = dict(zip(config.bucket_codes, config.sizes, strict=True))
    feasible = len(bands) >= sum(config.sizes) and bool(_match(need, bands))
    return Availability(now, len(usable), len(bands), feasible, problems)


def round_availability(engine: Engine, round_id: UUID) -> Availability:
    """Read-only competitive availability of a rolling-entry round now (database
    clock): the pause state the participant experience (R4) will show."""
    with transaction(engine) as conn:
        r = _round(conn, round_id)
        _, _, snap = snapshots.CACHE.current(conn, round_id)
        now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
        return availability(snap, get_config(r.config_version), now, r.buffer)


# ------------------------------------------------------------------ candidates
def restrict_to_universe(
    candidate: RoundSnapshot, universe: Iterable[int], as_of: datetime | None = None
) -> RoundSnapshot:
    """The candidate limited to the published universe and to fixtures that have not
    kicked off at ``as_of`` (the build time by default). Offers whose oldest
    observation is already older than 6 hours at the build time are left out (they
    could never be confirmed). Nothing is ever added."""
    as_of = as_of or candidate.snapshot_at
    ids = {int(f) for f in universe}
    fixtures = tuple(f for f in candidate.fixtures if f.fixture_id in ids and f.kickoff > as_of)
    kept = {f.fixture_id for f in fixtures}
    outcomes = tuple(
        o
        for o in candidate.outcomes
        if o.fixture_id in kept
        and o.oldest_observation_at is not None
        and as_of - o.oldest_observation_at <= OBSERVATION_MAX_AGE
    )
    with_offers = {o.fixture_id for o in outcomes}
    return dataclasses.replace(
        candidate,
        fixtures=tuple(f for f in fixtures if f.fixture_id in with_offers),
        outcomes=outcomes,
    )


def build_candidate(store_engine, engine: Engine, round_id: UUID, as_of: datetime):
    """A candidate edition from the football store at ``as_of`` (read-only; outside
    any competition transaction), with the round's own configuration, window and
    competitions, restricted to its published universe."""
    from diski9.app.data import LEAGUE_SHORT
    from diski9.challenge.roundsheet import build_live_snapshot, restrict_competitions

    with transaction(engine) as conn:
        r = _round(conn, round_id)
        universe = _universe(conn, round_id)
        comps = [int(c) for c in r.eligible_competitions]
    config = get_config(r.config_version)
    snap = build_live_snapshot(store_engine, as_of, r.window_start_at, r.window_end_at, r.code,
                               LEAGUE_SHORT, config, comps)  # fmt: skip
    return restrict_to_universe(restrict_competitions(snap, comps), universe, as_of)


# ------------------------------------------------------------------ publication
@dataclass(frozen=True)
class EditionResult:
    round_id: UUID
    snapshot_id: int
    edition: int
    fingerprint: str
    fixtures: int
    offers: int


def _round(conn: Connection, round_id: UUID):
    r = conn.execute(
        select(
            rounds.c.id,
            rounds.c.code,
            rounds.c.status,
            rounds.c.rules_version,
            rounds.c.config_version,
            rounds.c.deadline_at,
            rounds.c.window_start_at,
            rounds.c.window_end_at,
            rounds.c.is_development,
            round_schedules.c.deadline_buffer_minutes.label("buffer"),
            round_schedules.c.eligible_competitions,
        )
        .select_from(rounds.join(round_schedules, round_schedules.c.id == rounds.c.schedule_id))
        .where(rounds.c.id == round_id)
    ).one_or_none()
    if r is None:
        raise NotFound("No such round.")
    return r


def _universe(conn: Connection, round_id: UUID) -> set[int]:
    return set(
        conn.execute(
            select(snapshot_fixtures.c.fixture_id).where(
                snapshot_fixtures.c.snapshot_id == snapshots.universe_id(conn, round_id)
            )
        ).scalars()
    )


def publish_edition(
    engine: Engine,
    actor,
    round_id: UUID,
    candidate: RoundSnapshot,
    *,
    source: str = "football-db",
    max_age: timedelta | None = None,
    job_run_id: int | None = None,
) -> EditionResult:
    """Write ``candidate`` as the round's next edition, atomically, or refuse with
    nothing written. ``actor``: the scheduler (:data:`~.rounds.SYSTEM`) or a person
    with ``round.publish``."""
    from .rounds import System, max_snapshot_age

    actor_id = None
    if not isinstance(actor, System):
        authorize(actor, Capability.PUBLISH_ROUND)
        actor_id = actor.user_id if isinstance(actor, Principal) else None
    if source not in snapshots.SOURCES:
        raise EditionRefused("Unknown snapshot source.")
    with transaction(engine) as conn:
        rounds_repo.lock_round_for_change(conn, round_id)  # conflicts with FOR SHARE
        r = _round(conn, round_id)
        now = conn.execute(text("SELECT clock_timestamp()")).scalar_one()
        problem = None
        if not rolling.is_rolling(r.rules_version):
            problem = "Only rolling-entry rounds take price editions."
        elif r.status != "open" or now >= r.deadline_at:
            problem = "The round is not open for new editions."
        elif (source == "development") != bool(r.is_development):
            problem = "Development data only for development rounds; real data only for real ones."
        elif candidate.round_id != r.code or candidate.config_version != r.config_version:
            problem = "The candidate was built for another round or configuration."
        elif candidate.snapshot_at > now or now - candidate.snapshot_at > (
            max_age or max_snapshot_age()
        ):
            problem = "The candidate is too old (or in the future); build a fresh one."
        elif not candidate.fixtures:
            problem = "The candidate has no priced fixtures; the current edition stays."
        else:
            outside = {f.fixture_id for f in candidate.fixtures} - _universe(conn, round_id)
            if outside:
                problem = (
                    "The candidate has fixtures outside the published universe: "
                    f"{sorted(outside)[:10]}"
                )
        if problem is not None:
            raise EditionRefused(problem)
        last = conn.execute(
            select(round_snapshots.c.edition)
            .where(round_snapshots.c.round_id == round_id)
            .order_by(round_snapshots.c.edition.desc())
            .limit(1)
        ).scalar_one()
        config = get_config(r.config_version)
        report = candidate.opening_report(config)
        sid = snapshots.store_snapshot(
            conn,
            round_id,
            candidate,
            config,
            source=source,
            report=report,
            model_version=conn.execute(
                select(rounds.c.model_version).where(rounds.c.id == round_id)
            ).scalar_one(),
            job_run_id=job_run_id,
            edition=last + 1,
        )
        ops.record_audit(
            conn,
            action="round.edition",
            target_type="round",
            target_id=str(round_id),
            actor=actor_id,
            actor_role="system" if actor_id is None else "operator",
            after={"edition": last + 1, "snapshot_id": sid, "fingerprint": candidate.fingerprint,
                   "fixtures": len(candidate.fixtures), "offers": len(candidate.outcomes)},
        )  # fmt: skip
        return EditionResult(round_id, sid, last + 1, candidate.fingerprint,
                             len(candidate.fixtures), len(candidate.outcomes))  # fmt: skip


def editions(engine: Engine, round_id: UUID) -> list[dict]:
    """Every edition of a round (read-only, for operators and tests)."""
    with transaction(engine) as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(
                select(round_snapshots.c.id, round_snapshots.c.edition, round_snapshots.c.as_of,
                       round_snapshots.c.fingerprint, round_snapshots.c.created_at)
                .where(round_snapshots.c.round_id == round_id)
                .order_by(round_snapshots.c.edition)
            )
        ]  # fmt: skip


__all__ = [
    "OBSERVATION_MAX_AGE",
    "PROVIDER_MAX_AGE",
    "Availability",
    "EditionRefused",
    "EditionResult",
    "availability",
    "build_candidate",
    "editions",
    "offer_problem",
    "publish_edition",
    "restrict_to_universe",
    "round_availability",
    "usable_outcomes",
]
