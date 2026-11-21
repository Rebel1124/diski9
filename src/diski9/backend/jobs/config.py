"""Scheduler configuration from the environment (owner decision Q-06, Stage C).

Fail closed: automation is **off** unless ``DISKI9_JOBS_ENABLED`` is true, it needs
an explicit stream allowlist, any invalid value is a :class:`ConfigError` (the tick
does nothing), and the Official stream can never be listed — there is no setting
that makes it automatable. Provider calls are a separate switch, off by default.

=====================================  ========  ==========================================
Variable                               Default   Meaning
=====================================  ========  ==========================================
``DISKI9_JOBS_ENABLED``                off       master switch for unattended processing
``DISKI9_JOBS_STREAMS``                (none)    comma list from ``development``, ``beta``
``DISKI9_JOBS_PAUSED``                 off       emergency pause (a tick records and stops)
``DISKI9_JOBS_PAUSE_FILE``             (none)    pause while this file exists
``DISKI9_JOBS_PROVIDER_CALLS``         off       allow results import from the provider
``DISKI9_JOBS_MAX_REQUESTS_PER_TICK``  10        provider requests per tick (1–100)
``DISKI9_JOBS_MAX_REQUESTS_PER_DAY``   100       scheduler provider requests per 24 h (1–5000)
``DISKI9_JOBS_RESULTS_REFRESH_MINUTES``  60      minimum gap between imports per round (5–1440)
``DISKI9_JOBS_SETTLE_REFRESH_MINUTES``   60      gap between routine settlement runs (5–1440)
``DISKI9_JOBS_RETRY_BASE_MINUTES``     15        first back-off after a failure (1–1440)
``DISKI9_JOBS_RETRY_MAX_MINUTES``      240       longest back-off (1–10080)
``DISKI9_JOBS_TICK_BUDGET_SECONDS``    240       no new step starts after this (30–900)
``DISKI9_JOBS_ABANDON_AFTER_MINUTES``  20        a lost tick's steps count as abandoned
                                                 only after this (10–1440)
``DISKI9_JOBS_PROVIDER_TIMEOUT_SECONDS`` 10      scheduler provider request timeout (1–30)
``DISKI9_JOBS_PROVIDER_MAX_RETRIES``   1         scheduler provider retries (0–3)
``DISKI9_JOBS_DATABASE_URL``           (none)    direct or session-mode URL for the tick
                                                 lock (secret); default: the app URL
``DISKI9_JOBS_DATABASE_MODE``          direct    ``direct`` or ``session``
=====================================  ========  ==========================================

``abandon_after`` must exceed the longest a live tick can run: the tick budget plus
one in-flight step (at most ``max_requests_per_tick × (retries + 1)`` provider
requests of ``timeout`` seconds, and database statements bounded by the statement
and lock timeouts) — about 8 minutes with the defaults.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

#: Streams the scheduler may ever process. ``official`` is deliberately absent and
#: cannot be added by configuration (D-38 activation is a separate, owner-approved
#: change of code, not of an environment variable).
AUTOMATABLE_STREAMS = frozenset({"development", "beta"})
KNOWN_STREAMS = frozenset({"development", "beta", "official"})

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"", "0", "false", "no", "off"})


class ConfigError(ValueError):
    """Missing or invalid scheduler configuration: the tick must not run."""


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool = False
    streams: tuple[str, ...] = ()
    paused: bool = False
    pause_reason: str | None = None
    provider_calls: bool = False
    max_requests_per_tick: int = 10
    max_requests_per_day: int = 100
    results_refresh: timedelta = timedelta(minutes=60)
    settle_refresh: timedelta = timedelta(minutes=60)
    retry_base: timedelta = timedelta(minutes=15)
    retry_max: timedelta = timedelta(minutes=240)
    environment: str = "development"
    notes: tuple[str, ...] = field(default=())
    tick_budget: timedelta = timedelta(seconds=240)
    abandon_after: timedelta = timedelta(minutes=20)
    provider_timeout_seconds: float = 10.0
    provider_max_retries: int = 1

    def __post_init__(self) -> None:
        # a second line of defence for configurations built in code (tests, tools)
        for s in self.streams:
            if s not in AUTOMATABLE_STREAMS:
                raise ConfigError(f"stream {s!r} cannot be automated")
        if self.enabled and not self.streams:
            raise ConfigError("DISKI9_JOBS_STREAMS must list the streams to automate")
        if self.environment == "production" and "development" in self.streams:
            raise ConfigError("the development stream cannot be automated in production")
        if self.abandon_after <= self.tick_budget:
            raise ConfigError("DISKI9_JOBS_ABANDON_AFTER_MINUTES must exceed the tick budget")


def _flag(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ConfigError(f"{name} must be on/off (true/false, 1/0)")


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}")
    return value


def _streams(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = env.get("DISKI9_JOBS_STREAMS", "")
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip().lower()
        if not s:
            continue
        if s == "official":
            raise ConfigError(
                "the official stream cannot be automated (it stays disabled until a "
                "separately approved activation)"
            )
        if s not in KNOWN_STREAMS:
            raise ConfigError(f"unknown stream {s!r} in DISKI9_JOBS_STREAMS")
        if s not in out:
            out.append(s)
    return tuple(out)


def load_config(
    env: Mapping[str, str] | None = None, *, environment: str | None = None
) -> SchedulerConfig:
    """Read and validate the scheduler settings; raises :class:`ConfigError`."""
    env = os.environ if env is None else env
    if environment is None:
        from ..db.settings import BackendDatabaseSettings

        environment = BackendDatabaseSettings().environment
    enabled = _flag(env, "DISKI9_JOBS_ENABLED")
    streams = _streams(env)
    paused, reason = False, None
    if _flag(env, "DISKI9_JOBS_PAUSED"):
        paused, reason = True, "DISKI9_JOBS_PAUSED is set"
    pause_file = env.get("DISKI9_JOBS_PAUSE_FILE", "").strip()
    if pause_file and Path(pause_file).exists():
        paused, reason = True, "the pause file exists"
    retry_base = _int(env, "DISKI9_JOBS_RETRY_BASE_MINUTES", 15, 1, 1440)
    retry_max = _int(env, "DISKI9_JOBS_RETRY_MAX_MINUTES", 240, 1, 10080)
    if retry_max < retry_base:
        raise ConfigError("DISKI9_JOBS_RETRY_MAX_MINUTES must be at least the base back-off")
    per_tick = _int(env, "DISKI9_JOBS_MAX_REQUESTS_PER_TICK", 10, 1, 100)
    per_day = _int(env, "DISKI9_JOBS_MAX_REQUESTS_PER_DAY", 100, 1, 5000)
    if per_day < per_tick:
        raise ConfigError("DISKI9_JOBS_MAX_REQUESTS_PER_DAY must be at least the per-tick cap")
    return SchedulerConfig(
        enabled=enabled,
        streams=streams,
        paused=paused,
        pause_reason=reason,
        provider_calls=_flag(env, "DISKI9_JOBS_PROVIDER_CALLS"),
        max_requests_per_tick=per_tick,
        max_requests_per_day=per_day,
        results_refresh=timedelta(
            minutes=_int(env, "DISKI9_JOBS_RESULTS_REFRESH_MINUTES", 60, 5, 1440)
        ),
        settle_refresh=timedelta(
            minutes=_int(env, "DISKI9_JOBS_SETTLE_REFRESH_MINUTES", 60, 5, 1440)
        ),
        retry_base=timedelta(minutes=retry_base),
        retry_max=timedelta(minutes=retry_max),
        environment=environment,
        tick_budget=timedelta(seconds=_int(env, "DISKI9_JOBS_TICK_BUDGET_SECONDS", 240, 30, 900)),
        abandon_after=timedelta(
            minutes=_int(env, "DISKI9_JOBS_ABANDON_AFTER_MINUTES", 20, 10, 1440)
        ),
        provider_timeout_seconds=float(
            _int(env, "DISKI9_JOBS_PROVIDER_TIMEOUT_SECONDS", 10, 1, 30)
        ),
        provider_max_retries=_int(env, "DISKI9_JOBS_PROVIDER_MAX_RETRIES", 1, 0, 3),
    )
