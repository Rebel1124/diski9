"""Research only: cross-league validation of the frozen goal-distribution model.

Run: uv run python scripts/research_goal_crossleague.py
Reads the separate research database ``data/research_crossleague.sqlite`` (built
with the existing ingestion commands; see docs/goal_model_crossleague_validation.md)
and writes docs/research/goal_model_crossleague/*. No production code, database
or cache is touched; no bookmaker data is read.

Frozen parameters (chosen on EPL, Championship, PSL, PSL 1st Division only):
k_s = 12, k_t = 96, m0 = 30. Nothing is re-tuned for the evaluation. A headroom
check on the earliest holdout seasons only asks how much a re-tuned setting could
gain at most; it never feeds the reported holdout results.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from research_goal_distribution import metrics, per_row_losses  # noqa: E402

from diski9.db import make_engine  # noqa: E402
from diski9.research import goal_distribution as gd  # noqa: E402
from diski9.research.charts import calibration_panels  # noqa: E402
from diski9.research.evaluation import calibration_table, iso_week, paired_bootstrap  # noqa: E402
from diski9.research.form_score_comparison import write_csv  # noqa: E402
from diski9.screener.engine import MatchStore  # noqa: E402

DB_PATH = Path("data/research_crossleague.sqlite")
DB = f"sqlite:///{DB_PATH}"
_ARGS = "--competitions 140 61 78 135 2 3 --seasons 2022 2023 2024 2025 2026"
BUILD_HELP = f"""The research database {DB_PATH} has not been built on this computer.
It is local data (not in git). Build it once (about 67 API requests), then rerun:

  uv run diski9 --database-url {DB} init-db
  uv run diski9 --database-url {DB} sync-reference {_ARGS}
  uv run diski9 --database-url {DB} ingest-fixtures {_ARGS}
"""


def require_research_db() -> None:
    """Fail with build instructions (and without creating an empty file) when the
    research database is missing or has not been populated."""
    import sqlite3

    if DB_PATH.exists():
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
            n = con.execute(
                "select count(*) from sqlite_master where type='table' and name='fixtures'"
            ).fetchone()[0]
            if n and con.execute("select count(*) from fixtures").fetchone()[0]:
                return
    raise SystemExit(BUILD_HELP)


OUT = Path("docs/research/goal_model_crossleague")
FROZEN = gd.Params("season", 12, gd.INF, 30.0, 96)
DOMESTIC = {140: "La Liga", 61: "Ligue 1", 78: "Bundesliga", 135: "Serie A"}
UEFA = {2: "Champions League", 3: "Europa League"}
NAMES = {**DOMESTIC, **UEFA}
SEASONS = (2022, 2023, 2024, 2025, 2026)
HOLDOUT = (2023, 2024, 2025, 2026)  # 2022/23 supplies the previous-season prior only
GAMES = {140: 38, 61: 34, 78: 34, 135: 38}  # per team, holdout seasons (Ligue 1: 18 teams)
QUALIFYING = re.compile(r"qualifying|preliminary|^play-offs$", re.I)
GROUP = re.compile(r"^(group [a-h]|group stage|league stage) - (\d+)$", re.I)


def uefa_stage(round_name: str) -> tuple[str, int | None]:
    """qualifying | group (2022-23 format) | league (2024- format) | knockout | final."""
    r = (round_name or "").strip()
    if QUALIFYING.search(r):
        return "qualifying", None
    m = GROUP.match(r)
    if m:
        return ("league" if m.group(1).lower().startswith("league") else "group"), int(m.group(2))
    if r.lower() == "final":
        return "final", None
    return "knockout", None


def load_store() -> tuple[MatchStore, dict[int, tuple[str, int | None]]]:
    """Domestic matches keep the production eligibility rules (regular season only).
    UEFA matches: the main competition only - group / league stage and two-legged
    knockout rounds (90-minute score). Qualifying rounds and the single-venue final
    are excluded from both team statistics and evaluation."""
    with make_engine(DB).connect() as c:
        base = MatchStore(c)
    stage = {}
    out = []
    for m in base.matches:
        if m.competition_id in UEFA:
            st = uefa_stage(m.round_name)
            stage[m.fixture_id] = st
            ok = st[0] in ("group", "league", "knockout") and m.status in ("FT", "AET", "PEN")
            m = replace(m, stats_eligible=ok)
        out.append(m)
    store = MatchStore.from_matches(out, base.team_names, base.competition_names)
    return store, stage


def stage_labels(ds, stage):
    """Season stage for each row: domestic by share of the season played; UEFA by
    matchday (early MD1-2, mid MD3-4 group / MD3-5 league, late the rest) and
    knockout."""
    labels = []
    for i in range(len(ds)):
        comp = int(ds.competition[i])
        if comp in UEFA:
            kind, md = stage[int(ds.fixture_id[i])]
            if kind == "knockout":
                labels.append("knockout")
            else:
                mid_end = 4 if kind == "group" else 5
                labels.append("early" if md <= 2 else "mid" if md <= mid_end else "late")
        else:
            t = ds.team["season"][i]
            played = (t[0] + t[1] + t[6] + t[7]) / 2
            p = played / GAMES[comp]
            labels.append("early" if p < 0.25 else "mid" if p <= 0.75 else "late")
    return np.array(labels)


def evaluate(ds, mask=None):
    """Frozen-model and league-baseline predictions for rows in ``mask``."""
    sub = ds if mask is None else ds.subset(mask)
    lh, la, av = gd.lambdas(sub, FROZEN)
    assert av.all()
    model = gd.poisson_markets(lh, la)
    lf = gd.league_frequencies(sub, FROZEN.m0)
    base = {k: lf[k] for k in ("home", "draw", "away", "btts_yes", "over")}
    lp = gd.poisson_score_logprob(lh, la, sub.hg, sub.ag)
    return sub, model, base, lp, (lh, la)


def compare(sub, model, base):
    cl = [iso_week(k) for k in sub.kickoff]
    lm, lb = per_row_losses(model, sub), per_row_losses(base, sub)
    return {k: paired_bootstrap(lm[k] - lb[k], cl) for k in lm}


def headroom(ds, comps):
    """In-sample check on the 2023/24 and 2024/25 seasons only: the best setting on
    a coarse grid versus the frozen one, by mean scoreline log-likelihood."""
    m = np.isin(ds.competition, comps) & np.isin(ds.season, (2023, 2024))
    sub = ds.subset(m)
    grid = [
        gd.Params("season", ks, gd.INF, 30.0, kt)
        for ks, kt in product((2, 4, 6, 8, 12, 16, 24), (12, 24, 48, 96, 192, 1e12))
    ]
    best, table = gd.tune_poisson(sub, grid)
    frozen = [r for r in table if r["params"] == FROZEN][0]["score_loglik"]
    top = max(r["score_loglik"] for r in table)
    return {
        "rows": len(sub),
        "best": {"k_s": best.k_o, "k_t": best.k_t},
        "frozen_loglik": round(frozen, 5),
        "best_loglik": round(top, 5),
        "gap": round(top - frozen, 5),
    }


def split_check(ds, comps):
    """Only run if the frozen model is weak: tune on 2023/24-2024/25 of ``comps``
    and evaluate frozen versus tuned on 2025/26-2026/27 (never seen by the tuning)."""
    tr = ds.subset(np.isin(ds.competition, comps) & np.isin(ds.season, (2023, 2024)))
    te_mask = np.isin(ds.competition, comps) & np.isin(ds.season, (2025, 2026))
    te = ds.subset(te_mask)
    grid = [
        gd.Params("season", ks, gd.INF, 30.0, kt)
        for ks, kt in product((1, 2, 3, 4, 6, 8, 12), (12, 24, 48, 96, 192))
    ]
    best, _ = gd.tune_poisson(tr, grid)
    out = {
        "tuned_on": "2023/24-2024/25",
        "evaluated_on": "2025/26-2026/27",
        "n": len(te),
        "tuned_params": {"k_s": best.k_o, "k_t": best.k_t},
    }
    res = {}
    for name, p in (("frozen", FROZEN), ("tuned", best)):
        lh, la, _ = gd.lambdas(te, p)
        res[name] = gd.poisson_markets(lh, la)
        out[name] = metrics(res[name], te)
    cl = [iso_week(k) for k in te.kickoff]
    lt, lf = per_row_losses(res["tuned"], te), per_row_losses(res["frozen"], te)
    out["tuned_minus_frozen"] = {k: paired_bootstrap(lt[k] - lf[k], cl) for k in lt}
    return out


def development_league_check(alt: gd.Params) -> dict:
    """Would the setting preferred by the new domestic leagues also help the four
    development leagues? Same test seasons as the original study (2024/25 onwards)."""
    with make_engine().connect() as c:
        store = MatchStore(c)
    ds = gd.build_dataset(store, (39, 40, 288, 289), (2023, 2024, 2025, 2026))
    _, _, av = gd.league_rates(ds, 30.0)
    te = ds.subset(av & np.isin(ds.season, (2024, 2025, 2026)))
    loss = {}
    for name, p in (("frozen", FROZEN), ("alternative", alt)):
        lh, la, _ = gd.lambdas(te, p)
        loss[name] = per_row_losses(gd.poisson_markets(lh, la), te)
    cl = [iso_week(k) for k in te.kickoff]
    return {
        "alternative": {"k_s": alt.k_o, "k_t": alt.k_t},
        "n": len(te),
        "alternative_minus_frozen": {
            k: paired_bootstrap(loss["alternative"][k] - loss["frozen"][k], cl)
            for k in loss["frozen"]
        },
    }


def main() -> None:
    require_research_db()
    OUT.mkdir(parents=True, exist_ok=True)
    gd.GAMES_PER_TEAM.update(GAMES)
    store, stage = load_store()
    ds_all = gd.build_dataset(store, NAMES, SEASONS)
    summary: dict = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "parameters": {"k_s": 12, "k_t": 96, "m0": 30},
    }

    # -------------------------------------------------------------- coverage
    with make_engine(DB).connect() as c:
        from sqlalchemy import text

        status = c.execute(
            text(
                "select competition_id, season, coalesce(stats_exclusion_reason, 'eligible'), "
                "count(*) from fixtures group by 1, 2, 3 order by 1, 2, 3"
            )
        ).all()
    cov = []
    for comp in NAMES:
        for yr in SEASONS:
            m = (ds_all.competition == comp) & (ds_all.season == yr)
            _, _, av = gd.league_rates(ds_all.subset(m), 30.0) if m.any() else (0, 0, np.array([]))
            row = {
                "competition": NAMES[comp],
                "season": f"{yr}/{str(yr + 1)[2:]}",
                "evaluated_fixtures": int(m.sum()) if yr in HOLDOUT else 0,
                "role": "holdout (new evidence)" if yr in HOLDOUT else "prior only",
            }
            kinds = defaultdict(int)
            for x in store.matches:
                if x.competition_id == comp and x.season == yr and x.fixture_id in stage:
                    kinds[stage[x.fixture_id][0]] += 1
            for k in ("qualifying", "group", "league", "knockout", "final"):
                row[f"uefa_{k}"] = kinds.get(k, 0) if comp in UEFA else ""
            cov.append(row)
    write_csv(OUT / "coverage.csv", cov)
    summary["fixture_status_counts"] = [list(r) for r in status]

    hold = np.isin(ds_all.season, HOLDOUT)
    labels_all = stage_labels(ds_all, stage)

    # ----------------------------------------------------- per competition
    per_comp, rows_csv, calib = {}, [], {}
    panels = {"Home win": {}, "BTTS Yes": {}, "Over 2.5": {}}
    groups = {
        **{n: [c] for c, n in NAMES.items()},
        "New domestic leagues (pooled)": list(DOMESTIC),
        "UEFA (pooled)": list(UEFA),
    }
    for name, comps in groups.items():
        mask = hold & np.isin(ds_all.competition, comps)
        sub, model, base, lp, (lh, la) = evaluate(ds_all, mask)
        labels = labels_all[mask]
        res = {
            "seasons": sorted({f"{s}/{str(s + 1)[2:]}" for s in sub.season}),
            "model": metrics(model, sub, lp),
            "league_baseline": metrics(base, sub),
            "model_minus_baseline": compare(sub, model, base),
            "lambda_range": [
                round(float(np.min([lh.min(), la.min()])), 2),
                round(float(np.max([lh.max(), la.max()])), 2),
            ],
            "by_stage": {},
        }
        for st in ("early", "mid", "late", "knockout"):
            sm = labels == st
            if sm.sum() < 20:
                continue
            ssub = sub.subset(sm)
            mm = {k: np.asarray(v)[sm] for k, v in model.items()}
            bb = {k: np.asarray(v)[sm] for k, v in base.items()}
            lm_, lb_ = per_row_losses(mm, ssub), per_row_losses(bb, ssub)
            cl = [iso_week(k) for k in ssub.kickoff]
            res["by_stage"][st] = {
                "n": int(sm.sum()),
                **{
                    f"model_{k}": round(float(lm_[k].mean()), 4)
                    for k in ("1x2_log_loss", "btts_log_loss", "ou_log_loss")
                },
                **{
                    f"baseline_{k}": round(float(lb_[k].mean()), 4)
                    for k in ("1x2_log_loss", "btts_log_loss", "ou_log_loss")
                },
                "1x2_diff": paired_bootstrap(lm_["1x2_log_loss"] - lb_["1x2_log_loss"], cl),
            }
        per_comp[name] = res
        d = res["model_minus_baseline"]
        rows_csv.append(
            {
                "competition": name,
                "fixtures": res["model"]["n"],
                "seasons": " ".join(res["seasons"]),
                **{
                    f"model_{k}": res["model"][k]
                    for k in (
                        "1x2_log_loss",
                        "1x2_brier",
                        "btts_log_loss",
                        "btts_brier",
                        "ou_log_loss",
                        "ou_brier",
                    )
                },
                **{
                    f"baseline_{k}": res["league_baseline"][k]
                    for k in ("1x2_log_loss", "btts_log_loss", "ou_log_loss")
                },
                "1x2_diff": d["1x2_log_loss"]["mean"],
                "1x2_ci": d["1x2_log_loss"]["ci95"],
                "btts_diff": d["btts_log_loss"]["mean"],
                "btts_ci": d["btts_log_loss"]["ci95"],
                "ou_diff": d["ou_log_loss"]["mean"],
                "ou_ci": d["ou_log_loss"]["ci95"],
                "slope_1x2_home": res["model"]["1x2_slope_home"],
                "slope_btts": res["model"]["btts_slope"],
                "slope_ou": res["model"]["ou_slope"],
                "ece_home": res["model"]["1x2_ece_home"],
                "ece_btts": res["model"]["btts_ece"],
                "ece_ou": res["model"]["ou_ece"],
            }
        )
        if name in ("New domestic leagues (pooled)", "UEFA (pooled)"):
            P = np.column_stack([model["home"], model["draw"], model["away"]])
            calib[name] = {}
            for lab, p, y in (
                ("Home win", P[:, 0], (sub.outcome == 0).astype(int)),
                ("BTTS Yes", model["btts_yes"], sub.btts),
                ("Over 2.5", model["over"], sub.over),
            ):
                tab = calibration_table(p, y)
                calib[name][lab] = tab
                panels[lab][name.replace(" (pooled)", "")] = [
                    (r["mean_forecast"], r["observed"], r["n"]) for r in tab if r["n"]
                ]
    write_csv(OUT / "per_competition.csv", rows_csv)
    calibration_panels(
        OUT / "calibration.svg",
        panels,
        "Frozen model (k_s 12, k_t 96, m0 30): new competitions, 2023/24 onwards",
    )
    summary["per_competition"] = per_comp
    summary["calibration_tables"] = calib

    # ------------------------------------------------- UEFA by stage type
    uefa_detail = {}
    for comp, name in UEFA.items():
        for kind in ("group", "league", "knockout"):
            m = (
                hold
                & (ds_all.competition == comp)
                & np.array(
                    [
                        stage[int(f)][0] == kind if int(f) in stage else False
                        for f in ds_all.fixture_id
                    ]
                )
            )
            if m.sum() < 20:
                continue
            sub, model, base, lp, _ = evaluate(ds_all, m)
            uefa_detail[f"{name} {kind}"] = {
                "model": metrics(model, sub, lp),
                "league_baseline": metrics(base, sub),
                "model_minus_baseline": compare(sub, model, base),
            }
    summary["uefa_by_format"] = uefa_detail
    # matches played before each UEFA fixture (how much team data the model has)
    um = hold & np.isin(ds_all.competition, list(UEFA))
    t = ds_all.team["season"][um]
    played = np.minimum(t[:, 0] + t[:, 1], t[:, 6] + t[:, 7])
    summary["uefa_team_matches_before_fixture"] = {
        "median_min_of_two_teams": float(np.median(played)),
        "share_with_zero": round(float((played == 0).mean()), 3),
        "max": float(played.max()),
    }

    # ------------------------------------------------------ headroom checks
    summary["headroom_2023_2024_in_sample"] = {
        "new_domestic": headroom(ds_all, list(DOMESTIC)),
        "uefa": headroom(ds_all, list(UEFA)),
        **{NAMES[c]: headroom(ds_all, [c]) for c in DOMESTIC},
    }
    summary["uefa_split_check"] = split_check(ds_all, list(UEFA))
    summary["domestic_split_check"] = split_check(ds_all, list(DOMESTIC))
    t = summary["domestic_split_check"]["tuned_params"]
    summary["development_league_check"] = development_league_check(
        gd.Params("season", t["k_s"], gd.INF, 30.0, t["k_t"])
    )

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    for r in rows_csv:
        print(r)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "headroom_2023_2024_in_sample",
                    "uefa_split_check",
                    "domestic_split_check",
                    "uefa_team_matches_before_fixture",
                )
            },
            indent=1,
            default=str,
        )[:6000]
    )


if __name__ == "__main__":
    main()
