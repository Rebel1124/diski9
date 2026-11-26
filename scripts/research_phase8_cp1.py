"""Phase 8 CP1 research only: current-season-only Goal Model candidates, market-implied
fit quality and Weekly Challenge season-start feasibility.

Procedure, criteria and periods are pre-registered in
docs/research/phase8_cp1/preregistration.md (committed before any result).

Inputs (read-only; copied to a temporary directory first):
  data/diski9.sqlite                (EPL, Championship, PSL, PSL 1st Division; cached odds)
  data/research_crossleague.sqlite  (La Liga, Ligue 1, Bundesliga, Serie A, UCL, UEL)
  docs/research/weekly_challenge_risk/pool_weekend.json (real strict-consensus snapshot)
Outputs: docs/research/phase8_cp1/*.json|csv

No provider calls, no production module or database is modified.

Run:  uv run python scripts/research_phase8_cp1.py [model|market|pools|all]
"""

from __future__ import annotations

import json
import math
import re
import shutil
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from research_goal_distribution import calib_slope, metrics, per_row_losses  # noqa: E402

from diski9.research import goal_distribution as gd  # noqa: E402
from diski9.research.evaluation import (  # noqa: E402
    expected_calibration_error,
    iso_week,
    paired_bootstrap,
)
from diski9.research.form_score_comparison import write_csv  # noqa: E402

OUT = Path("docs/research/phase8_cp1")
DEV_DB = Path("data/diski9.sqlite")
RESEARCH_DB = Path("data/research_crossleague.sqlite")

DEV_LEAGUES = (39, 40, 288, 289)
NEW_LEAGUES = (140, 61, 78, 135)
DOMESTIC = DEV_LEAGUES + NEW_LEAGUES
UEFA = (2, 3)
NAMES = {
    39: "EPL", 40: "Championship", 288: "PSL", 289: "PSL 1st Division", 140: "La Liga",
    61: "Ligue 1", 78: "Bundesliga", 135: "Serie A", 2: "Champions League", 3: "Europa League",
}  # fmt: skip
SEASONS = (2023, 2024, 2025, 2026)
SELECTION = (2023, 2024)
CONFIRMATION = (2025, 2026)
FULL_SEASONS = (2023, 2024, 2025)
AVAILABILITY_LAG = timedelta(hours=3)  # a match counts only if it kicked off >= 3 h earlier
K_GRID = (2, 3, 4, 5)
L_GRID = (20, 30, 40)
KS_T_GRID = tuple(product((6, 8, 12), (24, 48, 96)))
KS, KT, M0 = 12.0, 96.0, 30.0  # Goal Model 1.0 (frozen)
MARKETS = ("1x2_log_loss", "btts_log_loss", "ou_log_loss")

# ------------------------------------------------------------------ UEFA stages
QUALIFYING = re.compile(r"qualifying|preliminary|^play-offs$", re.I)
GROUP = re.compile(r"^(group [a-h]|group stage|league stage) - (\d+)$", re.I)
KNOCKOUT = {"knockout round play-offs", "round of 32", "round of 16", "quarter-finals",
            "semi-finals"}  # fmt: skip


class StageError(ValueError):
    """An unrecognised UEFA round label or an impossible stage order: stop the run."""


def uefa_stage(round_name: str | None) -> tuple[str, int | None]:
    """qualifying | group | league | knockout | final. Unknown labels raise."""
    r = (round_name or "").strip()
    if QUALIFYING.search(r):
        return "qualifying", None
    m = GROUP.match(r)
    if m:
        return ("league" if m.group(1).lower().startswith("league") else "group"), int(m.group(2))
    if r.lower() == "final":
        return "final", None
    if r.lower() in KNOCKOUT:
        return "knockout", None
    raise StageError(f"unrecognised UEFA round label {round_name!r}")


def check_stage_order(rows) -> None:
    """rows: (competition, season, stage, kickoff). A knockout fixture before the
    season's first group / league-phase fixture means a mislabelled qualifier."""
    first: dict[tuple[int, int], datetime] = {}
    for comp, season, stage, k in rows:
        if stage in ("group", "league"):
            key = (comp, season)
            first[key] = min(first.get(key, k), k)
    for comp, season, stage, k in rows:
        f = first.get((comp, season))
        if stage == "knockout" and (f is None or k < f):
            raise StageError(f"knockout fixture before the main stage: {comp} {season} {k}")


# ------------------------------------------------------------------ data
def _copy_store(src: Path, tmp: Path):
    from diski9.db import make_engine
    from diski9.screener.engine import MatchStore

    if not src.exists():
        raise SystemExit(f"{src} is not present on this computer (local research data).")
    dst = tmp / src.name
    shutil.copy(src, dst)
    eng = make_engine(f"sqlite:///{dst}")
    with eng.connect() as c:
        store = MatchStore(c)
    return eng, store


def load_matches(tmp: Path):
    """One combined store: development leagues from the local store, the four newer
    leagues and UEFA from the research store. UEFA eligibility = main stage only."""
    from diski9.screener.engine import MatchStore

    _, dev = _copy_store(DEV_DB, tmp)
    _, res = _copy_store(RESEARCH_DB, tmp)
    stage: dict[int, tuple[str, int | None]] = {}
    out = [m for m in dev.matches if m.competition_id in DEV_LEAGUES]
    order = []
    for m in res.matches:
        if m.competition_id in NEW_LEAGUES:
            out.append(m)
        elif m.competition_id in UEFA:
            st = uefa_stage(m.round_name)
            stage[m.fixture_id] = st
            order.append((m.competition_id, m.season, st[0], m.kickoff))
            ok = st[0] in ("group", "league", "knockout") and m.status in ("FT", "AET", "PEN")
            out.append(replace(m, stats_eligible=ok))
    check_stage_order(order)
    names = {**dev.team_names, **res.team_names}
    comps = {**dev.competition_names, **res.competition_names}
    return MatchStore.from_matches(out, names, comps), stage


@dataclass
class Rows:
    """One row per evaluated fixture with point-in-time features (lagged cutoff)."""

    fixture: np.ndarray
    comp: np.ndarray
    season: np.ndarray
    kickoff: list
    stage: list  # domestic: "league"; UEFA: group/league/knockout
    matchday: np.ndarray  # UEFA group/league matchday, else 0
    hg: np.ndarray
    ag: np.ndarray
    cur_n: np.ndarray
    cur_hg: np.ndarray
    cur_ag: np.ndarray
    cur_res: np.ndarray
    prev_n: np.ndarray
    prev_hg: np.ndarray
    prev_ag: np.ndarray
    prev_res: np.ndarray
    team: np.ndarray  # (N, 12) [n_h n_a gf_h ga_h gf_a ga_a] x home, away

    def subset(self, mask) -> Rows:
        idx = np.flatnonzero(mask)
        kw = {}
        for k, v in self.__dict__.items():
            kw[k] = [v[i] for i in idx] if isinstance(v, list) else v[idx]
        return Rows(**kw)

    def __len__(self) -> int:
        return len(self.fixture)

    @property
    def outcome(self):
        return np.where(self.hg > self.ag, 0, np.where(self.hg == self.ag, 1, 2))

    @property
    def btts(self):
        return ((self.hg > 0) & (self.ag > 0)).astype(int)

    @property
    def over(self):
        return (self.hg + self.ag >= 3).astype(int)

    @property
    def played(self):
        t = self.team
        return t[:, 0] + t[:, 1], t[:, 6] + t[:, 7]


def build_rows(store, stage, comps, seasons, lag: timedelta = AVAILABILITY_LAG) -> Rows:
    cols = defaultdict(list)
    far = datetime(2100, 1, 1, tzinfo=UTC)
    prev_cache = {}
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in seasons:
            continue
        st = stage.get(m.fixture_id, ("league", None))
        cutoff = m.kickoff - lag
        cur = gd._league(store.league_matches(m.competition_id, m.season, cutoff))
        key = (m.competition_id, m.season - 1)
        if key not in prev_cache:
            prev_cache[key] = gd._league(store.league_matches(*key, far))
        prev = prev_cache[key]
        hw = store.team_window(m.home_id, cutoff, None, 999, m.competition_id, m.season)
        aw = store.team_window(m.away_id, cutoff, None, 999, m.competition_id, m.season)
        vals = dict(
            fixture=m.fixture_id, comp=m.competition_id, season=m.season, kickoff=m.kickoff,
            stage=st[0], matchday=st[1] or 0, hg=m.home_goals, ag=m.away_goals,
            cur_n=cur[0], cur_hg=cur[1], cur_ag=cur[2], cur_res=cur[3],
            prev_n=prev[0], prev_hg=prev[1], prev_ag=prev[2], prev_res=prev[3],
            team=gd.team_stats(hw) + gd.team_stats(aw),
        )  # fmt: skip
        for k, v in vals.items():
            cols[k].append(v)
    return Rows(**{k: (v if k in ("kickoff", "stage") else np.array(v)) for k, v in cols.items()})


# ------------------------------------------------------------------ candidates
@dataclass(frozen=True)
class Candidate:
    name: str
    m0: float | None  # 30 = Goal Model 1.0 prior; None = current season only
    k: int = 0  # team minimum (both teams)
    L: int = 0  # competition minimum (current season only)
    k_s: float = KS
    k_t: float = KT


C0 = Candidate("C0", M0)


def league_rates(r: Rows, c: Candidate):
    """Competition H, A and availability of the competition average."""
    with np.errstate(invalid="ignore", divide="ignore"):
        if c.m0 is not None:  # Goal Model 1.0 rule (production league_rates)
            has_prev = r.prev_n > 0
            ph = np.where(has_prev, r.prev_hg / np.maximum(r.prev_n, 1), 0.0)
            pa = np.where(has_prev, r.prev_ag / np.maximum(r.prev_n, 1), 0.0)
            w = np.where(has_prev, c.m0, 0.0)
            H = (r.cur_hg + w * ph) / (r.cur_n + w)
            A = (r.cur_ag + w * pa) / (r.cur_n + w)
            ok = has_prev | (r.cur_n >= gd.LEAGUE_MIN)
        else:
            H, A = r.cur_hg / r.cur_n, r.cur_ag / r.cur_n
            ok = (r.cur_n >= max(c.L, 1)) & (r.cur_hg + r.cur_ag > 0)
    return H, A, ok


def predict(r: Rows, c: Candidate):
    """(markets dict, lambda_home, lambda_away, available)."""
    H, A, ok = league_rates(r, c)
    nh, na = r.played
    ok = ok & (np.minimum(nh, na) >= c.k)
    Hs, As = np.where(ok, H, 1.0), np.where(ok, A, 1.0)
    aH, _, _, dH = gd._factors(r.team[:, :6], Hs, As, c.k_s, gd.INF, c.k_t)
    _, _, aA, dA = gd._factors(r.team[:, 6:], Hs, As, c.k_s, gd.INF, c.k_t)
    lh, la = Hs * aH * dA, As * aA * dH
    lh, la = np.where(ok, lh, 1.0), np.where(ok, la, 1.0)
    return gd.poisson_markets(lh, la), lh, la, ok


def baseline(r: Rows, c: Candidate) -> dict:
    """Competition frequencies before kickoff (C0: blended with the previous season)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        if c.m0 is not None:
            has_prev = r.prev_n > 0
            w = np.where(has_prev, c.m0, 0.0)[:, None]
            prev = np.where(has_prev[:, None], r.prev_res / np.maximum(r.prev_n, 1)[:, None], 0)
            f = (r.cur_res + w * prev) / (r.cur_n[:, None] + w)
        else:
            f = r.cur_res / r.cur_n[:, None]
    f = np.clip(np.nan_to_num(f, nan=0.5), 1e-4, 1 - 1e-4)
    s = f[:, 0] + f[:, 1] + f[:, 2]
    return {"home": f[:, 0] / s, "draw": f[:, 1] / s, "away": f[:, 2] / s,
            "btts_yes": f[:, 3], "over": f[:, 4]}  # fmt: skip


def take(mk: dict, mask) -> dict:
    return {k: np.asarray(v)[mask] for k, v in mk.items()}


def deltas(a: dict, b: dict, r: Rows) -> dict:
    """Paired bootstrap of per-row log-loss differences a - b (ISO-week clusters)."""
    cl = [iso_week(k) for k in r.kickoff]
    la, lb = per_row_losses(a, r), per_row_losses(b, r)
    return {m: paired_bootstrap(la[m] - lb[m], cl) for m in MARKETS}


def ni_verdict(d: dict, margin: float) -> str:
    lo, hi = d["ci95"]
    if hi <= margin:
        return "pass"
    return "deterioration" if lo > 0 else "inconclusive"


def home_ece(mk, r):
    return expected_calibration_error(np.asarray(mk["home"]), (r.outcome == 0).astype(int))


def domestic_check(r: Rows, c: Candidate) -> dict:
    """D1-D4 for candidate c against C0 on identical fixtures."""
    m1, _, _, ok1 = predict(r, c)
    m0, _, _, ok0 = predict(r, C0)
    s = ok1 & ok0
    rs = r.subset(s)
    a, b = take(m1, s), take(m0, s)
    d = deltas(a, b, rs)
    slope = calib_slope(a["home"], (rs.outcome == 0).astype(int))
    e1, e0 = home_ece(a, rs), home_ece(b, rs)
    nh, na = rs.played
    band = np.minimum(nh, na) <= 5
    d4 = None
    if band.sum() >= 30:
        rb = rs.subset(band)
        d4 = deltas(take(a, band), take(baseline(rs, c), band), rb)["1x2_log_loss"]
    out = {
        "candidate": c.name, "k": c.k, "L": c.L, "k_s": c.k_s, "k_t": c.k_t,
        "n_identical": int(s.sum()), "coverage": round(float(ok1.mean()), 4),
        "coverage_c0": round(float(ok0.mean()), 4),
        "D1_1x2": d["1x2_log_loss"], "D2_btts": d["btts_log_loss"], "D2_ou": d["ou_log_loss"],
        "D3_slope_home": slope, "D3_ece_home": round(e1, 4), "D3_ece_home_c0": round(e0, 4),
        "D4_band_n": int(band.sum()), "D4_1x2_vs_baseline": d4,
    }  # fmt: skip
    out["verdicts"] = {
        "D1": ni_verdict(d["1x2_log_loss"], 0.005),
        "D2_btts": ni_verdict(d["btts_log_loss"], 0.003),
        "D2_ou": ni_verdict(d["ou_log_loss"], 0.003),
        "D3": "pass" if (0.8 <= slope <= 1.25 and e1 <= e0 + 0.01) else "fail",
        "D4": "pass" if (d4 and d4["ci95"][1] < 0) else ("insufficient" if d4 is None else "fail"),
    }
    v = out["verdicts"]
    out["passes"] = all(x == "pass" for x in v.values())
    out["passes_except_D3"] = all(x == "pass" for k, x in v.items() if k != "D3")
    return out


def uefa_check(r: Rows, c: Candidate) -> dict:
    """E1-E3 (and the E4 count) for candidate c on its available fixtures."""
    mk, _, _, ok = predict(r, c)
    rs = r.subset(ok)
    out = {"candidate": c.name, "k": c.k, "L": c.L, "n_available": int(ok.sum()),
           "coverage": round(float(ok.mean()), 4), "n_total": len(r)}  # fmt: skip
    if ok.sum() < 30:
        out["verdicts"] = {"E1": "insufficient", "E2_btts": "insufficient",
                           "E2_ou": "insufficient", "E3": "insufficient"}  # fmt: skip
        out["passes"] = False
        return out
    a = take(mk, ok)
    d = deltas(a, take(baseline(r, c), ok), rs)
    slope = calib_slope(a["home"], (rs.outcome == 0).astype(int))
    out.update({"E1_1x2_vs_baseline": d["1x2_log_loss"], "E2_btts": d["btts_log_loss"],
                "E2_ou": d["ou_log_loss"], "E3_slope_home": slope,
                "metrics": metrics(a, rs)})  # fmt: skip
    out["verdicts"] = {
        "E1": "pass" if d["1x2_log_loss"]["ci95"][1] < 0 else "fail",
        "E2_btts": ni_verdict(d["btts_log_loss"], 0.005),
        "E2_ou": ni_verdict(d["ou_log_loss"], 0.005),
        "E3": "pass" if 0.75 <= slope <= 1.35 else "fail",
    }
    out["passes"] = all(x == "pass" for x in out["verdicts"].values())
    return out


def tune_shrinkage(r: Rows, k: int, L: int) -> Candidate:
    """C1-k-L-T: best (k_s, k_t) by mean scoreline log-likelihood (selection only)."""
    best, best_ll = None, -math.inf
    for ks, kt in KS_T_GRID:
        c = Candidate(f"C1-{k}-{L}-T{ks}/{kt}", None, k, L, ks, kt)
        _, lh, la, ok = predict(r, c)
        ll = float(np.mean(gd.poisson_score_logprob(lh[ok], la[ok], r.hg[ok], r.ag[ok])))
        if ll > best_ll:
            best, best_ll = c, ll
    return best


def coverage_table(r: Rows, cands) -> list[dict]:
    rows = []
    for comp in sorted(set(r.comp.tolist()), key=lambda x: DOMESTIC.index(x) if x in DOMESTIC
                       else 99):  # fmt: skip
        for season in SEASONS:
            m = (r.comp == comp) & (r.season == season)
            if not m.any():
                continue
            sub = r.subset(m)
            row = {"competition": NAMES[comp], "season": f"{season}/{(season + 1) % 100:02d}",
                   "period": "full" if season in FULL_SEASONS else "partial",
                   "fixtures": int(m.sum())}  # fmt: skip
            for c in cands:
                row[c.name] = round(float(predict(sub, c)[3].mean()), 4)
            rows.append(row)
    return rows


def full_report(r: Rows, c: Candidate, compare_to: Candidate = C0) -> dict:
    """Pooled and per-league metrics on identical fixtures, bands, withheld fixtures."""
    m1, _, _, ok1 = predict(r, c)
    m0, _, _, ok0 = predict(r, compare_to)
    s = ok1 & ok0
    out = {"pooled": domestic_check(r, c) if c.m0 is None else None, "per_league": [],
           "bands": [], "withheld": {}}  # fmt: skip
    for comp in sorted(set(r.comp.tolist())):
        m = s & (r.comp == comp)
        if m.sum() < 30:
            continue
        rs = r.subset(m)
        a, b = take(m1, m), take(m0, m)
        d = deltas(a, b, rs)
        flag = d["1x2_log_loss"]["ci95"][0] > 0 or d["1x2_log_loss"]["mean"] > 0.010
        out["per_league"].append({
            "competition": NAMES[comp], "n": int(m.sum()), "candidate": metrics(a, rs),
            "c0": metrics(b, rs), "delta": d, "material_deterioration": bool(flag),
            "verdict_1x2": ni_verdict(d["1x2_log_loss"], 0.005),
        })  # fmt: skip
    nh, na = r.played
    lo = np.minimum(nh, na)
    for name, band in (("k-5", lo <= 5), ("6-9", (lo >= 6) & (lo <= 9)), ("10+", lo >= 10)):
        m = s & band
        if m.sum() < 30:
            continue
        rs = r.subset(m)
        base = take(baseline(r, c), m)
        out["bands"].append({"band": name, "n": int(m.sum()),
                             "delta_vs_c0": deltas(take(m1, m), take(m0, m), rs),
                             "vs_baseline": deltas(take(m1, m), base, rs)})  # fmt: skip
    w = ok0 & ~ok1
    if w.sum() >= 30:
        rw = r.subset(w)
        b0 = take(baseline(r, C0), w)
        out["withheld"] = {"n": int(w.sum()), "share": round(float(w.mean()), 4),
                           "c0_metrics": metrics(take(m0, w), rw),
                           "c0_vs_c0_baseline": deltas(take(m0, w), b0, rw)}  # fmt: skip
    else:
        out["withheld"] = {"n": int(w.sum()), "share": round(float(w.mean()), 4)}
    return out


def c1(k, L):
    return Candidate(f"C1-{k}-{L}", None, k, L)


def c0k(k):
    return Candidate(f"C0-{k}", M0, k)


def run_model(tmp: Path) -> dict:
    store, stage = load_matches(tmp)
    dom = build_rows(store, stage, set(DOMESTIC), set(SEASONS))
    eu = build_rows(store, stage, set(UEFA), set(SEASONS))
    summary: dict = {"generated": datetime.now(UTC).isoformat(timespec="seconds"),
                     "lag_hours": AVAILABILITY_LAG.total_seconds() / 3600,
                     "rows": {"domestic": len(dom), "uefa": len(eu)}}  # fmt: skip
    summary["reproduces_goal_model_1_0"] = reproduction_check(dom)

    # ---------------------------------------------------- domestic selection
    sel = dom.subset(np.isin(dom.season, SELECTION))
    grid = [domestic_check(sel, c1(k, L)) for k, L in product(K_GRID, L_GRID)]
    summary["domestic_selection_grid"] = grid
    passing = [g for g in grid if g["passes"]]
    tuned = None
    if not passing and any(g["passes_except_D3"] for g in grid):
        g0 = min((g for g in grid if g["passes_except_D3"]), key=lambda g: (g["k"], g["L"]))
        tuned = tune_shrinkage(sel, g0["k"], g0["L"])
        t = domestic_check(sel, tuned)
        summary["domestic_selection_tuned"] = t
        if t["passes"]:
            passing = [t]
    chosen = None
    if passing:
        g = min(passing, key=lambda g: (g["k"], g["L"]))
        chosen = Candidate(g["candidate"], None, g["k"], g["L"], g["k_s"], g["k_t"])
    summary["domestic_chosen"] = None if chosen is None else chosen.__dict__

    # ---------------------------------------------------- domestic confirmation
    conf = dom.subset(np.isin(dom.season, CONFIRMATION))
    report_c = chosen or c1(min(K_GRID), min(L_GRID))  # reported even if nothing passed
    summary["domestic_confirmation"] = {
        "candidate": report_c.__dict__, "chosen_on_selection": chosen is not None,
        **full_report(conf, report_c),
    }  # fmt: skip
    # C0-k alternative (same k): C0's own quality on the gated set
    k_alt = report_c.k
    alt = c0k(k_alt)
    ma, _, _, oka = predict(conf, alt)
    rs = conf.subset(oka)
    summary["domestic_c0k_alternative"] = {
        "candidate": alt.__dict__, "n": int(oka.sum()), "coverage": round(float(oka.mean()), 4),
        "metrics": metrics(take(ma, oka), rs),
        "vs_c0_baseline": deltas(take(ma, oka), take(baseline(conf, C0), oka), rs),
    }  # fmt: skip
    summary["domestic_c0_confirmation"] = {
        "metrics": metrics(predict(conf, C0)[0], conf),
        "vs_baseline": deltas(predict(conf, C0)[0], baseline(conf, C0), conf),
    }
    # coverage trade-off, every k and L (C1) and k (C0-k)
    cands = [C0] + [c0k(k) for k in K_GRID] + [c1(k, L) for k, L in product(K_GRID, L_GRID)]
    cov = coverage_table(dom, cands)
    write_csv(OUT / "coverage_domestic.csv", cov)
    summary["coverage_tradeoff"] = tradeoff(dom, cands)

    # ---------------------------------------------------- UEFA
    summary["uefa"] = {}
    for comp in UEFA:
        r = eu.subset(eu.comp == comp)
        s_sel = r.subset(np.isin(r.season, SELECTION))
        s_conf = r.subset(np.isin(r.season, CONFIRMATION))
        grid_u = [uefa_check(s_sel, c1(k, L)) for k, L in product(K_GRID, L_GRID)]
        c0u = uefa_check(s_sel, C0)
        dk = report_c.k
        ok_dom_k = [g for g in grid_u if g["k"] == dk and g["passes"]]
        if ok_dom_k:
            g = min(ok_dom_k, key=lambda g: g["L"])
        else:
            p = [g for g in grid_u if g["passes"]]
            g = min(p, key=lambda g: (g["k"], g["L"])) if p else None
        cu = None if g is None else c1(g["k"], g["L"])
        report_u = cu or c1(dk, report_c.L)
        conf_u = uefa_check(s_conf, report_u)
        conf_u["E4_available_confirmation"] = conf_u["n_available"]
        conf_u["verdicts"]["E4"] = "pass" if conf_u["n_available"] >= 250 else "fail"
        conf_c0 = uefa_check(s_conf, C0)
        summary["uefa"][NAMES[comp]] = {
            "selection_grid": grid_u, "selection_c0": c0u,
            "chosen": None if cu is None else cu.__dict__, "reported": report_u.__dict__,
            "separate_threshold": cu is not None and cu.k != dk,
            "confirmation": conf_u, "confirmation_c0": conf_c0,
            "confirmation_vs_c0_identical": full_report(s_conf, report_u)["per_league"],
            "coverage_by_stage": stage_coverage(r, [C0] + [c1(k, report_u.L) for k in K_GRID]),
            "rows": {"selection": len(s_sel), "confirmation": len(s_conf)},
        }  # fmt: skip
    return summary


def tradeoff(r: Rows, cands) -> list[dict]:
    out = []
    for c in cands:
        ok = predict(r, c)[3]
        full = np.isin(r.season, FULL_SEASONS)
        out.append({
            "candidate": c.name,
            "coverage_full_seasons": round(float(ok[full].mean()), 4),
            "coverage_partial_season": round(float(ok[~full].mean()), 4),
            "min_league_full_season": min(
                (round(float(ok[full & (r.comp == x)].mean()), 4), NAMES[x])
                for x in DOMESTIC if (full & (r.comp == x)).any()),
        })  # fmt: skip
    return out


def stage_coverage(r: Rows, cands) -> list[dict]:
    rows = []
    for season in SEASONS:
        for label in sorted({(s, int(md)) for s, md in zip(r.stage, r.matchday, strict=True)},
                            key=lambda x: (x[0] == "knockout", x[1])):  # fmt: skip
            m = (r.season == season) & np.array(
                [(s, int(md)) == label for s, md in zip(r.stage, r.matchday, strict=True)]
            )
            if not m.any():
                continue
            sub = r.subset(m)
            row = {"season": season, "stage": label[0], "matchday": label[1] or "",
                   "fixtures": int(m.sum())}  # fmt: skip
            for c in cands:
                row[c.name] = round(float(predict(sub, c)[3].mean()), 3)
            rows.append(row)
    return rows


def reproduction_check(r: Rows, n: int = 200) -> dict:
    """C0 here must reproduce production Goal Model 1.0 (screener.goal_model.estimate)."""
    from diski9.screener import goal_model as gm

    mk, lh, la, ok = predict(r, C0)
    idx = np.flatnonzero(ok)[:: max(1, int(ok.sum()) // n)][:n]
    worst = 0.0
    for i in idx:
        t = r.team[i]
        rec = [gm.TeamRecord(*(int(x) for x in t[j : j + 6])) for j in (0, 6)]
        has_prev = r.prev_n[i] > 0
        if has_prev:
            ph, pa = r.prev_hg[i] / r.prev_n[i], r.prev_ag[i] / r.prev_n[i]
            H = (r.cur_hg[i] + M0 * ph) / (r.cur_n[i] + M0)
            A = (r.cur_ag[i] + M0 * pa) / (r.cur_n[i] + M0)
        else:
            H, A = r.cur_hg[i] / r.cur_n[i], r.cur_ag[i] / r.cur_n[i]
        lg = gm.LeagueRates(H, A, 0, 0, 0, 0, None, None, "x")
        e = gm.estimate(rec[0], rec[1], lg)
        worst = max(worst, abs(e["lambda_home"] - lh[i]), abs(e["lambda_away"] - la[i]),
                    abs(e["probabilities"]["home"] - mk["home"][i]))  # fmt: skip
    return {"checked": len(idx), "max_abs_difference": worst, "ok": worst < 1e-9}


# ------------------------------------------------------------------ market fits
def run_market(tmp: Path) -> dict:
    from sqlalchemy import select

    from diski9.api_football.markets import Market
    from diski9.db.schema import fixtures, odds_fixture_observations
    from diski9.odds.display import display_consensus
    from diski9.research.market_implied_xg import MarketInputs, fit, from_display

    eng, _ = _copy_store(DEV_DB, tmp)
    rows, timings = [], []
    with eng.connect() as conn:
        obs = conn.execute(
            select(odds_fixture_observations.c.fixture_id, odds_fixture_observations.c.retrieved_at,
                   fixtures.c.kickoff_utc, fixtures.c.competition_id)
            .join(fixtures, fixtures.c.id == odds_fixture_observations.c.fixture_id)
            .distinct()
        ).all()  # fmt: skip
        for fid, t, ko, comp in sorted(obs, key=lambda x: (x[1], x[0])):
            t = t if t.tzinfo else t.replace(tzinfo=UTC)
            ko = ko if ko.tzinfo else ko.replace(tzinfo=UTC)
            if ko <= t:
                continue
            disp = display_consensus(conn, fid, t)
            fresh = from_display(disp, fid)  # fresh markets only (prototype default)
            elig = {
                "1x2": disp[Market.MATCH_RESULT].challenge_eligible,
                "btts": disp[Market.BTTS].challenge_eligible,
                "ou25": disp[Market.OVER_UNDER_25].challenge_eligible,
            }
            av = fresh.available()
            use = {m: v for m, v in av.items() if elig[m]}
            rule_ok = "1x2" in use and ("btts" in use or "ou25" in use)
            row = {
                "fixture_id": fid, "competition": NAMES.get(comp, comp),
                "retrieved_at": t.isoformat(), "hours_to_kickoff": round((ko - t).total_seconds()
                                                                         / 3600, 1),
                "fresh_markets": "+".join(av), "eligible_markets": "+".join(use),
                "groups_1x2": (disp[Market.MATCH_RESULT].consensus.sources
                               if disp[Market.MATCH_RESULT].consensus else 0),
                "rule_ok": rule_ok,
            }  # fmt: skip
            if rule_ok:
                inp = MarketInputs(use.get("1x2"), use.get("btts"), use.get("ou25"))
                t0 = time.perf_counter()
                res = fit(inp)
                timings.append(time.perf_counter() - t0)
                row.update({
                    "status": res.status, "lambda_home": res.lambda_home,
                    "lambda_away": res.lambda_away, "max_abs_residual": res.max_abs_residual,
                    "converged": res.converged, "at_boundary": res.at_boundary,
                    "identified": res.identified,
                    "smallest_singular_value": res.jacobian_singular_values[-1]
                    if res.jacobian_singular_values else None,
                    **{f"res_{m}_{i}": res.residuals[m][i] for m in res.residuals
                       for i in range(len(res.residuals[m]))},
                    **{f"market_{m}_{i}": res.market[m][i] for m in res.market
                       for i in range(len(res.market[m]))},
                    **{f"fitted_{m}_{i}": res.model[m][i] for m in res.model
                       for i in range(len(res.model[m]))},
                })  # fmt: skip
            else:
                row["status"] = "rejected_inputs"
            rows.append(row)
    eng.dispose()
    write_csv(OUT / "market_fits.csv", rows)
    fitted = [r for r in rows if r["rule_ok"]]

    def dist(vals):
        vals = sorted(v for v in vals if v is not None)
        if not vals:
            return None
        q = lambda p: round(vals[min(len(vals) - 1, int(p * (len(vals) - 1)))], 5)  # noqa: E731
        return {"p10": q(0.1), "median": q(0.5), "p90": q(0.9), "max": q(1.0), "n": len(vals)}

    by_status = defaultdict(int)
    for r in rows:
        by_status[r["status"]] += 1
    resid_mean = {}
    for key, label in (("res_1x2_0", "home"), ("res_1x2_1", "draw"), ("res_1x2_2", "away"),
                       ("res_btts_0", "btts_yes"), ("res_ou25_0", "over")):  # fmt: skip
        v = [r[key] for r in fitted if r.get(key) is not None]
        resid_mean[label] = round(statistics.mean(v), 5) if v else None
    best = {}
    for r in fitted:  # latest snapshot per fixture
        best[r["fixture_id"]] = r
    return {
        "snapshots": len(rows),
        "unique_fixtures": len({r["fixture_id"] for r in rows}),
        "fixtures_by_league": _count({r["fixture_id"]: r["competition"] for r in rows}.values()),
        "snapshots_meeting_input_rule": len(fitted),
        "fixtures_meeting_input_rule": len({r["fixture_id"] for r in fitted}),
        "rejected_input_reasons": _count(
            f"fresh={r['fresh_markets'] or 'none'}; eligible={r['eligible_markets'] or 'none'}"
            for r in rows
            if not r["rule_ok"]
        ),
        "status_counts": dict(by_status),
        "status_latest_per_fixture": _count(r["status"] for r in best.values()),
        "status_by_league_latest": _count(
            f"{r['competition']}: {r['status']}" for r in best.values()
        ),
        "markets_used": _count(r["eligible_markets"] for r in fitted),
        "max_abs_residual": dist(r.get("max_abs_residual") for r in fitted),
        "mean_residual_fitted_minus_market": resid_mean,
        "lambda_home": dist(r.get("lambda_home") for r in fitted),
        "lambda_away": dist(r.get("lambda_away") for r in fitted),
        "smallest_singular_value": dist(r.get("smallest_singular_value") for r in fitted),
        "not_converged": sum(1 for r in fitted if r.get("converged") is False),
        "at_boundary": sum(1 for r in fitted if r.get("at_boundary")),
        "not_identified": sum(1 for r in fitted if r.get("identified") is False),
        "fit_latency_seconds": dist(timings),
        "footprint": footprint(),
    }


def _count(items) -> dict:
    c = defaultdict(int)
    for x in items:
        c[str(x)] += 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def footprint() -> dict:
    """Installed size of numpy and scipy (and their bundled libraries) in this
    environment, scipy.optimize import time and process peak memory."""
    import importlib.util
    import subprocess

    sizes = {}
    for pkg in ("numpy", "scipy"):
        spec = importlib.util.find_spec(pkg)
        base = Path(spec.origin).parent
        total = sum(f.stat().st_size for f in base.rglob("*") if f.is_file())
        libs = base.parent / f"{pkg}.libs"
        if libs.exists():
            total += sum(f.stat().st_size for f in libs.rglob("*") if f.is_file())
        sizes[pkg] = round(total / 2**20, 1)
    rss = "int(next(l for l in open('/proc/self/status') if l.startswith('VmRSS')).split()[1])"
    code = ("import time;t=time.perf_counter();import scipy.optimize, numpy;"
            f"d=time.perf_counter()-t;print(d, {rss})")  # fmt: skip
    base_code = f"import sqlalchemy, dash;print({rss})"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout
    base = subprocess.run([sys.executable, "-c", base_code], capture_output=True, text=True).stdout
    secs, rss_kib = out.split()
    both = subprocess.run(
        [sys.executable, "-c", f"import sqlalchemy, dash, scipy.optimize, numpy;print({rss})"],
        capture_output=True,
        text=True,
    ).stdout
    return {
        "installed_mib": sizes,
        "import_scipy_optimize_seconds": round(float(secs), 3),
        "rss_scipy_numpy_only_mib": round(int(rss_kib) / 1024, 1),
        "rss_dash_sqlalchemy_mib": round(int(base) / 1024, 1),
        "rss_dash_sqlalchemy_plus_scipy_mib": round(int(both) / 1024, 1),
        "note": "production code imports neither numpy nor scipy today (research modules only)",
    }  # fmt: skip


# ------------------------------------------------------------------ weekly pools
ODDS_LEAGUES = (39, 40, 140, 61, 78, 135)  # PSL and PSL 1st Division: no provider odds


def run_pools(tmp: Path, chosen: Candidate | None) -> dict:
    """Season-start pool feasibility from real schedules (fixture availability)."""
    from diski9.challenge.config import A3_432_V1 as CFG
    from diski9.challenge.structured import _match
    from diski9.db.schema import fixtures

    store, stage = load_matches(tmp)
    sched = []  # every scheduled league fixture (any status) in the odds leagues
    for path, comps in ((DEV_DB, (39, 40)), (RESEARCH_DB, (140, 61, 78, 135))):
        from sqlalchemy import select

        from diski9.db import make_engine

        dst = tmp / ("s_" + path.name)
        shutil.copy(path, dst)
        eng = make_engine(f"sqlite:///{dst}")
        with eng.connect() as c:
            for r in c.execute(select(fixtures).where(fixtures.c.competition_id.in_(comps))):
                if r.round_type == "regular" or (r.round_name or "").lower().startswith("regular"):
                    k = r.kickoff_utc if r.kickoff_utc.tzinfo else r.kickoff_utc.replace(tzinfo=UTC)
                    sched.append((r.competition_id, r.season, k, r.home_team_id, r.away_team_id))
        eng.dispose()
    # real snapshot bucket profiles (A3) of fully priced fixtures
    snap = json.loads(Path("docs/research/weekly_challenge_risk/pool_weekend.json").read_text())
    profiles = []
    for f in snap["fixtures"]:
        b = {CFG.classify(o["p_market"]) for o in f["outcomes"] if o["eligible"]} - {None}
        if any(o["eligible"] for o in f["outcomes"]):
            profiles.append(b)
    need = dict(zip(CFG.bucket_codes, CFG.sizes, strict=True))
    rng = np.random.default_rng(20261126)

    def feasible_share(n: int, reps: int = 400) -> float:
        if n < sum(need.values()):
            return 0.0
        ok = 0
        for _ in range(reps):
            pick = rng.integers(0, len(profiles), n)
            ok += _match(need, {i: profiles[j] for i, j in enumerate(pick)})
        return round(ok / reps, 3)

    treatments = {"no_model_required": None, "C0_required": C0}
    if chosen is not None:
        treatments[f"{chosen.name}_required"] = chosen
        treatments[f"C0-{chosen.k}_required"] = c0k(chosen.k)
    out_rows = []
    for season in (2024, 2025, 2026):
        ks = sorted(k for c, s, k, *_ in sched if s == season)
        if not ks:
            continue
        first = ks[0]
        fri = first - timedelta(days=(first.weekday() - 4) % 7)
        fri = fri.replace(hour=0, minute=0, second=0, microsecond=0)
        for w in range(8):
            start = fri + timedelta(days=7 * w)
            end = start + timedelta(days=4)
            pub = start + timedelta(hours=6)  # Friday 08:00 SAST publication
            fx = [x for x in sched if x[1] == season and start <= x[2] < end]
            row = {"season": f"{season}/{(season + 1) % 100:02d}", "window_friday":
                   start.date().isoformat(), "scheduled_fixtures": len(fx)}  # fmt: skip
            for name, c in treatments.items():
                elig = [x for x in fx if c is None or _available_at(store, x, pub, c)]
                leagues = {x[0] for x in elig}
                row[f"{name}_fixtures"] = len(elig)
                row[f"{name}_leagues"] = len(leagues)
                row[f"{name}_opens"] = len(elig) >= 15 and len(leagues) >= 3
                row[f"{name}_feasible_share"] = feasible_share(len(elig)) if row[
                    f"{name}_opens"] else 0.0  # fmt: skip
            out_rows.append(row)
    write_csv(OUT / "weekly_pools.csv", out_rows)
    return {"windows": out_rows, "snapshot_profiles": len(profiles),
            "treatments": list(treatments)}  # fmt: skip


def _available_at(store, x, cutoff: datetime, c: Candidate) -> bool:
    comp, season, _, h, a = x
    cur = store.league_matches(comp, season, cutoff)
    prev = store.league_matches(comp, season - 1, datetime(2100, 1, 1, tzinfo=UTC))
    n = len(cur)
    lg_ok = (bool(prev) or n >= gd.LEAGUE_MIN) if c.m0 is not None else n >= max(c.L, 1)
    if not lg_ok:
        return False
    nh = len(store.team_window(h, cutoff, None, 999, comp, season))
    na = len(store.team_window(a, cutoff, None, 999, comp, season))
    return min(nh, na) >= c.k


# ------------------------------------------------------------------ main
def _json(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(type(o))


def main(what: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if what in ("model", "all"):
            s = run_model(tmp)
            (OUT / "model_summary.json").write_text(json.dumps(s, indent=1, default=_json))
        if what in ("market", "all"):
            s = run_market(tmp)
            (OUT / "market_summary.json").write_text(json.dumps(s, indent=1, default=_json))
        if what in ("pools", "all"):
            ms = json.loads((OUT / "model_summary.json").read_text())
            ch = ms.get("domestic_chosen")
            chosen = Candidate(**ch) if ch else None
            s = run_pools(tmp, chosen)
            (OUT / "pools_summary.json").write_text(json.dumps(s, indent=1, default=_json))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
