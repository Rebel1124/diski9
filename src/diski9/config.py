"""Application configuration loaded from environment variables (prefix ``DISKI9_``).

Secrets are never hard-coded. The API-Football key is *optional*: in Claude Code
Cloud the ``x-apisports-key`` header is injected by the environment's network
proxy, so the application must work without a key in its own environment. For
local development outside that proxy, set ``DISKI9_API_FOOTBALL_KEY`` (e.g. in an
untracked ``.env`` file).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DISKI9_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_football_base_url: str = "https://v3.football.api-sports.io/"
    api_football_key: SecretStr | None = Field(
        default=None,
        description="Optional. Leave unset when a network proxy injects x-apisports-key.",
    )
    api_football_timeout_seconds: float = 30.0
    api_football_max_retries: int = 3
    api_football_backoff_seconds: float = 2.0
    # Stop issuing requests when the provider reports fewer daily requests
    # remaining than this. Protects scheduled jobs from exhausting the quota.
    api_football_daily_reserve: int = 500
    # Hard cap on requests a single client instance may issue (None = unlimited).
    api_football_request_budget: int | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
