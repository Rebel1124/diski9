"""Monitoring thresholds and notification settings (Phase 6C.6 Stage D).

Thresholds are measured from the competition's own times (deadline, settlement
cutoff, S-02 earliest finalisation) — never alternative deadlines. Notification is
**off** unless ``DISKI9_OPS_NOTIFY`` is on *and* a webhook URL is configured; the URL
is treated as a secret and never printed. Invalid values fail closed
(:class:`ConfigError`).

==========================================  =======  ==========================================
Variable                                    Default  Meaning
==========================================  =======  ==========================================
``DISKI9_OPS_TICK_INTERVAL_MINUTES``        5        how often the trigger runs ``jobs tick``
``DISKI9_OPS_HEARTBEAT_WARNING_MINUTES``    15       no tick for this long (automation on): WARNING
``DISKI9_OPS_HEARTBEAT_CRITICAL_MINUTES``   60       ... CRITICAL
``DISKI9_OPS_LOCK_WARNING_MINUTES``         15       open round past its deadline: WARNING
``DISKI9_OPS_LOCK_CRITICAL_MINUTES``        60       ... CRITICAL
``DISKI9_OPS_SETTLE_WARNING_HOURS``         6        no settlement run since the cutoff: WARNING
``DISKI9_OPS_SETTLE_CRITICAL_HOURS``        24       ... CRITICAL
``DISKI9_OPS_FINALISE_WARNING_HOURS``       6        eligible (S-02) but not final: WARNING
``DISKI9_OPS_FINALISE_CRITICAL_HOURS``      24       ... (or blocked beyond eligibility): CRITICAL
``DISKI9_OPS_RESULTS_STALE_HOURS``          3        matches in play, no results import: WARNING
``DISKI9_OPS_STEP_FAILURES_WARNING``        3        consecutive failures of a step: WARNING
``DISKI9_OPS_STEP_FAILURES_CRITICAL``       6        ... CRITICAL
``DISKI9_OPS_STUCK_MINUTES``                30       a step still ``running`` after this: WARNING
``DISKI9_OPS_BUDGET_WARNING_PERCENT``       80       24-hour provider use at this share: WARNING
``DISKI9_OPS_NOTIFY``                       off      send notifications (``ops check --notify``)
``DISKI9_OPS_WEBHOOK_URL``                  (none)   https endpoint (secret; never printed)
``DISKI9_OPS_NOTIFY_MIN_SEVERITY``          warning  ``warning`` or ``critical``
``DISKI9_OPS_RENOTIFY_WARNING_HOURS``       24       repeat an ongoing WARNING after this
``DISKI9_OPS_RENOTIFY_CRITICAL_HOURS``      4        repeat an ongoing CRITICAL after this
``DISKI9_OPS_NOTIFY_RETRY_MINUTES``         15       retry a failed delivery after this
==========================================  =======  ==========================================
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from ..jobs.config import ConfigError, _flag, _int

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class OpsConfig:
    tick_interval: timedelta = timedelta(minutes=5)
    heartbeat_warning: timedelta = timedelta(minutes=15)
    heartbeat_critical: timedelta = timedelta(minutes=60)
    lock_warning: timedelta = timedelta(minutes=15)
    lock_critical: timedelta = timedelta(minutes=60)
    settle_warning: timedelta = timedelta(hours=6)
    settle_critical: timedelta = timedelta(hours=24)
    finalise_warning: timedelta = timedelta(hours=6)
    finalise_critical: timedelta = timedelta(hours=24)
    results_stale: timedelta = timedelta(hours=3)
    step_failures_warning: int = 3
    step_failures_critical: int = 6
    stuck: timedelta = timedelta(minutes=30)
    budget_warning_percent: int = 80
    notify: bool = False
    webhook_url: str | None = None  # secret: never printed or logged
    notify_min_severity: str = "warning"
    renotify_warning: timedelta = timedelta(hours=24)
    renotify_critical: timedelta = timedelta(hours=4)
    notify_retry: timedelta = timedelta(minutes=15)

    @property
    def notifications_active(self) -> bool:
        return self.notify and bool(self.webhook_url)

    def describe_notifications(self) -> str:
        if not self.notify:
            return "notifications off"
        if not self.webhook_url:
            return "notifications on but no webhook configured (nothing is sent)"
        return f"notifications on (webhook configured, minimum {self.notify_min_severity})"

    def __repr__(self) -> str:  # never expose the webhook URL
        return f"OpsConfig({self.describe_notifications()})"


def _check_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host:
        return url
    if parts.scheme == "http" and host in LOOPBACK:
        return url  # local test servers only
    raise ConfigError("DISKI9_OPS_WEBHOOK_URL must be an https URL (http only for localhost)")


def load_ops_config(env: Mapping[str, str] | None = None) -> OpsConfig:
    env = os.environ if env is None else env

    def minutes(name, default, lo=1, hi=10080):
        return timedelta(minutes=_int(env, f"DISKI9_OPS_{name}_MINUTES", default, lo, hi))

    def hours(name, default, lo=1, hi=720):
        return timedelta(hours=_int(env, f"DISKI9_OPS_{name}_HOURS", default, lo, hi))

    cfg = OpsConfig(
        tick_interval=minutes("TICK_INTERVAL", 5, 1, 60),
        heartbeat_warning=minutes("HEARTBEAT_WARNING", 15),
        heartbeat_critical=minutes("HEARTBEAT_CRITICAL", 60),
        lock_warning=minutes("LOCK_WARNING", 15),
        lock_critical=minutes("LOCK_CRITICAL", 60),
        settle_warning=hours("SETTLE_WARNING", 6),
        settle_critical=hours("SETTLE_CRITICAL", 24),
        finalise_warning=hours("FINALISE_WARNING", 6),
        finalise_critical=hours("FINALISE_CRITICAL", 24),
        results_stale=hours("RESULTS_STALE", 3),
        step_failures_warning=_int(env, "DISKI9_OPS_STEP_FAILURES_WARNING", 3, 1, 100),
        step_failures_critical=_int(env, "DISKI9_OPS_STEP_FAILURES_CRITICAL", 6, 1, 100),
        stuck=minutes("STUCK", 30),
        budget_warning_percent=_int(env, "DISKI9_OPS_BUDGET_WARNING_PERCENT", 80, 1, 100),
        notify=_flag(env, "DISKI9_OPS_NOTIFY"),
        webhook_url=_check_url(u) if (u := env.get("DISKI9_OPS_WEBHOOK_URL", "").strip()) else None,
        notify_min_severity=env.get("DISKI9_OPS_NOTIFY_MIN_SEVERITY", "warning").strip().lower()
        or "warning",
        renotify_warning=hours("RENOTIFY_WARNING", 24),
        renotify_critical=hours("RENOTIFY_CRITICAL", 4),
        notify_retry=minutes("NOTIFY_RETRY", 15),
    )
    if cfg.notify_min_severity not in ("warning", "critical"):
        raise ConfigError("DISKI9_OPS_NOTIFY_MIN_SEVERITY must be warning or critical")
    for w, c, name in (
        (cfg.heartbeat_warning, cfg.heartbeat_critical, "HEARTBEAT"),
        (cfg.lock_warning, cfg.lock_critical, "LOCK"),
        (cfg.settle_warning, cfg.settle_critical, "SETTLE"),
        (cfg.finalise_warning, cfg.finalise_critical, "FINALISE"),
        (cfg.step_failures_warning, cfg.step_failures_critical, "STEP_FAILURES"),
    ):
        if c < w:
            raise ConfigError(f"DISKI9_OPS_{name} critical threshold must be at least the warning")
    return cfg


__all__ = ["LOOPBACK", "ConfigError", "OpsConfig", "load_ops_config"]
