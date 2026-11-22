#!/usr/bin/env python3
"""Diski 9 Stage F3 day-one host check (read-only; Python standard library only).

Run on the new VPS right after purchase (Checkpoint 1, gate G1):

    python3 f3_day1_check.py --target <host>:<port> [--target ...] [--json out.json]

It changes nothing: it reads system facts, lists listening sockets and measures TCP
connection times to the targets you name (normally the Supabase session pooler and the
project's direct database host, both port 5432; no data is sent, no login attempted).
It never contacts API-Football or any other third party you did not name.

Public IP addresses are masked in the output, so the evidence can be returned as is.
Checks evaluated:
  IT-1  Frankfurt proximity: median TCP connect time to every Supabase target <= 10 ms
  IT-2  IPv6: a global IPv6 address, an IPv6 default route and an IPv6 connection to a
        target that resolves to IPv6 (the direct database host is IPv6-only)
  IT-9  is a manual check (the provider's browser console) and is only listed.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import time

RTT_TARGET_MS = 10.0
# shown unmasked: private (RFC 1918, ULA, shared CGNAT), loopback and link-local ranges
_READABLE = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "fc00::/7", "::1/128", "fe80::/10")]  # fmt: skip
ATTEMPTS = 10


def mask_ip(addr: str) -> str:
    """Mask public addresses; keep private, loopback and link-local ones readable."""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return addr
    if any(ip in net for net in _READABLE):
        return addr
    if ip.version == 4:
        a, b, *_ = addr.split(".")
        return f"{a}.{b}.x.x"
    groups = ip.exploded.split(":")
    return ":".join(groups[:2]) + ":x:x:x:x:x:x"


def run_json(cmd: list[str]):
    if not shutil.which(cmd[0]):
        return None
    try:
        return json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None


def addresses(ip_json) -> list[dict]:
    out = []
    for link in ip_json or []:
        for a in link.get("addr_info", []):
            if a.get("scope") == "global":
                out.append(
                    {
                        "if": link.get("ifname"),
                        "family": a.get("family"),
                        "address": mask_ip(a.get("local", "")),
                        "prefix": a.get("prefixlen"),
                    }
                )
    return out


def has_default_route(route_json) -> bool:
    return any(r.get("dst") == "default" for r in (route_json or []))


def listening(ss_text: str) -> list[str]:
    rows = []
    for line in ss_text.splitlines():
        parts = line.split()
        if len(parts) >= 5:
            local = parts[4]
            host, _, port = local.rpartition(":")
            rows.append(f"{parts[0]} {mask_ip(host.strip('[]'))}:{port}")
    return sorted(set(rows))


def measure(host: str, port: int, family: int) -> dict:
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return {"resolved": False, "error": str(exc)}
    addr = infos[0][4]
    times, errors = [], []
    for _ in range(ATTEMPTS):
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(5)
        t = time.perf_counter()
        try:
            s.connect(addr)
            times.append((time.perf_counter() - t) * 1000)
        except OSError as exc:
            errors.append(type(exc).__name__)
        finally:
            s.close()
    res = {"resolved": True, "address": mask_ip(addr[0]), "ok": len(times), "failed": len(errors)}
    if times:
        times.sort()
        res.update(min_ms=round(times[0], 2), median_ms=round(statistics.median(times), 2),
                   max_ms=round(times[-1], 2))  # fmt: skip
    if errors:
        res["errors"] = sorted(set(errors))
    return res


def _ss() -> str:
    if not shutil.which("ss"):
        return ""
    return subprocess.run(["ss", "-tulnH"], capture_output=True, text=True).stdout


def system_facts() -> dict:
    facts = {"kernel": platform.release(), "cpus": os.cpu_count()}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    facts["os"] = line.split("=", 1)[1].strip().strip('"')
        with open("/proc/meminfo") as f:
            facts["mem_gib"] = round(int(f.readline().split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    du = shutil.disk_usage("/")
    facts["disk_gib"] = round(du.total / 1024**3, 1)
    if shutil.which("timedatectl"):
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                           capture_output=True, text=True)  # fmt: skip
        facts["ntp_synchronized"] = r.stdout.strip() or "unknown"
    return facts


def evaluate(report: dict) -> dict:
    targets = report["targets"]
    v4 = [t["ipv4"] for t in targets.values() if t["ipv4"].get("ok")]
    v6 = [t["ipv6"] for t in targets.values() if t["ipv6"].get("ok")]
    medians = [r["median_ms"] for r in v4 + v6]
    it1 = "NOT RUN" if not targets else (
        "PASS" if medians and max(medians) <= RTT_TARGET_MS
        and all(t["ipv4"].get("ok") or t["ipv6"].get("ok") for t in targets.values())
        else "FAIL")  # fmt: skip
    has6 = any(a["family"] == "inet6" for a in report["addresses"])
    it2 = "PASS" if has6 and report["ipv6_default_route"] and v6 else (
        "NOT RUN" if not targets else "FAIL")  # fmt: skip
    return {"IT-1": it1, "IT-2": it2, "IT-9": "MANUAL (open the provider browser console)"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", action="append", default=[], help="host:port (repeatable)")
    ap.add_argument("--json", help="also write the report to this file")
    args = ap.parse_args(argv)
    report = {
        "check": "diski9-f3-day1/1",
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system": system_facts(),
        "addresses": addresses(run_json(["ip", "-j", "addr"])),
        "ipv4_default_route": has_default_route(run_json(["ip", "-j", "-4", "route"])),
        "ipv6_default_route": has_default_route(run_json(["ip", "-j", "-6", "route"])),
        "listening": listening(_ss()),
        "targets": {},
    }
    for t in args.target:
        host, _, port = t.rpartition(":")
        if not host or not port.isdigit():
            ap.error(f"--target must be host:port, got {t!r}")
        report["targets"][t] = {"ipv4": measure(host, int(port), socket.AF_INET),
                                "ipv6": measure(host, int(port), socket.AF_INET6)}  # fmt: skip
    report["result"] = evaluate(report)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        with open(args.json, "w") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
