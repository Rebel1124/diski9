"""Competition-backend database settings (prefix ``DISKI9_APP_``).

Separate from :mod:`diski9.config`, whose ``DISKI9_DATABASE_URL`` is the SQLite
football store (unchanged during Phase 6C, D-39). Values come from the
environment or an untracked ``.env`` file; ``.env.example`` documents them without
real credentials.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

Environment = Literal["development", "test", "production"]


class BackendDatabaseError(RuntimeError):
    """Configuration or connection problem (messages never contain credentials)."""


def _check_postgres(url: str, name: str) -> str:
    try:
        parsed = make_url(url)
    except Exception as exc:  # noqa: BLE001 - the message must not echo the URL
        raise ValueError(f"{name} is not a valid database URL") from exc
    if parsed.get_backend_name() != "postgresql":
        raise ValueError(f"{name} must be a PostgreSQL URL (postgresql+psycopg://...)")
    if parsed.get_driver_name() not in ("psycopg", ""):
        raise ValueError(f"{name} must use the psycopg (version 3) driver")
    if not parsed.database:
        raise ValueError(f"{name} must name a database")
    return url


class BackendDatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DISKI9_APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,  # never echo a URL (with its password) in errors
    )

    environment: Environment = "development"
    database_url: SecretStr | None = Field(
        default=None, description="postgresql+psycopg://user:password@host:port/database"
    )
    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=5, ge=0, le=50)
    pool_timeout_seconds: float = Field(default=10.0, gt=0)
    pool_recycle_seconds: int = Field(default=1800, ge=60)
    statement_timeout_ms: int = Field(default=15_000, ge=100)
    lock_timeout_ms: int = Field(default=5_000, ge=50)
    echo_sql: bool = False
    # "session": a direct connection or Supabase's session pooler (port 5432), which
    # keep session settings; "transaction": Supabase's transaction pooler (port
    # 6543), where settings are applied per transaction and prepared statements are
    # disabled. Transaction-level locks and the database clock work in both.
    pooler_mode: Literal["session", "transaction"] = "session"

    @field_validator("database_url")
    @classmethod
    def _postgres_only(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None:
            _check_postgres(v.get_secret_value(), "DISKI9_APP_DATABASE_URL")
        return v

    @model_validator(mode="after")
    def _no_test_database_in_production(self) -> BackendDatabaseSettings:
        if self.environment == "production" and self.database_url is not None:
            db = make_url(self.database_url.get_secret_value()).database or ""
            if db.endswith("_test"):
                raise ValueError("a *_test database cannot be used in production")
        return self

    def url(self) -> str:
        if self.database_url is None:
            raise BackendDatabaseError(
                "DISKI9_APP_DATABASE_URL is not set; see .env.example and docs/backend.md"
            )
        return self.database_url.get_secret_value()

    def safe_url(self) -> str:
        """The URL with the password hidden, for logs and error messages."""
        if self.database_url is None:
            return "<unset>"
        return make_url(self.database_url.get_secret_value()).render_as_string(hide_password=True)


def require_test_database_url(url: str | None, environment: str = "test") -> str:
    """Validate a URL intended for automated tests: PostgreSQL, a database whose
    name ends in ``_test``, and never in a production environment."""
    if not url:
        raise BackendDatabaseError("DISKI9_APP_TEST_DATABASE_URL is not set")
    _check_postgres(url, "DISKI9_APP_TEST_DATABASE_URL")
    if environment == "production":
        raise BackendDatabaseError("tests refuse to run with DISKI9_APP_ENVIRONMENT=production")
    if not (make_url(url).database or "").endswith("_test"):
        raise BackendDatabaseError("the test database name must end in '_test'")
    return url
