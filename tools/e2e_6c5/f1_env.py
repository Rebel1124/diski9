"""Shared settings for the Phase 6C.5 F1 local scripts (development only)."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> dict[str, str]:
    env = {}
    with open(ROOT / "tmp/f1/serve.env", encoding="utf-8") as fh:
        for line in fh:
            if "=" in line and not line.startswith("#"):
                key, value = line.strip().split("=", 1)
                env[key] = value
    return env


def load_accounts() -> dict:
    with open(ROOT / "tmp/f1/accounts.json", encoding="utf-8") as fh:
        return json.load(fh)


def sql(query: str) -> str:
    """One value from the F1 development database (local test server)."""
    cmd = ["psql", "-h", "127.0.0.1", "-p", "5433", "-U", "postgres", "-d", "diski9_f1_e2e",
           "-Atc", query]  # fmt: skip
    return subprocess.check_output(cmd).decode().strip()
