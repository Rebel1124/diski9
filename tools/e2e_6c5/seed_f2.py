"""Phase 6C.5 Stage F2: extra browser-journey data on isolated e2e databases (local
development only), built through the real services like ``seed.py``.

    uv run python tools/e2e_6c5/seed_f2.py extra   postgresql+psycopg://…/diski9_f2_e2e
    uv run python tools/e2e_6c5/seed_f2.py nochamp postgresql+psycopg://…/diski9_f2_e2e_nochamp

* ``extra`` (after ``seed.py`` on the same database): one more final round in the
  current championship where 30 entrants recover with the same portfolio and the
  other 30 share one identical losing portfolio, so the shared rank 31 spans rows
  31-60 and therefore the 50-row page boundary (journey 3). Its code is appended
  to ``rounds.json`` as ``R15``.
* ``nochamp``: ten competitive rounds of five participants in which nobody
  recovers, so the championship completes with no champion (journey 8).

Refused unless the database name contains ``e2e``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / os.environ.get("E2E_DIR", "tmp/f2")
sys.path.insert(0, str(ROOT / "tests" / "backend"))


def _engine(url: str):
    from sqlalchemy.engine import make_url

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine

    if "e2e" not in (make_url(url).database or ""):
        raise SystemExit("refused: runs only on an e2e database")
    return make_app_engine(BackendDatabaseSettings(environment="development"), url=url)


def extra(url: str) -> None:
    import champ_helpers as h
    from sqlalchemy import text

    from diski9.backend.db import transaction

    eng = _engine(url)
    codes = json.loads((DATA / "rounds.json").read_text())
    accts = json.loads((DATA / "accounts.json").read_text())
    with transaction(eng) as conn:
        people = conn.execute(text(
            "SELECT e.user_id FROM app.entries e JOIN app.rounds r ON r.id = e.round_id "
            "JOIN app.profiles p ON p.user_id = e.user_id WHERE r.code = :c "
            "ORDER BY p.username"), {"c": codes[12]}).scalars().all()  # fmt: skip
        you = conn.execute(text("SELECT user_id FROM app.user_identities WHERE subject = :s"),
                           {"s": accts["you"]["sub"]}).scalar_one()  # fmt: skip
    losers = [u for u in people if u != you][:29] + [you]
    winners = [u for u in people if u not in losers]
    plan = [[(u, h.WIN) for u in winners] + [(u, h.lose(1)) for u in losers]]
    op = h.operator(eng)
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=5))
    h.prepare(eng, op, made)
    h.finalise(eng, h.fresh(eng, op), made[0])
    with transaction(eng) as conn:
        code = conn.execute(text("SELECT code FROM app.rounds WHERE id = :r"),
                            {"r": made[0]["round"]}).scalar_one()  # fmt: skip
    (DATA / "rounds.json").write_text(json.dumps([*codes, code]))
    print(f"R15 {code}: {len(winners)} recovered, {len(losers)} share one losing portfolio")
    eng.dispose()


def nochamp(url: str) -> None:
    import champ_helpers as h
    from sqlalchemy import text

    from diski9.backend.db import transaction

    eng = _engine(url)
    u = h.users(eng, 5, prefix="zero")
    op = h.operator(eng)
    plan = [[(x, h.lose(i)) for i, x in enumerate(u)] for _ in range(10)]
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=5))
    h.prepare(eng, op, made, result_of=h.two_all)
    for w in made:
        h.finalise(eng, h.fresh(eng, op), w)
    with transaction(eng) as conn:
        for r in conn.execute(text("SELECT display_name, status, counted_rounds "
                                   "FROM app.championships ORDER BY ordinal")):  # fmt: skip
            print("championship:", tuple(r))
    eng.dispose()


if __name__ == "__main__":
    {"extra": extra, "nochamp": nochamp}[sys.argv[1]](sys.argv[2])
