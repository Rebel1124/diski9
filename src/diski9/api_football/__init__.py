"""API-Football v3 provider package."""

from .client import ApiFootballClient, ApiResponse
from .errors import (
    ApiFootballAuthError,
    ApiFootballError,
    ApiFootballHTTPError,
    ApiFootballQuotaExceededError,
    ApiFootballRateLimitError,
    ApiFootballResponseError,
    ForbiddenEndpointError,
    QuotaGuardError,
)

__all__ = [
    "ApiFootballAuthError",
    "ApiFootballClient",
    "ApiFootballError",
    "ApiFootballHTTPError",
    "ApiFootballQuotaExceededError",
    "ApiFootballRateLimitError",
    "ApiFootballResponseError",
    "ApiResponse",
    "ForbiddenEndpointError",
    "QuotaGuardError",
]
