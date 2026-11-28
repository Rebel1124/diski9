"""CP3A-R.1 (research only): point-in-time replay of the captured odds trial.

Replays the saved monitoring runs (EPL 15-21 Nov 2026; PSL 15-27 Nov 2026) into a
scratch copy of the local football store with the production collector
(``odds.monitor.replay``), then evaluates the production strict Challenge consensus
(``odds.consensus.fixture_consensus``, 24 h freshness, >= 3 independent groups,
complete market) and A3 classification at each capture time. No look-ahead: the
consensus only uses quotes first seen at or before the evaluation time.

The captures live on the research branch and are NOT merged. Extract them first:
  git archive origin/claude/gifted-newton-h6o5hk monitoring/odds_trial | tar -x -C DIR
Run:
  uv run python tools/research/cp3ar/odds_trial_replay.py DIR/monitoring/odds_trial
No provider requests; the local store is copied, never modified.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from diski9.challenge.config import A3_432_V1 as CFG
from diski9.challenge.structured import _match
from diski9.db import make_engine
from diski9.db.schema import fixtures, odds_fetches, odds_fixture_observations, odds_quotes
from diski9.odds.consensus import fixture_consensus, load_bookmakers
from diski9.odds.implied import implied
from diski9.odds.monitor import load_runs, replay

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/diski9.sqlite"
OUT = ROOT / "docs/research/phase8_cp3ar/odds_trial_replay.json"
NEED = dict(zip(CFG.bucket_codes, CFG.sizes, strict=True))


def evaluate(conn, books, fixture_ids, kick, t: datetime) -> dict:
    """Strict consensus and A3 buckets for every pre-kickoff fixture at time t."""
    per = {}
    reasons = Counter()
    for fid in fixture_ids:
        if kick[fid] <= t:
            continue
        cons = fixture_consensus(conn, fid, t, books=books)
        probs, eligible_markets = {}, 0
        for m, mc in cons.items():
            if not mc.challenge_eligible:
                reasons.update(mc.exclusions or {"too_few_sources": 1})
                if mc.sources and mc.sources < mc.min_required:
                    reasons["below_min_groups"] += 1
                continue
            adj = implied(mc).margin_adjusted
            if not adj:
                reasons["incomplete_outcomes"] += 1
                continue
            eligible_markets += 1
            for o, p in adj.items():
                probs[f"{m.value}:{o.value}"] = float(p)
        per[fid] = {
            "markets": eligible_markets,
            "probs": probs,
            "bands": {CFG.classify(p) for p in probs.values()} - {None},
        }
    with_any = {f: v for f, v in per.items() if v["markets"]}
    return {
        "fixtures_pre_kickoff": len(per),
        "fixtures_any_eligible_market": len(with_any),
        "fixtures_all_three_markets": sum(v["markets"] == 3 for v in per.values()),
        "eligible_outcomes_by_bucket": dict(
            Counter(CFG.classify(p) or "-" for v in per.values() for p in v["probs"].values())
        ),
        "fixtures_with_bucket": dict(Counter(b for v in with_any.values() for b in v["bands"])),
        "exclusion_reasons": dict(reasons),
        "portfolio_feasible_alone": bool(
            len(with_any) >= 9 and _match(NEED, {f: v["bands"] for f, v in with_any.items()})
        ),
        "_per": per,
    }


def main(capture_dir: str) -> None:
    runs = load_runs(Path(capture_dir))
    out: dict = {
        "captures": len(runs),
        "first": runs[0]["run_at"],
        "last": runs[-1]["run_at"],
        "source": "research branch claude/gifted-newton-h6o5hk monitoring/odds_trial "
        "(not merged); last capture commit 37b7ea7",
        "by_competition": {},
    }
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "replay.sqlite"
        shutil.copy(STORE, copy)
        eng = make_engine(f"sqlite:///{copy}")
        with eng.begin() as conn:
            for t in (odds_quotes, odds_fixture_observations, odds_fetches):
                conn.execute(t.delete())
            # Incremental replay: evaluate right after each capture, as a live system
            # would. (Evaluating an earlier time after replaying later captures would
            # use an episode's first provider timestamp and overstate staleness: the
            # episode store does not keep every intermediate observation.)
            books = load_bookmakers(conn)
            errors, comp_of, kick = [], {}, {}
            series: dict = defaultdict(list)
            prev: dict = {}
            snaps: dict = {}
            for r in runs:
                errors += replay(conn, [r]).errors
                for fid, comp, k in conn.execute(
                    select(
                        odds_fixture_observations.c.fixture_id,
                        fixtures.c.competition_id,
                        fixtures.c.kickoff_utc,
                    ).join(fixtures, fixtures.c.id == odds_fixture_observations.c.fixture_id)
                ).all():
                    comp_of[fid] = comp
                    kick[fid] = k if k.tzinfo else k.replace(tzinfo=UTC)
                t = datetime.fromisoformat(r["run_at"]) + timedelta(minutes=3)
                for cid in r["competitions"]:
                    comp = int(cid)
                    fids = sorted(f for f, c in comp_of.items() if c == comp)
                    ev = evaluate(conn, books, fids, kick, t)
                    per = ev.pop("_per")
                    snaps[(comp, r["run_at"][:16])] = per
                    if comp in prev:
                        moves, flips = [], 0
                        for f, v in per.items():
                            for k2, p2 in v["probs"].items():
                                q = prev[comp].get(f, {}).get("probs", {}).get(k2)
                                if q is not None:
                                    moves.append(abs(p2 - q) * 100)
                                    flips += CFG.classify(p2) != CFG.classify(q)
                        ev["vs_previous"] = {
                            "outcomes_compared": len(moves),
                            "moved_gt_1pp": sum(m > 1 for m in moves),
                            "max_move_pp": round(max(moves), 2) if moves else None,
                            "bucket_changes": flips,
                        }
                    series[comp].append({"t": t.isoformat(), **ev})
                    prev[comp] = per
            out["replay_errors"] = errors
            for comp, ser in series.items():
                out["by_competition"][str(comp)] = {
                    "fixtures_with_observations": sum(1 for c in comp_of.values() if c == comp),
                    "series": ser,
                }
            out["epl_drift"] = drift(snaps, kick)
        eng.dispose()
    # provider update timestamps per capture (from the raw files)
    upd = []
    for r in runs:
        for cid, e in r["competitions"].items():
            vals = sorted(
                {i.get("update") for p in e["pages"] for i in p["items"] if i.get("update")}
            )
            upd.append({"run_at": r["run_at"], "competition": cid, "updates": vals[-4:]})
    out["provider_updates"] = upd
    OUT.write_text(json.dumps(out, indent=1, default=str))
    print(
        json.dumps(
            {
                c: [
                    (
                        s["t"][5:16],
                        s["fixtures_pre_kickoff"],
                        s["fixtures_any_eligible_market"],
                        s["fixtures_all_three_markets"],
                        s.get("vs_previous", {}).get("bucket_changes"),
                    )
                    for s in v["series"]
                ]
                for c, v in out["by_competition"].items()
            },
            indent=0,
        )
    )
    print(json.dumps(out["epl_drift"], indent=1))


def drift(snaps, kick) -> dict:
    """Probability and bucket change of the same eligible outcomes between captures
    (EPL), restricted to fixtures not yet started at the later capture."""
    pairs = {
        "tue_0616_to_fri_0614": ("2026-11-17T06:16", "2026-11-20T06:14"),
        "fri_0614_to_fri_1216": ("2026-11-20T06:14", "2026-11-20T12:16"),
        "fri_0614_to_sat_0614": ("2026-11-20T06:14", "2026-11-21T06:14"),
        "fri_0614_to_sat_1214": ("2026-11-20T06:14", "2026-11-21T12:14"),
    }
    res = {}
    for name, (a, b) in pairs.items():
        ea, eb = snaps.get((39, a)), snaps.get((39, b))
        if ea is None or eb is None:
            res[name] = "capture missing"
            continue
        tb = datetime.fromisoformat(b + ":00+00:00")
        moves, flips = [], 0
        for f, v in eb.items():
            if kick[f] <= tb:
                continue
            for k, p in v["probs"].items():
                q = ea.get(f, {}).get("probs", {}).get(k)
                if q is not None:
                    moves.append(abs(p - q) * 100)
                    flips += CFG.classify(p) != CFG.classify(q)
        moves.sort()
        res[name] = {
            "outcomes_eligible_at_both": len(moves),
            "median_move_pp": round(moves[len(moves) // 2], 2) if moves else None,
            "p90_move_pp": round(moves[int(len(moves) * 0.9)], 2) if moves else None,
            "max_move_pp": round(moves[-1], 2) if moves else None,
            "moved_gt_2pp": sum(m > 2 for m in moves),
            "bucket_changes": flips,
        }
    return res


if __name__ == "__main__":
    main(sys.argv[1])
