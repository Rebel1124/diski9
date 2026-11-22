"""Guarded football-store restoration (Phase 6C.6 Stage F2, safeguard A).

**Live replacement is disabled in F2.** An exclusive SQLite lock proves only that no
connection held a lock at one instant: it does not prove that the web workers, the
scheduler timer, a manual command or any other process has closed its connection
and released its WAL/SHM state, and a timer could start a new consumer the moment
after the check. Proving that every consumer is stopped needs the host's service
manager, which F2 deliberately does not depend on (provider-neutral; no host). So
``--replace-live`` is refused outright, and the configured live store (and its
``-wal``/``-shm``/``-journal`` files) can never be a restore target.

What *is* available: restoring a verified backup into a **new, unused path**. The
live store is then switched by an explicit, offline configuration change with the
services stopped (``docs/operations_hosting.md``: stop units, confirm no process
holds the store, point ``DISKI9_DATABASE_URL`` at the restored file, verify, start).
The previous store and its WAL/SHM files stay exactly where they were, untouched,
so they remain available for recovery.

Rules enforced here:

* an explicit target path; it must not exist, nor any of its side files;
* the target must not be (or alias) the configured live store or its side files;
* the source must pass full verification (manifest checksum, integrity, version);
* the copy is written to a temporary file (``0600``), verified again, and linked
  into place with ``os.link`` (which never overwrites); then verified in place;
* nothing is ever deleted except this command's own temporary file.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .store import (
    FILE_MODE,
    BackupError,
    Verification,
    inspect_store,
    read_manifest,
    sha256_file,  # fmt: skip
    verify_backup,
)

SIDE_SUFFIXES = ("-wal", "-shm", "-journal")
LIVE_REPLACEMENT_DISABLED = (
    "live replacement is disabled in this version (Stage F2 safeguard A): an SQLite lock "
    "cannot prove that the web app, the scheduler and every other consumer have stopped. "
    "Restore into a new path, then follow the offline switch procedure in "
    "docs/operations_hosting.md (stop the services, confirm nothing holds the store, point "
    "DISKI9_DATABASE_URL at the restored file, verify, start). Nothing was changed."
)


class RestoreRefused(Exception):
    """A refused restore; the message is safe to print and nothing was changed."""


@dataclass(frozen=True)
class RestoreResult:
    target: Path
    sha256: str
    manifest_created_at: str | None
    seconds: float
    verification: Verification


def _real(p: Path) -> Path:
    return Path(os.path.realpath(p))


def _live_paths(live: Path | None) -> set[Path]:
    if live is None:
        return set()
    base = _real(live)
    return {base, *(base.with_name(base.name + s) for s in SIDE_SUFFIXES)}


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def check_target(target: Path, live: Path | None) -> None:
    """Refuse every unsafe target (raises :class:`RestoreRefused`)."""
    if not str(target):
        raise RestoreRefused("--to is required; there is no default target")
    if target.name.endswith(SIDE_SUFFIXES):
        raise RestoreRefused("the target cannot be an SQLite -wal, -shm or -journal file")
    real = _real(target)
    live_set = _live_paths(live)
    if real in live_set or (live is not None and _same_file(target, live)):
        raise RestoreRefused("the target is the configured live football store. "
                             + LIVE_REPLACEMENT_DISABLED)  # fmt: skip
    if target.exists() or target.is_symlink():
        raise RestoreRefused(f"{target.name} already exists: restore only into a new, unused "
                             "path (existing files are never overwritten). "
                             "Nothing was changed.")  # fmt: skip
    for s in SIDE_SUFFIXES:
        side = target.with_name(target.name + s)
        if side.exists():
            raise RestoreRefused(f"{side.name} exists next to the target (a store was in use "
                                 "there): choose a new, unused path. "
                                 "Nothing was changed.")  # fmt: skip
    if not real.parent.is_dir():
        raise RestoreRefused("the target folder does not exist. Nothing was changed.")


def restore_store(source: Path, target: Path, *, live: Path | None,
                  replace_live: bool = False) -> RestoreResult:  # fmt: skip
    """Restore the verified backup ``source`` into the new path ``target``."""
    if replace_live:
        raise RestoreRefused(LIVE_REPLACEMENT_DISABLED)
    check_target(target, live)
    if live is not None and (_real(source) in _live_paths(live) or _same_file(source, live)):
        raise RestoreRefused("the source is the live store itself; restore from a backup file")
    v = verify_backup(source)
    if not v.ok:
        raise RestoreRefused(f"the source failed verification ({'; '.join(v.problems)}). "
                             "Nothing was changed.")  # fmt: skip
    try:
        manifest = read_manifest(source)
    except BackupError as exc:
        raise RestoreRefused(str(exc)) from None
    t0 = time.monotonic()
    tmp = target.with_name(f".{target.name}.restore-tmp")
    if tmp.exists():
        raise RestoreRefused(f"{tmp.name} exists (an interrupted restore?); remove it after "
                             "checking it, then retry. Nothing was changed.")  # fmt: skip
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        with open(source, "rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
            dst.flush()
            os.fsync(dst.fileno())
        if sha256_file(tmp) != manifest["sha256"]:
            raise RestoreRefused("the copied file does not match the manifest checksum")
        check_target(target, live)  # re-check immediately before the switch
        os.link(tmp, target)  # never overwrites: fails if the target appeared meanwhile
    except FileExistsError:
        raise RestoreRefused(f"{target.name} appeared during the restore; nothing was "
                             "overwritten") from None  # fmt: skip
    finally:
        tmp.unlink(missing_ok=True)
    final = inspect_store(target)
    final.sha256, final.size = sha256_file(target), target.stat().st_size
    if not final.ok or final.sha256 != manifest["sha256"]:
        raise BackupError(f"{target.name} failed verification after the restore ("
                          f"{'; '.join(final.problems) or 'checksum'}); do not use it")  # fmt: skip
    return RestoreResult(target, final.sha256, manifest.get("created_at"),
                         round(time.monotonic() - t0, 3), final)  # fmt: skip
