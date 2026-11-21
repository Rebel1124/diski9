"""One-round operational investigation (Phase 6C.6 Stage E).

Composes existing read-only sources — the round view, the settlement services'
operator reports (status, S-02 finalisation eligibility, fixtures and evidence,
alerts), the Stage D job history and the round's audit records, and the round's
championship assignment — into one report. Nothing is written and no lifecycle or
settlement rule is reimplemented: settlement figures come from
:mod:`..services.settlement_ops`, which computes them inside a transaction that is
always rolled back, and the lifecycle position uses the Stage D classifier.

Authorised like ``settle status`` (``jobs.run``, a password-verified operator or
owner); no participant identity, email or provider payload is included.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from ..auth.permissions import Capability, Forbidden, Principal
from ..db import read_only
from ..services import rounds as rounds_svc
from ..services import settlement_ops
from ..services.results import actor_id
from .config import load_ops_config
from .history import recent_jobs
from .snapshot import RoundFact, classify

PUBLISHED = frozenset({"open", "locked", "settling", "final"})


@dataclass
class RoundInspection:
    round: rounds_svc.RoundView
    position: str
    evaluated_at: datetime
    entries: dict[str, int] = field(default_factory=dict)
    settlement: settlement_ops.RoundReport | None = None
    fixtures: list[settlement_ops.FixtureReport] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)
    championship: dict[str, Any] | None = None
    score_set: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def fixture_summary(self) -> dict[str, int]:
        relevant = [f for f in self.fixtures if f.relevant]
        return {
            "on_sheet": len(self.fixtures),
            "relevant": len(relevant),
            "resolved": sum(1 for f in relevant if f.rule is not None),
            "unresolved": sum(1 for f in relevant if f.rule is None),
            "with_alerts": sum(1 for f in self.fixtures if f.alerts),
        }


def _entries(conn, round_id) -> dict[str, int]:
    rows = conn.execute(
        text("SELECT state, count(*) AS n FROM app.entries WHERE round_id = :r GROUP BY state"),
        {"r": round_id},
    ).all()
    return {r.state: r.n for r in rows}


def _championship(conn, round_id) -> dict[str, Any] | None:
    r = conn.execute(
        text(
            "SELECT c.display_name, c.stream, c.status, c.counted_rounds, c.rounds_required, "
            "c.current_version, cr.role, cr.slot, cr.assigned_at "
            "FROM app.championship_rounds cr "
            "JOIN app.championships c ON c.id = cr.championship_id WHERE cr.round_id = :r"
        ),
        {"r": round_id},
    ).one_or_none()
    return dict(r._mapping) if r else None


def _score_set(conn, round_id) -> dict[str, Any] | None:
    r = conn.execute(
        text(
            "SELECT revision, kind, final, created_at FROM app.score_sets "
            "WHERE round_id = :r ORDER BY revision DESC LIMIT 1"
        ),
        {"r": round_id},
    ).one_or_none()
    return dict(r._mapping) if r else None


def inspect_round(engine: Engine, actor: Principal, round_id) -> RoundInspection:
    if not isinstance(actor, Principal):  # a person only: never the scheduler's SYSTEM
        raise Forbidden("human_only")
    actor_id(actor, Capability.RUN_JOBS)  # authorise before reading anything
    view = rounds_svc.get_round(engine, round_id)
    with read_only(engine) as conn:
        now = conn.execute(text("SELECT transaction_timestamp()")).scalar_one()
        entries = _entries(conn, round_id)
        champ = _championship(conn, round_id)
        score = _score_set(conn, round_id)
    out = RoundInspection(view, "", now, entries=entries, championship=champ, score_set=score)
    report = None
    if view.status in PUBLISHED:
        report = settlement_ops.round_report(engine, actor, round_id)
        out.settlement = report
        out.fixtures = settlement_ops.fixture_report(engine, actor, round_id)
        out.alerts = settlement_ops.alerts_report(engine, actor, round_id)
    fact = RoundFact(
        id=view.id,
        code=view.code,
        stream="development" if view.is_development else view.series,
        status=view.status,
        result_mode=report.result_mode if report else None,
        deadline_at=view.deadline_at,
        settle_cutoff_at=view.settle_cutoff_at,
        earliest=report.earliest_finalisation if report else None,
        first_kickoff=None,
        blocking_alerts=report.open_blocking_alerts if report else 0,
        last_settlement_at=None,
        last_import_at=None,
        finalised_at=None,
    )
    out.position = classify(fact, now, load_ops_config().finalise_warning)
    history = recent_jobs(engine, limit=20, round_code=view.code)
    out.jobs = history["jobs"]
    out.audit = history["audit"]
    if view.status == "draft":
        out.notes.append(
            "Draft: check readiness with `round readiness`, then publish with `round "
            "publish` (an authenticated person; the scheduler never publishes)."
        )
    if report and report.result_mode is None and view.status in {"locked", "settling"}:
        out.notes.append("No result mode chosen (development rounds: dev-results set-mode).")
    return out
