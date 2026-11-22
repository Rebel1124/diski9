"""Disposable, provably isolated targets for offline rehearsals and restore drills
(Phase 6C.6 Stage F2, safeguard C).

Isolation is never inferred from a name alone. A :class:`DisposableDatabase` is
accepted only when **all** of these hold, and they are re-checked before every
destructive step (migration, population, restore, teardown):

1. the environment is not production;
2. the server is a loopback server (``127.0.0.1``, ``::1``, ``localhost`` or a local
   socket): never a hosted database;
3. the target is not, and does not share a database name with, any configured
   competition-database URL, and is not on the protected list;
4. this process created the database itself under a fresh random name
   (``CREATE DATABASE`` fails if it already exists, so an existing database is never
   adopted), found it empty, and planted a random marker token in it; teardown and
   every destructive step require that exact token.

A :class:`DisposableStore` is a new temporary folder holding a marker file with its
own token; the configured live football store (and the repository's ``data``
folder) is refused. :func:`no_network` refuses every non-loopback connection, so a
rehearsal can only use mock provider transports. If any check cannot be made, the
operation fails closed.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import secrets
import shutil
import socket
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PROTECTED_DATABASES = frozenset({"diski9", "diski9_6c5_acceptance", "diski9_f1_e2e",
                                 "diski9_f2_e2e", "diski9_f2_e2e_nochamp", "postgres",
                                 "template0", "template1"})  # fmt: skip
MARKER_TABLE = "diski9_disposable_target"
STORE_MARKER = ".diski9-disposable"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})
CONFIGURED_URL_VARS = ("DISKI9_APP_DATABASE_URL", "DISKI9_JOBS_DATABASE_URL")
REHEARSAL_LABEL = ("SIMULATED OFFLINE REHEARSAL: disposable database, temporary football "
                   "store, mock API-Football transport, compressed time. Not real-clock "
                   "evidence (Q-14) and not evidence of production behaviour.")  # fmt: skip


class IsolationError(Exception):
    """Isolation could not be proved; nothing destructive was done."""


def refuse_production() -> None:
    for var in ("DISKI9_APP_ENVIRONMENT",):
        if os.environ.get(var, "").strip().lower() == "production":
            raise IsolationError(f"refused: {var}=production")


def _is_loopback(host: str | None) -> bool:
    host = (host or "").strip("[]")
    if host in LOOPBACK_HOSTS or host.startswith("/"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _configured_names() -> set[tuple[str, str]]:
    from sqlalchemy.engine import make_url

    out = set()
    for var in CONFIGURED_URL_VARS:
        v = os.environ.get(var, "").strip()
        if v:
            with contextlib.suppress(Exception):
                u = make_url(v)
                out.add(((u.host or "").lower(), u.database or ""))
    return out


def check_target_name(name: str) -> None:
    if name in PROTECTED_DATABASES:
        raise IsolationError(f"refused: {name} is a protected database")
    if not (name.startswith("diski9_") and name.endswith("_test")) or not name.replace(
            "_", "").isalnum():  # fmt: skip
        raise IsolationError("refused: not a disposable database name")
    if any(db == name for _, db in _configured_names()):
        raise IsolationError("refused: the target is a configured competition database")


@dataclass
class DisposableDatabase:
    server_url: str  # any database on the (loopback) test server, used for admin
    name: str
    token: str

    @property
    def url(self) -> str:
        from sqlalchemy.engine import make_url

        return make_url(self.server_url).set(database=self.name).render_as_string(
            hide_password=False)  # fmt: skip

    def _admin(self):
        from sqlalchemy import create_engine, pool
        from sqlalchemy.engine import make_url

        return create_engine(make_url(self.server_url).set(database="postgres"),
                             poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")  # fmt: skip

    def _target(self):
        from sqlalchemy import create_engine, pool

        return create_engine(self.url, poolclass=pool.NullPool)

    @classmethod
    def create(cls, server_url: str, purpose: str) -> DisposableDatabase:
        from sqlalchemy import text
        from sqlalchemy.engine import make_url

        refuse_production()
        u = make_url(server_url)
        if u.get_backend_name() != "postgresql":
            raise IsolationError("refused: not a PostgreSQL server")
        if not _is_loopback(u.host):
            raise IsolationError("refused: rehearsals run only on a loopback (local) server")
        if not purpose.isalnum() or len(purpose) > 12:
            raise IsolationError("purpose must be 1-12 letters or digits")
        db = cls(server_url, f"diski9_{purpose.lower()}_{secrets.token_hex(6)}_test",
                 secrets.token_hex(16))  # fmt: skip
        check_target_name(db.name)
        admin = db._admin()
        try:
            with admin.connect() as c:  # fails if it exists: an existing DB is never adopted
                c.execute(text(f'CREATE DATABASE "{db.name}"'))
        finally:
            admin.dispose()
        eng = db._target()
        try:
            with eng.begin() as c:
                n = c.execute(text(
                    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN "
                    "('pg_catalog', 'information_schema')")).scalar_one()  # fmt: skip
                if n:
                    raise IsolationError("refused: the new database is not empty")
                c.execute(text(f"CREATE TABLE public.{MARKER_TABLE} (token text NOT NULL, "
                               "purpose text NOT NULL, created_at timestamptz NOT NULL "
                               "DEFAULT now())"))  # fmt: skip
                c.execute(text(f"INSERT INTO public.{MARKER_TABLE} (token, purpose) "
                               "VALUES (:t, :p)"), {"t": db.token, "p": purpose})  # fmt: skip
        finally:
            eng.dispose()
        db.verify()
        return db

    def verify(self) -> None:
        """Re-prove isolation; raises :class:`IsolationError` otherwise."""
        from sqlalchemy import text
        from sqlalchemy.engine import make_url
        from sqlalchemy.exc import SQLAlchemyError

        refuse_production()
        if not _is_loopback(make_url(self.server_url).host):
            raise IsolationError("refused: not a loopback server")
        check_target_name(self.name)
        eng = self._target()
        try:
            with eng.connect() as c:
                rows = c.execute(text(f"SELECT token FROM public.{MARKER_TABLE}")).all()
        except SQLAlchemyError:
            raise IsolationError("refused: the target carries no disposable marker") from None
        finally:
            eng.dispose()
        if [r.token for r in rows] != [self.token]:
            raise IsolationError("refused: the disposable marker does not match")

    def drop(self) -> None:
        from sqlalchemy import text

        self.verify()
        admin = self._admin()
        try:
            with admin.connect() as c:
                c.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        finally:
            admin.dispose()


@dataclass
class DisposableStore:
    folder: Path
    token: str

    @property
    def path(self) -> Path:
        return self.folder / "football.sqlite"

    @property
    def url(self) -> str:
        return f"sqlite:///{self.path}"

    @classmethod
    def create(cls, base: Path | None = None) -> DisposableStore:
        refuse_production()
        folder = Path(tempfile.mkdtemp(prefix="diski9-disposable-", dir=base))
        s = cls(folder, secrets.token_hex(16))
        (folder / STORE_MARKER).write_text(s.token)
        s.verify()
        return s

    def verify(self) -> None:
        from diski9.config import get_settings
        from diski9.db.engine import PROJECT_ROOT

        refuse_production()
        real = Path(os.path.realpath(self.folder))
        live_url = os.environ.get("DISKI9_DATABASE_URL") or get_settings().database_url
        if live_url.startswith("sqlite:///"):
            live = Path(os.path.realpath(live_url.removeprefix("sqlite:///")))
            if live.parent == real or Path(os.path.realpath(self.path)) == live:
                raise IsolationError("refused: the configured live football store")
        data = Path(os.path.realpath(PROJECT_ROOT / "data"))
        if real == data or data in real.parents:
            raise IsolationError("refused: the repository's data folder")
        marker = self.folder / STORE_MARKER
        if not marker.is_file() or marker.read_text() != self.token:
            raise IsolationError("refused: the store folder carries no matching marker")

    def remove(self) -> None:
        self.verify()
        shutil.rmtree(self.folder)


@contextlib.contextmanager
def no_network() -> Iterator[None]:
    """Refuse every non-loopback network connection (mock transports and the local
    test database still work)."""
    real_connect = socket.socket.connect

    def guarded(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) else str(address)
            if not _is_loopback(host):
                raise ConnectionRefusedError("network disabled during an offline rehearsal")
        return real_connect(sock, address)

    socket.socket.connect = guarded
    try:
        yield
    finally:
        socket.socket.connect = real_connect
