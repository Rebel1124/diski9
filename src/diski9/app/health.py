"""Health endpoints for a reverse proxy or service manager (Phase 6C.6 Stage F2,
SF-13).

* ``GET /healthz`` — process liveness: the worker answers. No dependency checks.
* ``GET /readyz`` — dependency readiness: the competition database answers
  ``SELECT 1`` (only when accounts are configured) and the football store exists
  with its required tables. ``200`` when ready, ``503`` otherwise.

Responses carry only fixed status words and component names: never a version, host
name, path, URL, exception text or count. ``Cache-Control: no-store``; GET and HEAD
only. The routes read and set no cookies, and they do not change the
authentication hooks (which resolve a session only when a cookie is sent and check
origin/CSRF only on unsafe methods). The reverse-proxy template answers ``/readyz``
to the host itself only. Failures are logged by exception type only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Flask
from werkzeug.wrappers import Response

log = logging.getLogger(__name__)

HEALTH_PATHS = ("/healthz", "/readyz")
# The football-store tables the web app reads (the store's full schema is checked by
# the backup verifier; readiness needs only what serving requires).
REQUIRED_STORE_TABLES = frozenset(
    {"alembic_version", "competitions", "fixtures", "teams", "odds_fetches", "screener_results"}
)
DB_TIMEOUT_MS = 2000


def _respond(body: dict, status: int) -> Response:
    resp = Response(json.dumps(body), status=status, mimetype="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def check_football_store(engine) -> str:
    """``ok`` or ``unavailable``. A missing SQLite file is reported without opening
    it (opening would create an empty database)."""
    try:
        url = engine.url
        is_file_db = url.get_backend_name() == "sqlite" and url.database not in (
            None,
            "",
            ":memory:",
        )
        if is_file_db and not Path(url.database).is_file():
            return "unavailable"
        from sqlalchemy import inspect

        names = set(inspect(engine).get_table_names())
        return "ok" if names >= REQUIRED_STORE_TABLES else "unavailable"
    except Exception as exc:  # any failure means "not ready"; never echo details
        log.warning("readiness: football store check failed (%s)", type(exc).__name__)
        return "unavailable"


def check_competition_database(engine) -> str:
    """``ok``, ``unavailable`` or ``not_configured`` (guest mode: no accounts)."""
    if engine is None:
        return "not_configured"
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text(f"SET LOCAL statement_timeout = {DB_TIMEOUT_MS}"))
            conn.execute(text("SELECT 1"))
            conn.rollback()
        return "ok"
    except Exception as exc:
        log.warning("readiness: competition database check failed (%s)", type(exc).__name__)
        return "unavailable"


class HealthMiddleware:
    """Answers ``/healthz`` and ``/readyz`` in front of Flask and Dash. Served here
    rather than as Flask routes so that a health probe never triggers Dash's
    first-request setup (which builds the layout from the football store) and never
    passes through the session/CSRF hooks: the probes read no cookies, set none and
    change nothing. Every other request goes to the app unchanged."""

    def __init__(self, app, football_engine, competition_engine=None):
        self.app = app
        self.football_engine = football_engine
        self.competition_engine = competition_engine

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path not in HEALTH_PATHS:
            return self.app(environ, start_response)
        if environ.get("REQUEST_METHOD", "GET") not in ("GET", "HEAD"):
            resp = _respond({"status": "method_not_allowed"}, 405)
            resp.headers["Allow"] = "GET, HEAD"
        elif path == "/healthz":
            resp = _respond({"status": "ok"}, 200)
        else:
            checks = {
                "database": check_competition_database(self.competition_engine),
                "football_store": check_football_store(self.football_engine),
            }
            ready = all(v in ("ok", "not_configured") for v in checks.values())
            resp = _respond({"status": "ready" if ready else "not_ready", "checks": checks},
                            200 if ready else 503)  # fmt: skip
        return resp(environ, start_response)


def register_health(server: Flask, football_engine, competition_engine=None) -> None:
    """Put the health middleware in front of the Flask server's WSGI app."""
    server.wsgi_app = HealthMiddleware(server.wsgi_app, football_engine, competition_engine)
