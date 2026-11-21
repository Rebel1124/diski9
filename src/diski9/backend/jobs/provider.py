"""The scheduler's provider adapter: the existing API-Football client and by-ID
fetch, with the scheduler's per-call allowance applied through the client's own
request budget (quota reserve, retries and key protection unchanged)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...ingestion.results_fetch import fetch_fixtures_by_ids


class ApiFootballProvider:
    def __init__(self, client: Any) -> None:
        self.client = client

    @property
    def requests_made(self) -> int:
        return self.client.requests_made

    def fetch(self, ids: Sequence[int], allowance: int) -> tuple[list[dict], int]:
        # the client refuses (QuotaGuardError) before exceeding this, retries included
        self.client.request_budget = self.client.requests_made + allowance
        return fetch_fixtures_by_ids(self.client, ids)


def api_football_provider() -> ApiFootballProvider:
    from ...api_football import ApiFootballClient

    return ApiFootballProvider(ApiFootballClient.from_settings())
