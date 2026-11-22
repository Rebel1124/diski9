"""Phase 6C.6 E.1b: bounded provider waits (scheduler only) and the per-minute floor.

Mock transport only; no live provider call. The defaults (``max_wait_seconds=None``)
keep the original behaviour for every CLI command."""

from __future__ import annotations

import httpx
import pytest

from diski9.api_football.errors import ApiFootballRateLimitError
from diski9.api_football.ratelimit import RateLimiter, RateLimitSnapshot

from .conftest import envelope, json_response


def _seq(responses):
    it = iter(responses)
    return lambda request: next(it)


def test_retry_after_within_the_cap_waits_and_retries(make_client, clock):
    client, seen = make_client(
        _seq([httpx.Response(429, headers={"Retry-After": "7"}), json_response(envelope([]))]),
        max_wait_seconds=30,
    )
    client.get("fixtures")
    assert len(seen) == 2 and clock.sleeps == [7.0]


def test_retry_after_above_the_cap_raises_without_sleeping(make_client, clock):
    client, seen = make_client(
        _seq([httpx.Response(429, headers={"Retry-After": "3600"})]), max_wait_seconds=30
    )
    with pytest.raises(ApiFootballRateLimitError) as err:
        client.get("fixtures")
    assert err.value.retry_after == 3600.0
    assert len(seen) == 1 and clock.sleeps == []  # no in-tick sleep at all


def test_the_default_client_keeps_its_original_wait(make_client, clock):
    """CLI commands (no cap) behave exactly as before: they honour Retry-After."""
    client, seen = make_client(
        _seq([httpx.Response(429, headers={"Retry-After": "120"}), json_response(envelope([]))])
    )
    client.get("fixtures")
    assert clock.sleeps == [120.0] and len(seen) == 2


def test_a_rate_limit_body_honours_the_cap(make_client, clock):
    body = json_response(envelope([], errors={"rateLimit": "Too many requests"}),
                         headers={"X-RateLimit-Limit": "1"})  # fmt: skip
    client, _ = make_client(_seq([body]), max_wait_seconds=30)
    with pytest.raises(ApiFootballRateLimitError) as err:
        client.get("fixtures")  # minimum wait 60/1*10 = 600 s > 30 s
    assert err.value.retry_after == 600.0 and clock.sleeps == []


def test_exhausted_retries_still_raise_rate_limit(make_client):
    client, seen = make_client(lambda r: httpx.Response(429), max_retries=1, max_wait_seconds=30)
    with pytest.raises(ApiFootballRateLimitError):
        client.get("fixtures")
    assert len(seen) == 2  # one retry, every attempt went through the limiter hook


class _Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _limiter(**kw):
    c = _Clock()
    return RateLimiter(min_interval_seconds=0.0, clock=c, sleep=c.sleep, **kw), c


def test_minute_floor_keeps_a_tenth_of_the_allowance_for_other_users():
    lim, c = _limiter(minute_floor_ratio=0.1, max_wait_seconds=60)
    lim.before_request()
    lim.after_response(RateLimitSnapshot(7500, 7000, 300, 30))  # 30 left = 10 % of 300
    c.t += 50  # 10 s left in the minute window
    lim.before_request()
    assert c.slept == [pytest.approx(10.0)]


def test_a_long_minute_window_wait_is_raised_not_slept():
    lim, c = _limiter(minute_floor_ratio=0.1, max_wait_seconds=30)
    lim.before_request()
    lim.after_response(RateLimitSnapshot(7500, 7000, 300, 25))
    with pytest.raises(ApiFootballRateLimitError) as err:
        lim.before_request()  # 60 s to the window: above the 30 s cap
    assert err.value.retry_after == pytest.approx(60.0) and c.slept == []


def test_rate_limiter_defaults_are_unchanged():
    lim, c = _limiter()
    lim.before_request()
    lim.after_response(RateLimitSnapshot(7500, 7000, 300, 30))
    lim.before_request()  # 30 left > default floor 2: no wait
    assert c.slept == []
