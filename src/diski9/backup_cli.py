"""``diski9 backup`` and ``diski9 restore`` (Phase 6C.6 Stage F2).

* ``backup store --out DIR [--keep N]`` — online backup of the football store,
  verified and checksummed (evidence levels 1 and 2).
* ``backup verify FILE`` — re-check a backup against its manifest.
* ``backup record --kind KIND --file FILE`` — record evidence the application cannot
  produce itself: ``postgres`` (a ``pg_dump`` file: header and checksum checked),
  ``offhost-copy`` (reported by the host's copy hook; level 3, not verified here),
  ``postgres-drill`` (a completed PostgreSQL restore drill; operator-declared),
  ``postgres-restore`` (the competition database was restored: places the provider
  hold of safeguard D).
* ``restore store --from FILE --to NEW_PATH --purpose recovery|drill`` — guarded
  restore into a new, unused path; live replacement is disabled (safeguard A).

Output and records contain file names only: never a URL, path outside the backup
folder, host name or credential. Exit codes: 0 success, 1 verification failure or
unrecorded evidence, 2 refused or invalid usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PG_MANIFEST_SCHEMA = "diski9-postgres-backup/1"


def add_parsers(sub) -> None:
    s = sub.add_parser("backup", help="football-store backups and backup/restore evidence")
    b = s.add_subparsers(dest="action", required=True)
    p = b.add_parser("store", help="online backup of the football store (verified, checksummed)")
    p.add_argument("--out", required=True, help="backup folder (created 0700 if missing)")
    p.add_argument("--keep", type=int, default=14, help="backups to keep (default 14)")
    p = b.add_parser("verify", help="verify a backup file against its manifest")
    p.add_argument("file")
    p = b.add_parser("record", help="record backup or restore evidence in the competition DB")
    p.add_argument(
        "--kind",
        required=True,
        choices=["postgres", "offhost-copy", "postgres-drill", "postgres-restore"],
    )
    p.add_argument("--file", required=True, help="the backup or dump file concerned")
    p.add_argument(
        "--label",
        default=None,
        help="offhost-copy: a short destination nickname (no URLs or paths)",
    )
    p.add_argument(
        "--source-origin",
        choices=["local", "offhost"],
        default="local",
        help="postgres-drill: where the restored dump came from (declared)",
    )

    s = sub.add_parser("restore", help="guarded football-store restore into a new path")
    r = s.add_subparsers(dest="action", required=True)
    p = r.add_parser("store", help="restore a verified backup into a NEW, unused path")
    p.add_argument("--from", dest="source", required=True, help="backup file (with manifest)")
    p.add_argument("--to", dest="target", required=True, help="new, unused target path")
    p.add_argument(
        "--purpose",
        required=True,
        choices=["recovery", "drill"],
        help="recovery: the restored store is meant to become live (data refresh "
        "sweeps before it stop counting as current); drill: a test restore",
    )
    p.add_argument(
        "--source-origin",
        choices=["local", "offhost"],
        default="local",
        help="where the backup file came from (declared; recorded as such)",
    )
    p.add_argument(
        "--replace-live",
        action="store_true",
        help="refused in this version (safeguard A); see docs/operations_hosting.md",
    )


def _live_store(args) -> Path | None:
    from diski9.backup.store import BackupError, sqlite_path
    from diski9.config import get_settings

    url = getattr(args, "database_url", None) or get_settings().database_url
    try:
        return sqlite_path(url)
    except BackupError:
        return None


def _competition_engine():
    """The competition database, or ``None`` when it is not configured."""
    from diski9.backend.db.settings import BackendDatabaseSettings

    if BackendDatabaseSettings().database_url is None:
        return None
    from diski9.backend.db import make_app_engine

    return make_app_engine()


def _record(job: str, args_: dict, *, ok: bool = True, detail: str | None = None,
            required: bool = False) -> int:  # fmt: skip
    """Record one evidence row; returns an exit-code contribution (0 or 1/2)."""
    from sqlalchemy.exc import SQLAlchemyError

    from diski9.backend.db import transaction
    from diski9.backup import records

    try:
        engine = _competition_engine()
    except Exception as exc:  # noqa: BLE001 - invalid settings: never echo the URL
        print(f"not recorded: competition database settings are invalid ({type(exc).__name__})",
              file=sys.stderr)  # fmt: skip
        return 1
    if engine is None:
        msg = "not recorded: no competition database is configured (DISKI9_APP_DATABASE_URL)"
        print(msg, file=sys.stderr)
        return 2 if required else 0
    try:
        with transaction(engine) as conn:
            rid = records.record(conn, job, args_, ok=ok, detail=detail)
    except SQLAlchemyError as exc:
        print(f"NOT RECORDED: the competition database is unavailable ({type(exc).__name__}); "
              "monitoring will not see this event", file=sys.stderr)  # fmt: skip
        return 1
    print(f"recorded as {job} (job run {rid})")
    return 0


def _backup_store(args) -> int:
    from diski9.backup import records
    from diski9.backup.store import BackupError, backup_store

    live = _live_store(args)
    if live is None:
        print("backup store: the football store is not a SQLite file; nothing was done",
              file=sys.stderr)  # fmt: skip
        return 2
    try:
        res = backup_store(live, Path(args.out), keep=args.keep)
    except BackupError as exc:
        print(f"backup store: FAILED - {exc}. The failed copy was deleted.", file=sys.stderr)
        _record(records.BACKUP_STORE, {"verified": False, "created": False}, ok=False,
                detail=str(exc)[:300])  # fmt: skip
        return 1
    v = res.verification
    print(f"backup store: created {res.file.name} ({res.size / 1e6:.1f} MB) in {res.seconds:.2f} s")
    print(f"backup store: {v.verdict(res.file.name)}")
    print(f"backup store: manifest {res.manifest.name}")
    if res.pruned:
        print(f"backup store: pruned {len(res.pruned)} older backup(s)")
    print("backup store: evidence - local copy created: yes; locally verified: yes; "
          "off-host copy: NOT established by this command")  # fmt: skip
    return _record(records.BACKUP_STORE, {
        "file": res.file.name, "size_bytes": res.size, "sha256_prefix": res.sha256[:16],
        "store_version": v.store_version, "tables": v.tables, "created": True,
        "verified": True, "seconds": res.seconds,
    })  # fmt: skip


def _verify(args) -> int:
    from diski9.backup.store import verify_backup

    f = Path(args.file)
    v = verify_backup(f)
    print(v.verdict(f.name))
    return 0 if v.ok else 1


def _write_pg_manifest(dump: Path, sha: str, size: int) -> None:
    from diski9.backup.store import _write_private, manifest_path

    mp = manifest_path(dump)
    if mp.exists():
        try:
            old = json.loads(mp.read_text())
        except (OSError, ValueError):
            old = {}
        if old.get("sha256") != sha:
            raise ValueError(f"{mp.name} exists with a different checksum")
        return
    _write_private(mp, json.dumps({
        "schema": PG_MANIFEST_SCHEMA, "file": dump.name, "size_bytes": size, "sha256": sha,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "format": "pg_dump custom",
        "evidence": {"local_created": True,
                     "local_verified": "dump header and checksum only; a restore drill is "
                                       "the only proof that it restores",
                     "offhost_copy": "not recorded by this command"},
    }, indent=2).encode())  # fmt: skip


def _record_cmd(args) -> int:
    from diski9.backup import records
    from diski9.backup.store import sha256_file

    f = Path(args.file)
    if not f.is_file():
        print(f"backup record: {f.name} does not exist; nothing was recorded", file=sys.stderr)
        return 2
    sha, size = sha256_file(f), f.stat().st_size
    base = {"file": f.name, "size_bytes": size, "sha256_prefix": sha[:16]}
    if args.kind == "postgres":
        with open(f, "rb") as fh:
            header_ok = fh.read(5) == b"PGDMP"
        if not header_ok:
            print(f"backup record: {f.name} is not a pg_dump custom-format file; recorded as a "
                  "FAILED PostgreSQL backup", file=sys.stderr)  # fmt: skip
            rc = _record(records.BACKUP_POSTGRES, base | {"verified": False}, ok=False,
                         detail="not a pg_dump custom-format file", required=True)  # fmt: skip
            return rc or 1
        try:
            _write_pg_manifest(f, sha, size)
        except ValueError as exc:
            print(f"backup record: {exc}; nothing was recorded", file=sys.stderr)
            return 1
        print(f"backup record: {f.name} - pg_dump header and SHA-256 recorded (sha256 {sha[:16]});"
              " it is proven restorable only by a restore drill")  # fmt: skip
        return _record(records.BACKUP_POSTGRES, base | {"verified": True,
                       "verification": "header+checksum"}, required=True)  # fmt: skip
    if args.kind == "offhost-copy":
        try:
            label = records.safe_label(args.label, "--label")
        except ValueError as exc:
            print(f"backup record: {exc}", file=sys.stderr)
            return 2
        print(f"backup record: off-host copy of {f.name} REPORTED (not verified by Diski 9)")
        return _record(records.BACKUP_OFFHOST, base | {"destination": label,
                       "evidence": "reported by the host copy hook"}, required=True)  # fmt: skip
    if args.kind == "postgres-drill":
        engine = _competition_engine()
        matched = False
        if engine is not None:
            from diski9.backend.db import transaction

            with transaction(engine) as conn:
                matched = records.matches_recorded_backup(conn, sha)
        print(f"backup record: PostgreSQL restore drill of {f.name} (origin "
              f"{args.source_origin}, declared; matches a recorded backup: "
              f"{'yes' if matched else 'no'})")  # fmt: skip
        return _record(records.RESTORE_DRILL, base | {
            "store": "postgres", "source_origin": args.source_origin,
            "matches_recorded_backup": matched, "evidence": "operator-declared drill result",
        }, required=True)  # fmt: skip
    # postgres-restore: the competition database itself was restored (safeguard D)
    print(f"backup record: competition-database restore from {f.name} recorded. Provider calls "
          "are now HELD for the scheduler until an operator runs `diski9 ops provider-resume` "
          "after reconciliation (docs/operations_hosting.md).")  # fmt: skip
    return _record(records.RESTORE_POSTGRES, base | {"hold": True}, required=True)


def _restore(args) -> int:
    from diski9.backup import records
    from diski9.backup.restore import RestoreRefused, restore_store
    from diski9.backup.store import BackupError

    try:
        res = restore_store(Path(args.source), Path(args.target), live=_live_store(args),
                            replace_live=args.replace_live)  # fmt: skip
    except RestoreRefused as exc:
        print(f"restore store: REFUSED - {exc}", file=sys.stderr)
        return 2
    except BackupError as exc:
        print(f"restore store: FAILED - {exc}", file=sys.stderr)
        return 1
    print(f"restore store: {res.target.name} restored and verified in {res.seconds:.2f} s "
          f"({res.verification.verdict(res.target.name)})")  # fmt: skip
    matched = False
    try:
        engine = _competition_engine()
        if engine is not None:
            from diski9.backend.db import transaction

            with transaction(engine) as conn:
                matched = records.matches_recorded_backup(conn, res.sha256)
    except Exception:  # noqa: BLE001 - reported by the record step below
        pass
    job = records.RESTORE_STORE if args.purpose == "recovery" else records.RESTORE_DRILL
    rc = _record(job, {
        "store": "football", "file": Path(args.source).name, "target": res.target.name,
        "sha256_prefix": res.sha256[:16], "manifest_created_at": res.manifest_created_at,
        "source_origin": args.source_origin, "matches_recorded_backup": matched,
        "purpose": args.purpose, "seconds": res.seconds,
    }, required=args.purpose == "recovery")  # fmt: skip
    if args.purpose == "recovery":
        print("restore store: the live store was NOT changed. To use the restored file, follow "
              "the offline switch procedure in docs/operations_hosting.md (stop the services, "
              "confirm nothing holds the store, point DISKI9_DATABASE_URL at the restored file, "
              "verify, start). Data refresh sweeps from before this restore no longer count as "
              "current.")  # fmt: skip
    return rc


def run(args: argparse.Namespace) -> int:
    if args.command == "restore":
        return _restore(args)
    return {"store": _backup_store, "verify": _verify, "record": _record_cmd}[args.action](args)
