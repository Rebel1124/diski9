"""The scheduler's provider adapter: the existing API-Football client and by-ID
fetch. Every request the client sends, retries included, first passes the
scheduler's ``reserve()`` (ownership check and durable request record) through the
client's own pre-request hook, and the scheduler uses bounded timeouts and retries
(R5). Quota reserve and key protection are unchanged."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ...ingestion.results_fetch import fetch_fixtures_by_ids


class _ReservingLimiter:
    """Wraps the client's rate limiter: ``before_request`` (called before every
    attempt) records the request first."""

    def __init__(self, inner: Any, reserve: Callable[[], None]) -> None:
        self._inner, self._reserve = inner, reserve

    def before_request(self) -> None:
        self._reserve()
        self._inner.before_request()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class ApiFootballProvider:
    def __init__(self, client: Any) -> None:
        self.client = client

    @property
    def requests_made(self) -> int:
        return self.client.requests_made

    def fetch(self, ids: Sequence[int], reserve: Callable[[], None]) -> tuple[list[dict], int]:
        return self.call(lambda client: fetch_fixtures_by_ids(client, ids), reserve)

    def call(self, fn: Callable[[Any], Any], reserve: Callable[[], None]) -> Any:
        """Run ``fn(client)`` with every request it sends (retries included) reserved
        first (Stage E.1b refresh uses the existing ingestion fetch functions)."""
        original = self.client.rate_limiter
        self.client.rate_limiter = _ReservingLimiter(original, reserve)
        try:
            return fn(self.client)
        finally:
            self.client.rate_limiter = original

    @property
    def quota(self) -> tuple[int | None, int | None]:
        """(daily remaining, daily limit) from the latest response headers."""
        snap = self.client.last_rate_limit
        return snap.daily_remaining, snap.daily_limit


def api_football_provider(
    timeout_seconds: float = 10.0, max_retries: int = 1, max_wait_seconds: float | None = None
) -> ApiFootballProvider:
    """The scheduler's client. With ``max_wait_seconds`` (E.1b) no provider wait inside
    a tick exceeds it, and the per-minute floor keeps a tenth of the provider's minute
    allowance for other users of the key."""
    from ...api_football import ApiFootballClient
    from ...api_football.ratelimit import RateLimiter

    extra: dict[str, Any] = {}
    if max_wait_seconds is not None:
        extra["max_wait_seconds"] = max_wait_seconds
        extra["rate_limiter"] = RateLimiter(
            minute_floor_ratio=0.1, max_wait_seconds=max_wait_seconds
        )
    return ApiFootballProvider(
        ApiFootballClient.from_settings(
            timeout_seconds=timeout_seconds, max_retries=max_retries, **extra
        )
    )
