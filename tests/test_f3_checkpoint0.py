"""Phase 6C.6 Stage F3 Checkpoint 0: the owner and host preparation scripts.

The scripts handle private keys, so these tests run them end to end: the one-shot CA
must issue exactly one IP-SAN server certificate and leave no CA key behind; the age
script must never write a plaintext identity and both identities must decrypt; the
day-one check must stay read-only and mask public addresses."""

from __future__ import annotations

import importlib.util
import json
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
F3 = ROOT / "deploy" / "f3"
OWNER, HOST = F3 / "owner", F3 / "host"
SCRIPTS = sorted(p for p in F3.rglob("*") if p.is_file() and p.suffix in (".sh", ""))


def _load_day1():
    spec = importlib.util.spec_from_file_location("f3_day1", HOST / "f3_day1_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode, before = True, sys.dont_write_bytecode  # no __pycache__ in deploy/
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = before
    return mod


def _openssl(*args: str) -> str:
    return subprocess.run(["openssl", *args], check=True, capture_output=True, text=True).stdout


def _shm_files() -> set[str]:
    return {p.name for p in Path("/dev/shm").iterdir()} if Path("/dev/shm").is_dir() else set()


# ------------------------------------------------------------------ all scripts
@pytest.mark.parametrize("path", [p for p in F3.rglob("*.sh")], ids=lambda p: p.name)
def test_shell_scripts_are_strict_and_parse(path):
    text = path.read_text()
    if path.name != "lib-ramdir.sh":  # sourced library, not executable
        assert text.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in text
        assert os.access(path, os.X_OK)
    subprocess.run(["bash", "-n", str(path)], check=True)


def test_no_script_reads_or_prints_secrets_from_the_environment():
    for path in F3.rglob("*"):
        if path.is_file():
            text = path.read_text()
            # no password, key or token is ever taken from arguments or the environment
            assert not re.search(r"(PASSWORD|SECRET|TOKEN|API_KEY)\s*=", text), path.name
            assert "api-sports.io" not in text, path.name  # never a provider endpoint


# ------------------------------------------------------------------ server CSR + CA
@pytest.fixture
def csr(tmp_path):
    d = tmp_path / "tls"
    r = subprocess.run([str(HOST / "f3-make-server-csr.sh"), "--dir", str(d)],
                       capture_output=True, text=True, check=True)  # fmt: skip
    assert "BEGIN CERTIFICATE REQUEST" in r.stdout and "PRIVATE KEY" not in r.stdout
    assert (d / "server.key").stat().st_mode & 0o077 in (0, 0o040)
    return d


def test_csr_script_refuses_to_replace_a_key_without_rotate(csr):
    r = subprocess.run([str(HOST / "f3-make-server-csr.sh"), "--dir", str(csr)],
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode != 0 and "--rotate" in r.stderr


def test_one_shot_ca_issues_one_ip_san_certificate_and_destroys_its_key(csr, tmp_path):
    out = tmp_path / "out"
    before = _shm_files()
    r = subprocess.run([str(OWNER / "f3-sign-server-cert.sh"), str(csr / "server.csr"), str(out)],
                       capture_output=True, text=True, check=True)  # fmt: skip
    assert "CA private key destroyed" in r.stdout
    assert _shm_files() == before  # the RAM scratch directory is gone
    files = {p.name for p in out.iterdir()}
    assert files == {"diski9-f3-ca.crt", "diski9-f3-ca.cer", "server.crt", "fingerprints.txt"}
    for p in out.iterdir():  # no private key of any kind in the output
        assert b"PRIVATE KEY" not in p.read_bytes()
    leaf = _openssl("x509", "-in", str(out / "server.crt"), "-noout", "-text")
    assert "IP Address:10.88.0.1" in leaf and "DNS:" not in leaf
    assert "CA:FALSE" in leaf and "TLS Web Server Authentication" in leaf
    ca = _openssl("x509", "-in", str(out / "diski9-f3-ca.crt"), "-noout", "-text")
    assert "CA:TRUE, pathlen:0" in ca and "Name Constraints" not in ca
    # the leaf really is for the CSR's key (the key that stays on the server)
    pub_leaf = _openssl("x509", "-in", str(out / "server.crt"), "-noout", "-pubkey")
    pub_key = _openssl("ec", "-in", str(csr / "server.key"), "-pubout")
    assert pub_leaf == pub_key
    ok = subprocess.run(["openssl", "verify", "-CAfile", str(out / "diski9-f3-ca.crt"),
                         "-verify_ip", "10.88.0.1", str(out / "server.crt")])  # fmt: skip
    bad = subprocess.run(["openssl", "verify", "-CAfile", str(out / "diski9-f3-ca.crt"),
                          "-verify_ip", "10.88.0.2", str(out / "server.crt")],
                         capture_output=True)  # fmt: skip
    assert ok.returncode == 0 and bad.returncode != 0
    for secs, expired in ((179 * 86400, 0), (181 * 86400, 1)):  # 180-day validity
        r = subprocess.run(["openssl", "x509", "-in", str(out / "server.crt"), "-noout",
                            "-checkend", str(secs)], capture_output=True)  # fmt: skip
        assert r.returncode == expired


def test_ca_script_refusals(csr, tmp_path):
    sign = str(OWNER / "f3-sign-server-cert.sh")
    bad_ip = subprocess.run([sign, str(csr / "server.csr"), str(tmp_path / "a")],
                            env={**os.environ, "F3_IP": "192.168.1.1"}, capture_output=True,
                            text=True)  # fmt: skip
    assert bad_ip.returncode != 0 and "tunnel address" in bad_ip.stderr
    too_long = subprocess.run([sign, str(csr / "server.csr"), str(tmp_path / "b")],
                              env={**os.environ, "F3_DAYS": "800"}, capture_output=True,
                              text=True)  # fmt: skip
    assert too_long.returncode != 0
    (tmp_path / "c").mkdir()
    exists = subprocess.run([sign, str(csr / "server.csr"), str(tmp_path / "c")],
                            capture_output=True, text=True)  # fmt: skip
    assert exists.returncode != 0 and "refusing to overwrite" in exists.stderr
    rsa = tmp_path / "rsa.csr"
    subprocess.run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout",
                    str(tmp_path / "rsa.key"), "-subj", "/CN=x", "-out", str(rsa)],
                   check=True, capture_output=True)  # fmt: skip
    wrong = subprocess.run([sign, str(rsa), str(tmp_path / "d")], capture_output=True, text=True)
    assert wrong.returncode != 0 and "P-256" in wrong.stderr
    assert not (tmp_path / "a").exists() and not (tmp_path / "d").exists()


# ------------------------------------------------------------------ age identities
def _drive(cmd: list[str], answers: str, timeout: float = 60) -> tuple[int, str]:
    """Run cmd on a pseudo-terminal, typing `answers` whenever it asks for a passphrase."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)
    out, deadline = b"", time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 1)
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if re.search(rb"passphrase[^\n]*:\s*$", out, re.I):
            os.write(fd, answers.encode() + b"\n")
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


def test_age_identities_are_encrypted_at_rest_and_both_decrypt(tmp_path):
    assert shutil.which("age") and shutil.which("age-keygen"), "age is required (CI installs it)"
    out = tmp_path / "age"
    before = _shm_files()
    code, log = _drive([str(OWNER / "f3-make-age-identities.sh"), str(out)],
                       "correct horse battery staple diski9 f3 test")  # fmt: skip
    assert code == 0, log
    assert "primary: OK" in log and "offline-recovery: OK" in log
    assert _shm_files() == before
    assert "AGE-SECRET-KEY" not in log  # the private key is never displayed
    files = sorted(p.name for p in out.iterdir())
    assert files == ["diski9-f3-age-offline-recovery.age", "diski9-f3-age-primary.age",
                     "diski9-f3-age-recipients.txt"]  # fmt: skip
    for name in ("primary", "offline-recovery"):
        data = (out / f"diski9-f3-age-{name}.age").read_text()
        assert data.startswith("-----BEGIN AGE ENCRYPTED FILE-----")
        assert "AGE-SECRET-KEY" not in data
    recips = [ln for ln in (out / "diski9-f3-age-recipients.txt").read_text().splitlines()
              if ln.startswith("age1")]  # fmt: skip
    assert len(recips) == 2 and recips[0] != recips[1]
    # refuses to overwrite an existing identity folder
    again = subprocess.run([str(OWNER / "f3-make-age-identities.sh"), str(out)],
                           capture_output=True, text=True)  # fmt: skip
    assert again.returncode != 0 and "refusing to overwrite" in again.stderr


# ------------------------------------------------------------------ day-one check
def test_day1_masks_public_addresses_and_keeps_private_ones():
    d1 = _load_day1()
    assert d1.mask_ip("203.0.113.7") == "203.0.x.x"
    assert d1.mask_ip("2a02:4780:1:2::5") == "2a02:4780:x:x:x:x:x:x"
    assert d1.mask_ip("10.88.0.1") == "10.88.0.1" and d1.mask_ip("127.0.0.1") == "127.0.0.1"
    rows = d1.addresses([{"ifname": "eth0", "addr_info": [
        {"family": "inet", "local": "198.51.100.20", "prefixlen": 24, "scope": "global"},
        {"family": "inet6", "local": "2001:db8::1", "prefixlen": 64, "scope": "global"},
        {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"}]}])  # fmt: skip
    assert [r["address"] for r in rows] == ["198.51.x.x", "2001:0db8:x:x:x:x:x:x"]
    assert d1.mask_ip("192.168.1.10") == "192.168.1.10" and d1.mask_ip("fd00::1") == "fd00::1"
    assert d1.listening("tcp LISTEN 0 4096 198.51.100.20:22 0.0.0.0:*") == ["tcp 198.51.x.x:22"]


def test_day1_p95_is_nearest_rank():
    d1 = _load_day1()
    assert d1.p95([float(x) for x in range(1, 101)]) == 95.0  # ceil(0.95 * 100) = 95th value
    assert d1.p95([1.0] * 19 + [50.0]) == 1.0  # 19th of 20 values
    assert d1.p95([1.0] * 18 + [50.0, 50.0]) == 50.0
    assert d1.p95([3.0]) == 3.0


def test_day1_it1_is_rtt_p95_strictly_below_10_ms():
    d1 = _load_day1()

    def fam(p95, ok=100, samples=100):
        return {"samples": samples, "ok": ok, "failed": samples - ok, "p95_ms": p95}

    base = {"addresses": [{"family": "inet6"}], "ipv6_default_route": True}

    def it(targets):
        return d1.evaluate({**base, "targets": targets})

    good = {
        "db:5432": {"ipv4": {}, "ipv6": fam(4.2)},
        "pooler:5432": {"ipv4": fam(3.9), "ipv6": {}},
    }
    assert it(good) == {**it(good), "IT-1": "PASS", "IT-2": "PASS"}
    # the approved criterion is strict: p95 of exactly 10 ms fails
    edge = {"pooler:5432": {"ipv4": fam(10.0), "ipv6": {}}}
    assert it(edge)["IT-1"] == "FAIL"
    assert it({"pooler:5432": {"ipv4": fam(9.999), "ipv6": {}}})["IT-1"] == "PASS"
    # every measured family must pass, not just the faster one
    mixed = {"db:5432": {"ipv4": fam(3.0), "ipv6": fam(12.0)}}
    assert it(mixed)["IT-1"] == "FAIL"
    # fewer than 95 % successful samples is not evidence
    lossy = {"pooler:5432": {"ipv4": fam(2.0, ok=90), "ipv6": {}}}
    assert it(lossy)["IT-1"] == "FAIL"
    # an unreachable target fails; no targets means not run
    assert it({"db:5432": {"ipv4": {}, "ipv6": {"resolved": False}}})["IT-1"] == "FAIL"
    assert it({})["IT-1"] == "NOT RUN"
    assert it({"pooler:5432": {"ipv4": fam(3.0), "ipv6": {}}})["IT-2"] == "FAIL"  # no IPv6 path


def test_day1_runs_read_only_against_loopback(tmp_path):
    out = tmp_path / "day1.json"
    cmd = ["python3", str(HOST / "f3_day1_check.py"), "--target", "127.0.0.1:9",
           "--json", str(out), "--samples", "20", "--interval", "0"]  # fmt: skip
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    report = json.loads(out.read_text())
    assert report["check"] == "diski9-f3-day1/2" and json.loads(r.stdout) == report
    assert report["it1_rule"] == "RTT p95 < 10 ms (TCP handshake, nearest-rank)"
    assert report["targets"]["127.0.0.1:9"]["ipv4"]["failed"] == 20  # closed port, no data sent
    assert report["result"]["IT-1"] == "FAIL"


# ------------------------------------------------------------------ macOS readiness
def _fake_tool(tmp_path, name: str, version_line: str) -> dict:
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    tool = bindir / name
    tool.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    tool.chmod(0o755)
    return {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}


def test_ca_script_refuses_libressl(tmp_path):
    env = _fake_tool(tmp_path, "openssl", "LibreSSL 3.3.6")  # the macOS built-in
    r = subprocess.run([str(OWNER / "f3-sign-server-cert.sh"), str(tmp_path / "x.csr"),
                        str(tmp_path / "out")], env=env, capture_output=True, text=True)  # fmt: skip
    assert r.returncode != 0 and "OpenSSL 3 or later is required" in r.stderr
    assert not (tmp_path / "out").exists()


def test_age_script_refuses_an_age_without_encrypted_identity_support(tmp_path):
    env = _fake_tool(tmp_path, "age", "v1.0.0")
    _fake_tool(tmp_path, "age-keygen", "v1.0.0")
    r = subprocess.run([str(OWNER / "f3-make-age-identities.sh"), str(tmp_path / "out")],
                       env=env, capture_output=True, text=True)  # fmt: skip
    assert r.returncode != 0 and "age 1.1 or later" in r.stderr
    assert not (tmp_path / "out").exists()


def test_prerequisite_check_is_read_only_and_reports_every_item():
    r = subprocess.run([str(OWNER / "f3-check-mac-prereqs.sh")], cwd=ROOT, capture_output=True,
                       text=True, check=True)  # fmt: skip
    for item in ("git", "openssl (on PATH)", "age", "repository"):
        assert item in r.stdout
    assert "prerequisite" in r.stdout.splitlines()[-1]
    assert not re.search(r"/(Users|home)/[^/\s]+", r.stdout)  # no personal paths
