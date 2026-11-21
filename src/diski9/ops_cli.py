"""``diski9 ops``: operational status, health checks, notifications and job history
(Phase 6C.6 Stage D). Read-only apart from the notification ledger.

* ``diski9 ops status [--json]`` — overview; exit 0, or 1 if the database is
  unavailable.
* ``diski9 ops check [--json] [--deep] [--notify]`` — findings with severities;
  exit 0 healthy (INFO only), 1 WARNING, 2 CRITICAL (including an unreachable
  database or invalid configuration). ``--deep`` adds the full championship
  integrity inspection (expensive: not for every tick). ``--notify`` sends
  notifications when they are configured (off by default).
* ``diski9 ops jobs [--limit N] [--job JOB] [--round CODE] [--failed] [--json]`` —
  recent job runs (and, with ``--round``, that round's audit records).

No output contains credentials, the webhook URL, account e-mail addresses or
provider data.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

CATEGORY_LABELS = (
    ("awaiting_publication", "awaiting operator publication"),
    ("entries_open", "entries open"),
    ("awaiting_lock", "awaiting locking"),
    ("awaiting_settlement", "awaiting settlement"),
    ("awaiting_results", "awaiting results (before the settlement cutoff)"),
    ("correction_window", "in the correction window (S-02)"),
    ("eligible_for_finalisation", "eligible for finalisation"),
    ("overdue_for_finalisation", "overdue for finalisation"),
    ("blocked", "blocked by settlement alerts"),
    ("needs_result_mode", "needs a result mode"),
    ("final", "final (last 7 days)"),
)


def add_parsers(sub) -> None:
    s = sub.add_parser("ops", help="operational status, health checks, alerts and job history")
    os_ = s.add_subparsers(dest="action", required=True)
    p = os_.add_parser("status", help="operational overview (read-only)")
    p.add_argument("--json", action="store_true", help="structured output")
    p = os_.add_parser("check", help="health checks with severities and an exit status")
    p.add_argument("--json", action="store_true", help="structured output")
    p.add_argument(
        "--deep",
        action="store_true",
        help="also run the full championship integrity inspection (expensive)",
    )
    p.add_argument(
        "--notify",
        action="store_true",
        help="send notifications if configured (DISKI9_OPS_NOTIFY, off by default)",
    )
    p = os_.add_parser("jobs", help="recent job runs (read-only)")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--job", default=None, help="one job name, e.g. scheduler.settle")
    p.add_argument("--round", dest="round_code", default=None, help="one round code")
    p.add_argument("--failed", action="store_true", help="failed runs only")
    p.add_argument("--json", action="store_true", help="structured output")


def _configs():
    from diski9.backend.jobs import ConfigError, load_config
    from diski9.backend.ops import OpsConfig, load_ops_config

    errors = []
    try:
        jobs = load_config()
    except (ConfigError, ValueError) as exc:
        jobs, _ = None, errors.append(("scheduler", str(exc)))
    try:
        ops = load_ops_config()
    except (ConfigError, ValueError) as exc:
        ops, _ = OpsConfig(), errors.append(("monitoring", str(exc)))
    return jobs, ops, errors


def _environment() -> str:
    try:
        from diski9.backend.db.settings import BackendDatabaseSettings

        return BackendDatabaseSettings().environment
    except Exception:  # noqa: BLE001 - reported as unknown, never echoed
        return "unknown"


def _engine():
    from diski9.backend.db import make_app_engine

    return make_app_engine()


def _ago(now: datetime, then: datetime | None) -> str:
    if then is None:
        return "never"
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} min ago"
    return f"{minutes // 60} h ago" if minutes < 4320 else f"{minutes // 1440} d ago"


def _jobs_desc(jobs) -> str:
    if jobs is None:
        return "INVALID configuration"
    state = "enabled" if jobs.enabled else "disabled"
    if jobs.paused:
        state += f", paused ({jobs.pause_reason})"
    return (
        f"{state}; streams {', '.join(jobs.streams) or '(none)'}; provider calls "
        f"{'on' if jobs.provider_calls else 'off'}"
    )


def _gather(ops, jobs, environment):
    from diski9.backend.ops import collect, evaluate

    snap = collect(_engine(), environment=environment, finalise_warning=ops.finalise_warning)
    return snap, evaluate(snap, ops, jobs)


def _status(args) -> int:
    from diski9.backend.ops import Severity

    jobs, ops, errors = _configs()
    env = _environment()
    try:
        snap, findings = _gather(ops, jobs, env)
    except Exception as exc:  # noqa: BLE001 - never echo connection details
        print(f"database unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1
    counts = {s.label: sum(1 for f in findings if f.severity == s) for s in Severity}
    by_cat: dict[str, list] = {}
    for r in snap.rounds:
        by_cat.setdefault(r.category, []).append(r)
    if args.json:
        doc = {
            "now": snap.now,
            "environment": env,
            "database": {
                "server_version": snap.server_version,
                "schema": snap.schema_revision,
                "expected_schema": snap.expected_head,
                "query_ms": snap.query_ms,
            },
            "scheduler": {
                "configuration": _jobs_desc(jobs),
                "enabled": bool(jobs and jobs.enabled),
                "paused": bool(jobs and jobs.paused),
                "last_tick": snap.last_tick.as_dict() if snap.last_tick else None,
                "last_successful_tick": snap.last_ok_tick.as_dict() if snap.last_ok_tick else None,
                "heartbeat_age_seconds": (snap.now - snap.last_tick.started_at).total_seconds()
                if snap.last_tick
                else None,
            },
            "notifications": ops.describe_notifications(),
            "provider": {
                "requests_24h": snap.provider_day_requests,
                "cap_24h": jobs.max_requests_per_day if jobs else None,
                "cap_per_tick": jobs.max_requests_per_tick if jobs else None,
                "provider_calls": bool(jobs and jobs.provider_calls),
            },
            "rounds": {k: [r.as_dict() for r in v] for k, v in by_cat.items()},
            "recent_failures": [j.as_dict() for j in snap.failures],
            "running": [j.as_dict() for j in snap.running],
            "abandoned": [j.as_dict() for j in snap.abandoned],
            "integrity": {
                "official_anomalies": snap.official_anomalies,
                "final_without_results": snap.final_without_results,
            },
            "configuration_errors": [f"{w}: {e}" for w, e in errors],
            "checks": counts,
            "elapsed_ms": snap.elapsed_ms,
        }
        print(json.dumps(doc, indent=2, default=str))
        return 0
    now = snap.now
    print(f"Diski 9 operations - {now:%Y-%m-%d %H:%M} UTC (environment {env})")
    print(
        f"database: PostgreSQL {snap.server_version}, schema {snap.schema_revision} "
        f"(expected {snap.expected_head}), query {snap.query_ms} ms"
    )
    print(f"scheduler: {_jobs_desc(jobs)}")
    lt, ok = snap.last_tick, snap.last_ok_tick
    print(
        f"  last tick: {_ago(now, lt.started_at) if lt else 'never'}"
        f"{f' ({lt.outcome}, job {lt.id})' if lt else ''}; last successful tick: "
        f"{_ago(now, ok.started_at) if ok else 'never'}"
    )
    print(f"notifications: {ops.describe_notifications()}")
    cap = f"{jobs.max_requests_per_day}" if jobs else "?"
    print(
        f"provider: {snap.provider_day_requests}/{cap} scheduler requests in 24 h"
        f"{f' (cap {jobs.max_requests_per_tick}/tick)' if jobs else ''}"
    )
    print("rounds:")
    for key, label in CATEGORY_LABELS:
        rs = by_cat.get(key)
        if rs:
            listed = ", ".join(
                f"{r.code} ({r.stream}"
                + (f", {r.blocking_alerts} blocking" if r.blocking_alerts else "")
                + ")"
                for r in rs[:8]
            )
            more = f" and {len(rs) - 8} more" if len(rs) > 8 else ""
            print(f"  {label}: {listed}{more}")
    if not snap.rounds:
        print("  (no active rounds)")
    print(f"recent failures (24 h): {len(snap.failures)}")
    for j in snap.failures[:5]:
        print(f"  job {j.id} {j.job} {j.scope}: {j.error}")
    print(f"running steps: {len(snap.running)}; abandoned (24 h): {len(snap.abandoned)}")
    blocking = [r for r in snap.rounds if r.blocking_alerts]
    print(
        "blocking settlement alerts: "
        + (", ".join(f"{r.code} ({r.blocking_alerts})" for r in blocking) or "none")
    )
    integ = snap.official_anomalies + [
        f"final without results: {c}" for c in snap.final_without_results
    ]
    print("integrity (light): " + ("; ".join(integ) if integ else "no warnings"))
    for w, e in errors:
        print(f"configuration error ({w}): {e}")
    print(
        f"checks: {counts['CRITICAL']} critical, {counts['WARNING']} warning, "
        f"{counts['INFO']} info (details: diski9 ops check); {snap.elapsed_ms} ms"
    )
    return 0


def _check(args) -> int:
    from diski9.backend.ops import deep_findings, exit_code
    from diski9.backend.ops.checks import config_problem, database_unavailable

    jobs, ops, errors = _configs()
    env = _environment()
    findings = [config_problem(w, e) for w, e in errors]
    snap = None
    elapsed = {}
    try:
        snap, more = _gather(ops, jobs, env)
        findings += more
        elapsed["light_ms"] = snap.elapsed_ms
        if args.deep:
            deep, ms = deep_findings(_engine())
            findings += deep
            elapsed["deep_ms"] = ms
    except SQLAlchemyError as exc:
        findings += database_unavailable(f"database unavailable ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001 - settings errors never echo the URL
        findings += database_unavailable(f"database not reachable ({type(exc).__name__})")
    findings.sort(key=lambda f: (-int(f.severity), f.category, f.subject))
    deliveries = []
    if args.notify and snap is not None and not any(w == "monitoring" for w, _ in errors):
        from diski9.backend.ops.notify import notify

        try:
            deliveries = notify(_engine(), findings, ops, environment=env, now=snap.now)
        except SQLAlchemyError as exc:
            print(f"notification ledger unavailable ({type(exc).__name__})", file=sys.stderr)
    code = exit_code(findings)
    if args.json:
        print(
            json.dumps(
                {
                    "exit_code": code,
                    "findings": [f.as_dict() for f in findings],
                    "notifications": [d.__dict__ for d in deliveries],
                    **elapsed,
                },
                indent=2,
                default=str,
            )
        )
        return code
    for f in findings:
        print(f"{f.severity.label:<8} {f.category:<9} {f.code}: {f.message}")
    for d in deliveries:
        print(
            f"notification {d.state} {d.severity} {d.fingerprint}: "
            f"{'delivered' if d.delivered else 'NOT delivered - ' + d.detail}"
        )
    n = {s: sum(1 for f in findings if f.severity.label == s) for s in ("CRITICAL", "WARNING")}
    print(
        f"ops check: {n['CRITICAL']} critical, {n['WARNING']} warning; exit {code}"
        + "".join(f"; {k} {v}" for k, v in elapsed.items())
    )
    return code


def _jobs(args) -> int:
    from diski9.backend.ops.history import KNOWN_JOBS, recent_jobs

    if args.job and args.job not in KNOWN_JOBS:
        print(f"unknown job {args.job!r}; one of: {', '.join(KNOWN_JOBS)}", file=sys.stderr)
        return 2
    try:
        data = recent_jobs(
            _engine(),
            limit=args.limit,
            job=args.job,
            round_code=args.round_code,
            failed_only=args.failed,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"database unavailable ({type(exc).__name__})", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0
    for j in data["jobs"]:
        dur = (
            f"{(j['finished_at'] - j['started_at']).total_seconds():.1f}s"
            if j["finished_at"]
            else "running"
        )
        link = f" settlement run {j['settlement_run_id']}" if j["settlement_run_id"] else ""
        err = f" - {j['error']}" if j["error"] else ""
        print(
            f"{j['id']:>8} {j['started_at']:%Y-%m-%d %H:%M:%S} {dur:>8} {j['job']:<22} "
            f"{(j['scope'] or '-')[:36]:<36} {j['outcome']:<18} req {j['api_requests']}"
            f"{link}{err}"
        )
    if not data["jobs"]:
        print("no job runs match")
    for a in data["audit"]:
        print(
            f"audit {a['id']} {a['at']:%Y-%m-%d %H:%M:%S} {a['action']} by {a['actor_role']}"
            + (f" (job {a['job_run_id']})" if a["job_run_id"] else "")
        )
    return 0


def run(args: argparse.Namespace) -> int:
    return {"status": _status, "check": _check, "jobs": _jobs}[args.action](args)
