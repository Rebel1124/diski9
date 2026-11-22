"""Phase 6C.5 Stage F3: WSGI entry point for production-style multi-worker load tests
(local development only). Since Phase 6C.6 Stage F2 it reuses the production entry
point ``diski9.wsgi`` (one shared app factory); it only changes to the repository
root first, so the development football store and ``.env`` resolve as for the CLI.

    uv run --extra server gunicorn -w 4 -b 127.0.0.1:8070 --chdir tools f3_wsgi:server
"""

from __future__ import annotations

import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parents[1])

from diski9.wsgi import app, server  # noqa: E402

__all__ = ["app", "server"]
