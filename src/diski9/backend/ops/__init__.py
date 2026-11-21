"""Operational monitoring, health checks, alerts and history (Phase 6C.6 Stage D).

Read-only over the competition database (the notification ledger is the only
write, to ``job_runs``); reuses the scheduler's records, the audit log, the
settlement alerts and the championship integrity inspection.
"""

from .checks import Finding, Severity, deep_findings, evaluate, exit_code
from .config import OpsConfig, load_ops_config
from .snapshot import Snapshot, collect

__all__ = [
    "Finding",
    "OpsConfig",
    "Severity",
    "Snapshot",
    "collect",
    "deep_findings",
    "evaluate",
    "exit_code",
    "load_ops_config",
]
