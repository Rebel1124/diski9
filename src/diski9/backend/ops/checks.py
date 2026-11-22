"""Operational health checks with a three-level severity model (Stage D).

* **INFO** — expected states: automation disabled or paused on purpose, provider
  calls off, a draft awaiting operator publication, rounds progressing normally.
* **WARNING** — needs attention: a delayed tick, repeated retryable failures, a
  stuck or abandoned step, a round past a lifecycle time by the warning threshold,
  a blocking alert, provider budget nearly used.
* **CRITICAL** — threatens integrity or blocks required operations: no tick for the
  critical threshold while automation should run, persistent step failures, a round
  far overdue for locking or finalisation, finalisation blocked beyond its eligible
  time, an Official-stream anomaly, an integrity mismatch, database unreachable or
  at the wrong migration head.

Times are the competition's own: the entry deadline, the settlement cutoff and the
S-02 earliest finalisation. Each finding has a stable fingerprint
(``code:subject``) used for notification de-duplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any

from sqlalchemy import Engine

from ..jobs.config import SchedulerConfig
from .config import OpsConfig
from .snapshot import PROVIDER_JOBS, Snapshot


class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    CRITICAL = 2

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class Finding:
    severity: Severity
    category: str  # scheduler | lifecycle | integrity | provider | database | config
    code: str
    subject: str
    message: str

    @property
    def fingerprint(self) -> str:
        return f"{self.code}:{self.subject}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.label,
            "category": self.category,
            "code": self.code,
            "subject": self.subject,
            "message": self.message,
            "fingerprint": self.fingerprint,
        }


def exit_code(findings: list[Finding]) -> int:
    """0 healthy (INFO only), 1 at least one WARNING, 2 at least one CRITICAL."""
    worst = max((f.severity for f in findings), default=Severity.INFO)
    return int(worst)


def _age(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} min"
    hours = minutes // 60
    return f"{hours} h" if hours < 72 else f"{hours // 24} d"


def database_unavailable(detail: str) -> list[Finding]:
    return [Finding(Severity.CRITICAL, "database", "database_unavailable", "database", detail)]


def config_problem(what: str, detail: str) -> Finding:
    return Finding(Severity.CRITICAL, "config", "config_invalid", what, detail)


def evaluate(snap: Snapshot, ops: OpsConfig, jobs: SchedulerConfig | None) -> list[Finding]:
    out: list[Finding] = []

    def add(sev, cat, code, subject, msg):
        out.append(Finding(sev, cat, code, subject, msg))

    now = snap.now
    # ------------------------------------------------------------ database
    if snap.tables_missing:
        add(
            Severity.CRITICAL,
            "database",
            "tables_missing",
            "database",
            f"required tables missing: {', '.join(snap.tables_missing)}",
        )
        return out
    if snap.schema_revision != snap.expected_head:
        add(
            Severity.CRITICAL,
            "database",
            "migration_head",
            "database",
            f"schema at {snap.schema_revision}, code expects {snap.expected_head}",
        )
    if snap.query_ms is not None and snap.query_ms > 2000:
        add(
            Severity.WARNING,
            "database",
            "slow_database",
            "database",
            f"a trivial query took {snap.query_ms:.0f} ms",
        )

    # ------------------------------------------------------------ scheduler
    active = bool(jobs and jobs.enabled and not jobs.paused)
    if jobs is None:
        pass  # reported by the caller as a configuration problem
    elif not jobs.enabled:
        add(
            Severity.INFO,
            "scheduler",
            "automation_disabled",
            "scheduler",
            "automation is disabled (DISKI9_JOBS_ENABLED): lifecycle steps are manual",
        )
    elif jobs.paused:
        add(
            Severity.INFO,
            "scheduler",
            "automation_paused",
            "scheduler",
            f"automation is paused ({jobs.pause_reason})",
        )
    tick_live = snap.active_tick
    if tick_live is not None:
        age = now - tick_live["started_at"]
        if age >= ops.heartbeat_critical:
            add(
                Severity.CRITICAL,
                "scheduler",
                "tick_overrunning",
                "scheduler",
                f"tick {tick_live.get('tick_id')} has held the scheduler lock for {_age(age)}",
            )
        else:
            add(
                Severity.INFO,
                "scheduler",
                "tick_active",
                "scheduler",
                f"tick {tick_live.get('tick_id')} is running ({_age(age)})",
            )
    if snap.lock_lost:
        last_lost = snap.lock_lost[0]
        add(
            Severity.WARNING,
            "scheduler",
            "tick_lock_lost",
            "scheduler",
            f"{len(snap.lock_lost)} tick(s) lost the scheduler lock in 24 h (last: tick "
            f"{last_lost.id}, {_age(now - last_lost.started_at)} ago); see operations runbook",
        )
    abandon_after = jobs.abandon_after if jobs is not None else timedelta(minutes=20)
    for o in snap.orphan_ticks:
        age = now - o["started_at"]
        if age < abandon_after:
            add(
                Severity.WARNING,
                "scheduler",
                "tick_indeterminate",
                f"tick {o['tick_id']}",
                f"tick {o['tick_id']} no longer holds the lock but its steps are still running "
                f"({_age(age)}); it may still be finishing, so new ticks wait (up to "
                f"{_age(abandon_after)})",
            )
        else:
            add(
                Severity.WARNING,
                "scheduler",
                "tick_unfinished",
                f"tick {o['tick_id']}",
                f"tick {o['tick_id']} left steps running for {_age(age)}; the next tick records "
                "them as abandoned",
            )
    if active and tick_live is None:
        last = snap.last_tick
        if last is None:
            add(
                Severity.CRITICAL,
                "scheduler",
                "no_heartbeat",
                "scheduler",
                "automation is enabled but no scheduler tick has ever been recorded",
            )
        else:
            age = now - last.started_at
            if age >= ops.heartbeat_critical:
                add(
                    Severity.CRITICAL,
                    "scheduler",
                    "heartbeat_missing",
                    "scheduler",
                    f"no scheduler tick for {_age(age)} (expected every {_age(ops.tick_interval)})",
                )
            elif age >= ops.heartbeat_warning:
                add(
                    Severity.WARNING,
                    "scheduler",
                    "heartbeat_delayed",
                    "scheduler",
                    f"last scheduler tick {_age(age)} ago (expected every "
                    f"{_age(ops.tick_interval)})",
                )
            ok = snap.last_ok_tick
            if ok is None or now - ok.started_at >= ops.heartbeat_critical:
                recent = [t for t in snap.ticks[:3] if t.status == "failed"]
                if len(recent) == 3:
                    add(
                        Severity.CRITICAL,
                        "scheduler",
                        "ticks_failing",
                        "scheduler",
                        "the last three scheduler ticks recorded failed steps and none "
                        "succeeded within the critical heartbeat window",
                    )
    for j in snap.running:
        age = now - j.started_at
        if age >= ops.stuck:
            add(
                Severity.WARNING,
                "scheduler",
                "step_stuck",
                f"{j.job} {j.scope}",
                f"{j.job} for {j.scope or 'scheduler'} still running after {_age(age)} "
                f"(job {j.id})",
            )
    for j in snap.abandoned:
        add(
            Severity.WARNING,
            "scheduler",
            "step_abandoned",
            f"{j.job} {j.scope}",
            f"{j.job} for {j.scope or 'scheduler'} was abandoned by an interrupted tick "
            f"(job {j.id})",
        )
    for (job, scope), (n, err) in sorted(snap.streaks.items()):
        if n >= ops.step_failures_warning:
            sev = Severity.CRITICAL if n >= ops.step_failures_critical else Severity.WARNING
            add(
                sev,
                "scheduler",
                "step_failing",
                f"{job} {scope}",
                f"{job} for {scope} failed {n} times in a row (last: {err or 'unknown'})",
            )

    # ------------------------------------------------------------ lifecycle
    for f in snap.rounds:
        s = f.code
        if f.category == "awaiting_publication":
            add(
                Severity.INFO,
                "lifecycle",
                "awaiting_publication",
                s,
                f"{f.stream} draft {s} awaits authenticated operator publication",
            )
        elif f.category == "awaiting_lock" and f.deadline_at:
            late = now - f.deadline_at
            if late >= ops.lock_critical:
                add(
                    Severity.CRITICAL,
                    "lifecycle",
                    "lock_overdue",
                    s,
                    f"{s} is still open {_age(late)} after its entry deadline",
                )
            elif late >= ops.lock_warning:
                add(
                    Severity.WARNING,
                    "lifecycle",
                    "lock_overdue",
                    s,
                    f"{s} is still open {_age(late)} after its entry deadline",
                )
        elif f.category == "needs_result_mode":
            add(
                Severity.WARNING,
                "lifecycle",
                "result_mode_missing",
                s,
                f"development round {s} needs a result mode (dev-results set-mode)",
            )
        if f.status in ("locked", "settling") and f.settle_cutoff_at and now >= f.settle_cutoff_at:
            settled_after = f.last_settlement_at and f.last_settlement_at >= f.settle_cutoff_at
            late = now - f.settle_cutoff_at
            if not settled_after:
                if late >= ops.settle_critical:
                    add(
                        Severity.CRITICAL,
                        "lifecycle",
                        "settlement_overdue",
                        s,
                        f"{s} has no settlement run since its cutoff {_age(late)} ago",
                    )
                elif late >= ops.settle_warning:
                    add(
                        Severity.WARNING,
                        "lifecycle",
                        "settlement_overdue",
                        s,
                        f"{s} has no settlement run since its cutoff {_age(late)} ago",
                    )
        if f.code in snap.settlement_failures:
            add(
                Severity.WARNING,
                "lifecycle",
                "settlement_failed",
                s,
                f"{snap.settlement_failures[s]} failed settlement run(s) for {s} in 24 h",
            )
        if f.blocking_alerts:
            beyond = f.earliest is not None and now >= f.earliest + ops.finalise_critical
            add(
                Severity.CRITICAL if beyond else Severity.WARNING,
                "lifecycle",
                "blocking_alerts",
                s,
                f"{f.blocking_alerts} settlement-blocking alert(s) on {s} need an operator"
                + (" (finalisation blocked beyond its eligible time)" if beyond else ""),
            )
        if f.category in ("eligible_for_finalisation", "overdue_for_finalisation") and f.earliest:
            late = now - f.earliest
            if late >= ops.finalise_critical:
                sev = Severity.CRITICAL
            elif late >= ops.finalise_warning:
                sev = Severity.WARNING
            else:
                sev = Severity.INFO
            add(
                sev,
                "lifecycle",
                "finalisation_pending",
                s,
                f"{s} has been eligible for finalisation (S-02) for {_age(late)}",
            )
        # results staleness: only meaningful when the scheduler is expected to import
        if (
            active
            and jobs
            and jobs.provider_calls
            and f.stream != "development"
            and f.result_mode == "real"
            and f.status in ("locked", "settling")
            and f.first_kickoff
            and f.settle_cutoff_at
            and f.first_kickoff <= now < f.settle_cutoff_at
        ):
            since = f.last_import_at or f.first_kickoff
            if now - since >= ops.results_stale:
                add(
                    Severity.WARNING,
                    "provider",
                    "results_stale",
                    s,
                    f"no results import for {s} for {_age(now - since)} while matches are in play",
                )

    # ------------------------------------------------------------ preparation (E.1a)
    _preparation(snap, ops, jobs, add)
    _refresh(snap, ops, jobs, add)
    from .backups import backup_findings

    backup_findings(snap, ops, add)

    # ------------------------------------------------------------ provider
    if jobs is not None:
        if not jobs.provider_calls:
            add(
                Severity.INFO,
                "provider",
                "provider_calls_off",
                "provider",
                "automated provider calls are off: real rounds are not finalised by the scheduler",
            )
        cap = jobs.max_requests_per_day
        used = snap.provider_day_requests
        if used > cap:
            add(
                Severity.CRITICAL,
                "provider",
                "budget_exceeded",
                "provider",
                f"scheduler used {used} provider requests in 24 h, above its cap of {cap}",
            )
        elif used >= cap:
            add(
                Severity.WARNING,
                "provider",
                "budget_exhausted",
                "provider",
                f"scheduler provider budget exhausted ({used}/{cap} in 24 h); imports deferred",
            )
        elif cap and used * 100 >= cap * ops.budget_warning_percent:
            add(
                Severity.WARNING,
                "provider",
                "budget_high",
                "provider",
                f"scheduler provider use {used}/{cap} in 24 h",
            )
        fails = [
            n
            for (job, _), (n, err) in snap.streaks.items()
            if job in PROVIDER_JOBS and (err or "").find("provider") >= 0
        ]
        if fails and max(fails) >= ops.step_failures_warning:
            add(
                Severity.WARNING,
                "provider",
                "provider_failing",
                "provider",
                f"provider imports failing repeatedly (up to {max(fails)} in a row)",
            )

    # ------------------------------------------------------------ integrity (light)
    for a in snap.official_anomalies:
        add(Severity.CRITICAL, "integrity", "official_anomaly", "official", a)
    for code in snap.final_without_results:
        add(
            Severity.WARNING,
            "integrity",
            "final_without_results",
            code,
            f"final round {code} has no published weekly results (competition verify)",
        )
    return out


def _preparation(snap: Snapshot, ops: OpsConfig, jobs: SchedulerConfig | None, add) -> None:
    """Stage E.1a findings for the upcoming Beta week, relative to the schedule's own
    times (draft creation time, publication target). Quiet when nothing is
    actionable: a draft NOT READY days before the target is expected (the football
    store is refreshed shortly before publication), so it raises nothing until the
    attention window opens."""
    if jobs is None or not jobs.enabled:
        return
    if not jobs.prepare:
        add(Severity.INFO, "preparation", "prepare_disabled", "preparation",
            "automated draft preparation is off (DISKI9_JOBS_PREPARE): drafts are created "
            "with round create")  # fmt: skip
        return
    if snap.preparation_error:
        add(Severity.WARNING, "preparation", "prepare_status_unavailable", "preparation",
            f"preparation status could not be derived ({snap.preparation_error})")  # fmt: skip
        return
    st = snap.preparation
    if st is None or st.week is None:
        return
    for code in st.lapsed_recent:
        add(Severity.WARNING, "preparation", "prepare_lapsed", code,
            f"draft {code} was never published; its fixture window has ended")  # fmt: skip
    if jobs.paused:
        return  # paused on purpose: reported as automation_paused
    w, now, code = st.week, st.now or snap.now, st.week.code
    attention = now >= w.target - ops.prepare_attention
    after_target = now >= w.target
    state = st.state
    if state == "no_draft":
        if now >= w.target - timedelta(hours=6):
            add(Severity.CRITICAL, "preparation", "prepare_no_draft", code,
                f"no draft for {code} and the publication target is {_iso_short(w.target)}; "
                "check the scheduler or create it with round create")  # fmt: skip
        elif now >= w.create_at + timedelta(hours=1):
            add(
                Severity.WARNING,
                "preparation",
                "prepare_no_draft",
                code,
                f"the draft for {code} was due at {_iso_short(w.create_at)} but does not exist",
            )
    elif state == "lapsed":
        add(Severity.WARNING, "preparation", "prepare_lapsed", code,
            f"{code} can no longer be published: the entry deadline of its fixtures has "
            "passed")  # fmt: skip
    elif state == "intervention":
        near = now >= w.target - timedelta(hours=6)
        critical = (st.blocked and near) or st.failing >= ops.step_failures_critical
        sev = Severity.CRITICAL if critical else Severity.WARNING
        add(
            sev,
            "preparation",
            "prepare_failing",
            code,
            f"preparation of {code} needs an operator: {st.last_error or 'repeated failures'}",
        )
    elif state == "target_missed":
        ready = st.verdict is not None and st.verdict.ready
        add(Severity.CRITICAL if not ready else Severity.WARNING, "preparation",
            "prepare_target_missed", code,
            f"{code} is unpublished {_age(now - w.target)} after its publication target"
            + ("; the draft was READY at its last evaluation" if ready else
               f"; last evaluation NOT READY ({_verdict_text(st)})"))  # fmt: skip
    elif state == "draft_ready" and after_target:
        late = now - w.target
        sev = Severity.WARNING if late >= ops.prepare_publish_warning else Severity.INFO
        add(sev, "preparation", "prepare_ready_unpublished", code,
            f"{code} is READY for operator review and unpublished {_age(late)} after its "
            "publication target (round readiness, then round publish)")  # fmt: skip
    elif state == "draft_ready" and attention:
        add(Severity.INFO, "preparation", "prepare_ready", code,
            f"{code} is READY for operator review (publication target "
            f"{_iso_short(w.target)})")  # fmt: skip
    elif state == "draft_not_ready" and attention:
        add(Severity.WARNING if after_target else Severity.INFO, "preparation",
            "prepare_not_ready", code,
            f"{code} is NOT READY ({_verdict_text(st)}); publication target "
            f"{_iso_short(w.target)}")  # fmt: skip
    elif state == "draft_not_evaluated" and attention:
        add(
            Severity.WARNING,
            "preparation",
            "prepare_stale_evaluation",
            code,
            f"readiness of {code} has not been evaluated recently "
            f"(last: {_iso_short(st.last_evaluation_at) if st.last_evaluation_at else 'never'})",
        )


def _refresh(snap: Snapshot, ops: OpsConfig, jobs: SchedulerConfig | None, add) -> None:
    """Stage E.1b findings: football-data refresh and provider allowance. Quiet early
    in the week; escalates as the publication target approaches."""
    if jobs is None or not jobs.enabled or not jobs.prepare or snap.preparation_error:
        return
    st = snap.preparation
    if st is None or st.week is None:
        return
    w, now, code = st.week, st.now or snap.now, st.week.code
    if not jobs.prepare_refresh:
        if st.state not in ("published", "lapsed", "not_due") and now < w.target:
            add(Severity.INFO, "refresh", "refresh_disabled", "refresh",
                "automated data refresh is off (DISKI9_JOBS_PREPARE_REFRESH): run "
                "refresh-data --with-odds before checking readiness")  # fmt: skip
        return
    r = st.refresh
    if r is None:
        return
    # provider allowance (any week state: it protects results imports too)
    if r.limit_today is not None and r.limit_today < jobs.provider_expected_daily_limit:
        add(Severity.CRITICAL, "refresh", "provider_limit_mismatch", "provider",
            f"the provider reports a daily limit of {r.limit_today} (expected "
            f"{jobs.provider_expected_daily_limit}); preparation is stopped for the provider "
            "day; verify the subscription")  # fmt: skip
    if r.quota_remaining is not None:
        if r.quota_remaining < 600:
            add(Severity.CRITICAL, "refresh", "provider_quota_low", "provider",
                f"provider daily remaining {r.quota_remaining}: results imports are close to "
                "the client reserve; stop manual bulk commands")  # fmt: skip
        elif r.quota_remaining < jobs.prepare_provider_floor:
            add(Severity.WARNING, "refresh", "provider_quota_low", "provider",
                f"provider daily remaining {r.quota_remaining} is below the preparation floor "
                f"{jobs.prepare_provider_floor}: refresh is held back (other users of the "
                "key?)")  # fmt: skip
    if r.quota_gap is not None and r.quota_gap > 0.10:
        add(Severity.WARNING, "refresh", "provider_quota_inconsistent", "provider",
            f"provider status and response headers disagree by {r.quota_gap:.0%}; the lower "
            "figure is used")  # fmt: skip
    if r.throttled_24h:
        sev = Severity.CRITICAL if r.throttled_24h >= 3 else Severity.WARNING
        add(sev, "refresh", "provider_throttled", "provider",
            f"the provider rate-limited the scheduler {r.throttled_24h} time(s) in 24 h; check "
            "other users of the key")  # fmt: skip
    caps = r.caps
    if caps and r.used_preparation > caps["per_day"] - caps["results_reserve"]:
        add(Severity.CRITICAL, "refresh", "results_reserve_breached", "provider",
            f"preparation used {r.used_preparation} requests in 24 h, inside the results "
            "reserve; escalate")  # fmt: skip
    elif caps and r.used_preparation >= caps["nonessential"]:
        add(Severity.WARNING, "refresh", "budget_nonessential_exhausted", "provider",
            f"preparation used its {caps['nonessential']} requests in 24 h; refresh "
            "waits")  # fmt: skip
    if st.state in ("published", "lapsed") or now >= w.target + jobs.prepare_grace:
        return
    attention = now >= w.target - ops.prepare_attention
    sw = r.sweep
    if sw is not None:
        for league, (n, err) in sorted(r.failing.items()):
            if n < 2:
                continue
            near = w.target - timedelta(hours=1) <= now
            add(Severity.CRITICAL if near else Severity.WARNING, "refresh", "refresh_failing",
                f"{code}:{league}", f"league {league} refresh failed {n} times in the "
                f"{sw.slot.label} slot: {err[:160]}")  # fmt: skip
        if sw.state == "partial":
            add(Severity.WARNING, "refresh", "refresh_partial", code,
                f"the {sw.slot.label} sweep closed partial ({sw.counts} leagues); the next slot "
                "refreshes every league")  # fmt: skip
        if r.coverage_drop and attention:
            add(Severity.WARNING, "refresh", "odds_coverage_drop", code,
                f"leagues {r.coverage_drop} returned no odds fixtures although they had odds "
                "earlier this week")  # fmt: skip
        if r.update_not_today and now >= w.target - timedelta(hours=1):
            add(Severity.WARNING, "refresh", "provider_update_missing", code,
                f"today's provider odds update not seen yet for leagues {r.update_not_today}; "
                "grace sweeps retry hourly")  # fmt: skip
    if now >= w.target - timedelta(minutes=90):
        first = min(jobs.refresh_publication)
        friday = datetime.combine(w.window_start.date(), first, UTC)
        closed = r.last_closed
        slot_at = None
        if closed:
            try:
                slot_at = datetime.strptime(str(closed["slot"]).rsplit("@", 1)[1],
                                            "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)  # fmt: skip
            except (KeyError, ValueError, IndexError):
                slot_at = None
        if slot_at is None or slot_at < friday:
            sev = Severity.CRITICAL if now >= w.target - timedelta(minutes=30) else Severity.WARNING
            add(sev, "refresh", "store_not_current", code,
                f"no data sweep has closed since {_iso_short(friday)} (publication target "
                f"{_iso_short(w.target)}): run refresh-data --with-odds, then round "
                "readiness")  # fmt: skip
        elif closed.get("kind") == "complete":
            add(
                Severity.INFO,
                "refresh",
                "refresh_ok",
                code,
                f"data refreshed for publication ({_iso_short(closed.get('finished_at'))})",
            )
    elif r.last_complete and attention:
        add(
            Severity.INFO,
            "refresh",
            "refresh_ok",
            code,
            f"last complete data sweep {_iso_short(r.last_complete.get('finished_at'))}",
        )


def _iso_short(dt) -> str:
    return dt.astimezone(UTC).strftime("%a %d %b %H:%M UTC") if dt else "-"


def _verdict_text(st) -> str:
    v = st.verdict
    if v is None:
        return "not evaluated"
    return f"{v.category}: {(v.problem or '')[:120]}"


def _short(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()[:10]


def deep_findings(engine: Engine) -> tuple[list[Finding], float]:
    """The full championship integrity inspection (``inspect_stream``) of every open
    stream. Expensive on large datasets: run on demand (``ops check --deep``) or on a
    slow schedule, never on every tick. Returns findings and elapsed milliseconds."""
    import time

    from ..db import read_only
    from ..services import championships

    t0 = time.monotonic()
    out: list[Finding] = []
    with read_only(engine) as conn:
        for stream in championships.STREAMS:
            if not championships.stream_open(conn, stream):
                continue
            ins = championships.inspect_stream(conn, stream)
            for f in ins.material:
                out.append(
                    Finding(
                        Severity.CRITICAL,
                        "integrity",
                        "integrity_material",
                        f"{stream} {_short(str(f))}",
                        f"{stream}: {f}",
                    )
                )
            for f in ins.repairable:
                out.append(
                    Finding(
                        Severity.WARNING,
                        "integrity",
                        "integrity_repairable",
                        f"{stream} {_short(str(f))}",
                        f"{stream}: {f} (competition repair)",
                    )
                )
    return out, round((time.monotonic() - t0) * 1000, 1)
