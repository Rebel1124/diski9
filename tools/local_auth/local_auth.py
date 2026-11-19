"""Run a local Supabase Auth server for development and tests WITHOUT Docker.

Uses a Supabase Auth (GoTrue) binary you built or downloaded, a local PostgreSQL
database prepared with the standard Supabase roles, the mail sink in this folder
and the email templates in ``supabase/templates``. It is a faithful local Auth
server, but not the complete Supabase CLI stack (no Studio, Data API, Realtime):
use ``supabase start`` on a machine with Docker for the full stack
(docs/authentication.md).

    uv run python tools/local_auth/local_auth.py prepare --admin-url postgresql://postgres@127.0.0.1:5433/postgres
    uv run python tools/local_auth/local_auth.py run --gotrue /path/to/gotrue

Development only. Keys generated here are throwaway local keys (written under
``tmp/local_auth``, which is git-ignored).
"""

from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import secrets
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "tmp" / "local_auth"
TEMPLATES = ROOT / "supabase" / "templates"
AUTH_DB = "diski9_auth_local"
# "postgres" exists in hosted Supabase and stock installs, but not in every CI image;
# a Supabase Auth migration grants to it.
SUPABASE_ROLES = (
    "anon",
    "authenticated",
    "service_role",
    "supabase_admin",
    "authenticator",
    "postgres",
)


def _b64(n: int, length: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()


def es256_jwk(kid: str) -> dict:
    """A fresh P-256 signing key as a private JWK (Supabase's recommended ES256)."""
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "kid": kid,
        "use": "sig",
        "key_ops": ["sign", "verify"],
        "x": _b64(pub.x, 32),
        "y": _b64(pub.y, 32),
        "d": _b64(key.private_numbers().private_value, 32),
    }


def legacy_api_key(secret: str, role: str) -> str:
    """An HS256 API key (``apikey`` header) signed with the local legacy secret, as
    the Supabase CLI does for its local anon and service_role keys."""
    import jwt

    return jwt.encode(
        {
            "role": role,
            "iss": "supabase-local",
            "iat": int(time.time()),
            "exp": int(time.time()) + 10 * 365 * 86400,
        },
        secret,
        algorithm="HS256",
    )


def prepare(admin_url: str) -> None:
    """Create the auth database and the roles Supabase Auth expects."""
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (AUTH_DB,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{AUTH_DB}"')
        for role in SUPABASE_ROLES:
            conn.execute(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$;"
            )
        conn.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles "
            "WHERE rolname = 'supabase_auth_admin') THEN CREATE ROLE supabase_auth_admin "
            "NOINHERIT CREATEROLE LOGIN PASSWORD 'local-auth-only'; END IF; END $$;"
        )
    db_url = admin_url.rsplit("/", 1)[0] + f"/{AUTH_DB}"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION supabase_auth_admin")
        conn.execute(f'GRANT CREATE ON DATABASE "{AUTH_DB}" TO supabase_auth_admin')
        conn.execute("ALTER ROLE supabase_auth_admin SET search_path = auth")
    print(f"prepared database {AUTH_DB} and Supabase roles")


def _serve_templates(port: int) -> None:
    def handler(*a, **k):
        return http.server.SimpleHTTPRequestHandler(*a, directory=str(TEMPLATES), **k)

    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def config(args) -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    keys_file = WORK / "keys.json"
    if keys_file.exists():
        state = json.loads(keys_file.read_text())
    else:
        secret = secrets.token_urlsafe(48)
        state = {"legacy_secret": secret, "jwk": es256_jwk(secrets.token_hex(8))}
        state["anon_key"] = legacy_api_key(secret, "anon")
        state["service_role_key"] = legacy_api_key(secret, "service_role")
        keys_file.write_text(json.dumps(state, indent=2))
        keys_file.chmod(0o600)
    legacy = {
        "kty": "oct",
        "k": base64.urlsafe_b64encode(state["legacy_secret"].encode()).rstrip(b"=").decode(),
        "kid": "legacy",
        "alg": "HS256",
        "key_ops": ["verify"],
    }
    return {
        "state": state,
        "env": {
            "GOTRUE_API_HOST": "127.0.0.1",
            "PORT": str(args.port),
            "API_EXTERNAL_URL": f"http://127.0.0.1:{args.port}",
            "GOTRUE_DB_DRIVER": "postgres",
            "DB_NAMESPACE": "auth",
            "DATABASE_URL": args.auth_db_url,
            "GOTRUE_SITE_URL": args.site_url,
            "GOTRUE_URI_ALLOW_LIST": f"{args.site_url}/auth/confirm",
            "GOTRUE_JWT_SECRET": state["legacy_secret"],
            "GOTRUE_JWT_KEYS": json.dumps([state["jwk"], legacy]),
            "GOTRUE_JWT_EXP": "3600",
            "GOTRUE_JWT_AUD": "authenticated",
            "GOTRUE_JWT_ISSUER": f"http://127.0.0.1:{args.port}",
            # hosted Supabase issues role "authenticated" for signed-in users
            "GOTRUE_JWT_DEFAULT_GROUP_NAME": "authenticated",
            "GOTRUE_JWT_ADMIN_ROLES": "service_role,supabase_admin",
            "GOTRUE_DISABLE_SIGNUP": "false",
            "GOTRUE_EXTERNAL_EMAIL_ENABLED": "true",
            "GOTRUE_EXTERNAL_PHONE_ENABLED": "false",
            "GOTRUE_MAILER_AUTOCONFIRM": "false",
            "GOTRUE_MAILER_SECURE_EMAIL_CHANGE_ENABLED": "true",
            "GOTRUE_PASSWORD_MIN_LENGTH": "10",
            "GOTRUE_SECURITY_REFRESH_TOKEN_ROTATION_ENABLED": "true",
            "GOTRUE_SECURITY_REFRESH_TOKEN_REUSE_INTERVAL": "10",
            "GOTRUE_SMTP_HOST": "127.0.0.1",
            "GOTRUE_SMTP_PORT": str(args.smtp_port),
            "GOTRUE_SMTP_ADMIN_EMAIL": "no-reply@diski9.local",
            "GOTRUE_SMTP_SENDER_NAME": "Diski 9 (local)",
            "GOTRUE_SMTP_MAX_FREQUENCY": "1s",
            "GOTRUE_MAILER_URLPATHS_CONFIRMATION": "/verify",
            "GOTRUE_MAILER_URLPATHS_RECOVERY": "/verify",
            "GOTRUE_MAILER_TEMPLATES_CONFIRMATION": f"http://127.0.0.1:{args.template_port}/confirmation.html",
            "GOTRUE_MAILER_TEMPLATES_RECOVERY": f"http://127.0.0.1:{args.template_port}/recovery.html",
            "GOTRUE_RATE_LIMIT_EMAIL_SENT": "1000",
            "GOTRUE_RATE_LIMIT_VERIFY": "1000",
            "GOTRUE_RATE_LIMIT_TOKEN_REFRESH": "1000",
            "GOTRUE_RATE_LIMIT_SIGN_IN_SIGN_UPS": "1000",
            "GOTRUE_LOG_LEVEL": "warn",
        },
    }


def run(args) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from mail_sink import MailSink

    cfg = config(args)
    mail_dir = WORK / "mail"
    sink = MailSink("127.0.0.1", args.smtp_port, mail_dir)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    _serve_templates(args.template_port)
    env = {**os.environ, **cfg["env"]}
    proc = subprocess.Popen([args.gotrue], env=env)
    url = f"http://127.0.0.1:{args.port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    else:
        proc.terminate()
        raise SystemExit("Supabase Auth did not become healthy")
    (WORK / "env").write_text(
        "\n".join(
            [
                f"DISKI9_TEST_SUPABASE_AUTH_URL={url}",
                f"DISKI9_TEST_SUPABASE_ANON_KEY={cfg['state']['anon_key']}",
                f"DISKI9_TEST_SUPABASE_SERVICE_ROLE_KEY={cfg['state']['service_role_key']}",
                f"DISKI9_TEST_SUPABASE_MAIL_DIR={mail_dir}",
            ]
        )
        + "\n"
    )
    print(f"Supabase Auth running at {url}; test settings in {WORK / 'env'}", flush=True)
    try:
        proc.wait()
    finally:
        sink.shutdown()


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prepare")
    pr.add_argument("--admin-url", required=True)
    r = sub.add_parser("run")
    r.add_argument("--gotrue", required=True, help="path to the Supabase Auth binary")
    r.add_argument(
        "--auth-db-url",
        default=f"postgres://supabase_auth_admin:local-auth-only@127.0.0.1:5433/{AUTH_DB}",
    )
    r.add_argument("--port", type=int, default=9999)
    r.add_argument("--smtp-port", type=int, default=2500)
    r.add_argument("--template-port", type=int, default=9998)
    r.add_argument("--site-url", default="http://127.0.0.1:8050")
    a = p.parse_args()
    prepare(a.admin_url) if a.cmd == "prepare" else run(a)


if __name__ == "__main__":
    main()
