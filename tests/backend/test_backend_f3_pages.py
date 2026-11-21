"""Phase 6C.5 Stage F3: the O(page) leaderboard page queries (shared ranks from the
display-order neighbours, joint champions bounded by the first lower rank) return
exactly what the previous whole-set window function returned, on every page of a
weekly board and a championship board with ties across page boundaries and joint
champions beyond the first page. Own database, two-round championships."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa
from champ_helpers import (
    WIN,
    build,
    drop,
    finalise,
    isolated_engine,
    lose,
    operator,
    prepare,
    set_required,
    users,
)
from svc_helpers import principal

from diski9.backend.db import transaction
from diski9.backend.services import leaderboards as lb

DB = "diski9_f3_pages_test"
DEV = {"include_development": True}


@pytest.fixture(scope="module")
def world(pg_url):
    eng, _ = isolated_engine(pg_url, DB)
    set_required(eng, 2)
    op = operator(eng)
    u = users(eng, 130)

    # 55 identical winners (joint first beyond page 1 of 50), then groups of shared
    # losing portfolios, so shared ranks straddle the 50- and 100-row boundaries
    def partial(v):  # the first v legs on cancelled fixtures: distinct returns
        return tuple([(9 + j, m, o) for j, (_, m, o) in enumerate(WIN[:v])] + list(WIN[v:]))

    def spec(i):
        if i < 55:
            return WIN
        if i < 63:
            return partial(i - 54)  # eight entrants with unshared ranks
        return lose(1 + i % 3)

    plan = [[(x, spec(i)) for i, x in enumerate(u)] for _ in range(2)]
    made = build(eng, plan, cutoff_after=timedelta(seconds=4))
    prepare(eng, op, made)
    for w in made:
        finalise(eng, op, w)
    yield {"engine": eng, "w": made, "u": u}
    eng.dispose()
    drop(pg_url, DB)


def truth(conn, table, key, value):
    """(display_order -> shared) by the original whole-set window function."""
    rows = conn.execute(sa.text(
        f"SELECT display_order, rank, count(*) OVER (PARTITION BY rank) AS c FROM app.{table} "
        f"WHERE {key} = :v"), {"v": value}).all()  # fmt: skip
    return {r.display_order: (r.rank is not None and r.c > 1) for r in rows}


def test_weekly_pages_match_the_window_function(world):
    eng, w = world["engine"], world["w"][0]
    with transaction(eng) as conn:
        s = conn.execute(sa.text("SELECT id FROM app.score_sets WHERE round_id = :r"),
                         {"r": w["round"]}).scalar_one()  # fmt: skip
        want = truth(conn, "round_scores", "score_set_id", s)
    first = lb.weekly_board(eng, w["round"], **DEV)
    seen = 0
    for page in range(1, first.pages + 1):
        b = lb.weekly_board(eng, w["round"], page=page, **DEV)
        for i, r in enumerate(b.rows):
            assert r.shared == want[(page - 1) * 50 + i + 1], (page, i)
            seen += 1
    assert seen == first.total and first.pages == 3
    assert any(want.values()) and not all(want.values())
    viewer = principal(eng, user_id=world["u"][120])
    with transaction(eng) as conn:
        mine = conn.execute(sa.text("SELECT display_order FROM app.round_scores WHERE "
                                    "score_set_id = :s AND user_id = :u"),
                            {"s": s, "u": world["u"][120]}).scalar_one()  # fmt: skip
    b = lb.weekly_board(eng, w["round"], viewer=viewer, **DEV)  # page 1, viewer elsewhere
    assert b.me is not None and b.me_page == (mine - 1) // 50 + 1 and b.me.shared == want[mine]


def test_championship_pages_and_joint_champions_beyond_page_one(world):
    eng = world["engine"]
    cb = lb.championship_board(eng, stream="development", **DEV)
    assert cb.status == "completed" and cb.total == 130
    with transaction(eng) as conn:
        vid = conn.execute(sa.text("SELECT id FROM app.championship_versions ORDER BY id DESC "
                                   "LIMIT 1")).scalar_one()  # fmt: skip
        want = truth(conn, "championship_standings", "version_id", vid)
        leaders = conn.execute(sa.text("SELECT count(*) FROM app.championship_standings WHERE "
                                       "version_id = :v AND rank = 1 AND points > 0"),
                               {"v": vid}).scalar()  # fmt: skip
    assert leaders == 55
    for page in range(1, cb.pages + 1):
        b = lb.championship_board(eng, stream="development", page=page, **DEV)
        assert len(b.champions) == 55  # all joint champions, though 5 are on page 2
        for i, r in enumerate(b.rows):
            assert r.shared == want[(page - 1) * 50 + i + 1], (page, i)
