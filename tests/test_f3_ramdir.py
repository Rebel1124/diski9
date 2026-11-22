"""Stage F3: RAM-disk initialisation is cleaned up on every failure path.

lib-ramdir.sh installs its cleanup trap before creating anything. A failure or a
signal at any point of initialisation (macOS: attach, format, mount check, chmod;
Linux: mktemp, swap check, chmod) must leave no RAM disk behind. macOS is simulated
with fake `uname`, `hdiutil` and `diskutil` commands."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "deploy" / "f3" / "owner" / "lib-ramdir.sh"
HARNESS = """#!/usr/bin/env bash
set -euo pipefail
. "$LIB"
f3_ramdir_create
echo "CREATED dir=$F3_RAMDIR dev=$F3_RAMDEV"
if [ -n "${HOLD:-}" ]; then sleep 30; fi
echo "AFTER"
"""
FAKE_HDIUTIL = """#!/bin/sh
echo "hdiutil $*" >> "$FAKE_LOG"
case "$1" in
  attach) [ -n "$ATTACH_FAIL" ] && exit 1
          [ -n "$ATTACH_GARBAGE" ] && { echo "something unexpected"; exit 0; }
          echo "/dev/disk42          	" ;;
  detach) [ -n "$DETACH_FAIL" ] && exit 1 ;;
esac
exit 0
"""
FAKE_DISKUTIL = """#!/bin/sh
echo "diskutil $*" >> "$FAKE_LOG"
[ -n "$FORMAT_SLEEP" ] && sleep "$FORMAT_SLEEP"
[ -n "$FORMAT_FAIL" ] && exit 1
exit 0
"""


def _exe(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def h(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(tmp_path / "harness.sh", HARNESS)
    env = {**os.environ, "LIB": str(LIB), "FAKE_LOG": str(tmp_path / "log"),
           "PATH": f"{bindir}:{os.environ['PATH']}"}  # fmt: skip
    return tmp_path, bindir, env


def _macos(bindir):
    _exe(bindir / "uname", "#!/bin/sh\necho Darwin\n")
    _exe(bindir / "hdiutil", FAKE_HDIUTIL)
    _exe(bindir / "diskutil", FAKE_DISKUTIL)


def _log(tmp):
    p = tmp / "log"
    return p.read_text().splitlines() if p.exists() else []


def _run(tmp, env, **extra):
    return subprocess.run([str(tmp / "harness.sh")], env={**env, **extra}, capture_output=True,
                          text=True, timeout=60)  # fmt: skip


def _spawn(tmp, env):
    return subprocess.Popen([str(tmp / "harness.sh")], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)  # fmt: skip


def _signal_group(p, sig):
    """Signal the whole process group, as a terminal does for Ctrl-C or on close."""
    try:
        os.killpg(p.pid, sig)
        return p.communicate(timeout=20)
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


def _ours():
    return {p.name for p in Path("/dev/shm").iterdir() if p.name.startswith("diski9-f3.")}


# ------------------------------------------------------------------ macOS (simulated)
def test_macos_format_failure_detaches_the_attached_device(h):
    tmp, bindir, env = h
    _macos(bindir)
    r = _run(tmp, env, FORMAT_FAIL="1")
    assert r.returncode != 0 and "could not format the RAM disk" in r.stderr
    assert "CREATED" not in r.stdout
    assert "hdiutil detach /dev/disk42 -force" in _log(tmp)


def test_macos_missing_mount_point_after_format_detaches(h):
    tmp, bindir, env = h
    _macos(bindir)  # the fake format "succeeds" but nothing is mounted under /Volumes
    r = _run(tmp, env)
    assert r.returncode != 0 and "not mounted" in r.stderr
    assert "hdiutil detach /dev/disk42 -force" in _log(tmp)


def test_macos_attach_failure_or_garbage_leaves_nothing_to_detach(h):
    tmp, bindir, env = h
    _macos(bindir)
    r = _run(tmp, env, ATTACH_FAIL="1")
    assert r.returncode != 0 and "could not create a RAM disk" in r.stderr
    r = _run(tmp, env, ATTACH_GARBAGE="1")
    assert r.returncode != 0 and "hdiutil info" in r.stderr
    assert not any("detach" in line for line in _log(tmp))


def test_macos_signal_during_format_detaches(h):
    tmp, bindir, env = h
    _macos(bindir)
    p = _spawn(tmp, {**env, "FORMAT_SLEEP": "10"})
    deadline = time.time() + 20
    while time.time() < deadline and not any("diskutil" in x for x in _log(tmp)):
        time.sleep(0.05)
    _signal_group(p, signal.SIGTERM)
    assert p.returncode == 143
    assert "hdiutil detach /dev/disk42 -force" in _log(tmp)


def test_macos_detach_failure_during_partial_initialisation_is_reported(h):
    tmp, bindir, env = h
    _macos(bindir)
    r = _run(tmp, env, FORMAT_FAIL="1", DETACH_FAIL="1")
    assert r.returncode != 0
    assert "could not be removed: (not mounted) (device /dev/disk42)" in r.stderr
    assert "hdiutil detach /dev/disk42 -force" in r.stderr  # the manual command


# ------------------------------------------------------------------ Linux
def test_linux_chmod_failure_removes_the_new_directory(h):
    tmp, bindir, env = h
    before = _ours()
    _exe(bindir / "chmod", "#!/bin/sh\nexit 1\n")
    r = _run(tmp, env)
    assert r.returncode != 0 and "could not restrict" in r.stderr
    assert _ours() == before


def test_linux_signal_during_initialisation_removes_the_directory(h):
    tmp, bindir, env = h
    before = _ours()
    # swapon runs after mktemp: make it slow, then interrupt
    _exe(bindir / "swapon", '#!/bin/sh\necho "swapon" >> "$FAKE_LOG"\nsleep 10\n')
    p = _spawn(tmp, env)
    deadline = time.time() + 20
    while time.time() < deadline and "swapon" not in _log(tmp):
        time.sleep(0.05)
    assert _ours() - before  # the directory exists at this point
    _signal_group(p, signal.SIGTERM)
    assert p.returncode == 143 and _ours() == before


@pytest.mark.parametrize(("sig", "code"), [(signal.SIGINT, 130), (signal.SIGTERM, 143),
                                           (signal.SIGHUP, 129)])  # fmt: skip
def test_signal_after_creation_cleans_up_and_never_continues(h, sig, code):
    tmp, _, env = h
    before = _ours()
    p = _spawn(tmp, {**env, "HOLD": "1"})
    deadline = time.time() + 20
    while time.time() < deadline and not (_ours() - before):
        time.sleep(0.05)
    time.sleep(0.3)
    out, _ = _signal_group(p, sig)
    assert p.returncode == code and "AFTER" not in out
    assert _ours() == before


def test_normal_exit_removes_the_directory(h):
    tmp, _, env = h
    before = _ours()
    r = _run(tmp, env)
    assert r.returncode == 0 and "AFTER" in r.stdout and "/dev/shm/diski9-f3." in r.stdout
    assert _ours() == before
