"""Phase 6C.6 Stage F2: football-store online backup, verification and guarded
restoration (temporary SQLite stores only; no competition database, no network).

Safeguard A: live replacement is disabled, and every unsafe target is refused.
Safeguard B: the backup establishes only local creation and local verification.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path

import pytest

from diski9 import cli
from diski9.backup.restore import LIVE_REPLACEMENT_DISABLED, RestoreRefused, restore_store
from diski9.backup.store import (
    BackupError,
    backup_store,
    manifest_path,
    prune,
    verify_backup,
)
from diski9.db import make_engine, upgrade

from .factories import seed_competition

PLANTED = ("planted-db-password-7731", "planted-api-key-5512", "planted-secret-key-9a8b")


@pytest.fixture
def live(tmp_path):
    """A migrated football store in WAL mode with some rows, in its own folder."""
    d = tmp_path / "var"
    d.mkdir()
    url = f"sqlite:///{d / 'diski9.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    with eng.begin() as c:
        for cid in (39, 40, 288):
            seed_competition(c, cid, name=f"League {cid}")
    eng.dispose()
    return d / "diski9.sqlite"


@pytest.fixture
def backups(tmp_path):
    return tmp_path / "backups"


def _bytes(p: Path) -> bytes | None:
    return p.read_bytes() if p.exists() else None


def _snapshot(live: Path) -> dict:
    return {s: _bytes(Path(f"{live}{s}")) for s in ("", "-wal", "-shm")}


# ------------------------------------------------------------------ backup
def test_backup_is_verified_checksummed_private_and_self_contained(live, backups):
    before = _snapshot(live)
    res = backup_store(live, backups)
    assert res.verification.ok and res.verification.store_version == "0004"
    assert stat.S_IMODE(res.file.stat().st_mode) == 0o600
    assert stat.S_IMODE(res.manifest.stat().st_mode) == 0o600
    m = json.loads(res.manifest.read_text())
    assert m["schema"] == "diski9-store-backup/1" and m["file"] == res.file.name
    assert m["sha256"] == res.sha256 and m["size_bytes"] == res.size
    assert m["tables"]["competitions"] == 3
    assert m["evidence"] == {"local_created": True, "local_verified": True,
                             "offhost_copy": "not recorded by this command",
                             "offhost_restore_drill": "not recorded by this command"}  # fmt: skip
    text = res.manifest.read_text()
    assert str(live.parent) not in text and "sqlite:" not in text and str(backups) not in text
    # a single self-contained file: no WAL/SHM next to the backup
    con = sqlite3.connect(f"file:{res.file}?mode=ro", uri=True)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    con.close()
    assert sorted(p.name for p in backups.iterdir()) == [res.file.name, res.manifest.name]
    assert _snapshot(live)[""] == before[""]  # the live store itself is not modified
    assert verify_backup(res.file).ok


def test_backup_while_the_store_is_written_and_read(live, backups):
    """Online backup under concurrent use: a writer keeps inserting (as the
    scheduler would) and a reader holds a transaction open (as a web worker would).
    The backup is one consistent snapshot, and the writer is never blocked."""
    stop = threading.Event()
    longest = [0.0]
    written = [0]
    errors: list[BaseException] = []

    def writer():
        try:
            _write(live, stop, longest, written)
        except BaseException as exc:  # surfaced by the test below
            errors.append(exc)

    reader = sqlite3.connect(live)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM fixtures").fetchone()
    th = threading.Thread(target=writer)
    th.start()
    try:
        deadline = time.monotonic() + 30
        while written[0] < 20 and not errors and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not errors, errors
        assert written[0] >= 20, "the writer did not start"
        results = [backup_store(live, backups / str(n)) for n in range(3)]
    finally:
        stop.set()
        th.join(timeout=30)
        reader.rollback()
        reader.close()
    assert not errors, errors
    for res in results:
        assert res.verification.ok
        n = res.verification.tables["venues"]
        assert 20 <= n <= written[0]  # a point-in-time snapshot of the writer's progress
        assert verify_backup(res.file).ok
    assert longest[0] < 2.0  # the writer was never held up by the backup


def _write(live, stop, longest, written):
    con = sqlite3.connect(live, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    i = 0
    try:
        while not stop.is_set():
            t = time.monotonic()
            with con:
                con.execute("INSERT INTO venues (id, name, city, updated_at) VALUES (?, ?, ?, ?)",
                            (100000 + i, f"Venue {i}", "City", "2026-11-22 00:00:00"))  # fmt: skip
            longest[0] = max(longest[0], time.monotonic() - t)
            i += 1
            written[0] = i
            time.sleep(0.002)
    finally:
        con.close()


def test_failed_verification_deletes_the_copy(live, backups, monkeypatch):
    from diski9.backup import store as st

    real = st.inspect_store

    def corrupting(path):
        v = real(path)
        v.problems.append("integrity_check failed (1 problem(s))")
        v.ok = False
        return v

    monkeypatch.setattr(st, "inspect_store", corrupting)
    with pytest.raises(BackupError, match="failed verification"):
        backup_store(live, backups)
    assert list(backups.iterdir()) == []  # no copy, no manifest, no temporary file


def test_backup_refuses_its_own_folder_and_missing_store(live, tmp_path):
    with pytest.raises(BackupError, match="own folder"):
        backup_store(live, live.parent)
    with pytest.raises(BackupError, match="does not exist"):
        backup_store(tmp_path / "absent.sqlite", tmp_path / "b")


def test_prune_keeps_the_newest_and_only_its_own_files(live, backups):
    from datetime import UTC, datetime, timedelta

    t = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)
    for i in range(5):
        backup_store(live, backups, keep=100, now=t + timedelta(days=i))
    (backups / "notes.txt").write_text("keep me")
    removed = prune(backups, 2)
    assert len(removed) == 3
    names = sorted(p.name for p in backups.iterdir())
    assert names == ["diski9-store-20261104T033000Z.sqlite",
                     "diski9-store-20261104T033000Z.sqlite.manifest.json",
                     "diski9-store-20261105T033000Z.sqlite",
                     "diski9-store-20261105T033000Z.sqlite.manifest.json", "notes.txt"]  # fmt: skip


# ------------------------------------------------------------------ verification
def test_verify_detects_checksum_mismatch(live, backups):
    res = backup_store(live, backups)
    m = json.loads(res.manifest.read_text())
    m["sha256"] = "0" * 64
    res.manifest.write_text(json.dumps(m))
    v = verify_backup(res.file)
    assert not v.ok and "SHA-256 does not match the manifest" in v.problems


def test_verify_detects_corruption(live, backups):
    res = backup_store(live, backups)
    data = bytearray(res.file.read_bytes())
    data[4096:8192] = b"\x00" * 4096  # damage a page
    res.file.write_bytes(bytes(data))
    v = verify_backup(res.file)
    assert not v.ok
    # with a manifest re-computed for the damaged file, integrity checks still catch it
    import hashlib

    m = json.loads(res.manifest.read_text())
    m["sha256"] = hashlib.sha256(bytes(data)).hexdigest()
    res.manifest.write_text(json.dumps(m))
    v = verify_backup(res.file)
    assert not v.ok and v.problems


def test_verify_detects_truncation_missing_or_foreign_manifest(live, backups):
    res = backup_store(live, backups)
    other = backup_store(live, backups / "other")
    with open(res.file, "r+b") as fh:
        fh.truncate(res.size // 2)
    assert "size does not match the manifest" in verify_backup(res.file).problems
    manifest_path(other.file).rename(other.file.with_name("moved.json"))
    assert "no manifest" in verify_backup(other.file).problems[0]
    from datetime import UTC, datetime

    foreign = backup_store(live, backups / "foreign", now=datetime(2026, 1, 1, tzinfo=UTC))
    manifest_path(foreign.file).write_text(json.dumps(
        json.loads(manifest_path(res.file).read_text())))  # fmt: skip
    assert "does not describe" in verify_backup(foreign.file).problems[0]


def test_verify_detects_row_counts_differing_from_the_manifest(live, backups):
    res = backup_store(live, backups)
    m = json.loads(res.manifest.read_text())
    m["tables"]["competitions"] = 99
    res.manifest.write_text(json.dumps(m))
    assert "row counts differ from the manifest" in verify_backup(res.file).problems


# ------------------------------------------------------------------ restore
def test_restore_into_a_new_path_verifies_and_preserves_the_previous_store(live, backups,
                                                                          tmp_path):  # fmt: skip
    res = backup_store(live, backups)
    eng = make_engine(f"sqlite:///{live}")  # an open consumer with WAL/SHM present
    with eng.begin() as c:
        seed_competition(c, 61, name="Later")
    before = _snapshot(live)
    target = tmp_path / "restored" / "diski9-restored.sqlite"
    target.parent.mkdir()
    out = restore_store(res.file, target, live=live)
    assert out.verification.ok and out.sha256 == res.sha256
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert out.verification.tables["competitions"] == 3  # the backup's content
    assert _snapshot(live) == before  # previous store, WAL and SHM untouched
    assert not list(target.parent.glob(".*restore-tmp"))
    eng.dispose()


def test_replace_live_is_always_refused(live, backups, tmp_path):
    res = backup_store(live, backups)
    before = _snapshot(live)
    for target in (live, tmp_path / "new.sqlite"):
        with pytest.raises(RestoreRefused) as exc:
            restore_store(res.file, target, live=live, replace_live=True)
        assert "live replacement is disabled" in str(exc.value)
    assert _snapshot(live) == before
    assert not (tmp_path / "new.sqlite").exists()


def _refuses(res, target, live, match):
    before = _snapshot(live)
    existed = target.exists() or target.is_symlink()
    with pytest.raises(RestoreRefused, match=match):
        restore_store(res.file, target, live=live)
    assert _snapshot(live) == before
    if not existed:
        assert not target.exists()


def test_restore_refuses_the_live_store_and_every_alias(live, backups, tmp_path):
    res = backup_store(live, backups)
    make_engine(f"sqlite:///{live}").connect().close()  # create -wal/-shm
    _refuses(res, live, live, "configured live football store")
    for side in ("-wal", "-shm", "-journal"):
        _refuses(res, Path(f"{live}{side}"), live, "-wal, -shm or -journal")
    link = tmp_path / "alias.sqlite"
    link.symlink_to(live)
    _refuses(res, link, live, "configured live football store")
    hard = tmp_path / "hard.sqlite"
    os.link(live, hard)
    _refuses(res, hard, live, "configured live football store")
    dotted = live.parent / "." / live.name
    _refuses(res, dotted, live, "configured live football store")


def test_restore_refuses_existing_targets_side_files_and_bad_folders(live, backups, tmp_path):
    res = backup_store(live, backups)
    other = tmp_path / "not-a-store.txt"
    other.write_text("important")
    _refuses(res, other, live, "already exists")
    assert other.read_text() == "important"
    store2 = tmp_path / "other-store.sqlite"
    store2.write_bytes(res.file.read_bytes())
    _refuses(res, store2, live, "already exists")
    fresh = tmp_path / "fresh.sqlite"
    Path(f"{fresh}-wal").write_bytes(b"")
    _refuses(res, fresh, live, "exists next to the target")
    _refuses(res, tmp_path / "missing-dir" / "x.sqlite", live, "folder does not exist")


def test_restore_refuses_unverified_sources(live, backups, tmp_path):
    res = backup_store(live, backups)
    bad = backup_store(live, backups / "bad")
    data = bytearray(bad.file.read_bytes())
    data[100] ^= 0xFF
    bad.file.write_bytes(bytes(data))
    with pytest.raises(RestoreRefused, match="failed verification"):
        restore_store(bad.file, tmp_path / "a.sqlite", live=live)
    nomani = backup_store(live, backups / "nomani")
    manifest_path(nomani.file).unlink()
    with pytest.raises(RestoreRefused, match="no manifest"):
        restore_store(nomani.file, tmp_path / "b.sqlite", live=live)
    with pytest.raises(RestoreRefused, match="source is the live store"):
        restore_store(live, tmp_path / "c.sqlite", live=live)
    assert not any((tmp_path / n).exists() for n in ("a.sqlite", "b.sqlite", "c.sqlite"))
    # a leftover temporary file from an interrupted restore is never reused blindly
    (tmp_path / ".d.sqlite.restore-tmp").write_bytes(b"partial")
    with pytest.raises(RestoreRefused, match="interrupted restore"):
        restore_store(res.file, tmp_path / "d.sqlite", live=live)
    assert (tmp_path / ".d.sqlite.restore-tmp").read_bytes() == b"partial"


# ------------------------------------------------------------------ CLI and secrets
@pytest.fixture
def secret_env(monkeypatch):
    monkeypatch.setenv("DISKI9_API_FOOTBALL_KEY", PLANTED[1])
    monkeypatch.setenv("DISKI9_APP_SECRET_KEY", PLANTED[2])
    monkeypatch.delenv("DISKI9_APP_DATABASE_URL", raising=False)


def _main(capsys, *argv) -> tuple[int, str]:
    rc = cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_cli_backup_verify_restore_print_names_only(live, backups, tmp_path, capsys,
                                                    secret_env, monkeypatch):  # fmt: skip
    monkeypatch.chdir(tmp_path)
    url = f"sqlite:///{live}"
    rc, out = _main(capsys, "--database-url", url, "backup", "store", "--out", str(backups))
    assert rc == 0, out
    assert "locally verified: yes" in out and "off-host copy: NOT established" in out
    assert "not recorded: no competition database is configured" in out
    f = next(backups.glob("diski9-store-*.sqlite"))
    rc, out2 = _main(capsys, "backup", "verify", str(f))
    assert rc == 0 and "verified" in out2
    target = tmp_path / "restored.sqlite"
    rc, out3 = _main(capsys, "--database-url", url, "restore", "store", "--from", str(f),
                     "--to", str(target), "--purpose", "drill")  # fmt: skip
    assert rc == 0 and target.exists(), out3
    rc, out4 = _main(capsys, "--database-url", url, "restore", "store", "--from", str(f),
                     "--to", str(live), "--purpose", "recovery")  # fmt: skip
    assert rc == 2 and "REFUSED" in out4
    rc, out5 = _main(capsys, "--database-url", url, "restore", "store", "--from", str(f),
                     "--to", str(tmp_path / "x.sqlite"), "--purpose", "recovery",
                     "--replace-live")  # fmt: skip
    assert rc == 2 and LIVE_REPLACEMENT_DISABLED[:40] in out5
    everything = out + out2 + out3 + out4 + out5 + "".join(
        p.read_text() for p in backups.glob("*.json"))  # fmt: skip
    for leak in (*PLANTED, str(tmp_path), "sqlite:///"):
        assert leak not in everything


def test_cli_recording_failure_never_echoes_credentials(live, backups, tmp_path, capsys,
                                                        monkeypatch):  # fmt: skip
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISKI9_APP_DATABASE_URL",
                       f"postgresql+psycopg://diski9:{PLANTED[0]}@127.0.0.1:1/nodb_test")  # fmt: skip
    rc, out = _main(capsys, "--database-url", f"sqlite:///{live}", "backup", "store", "--out",
                    str(backups))  # fmt: skip
    assert rc == 1 and "NOT RECORDED" in out  # created and verified, but monitoring is told
    assert PLANTED[0] not in out and "127.0.0.1" not in out and "nodb_test" not in out
    assert next(backups.glob("diski9-store-*.sqlite")).exists()


def test_cli_refuses_a_non_sqlite_store(capsys, backups, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    rc, out = _main(capsys, "--database-url", "postgresql+psycopg://u:pw-x@h/db", "backup",
                    "store", "--out", str(backups))  # fmt: skip
    assert rc == 2 and "not a SQLite file" in out and "pw-x" not in out


def test_offhost_labels_cannot_carry_urls_or_paths():
    from diski9.backup.records import safe_label

    assert safe_label("second-box nightly") == "second-box nightly"
    for bad in ("s3://bucket/key", "https://x.example/a", "/var/lib/x", "user:pw@host",
                "x" * 41, ""):  # fmt: skip
        with pytest.raises(ValueError):
            safe_label(bad)
