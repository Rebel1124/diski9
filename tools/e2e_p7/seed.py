"""Phase 7 CP3 end-to-end scenario (local development only; disposable database).

Builds the achievement lifecycle through the REAL services: confirmed entries,
lock, results, settlement, finalisation and publication, owner reopening and
corrections. Nothing is synthetic at the presentation layer; every number the app
shows comes from published results. Stages run in order, with browser checks
in between (``checks.js``):

* ``base``: development stream (viewer "you"; "pat" and four local participants
  enter losing portfolios):
  - R1 competitive, X portfolio (4 Home, 3 Over 2.5, 2 Draws), all correct:
    Foundation, Balanced, Challenger, Goals Guru, Draw Dynamo;
  - R2 competitive, Y portfolio (4 Home, 3 BTTS Yes, 2 Away), all correct:
    Foundation, Balanced, Challenger, BTTS Bonanza;
  - R3 practice (three entries), R4 void (D-32b), R5 "you" refunded (all nine
    void): nothing;
  - R6 competitive with a void Challenger pick: Foundation and Balanced only.
  Result: Semi-Pro (3, 3, 2, 1, 1, 1). Also one beta round (Y, a3-432-v1,
  provider evidence, real clock): beta (1, 1, 1, 0, 1, 0), never mixed.
* ``pro``: R7 X, R8 Y, R9 X, R10 Y: Pro (7, 7, 6, 3, 3, 3).
* ``reopen``: the owner reopens R9 and corrects fixture 7 (a draw becomes an away
  win). Under review, the last published result still counts (Pro).
* ``republish``: R9 is re-finalised: Challenger and Draw Dynamo are lost there:
  Semi-Pro (7, 7, 5, 3, 3, 2).
* ``corrupt``: inserts a malformed settlement revision for "you" in R10 to show
  the unavailable state (the database is disposable).

Each stage writes the authoritative expectations from the service to
``tmp/e2e_p7/expect.json``.

    uv run python tools/e2e_p7/seed.py <url> none|base|pro|reopen|republish|corrupt

Refused unless the database name contains ``p7_e2e``.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tmp" / "e2e_p7"
sys.path.insert(0, str(ROOT / "tests" / "backend"))

HOME4 = tuple((i, "1X2", "HOME") for i in range(4))
X = HOME4 + tuple((i, "OU25", "OVER_2_5") for i in (4, 5, 6)) + ((7, "1X2", "DRAW"),
                                                               (8, "1X2", "DRAW"))  # fmt: skip
Y = HOME4 + tuple((i, "BTTS", "BTTS_YES") for i in (4, 5, 6)) + ((7, "1X2", "AWAY"),
                                                                (8, "1X2", "AWAY"))  # fmt: skip


def res_x(i):
    return (3, 0) if i < 4 else (2, 1) if i < 7 else (1, 1) if i < 9 else (1, 0)


def res_y(i):
    return (2, 0) if i < 4 else (1, 1) if i < 7 else (0, 1) if i < 9 else (1, 0)


def main(url: str, stage: str) -> None:
    from sqlalchemy.engine import make_url

    if "p7_e2e" not in (make_url(url).database or ""):
        raise SystemExit("refused: the Phase 7 scenario runs only on a p7_e2e database")
    import champ_helpers as h
    from settle_helpers import provider_item
    from sqlalchemy import text
    from svc_helpers import principal, wait_until

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine, transaction
    from diski9.backend.repositories import results as results_repo
    from diski9.backend.services import achievements as ac
    from diski9.backend.services import corrections as co
    from diski9.backend.services import settlement as st
    from diski9.ingestion.results_fetch import canonical_hash, evidence_fields

    eng = make_app_engine(BackendDatabaseSettings(environment="development"), url=url)
    accts = json.loads((DATA / "accounts.json").read_text())
    state_file = DATA / "rounds.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    with transaction(eng) as conn:
        you, pat = (
            conn.execute(text("SELECT user_id FROM app.user_identities WHERE subject = :s"),
                         {"s": accts[k]["sub"]}).scalar_one()
            for k in ("you", "pat")
        )  # fmt: skip
    if "others" not in state:
        state["others"] = [str(u) for u in h.users(eng, 4, prefix="p7local")]
        h.set_required(eng, 2)
    from uuid import UUID

    others = [UUID(u) for u in state["others"]]
    field = [pat, *others]  # five losing entrants beside "you"
    op, own = h.operator(eng), h.owner(eng)

    def plan(spec):
        return [(you, spec)] + [(u, h.lose(i + 1)) for i, u in enumerate(field)]

    def save(names, made):
        for name, w in zip(names, made, strict=True):
            state[name] = {
                k: (str(v) if k in ("round",) else v) for k, v in w.items() if k in ("round",)
            } | {
                "fixtures": w["fixtures"],
                "entries": [str(e) for e in w["entries"]],
                "deadline": w["deadline"].isoformat(),
                "cutoff": w["cutoff"].isoformat(),
            }

    def load(name):
        from datetime import datetime

        s = state[name]
        return {"round": UUID(s["round"]), "fixtures": s["fixtures"],
                "entries": [UUID(e) for e in s["entries"]],
                "deadline": datetime.fromisoformat(s["deadline"]),
                "cutoff": datetime.fromisoformat(s["cutoff"])}  # fmt: skip

    if stage == "none":  # nothing published yet: the honest Beginner empty state
        pass
    elif stage == "base":

        def partial(i):
            return "CANC" if i >= 8 else h.WINNER[i]

        made = h.build(eng, [plan(X), plan(Y),
                             [(you, X), (pat, h.lose(1)), (others[0], h.lose(2))],
                             plan(X), plan(h.REFUND), plan(h.WIN)],
                       extra_outcomes=True)  # fmt: skip
        h.prepare(eng, op, made, [res_x, res_y, res_x, h.void_majority, h.winner, partial])
        for w in made:
            h.finalise(eng, h.fresh(eng, op), w)
        save(["R1", "R2", "R3", "R4", "R5", "R6"], made)
        # one beta round: provider evidence, real clock (correction window 0)
        (rb,) = h.build(eng, [plan(Y)], development=False, extra_outcomes=True,
                        config_version="a3-432-v1", correction_window_hours=0)  # fmt: skip
        at = rb["deadline"] + timedelta(milliseconds=1500)
        wait_until(eng, at)
        for i, fid in enumerate(rb["fixtures"]):
            item = provider_item(fid, "FT", ko=rb["deadline"] + timedelta(seconds=1),
                                 h=res_y(i)[0], a=res_y(i)[1])  # fmt: skip
            with transaction(eng) as conn:
                results_repo.record_evidence(conn, source="api-football", fixture_id=fid,
                                             observed_at=at, raw=item,
                                             raw_hash=canonical_hash(item),
                                             fields=evidence_fields(item))  # fmt: skip
        h.settle(eng, op, rb)
        with transaction(eng) as conn:
            r = conn.execute(text("SELECT * FROM app.rounds WHERE id = :r"),
                             {"r": rb["round"]}).one()  # fmt: skip
            wait_until(eng, st.earliest_finalisation(conn, r) + timedelta(milliseconds=50))
        assert co.finalise_round(eng, h.fresh(eng, op), rb["round"]).finalised
        save(["RB"], [rb])
    elif stage == "pro":
        made = h.build(eng, [plan(X), plan(Y), plan(X), plan(Y)], extra_outcomes=True)
        h.prepare(eng, op, made, [res_x, res_y, res_x, res_y])
        for w in made:
            h.finalise(eng, h.fresh(eng, op), w)
        save(["R7", "R8", "R9", "R10"], made)
    elif stage == "reopen":
        w = load("R9")
        h.reopen_correct(eng, own, op, w, [co.CorrectionInput(w["fixtures"][7], "FT", 0, 1)])
    elif stage == "republish":
        h.finalise(eng, h.fresh(eng, op), load("R9"))
    elif stage == "corrupt":
        w = load("R10")
        with transaction(eng) as conn:
            s = conn.execute(text("SELECT run_id FROM app.score_sets WHERE round_id = :r "
                                  "ORDER BY revision DESC LIMIT 1"),
                             {"r": w["round"]}).scalar_one()  # fmt: skip
            cur = conn.execute(text("SELECT * FROM app.entry_settlements WHERE entry_id = :e "
                                    "ORDER BY revision DESC LIMIT 1"),
                               {"e": w["entries"][0]}).one()  # fmt: skip
            legs = dict(cur.legs)
            legs["legs"] = legs["legs"][:8]
            conn.execute(text(
                "INSERT INTO app.entry_settlements (run_id, entry_id, submission_id, revision, "
                "gross, net, legs, basis, complete) VALUES (:run, :e, :s, :rev, :g, :n, "
                "CAST(:legs AS jsonb), :b, true)"),
                {"run": s, "e": w["entries"][0], "s": cur.submission_id,
                 "rev": cur.revision + 1, "g": cur.gross, "n": cur.net,
                 "legs": json.dumps(legs), "b": cur.basis})  # fmt: skip
    else:
        raise SystemExit(f"unknown stage {stage!r}")
    state_file.write_text(json.dumps(state, indent=1))

    # authoritative expectations, straight from the service
    def summary(uid, stream):
        p = principal(eng, user_id=uid)
        try:
            a = ac.my_achievements(eng, p, stream=stream, include_development=True)
        except ac.AchievementIntegrityError:
            return {"unavailable": True}
        return {"level": str(a.level), "counts": [a.counts[b] for b in ac.BADGES],
                "total": a.total, "eligible_rounds": a.eligible_rounds,
                "categories_met": a.progress.categories_met}  # fmt: skip

    def round_badges(name):
        try:
            r = ac.my_round_badges(eng, principal(eng, user_id=you), UUID(state[name]["round"]),
                                   stream="beta" if name == "RB" else "development",
                                   include_development=True)  # fmt: skip
        except ac.AchievementIntegrityError:
            return "unavailable"
        return None if r is None else [str(b) for b in r.badges]

    codes = {}
    with transaction(eng) as conn:
        for name, s in state.items():
            if name.startswith("R"):
                codes[name] = conn.execute(text("SELECT code FROM app.rounds WHERE id = :r"),
                                           {"r": s["round"]}).scalar_one()  # fmt: skip
    expect = {
        "stage": stage,
        "you": {"development": summary(you, "development"), "beta": summary(you, "beta"),
                "official": summary(you, "official")},
        "pat": {"development": summary(pat, "development")},
        "rounds": {n: {"code": codes[n], "badges": round_badges(n)} for n in codes},
    }  # fmt: skip
    (DATA / "expect.json").write_text(json.dumps(expect, indent=1))
    print(json.dumps(expect["you"]), "| rounds:",
          {n: v["badges"] for n, v in expect["rounds"].items()})  # fmt: skip


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
