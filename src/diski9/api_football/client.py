"""Minimal, reusable API-Football v3 client.

Design goals
------------
* One small synchronous class built on ``httpx`` with an injectable transport,
  clock and sleep function so behaviour is fully testable offline.
* Authentication via the ``x-apisports-key`` header. The key is optional
  because in Claude Code Cloud the network proxy injects the header.
* Uniform handling of the response envelope::

      {"get": ..., "parameters": ..., "errors": [] | {...},
       "results": int, "paging": {"current": int, "total": int},
       "response": [...] | {...}}

* Pagination, retries with exponential backoff, rate-limit awareness and a
  local daily-quota guard.
* ``/predictions`` is deliberately blocked: Diski 9 must not use it.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from diski9.config import Settings, get_settings

from .errors import (
    ApiFootballAuthError,
    ApiFootballHTTPError,
    ApiFootballQuotaExceededError,
    ApiFootballRateLimitError,
    ApiFootballResponseError,
    ForbiddenEndpointError,
    QuotaGuardError,
)
from .ratelimit import RateLimiter, RateLimitSnapshot

logger = logging.getLogger(__name__)

AUTH_HEADER = "x-apisports-key"
FORBIDDEN_ENDPOINTS = frozenset({"predictions"})
# Endpoints that the provider documents as not counting towards the daily quota.
QUOTA_EXEMPT_ENDPOINTS = frozenset({"status"})

# Keys observed / documented in the ``errors`` object.
_AUTH_ERROR_KEYS = frozenset({"token", "access", "subscription"})
_RATE_ERROR_KEYS = frozenset({"ratelimit"})
_QUOTA_ERROR_KEYS = frozenset({"requests"})

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def normalise_errors(raw: Any) -> dict[str, Any]:
    """API-Football returns ``[]`` when there are no errors and an object otherwise.

    Some error shapes are lists of messages; normalise everything to a dict.
    """
    if not raw:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, list):
        return {str(i): v for i, v in enumerate(raw)}
    return {"error": raw}


@dataclass(frozen=True)
class ApiResponse:
    """One page of an API-Football response plus request metadata."""

    endpoint: str
    params: dict[str, Any]
    status_code: int
    results: int
    paging_current: int
    paging_total: int
    response: Any
    errors: dict[str, Any]
    rate_limit: RateLimitSnapshot
    retrieved_at: datetime

    @property
    def items(self) -> list[Any]:
        if isinstance(self.response, list):
            return self.response
        if self.response in (None, {}):
            return []
        return [self.response]

    @property
    def is_empty(self) -> bool:
        return not self.items


@dataclass(frozen=True)
class RequestRecord:
    endpoint: str
    params: dict[str, Any]
    status_code: int | None
    results: int | None
    daily_remaining: int | None
    attempt: int


@dataclass
class ApiFootballClient:
    base_url: str = "https://v3.football.api-sports.io/"
    api_key: str | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 3
    backoff_seconds: float = 2.0
    daily_reserve: int = 500
    request_budget: int | None = None
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    rate_limiter: RateLimiter | None = None
    request_log: list[RequestRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.rate_limiter is None:
            self.rate_limiter = RateLimiter(sleep=self.sleep)
        headers = {"Accept": "application/json", "User-Agent": "diski9/0.1"}
        if self.api_key:
            headers[AUTH_HEADER] = self.api_key
        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_seconds,
            transport=self.transport,
        )

    # ------------------------------------------------------------------ setup
    @classmethod
    def from_settings(cls, settings: Settings | None = None, **overrides: Any) -> ApiFootballClient:
        s = settings or get_settings()
        kwargs: dict[str, Any] = dict(
            base_url=s.api_football_base_url,
            api_key=s.api_football_key.get_secret_value() if s.api_football_key else None,
            timeout_seconds=s.api_football_timeout_seconds,
            max_retries=s.api_football_max_retries,
            backoff_seconds=s.api_football_backoff_seconds,
            daily_reserve=s.api_football_daily_reserve,
            request_budget=s.api_football_request_budget,
        )
        kwargs.update(overrides)
        return cls(**kwargs)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ApiFootballClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:  # never expose the key
        key = "***" if self.api_key else None
        return f"ApiFootballClient(base_url={self.base_url!r}, api_key={key})"

    # -------------------------------------------------------------- accounting
    @property
    def requests_made(self) -> int:
        """HTTP requests actually sent (including retries)."""
        return len(self.request_log)

    @property
    def quota_requests_made(self) -> int:
        """Requests that count towards the provider's daily quota."""
        return sum(1 for r in self.request_log if r.endpoint not in QUOTA_EXEMPT_ENDPOINTS)

    @property
    def last_rate_limit(self) -> RateLimitSnapshot:
        assert self.rate_limiter is not None
        return self.rate_limiter.last

    # ---------------------------------------------------------------- requests
    def get(self, endpoint: str, params: Mapping[str, Any] | None = None) -> ApiResponse:
        """GET a single page. Raises on transport/HTTP/envelope errors."""
        endpoint = endpoint.strip("/")
        if endpoint.split("/")[0] in FORBIDDEN_ENDPOINTS:
            raise ForbiddenEndpointError(f"/{endpoint} must not be used by Diski 9")
        clean = {k: v for k, v in (params or {}).items() if v is not None}

        attempt = 0
        while True:
            self._guard_quota(endpoint)
            assert self.rate_limiter is not None
            self.rate_limiter.before_request()
            try:
                resp = self._http.get(endpoint, params=clean)
            except httpx.TransportError as exc:
                self.request_log.append(RequestRecord(endpoint, clean, None, None, None, attempt))
                if attempt >= self.max_retries:
                    raise
                logger.warning("Transport error on /%s (%s); retrying", endpoint, exc)
                self._backoff(attempt)
                attempt += 1
                continue

            snapshot = RateLimitSnapshot.from_headers(resp.headers)
            self.rate_limiter.after_response(snapshot)

            if resp.status_code in _RETRYABLE_STATUS:
                self.request_log.append(
                    RequestRecord(
                        endpoint,
                        clean,
                        resp.status_code,
                        None,
                        snapshot.daily_remaining,
                        attempt,
                    )
                )
                if attempt >= self.max_retries:
                    if resp.status_code == 429:
                        raise ApiFootballRateLimitError(
                            f"/{endpoint}: HTTP 429 after {attempt} retries"
                        )
                    raise ApiFootballHTTPError(resp.status_code, resp.text[:200])
                self._backoff(attempt, retry_after=resp.headers.get("Retry-After"))
                attempt += 1
                continue
            if resp.status_code >= 400:
                self.request_log.append(
                    RequestRecord(
                        endpoint,
                        clean,
                        resp.status_code,
                        None,
                        snapshot.daily_remaining,
                        attempt,
                    )
                )
                raise ApiFootballHTTPError(resp.status_code, resp.text[:200])

            try:
                body = resp.json()
            except ValueError as exc:
                self.request_log.append(
                    RequestRecord(
                        endpoint,
                        clean,
                        resp.status_code,
                        None,
                        snapshot.daily_remaining,
                        attempt,
                    )
                )
                raise ApiFootballHTTPError(resp.status_code, f"invalid JSON: {exc}") from exc

            errors = normalise_errors(body.get("errors"))
            paging = body.get("paging") or {}
            result = ApiResponse(
                endpoint=endpoint,
                params=clean,
                status_code=resp.status_code,
                results=int(body.get("results") or 0),
                paging_current=int(paging.get("current") or 1),
                paging_total=int(paging.get("total") or 1),
                response=body.get("response"),
                errors=errors,
                rate_limit=snapshot,
                retrieved_at=datetime.now(UTC),
            )
            self.request_log.append(
                RequestRecord(
                    endpoint,
                    clean,
                    resp.status_code,
                    result.results,
                    snapshot.daily_remaining,
                    attempt,
                )
            )

            if errors:
                keys = {k.lower() for k in errors}
                if keys & _RATE_ERROR_KEYS and attempt < self.max_retries:
                    logger.warning("Rate limited on /%s; backing off", endpoint)
                    self._backoff(attempt, minimum=60.0 / max(snapshot.minute_limit or 60, 1) * 10)
                    attempt += 1
                    continue
                if keys & _RATE_ERROR_KEYS:
                    raise ApiFootballRateLimitError(f"/{endpoint}: {errors}")
                if keys & _AUTH_ERROR_KEYS:
                    raise ApiFootballAuthError(endpoint, errors)
                if keys & _QUOTA_ERROR_KEYS:
                    raise ApiFootballQuotaExceededError(endpoint, errors)
                raise ApiFootballResponseError(endpoint, errors)
            return result

    def paginate(
        self,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
        *,
        max_pages: int | None = None,
    ) -> Iterator[ApiResponse]:
        """Yield successive pages until ``paging.total`` (or ``max_pages``) is reached.

        Only some endpoints are paginated (e.g. ``/odds``); others return
        ``paging.total == 1`` and reject a ``page`` parameter, so the first
        request is always sent without one.
        """
        base = dict(params or {})
        base.pop("page", None)
        first = self.get(endpoint, base)
        yield first
        total = first.paging_total
        if max_pages is not None:
            total = min(total, max_pages)
        for page in range(2, total + 1):
            yield self.get(endpoint, {**base, "page": page})

    def get_all(
        self,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
        *,
        max_pages: int | None = None,
    ) -> list[Any]:
        items: list[Any] = []
        for page in self.paginate(endpoint, params, max_pages=max_pages):
            items.extend(page.items)
        return items

    # ----------------------------------------------------------------- helpers
    def _guard_quota(self, endpoint: str) -> None:
        if self.request_budget is not None and self.requests_made >= self.request_budget:
            raise QuotaGuardError(f"request budget of {self.request_budget} exhausted")
        if endpoint in QUOTA_EXEMPT_ENDPOINTS:
            return
        remaining = self.last_rate_limit.daily_remaining
        if remaining is not None and remaining <= self.daily_reserve:
            raise QuotaGuardError(
                f"daily remaining ({remaining}) at or below reserve ({self.daily_reserve})"
            )

    def _backoff(self, attempt: int, retry_after: str | None = None, minimum: float = 0.0) -> None:
        delay = self.backoff_seconds * (2**attempt)
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = max(delay, float(retry_after))
        self.sleep(max(delay, minimum))
