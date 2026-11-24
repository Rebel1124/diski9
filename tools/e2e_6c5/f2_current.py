"""Phase 6C.5 Stage F2: My Challenge *Current* result-panel states on the isolated
``diski9_f2_e2e`` database (local development only), each made the live current
round through the real services: the signed-in viewer's own test entry
(``submit_test_entry``, the draft and entry services), five development
participants, lock after the real deadline, synthetic results, settlement and
finalisation with the development-only ``as_of``, and the owner's reopening and
correction. No clock is changed. The viewer's authoritative settlement for each
state is written to ``tmp/f2/current_<state>.json`` for ``f2_current.js``.

    uv run python tools/e2e_6c5/f2_current.py refund|void|negative|review|corrected

* ``refund``: every fixture the viewer chose is cancelled (D-33 refund, Net 0.00);
  the round stays valid.
* ``void``: every fixture is cancelled (D-32b round void, round refund).
* ``negative``: the viewer's predictions lose (final, Net negative).
* ``review``: the owner reopens that round with a correction (under review).
* ``corrected``: the round is re-finalised (corrected, Net positive).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / os.environ.get("E2E_DIR", "tmp/f2")
URL = os.environ.get("E2E_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/diski9_f2_e2e")
sys.path.insert(0, str(ROOT / "tests" / "backend"))

WIN = {("1X2", "HOME"): (1, 0), ("1X2", "AWAY"): (0, 1), ("1X2", "DRAW"): (1, 1),
       ("BTTS", "BTTS_YES"): (1, 1), ("BTTS", "BTTS_NO"): (1, 0),
       ("OU25", "OVER_2_5"): (2, 1), ("OU25", "UNDER_2_5"): (1, 0)}  # fmt: skip
LOSE = {("1X2", "HOME"): (0, 1), ("1X2", "AWAY"): (1, 0), ("1X2", "DRAW"): (1, 0),
        ("BTTS", "BTTS_YES"): (1, 0), ("BTTS", "BTTS_NO"): (1, 1),
        ("OU25", "OVER_2_5"): (1, 0), ("OU25", "UNDER_2_5"): (2, 2)}  # fmt: skip


def setup():
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, transaction
    from diski9.backend.services.common import cli_principal

    if "e2e" not in (make_url(URL).database or ""):
        raise SystemExit("refused: runs only on an e2e database")
    os.environ["DISKI9_APP_ENVIRONMENT"] = "development"
    eng = make_app_engine(BackendDatabaseSettings(environment="development"), url=URL)
    accts = json.loads((DATA / "accounts.json").read_text())
    with transaction(eng) as conn:
        uid = conn.execute(text("SELECT user_id FROM app.user_identities WHERE subject = :s"),
                           {"s": accts["you"]["sub"]}).scalar_one()  # fmt: skip
        me = cli_principal(conn, uid, db_now(conn))
    return eng, me


def fresh(eng, role):
    import champ_helpers as h

    return h.operator(eng) if role == "operator" else h.owner(eng)


def open_round(eng, me, label):
    from diski9.backend import dev_championship as dc
    from diski9.backend import settlement_scenarios as sc
    from diski9.backend.db import db_now, transaction
    from diski9.backend.devdata import dev_snapshot
    from diski9.backend.services import rounds as svc

    op = fresh(eng, "operator")
    with transaction(eng) as conn:
        now = db_now(conn)
        config = svc.schedule_config(conn)  # what create_round below binds the round to
    code = f"dev-f2-current-{label}-{now:%H%M%S}"
    snap = dev_snapshot(code, now, now + timedelta(minutes=15, seconds=25), fixtures=40,
                        spacing=timedelta(minutes=1), seed=hash(label) % 1000,
                        config=config)  # fmt: skip
    v = svc.create_round(eng, op, code=code, window_start=snap.window[0],
                         window_end=snap.window[1], development=True)  # fmt: skip
    v = svc.publish_round(eng, op, v.id, snap, source="development")
    sc.submit_test_entry(eng, me, v.id, variant=7)
    dc.ensure_participants(eng, op, 5, preview=False)
    dc.submit_all(eng, op, v.id, count=5, seed=4242)
    return op, v


def my_legs(eng, me, round_id) -> dict:
    """The viewer's locked selections {fixture_id: (market, outcome)}."""
    from sqlalchemy import text

    from diski9.backend.db import transaction

    with transaction(eng) as conn:
        rows = conn.execute(
            text(
                "SELECT s.fixture_id, s.market, s.outcome FROM app.entries e "
                "JOIN app.submission_selections s ON s.submission_id = e.locked_submission_id "
                "WHERE e.round_id = :r AND e.user_id = :u"
            ),
            {"r": round_id, "u": me.user_id},
        ).all()
    assert len(rows) == 9, rows
    return {r.fixture_id: (r.market, r.outcome) for r in rows}


def lock_and_results(eng, op, me, v, result_for):
    from svc_helpers import wait_until

    from diski9.backend.db import transaction
    from diski9.backend.services import results as rs
    from diski9.backend.services import rounds as svc

    wait_until(eng, v.deadline_at + timedelta(seconds=1))
    svc.lock_round(eng, svc.SYSTEM, v.id)
    mine = my_legs(eng, me, v.id)
    rs.set_result_mode(eng, op, v.id, "synthetic")
    at, ko = v.deadline_at + timedelta(seconds=3), v.deadline_at + timedelta(seconds=2)
    wait_until(eng, at)
    with transaction(eng) as conn:
        from diski9.backend.services.snapshots import load_snapshot

        fids = [f.fixture_id for f in load_snapshot(conn, v.id).fixtures]
    for fid in fids:
        res = result_for(fid, mine.get(fid))
        kw = ({"status": "CANC"} if res == "CANC"
              else {"status": "FT", "ft_home": res[0], "ft_away": res[1]})  # fmt: skip
        rs.record_synthetic_observation(eng, op, v.id, fid, observed_at=at, kickoff_at=ko, **kw)
    return mine


def settle_and_finalise(eng, op, v, *, finalise=True):
    import sqlalchemy as sa

    from diski9.backend.db import transaction
    from diski9.backend.db.schema import rounds
    from diski9.backend.services import settlement as st

    with transaction(eng) as conn:
        row = conn.execute(sa.select(rounds).where(rounds.c.id == v.id)).one()
    st.settle_round(eng, op, v.id, as_of=row.settle_cutoff_at + timedelta(seconds=1))
    if finalise:
        refinalise(eng, op, v)


def refinalise(eng, op, v):
    import sqlalchemy as sa

    from diski9.backend.db import transaction
    from diski9.backend.db.schema import rounds
    from diski9.backend.services import corrections as co
    from diski9.backend.services import settlement as st

    with transaction(eng) as conn:
        row = conn.execute(sa.select(rounds).where(rounds.c.id == v.id)).one()
        earliest = st.earliest_finalisation(conn, row)
    out = co.finalise_round(eng, fresh(eng, "operator"), v.id, as_of=earliest)
    assert out.finalised, out.reason


def record(eng, me, v, label):
    from diski9.backend.services import leaderboards as lb
    from diski9.backend.services import participant_results as pr

    s = pr.my_settlement(eng, me, v.id)
    o = lb.my_round_result(eng, me, v.id, include_development=True)
    out = {"label": label, "code": v.code, "state": s.state, "settled": s.settled,
           "gross": None if s.gross is None else f"{s.gross:,.2f}",
           "net": None if s.net is None else f"{s.net:,.2f}", "recovered": s.recovered,
           "entry_refunded": s.entry_refunded, "round_void": s.round_void,
           "version_kind": s.version_kind,
           "official_under_review": None if o is None else o.under_review}  # fmt: skip
    (DATA / f"current_{label}.json").write_text(json.dumps(out, indent=1))
    (DATA / "current_round.json").write_text(json.dumps({"id": str(v.id), "code": v.code}))
    print(json.dumps(out))


def main(step: str) -> None:
    eng, me = setup()
    if step in ("refund", "void", "negative"):
        op, v = open_round(eng, me, step)
        if step == "refund":

            def fn(fid, leg):
                return "CANC" if leg else (1, 0)
        elif step == "void":

            def fn(fid, leg):
                return "CANC"
        else:

            def fn(fid, leg):
                return LOSE.get(leg, (1, 0)) if leg else (1, 0)

        lock_and_results(eng, op, me, v, fn)
        settle_and_finalise(eng, op, v)
        record(eng, me, v, step)
        return
    from diski9.backend.services import corrections as co
    from diski9.backend.services import rounds as svc

    cur = json.loads((DATA / "current_round.json").read_text())
    v = svc.get_round(eng, svc.round_id_for_code(eng, cur["code"]))
    if step == "review":
        mine = [(f, m, o) for f, (m, o) in my_legs(eng, me, v.id).items()]
        fixes = [co.CorrectionInput(f, "FT", *WIN.get((m, o), (1, 0))) for f, m, o in mine]
        own, op = fresh(eng, "owner"), fresh(eng, "operator")
        imp = co.preview_reopen(eng, own, v.id, correction=fixes[0])
        co.reopen_round(eng, own, v.id, reason="F2 Current-tab review", evidence="league statement",
                        confirmation=imp.token, correction=fixes[0])  # fmt: skip
        for c in fixes[1:]:
            imp = co.preview_correction(eng, op, v.id, c)
            co.correct_result(eng, op, v.id, c, reason="F2 Current-tab review",
                              evidence="league statement", confirmation=imp.token)  # fmt: skip
        record(eng, me, v, "review")
    elif step == "corrected":
        refinalise(eng, fresh(eng, "operator"), v)
        record(eng, me, v, "corrected")
    eng.dispose()


if __name__ == "__main__":
    main(sys.argv[1])
