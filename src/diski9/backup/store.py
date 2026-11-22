"""Football-store (SQLite) online backup and verification (Phase 6C.6 Stage F2).

* :func:`backup_store` copies the live store with SQLite's online backup API from a
  **read-only** connection: one consistent snapshot, safe while the web app and the
  scheduler use the store (in WAL mode readers never block the writer). The copy is
  written to a temporary file (mode ``0600``), switched to a self-contained
  single-file journal mode, ``fsync``-ed, verified, and only then renamed into
  place next to a SHA-256 manifest. A copy that fails verification is deleted.
* :func:`verify_backup` re-checks a backup file against its manifest: checksum,
  size, ``PRAGMA integrity_check``, ``PRAGMA foreign_key_check``, the required
  tables, the store migration version and the recorded row counts.

Evidence levels (safeguard B): this module can establish only **local creation**
and **local verification**. It never handles encryption keys, never copies anything
off the host and never claims that an off-host copy exists or can be restored.

Manifests and messages contain file names only: never a directory outside the
backup folder, a database URL, a host name or a credential.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_SCHEMA = "diski9-store-backup/1"
NAME_RE = re.compile(r"^diski9-store-(\d{8}T\d{6}Z)\.sqlite$")
MANIFEST_SUFFIX = ".manifest.json"
FILE_MODE = 0o600


class BackupError(Exception):
    """A backup or verification failure, with a message safe to print."""


@dataclass
class Verification:
    ok: bool
    problems: list[str] = field(default_factory=list)
    tables: dict[str, int] = field(default_factory=dict)
    store_version: str | None = None
    sha256: str | None = None
    size: int | None = None

    def verdict(self, name: str) -> str:
        if self.ok:
            return (f"{name}: verified (sha256 {self.sha256[:16]}, store version "
                    f"{self.store_version}, {len(self.tables)} tables)")  # fmt: skip
        return f"{name}: NOT VERIFIED - " + "; ".join(self.problems)


@dataclass(frozen=True)
class BackupResult:
    file: Path
    manifest: Path
    sha256: str
    size: int
    seconds: float
    verification: Verification
    pruned: tuple[str, ...] = ()


def expected_tables() -> frozenset[str]:
    from diski9.db.schema import metadata

    return frozenset(metadata.tables) | {"alembic_version"}


def store_head() -> str:
    """The football store's migration head (``migrations/``)."""
    from alembic.script import ScriptDirectory

    from diski9.db.engine import alembic_config

    head = ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()
    if not head:
        raise BackupError("the football-store migration head cannot be determined")
    return head


def sqlite_path(url: str) -> Path:
    """The file behind a ``sqlite:///`` URL; refuses anything else."""
    if not url.startswith("sqlite:///") or url.startswith("sqlite:///:memory:"):
        raise BackupError("the football store is not a SQLite file (DISKI9_DATABASE_URL)")
    return Path(url.removeprefix("sqlite:///"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def inspect_store(path: Path) -> Verification:
    """Integrity, foreign keys, tables, version and row counts of a store file
    (opened read-only; never modified)."""
    v = Verification(ok=False)
    if not path.is_file():
        v.problems.append("file missing")
        return v
    try:
        con = _ro(path)
    except sqlite3.Error as exc:
        v.problems.append(f"cannot open ({type(exc).__name__})")
        return v
    try:
        integrity = [r[0] for r in con.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            v.problems.append(f"integrity_check failed ({len(integrity)} problem(s))")
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            v.problems.append(f"foreign_key_check found {len(fk)} violation(s)")
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(expected_tables() - names)
        if missing:
            v.problems.append(f"not a Diski 9 football store (missing {', '.join(missing[:4])})")
        else:
            row = con.execute("SELECT version_num FROM alembic_version").fetchone()
            v.store_version = row[0] if row else None
            head = store_head()
            if v.store_version != head:
                v.problems.append(f"store version {v.store_version}, expected {head}")
            for t in sorted(names & expected_tables()):
                v.tables[t] = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
    except sqlite3.DatabaseError as exc:
        v.problems.append(f"unreadable ({type(exc).__name__})")
    finally:
        con.close()
    v.ok = not v.problems
    return v


def _data_age(path: Path) -> dict[str, str | None]:
    con = _ro(path)
    try:
        return {
            "odds_fetches_newest_finished_at": con.execute(
                "SELECT max(finished_at) FROM odds_fetches").fetchone()[0],
            "ingestion_runs_newest_finished_at": con.execute(
                "SELECT max(finished_at) FROM ingestion_runs").fetchone()[0],
        }  # fmt: skip
    finally:
        con.close()


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("diski9")
    except Exception:  # noqa: BLE001
        return "unknown"


def _git_commit() -> str | None:
    from diski9.db.engine import PROJECT_ROOT

    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, timeout=3, check=False)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    c = out.stdout.strip()
    return c if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,40}", c) else None


def _fsync_dir(d: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def manifest_path(file: Path) -> Path:
    return file.with_name(file.name + MANIFEST_SUFFIX)


def read_manifest(file: Path) -> dict:
    mp = manifest_path(file)
    if not mp.is_file():
        raise BackupError(f"{file.name}: no manifest ({mp.name}); the checksum cannot be verified")
    try:
        m = json.loads(mp.read_text())
    except (OSError, ValueError):
        raise BackupError(f"{mp.name}: unreadable manifest") from None
    if m.get("schema") != MANIFEST_SCHEMA or m.get("file") != file.name:
        raise BackupError(f"{mp.name}: manifest does not describe {file.name}")
    return m


def verify_backup(file: Path) -> Verification:
    """Checksum and size against the manifest, then the full store inspection and
    the recorded row counts."""
    try:
        m = read_manifest(file)
    except BackupError as exc:
        return Verification(ok=False, problems=[str(exc)])
    if not file.is_file():
        return Verification(ok=False, problems=["file missing"])
    sha, size = sha256_file(file), file.stat().st_size
    problems = []
    if size != m.get("size_bytes"):
        problems.append("size does not match the manifest")
    if sha != m.get("sha256"):
        problems.append("SHA-256 does not match the manifest")
    v = inspect_store(file) if not problems else Verification(ok=False)
    v.problems = problems + v.problems
    if not problems and v.tables and m.get("tables") and v.tables != m["tables"]:
        v.problems.append("row counts differ from the manifest")
    v.sha256, v.size = sha, size
    v.ok = not v.problems
    return v


def _timestamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def backup_store(source: Path, out_dir: Path, *, keep: int = 14,
                 now: datetime | None = None) -> BackupResult:  # fmt: skip
    """Online backup of ``source`` into ``out_dir``. Raises :class:`BackupError`
    (after deleting the failed copy) when the copy cannot be verified."""
    import time

    if keep < 1:
        raise BackupError("--keep must be at least 1")
    if not source.is_file():
        raise BackupError("the football store file does not exist")
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if out_dir.resolve() == source.resolve().parent:
        raise BackupError("the backup folder must not be the store's own folder")
    now = now or datetime.now(UTC)
    name = f"diski9-store-{_timestamp(now)}.sqlite"
    final = out_dir / name
    if final.exists():
        raise BackupError(f"{name} already exists; nothing was overwritten")
    tmp = out_dir / f".{name}.tmp"
    t0 = time.monotonic()
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE))
    try:
        src = _ro(source)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)  # one step: a single consistent read snapshot
                dst.execute("PRAGMA journal_mode=DELETE")  # self-contained single file
                dst.commit()
            finally:
                dst.close()
        finally:
            src.close()
        fd = os.open(tmp, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        v = inspect_store(tmp)
        if not v.ok:
            raise BackupError("the copy failed verification: " + "; ".join(v.problems))
        sha, size = sha256_file(tmp), tmp.stat().st_size
        v.sha256, v.size = sha, size
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "created_at": now.astimezone(UTC).isoformat(timespec="seconds"),
            "file": name,
            "size_bytes": size,
            "sha256": sha,
            "store_version": v.store_version,
            "tables": v.tables,
            "data_age": _data_age(tmp),
            "app_version": _app_version(),
            "git_commit": _git_commit(),
            "evidence": {
                "local_created": True,
                "local_verified": True,
                "offhost_copy": "not recorded by this command",
                "offhost_restore_drill": "not recorded by this command",
            },
        }
        os.replace(tmp, final)
        _write_private(manifest_path(final), json.dumps(manifest, indent=2).encode())
        _fsync_dir(out_dir)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    pruned = prune(out_dir, keep)
    return BackupResult(final, manifest_path(final), sha, size,
                        round(time.monotonic() - t0, 3), v, tuple(pruned))  # fmt: skip


def prune(out_dir: Path, keep: int) -> list[str]:
    """Delete the oldest backups beyond ``keep`` (only files this command names)."""
    backups = sorted(p for p in out_dir.iterdir() if p.is_file() and NAME_RE.match(p.name))
    removed = []
    for p in backups[:-keep] if len(backups) > keep else []:
        p.unlink(missing_ok=True)
        manifest_path(p).unlink(missing_ok=True)
        removed.append(p.name)
    return removed
