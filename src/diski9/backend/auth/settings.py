"""Authentication settings (prefixes ``DISKI9_SUPABASE_`` and ``DISKI9_APP_``).

Only the server uses these values. The publishable (anon) key is sent by the server
to Supabase Auth; no Supabase key, token or secret is ever sent to the browser, and
the service-role / secret key is not used by the web application at all.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthConfigError(RuntimeError):
    """Authentication is misconfigured (messages never contain secrets)."""


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DISKI9_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    # Supabase Auth (server-side use only)
    supabase_auth_url: str | None = Field(
        default=None,
        description="Auth base URL: https://<ref>.supabase.co/auth/v1, "
        "http://127.0.0.1:54321/auth/v1 (Supabase CLI) or the local harness URL",
    )
    supabase_publishable_key: SecretStr | None = None  # anon / publishable key
    supabase_jwt_issuer: str | None = None  # defaults to the auth URL
    supabase_jwt_audience: str = "authenticated"

    # Application
    app_environment: Literal["development", "test", "production"] = Field(
        default="development", alias="DISKI9_APP_ENVIRONMENT"
    )
    app_site_url: str = Field(default="http://127.0.0.1:8050", alias="DISKI9_APP_SITE_URL")
    app_secret_key: SecretStr | None = Field(default=None, alias="DISKI9_APP_SECRET_KEY")
    app_token_encryption_key: SecretStr | None = Field(
        default=None, alias="DISKI9_APP_TOKEN_ENCRYPTION_KEY"
    )
    app_cookie_secure: bool | None = Field(default=None, alias="DISKI9_APP_COOKIE_SECURE")
    app_trusted_proxies: int = Field(default=0, ge=0, le=3, alias="DISKI9_APP_TRUSTED_PROXIES")
    app_terms_version: str = Field(default="beta-2026-11", alias="DISKI9_APP_TERMS_VERSION")

    # Session policy (T-12; sensitive-operation recency proposed in Phase 6C.2)
    session_idle_days: int = Field(default=14, ge=1, le=14)
    session_absolute_days: int = Field(default=30, ge=1, le=30)
    operator_recency_hours: int = Field(default=12, ge=1, le=12)
    sensitive_recency_minutes: int = Field(default=15, ge=1, le=15)
    provider_refresh_margin_minutes: int = Field(default=5, ge=1, le=30)

    @field_validator("supabase_auth_url", "app_site_url")
    @classmethod
    def _http_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return v.rstrip("/")

    @model_validator(mode="after")
    def _production_rules(self) -> AuthSettings:
        if self.app_environment == "production":
            if urlsplit(self.app_site_url).scheme != "https":
                raise ValueError("DISKI9_APP_SITE_URL must use https in production")
            if self.supabase_auth_url and urlsplit(self.supabase_auth_url).scheme != "https":
                raise ValueError("DISKI9_SUPABASE_AUTH_URL must use https in production")
            if self.app_cookie_secure is False:
                raise ValueError("cookies must be Secure in production")
        return self

    # ------------------------------------------------------------ derived values
    @property
    def enabled(self) -> bool:
        return bool(self.supabase_auth_url and self.supabase_publishable_key)

    @property
    def issuer(self) -> str:
        return (self.supabase_jwt_issuer or self.supabase_auth_url or "").rstrip("/")

    @property
    def cookie_secure(self) -> bool:
        if self.app_cookie_secure is not None:
            return self.app_cookie_secure
        return urlsplit(self.app_site_url).scheme == "https"

    @property
    def session_cookie_name(self) -> str:
        # the __Host- prefix requires Secure, path=/ and no Domain attribute
        return "__Host-d9_session" if self.cookie_secure else "d9_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-d9_csrf" if self.cookie_secure else "d9_csrf"

    @property
    def site_origin(self) -> str:
        p = urlsplit(self.app_site_url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def idle_lifetime(self) -> timedelta:
        return timedelta(days=self.session_idle_days)

    @property
    def absolute_lifetime(self) -> timedelta:
        return timedelta(days=self.session_absolute_days)

    def secret(self) -> bytes:
        if self.app_secret_key is None:
            raise AuthConfigError("DISKI9_APP_SECRET_KEY is not set (see .env.example)")
        raw = self.app_secret_key.get_secret_value().encode()
        if len(raw) < 32:
            raise AuthConfigError("DISKI9_APP_SECRET_KEY must be at least 32 characters")
        return raw

    def encryption_key(self) -> bytes:
        if self.app_token_encryption_key is None:
            raise AuthConfigError("DISKI9_APP_TOKEN_ENCRYPTION_KEY is not set (see .env.example)")
        key = self.app_token_encryption_key.get_secret_value().encode()
        try:
            if len(base64.urlsafe_b64decode(key)) != 32:
                raise ValueError
        except ValueError:
            raise AuthConfigError(
                "DISKI9_APP_TOKEN_ENCRYPTION_KEY must be a Fernet key "
                "(generate one with: uv run diski9 account generate-keys)"
            ) from None
        return key

    def publishable_key(self) -> str:
        if self.supabase_publishable_key is None:
            raise AuthConfigError("DISKI9_SUPABASE_PUBLISHABLE_KEY is not set")
        return self.supabase_publishable_key.get_secret_value()
