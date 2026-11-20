"""Seed the Phase 6C.5 Stage E showcase database (local development only).

Builds, through the real services (rounds, entries, lock, synthetic results,
settlement, finalisation, owner reopening, corrections), a development stream with:

* 60 participants: the two onboarded viewer accounts from ``accounts.js`` plus 58
  local-only participants. Their names come from their profiles, and pagination
  needs more than 50.
* Championship A: R1–R12, with R4 a practice round (three entries) and R5 void
  (D-32b). Its ten counted rounds are R1–R3 and R6–R12. In R8 one viewer's entry
  is refunded (all nine void). R12 completes A.
* Championship B: R13 (final) creates it; R14 is settling with six of nine
  results (provisional).
* Corrections afterwards:
  - R2 invalidated after B commenced: A stays completed with nine rounds (D-30a);
  - R3 corrected valid to valid: revision 2, with the two viewers' standings
    becoming joint champions;
  - R7 reopened by the owner: A is under review, showing the last published
    standings.

    uv run python tools/e2e_6c5/seed.py postgresql+psycopg://postgres@127.0.0.1:5433/diski9_e2e_6c5

Refused unless the database name contains ``e2e``. It never touches another database.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "backend"))


def main(url: str) -> None:
    from sqlalchemy.engine import make_url

    if "e2e" not in (make_url(url).database or ""):
        raise SystemExit("refused: the showcase seed runs only on an e2e database")
    import champ_helpers as h
    from pg_helpers import make_user
    from sqlalchemy import text

    from diski9.backend.db import BackendDatabaseSettings, make_app_engine, transaction
    from diski9.backend.services import corrections as co
    from diski9.backend.services import results as rs
    from diski9.backend.services import settlement as st

    eng = make_app_engine(BackendDatabaseSettings(environment="development"), url=url)
    accts = json.loads((ROOT / "tmp" / "e2e_6c5" / "accounts.json").read_text())
    with transaction(eng) as conn:
        you, pat = (
            conn.execute(text("SELECT user_id FROM app.user_identities WHERE subject = :s"),
                         {"s": accts[k]["sub"]}).scalar_one()
            for k in ("you", "pat")
        )  # fmt: skip
        names = ["kasi_king", "lindiwe", "thabo_fc", "zanele9", "sipho_s", "naledi_n", "bongani",
                 "ayanda_a", "lerato_l", "mpho_m"]  # fmt: skip
        fill = [make_user(conn, names[i] if i < len(names) else f"player{i:02d}")
                for i in range(58)]  # fmt: skip
    op, own = h.operator(eng), h.owner(eng)
    everyone = [you, pat, *fill]
    f = fill
    winners = [
        {you, f[1], f[2]}, {pat, f[3]}, {you, f[4], f[5], f[6]}, {you},  # R1-R4 (R4 practice)
        set(), {f[1], f[7]}, {you, pat}, {f[2], f[8]},  # R5 void, R6-R8
        {you}, {f[1], f[3]}, {pat, f[9]}, {you, f[1]},  # R9-R12
        {f[4], you}, {f[5]},  # R13, R14 (provisional)
    ]  # fmt: skip
    # partly void portfolios (some legs on cancelled fixtures 9-17) give varied returns,
    # so ranks and points vary below the winners
    win = list(h.WIN)
    variants = [
        tuple(win[:7] + [(9, "1X2", "AWAY"), (10, "1X2", "AWAY")]),  # Challenger legs void
        tuple(win[:4] + [(9, "BTTS", "BTTS_YES"), (10, "BTTS", "BTTS_YES"),
                         (11, "OU25", "UNDER_2_5")] + win[7:]),  # Balanced legs void
        tuple([(9 + j, "1X2", "HOME") for j in range(4)] + win[4:]),  # Foundation legs void
    ]  # fmt: skip
    plan = []
    for k, champs_win in enumerate(winners):
        entrants = [you, pat, f[1]] if k == 3 else everyone
        partial = {u: variants[j % 3] for j, u in enumerate(f[10 + 3 * k : 19 + 3 * k])}
        row = []
        for i, u in enumerate(entrants):
            if k == 7 and u == pat:
                row.append((u, h.REFUND))
            elif u in champs_win:
                row.append((u, h.WIN))
            else:
                row.append((u, partial.get(u, h.lose(i))))
        plan.append(row)
    print("building 14 rounds ...", flush=True)
    made = h.build(eng, plan, cutoff_after=timedelta(seconds=5))
    for k, w in enumerate(made[:13]):
        h.results(eng, op, w, h.void_majority if k == 4 else h.winner)
    w14 = made[13]
    rs.set_result_mode(eng, op, w14["round"], "synthetic")
    at = w14["deadline"] + timedelta(milliseconds=1500)
    ko = w14["deadline"] + timedelta(seconds=1)
    h.wait_until(eng, at) if hasattr(h, "wait_until") else None
    for i, fid in enumerate(w14["fixtures"][:6]):  # six of nine played so far
        res = h.winner(i)
        rs.record_synthetic_observation(
            eng,
            op,
            w14["round"],
            fid,
            observed_at=at,
            status="FT",
            kickoff_at=ko,
            ft_home=res[0],
            ft_away=res[1],
        )
    for w in made:
        h.settle(eng, op, w)
    print("finalising R1-R13 ...", flush=True)
    for w in made[:13]:
        h.finalise(eng, h.fresh(eng, op), w)
    print("corrections ...", flush=True)
    h.invalidate(eng, own, op, made[1])  # R2: D-30a (B has commenced)
    h.correct_all(eng, own, op, made[2], lambda i: (2, 2))  # R3: nobody recovers any more
    o = h.fresh(eng, own)
    imp = co.preview_reopen(eng, o, made[6]["round"])
    co.reopen_round(eng, o, made[6]["round"], reason="league review",
                    evidence="league statement", confirmation=imp.token)  # fmt: skip
    st.settle_round(eng, h.fresh(eng, op), made[13]["round"])
    with transaction(eng) as conn:
        for r in conn.execute(text(
            "SELECT c.display_name, c.status, c.counted_rounds FROM app.championships c "
            "ORDER BY ordinal")):  # fmt: skip
            print("championship:", tuple(r))
        codes = [conn.execute(text("SELECT code FROM app.rounds WHERE id = :r"),
                              {"r": w["round"]}).scalar_one() for w in made]  # fmt: skip
    (ROOT / "tmp" / "e2e_6c5" / "rounds.json").write_text(json.dumps(codes))
    print("rounds:", ", ".join(codes))
    eng.dispose()


if __name__ == "__main__":
    main(sys.argv[1])
