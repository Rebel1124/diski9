"""Exception hierarchy for the API-Football client."""

from __future__ import annotations

from typing import Any


class ApiFootballError(Exception):
    """Base class for all API-Football client errors."""


class ApiFootballHTTPError(ApiFootballError):
    """Non-success HTTP status that was not resolved by retrying."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class ApiFootballResponseError(ApiFootballError):
    """HTTP 200 with a populated ``errors`` field in the response envelope.

    API-Football reports most application errors (bad parameters, auth,
    plan limits) this way rather than via HTTP status codes.
    """

    def __init__(self, endpoint: str, errors: dict[str, Any]) -> None:
        super().__init__(f"{endpoint}: {errors}")
        self.endpoint = endpoint
        self.errors = errors


class ApiFootballAuthError(ApiFootballResponseError):
    """Missing/invalid key or inactive subscription."""


class ApiFootballRateLimitError(ApiFootballError):
    """Per-minute rate limit still exceeded after retries, or the provider asked for a
    longer wait than the caller allows (``retry_after``: the requested wait in seconds,
    when known)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuotaGuardError(ApiFootballError):
    """Request refused locally to protect the daily quota or request budget."""


class ForbiddenEndpointError(ApiFootballError):
    """The endpoint is deliberately not used by Diski 9 (e.g. /predictions)."""


class ApiFootballQuotaExceededError(ApiFootballResponseError):
    """Provider reports the daily request allowance has been reached."""
