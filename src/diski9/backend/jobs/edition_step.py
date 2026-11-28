"""The competitive price-edition step of a tick (Phase 8 CP3A-R, R2).

:mod:`.refresh` plans one ``scheduler.prepare_edition`` step after each closed
competitive sweep of an open rolling-entry round, but never touches competition data
itself (its E.1b boundary). This module runs that step from preparation: it builds the
candidate from the football store (read-only) and writes it as the round's next
immutable edition through :func:`~diski9.backend.services.editions.publish_edition`,
as the scheduler actor. Attempted once per slot: a refusal (for example nothing fresh
to price) is recorded with its reason; the current edition stays and its prices age
out by their own timestamps.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..db import transaction
from ..repositories import ops
from ..services import editions
from ..services.rounds import SYSTEM
from . import refresh
from .locking import LockLost


def run_editions(run, report, week, round_status: str | None) -> None:
    """Run the edition steps the refresh planner lists now (rolling rounds only)."""
    from ..db import db_now
    from .prepare import _now

    if round_status != "open":
        return
    with transaction(run.engine) as conn:
        now, real = _now(conn), db_now(conn)
        todo, _ = refresh.plan(conn, run.cfg, week, round_status, now, real)
    for p in todo:
        if p.kind == "edition":
            report.steps.append(edition_step(run, week, p.slot))


def edition_step(run, week, slot):
    from .reconciler import JOB_STATUS, Outcome, StepReport, _begin, _classify, _end

    run.check()
    run_id = _begin(run.engine, refresh.PREPARE_EDITION, week.code,
                    {"stream": refresh.STREAM, "slot": slot.key(week.code), "tick": run.tick_id,
                     "run_token": run.token, "step": "prepare_edition"}, run.host)  # fmt: skip
    store = None
    lost: LockLost | None = None
    try:
        store = refresh._store(run)
        run.lock.verify()
        with transaction(run.engine) as conn:
            rr = refresh._round_row(conn, week.code)
        cand = editions.build_candidate(store, run.engine, rr.id, datetime.now(UTC))
        run.lock.verify()
        res = editions.publish_edition(run.engine, SYSTEM, rr.id, cand, job_run_id=run_id)
        detail = (f"edition {res.edition} after the {slot.label} sweep: {res.fixtures} "
                  f"fixtures, {res.offers} offers")  # fmt: skip
        with transaction(run.engine) as conn:
            ops.finish_job(conn, run_id, JOB_STATUS[Outcome.SUCCEEDED], error=detail[:500])
        return StepReport(week.code, refresh.STREAM, "prepare_edition", Outcome.SUCCEEDED,
                          detail, run_id)  # fmt: skip
    except LockLost as exc:
        lost = exc
        outcome, detail = Outcome.RETRYABLE, f"lock lost: {exc}"
    except editions.EditionRefused as exc:
        outcome, detail = Outcome.SKIPPED, f"edition not written: {exc.message}"
    except refresh.FootballStoreUnavailable as exc:
        outcome, detail = Outcome.BLOCKING, f"football store unavailable ({exc})"
    except Exception as exc:  # noqa: BLE001 - classified, recorded, never fatal
        outcome, detail = _classify(exc)
    finally:
        if store is not None:
            store.dispose()
    _end(run.engine, run_id, outcome, detail)
    if lost is not None:
        raise lost
    return StepReport(week.code, refresh.STREAM, "prepare_edition", outcome, detail, run_id)
