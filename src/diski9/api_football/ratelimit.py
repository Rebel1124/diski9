"""Rate-limit / quota tracking based on API-Football response headers.

Observed headers (verified November 2026, Pro plan):

* ``x-ratelimit-requests-limit``      daily request allowance (7500)
* ``x-ratelimit-requests-remaining``  daily requests remaining
* ``X-RateLimit-Limit``               per-minute allowance (300)
* ``X-RateLimit-Remaining``           per-minute requests remaining
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field


def _int_header(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class RateLimitSnapshot:
    daily_limit: int | None = None
    daily_remaining: int | None = None
    minute_limit: int | None = None
    minute_remaining: int | None = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> RateLimitSnapshot:
        # httpx.Headers is case-insensitive; plain dicts in tests may not be.
        lower = {k.lower(): v for k, v in headers.items()}
        return cls(
            daily_limit=_int_header(lower, "x-ratelimit-requests-limit"),
            daily_remaining=_int_header(lower, "x-ratelimit-requests-remaining"),
            minute_limit=_int_header(lower, "x-ratelimit-limit"),
            minute_remaining=_int_header(lower, "x-ratelimit-remaining"),
        )


@dataclass
class RateLimiter:
    """Conservative client-side pacing.

    * Enforces a minimum interval between requests.
    * When the per-minute remaining count reaches ``minute_floor`` it waits
      for the window to roll over before sending the next request.
    """

    min_interval_seconds: float = 0.25
    minute_floor: int = 2
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    last: RateLimitSnapshot = field(default_factory=RateLimitSnapshot)
    _last_request_at: float | None = None
    _minute_window_start: float | None = None

    def before_request(self) -> None:
        now = self.clock()
        if self._last_request_at is not None:
            wait = self.min_interval_seconds - (now - self._last_request_at)
            if wait > 0:
                self.sleep(wait)
                now = self.clock()
        remaining = self.last.minute_remaining
        if remaining is not None and remaining <= self.minute_floor:
            start = self._minute_window_start if self._minute_window_start is not None else now
            wait = 60.0 - (now - start)
            if wait > 0:
                self.sleep(wait)
            self.last = RateLimitSnapshot(
                daily_limit=self.last.daily_limit,
                daily_remaining=self.last.daily_remaining,
                minute_limit=self.last.minute_limit,
                minute_remaining=None,
            )
            self._minute_window_start = None
        if self._minute_window_start is None:
            self._minute_window_start = self.clock()
        self._last_request_at = self.clock()

    def after_response(self, snapshot: RateLimitSnapshot) -> None:
        # Keep the previous daily values if a response omits the headers.
        self.last = RateLimitSnapshot(
            daily_limit=snapshot.daily_limit
            if snapshot.daily_limit is not None
            else self.last.daily_limit,
            daily_remaining=(
                snapshot.daily_remaining
                if snapshot.daily_remaining is not None
                else self.last.daily_remaining
            ),
            minute_limit=snapshot.minute_limit,
            minute_remaining=snapshot.minute_remaining,
        )
