"""Phase 6C.5 Stage D: generated correction sequences against real PostgreSQL and
the real 6C.4 services (spec §16.3 R-7, R-8).

Each seed builds its own database with seven development rounds (two-round
championships, so rollover and historical boundaries happen early) whose initial
results are valid or D-32b void, then applies a seeded random sequence of
*legitimate* operations, choosing only among those the current state allows:

* first finalisation of a settled round;
* owner reopening + corrections + re-finalisation: invalidation (D-32b),
  restoration of a D-32b void, valid-to-valid correction;
* owner reopening + operator invalidation (never restorable afterwards);
* a repeated finalisation of a final round (refused by 6C.4);
* a re-finalisation whose championship processing fails (rolled back), then retried;
* reconciliation (processing the stream again).

After every operation: no integrity finding (weekly results equal a re-scoring of
the settlement; standings equal a from-scratch recomputation with the unchanged
engine; counters, slots, statuses and versions agree), at most two counted rounds
per championship, immutable membership, no champion without points, operator
invalidations never restored, fixed championships untouched by corrections in
other championships, and reads write nothing. The seed and the operation log are
printed so any failure can be replayed exactly."""

from __future__ import annotations

import random

import pytest
import sqlalchemy as sa
from champ_helpers import (
    WIN,
    build,
    correct_all,
    drop,
    finalise,
    fresh,
    invalidate,
    isolated_engine,
    lose,
    operator,
    owner,
    prepare,
    reopen_correct,
    restore,
    set_required,
    two_all,
    users,
    void_majority,
    winner,
)

from diski9.backend.db import transaction
from diski9.backend.services import championships as ch
from diski9.backend.services import corrections as co
from diski9.backend.services import leaderboards as lb

SEEDS = (20261120, 7, 42, 2026)
STEPS = 30
ROUNDS = 7


def state(eng):
    with transaction(eng) as conn:
        members = dict(conn.execute(sa.text(
            "SELECT round_id, championship_id FROM app.championship_rounds")).all())  # fmt: skip
        champs = conn.execute(sa.text(
            "SELECT id, display_name, current_version, boundary_fixed_at IS NOT NULL AS fixed, "
            "counted_rounds, rounds_required, status FROM app.championships")).all()  # fmt: skip
        roles = dict(conn.execute(sa.text(
            "SELECT round_id, role FROM app.championship_rounds")).all())  # fmt: skip
        rows = conn.execute(sa.text("SELECT count(*) FROM app.championship_versions")).scalar()
    return members, champs, roles, rows


def check(eng, history, operator_void, touched_champ, before_champs):
    with transaction(eng) as conn:
        ins = ch.inspect_stream(conn, "development")
    assert ins.findings == (), ins.findings
    members, champs, roles, _ = state(eng)
    for rid, cid in members.items():  # membership is immutable
        assert history.setdefault(rid, cid) == cid
    for c in champs:
        assert c.counted_rounds <= c.rounds_required
        b = lb.championship_board(eng, stream="development", name=c.display_name,
                                  include_development=True)  # fmt: skip
        if b.champions:
            assert b.status == "completed" and all(r.points > 0 for r in b.rows[:1])
    for rid in operator_void:
        assert roles.get(rid) in (None, "void")
    # fixed championships other than the corrected one are untouched
    for c in before_champs:
        if c.fixed and c.id != touched_champ:
            now = next(x for x in champs if x.id == c.id)
            assert now.current_version == c.current_version


def counts(eng):
    with transaction(eng) as conn:
        return [conn.execute(sa.text(f"SELECT count(*) FROM app.{t}")).scalar_one()
                for t in ("score_sets", "championship_versions", "audit_log")]  # fmt: skip


@pytest.mark.parametrize("seed", SEEDS)
def test_generated_correction_sequences_on_postgresql(pg_url, seed, monkeypatch):
    rng = random.Random(seed)
    name = f"diski9_champ_seq_{seed}_test"
    eng, _ = isolated_engine(pg_url, name)
    try:
        set_required(eng, 2)
        op, own = operator(eng), owner(eng)
        u = users(eng, 5)
        plan = [[(u[i], WIN if i == k % 5 else lose(i)) for i in range(5)] for k in range(ROUNDS)]
        initial = [void_majority if rng.random() < 0.3 else winner for _ in range(ROUNDS)]
        made = build(eng, plan)
        prepare(eng, op, made, initial)
        status = ["settled"] * ROUNDS  # settled | valid | void | operator_void
        first_void = {k for k in range(ROUNDS) if initial[k] is void_majority}
        operator_void: set = set()
        history: dict = {}
        log = []
        for step in range(STEPS):
            options = []
            for k in range(ROUNDS):
                s = status[k]
                if s == "settled":
                    options.append(("finalise", k))
                elif s == "valid":
                    options += [("invalidate", k), ("correct", k), ("operator_void", k),
                                ("repeat_finalise", k), ("failed_invalidate", k)]  # fmt: skip
                elif s == "void":
                    options.append(("restore", k))
            options.append(("reconcile", None))
            act, k = rng.choice(options)
            log.append((step, act, k))
            print(f"seed {seed} step {step}: {act} R{'' if k is None else k + 1}")
            members, before_champs, _, _ = state(eng)
            w = made[k] if k is not None else None
            touched = members.get(w["round"]) if w else None
            if act == "finalise":
                finalise(eng, fresh(eng, op), w)
                status[k] = "void" if k in first_void else "valid"
            elif act == "invalidate":
                invalidate(eng, own, op, w)
                status[k] = "void"
            elif act == "restore":
                restore(eng, own, op, w, rng.choice([winner, two_all]))
                status[k] = "valid"
            elif act == "correct":
                correct_all(eng, own, op, w, rng.choice([winner, lambda i: (2, 2),
                                                         lambda i: (1, 0)]))  # fmt: skip
            elif act == "operator_void":
                o = fresh(eng, own)
                imp = co.preview_reopen(eng, o, w["round"])
                co.reopen_round(eng, o, w["round"], reason="ruling", evidence="statement",
                                confirmation=imp.token)  # fmt: skip
                p = fresh(eng, op)
                imp = co.preview_invalidation(eng, p, w["round"], reason="abandoned")
                co.invalidate_round(eng, p, w["round"], reason="abandoned",
                                    confirmation=imp.token)  # fmt: skip
                finalise(eng, fresh(eng, op), w)
                status[k] = "operator_void"
                operator_void.add(w["round"])
            elif act == "repeat_finalise":
                before = counts(eng)
                with pytest.raises(co.CorrectionRefused):  # 6C.4: only a settling round
                    co.finalise_round(eng, fresh(eng, op), w["round"])
                assert counts(eng) == before
            elif act == "failed_invalidate":
                reopen_correct(eng, own, op, w, [co.CorrectionInput(f, "CANC")
                                                 for f in w["fixtures"][:6]])  # fmt: skip
                real = ch.process_stream

                def boom(*a, **kw):
                    raise RuntimeError("injected")

                monkeypatch.setattr(ch, "process_stream", boom)
                before = counts(eng)
                with pytest.raises(RuntimeError):
                    finalise(eng, fresh(eng, op), w)
                monkeypatch.setattr(ch, "process_stream", real)
                assert counts(eng) == before  # nothing partial (weekly results included)
                finalise(eng, fresh(eng, op), w)  # retry
                status[k] = "void"
            else:  # reconcile: processing again changes nothing
                before = counts(eng)
                with transaction(eng) as conn:
                    out = ch.process_stream(conn, "development")
                assert out.versions == 0 and out.changes == () and counts(eng) == before
            before = counts(eng)
            lb.championship_list(eng, stream="development", include_development=True)
            assert counts(eng) == before  # reads write nothing
            check(eng, history, operator_void, touched, before_champs)
        print(f"seed {seed}: {len(log)} operations: {log}")
    finally:
        eng.dispose()
        drop(pg_url, name)
