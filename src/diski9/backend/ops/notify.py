"""One webhook notification channel (Stage D, decision Q-08), off by default.

De-duplication uses the existing ``job_runs`` table as the ledger (no migration):
each delivery attempt is a row with ``job = 'ops.notify'``, ``scope`` = the finding's
fingerprint and ``args`` = ``{state, severity, code, subject}`` (written once at
insert, as ``app.run_guard`` requires); ``status`` records delivery success or
failure. The latest row per fingerprint (indexed lookup on ``(job, scope,
started_at)``, bounded to 30 days) decides what to send:

* **new** — a WARNING/CRITICAL condition not notified before, or after it resolved;
* **ongoing** — still present and the re-notification interval has passed (4 h for
  CRITICAL, 24 h for WARNING by default), or it escalated to CRITICAL;
* **resolved** — notified as new/ongoing, now absent: sent once.

A failed delivery is recorded and retried after ``notify_retry``. Notifications are
a separate command (``ops check --notify``) from the lifecycle tick, so a delivery
problem can never block or alter competition processing. The webhook URL is a
secret: it is never printed, logged or stored; the payload contains only the
finding (no account, provider or credential data).
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import Engine, text

from ..db import transaction
from ..repositories import ops
from .checks import Finding, Severity
from .config import OpsConfig

JOB = "ops.notify"
LEDGER_WINDOW = timedelta(days=30)


@dataclass
class Delivery:
    fingerprint: str
    state: str  # new | ongoing | resolved
    severity: str
    delivered: bool
    detail: str = ""


def _latest(engine: Engine, now: datetime, fingerprints: list[str] | None) -> dict[str, dict]:
    """Latest ledger row per fingerprint and its latest successful delivery."""
    sql = (
        "SELECT DISTINCT ON (scope) scope, status, started_at, args FROM app.job_runs "
        "WHERE job = :job AND started_at >= :since {extra} ORDER BY scope, started_at DESC"
    )
    params = {"job": JOB, "since": now - LEDGER_WINDOW}
    out: dict[str, dict] = {}
    with transaction(engine) as conn:
        for kind, cond in (("last", ""), ("ok", "AND status = 'succeeded'")):
            stmt = text(sql.format(extra=cond))
            for r in conn.execute(stmt, params):
                out.setdefault(r.scope, {})[kind] = r
    if fingerprints is not None:
        out = {k: v for k, v in out.items() if k in fingerprints or _open(v)}
    return out


def _open(entry: dict) -> bool:
    ok = entry.get("ok")
    return bool(ok and ok.args.get("state") in ("new", "ongoing"))


def plan(
    findings: list[Finding], cfg: OpsConfig, ledger: dict[str, dict], now: datetime
) -> list[tuple[str, str, Finding | None, dict]]:
    """``(fingerprint, state, finding or None, previous args)`` to send now."""
    floor = Severity.CRITICAL if cfg.notify_min_severity == "critical" else Severity.WARNING
    current = {f.fingerprint: f for f in findings if f.severity >= floor}
    todo = []
    for fp, f in current.items():
        entry = ledger.get(fp, {})
        last, ok = entry.get("last"), entry.get("ok")
        if (
            last is not None
            and last.status != "succeeded"
            and now - last.started_at < cfg.notify_retry
        ):
            continue  # a recent delivery failed: wait before retrying
        if ok is None or ok.args.get("state") == "resolved":
            todo.append((fp, "new", f, {}))
            continue
        escalated = ok.args.get("severity") == "WARNING" and f.severity == Severity.CRITICAL
        every = cfg.renotify_critical if f.severity == Severity.CRITICAL else cfg.renotify_warning
        if escalated or now - ok.started_at >= every:
            todo.append((fp, "ongoing", f, dict(ok.args)))
    for fp, entry in ledger.items():
        if fp in current or not _open(entry):
            continue
        last = entry.get("last")
        if (
            last is not None
            and last.status != "succeeded"
            and last.args.get("state") == "resolved"
            and now - last.started_at < cfg.notify_retry
        ):
            continue
        todo.append((fp, "resolved", None, dict(entry["ok"].args)))
    return todo


def _payload(fp: str, state: str, f: Finding | None, prev: dict, environment: str, now) -> dict:
    base = (
        f.as_dict()
        if f is not None
        else {
            "severity": prev.get("severity"),
            "code": prev.get("code"),
            "subject": prev.get("subject"),
            "category": prev.get("category"),
            "message": "the condition is no longer present",
            "fingerprint": fp,
        }
    )
    return {
        "source": "diski9-ops",
        "environment": environment,
        "state": state,
        "detected_at": now.isoformat(),
        **base,
    }


def notify(
    engine: Engine,
    findings: list[Finding],
    cfg: OpsConfig,
    *,
    environment: str,
    now: datetime,
    transport: httpx.BaseTransport | None = None,
    post: Callable[[str, dict], int] | None = None,
) -> list[Delivery]:
    """Send what :func:`plan` decides and record every attempt. Never raises for a
    delivery problem (it is recorded); returns the attempts made."""
    if not cfg.notifications_active:
        return []
    fps = [f.fingerprint for f in findings]
    todo = plan(findings, cfg, _latest(engine, now, fps), now)
    if not todo:
        return []
    host = socket.gethostname()
    client = None if post else httpx.Client(timeout=5.0, transport=transport)
    results = []
    try:
        for fp, state, f, prev in todo:
            payload = _payload(fp, state, f, prev, environment, now)
            args = {
                "state": state,
                "severity": payload["severity"],
                "code": payload["code"],
                "subject": payload["subject"],
                "category": payload.get("category"),
            }
            with transaction(engine) as conn:
                run = ops.start_job(conn, JOB, fp, args, host)
            try:
                if post is not None:
                    code = post(cfg.webhook_url, payload)
                else:
                    code = client.post(
                        cfg.webhook_url, json=payload, headers={"User-Agent": "diski9-ops"}
                    ).status_code
                ok = 200 <= code < 300
                detail = "" if ok else f"webhook answered HTTP {code}"
            except Exception as exc:  # noqa: BLE001 - recorded, never propagated
                ok, detail = False, f"delivery failed ({type(exc).__name__})"
            with transaction(engine) as conn:
                ops.finish_job(
                    conn, run, "succeeded" if ok else "failed", error=None if ok else detail
                )
            results.append(Delivery(fp, state, str(payload["severity"]), ok, detail))
    finally:
        if client is not None:
            client.close()
    return results


__all__ = ["Delivery", "JOB", "notify", "plan"]
