"""Production WSGI entry point (Phase 6C.6 Stage F2, SF-13)::

    gunicorn diski9.wsgi:server --workers 2 --bind 127.0.0.1:8050 --timeout 60

The app is built by the shared factory (``diski9.app.factory.build_app``), exactly as
``diski9 serve`` builds it. Unlike the development tooling, this module never changes
the working directory: on a host every location comes from the environment. With
``DISKI9_APP_ENVIRONMENT=production`` a relative SQLite football-store path is
refused, because it would silently depend on the service's working directory.

Gunicorn itself is an optional dependency (``uv sync --extra server``).
"""

from __future__ import annotations

import os


class WsgiConfigError(RuntimeError):
    pass


def check_store_location(url: str, environment: str) -> None:
    """Refuse a relative SQLite football-store path in production."""
    if environment != "production" or not url.startswith("sqlite:"):
        return
    path = url.removeprefix("sqlite:///")
    if url.startswith("sqlite:///:memory:") or not path.startswith("/"):
        raise WsgiConfigError(
            "DISKI9_DATABASE_URL must be an absolute SQLite path in production "
            "(sqlite:////var/lib/diski9/diski9.sqlite); a relative path depends on the "
            "service's working directory"
        )


def _build():
    from diski9.app.factory import build_app
    from diski9.config import get_settings

    check_store_location(
        get_settings().database_url, os.environ.get("DISKI9_APP_ENVIRONMENT", "development")
    )
    return build_app().app


app = _build()
server = app.server
