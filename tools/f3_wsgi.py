"""Phase 6C.5 Stage F3: a WSGI entry point for production-style multi-worker load
tests (local development only; not a deployment artefact). It builds the app
exactly as ``diski9 serve`` does (``cli.cmd_serve``): the football store, the
competition database and Supabase Auth from the environment.

    uv run --with gunicorn gunicorn -w 4 -b 127.0.0.1:8070 --chdir tools f3_wsgi:server
"""

from __future__ import annotations

import os
from pathlib import Path

# the football store and .env resolve relative to the repository root, as for the CLI
os.chdir(Path(__file__).resolve().parents[1])

from diski9.app import ScreenerData, create_app  # noqa: E402
from diski9.backend.auth.settings import AuthSettings  # noqa: E402
from diski9.db import make_engine  # noqa: E402

_settings = AuthSettings()
_auth = None
if _settings.enabled:
    from diski9.backend.auth.web import AuthRuntime
    from diski9.backend.db import make_app_engine

    _auth = AuthRuntime.create(make_app_engine(), _settings)

app = create_app(ScreenerData(make_engine(None), ttl_seconds=300, tz="Africa/Johannesburg"),
                 auth=_auth)  # fmt: skip
server = app.server
