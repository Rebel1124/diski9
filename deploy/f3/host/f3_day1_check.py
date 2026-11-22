#!/usr/bin/env python3
"""Diski 9 Stage F3 day-one host check (read-only; Python standard library only).

Run on the new VPS right after purchase (Checkpoint 1, gate G1):

    python3 f3_day1_check.py --target <host>:<port> [--target ...] [--json out.json]
                             [--samples 100] [--interval 0.2]

It changes nothing: it reads system facts, lists listening sockets and measures the
network round-trip time (RTT) to the targets you name (normally the Supabase session
pooler and the project's direct database host, both port 5432; no data is sent, no
login attempted).

RTT methodology (plan §Z.8): each sample is one TCP handshake. connect() returns when
the server's SYN-ACK arrives, so the time is one network round trip plus local kernel
overhead; nothing else is included: no TLS, no PostgreSQL authentication, no query.
The connection is then closed. Samples are spaced (--interval) so that a burst does not
distort the distribution; the 95th percentile uses the nearest-rank method over the
successful samples. ICMP ping is not used (often filtered, and not the database path).
It never contacts API-Football or any other third party you did not name.

Public IP addresses are masked in the output, so the evidence can be returned as is.
Checks evaluated:
  IT-1  VPS-to-Supabase database RTT: p95 strictly below 10 ms for every Supabase target
        (each address family that connects; at least 95 % of samples must succeed)
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

RTT_LIMIT_MS = 10.0  # IT-1: p95 must be strictly below this
MIN_SUCCESS = 0.95
# shown unmasked: private (RFC 1918, ULA, shared CGNAT), loopback and link-local ranges
_READABLE = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "fc00::/7", "::1/128", "fe80::/10")]  # fmt: skip


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


def p95(values: list[float]) -> float:
    """95th percentile, nearest-rank method (no interpolation)."""
    ordered = sorted(values)
    rank = max(1, -(-95 * len(ordered) // 100))  # ceil(0.95 * n)
    return ordered[rank - 1]


def measure(host: str, port: int, family: int, samples: int = 100, interval: float = 0.2) -> dict:
    """RTT samples by TCP handshake (see the module docstring); no data is sent."""
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return {"resolved": False, "error": str(exc)}
    addr = infos[0][4]
    times, errors = [], []
    for i in range(samples):
        if i and interval:
            time.sleep(interval)
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
    res = {
        "resolved": True,
        "address": mask_ip(addr[0]),
        "samples": samples,
        "ok": len(times),
        "failed": len(errors),
    }
    if times:
        times.sort()
        res.update(
            min_ms=round(times[0], 3),
            p50_ms=round(statistics.median(times), 3),
            p95_ms=round(p95(times), 3),
            max_ms=round(times[-1], 3),
        )
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


def _family_ok(res: dict) -> bool:
    return bool(res.get("ok")) and res["ok"] >= MIN_SUCCESS * res.get("samples", res["ok"])


def evaluate(report: dict) -> dict:
    targets = report["targets"]
    if not targets:
        it1 = "NOT RUN"
    else:
        it1 = "PASS"
        for t in targets.values():
            measured = [r for r in (t["ipv4"], t["ipv6"]) if r.get("ok")]
            if (
                not measured
                or not all(_family_ok(r) for r in measured)
                or not all(r["p95_ms"] < RTT_LIMIT_MS for r in measured)
            ):
                it1 = "FAIL"
    has6 = any(a["family"] == "inet6" for a in report["addresses"])
    v6 = [t["ipv6"] for t in targets.values() if _family_ok(t["ipv6"])]
    if not targets:
        it2 = "NOT RUN"
    else:
        it2 = "PASS" if has6 and report["ipv6_default_route"] and v6 else "FAIL"
    return {"IT-1": it1, "IT-2": it2, "IT-9": "MANUAL (open the provider browser console)"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", action="append", default=[], help="host:port (repeatable)")
    ap.add_argument("--json", help="also write the report to this file")
    ap.add_argument("--samples", type=int, default=100, help="RTT samples per target/family")
    ap.add_argument("--interval", type=float, default=0.2, help="seconds between samples")
    args = ap.parse_args(argv)
    if args.samples < 20:
        ap.error("--samples must be at least 20 for a meaningful p95")
    report = {
        "check": "diski9-f3-day1/2",
        "it1_rule": f"RTT p95 < {RTT_LIMIT_MS:g} ms (TCP handshake, nearest-rank)",
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
        report["targets"][t] = {
            "ipv4": measure(host, int(port), socket.AF_INET, args.samples, args.interval),
            "ipv6": measure(host, int(port), socket.AF_INET6, args.samples, args.interval),
        }
    report["result"] = evaluate(report)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        with open(args.json, "w") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
