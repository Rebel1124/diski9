"""By-ID fixture retrieval for competition settlement (Phase 6C.4, register S-01).

A thin addition beside :mod:`diski9.ingestion.fixtures`; nothing existing changes.
It fetches the raw provider items for an explicit set of fixture IDs, batched
(the provider's ``/fixtures`` endpoint accepts up to 20 IDs per request in its
``ids`` parameter, dash-separated), so a settlement import never re-reads whole
seasons or touches unrelated fixtures.

The same raw items can be passed to the existing
:func:`diski9.ingestion.fixtures.store_fixtures` (football store, unchanged
behaviour) and to the competition observation recorder (PostgreSQL), so both
stores see exactly the same provider response.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .common import parse_api_datetime

MAX_IDS_PER_REQUEST = 20


def batches(ids: Iterable[int], size: int = MAX_IDS_PER_REQUEST) -> list[list[int]]:
    unique = sorted({int(i) for i in ids})
    return [unique[i : i + size] for i in range(0, len(unique), size)]


def fetch_fixtures_by_ids(client: Any, ids: Iterable[int]) -> tuple[list[dict], int]:
    """Raw ``/fixtures`` items for ``ids`` and the number of requests made.

    ``client`` is an :class:`diski9.api_football.client.ApiFootballClient` (quota
    handling and key protection unchanged) or a test double with ``get``."""
    items: list[dict] = []
    requests = 0
    for chunk in batches(ids):
        resp = client.get("fixtures", {"ids": "-".join(str(i) for i in chunk)})
        requests += 1
        items.extend(resp.items)
    return items, requests


def canonical_hash(item: Any) -> str:
    """SHA-256 of the canonical JSON of one raw item (sorted keys, no whitespace)."""
    data = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def evidence_fields(item: dict) -> dict[str, Any]:
    """The settlement-relevant values of one raw item, read exactly as the football
    store reads them (``score.fulltime`` for the 90-minute score). The provider's
    ``periods.first`` is kept separately as supporting evidence only; it is never
    used as an actual kickoff."""
    fx = item["fixture"]
    status = fx.get("status") or {}
    full = (item.get("score") or {}).get("fulltime") or {}
    first = (fx.get("periods") or {}).get("first")
    return {
        "fixture_id": int(fx["id"]),
        "status_short": status.get("short") or None,
        "kickoff_at": parse_api_datetime(fx.get("date")),
        "ft_home": full.get("home"),
        "ft_away": full.get("away"),
        "provider_first_half_at": (
            datetime.fromtimestamp(int(first), UTC) if isinstance(first, int | float) else None
        ),
    }
