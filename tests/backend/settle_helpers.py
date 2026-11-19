"""Factories for the Phase 6C.4 settlement tests (real PostgreSQL).

A settlement round has twelve fixtures with eligible outcomes in every bucket and
frozen consensus odds that exercise half-up rounding. Entries are confirmed with
the confirmed submission's eight engine states stored exactly as the entries
service stores them, so settlement can be checked against them. Rounds use short
real deadlines (the database clock enforces them) and an explicit cutoff a few
seconds later.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal

from pg_helpers import make_user, unique
from sqlalchemy import insert
from svc_helpers import wait_until

from diski9.backend.db import db_now, transaction
from diski9.backend.db.schema import rounds as rounds_t
from diski9.backend.db.schema import user_roles
from diski9.backend.repositories import portfolios
from diski9.backend.repositories import rounds as rounds_repo
from diski9.backend.services import rounds as svc
from diski9.challenge.config import DEFAULT_CONFIG
from diski9.challenge.structured import evaluate_groups

N_FIXTURES = 12
# (market, outcome, bucket, market probability, odds for fixture i)
OUTCOMES = (
    ("1X2", "HOME", "A", 0.70, lambda i: Decimal(f"1.{31 + i}")),
    ("BTTS", "BTTS_YES", "B", 0.52, lambda i: Decimal(f"1.{85 + i}")),
    ("OU25", "UNDER_2_5", "B", 0.47, lambda i: Decimal(f"2.0{i % 10}")),
    ("1X2", "AWAY", "C", 0.28, lambda i: Decimal(f"3.{15 + i}")),
)
BY_KEY = {(m, o): (b, p, f) for m, o, b, p, f in OUTCOMES}
DEFAULT_ENTRY = (
    (0, "1X2", "HOME"), (1, "1X2", "HOME"), (2, "1X2", "HOME"), (3, "1X2", "HOME"),
    (4, "BTTS", "BTTS_YES"), (5, "BTTS", "BTTS_YES"), (6, "OU25", "UNDER_2_5"),
    (7, "1X2", "AWAY"), (8, "1X2", "AWAY"),
)  # fmt: skip


def shifted(offset: int) -> tuple:
    """The default structure on fixtures ``offset .. offset + 8``."""
    return tuple((i + offset, m, o) for i, m, o in DEFAULT_ENTRY)


def make_settlement_round(
    conn,
    *,
    deadline_in=timedelta(seconds=3),
    cutoff_after=timedelta(seconds=3),
    development: bool = False,
):
    now = db_now(conn)
    code = unique("dev-s-" if development else "2026-W48-s")
    rid = conn.execute(
        insert(rounds_t)
        .values(
            code=code,
            schedule_id=rounds_repo.schedule_id(conn),
            series_id=rounds_repo.series_id(conn, "beta"),
            window_start_at=now - timedelta(days=1),
            window_end_at=now + timedelta(days=3),
            is_development=development,
        )
        .returning(rounds_t.c.id)
    ).scalar_one()
    base = int(uuid.uuid4().int % 10**8) * 100 + 7_000_000_000
    fids = [base + i for i in range(N_FIXTURES)]
    deadline = now + deadline_in
    fx = [
        {
            "fixture_id": f,
            "competition_id": 39,
            "home_team": f"H{f}",
            "away_team": f"A{f}",
            "kickoff_at_publish": deadline + timedelta(minutes=15 + i),
        }
        for i, f in enumerate(fids)
    ]
    offers = []
    for i, f in enumerate(fids):
        for m, o, b, p, odds in OUTCOMES:
            offers.append(
                {
                    "fixture_id": f, "market": m, "outcome": o, "model_prob": p,
                    "consensus_odds": odds(i), "market_prob": p, "bookmaker_groups": 5,
                    "eligible": True, "bucket": b,
                }
            )  # fmt: skip
    snap = rounds_repo.insert_snapshot(
        conn,
        rid,
        as_of=now,
        fingerprint=hashlib.sha256(code.encode()).hexdigest()[:16],
        model_version="goal-model-1.0",
        feasibility={"opens": True},
        fixtures=fx,
        offers=offers,
    )
    rounds_repo.set_status(
        conn,
        rid,
        "open",
        reason="test publish",
        published_at=now,
        deadline_at=deadline,
        settle_cutoff_at=deadline + cutoff_after,
        config_version="broad60-432-v1",
        rules_version="settle/v1",
        scoring_version="points-150-75-v2",
        model_version="goal-model-1.0",
    )
    return rid, snap, fids, deadline, deadline + cutoff_after


def confirm_entry(conn, rid, snap, fids, user, spec=DEFAULT_ENTRY):
    rows = []
    for pos, (i, m, o) in enumerate(spec):
        b, p, odds = BY_KEY[(m, o)]
        rows.append(
            {
                "position": pos, "fixture_id": fids[i], "market": m, "outcome": o,
                "bucket": b, "model_prob": p, "consensus_odds": odds(i), "market_prob": p,
                "bookmaker_groups": 5,
            }
        )  # fmt: skip
    groups = [[(r["market_prob"], r["consensus_odds"]) for r in rows if r["bucket"] == c]
              for c in DEFAULT_CONFIG.bucket_codes]  # fmt: skip
    ev = evaluate_groups(
        groups, DEFAULT_CONFIG.stakes, DEFAULT_CONFIG.nine_fold_credits,
        codes=DEFAULT_CONFIG.bucket_codes,
    )  # fmt: skip
    states = [{"wins": list(s.wins), "p": s.probability, "gross": str(s.gross)} for s in ev.states]
    entry_id = portfolios.create_entry(conn, rid, user)
    sub = portfolios.insert_submission(
        conn,
        {
            "entry_id": entry_id, "round_id": rid, "user_id": user, "snapshot_id": snap,
            "version": 1, "idempotency_key": unique("settle-") + "-key-0000",
            "inputs_hash": hashlib.sha256(unique().encode()).hexdigest(),
            "p_recover_market": ev.p_recover, "p_recover_model": None,
            "expected_gross_market": ev.expected_gross, "expected_gross_model": None,
            "max_gross": ev.max_gross, "states": {"market": states, "model": None},
            "config_version": "broad60-432-v1", "calc_version": "structured-1",
            "model_version": "goal-model-1.0", "rules_version": "settle/v1",
        },
        rows,
    )  # fmt: skip
    assert portfolios.set_current_submission(conn, entry_id, sub, expected_version=0)
    portfolios.add_event(conn, entry_id, "confirmed", submission_id=sub, actor=user)
    return entry_id, sub


def settlement_world(
    engine,
    specs=(DEFAULT_ENTRY,),
    *,
    development: bool = False,
    deadline_in=timedelta(seconds=3),
    cutoff_after=timedelta(seconds=3),
    lock: bool = True,
):
    """A round with one confirmed entry per spec, locked after its deadline."""
    with transaction(engine) as conn:
        rid, snap, fids, deadline, cutoff = make_settlement_round(
            conn, deadline_in=deadline_in, cutoff_after=cutoff_after, development=development
        )
        users, ents = [], []
        for spec in specs:
            u = make_user(conn)
            e, _ = confirm_entry(conn, rid, snap, fids, u, spec)
            users.append(u)
            ents.append(e)
    if lock:
        wait_until(engine, deadline)
        svc.lock_round(engine, svc.SYSTEM, rid)
    return {
        "round": rid, "snapshot": snap, "fixtures": fids, "deadline": deadline,
        "cutoff": cutoff, "users": users, "entries": ents,
    }  # fmt: skip


def grant(engine, user_id, role: str) -> None:
    with transaction(engine) as conn:
        conn.execute(insert(user_roles).values(user_id=user_id, role=role))


def provider_item(fid, status, *, ko, h=None, a=None, first_half=None, extra=None) -> dict:
    """A provider ``/fixtures`` item in the shape of ``tests/fixtures/fixtures_sample.json``."""
    item = {
        "fixture": {
            "id": fid,
            "date": ko.isoformat(),
            "timestamp": int(ko.timestamp()),
            "periods": {"first": int(first_half.timestamp()) if first_half else None,
                        "second": None},
            "status": {"short": status, "long": status, "elapsed": None},
            "venue": {"id": None, "name": None, "city": None},
        },
        "league": {"id": 39, "season": 2026, "round": "Regular Season - 13"},
        "teams": {"home": {"id": 1, "name": "H"}, "away": {"id": 2, "name": "A"}},
        "goals": {"home": h, "away": a},
        "score": {
            "halftime": {"home": None, "away": None},
            "fulltime": {"home": h, "away": a},
            "extratime": {"home": None, "away": None},
            "penalty": {"home": None, "away": None},
        },
    }  # fmt: skip
    if extra:
        item["fixture"].update(extra)
    return item
