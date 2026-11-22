"""``diski9 jobs``: the scheduled lifecycle reconciler (Phase 6C.6 Stage C).

* ``diski9 jobs tick`` — one reconciliation pass, for an external trigger (cron,
  systemd timer, launchd, a hosted scheduler) every few minutes. It never loops or
  sleeps and exits with: 0 nothing failed (including disabled, paused, another tick
  running, or an earlier tick that may still be finishing); 1 a retryable failure,
  the tick lost its lock, or the database was unavailable; 2 invalid configuration
  or an unsafe (transaction-pooler) lock connection (nothing done); 4 an operator
  must act (blocking) and nothing retryable failed.
* ``diski9 jobs tick --dry-run`` — what is due now; writes nothing, no provider call.
* ``diski9 jobs status`` — configuration, provider requests in the last 24 hours and
  recent scheduler runs (read-only).

No password, session or operator identity is used: lifecycle steps run as the
explicit ``SYSTEM`` actor, which the services accept only for lock, results import,
settlement and finalisation. Output is one line per step, suitable for cron logs,
and never contains credentials.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError


def add_parsers(sub) -> None:
    s = sub.add_parser(
        "jobs", help="scheduled lifecycle reconciler (lock, results, settle, finalise)"
    )
    js = s.add_subparsers(dest="action", required=True)
    p = js.add_parser("tick", help="one reconciliation pass (run by cron/systemd/launchd)")
    p.add_argument("--dry-run", action="store_true",
                   help="show what is due now; writes nothing and calls no provider")  # fmt: skip
    p = js.add_parser("status", help="configuration, provider use and recent runs (read-only)")
    p.add_argument("--limit", type=int, default=15, help="recent runs to show (default 15)")


def _config():
    from diski9.backend.jobs import ConfigError, load_config

    try:
        return load_config(), None
    except (ConfigError, ValueError) as exc:
        return None, str(exc)


def _describe(cfg) -> str:
    state = "enabled" if cfg.enabled else "disabled"
    if cfg.paused:
        state += f", paused ({cfg.pause_reason})"
    return (
        f"automation {state}; streams {', '.join(cfg.streams) or '(none)'}; provider calls "
        f"{'on' if cfg.provider_calls else 'off'} (cap {cfg.max_requests_per_tick}/tick, "
        f"{cfg.max_requests_per_day}/24 h); draft preparation "
        + (
            f"on ({', '.join(cfg.prepare_streams)}; readiness every "
            f"{int(cfg.prepare_readiness_interval.total_seconds() // 60)} min)"
            if cfg.prepare
            else "off"
        )  # fmt: skip
    )


def _print_report(report, prefix: str) -> None:
    for step in report.steps:
        print(f"{prefix} {step.line()}")
    for note in report.notes:
        print(f"{prefix} note: {note}")


def _tick(args) -> int:
    from diski9.backend.db import make_app_engine
    from diski9.backend.jobs import Outcome, plan_tick, tick
    from diski9.backend.jobs.provider import api_football_provider

    cfg, error = _config()
    if cfg is None:
        print(f"jobs tick: configuration error: {error}; nothing was done", file=sys.stderr)
        return 2
    if not cfg.enabled and not args.dry_run:
        print("tick: disabled - automation is disabled (DISKI9_JOBS_ENABLED); nothing was done")
        return 0
    try:
        engine = make_app_engine()
    except Exception as exc:  # noqa: BLE001 - settings errors never echo the URL
        print(f"jobs tick: database configuration error ({type(exc).__name__}); nothing was done",
              file=sys.stderr)  # fmt: skip
        return 2
    if args.dry_run:
        try:
            report = plan_tick(engine, cfg)
        except SQLAlchemyError as exc:
            print(f"jobs tick --dry-run: database unavailable ({type(exc).__name__})",
                  file=sys.stderr)  # fmt: skip
            return 1
        print(f"dry run: {_describe(cfg)}")
        if not cfg.enabled:
            print("dry run: automation is disabled, so a real tick would do nothing")
        _print_report(report, "dry run:")
        print(f"dry run: {len(report.steps)} line(s); provider requests in the last 24 h "
              f"{report.day_requests}; nothing was written")  # fmt: skip
        return 0
    from diski9.backend.jobs.locking import lock_url

    try:
        url = lock_url()
    except ValueError as exc:  # ConfigError / ConnectionModeError: never echo the URL
        print(f"jobs tick: unsafe or invalid scheduler connection: {exc}; nothing was done",
              file=sys.stderr)  # fmt: skip
        return 2

    def provider():
        return api_football_provider(
            cfg.provider_timeout_seconds, cfg.provider_max_retries, cfg.provider_max_wait
        )

    report = tick(engine, cfg, provider_factory=provider if cfg.provider_calls else None,
                  lock_url=url)  # fmt: skip
    tag = f"tick {report.tick_run_id}" if report.tick_run_id else "tick"
    if report.status != "completed":
        stream = sys.stderr if report.exit_code else sys.stdout
        print(f"{tag}: {report.status} - {report.detail}", file=stream)
        for note in report.notes:
            print(f"{tag}: note: {note}", file=stream)
        return report.exit_code
    _print_report(report, f"[{tag}]")
    counts = ", ".join(
        f"{report.count(o)} {o.value.replace('_', ' ')}"
        for o in (
            Outcome.SUCCEEDED,
            Outcome.SKIPPED,
            Outcome.DEFERRED,
            Outcome.RETRYABLE,
            Outcome.BLOCKING,
        )  # fmt: skip
    )
    print(f"{tag} completed: {counts}; provider requests {report.api_requests} "
          f"(24 h {report.day_requests}/{cfg.max_requests_per_day})")  # fmt: skip
    return report.exit_code


def _status(args) -> int:
    from diski9.backend.db import make_app_engine, transaction
    from diski9.backend.db.schema import job_runs
    from diski9.backend.jobs.reconciler import _day_requests

    cfg, error = _config()
    print(f"configuration: {error and 'INVALID - ' + error or _describe(cfg)}")
    try:
        engine = make_app_engine()
    except Exception as exc:  # noqa: BLE001 - settings errors never echo the URL
        print(f"database configuration error ({type(exc).__name__})", file=sys.stderr)
        return 2
    try:
        with transaction(engine) as conn:
            rows = conn.execute(
                select(job_runs.c.id, job_runs.c.job, job_runs.c.scope, job_runs.c.status,
                       job_runs.c.started_at, job_runs.c.api_requests, job_runs.c.error)
                .where(job_runs.c.job.like("scheduler.%"))
                .order_by(job_runs.c.id.desc()).limit(max(1, min(args.limit, 200)))
            ).all()  # fmt: skip
        used = _day_requests(engine)
    except SQLAlchemyError as exc:
        print(f"database unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1
    cap = cfg.max_requests_per_day if cfg else "?"
    print(f"scheduler provider requests in the last 24 h: {used}/{cap}")
    try:
        from diski9.backend.jobs.prepare import preparation_lines, preparation_status

        for line in preparation_lines(preparation_status(engine, cfg)):
            print(line)
    except SQLAlchemyError as exc:
        print(f"preparation status unavailable ({type(exc).__name__})", file=sys.stderr)
    if not rows:
        print("no scheduler runs recorded")
    for r in rows:
        err = f" - {r.error}" if r.error else ""
        print(f"{r.id:>8} {r.started_at:%Y-%m-%d %H:%M:%S} {r.job:<24} {r.scope or '-':<22} "
              f"{r.status:<9} req {r.api_requests}{err}")  # fmt: skip
    return 0


def run(args: argparse.Namespace) -> int:
    return _tick(args) if args.action == "tick" else _status(args)
