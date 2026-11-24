"""Installed build metadata and process startup identity (Scenario A3, Checkpoint 4C).

Reduced scope (owner decision D4). Three separate facts, never conflated:

1. **Installed build metadata** (``BUILD_INFO.json``). It is written once, at
   installation, by ``diski9 ops build-stamp``. The stamp records the commit only
   after checking that the checkout is exactly the approved commit and has no
   modified or untracked files. The installer then makes the file and the source
   read-only to the service user (``/opt/diski9`` is root-owned, and the units run
   with ``ProtectSystem=strict``).
2. **Process startup identity.** It is captured **once**, when a process starts:
   the metadata as read at that moment, its verification status, the process role,
   the PID and the start time. It is written as one structured line to standard
   error (journald for the systemd units). Scheduler ticks also store it in
   ``job_runs.args``; activation and cancellation store it in the audit log. It is
   never recomputed later, so a long-running process keeps reporting what it saw
   when it started.
3. **The current checkout** (``git``) is used only by the stamp command at
   installation. It is never presented as evidence of what a running process
   loaded.

The status is ``VERIFIED`` only when the metadata file is present and
well-formed, records a clean, verified stamp, and is not writable by the process
reading it. Anything else is ``UNVERIFIED`` with a reason. A development checkout
without a stamp is UNVERIFIED by design.

Deferred to Stage F3 (not implemented here): source digests, per-process records,
PID-reuse detection, process discovery, an ``ops processes`` command.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
FILE_NAME = "BUILD_INFO.json"
ENV_PATH = "DISKI9_BUILD_INFO"  # optional override of the metadata location
VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
_SHA = re.compile(r"^[0-9a-f]{40}$")
STARTUP_TAG = "DISKI9_STARTUP"


class BuildStampError(RuntimeError):
    """The checkout cannot be stamped (wrong commit, local changes, no git)."""


def default_path() -> Path:
    """``$DISKI9_BUILD_INFO``, else ``BUILD_INFO.json`` at the checkout root (the
    package is installed in editable mode from ``<root>/src/diski9``)."""
    env = os.environ.get(ENV_PATH, "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / FILE_NAME


@dataclass(frozen=True)
class BuildInfo:
    status: str  # VERIFIED or UNVERIFIED
    reason: str | None  # why UNVERIFIED (None when verified)
    commit: str | None
    installed_at: str | None
    path: str

    @property
    def verified(self) -> bool:
        return self.status == VERIFIED

    def label(self) -> str:
        if self.verified:
            return f"{self.commit} (VERIFIED, installed {self.installed_at})"
        shown = self.commit or "unknown"
        return f"{shown} (UNVERIFIED: {self.reason})"


def read_build_info(path: Path | None = None) -> BuildInfo:
    """Read and validate the installed metadata. Never raises: problems become an
    UNVERIFIED result with a reason."""
    p = Path(path) if path is not None else default_path()

    def bad(reason: str, commit: str | None = None, at: str | None = None) -> BuildInfo:
        return BuildInfo(UNVERIFIED, reason, commit, at, str(p))

    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return bad("no build metadata (not an installed release)")
    except OSError as exc:
        return bad(f"build metadata unreadable ({type(exc).__name__})")
    try:
        data = json.loads(raw)
    except ValueError:
        return bad("build metadata is not valid JSON")
    if not isinstance(data, dict):
        return bad("build metadata is malformed")
    commit = data.get("commit") if isinstance(data.get("commit"), str) else None
    at = data.get("installed_at") if isinstance(data.get("installed_at"), str) else None
    if data.get("schema") != SCHEMA:
        return bad("unsupported build metadata schema", commit, at)
    if commit is None or not _SHA.match(commit):
        return bad("build metadata has no valid commit", None, at)
    if data.get("clean") is not True or data.get("verified") is not True:
        return bad("build metadata does not record a clean, verified stamp", commit, at)
    if at is None or not _aware_iso(at):
        return bad("build metadata has no valid installation time", commit, None)
    if _writable_by_this_process(p):
        return bad("build metadata is writable by this process (not a protected install)",
                   commit, at)  # fmt: skip
    return BuildInfo(VERIFIED, None, commit, at, str(p))


def _writable_by_this_process(p: Path) -> bool:
    """True when this process could change the metadata (or replace it in its
    directory). Root can always write, so administrative commands are run as the
    service user, never as root (operations guide)."""
    return os.access(p, os.W_OK) or os.access(p.parent, os.W_OK)


def _aware_iso(s: str) -> bool:
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return False
    return d.tzinfo is not None


# ------------------------------------------------------------------ installation stamp
def _git(root: Path, *args: str) -> str:
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                             check=False, timeout=30)  # fmt: skip
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildStampError(f"git is not available ({type(exc).__name__})") from exc
    if res.returncode != 0:
        raise BuildStampError(f"git {' '.join(args)} failed: {res.stderr.strip()[:200]}")
    return res.stdout


def stamp_build(expected_commit: str, *, root: Path | None = None,
                output: Path | None = None, now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    """Write ``BUILD_INFO.json`` for the checkout at ``root``, only if HEAD is exactly
    ``expected_commit`` (full 40-character SHA) and ``git status --porcelain``
    reports nothing: no modified, staged or untracked files. The file is written
    with mode 0444 (the installer then makes it root-owned). Raises
    :class:`BuildStampError` and writes nothing otherwise."""
    expected = (expected_commit or "").strip().lower()
    if not _SHA.match(expected):
        raise BuildStampError("the approved commit must be a full 40-character SHA")
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    head = _git(root, "rev-parse", "HEAD").strip()
    if head != expected:
        raise BuildStampError(f"the checkout is at {head}, not the approved commit {expected}")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=normal").strip()
    if dirty:
        n = len(dirty.splitlines())
        raise BuildStampError(f"the checkout has {n} modified or untracked path(s); "
                              "install a clean copy of the approved commit")  # fmt: skip
    out = Path(output) if output is not None else root / FILE_NAME
    data = {"schema": SCHEMA, "commit": head, "clean": True, "verified": True,
            "installed_at": (now or datetime.now(UTC)).isoformat(),
            "verification": "git HEAD equals the approved commit; git status --porcelain empty"}  # fmt: skip
    if out.exists():
        out.chmod(0o644)  # replace an earlier stamp (it is read-only)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    tmp.chmod(0o444)
    tmp.replace(out)
    return data


# ------------------------------------------------------------------ startup identity
@dataclass(frozen=True)
class StartupIdentity:
    role: str
    pid: int
    started_at: str
    build_status: str
    build_commit: str | None
    build_reason: str | None
    build_installed_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_IDENTITY: StartupIdentity | None = None


def capture_startup(role: str, *, path: Path | None = None, stream=None,
                    log: bool = True) -> StartupIdentity:  # fmt: skip
    """Capture this process's identity once (later calls return the first capture,
    whatever their arguments) and write one structured startup line."""
    global _IDENTITY
    if _IDENTITY is not None and _IDENTITY.pid == os.getpid():
        return _IDENTITY
    info = read_build_info(path)
    ident = StartupIdentity(role=role, pid=os.getpid(),
                            started_at=datetime.now(UTC).isoformat(),
                            build_status=info.status, build_commit=info.commit,
                            build_reason=info.reason, build_installed_at=info.installed_at)  # fmt: skip
    _IDENTITY = ident
    if log:
        (stream or sys.stderr).write(f"{STARTUP_TAG} {json.dumps(ident.as_dict(), sort_keys=True)}\n")
        (stream or sys.stderr).flush()
    return ident


def current_identity() -> StartupIdentity | None:
    """The identity captured at this process's start, if any (a forked child that
    did not capture its own returns None)."""
    if _IDENTITY is not None and _IDENTITY.pid == os.getpid():
        return _IDENTITY
    return None


def identity_for_records(role: str) -> dict[str, Any]:
    """The startup identity for audit and job records, capturing it now if this
    process has not done so yet (one capture per process)."""
    return (current_identity() or capture_startup(role)).as_dict()


def _reset_for_tests() -> None:
    global _IDENTITY
    _IDENTITY = None
