"""Factories for the competition-backend tests (imported by conftest and tests)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import Connection

from diski9.backend.db import db_now
from diski9.backend.repositories import accounts, portfolios, rounds


# ---------------------------------------------------------------- factories
def unique(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def make_user(conn: Connection, username: str | None = None) -> uuid.UUID:
    uid = accounts.create_user(conn)
    accounts.link_identity(conn, uid, "supabase", unique("sub-"))
    name = username or unique("user")
    alias = f"Anonymous {int(uuid.uuid4().int % 90_000_000) + 10_000_000}"
    accounts.create_profile(conn, uid, name, alias)
    return uid


BUCKETS = ["A", "A", "A", "A", "B", "B", "B", "C", "C"]


def make_round(
    conn: Connection, *, deadline_in: timedelta = timedelta(hours=2), fixtures: int = 9
) -> tuple[uuid.UUID, int, list[int]]:
    """An open round with a snapshot of ``fixtures`` fixtures, one eligible HOME offer
    each (4 A, 3 B, 2 C for the first nine), plus an ineligible DRAW offer."""
    now = db_now(conn)
    code = unique("2026-W48-")
    rid = rounds.create_round(
        conn,
        code,
        rounds.schedule_id(conn),
        rounds.series_id(conn, "beta"),
        now - timedelta(days=1),
        now + timedelta(days=3),
    )
    base = int(uuid.uuid4().int % 10**9) * 100
    fids = [base + i for i in range(fixtures)]
    fx = [
        {
            "fixture_id": f,
            "competition_id": 39,
            "home_team": f"H{f}",
            "away_team": f"A{f}",
            "kickoff_at_publish": now + deadline_in + timedelta(minutes=15 + i),
        }
        for i, f in enumerate(fids)
    ]
    offers = []
    for i, f in enumerate(fids):
        b = BUCKETS[i % 9]
        p = {"A": 0.7, "B": 0.5, "C": 0.3}[b]
        offers.append(
            {
                "fixture_id": f,
                "market": "1X2",
                "outcome": "HOME",
                "model_prob": p,
                "consensus_odds": Decimal("1.40")
                if b == "A"
                else Decimal("2.00")
                if b == "B"
                else Decimal("3.20"),
                "market_prob": p,
                "bookmaker_groups": 5,
                "eligible": True,
                "bucket": b,
            }
        )
        offers.append(
            {
                "fixture_id": f,
                "market": "1X2",
                "outcome": "DRAW",
                "model_prob": 0.1,
                "consensus_odds": Decimal("9.00"),
                "market_prob": 0.1,
                "bookmaker_groups": 5,
                "eligible": False,
                "bucket": None,
                "ineligible_reason": "below_20",
            }
        )
    snap = rounds.insert_snapshot(
        conn,
        rid,
        as_of=now,
        fingerprint=hashlib.sha256(code.encode()).hexdigest()[:16],
        model_version="goal-model-1.0",
        feasibility={"opens": True},
        fixtures=fx,
        offers=offers,
    )
    rounds.set_status(
        conn,
        rid,
        "open",
        reason="test publish",
        published_at=now,
        deadline_at=now + deadline_in,
        settle_cutoff_at=now + deadline_in + timedelta(days=3),
        config_version="broad60-432-v1",
        rules_version="settle/v1",
        scoring_version="points-150-75-v2",
        model_version="goal-model-1.0",
    )
    return rid, snap, fids


def selections_for(fids: list[int]) -> list[dict]:
    return [
        {
            "position": i,
            "fixture_id": f,
            "market": "1X2",
            "outcome": "HOME",
            "bucket": BUCKETS[i],
            "model_prob": 0.5,
            "consensus_odds": Decimal("2.00"),
            "market_prob": 0.5,
            "bookmaker_groups": 5,
        }
        for i, f in enumerate(fids[:9])
    ]


def submission_values(
    entry_id, round_id, user_id, snapshot_id, version: int = 1, key: str | None = None
) -> dict:
    return {
        "entry_id": entry_id,
        "round_id": round_id,
        "user_id": user_id,
        "snapshot_id": snapshot_id,
        "version": version,
        "idempotency_key": key or unique("idem-") + "-key-0000",
        "inputs_hash": hashlib.sha256(unique().encode()).hexdigest(),
        "p_recover_market": 0.35,
        "p_recover_model": 0.33,
        "expected_gross_market": 96.5,
        "expected_gross_model": 94.25,
        "max_gross": Decimal("1234.56"),
        "states": {"states": []},
        "config_version": "broad60-432-v1",
        "calc_version": "structured-1",
        "model_version": "goal-model-1.0",
        "rules_version": "settle/v1",
    }


def confirm(conn: Connection, round_id, snapshot_id, fids, user_id, key: str | None = None):
    """Minimal confirm for tests: entry, first submission, current pointer, event."""
    entry_id = portfolios.create_entry(conn, round_id, user_id)
    sub = portfolios.insert_submission(
        conn,
        submission_values(entry_id, round_id, user_id, snapshot_id, key=key),
        selections_for(fids),
    )
    assert portfolios.set_current_submission(conn, entry_id, sub, expected_version=0)
    portfolios.add_event(conn, entry_id, "confirmed", submission_id=sub, actor=user_id)
    return entry_id, sub
