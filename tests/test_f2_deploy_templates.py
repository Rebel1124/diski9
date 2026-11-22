"""Phase 6C.6 Stage F2: the provider-neutral deployment templates are secret-free,
default safely (provider calls and refresh off, caps 10/100, notifications and
backup monitoring off) and match the application's own configuration rules."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
ENV = DEPLOY / "env" / "diski9.env.example"
FILES = sorted(p for p in DEPLOY.rglob("*") if p.is_file())
# hosting providers: none is chosen (SF-02), so none may be named in a template
PROVIDERS = ("aws", "amazon", "ec2", "gcp", "google cloud", "azure", "hetzner", "digitalocean",
             "linode", "akamai", "vultr", "ovh", "fly.io", "render.com", "heroku", "railway",
             "scaleway", "oracle cloud")  # fmt: skip
SECRET_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}"),  # JWTs
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\b[0-9a-f]{32,}\b"),  # long hex keys
    re.compile(r"://[^/\s<>:@]+:[^/\s<>@]+@"),  # URL credentials that are not placeholders
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def env_values() -> dict[str, str]:
    out = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k] = v
    return out


def test_all_templates_exist():
    names = {p.relative_to(DEPLOY).as_posix() for p in FILES}
    assert {"systemd/diski9-web.service", "systemd/diski9-tick.service",
            "systemd/diski9-tick.timer", "systemd/diski9-backup.service",
            "systemd/diski9-backup.timer", "caddy/Caddyfile.example",
            "env/diski9.env.example", "bin/diski9-offhost-copy.example",
            "README.md"} <= names  # fmt: skip


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(DEPLOY).as_posix())
def test_templates_contain_nothing_secret_like(path):
    text = path.read_text()
    for pat in SECRET_PATTERNS:
        assert not pat.search(text), f"{path.name}: {pat.pattern}"
    for token in re.findall(r"[A-Za-z0-9+_-]{32,}", text):  # long random-looking tokens
        mixed = (re.search(r"[a-z]", token) and re.search(r"[A-Z]", token)
                 and re.search(r"[0-9]", token))  # fmt: skip
        assert not mixed, f"{path.name}: token-like string"
    lowered = text.lower()
    for name in PROVIDERS:
        assert not re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", lowered), name


def test_every_env_value_is_a_placeholder_or_a_safe_setting():
    for k, v in env_values().items():
        if any(w in k for w in ("PASSWORD", "SECRET", "KEY", "TOKEN", "DATABASE_URL")) \
                and k != "DISKI9_DATABASE_URL":  # fmt: skip
            assert "<" in v and ">" in v, f"{k} must be a placeholder"


def test_env_template_defaults_are_safe():
    v = env_values()
    assert v["DISKI9_JOBS_PROVIDER_CALLS"] == "off"
    assert v["DISKI9_JOBS_PREPARE_REFRESH"] == "off"
    assert v["DISKI9_JOBS_MAX_REQUESTS_PER_TICK"] == "10"
    assert v["DISKI9_JOBS_MAX_REQUESTS_PER_DAY"] == "100"
    assert v["DISKI9_JOBS_STREAMS"] == "beta"  # never official
    assert v["DISKI9_OPS_NOTIFY"] == "off" and "DISKI9_OPS_WEBHOOK_URL" not in v
    assert v["DISKI9_OPS_BACKUP_EXPECTED"] == "off"
    assert "DISKI9_API_FOOTBALL_KEY" not in v  # commented out
    assert v["DISKI9_DATABASE_URL"].startswith("sqlite:////")  # absolute


def test_env_template_is_accepted_by_the_application_rules():
    from diski9.backend.jobs.config import load_config
    from diski9.backend.ops.config import load_ops_config
    from diski9.wsgi import check_store_location

    v = env_values()
    jobs = load_config(v, environment="production")
    assert jobs.enabled and not jobs.provider_calls and not jobs.prepare_refresh
    assert (jobs.max_requests_per_tick, jobs.max_requests_per_day) == (10, 100)
    assert jobs.streams == ("beta",)
    ops = load_ops_config(v)
    assert not ops.notifications_active and not ops.backup_expected
    check_store_location(v["DISKI9_DATABASE_URL"], v["DISKI9_APP_ENVIRONMENT"])


def _unit(name: str) -> str:
    return (DEPLOY / "systemd" / name).read_text()


def test_web_unit_runs_the_wsgi_entry_point_locally_and_sandboxed():
    u = _unit("diski9-web.service")
    assert "gunicorn diski9.wsgi:server" in u and "--bind 127.0.0.1:8050" in u
    assert "EnvironmentFile=/etc/diski9/diski9.env" in u and "User=diski9" in u
    for d in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true",
              "PrivateTmp=true", "ReadWritePaths=/var/lib/diski9"):  # fmt: skip
        assert d in u
    assert "%(q)" not in u and "%%(U)s" in u  # access log: path without query string


def test_tick_and_backup_units():
    tick, timer = _unit("diski9-tick.service"), _unit("diski9-tick.timer")
    assert "Type=oneshot" in tick and "diski9 jobs tick" in tick
    assert "OnCalendar=*:0/5" in timer and "Persistent=true" in timer
    b, bt = _unit("diski9-backup.service"), _unit("diski9-backup.timer")
    assert "diski9 backup store --out /var/lib/diski9/backups" in b
    assert "ExecStartPost=" in b  # the off-host hook runs only after a successful backup
    assert "OnCalendar=*-*-* 03:30:00 UTC" in bt


def test_offhost_hook_records_only_after_a_successful_copy():
    hook = (DEPLOY / "bin" / "diski9-offhost-copy.example").read_text()
    assert "set -euo pipefail" in hook
    body = hook[hook.index("# ---- replace") :]
    assert body.index("exit 1") < body.index("backup record --kind offhost-copy")
    assert "not verified by Diski 9" in hook


def test_reverse_proxy_template():
    c = (DEPLOY / "caddy" / "Caddyfile.example").read_text()
    assert "reverse_proxy 127.0.0.1:8050" in c
    assert "<allowlisted-address-or-range>" in c and "<site-name>" in c
    assert "path /readyz" in c and "Strict-Transport-Security" in c
    assert "frame-ancestors 'none'" in c and "max_size" in c
    assert "query" in c and "Cookie delete" in c  # access logs without queries or cookies
