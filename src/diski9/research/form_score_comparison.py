"""Research only (Milestone 5.1): banded (Method A, production) vs continuous
(Method B, candidate) Diski Form Score.

Nothing here is used by the Screener, the cache or the Challenge. Method A is
imported from the production code unchanged; Method B is implemented here.

Partial-window policy (identical for both methods, from production):
* use the matches actually available; nothing is prorated or scaled to five
* points and goal difference use the actual totals in the window
* won-last-three bonus needs at least three matches
* scored-11+ bonus may be earned in any window
* conceded-2-or-fewer bonus needs a full five-match window

For Method B this means P = 2.5 x points / 15 and G = 2.5 x min(max(GD, 0) / 9, 1)
with the window's *actual* points and GD, so a partial window cannot reach the
maximum - exactly as under Method A.
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from diski9.screener.calc import diski_form_score
from diski9.screener.engine import MatchStore

RAW_MAX = Fraction(13, 2)


# ---------------------------------------------------------------- Method B
@dataclass(frozen=True)
class ContinuousFormScore:
    matches: int
    points: int
    goals_for: int
    goals_against: int
    last_three_won: bool

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def points_component(self) -> Fraction:
        return Fraction(5, 2) * Fraction(self.points, 15)

    @property
    def goal_difference_component(self) -> Fraction:
        return Fraction(5, 2) * min(Fraction(max(self.goal_difference, 0), 9), Fraction(1))

    @property
    def bonuses(self) -> Fraction:
        b = Fraction(0)
        if self.matches >= 3 and self.last_three_won:
            b += Fraction(1, 2)
        if self.goals_for >= 11:
            b += Fraction(1, 2)
        if self.matches >= 5 and self.goals_against <= 2:
            b += Fraction(1, 2)
        return b

    @property
    def raw(self) -> Fraction:
        return self.points_component + self.goal_difference_component + self.bonuses

    @property
    def score(self) -> Fraction:
        return self.raw * 5 / RAW_MAX


def exploratory_symmetric_gd_score(results: Iterable[tuple[int, int]]) -> Fraction | None:
    """Exploratory Method C (diagnostic only, not proposed as-is): Method B with a
    symmetric goal-difference component G = 1.25 + 1.25 x clip(GD / 9, -1, 1), so that
    negative goal differences are distinguished instead of all scoring zero."""
    b = continuous_form_score(results)
    if b is None:
        return None
    g = Fraction(5, 4) + Fraction(5, 4) * max(
        Fraction(-1), min(Fraction(1), Fraction(b.goal_difference, 9))
    )
    return (b.points_component + g + b.bonuses) * 5 / RAW_MAX


def continuous_form_score(results: Iterable[tuple[int, int]]) -> ContinuousFormScore | None:
    """(goals_for, goals_against) pairs, most recent first; None if no matches."""
    pairs = list(results)
    if not pairs:
        return None
    pts = sum(3 if f > a else 1 if f == a else 0 for f, a in pairs)
    last3 = len(pairs) >= 3 and all(f > a for f, a in pairs[:3])
    return ContinuousFormScore(
        len(pairs), pts, sum(f for f, _ in pairs), sum(a for _, a in pairs), last3
    )


# --------------------------------------------------------------- dataset
@dataclass
class Row:
    fixture_id: int
    competition_id: int
    season: int
    kickoff: datetime
    outcome: str  # H / D / A
    basis: str
    home_n: int
    away_n: int
    a_home: float | None
    a_away: float | None
    b_home: float | None
    b_away: float | None
    c_home: float | None
    c_away: float | None
    promoted_involved: bool  # a window draws on another division
    home_bonuses: tuple[bool, bool, bool]
    away_bonuses: tuple[bool, bool, bool]
    home_gd: int | None
    away_gd: int | None

    @property
    def a_diff(self) -> float | None:
        return None if self.a_home is None or self.a_away is None else self.a_home - self.a_away

    @property
    def b_diff(self) -> float | None:
        return None if self.b_home is None or self.b_away is None else self.b_home - self.b_away

    @property
    def c_diff(self) -> float | None:
        return None if self.c_home is None or self.c_away is None else self.c_home - self.c_away

    @property
    def complete(self) -> bool:
        return self.home_n == 5 and self.away_n == 5


def build_dataset(
    store: MatchStore, competitions: Iterable[int], seasons: Iterable[int]
) -> list[Row]:
    """Point-in-time windows (cutoff = kickoff) for every eligible completed fixture."""
    comps, yrs = set(competitions), set(seasons)
    rows: list[Row] = []
    for m in store.matches:
        if not m.stats_eligible or m.competition_id not in comps or m.season not in yrs:
            continue
        outcome = (
            "H" if m.home_goals > m.away_goals else "D" if m.home_goals == m.away_goals else "A"
        )
        for basis in ("venue", "overall"):
            hw = store.team_window(m.home_id, m.kickoff, "home" if basis == "venue" else None, 5)
            aw = store.team_window(m.away_id, m.kickoff, "away" if basis == "venue" else None, 5)
            hp = [(t.goals_for, t.goals_against) for t in hw]
            ap = [(t.goals_for, t.goals_against) for t in aw]
            ha, aa = diski_form_score(hp), diski_form_score(ap)
            hb, ab = continuous_form_score(hp), continuous_form_score(ap)

            def bonus(fs):
                return (
                    (
                        bool(fs.bonus_last_three_wins),
                        bool(fs.bonus_goals_scored),
                        bool(fs.bonus_goals_conceded),
                    )
                    if fs
                    else (False, False, False)
                )

            rows.append(
                Row(
                    m.fixture_id,
                    m.competition_id,
                    m.season,
                    m.kickoff,
                    outcome,
                    basis,
                    len(hw),
                    len(aw),
                    float(ha.score) if ha else None,
                    float(aa.score) if aa else None,
                    float(hb.score) if hb else None,
                    float(ab.score) if ab else None,
                    _f(exploratory_symmetric_gd_score(hp)),
                    _f(exploratory_symmetric_gd_score(ap)),
                    any(t.match.competition_id != m.competition_id for t in hw + aw),
                    bonus(ha),
                    bonus(aa),
                    ha.goal_difference if ha else None,
                    aa.goal_difference if aa else None,
                )
            )
    return rows


def _f(x: Fraction | None) -> float | None:
    return None if x is None else float(x)


# --------------------------------------------------------------- statistics
def describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    rounded = [round(v, 6) for v in values]
    counts = Counter(rounded)
    return {
        "n": len(values),
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
        "sd": round(pstdev(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "distinct": len(counts),
        "share_tied": round(sum(c for c in counts.values() if c > 1) / len(values), 3),
        "most_common": [round(counts.most_common(1)[0][0], 2), counts.most_common(1)[0][1]],
        "share_lowest_20pct_of_scale": round(sum(v <= 1.0 for v in values) / len(values), 3),
    }


def ranks(values: dict[Any, float]) -> dict[Any, float]:
    order = sorted(values, key=lambda k: values[k])
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in order[i : j + 1]:
            out[k] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: dict, b: dict) -> float | None:
    keys = [k for k in a if k in b]
    if len(keys) < 3:
        return None
    ra, rb = ranks({k: a[k] for k in keys}), ranks({k: b[k] for k in keys})
    ma, mb = mean(ra.values()), mean(rb.values())
    num = sum((ra[k] - ma) * (rb[k] - mb) for k in keys)
    den = math.sqrt(sum((ra[k] - ma) ** 2 for k in keys) * sum((rb[k] - mb) ** 2 for k in keys))
    return num / den if den else None


def top(values: dict, n: int, key) -> set:
    return set(sorted(values, key=lambda k: (key(values[k]), k))[:n])


def ranking_discrimination(rows: list[Row], basis: str) -> dict[str, Any]:
    """Screener-like lists: all fixtures kicking off in the same ISO week (all leagues)."""
    groups: dict[tuple, list[Row]] = defaultdict(list)
    for r in rows:
        if r.basis == basis and r.a_diff is not None:
            iso = r.kickoff.isocalendar()
            groups[(iso.year, iso.week)].append(r)
    stats = defaultdict(list)
    for g in groups.values():
        if len(g) < 10:
            continue
        a = {r.fixture_id: round(r.a_diff, 9) for r in g}
        b = {r.fixture_id: round(r.b_diff, 9) for r in g}
        for name, d in (("a", a), ("b", b)):
            c = Counter(d.values())
            stats[f"{name}_share_fixtures_tied"].append(
                sum(v for v in c.values() if v > 1) / len(d)
            )
            stats[f"{name}_distinct_share"].append(len(c) / len(d))
        rho = spearman(a, b)
        if rho is not None:
            stats["spearman_a_vs_b"].append(rho)
        for n in (5, 10):
            stats[f"top{n}_home_overlap"].append(
                len(top(a, n, lambda v: -v) & top(b, n, lambda v: -v)) / n
            )
            stats[f"top{n}_away_overlap"].append(
                len(top(a, n, lambda v: v) & top(b, n, lambda v: v)) / n
            )
            stats[f"top{n}_even_overlap"].append(len(top(a, n, abs) & top(b, n, abs)) / n)
    return {
        "weekly_lists": len(next(iter(stats.values()), [])),
        **{k: round(mean(v), 3) for k, v in stats.items()},
    }


def outcome_by_band(rows: list[Row], method: str, bands: list[tuple[float, float]]) -> list[dict]:
    out = []
    for lo, hi in bands:
        sel = [r for r in rows if (d := getattr(r, f"{method}_diff")) is not None and lo <= d < hi]
        n = len(sel)
        c = Counter(r.outcome for r in sel)
        out.append(
            {
                "band": f"[{lo:g}, {hi:g})",
                "n": n,
                "home": round(c["H"] / n, 3) if n else None,
                "draw": round(c["D"] / n, 3) if n else None,
                "away": round(c["A"] / n, 3) if n else None,
            }
        )
    return out


def outcome_by_quantile(rows: list[Row], method: str, q: int = 5) -> list[dict]:
    sel = sorted(
        (r for r in rows if getattr(r, f"{method}_diff") is not None),
        key=lambda r: (getattr(r, f"{method}_diff"), r.fixture_id),
    )
    out = []
    for i in range(q):
        chunk = sel[i * len(sel) // q : (i + 1) * len(sel) // q]
        c = Counter(r.outcome for r in chunk)
        ds = [getattr(r, f"{method}_diff") for r in chunk]
        out.append(
            {
                "quantile": i + 1,
                "n": len(chunk),
                "diff_range": [round(min(ds), 2), round(max(ds), 2)],
                "home": round(c["H"] / len(chunk), 3),
                "draw": round(c["D"] / len(chunk), 3),
                "away": round(c["A"] / len(chunk), 3),
            }
        )
    return out


# ------------------------------------------------- out-of-sample diagnostics
CLASSES = ("H", "D", "A")


def _softmax(z):
    import numpy as np

    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit_multinomial(x: list[float], y: list[str], l2: float = 1e-3):
    """Multinomial logistic regression, outcome ~ form difference (diagnostic only)."""
    import numpy as np
    from scipy.optimize import minimize

    X = np.column_stack([np.ones(len(x)), np.asarray(x, dtype=float)])
    Y = np.array([[c == k for k in CLASSES] for c in y], dtype=float)

    def nll(w):
        W = np.column_stack([np.zeros(2), w.reshape(2, 2)])  # home class is the reference
        P = _softmax(X @ W)
        return -(Y * np.log(np.clip(P, 1e-12, 1))).sum() / len(x) + l2 * (w**2).sum()

    res = minimize(nll, np.zeros(4), method="BFGS")
    return res.x, bool(res.success)


def predict(w, x: list[float]):
    import numpy as np

    X = np.column_stack([np.ones(len(x)), np.asarray(x, dtype=float)])
    W = np.column_stack([np.zeros(2), np.asarray(w).reshape(2, 2)])
    return _softmax(X @ W)


def scores(P, y: list[str]) -> dict[str, float]:
    import numpy as np

    Y = np.array([[c == k for k in CLASSES] for c in y], dtype=float)
    return {
        "log_loss": round(float(-(Y * np.log(np.clip(P, 1e-12, 1))).sum(axis=1).mean()), 4),
        "brier": round(float(((P - Y) ** 2).sum(axis=1).mean()), 4),
        "n": len(y),
    }


def out_of_sample(
    rows: list[Row], train_seasons: set[int], test_seasons: set[int], basis: str
) -> dict:
    import numpy as np

    data = [r for r in rows if r.basis == basis and r.a_diff is not None]
    train = [r for r in data if r.season in train_seasons]
    test = [r for r in data if r.season in test_seasons]
    y_tr, y_te = [r.outcome for r in train], [r.outcome for r in test]
    base = np.array([[sum(c == k for c in y_tr) / len(y_tr) for k in CLASSES]] * len(test))
    league_rates = {}
    for comp in {r.competition_id for r in train}:
        ys = [r.outcome for r in train if r.competition_id == comp]
        league_rates[comp] = [sum(c == k for c in ys) / len(ys) for k in CLASSES]
    base_league = np.array([league_rates.get(r.competition_id, base[0]) for r in test])
    out = {
        "train_n": len(train),
        "test_n": len(test),
        "baseline_overall_rates": scores(base, y_te),
        "baseline_league_rates": scores(base_league, y_te),
    }
    for method in ("a", "b", "c"):
        w, ok = fit_multinomial([getattr(r, f"{method}_diff") for r in train], y_tr)
        P = predict(w, [getattr(r, f"{method}_diff") for r in test])
        out[f"method_{method}"] = {
            **scores(P, y_te),
            "converged": ok,
            "coef_draw_away": [round(float(v), 3) for v in w],
        }
    return out


def bootstrap_logloss_difference(
    rows: list[Row], train_seasons, test_seasons, basis: str, reps: int = 500, seed: int = 7
) -> dict:
    """Paired bootstrap of per-fixture log-loss difference (B - A) on the test set."""
    import numpy as np

    data = [r for r in rows if r.basis == basis and r.a_diff is not None]
    train = [r for r in data if r.season in train_seasons]
    test = [r for r in data if r.season in test_seasons]
    y_tr, y_te = [r.outcome for r in train], [r.outcome for r in test]
    idx = np.array([CLASSES.index(c) for c in y_te])
    losses = {}
    for method in ("a", "b"):
        w, _ = fit_multinomial([getattr(r, f"{method}_diff") for r in train], y_tr)
        P = predict(w, [getattr(r, f"{method}_diff") for r in test])
        losses[method] = -np.log(np.clip(P[np.arange(len(idx)), idx], 1e-12, 1))
    d = losses["b"] - losses["a"]
    rng = np.random.default_rng(seed)
    boots = [float(d[rng.integers(0, len(d), len(d))].mean()) for _ in range(reps)]
    boots.sort()
    return {
        "mean_diff_b_minus_a": round(float(d.mean()), 5),
        "ci95": [round(boots[int(0.025 * reps)], 5), round(boots[int(0.975 * reps)], 5)],
        "n": len(d),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
