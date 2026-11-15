from __future__ import annotations

import httpx
import pytest

from diski9.api_football import (
    ApiFootballAuthError,
    ApiFootballHTTPError,
    ApiFootballQuotaExceededError,
    ApiFootballRateLimitError,
    ApiFootballResponseError,
    ForbiddenEndpointError,
    QuotaGuardError,
)
from diski9.api_football.client import normalise_errors
from diski9.config import Settings

from .conftest import envelope, json_response, load_fixture


def test_parses_envelope_and_rate_limit_headers(make_client):
    body = load_fixture("fixtures_sample.json")
    client, seen = make_client(lambda r: json_response(body))
    r = client.get("/fixtures", {"league": 39, "season": 2026, "team": None})

    assert seen[0].url.path == "/fixtures"
    assert dict(seen[0].url.params) == {
        "league": "39",
        "season": "2026",
    }  # None dropped
    assert r.results == 2 and len(r.items) == 2
    assert r.items[0]["fixture"]["id"] == 1557367
    assert r.rate_limit.daily_limit == 7500
    assert r.rate_limit.daily_remaining == 7000
    assert r.rate_limit.minute_remaining == 299
    assert r.retrieved_at.tzinfo is not None
    assert client.requests_made == 1


def test_api_key_header_sent_only_when_configured(make_client):
    client, seen = make_client(lambda r: json_response(envelope([])), api_key="secret-key")
    client.get("leagues")
    assert seen[0].headers["x-apisports-key"] == "secret-key"
    assert "secret-key" not in repr(client)

    client2, seen2 = make_client(lambda r: json_response(envelope([])))
    client2.get("leagues")
    assert "x-apisports-key" not in seen2[0].headers  # proxy-injected mode


def test_settings_key_optional(monkeypatch):
    monkeypatch.delenv("DISKI9_API_FOOTBALL_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.api_football_key is None
    monkeypatch.setenv("DISKI9_API_FOOTBALL_KEY", "abc")
    s = Settings(_env_file=None)
    assert s.api_football_key.get_secret_value() == "abc"
    assert "abc" not in repr(s)


def test_dict_response_items():
    from diski9.api_football.client import ApiResponse
    from diski9.api_football.ratelimit import RateLimitSnapshot

    r = ApiResponse("status", {}, 200, 0, 1, 1, {"a": 1}, {}, RateLimitSnapshot(), None)  # type: ignore[arg-type]
    assert r.items == [{"a": 1}]
    empty = ApiResponse("odds", {}, 200, 0, 1, 1, [], {}, RateLimitSnapshot(), None)  # type: ignore[arg-type]
    assert empty.is_empty


def test_empty_response_is_not_an_error(make_client):
    client, _ = make_client(lambda r: json_response(envelope([])))
    r = client.get("odds", {"fixture": 1})
    assert r.is_empty and r.results == 0


def test_predictions_endpoint_blocked(make_client):
    client, seen = make_client(lambda r: json_response(envelope([])))
    with pytest.raises(ForbiddenEndpointError):
        client.get("/predictions", {"fixture": 1})
    assert seen == []


@pytest.mark.parametrize(
    "errors,exc",
    [
        ({"token": "Error/Missing application key."}, ApiFootballAuthError),
        (
            {"requests": "You have reached the request limit for the day"},
            ApiFootballQuotaExceededError,
        ),
        (
            {"season": "The Season field must contain 4 characters."},
            ApiFootballResponseError,
        ),
        (["The Page field do not exist."], ApiFootballResponseError),
    ],
)
def test_envelope_errors_raise(make_client, errors, exc):
    client, seen = make_client(lambda r: json_response(envelope([], errors=errors)))
    with pytest.raises(exc):
        client.get("fixtures")
    assert len(seen) == 1  # not retried


def test_normalise_errors():
    assert normalise_errors([]) == {}
    assert normalise_errors(None) == {}
    assert normalise_errors({"a": "b"}) == {"a": "b"}
    assert normalise_errors(["x"]) == {"0": "x"}


def test_retries_5xx_then_succeeds(make_client, clock):
    responses = iter(
        [httpx.Response(502, text="bad gateway"), json_response(envelope([{"ok": 1}]))]
    )
    client, seen = make_client(lambda r: next(responses))
    r = client.get("fixtures")
    assert r.items == [{"ok": 1}]
    assert len(seen) == 2
    assert clock.sleeps == [1.0]


def test_retry_exhaustion_raises(make_client, clock):
    client, seen = make_client(lambda r: httpx.Response(503, text="down"), max_retries=2)
    with pytest.raises(ApiFootballHTTPError):
        client.get("fixtures")
    assert len(seen) == 3
    assert clock.sleeps == [1.0, 2.0]  # exponential backoff


def test_http_429_honours_retry_after(make_client, clock):
    responses = iter(
        [httpx.Response(429, headers={"Retry-After": "7"}), json_response(envelope([]))]
    )
    client, _ = make_client(lambda r: next(responses))
    client.get("fixtures")
    assert clock.sleeps == [7.0]


def test_http_429_exhaustion(make_client):
    client, _ = make_client(lambda r: httpx.Response(429), max_retries=1)
    with pytest.raises(ApiFootballRateLimitError):
        client.get("fixtures")


def test_envelope_rate_limit_error_retried(make_client):
    responses = iter(
        [
            json_response(envelope([], errors={"rateLimit": "Too many requests."})),
            json_response(envelope([{"ok": 1}])),
        ]
    )
    client, seen = make_client(lambda r: next(responses))
    assert client.get("fixtures").items == [{"ok": 1}]
    assert len(seen) == 2


def test_transport_error_retried(make_client):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return json_response(envelope([]))

    client, _ = make_client(handler)
    client.get("fixtures")
    assert client.requests_made == 2


def test_non_retryable_4xx(make_client):
    client, seen = make_client(lambda r: httpx.Response(403, text="forbidden"))
    with pytest.raises(ApiFootballHTTPError) as ei:
        client.get("fixtures")
    assert ei.value.status_code == 403
    assert len(seen) == 1


def test_invalid_json(make_client):
    client, _ = make_client(lambda r: httpx.Response(200, text="<html>", headers={}))
    with pytest.raises(ApiFootballHTTPError):
        client.get("fixtures")


def test_pagination_collects_all_pages(make_client):
    def handler(request):
        page = int(request.url.params.get("page", 1))
        return json_response(envelope([{"page": page}], current=page, total=3))

    client, seen = make_client(handler)
    items = client.get_all("odds", {"league": 39, "season": 2026, "page": 9})
    assert items == [{"page": 1}, {"page": 2}, {"page": 3}]
    assert "page" not in seen[0].url.params  # first request never sends page
    assert [r.url.params.get("page") for r in seen[1:]] == ["2", "3"]


def test_pagination_max_pages(make_client):
    client, seen = make_client(lambda r: json_response(envelope([{}], total=5)))
    client.get_all("odds", {"league": 39}, max_pages=2)
    assert len(seen) == 2


def test_daily_reserve_guard(make_client):
    client, seen = make_client(
        lambda r: json_response(envelope([]), headers={"x-ratelimit-requests-remaining": "100"}),
        daily_reserve=500,
    )
    client.get("fixtures")  # first call: remaining unknown, allowed
    with pytest.raises(QuotaGuardError):
        client.get("fixtures")
    client.get("status")  # quota-exempt endpoint still allowed
    assert len(seen) == 2
    assert client.quota_requests_made == 1


def test_request_budget(make_client):
    client, _ = make_client(lambda r: json_response(envelope([])), request_budget=2)
    client.get("a")
    client.get("b")
    with pytest.raises(QuotaGuardError):
        client.get("c")


def test_minute_limit_waits_for_window(make_client, clock):
    client, _ = make_client(
        lambda r: json_response(envelope([]), headers={"X-RateLimit-Remaining": "1"})
    )
    client.get("a")
    clock.now += 10
    client.get("b")
    assert clock.sleeps and abs(clock.sleeps[-1] - 50.0) < 1e-6
