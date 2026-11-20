"""Helpers for the Phase 6C.5 Stage C championship tests (real PostgreSQL).

Championship membership is chronological over a whole stream, so these tests use
their own database per module (rounds left behind by other tests in the shared
test database would legitimately reserve slots)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import sqlalchemy as sa
from pg_helpers import make_user
from settle_helpers import DEFAULT_ENTRY, confirm_entry, make_settlement_round, shifted
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import make_url
from svc_helpers import principal, wait_until

from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, migrate, transaction
from diski9.backend.db.schema import rounds
from diski9.backend.services import corrections as co
from diski9.backend.services import results as rs
from diski9.backend.services import rounds as svc
from diski9.backend.services import settlement as st

WINNER = {0: (1, 0), 1: (1, 0), 2: (1, 0), 3: (1, 0), 4: (1, 1), 5: (1, 1), 6: (0, 0),
          7: (0, 1), 8: (0, 1)}  # fmt: skip
WIN = tuple(((j + 0) % 9, m, o) for j, (_, m, o) in enumerate(DEFAULT_ENTRY))  # rot(0)
REFUND = shifted(9)  # fixtures 9..17: all cancelled in these tests


def lose(k: int) -> tuple:
    """A portfolio on fixtures 0..8 that does not win every bucket under WINNER."""
    r = 1 + k % 8
    return tuple(((j + r) % 9, m, o) for j, (_, m, o) in enumerate(DEFAULT_ENTRY))


def isolated_engine(pg_url: str, name: str):
    """A freshly migrated database ``name`` on the test server (dropped first)."""
    url = make_url(pg_url)
    admin = create_engine(url.set(database="postgres"), poolclass=pool.NullPool,
                          isolation_level="AUTOCOMMIT")  # fmt: skip
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {name}"))
    admin.dispose()
    target = url.set(database=name).render_as_string(hide_password=False)
    migrate.upgrade(target)
    eng = make_app_engine(BackendDatabaseSettings(environment="test", lock_timeout_ms=5000),
                          url=target)  # fmt: skip
    return eng, target


def drop(pg_url: str, name: str) -> None:
    url = make_url(pg_url)
    admin = create_engine(url.set(database="postgres"), poolclass=pool.NullPool,
                          isolation_level="AUTOCOMMIT")  # fmt: skip
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


def fresh(engine, p):
    with transaction(engine) as conn:
        now = db_now(conn)
    return replace(p, authenticated_at=now, reauthenticated_at=now, now=now)


def operator(engine):
    return fresh(engine, principal(engine, role="operator"))


def users(engine, n: int, prefix: str = "player"):
    with transaction(engine) as conn:
        return [make_user(conn, f"{prefix}{i:02d}") for i in range(n)]


def build(engine, plan, *, published=None, cutoff_after=timedelta(seconds=4)):
    """Development rounds in deadline order; ``plan`` = [[(user, spec), ...], ...].
    Returns one dict per round (locked after the shared deadline wait)."""
    made = []
    with transaction(engine) as conn:
        for k, entries in enumerate(plan):
            at = (published or {}).get(k)
            rid, snap, fids, deadline, cutoff = make_settlement_round(
                # one transaction has one clock: stagger deadlines so creation order is
                # deadline order (as in real weekly rounds)
                conn, deadline_in=timedelta(seconds=3, milliseconds=10 * k),
                cutoff_after=cutoff_after,
                development=True, published_at=at,
            )  # fmt: skip
            ents = [confirm_entry(conn, rid, snap, fids, u, spec)[0] for u, spec in entries]
            made.append({"round": rid, "fixtures": fids, "deadline": deadline, "cutoff": cutoff,
                         "users": [u for u, _ in entries], "entries": ents})  # fmt: skip
    wait_until(engine, max(w["deadline"] for w in made))
    for w in made:
        svc.lock_round(engine, svc.SYSTEM, w["round"])
    return made


def results(engine, op, w, result_of) -> None:
    rs.set_result_mode(engine, op, w["round"], "synthetic")
    at = w["deadline"] + timedelta(milliseconds=1500)
    ko = w["deadline"] + timedelta(seconds=1)
    wait_until(engine, at)
    for i, fid in enumerate(w["fixtures"]):
        res = result_of(i)
        if res == "CANC":
            rs.record_synthetic_observation(engine, op, w["round"], fid, observed_at=at,
                                            status="CANC", kickoff_at=ko)  # fmt: skip
        else:
            rs.record_synthetic_observation(engine, op, w["round"], fid, observed_at=at,
                                            status="FT", kickoff_at=ko, ft_home=res[0],
                                            ft_away=res[1])  # fmt: skip


def winner(i):
    return "CANC" if i >= 9 else WINNER[i]


def void_majority(i):
    return "CANC" if i < 6 or i >= 9 else WINNER[i]


def settle(engine, op, w) -> None:
    wait_until(engine, w["cutoff"] + timedelta(milliseconds=200))
    st.settle_round(engine, op, w["round"])


def finalise(engine, op, w):
    with transaction(engine) as conn:
        earliest = st.earliest_finalisation(
            conn, conn.execute(sa.select(rounds).where(rounds.c.id == w["round"])).one()
        )
    out = co.finalise_round(engine, op, w["round"], as_of=earliest)
    assert out.finalised, out.reason
    return out
