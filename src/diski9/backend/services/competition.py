"""Official weekly results (Phase 6C.5 Stage B).

Specification: ``docs/architecture/phase6c5_design_specification.md`` §6, §7.2,
§9.1 and §11.1.

* **Settlement is authoritative.** This module reads the Phase 6C.4 tables
  (locked entries, the latest ``entry_settlements`` revision, the current
  designation and settlement versions) and never computes a verdict, payout,
  recovery or validity itself.
* **One ranking implementation.** Weekly ranks, points, recovery gating, all-void
  refunds and the deterministic display order come from the unchanged
  ``diski9.challenge.scoring.score_round``. The adapter below only maps settlement
  rows to its inputs.
* **Publication happens only inside a successful finalisation.**
  ``publish_finalised`` runs in the same transaction as
  ``corrections.finalise_round``, so a round is never final without its official
  weekly results, and a failure rolls both back. It is idempotent per final
  settlement version (``score_sets.settlement_version_id`` is unique); a
  re-finalisation after an owner reopening publishes a new revision, and the
  earlier revisions stay in history.

**Weekly points versus championship contribution.** A score set records the points
the approved methodology gives each entry in that round ("weekly points"). Whether
and where they count toward a championship is decided by championship membership
(Stage C, decisions CH-02 and CH-05); nothing here writes championship tables.
Because ``score_round`` requires a championship identifier for competitive rounds,
the adapter passes the neutral placeholder ``UNASSIGNED``, which only labels the
calculation and never reaches storage.

Dependency direction: ``corrections`` imports this module; this module imports
only the schema, the operations repository and ``challenge.scoring`` (never
``settlement`` or ``corrections``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, func, insert, select, text

from ...challenge import scoring
from ..db.schema import (
    championship_series,
    designations,
    domain_events,
    round_scores,
    rounds,
    score_sets,
    settlement_versions,
)
from ..repositories import ops
from .common import ServiceError

ALLOCATION = Decimal("100.00")  # credits per entry (C-01); a refund returns exactly this
UNASSIGNED = "unassigned"  # neutral championship label for weekly scoring (see module doc)

CLASSIFICATION_OF = {
    "championship": scoring.RoundClassification.COMPETITIVE,  # legacy name (D-28 clarification)
    "practice": scoring.RoundClassification.PRACTICE,
    "void": scoring.RoundClassification.VOID,
}
KIND_OF = {
    scoring.RoundClassification.COMPETITIVE: "championship",
    scoring.RoundClassification.PRACTICE: "practice",
    scoring.RoundClassification.VOID: "void",
}


class PublicationRefused(ServiceError):
    """Official results cannot be published from this settlement state."""


def stream_of(is_development: bool, series_code: str) -> str:
    """The competition stream of a round (CH-01): development rounds are always the
    development stream; otherwise the series (``beta`` or ``official``)."""
    return "development" if is_development else series_code


# ------------------------------------------------------------------ adapter (pure)
@dataclass(frozen=True)
class EntryRecord:
    """One locked valid entry with its authoritative (latest) settlement."""

    entry_id: UUID
    user_id: UUID
    gross: Decimal
    basis: str  # entry_settlements.basis: 'settled' | 'all_void' | ...
    complete: bool


def round_result(
    round_id: UUID, designation: str, scoring_version: str, records: list[EntryRecord]
) -> scoring.RoundResult:
    """Map authoritative settlement records to the scoring engine's input.

    * classification from the current final designation (``championship`` means
      competitively classified);
    * every entry must be completely settled: official results are never made from
      incomplete settlement;
    * an all-void entry (D-33) has basis ``ALL_SELECTIONS_VOID``;
    * in an invalidated round every confirmed participant is refunded the
      allocation (D-32b), exactly as settlement presents it to the participant.
    """
    try:
        cls = CLASSIFICATION_OF[designation]
    except KeyError:
        raise PublicationRefused(
            f"A round designated {designation!r} has no official weekly results."
        ) from None
    entries = []
    for rec in records:
        if not rec.complete:
            raise PublicationRefused(
                "Official results need every locked entry to be completely settled."
            )
        all_void = rec.basis == "all_void"
        gross = ALLOCATION if (cls is scoring.RoundClassification.VOID or all_void) else rec.gross
        entries.append(
            scoring.EntryResult(
                participant_id=str(rec.entry_id),
                gross=gross,
                basis=(
                    scoring.SettlementBasis.ALL_SELECTIONS_VOID
                    if all_void
                    else scoring.SettlementBasis.SETTLED
                ),
            )
        )
    return scoring.RoundResult(
        round_id=str(round_id),
        championship_id=UNASSIGNED if cls is scoring.RoundClassification.COMPETITIVE else None,
        classification=cls,
        entries=tuple(entries),
        scoring_version=scoring_version,
        final=True,
    )


def score_status(cls: scoring.RoundClassification, s: scoring.WeeklyScore) -> str:
    if cls is scoring.RoundClassification.VOID:
        return "round_void"
    return "void_refunded" if s.refunded else "ranked"


# ------------------------------------------------------------------ authoritative inputs
def current_designation_row(conn: Connection, round_id: UUID):
    return conn.execute(
        select(designations)
        .where(designations.c.round_id == round_id)
        .order_by(designations.c.created_at.desc(), designations.c.id.desc())
        .limit(1)
    ).one_or_none()


def locked_records(conn: Connection, round_id: UUID) -> list[EntryRecord]:
    """Every entry locked at the deadline with its latest settlement revision; the
    settlement must belong to the locked submission."""
    rows = conn.execute(
        text(
            "SELECT e.id AS entry_id, e.user_id, e.locked_submission_id, "
            "s.submission_id, s.gross, s.basis, s.complete "
            "FROM app.entries e LEFT JOIN LATERAL ("
            "  SELECT submission_id, gross, basis, complete FROM app.entry_settlements es "
            "  WHERE es.entry_id = e.id ORDER BY es.revision DESC LIMIT 1) s ON true "
            "WHERE e.round_id = :r AND e.locked_submission_id IS NOT NULL "
            "ORDER BY e.id"
        ),
        {"r": round_id},
    ).all()
    out = []
    for row in rows:
        if row.submission_id is None or row.submission_id != row.locked_submission_id:
            raise PublicationRefused("A locked entry has no settlement of its locked submission.")
        out.append(EntryRecord(row.entry_id, row.user_id, row.gross, row.basis, row.complete))
    return out


# ------------------------------------------------------------------ publication
@dataclass(frozen=True)
class Publication:
    score_set_id: int
    round_id: UUID
    revision: int
    kind: str
    settlement_version_id: int
    entries: int
    created: bool  # False when this settlement version was already published


def publish_finalised(
    conn: Connection, round_id: UUID, settlement_version_id: int, *, actor: UUID | None
) -> Publication:
    """Publish the official weekly results of a round that has **just** been
    finalised, inside the finalisation transaction (the caller holds the round row
    lock). Idempotent per final settlement version. Raises ``PublicationRefused``
    (and so rolls back the finalisation) if the settlement state is not
    authoritative and complete."""
    existing = conn.execute(
        select(score_sets).where(score_sets.c.settlement_version_id == settlement_version_id)
    ).one_or_none()
    if existing is not None:
        if existing.round_id != round_id:
            raise PublicationRefused("That settlement version belongs to another round.")
        n = conn.execute(
            select(func.count())
            .select_from(round_scores)
            .where(round_scores.c.score_set_id == existing.id)
        ).scalar_one()
        return Publication(existing.id, round_id, existing.revision, existing.kind,
                           settlement_version_id, n, False)  # fmt: skip
    r = conn.execute(select(rounds).where(rounds.c.id == round_id)).one()
    if r.status != "final":
        raise PublicationRefused("Only a final round has official weekly results.")
    v = conn.execute(
        select(settlement_versions).where(settlement_versions.c.id == settlement_version_id)
    ).one_or_none()
    if v is None or v.round_id != round_id or v.kind != "final" or v.run_id is None:
        raise PublicationRefused("Official results publish a final settlement version.")
    latest = conn.execute(
        select(func.max(settlement_versions.c.version)).where(
            settlement_versions.c.round_id == round_id
        )
    ).scalar_one()
    if v.version != latest:
        raise PublicationRefused("Only the latest settlement version can be published.")
    d = current_designation_row(conn, round_id)
    if d is None or d.provisional:
        raise PublicationRefused("The round's designation is not final.")
    records = locked_records(conn, round_id)
    rr = round_result(round_id, d.designation, r.scoring_version, records)
    config = scoring.get_scoring_config(r.scoring_version)
    score = scoring.score_round(rr, config)
    revision = (
        conn.execute(
            select(func.max(score_sets.c.revision)).where(score_sets.c.round_id == round_id)
        ).scalar_one()
        or 0
    ) + 1
    kind = KIND_OF[score.classification]
    set_id = conn.execute(
        insert(score_sets)
        .values(
            round_id=round_id,
            revision=revision,
            run_id=v.run_id,
            designation_id=d.id,
            kind=kind,
            final=True,
            settlement_version_id=settlement_version_id,
            scoring_version=score.scoring_version,
            actor_user_id=actor,
        )
        .returning(score_sets.c.id)
    ).scalar_one()
    by_entry = {str(rec.entry_id): rec for rec in records}
    rows = []
    for s in score.scores:
        rec = by_entry[s.participant_id]
        rows.append(
            {
                "score_set_id": set_id,
                "kind": kind,
                "entry_id": rec.entry_id,
                "user_id": rec.user_id,
                "gross": s.gross,
                "rank": s.rank,
                "points": s.points,
                "recovered": s.recovered,
                "qualifying_top10": s.qualifying_top10,
                "status": score_status(score.classification, s),
                "display_order": s.display_order,
            }
        )
    _insert_scores(conn, rows)
    series_code = conn.execute(
        select(championship_series.c.code).where(championship_series.c.id == r.series_id)
    ).scalar_one()
    conn.execute(
        insert(domain_events).values(
            kind="weekly_results_published",
            round_id=round_id,
            payload={"score_set_id": set_id, "revision": revision, "kind": kind,
                     "stream": stream_of(r.is_development, series_code)},
        )
    )  # fmt: skip
    ops.record_audit(
        conn,
        action="competition.publish",
        target_type="round",
        target_id=str(round_id),
        actor=actor,
        actor_role="system" if actor is None else "operator",
        after={"score_set_id": set_id, "revision": revision, "kind": kind,
               "settlement_version_id": settlement_version_id, "entries": len(rows),
               "scoring_version": score.scoring_version},
    )  # fmt: skip
    # Stage C will assign the round to its championship here (CH-02), in this same
    # transaction and under the series lock.
    return Publication(set_id, round_id, revision, kind, settlement_version_id, len(rows), True)


def _insert_scores(conn: Connection, rows: list[dict]) -> None:
    if rows:
        conn.execute(insert(round_scores), rows)


__all__ = [
    "ALLOCATION",
    "EntryRecord",
    "Publication",
    "PublicationRefused",
    "publish_finalised",
    "round_result",
    "stream_of",
]
