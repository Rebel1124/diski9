"""Phase 6C.5 Stage F2: the authoritative expectations for the browser journeys,
read from the read services (the same ones the pages use) and written to
``tmp/f2/expect.json`` (git-ignored). ``journeys.js`` compares the visible pages
with these values, so a screenshot is never the only evidence.

    uv run python tools/e2e_6c5/f2_expect.py <url> [<no-champion url>]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / os.environ.get("E2E_DIR", "tmp/f2")
sys.path.insert(0, str(ROOT / "tests" / "backend"))


def rank(r) -> str:
    if r.position is None:
        return "—"
    return ("=" if r.shared else "") + str(r.position)


def weekly(wb) -> dict:
    return {
        "state": wb.state,
        "classification": wb.classification,
        "round_void": wb.round_void,
        "corrected": wb.corrected,
        "revision": wb.revision,
        "total": wb.total,
        "pages": wb.pages,
        "page": wb.page,
        "me_page": wb.me_page,
        "me_status": wb.me_status,
        "me": None
        if wb.me is None
        else {
            "rank": rank(wb.me),
            "name": wb.me.name,
            "points": wb.me.points,
            "returned": str(wb.me.returned),
        },  # fmt: skip
        "championship": wb.championship,
        "rows": [
            {
                "rank": rank(r),
                "name": r.name,
                "points": r.points,
                "me": r.is_me,
                "returned": None if r.returned is None else f"{r.returned:,.2f}",
            }
            for r in wb.rows
        ],  # fmt: skip
    }


def champ(cb) -> dict:
    return {
        "name": cb.name,
        "status": cb.status,
        "counted": cb.counted_rounds,
        "required": cb.rounds_required,
        "champions": list(cb.champions),
        "no_champion": cb.no_champion,
        "under_review": cb.under_review,
        "corrected_after_completion": cb.corrected_after_completion,
        "fewer_rounds": cb.corrected_with_fewer_rounds,
        "me_status": cb.me_status,
        "me": None
        if cb.me is None
        else {"rank": ("=" if cb.me.shared else "") + str(cb.me.position), "points": cb.me.points},
        "rows": [
            {
                "rank": ("=" if r.shared else "") + str(r.position),
                "name": r.name,
                "points": r.points,
                "me": r.is_me,
            }
            for r in cb.rows
        ],  # fmt: skip
    }


def main(url: str, nochamp: str | None) -> None:
    from dataclasses import replace

    from sqlalchemy import text

    from diski9.backend.db import BackendDatabaseSettings, db_now, make_app_engine, transaction
    from diski9.backend.services import challenge_history as ch
    from diski9.backend.services import leaderboards as lb
    from diski9.backend.services.common import cli_principal

    accts = json.loads((DATA / "accounts.json").read_text())
    codes = json.loads((DATA / "rounds.json").read_text())
    eng = make_app_engine(BackendDatabaseSettings(environment="development"), url=url)
    viewers = {"guest": None}
    names = {}
    with transaction(eng) as conn:
        for k in ("you", "pat"):
            uid = conn.execute(text("SELECT user_id FROM app.user_identities WHERE subject = :s"),
                               {"s": accts[k]["sub"]}).scalar_one()  # fmt: skip
            viewers[k] = cli_principal(conn, uid, db_now(conn))
            names[k] = viewers[k].username
    dev = {"include_development": True}
    out = {"codes": codes, "names": names, "weekly": {}, "champ": {}, "history": {}}
    for who, v in viewers.items():
        out["weekly"][who] = {}
        for n, code in enumerate(codes, 1):
            rid = lb.round_id_for(eng, code, stream="development", **dev)
            first = lb.weekly_board(eng, rid, viewer=v, **dev)
            out["weekly"][who][f"R{n}"] = weekly(first)
            if first.pages > 1:
                out["weekly"][who][f"R{n}p2"] = weekly(lb.weekly_board(eng, rid, viewer=v, page=2,
                                                                       **dev))  # fmt: skip
        cl = lb.championship_list(eng, stream="development", **dev)
        out["champ"][who] = {c.name: champ(lb.championship_board(
            eng, stream="development", name=c.name, viewer=v, **dev)) for c in cl}  # fmt: skip
        if v is not None:
            h = ch.my_history(eng, v, stream="development", **dev)
            s = ch.my_statistics(eng, v, stream="development", **dev)
            out["history"][who] = {
                "total": h.total, "pages": h.pages,
                "rows": [{"code": r.round_code, "state": r.state, "classification":
                          r.classification, "void": r.round_void, "refunded": r.entry_refunded,
                          "points": r.weekly_points} for r in h.rows],
                "stats": {"played": s.played, "recoveries": s.recoveries,
                          "allocated": f"{s.allocated:,.2f}", "returned": f"{s.returned:,.2f}"},
            }  # fmt: skip
    eng.dispose()
    if nochamp:
        e2 = make_app_engine(BackendDatabaseSettings(environment="development"), url=nochamp)
        cl = lb.championship_list(e2, stream="development", **dev)
        out["nochamp"] = champ(lb.championship_board(e2, stream="development", name=cl[0].name,
                                                     **dev))  # fmt: skip
        e2.dispose()
    del replace
    (DATA / "expect.json").write_text(json.dumps(out, indent=1, default=str))
    print("expectations:", DATA / "expect.json")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
