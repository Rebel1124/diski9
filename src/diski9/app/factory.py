"""One place that builds the Diski 9 web app from the environment (Phase 6C.6 Stage
F2, SF-13). Used by ``diski9 serve`` (development server), ``diski9.wsgi``
(production WSGI entry point under Gunicorn) and ``tools/f3_wsgi.py`` (local load
tests), so the three cannot drift apart.

The app is built exactly as before: the football store (``DISKI9_DATABASE_URL``),
and, when Supabase Auth is configured, accounts and the competition database.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine


@dataclass(frozen=True)
class BuiltApp:
    app: object  # dash.Dash
    accounts_enabled: bool


def build_app(
    engine: Engine | None = None,
    *,
    ttl_seconds: float = 300,
    tz: str = "Africa/Johannesburg",
) -> BuiltApp:
    """Build the app. ``engine`` is the football store (default: the configured
    ``DISKI9_DATABASE_URL``). Accounts are enabled only when Supabase Auth is
    configured; otherwise the app runs in guest mode, unchanged."""
    from diski9.app import ScreenerData, create_app
    from diski9.backend.auth.settings import AuthSettings
    from diski9.db import make_engine

    auth = None
    settings = AuthSettings()
    if settings.enabled:
        from diski9.backend.auth.web import AuthRuntime
        from diski9.backend.db import make_app_engine

        auth = AuthRuntime.create(make_app_engine(), settings)
    data = ScreenerData(engine if engine is not None else make_engine(None),
                        ttl_seconds=ttl_seconds, tz=tz)  # fmt: skip
    return BuiltApp(app=create_app(data, auth=auth), accounts_enabled=auth is not None)
