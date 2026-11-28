"""Frozen round snapshots in PostgreSQL (Phase 6C.3, Stage B).

A published round's :class:`~diski9.challenge.roundsheet.RoundSnapshot` is written
once, at publication, into ``round_snapshots``, ``snapshot_fixtures`` and
``snapshot_offers`` and is immutable afterwards (insert-only tables, plus a
trigger that refuses new rows once the round is no longer ``draft``).

:func:`load_snapshot` rebuilds the same ``RoundSnapshot`` the engine works with
and **recomputes its fingerprint**; a stored snapshot whose content no longer
matches its recorded fingerprint is refused. Values are stored at full
precision: probabilities as ``double precision`` (``repr`` round-trips exactly)
and consensus odds as ``numeric(8,2)`` (the consensus layer already quantises
them to 0.01).

Published snapshots are shared, immutable data, so they may be cached per
process (:class:`SnapshotCache`). Nothing private is ever cached.

**Editions (Phase 8 R2, rolling entry).** Edition 1 is the manually published
snapshot and the authoritative universe; later editions (written by
:mod:`~diski9.backend.services.editions`) reprice it. Consumers choose explicitly:
:func:`universe_id` / ``CACHE.get`` (edition 1), :func:`current_edition` /
``CACHE.current`` (competitive prices) or ``CACHE.by_id`` (a submission's own
edition). A historical round has only edition 1, so every choice gives the same
snapshot.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, select

from diski9.challenge.config import ChallengeConfig, get_config
from diski9.challenge.roundsheet import RoundFixture, RoundSnapshot, SnapshotKind
from diski9.challenge.structured import RoundOpeningReport, assess_outcome, make_outcome

from ..db.schema import round_snapshots, rounds, snapshot_fixtures, snapshot_offers
from ..repositories import rounds as rounds_repo
from .common import NotFound, SnapshotIntegrityError

SOURCES = ("football-db", "development")


def _key(o) -> list:
    return [o.fixture_id, str(o.market), str(o.outcome)]


def report_dict(report: RoundOpeningReport) -> dict:
    return {
        "config_version": report.config_version,
        "eligible_outcomes": report.eligible_outcomes,
        "eligible_outcomes_by_bucket": dict(report.eligible_outcomes_by_bucket),
        "eligible_fixtures": report.eligible_fixtures,
        "eligible_leagues": report.eligible_leagues,
        "fixtures_missing_league": report.fixtures_missing_league,
        "portfolio_feasible": report.portfolio_feasible,
        "checks": dict(report.checks),
        "opens": report.opens,
    }


def snapshot_rows(
    snap: RoundSnapshot, config: ChallengeConfig
) -> tuple[list[dict], list[dict], dict]:
    """(fixture rows, offer rows, ordering and labels) for a snapshot. Eligibility
    and buckets come from the engine at the snapshot time (never from a client)."""
    for f in snap.fixtures:
        if isinstance(f.fixture_id, bool) or not isinstance(f.fixture_id, int):
            raise SnapshotIntegrityError("Published snapshots need integer fixture IDs.")
    fixtures = [
        {
            "fixture_id": f.fixture_id,
            "competition_id": f.league_id,
            "home_team": f.home,
            "away_team": f.away,
            "kickoff_at_publish": f.kickoff,
            "estimated_goals_home": f.estimated_goals[0] if f.estimated_goals else None,
            "estimated_goals_away": f.estimated_goals[1] if f.estimated_goals else None,
        }
        for f in snap.fixtures
    ]
    known = {f.fixture_id for f in snap.fixtures}
    offers = []
    for o in snap.outcomes:
        if o.fixture_id not in known:
            raise SnapshotIntegrityError("An outcome refers to a fixture outside the snapshot.")
        a = assess_outcome(o, snap.snapshot_at, config)
        offers.append(
            {
                "fixture_id": o.fixture_id,
                "market": str(o.market),
                "outcome": str(o.outcome),
                "model_prob": o.model_probability,
                "consensus_odds": o.reference_odds,
                "market_prob": o.market_probability,
                "bookmaker_groups": o.bookmaker_groups,
                "latest_observation_at": o.latest_observation_at,
                "oldest_observation_at": o.oldest_observation_at,
                "provider_updated_at": o.provider_updated_at,
                "eligible": a.eligible,
                "bucket": a.bucket if a.eligible else None,
                "ineligible_reason": None
                if a.eligible
                else ",".join(sorted({str(i.code) for i in a.issues})) or "unclassified",
            }
        )
    meta = {
        "fixture_order": [f.fixture_id for f in snap.fixtures],
        "outcome_order": [_key(o) for o in snap.outcomes],
        "league_names": {str(f.league_id): f.league for f in snap.fixtures},
        "source_note": snap.source_note,
        "config_version": snap.config_version,
    }
    return fixtures, offers, meta


def store_snapshot(
    conn: Connection,
    round_id: UUID,
    snap: RoundSnapshot,
    config: ChallengeConfig,
    *,
    source: str,
    report: RoundOpeningReport,
    model_version: str,
    job_run_id: int | None = None,
    edition: int = 1,
) -> int:
    if source not in SOURCES:
        raise ValueError(f"unknown snapshot source {source!r}")
    fixtures, offers, meta = snapshot_rows(snap, config)
    feasibility = {
        "source": source,
        "report": report_dict(report),
        "diagnostics": snap.diagnostics or {},
        **meta,
    }
    return rounds_repo.insert_snapshot(
        conn,
        round_id,
        as_of=snap.snapshot_at,
        fingerprint=snap.fingerprint,
        model_version=model_version,
        feasibility=feasibility,
        fixtures=fixtures,
        offers=offers,
        job_run_id=job_run_id,
        edition=edition,
    )


# ------------------------------------------------------------------ editions (Phase 8 R2)
def universe_id(conn: Connection, round_id: UUID) -> int:
    """The id of a round's edition 1: the manually published snapshot, the authoritative
    fixture universe (results, settlement and correction membership, history)."""
    # ids are allocated in edition order (editions are written one at a time under the
    # round lock), so edition 1 is the round's first snapshot on every schema version
    sid = conn.execute(
        select(func.min(round_snapshots.c.id)).where(round_snapshots.c.round_id == round_id)
    ).scalar_one_or_none()
    if sid is None:
        raise NotFound("This round has no published snapshot.")
    return sid


def current_edition(conn: Connection, round_id: UUID) -> tuple[int, int]:
    """``(snapshot_id, edition)`` of a round's latest edition: the competitive prices
    (builder, draft validation, review, confirmation). Never cached: a new edition can
    commit at any time; under READ COMMITTED this reads the latest committed one."""
    row = conn.execute(
        select(func.max(round_snapshots.c.id), func.count()).where(
            round_snapshots.c.round_id == round_id
        )
    ).one()
    if row[0] is None:
        raise NotFound("This round has no published snapshot.")
    return row[0], row[1]  # editions are consecutive from 1, so the count is the latest


def load_snapshot(
    conn: Connection, round_id: UUID, *, snapshot_id: int | None = None
) -> RoundSnapshot:
    """A round's published snapshot, rebuilt and fingerprint-checked: edition 1 by
    default, or the edition with ``snapshot_id`` (which must belong to the round)."""
    q = (
        select(
            round_snapshots,
            rounds.c.code,
            rounds.c.config_version,
            rounds.c.window_start_at,
            rounds.c.window_end_at,
        )
        .join(rounds, rounds.c.id == round_snapshots.c.round_id)
        .where(round_snapshots.c.round_id == round_id)
    )
    q = q.where(
        round_snapshots.c.edition == 1
        if snapshot_id is None
        else round_snapshots.c.id == snapshot_id
    )
    head = conn.execute(q).one_or_none()
    if head is None:
        raise NotFound("This round has no published snapshot.")
    meta: Mapping[str, Any] = head.feasibility
    fx_rows = {
        r.fixture_id: r
        for r in conn.execute(
            select(snapshot_fixtures).where(snapshot_fixtures.c.snapshot_id == head.id)
        )
    }
    of_rows = {
        (r.fixture_id, r.market, r.outcome): r
        for r in conn.execute(
            select(snapshot_offers).where(snapshot_offers.c.snapshot_id == head.id)
        )
    }
    names = meta.get("league_names") or {}
    order = meta.get("fixture_order") or sorted(fx_rows)
    if set(order) != set(fx_rows):
        raise SnapshotIntegrityError("Stored snapshot fixtures do not match their record.")
    fixtures = []
    for fid in order:
        r = fx_rows[fid]
        eg = (
            (r.estimated_goals_home, r.estimated_goals_away)
            if r.estimated_goals_home is not None and r.estimated_goals_away is not None
            else None
        )
        fixtures.append(
            RoundFixture(
                r.fixture_id,
                r.competition_id,
                names.get(str(r.competition_id), str(r.competition_id)),
                r.home_team,
                r.away_team,
                r.kickoff_at_publish,
                eg,
            )
        )
    keys = [tuple(k) for k in meta.get("outcome_order") or []]
    if len(keys) != len(of_rows) or set(keys) != set(of_rows):
        raise SnapshotIntegrityError("Stored snapshot offers do not match their record.")
    outcomes = []
    for k in keys:
        r = of_rows[k]
        outcomes.append(
            make_outcome(
                r.fixture_id,
                r.market,
                r.outcome,
                r.market_prob,
                Decimal(r.consensus_odds),
                r.model_prob,
                r.bookmaker_groups,
                r.latest_observation_at,
                fx_rows[r.fixture_id].competition_id,
                oldest_observation_at=r.oldest_observation_at,
                provider_updated_at=r.provider_updated_at,
            )
        )
    config_version = meta.get("config_version") or head.config_version
    if head.config_version is not None and config_version != head.config_version:
        raise SnapshotIntegrityError("The snapshot and the round disagree on the configuration.")
    snap = RoundSnapshot(
        head.code,
        SnapshotKind.LIVE,
        head.as_of,
        config_version,
        (head.window_start_at, head.window_end_at),
        tuple(fixtures),
        tuple(outcomes),
        meta.get("source_note", ""),
        meta.get("diagnostics") or None,
    )
    if snap.fingerprint != head.fingerprint:
        raise SnapshotIntegrityError("The stored snapshot does not match its fingerprint.")
    get_config(config_version)  # the configuration must still be registered
    return snap


class SnapshotCache:
    """Per-process cache of published snapshots and editions (immutable, shared data
    only), keyed by **(round id, snapshot id)**: editions never collide, and neither do
    snapshot ids of different databases (identity values repeat across databases; the
    round UUID does not). Which edition is current is always read from the database
    (:func:`current_edition`)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[tuple[UUID, int], RoundSnapshot] = {}
        self._universe: dict[UUID, int] = {}

    def by_id(self, conn: Connection, round_id: UUID, snapshot_id: int) -> RoundSnapshot:
        key = (round_id, snapshot_id)
        with self._lock:
            hit = self._items.get(key)
        if hit is not None:
            return hit
        snap = load_snapshot(conn, round_id, snapshot_id=snapshot_id)
        with self._lock:
            self._items[key] = snap
        return snap

    def get(self, conn: Connection, round_id: UUID) -> RoundSnapshot:
        """Edition 1, the published snapshot (unchanged meaning for every round)."""
        with self._lock:
            sid = self._universe.get(round_id)
        if sid is None:
            sid = universe_id(conn, round_id)
            with self._lock:
                self._universe[round_id] = sid
        return self.by_id(conn, round_id, sid)

    def current(self, conn: Connection, round_id: UUID) -> tuple[int, int, RoundSnapshot]:
        """``(snapshot_id, edition, snapshot)`` of the round's latest edition."""
        sid, edition = current_edition(conn, round_id)
        return sid, edition, self.by_id(conn, round_id, sid)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._universe.clear()


CACHE = SnapshotCache()


def latest_kickoff(snap: RoundSnapshot) -> datetime | None:
    return max((f.kickoff for f in snap.fixtures), default=None)
