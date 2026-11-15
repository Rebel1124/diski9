from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from diski9.api_football import ApiFootballClient
from diski9.api_football.ratelimit import RateLimiter

FIXTURES = Path(__file__).parent / "fixtures"

DEFAULT_HEADERS = {
    "x-ratelimit-requests-limit": "7500",
    "x-ratelimit-requests-remaining": "7000",
    "X-RateLimit-Limit": "300",
    "X-RateLimit-Remaining": "299",
}


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def envelope(
    response: Any, *, errors: Any = None, current: int = 1, total: int = 1
) -> dict[str, Any]:
    items = response if isinstance(response, list) else [response]
    return {
        "get": "x",
        "parameters": {},
        "errors": errors if errors is not None else [],
        "results": len(items),
        "paging": {"current": current, "total": total},
        "response": response,
    }


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_client(
    clock: FakeClock,
) -> Callable[..., tuple[ApiFootballClient, list[httpx.Request]]]:
    """Build a client backed by a MockTransport handler; returns (client, requests)."""

    def _make(handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any):
        seen: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        limiter = RateLimiter(min_interval_seconds=0.0, clock=clock, sleep=clock.sleep)
        client = ApiFootballClient(
            transport=httpx.MockTransport(wrapped),
            sleep=clock.sleep,
            rate_limiter=limiter,
            backoff_seconds=1.0,
            **kwargs,
        )
        return client, seen

    return _make


def json_response(
    body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=body, headers={**DEFAULT_HEADERS, **(headers or {})})
