"""Scheduled competition lifecycle (Phase 6C.6 Stage C): a database-driven
reconciler run by an external cron-style trigger (``diski9 jobs tick``).

Publication is supervised and deliberately absent: the reconciler never creates or
publishes a round. It only locks, imports results, settles and finalises, through
the existing services, as the explicit ``SYSTEM`` actor.
"""

from .config import AUTOMATABLE_STREAMS, ConfigError, SchedulerConfig, load_config
from .reconciler import Outcome, StepReport, TickReport, plan_tick, tick

__all__ = [
    "AUTOMATABLE_STREAMS",
    "ConfigError",
    "Outcome",
    "SchedulerConfig",
    "StepReport",
    "TickReport",
    "load_config",
    "plan_tick",
    "tick",
]
