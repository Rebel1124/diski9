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
``DISKI9_JOBS_PREPARE``                off       Stage E.1a: create the upcoming Beta draft
                                                 and evaluate its readiness (no provider
                                                 calls, never publishes)
``DISKI9_JOBS_PREPARE_STREAMS``        (none)    ``beta`` only (required when on)
``DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS``  78    draft created this long before the
                                                 publication target (6–78)
``DISKI9_JOBS_PREPARE_READINESS_MINUTES``  30    gap between readiness evaluations (5–240)
``DISKI9_JOBS_PREPARE_GRACE_HOURS``    6         after the target, before "target missed"
                                                 (1–24)
``DISKI9_JOBS_PREPARE_MIN_SECONDS``    60        least tick time that must remain before a
                                                 readiness evaluation starts (10–600); the
                                                 scheduler also uses twice the slowest
                                                 recent evaluation when that is larger
``DISKI9_JOBS_PROVIDER_MIN_INTERVAL_SECONDS`` 3  E.1b: least gap between scheduler provider
                                                 requests, across ticks (1–30)
``DISKI9_JOBS_PROVIDER_MAX_WAIT_SECONDS`` 30     E.1b: longest provider wait inside a tick
                                                 (5–60); longer requests defer instead
``DISKI9_JOBS_PREPARE_REFRESH``        off       E.1b: refresh fixtures and odds for the
                                                 upcoming week (needs PREPARE and
                                                 PROVIDER_CALLS)
``DISKI9_JOBS_PREPARE_REFRESH_DAILY``  04:15     Tue–Thu sweep time (UTC)
``DISKI9_JOBS_PREPARE_REFRESH_PUBLICATION`` 04:15,05:15  Friday sweeps before the target (UTC)
``DISKI9_JOBS_PREPARE_REFRESH_GRACE_MINUTES`` 60  grace sweep interval (15–240)
``DISKI9_JOBS_PREPARE_REFRESH_PARTIAL_AFTER_MINUTES`` 30  an unfinished sweep is closed
                                                 as partial this long after it began
                                                 (10–60)
``DISKI9_JOBS_NONESSENTIAL_REQUESTS_PER_DAY`` 300  preparation requests in 24 h (1–5000)
``DISKI9_JOBS_RESULTS_RESERVE``        150       24-hour requests preparation may never use
                                                 (50–5000)
``DISKI9_JOBS_PREPARE_PROVIDER_FLOOR`` 2000      least provider-reported daily remaining for
                                                 preparation (600–7000)
``DISKI9_JOBS_PROVIDER_EXPECTED_DAILY_LIMIT`` 7500  a lower reported limit stops preparation
``DISKI9_JOBS_PROVIDER_OBSERVATION_MAX_AGE_MINUTES`` 30  quota observations older than
                                                 this are not used (5–120)
=====================================  ========  ==========================================

**E.1b and the caps (owner decision D-1).** The per-tick and 24-hour defaults stay 10
and 100. With refresh on, the 24-hour cap must hold the preparation cap plus the
results reserve (300 + 150 by default), so refresh cannot be switched on without
explicitly configuring the approved activation values (20 per tick, 450 per 24 h).

``abandon_after`` must exceed the longest a live tick can run: the tick budget plus
one in-flight step (at most ``max_requests_per_tick × (retries + 1)`` provider
requests of ``timeout`` seconds, and database statements bounded by the statement
and lock timeouts) — about 8 minutes with the defaults.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time as dtime
from datetime import timedelta
from pathlib import Path

#: Streams the scheduler may ever process. ``official`` is deliberately absent and
#: cannot be added by configuration (D-38 activation is a separate, owner-approved
#: change of code, not of an environment variable).
AUTOMATABLE_STREAMS = frozenset({"development", "beta"})
#: Streams whose drafts the scheduler may create (Stage E.1a): Beta only. Development
#: rounds are opened with ``round dev-open``; Official stays disabled (D-38).
PREPARABLE_STREAMS = frozenset({"beta"})
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
    prepare: bool = False
    prepare_streams: tuple[str, ...] = ()
    prepare_create_lead: timedelta = timedelta(hours=78)
    prepare_readiness_interval: timedelta = timedelta(minutes=30)
    prepare_grace: timedelta = timedelta(hours=6)
    prepare_min_seconds: float = 60.0
    # Stage E.1b: provider safety (also used by results imports) and data refresh
    provider_min_interval: float = 3.0
    provider_max_wait: float = 30.0
    prepare_refresh: bool = False
    refresh_daily: tuple[dtime, ...] = (dtime(4, 15),)
    refresh_publication: tuple[dtime, ...] = (dtime(4, 15), dtime(5, 15))
    refresh_grace_interval: timedelta = timedelta(minutes=60)
    refresh_partial_after: timedelta = timedelta(minutes=30)
    nonessential_per_day: int = 300
    results_reserve: int = 150
    prepare_provider_floor: int = 2000
    provider_expected_daily_limit: int = 7500
    provider_observation_max_age: timedelta = timedelta(minutes=30)

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
        for s in self.prepare_streams:
            if s not in PREPARABLE_STREAMS:
                raise ConfigError(f"drafts cannot be prepared for the {s!r} stream (beta only)")
        if self.prepare and not self.enabled:
            raise ConfigError("DISKI9_JOBS_PREPARE needs DISKI9_JOBS_ENABLED")
        if self.prepare and not self.prepare_streams:
            raise ConfigError("DISKI9_JOBS_PREPARE_STREAMS must list beta")
        if not timedelta(hours=6) <= self.prepare_create_lead <= timedelta(hours=78):
            raise ConfigError("DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS must be between 6 and 78")
        if self.prepare and self.prepare_min_seconds >= self.tick_budget.total_seconds():
            raise ConfigError("DISKI9_JOBS_PREPARE_MIN_SECONDS must be less than the tick budget")
        if self.prepare_refresh:
            self._check_refresh()

    def worst_tick_seconds(self) -> float:
        """The longest a tick can run with provider work: the budget, then one step
        whose every attempt (at most the per-tick cap) times out after its paced
        slot, plus one bounded provider wait."""
        per_request = self.provider_timeout_seconds + self.provider_min_interval
        return (self.tick_budget.total_seconds() + self.max_requests_per_tick * per_request
                + self.provider_max_wait)  # fmt: skip

    def _check_refresh(self) -> None:
        if not self.prepare:
            raise ConfigError("DISKI9_JOBS_PREPARE_REFRESH needs DISKI9_JOBS_PREPARE")
        if not self.provider_calls:
            raise ConfigError("DISKI9_JOBS_PREPARE_REFRESH needs DISKI9_JOBS_PROVIDER_CALLS")
        need = self.nonessential_per_day + self.results_reserve
        if self.max_requests_per_day < need:
            raise ConfigError(
                f"DISKI9_JOBS_PREPARE_REFRESH needs DISKI9_JOBS_MAX_REQUESTS_PER_DAY of at "
                f"least {need} (the preparation cap {self.nonessential_per_day} plus the results "
                f"reserve {self.results_reserve}); the current {self.max_requests_per_day} is "
                "the pre-E.1b default. Set the owner-approved activation values explicitly "
                "(D-1)"
            )
        if self.worst_tick_seconds() >= self.abandon_after.total_seconds():
            raise ConfigError(
                "the longest possible tick with these provider settings "
                f"({self.worst_tick_seconds():.0f} s) must stay below "
                "DISKI9_JOBS_ABANDON_AFTER_MINUTES"
            )
        if not self.refresh_daily or not self.refresh_publication:
            raise ConfigError("the refresh schedule needs daily and publication times")


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


def _times(env: Mapping[str, str], name: str, default: str, most: int) -> tuple[dtime, ...]:
    raw = env.get(name, "").strip() or default
    out: list[dtime] = []
    for part in raw.split(","):
        part = part.strip()
        try:
            hh, mm = part.split(":")
            value = dtime(int(hh), int(mm))
        except ValueError:
            raise ConfigError(f"{name} must be HH:MM times (UTC), comma-separated") from None
        if value not in out:
            out.append(value)
    if not 1 <= len(out) <= most:
        raise ConfigError(f"{name} accepts 1 to {most} times")
    return tuple(sorted(out))


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


def _prepare_streams(env: Mapping[str, str]) -> tuple[str, ...]:
    out: list[str] = []
    for part in env.get("DISKI9_JOBS_PREPARE_STREAMS", "").split(","):
        s = part.strip().lower()
        if not s:
            continue
        if s not in PREPARABLE_STREAMS:
            raise ConfigError(
                f"DISKI9_JOBS_PREPARE_STREAMS accepts only beta, not {s!r} (development "
                "rounds use round dev-open; official stays disabled)"
            )
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
        prepare=_flag(env, "DISKI9_JOBS_PREPARE"),
        prepare_streams=_prepare_streams(env),
        prepare_create_lead=timedelta(
            hours=_int(env, "DISKI9_JOBS_PREPARE_CREATE_LEAD_HOURS", 78, 6, 78)
        ),
        prepare_readiness_interval=timedelta(
            minutes=_int(env, "DISKI9_JOBS_PREPARE_READINESS_MINUTES", 30, 5, 240)
        ),
        prepare_grace=timedelta(hours=_int(env, "DISKI9_JOBS_PREPARE_GRACE_HOURS", 6, 1, 24)),
        prepare_min_seconds=float(_int(env, "DISKI9_JOBS_PREPARE_MIN_SECONDS", 60, 10, 600)),
        provider_min_interval=float(
            _int(env, "DISKI9_JOBS_PROVIDER_MIN_INTERVAL_SECONDS", 3, 1, 30)
        ),
        provider_max_wait=float(_int(env, "DISKI9_JOBS_PROVIDER_MAX_WAIT_SECONDS", 30, 5, 60)),
        prepare_refresh=_flag(env, "DISKI9_JOBS_PREPARE_REFRESH"),
        refresh_daily=_times(env, "DISKI9_JOBS_PREPARE_REFRESH_DAILY", "04:15", 1),
        refresh_publication=_times(
            env, "DISKI9_JOBS_PREPARE_REFRESH_PUBLICATION", "04:15,05:15", 4
        ),
        refresh_grace_interval=timedelta(
            minutes=_int(env, "DISKI9_JOBS_PREPARE_REFRESH_GRACE_MINUTES", 60, 15, 240)
        ),
        refresh_partial_after=timedelta(
            minutes=_int(env, "DISKI9_JOBS_PREPARE_REFRESH_PARTIAL_AFTER_MINUTES", 30, 10, 60)
        ),
        nonessential_per_day=_int(env, "DISKI9_JOBS_NONESSENTIAL_REQUESTS_PER_DAY", 300, 1, 5000),
        results_reserve=_int(env, "DISKI9_JOBS_RESULTS_RESERVE", 150, 50, 5000),
        prepare_provider_floor=_floor(env),
        provider_expected_daily_limit=_int(
            env, "DISKI9_JOBS_PROVIDER_EXPECTED_DAILY_LIMIT", 7500, 100, 100000
        ),
        provider_observation_max_age=timedelta(
            minutes=_int(env, "DISKI9_JOBS_PROVIDER_OBSERVATION_MAX_AGE_MINUTES", 30, 5, 120)
        ),
    )


def _floor(env: Mapping[str, str]) -> int:
    floor = _int(env, "DISKI9_JOBS_PREPARE_PROVIDER_FLOOR", 2000, 600, 7000)
    try:
        reserve = int(env.get("DISKI9_API_FOOTBALL_DAILY_RESERVE", "").strip() or 500)
    except ValueError:
        reserve = 500  # the client's own settings report that error
    if floor <= reserve:
        raise ConfigError(
            "DISKI9_JOBS_PREPARE_PROVIDER_FLOOR must exceed the client daily reserve "
            "(DISKI9_API_FOOTBALL_DAILY_RESERVE), which stays protected for results"
        )
    return floor
