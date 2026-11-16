"""Research only (Milestone 5.2): shared evaluation utilities.

Proper scoring rules, calibration tables, walk-forward folds and a paired
bootstrap clustered by ISO week. Nothing here is used by the app.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

EPS = 1e-12
SEED = 52


# ------------------------------------------------------------ scoring rules
def log_loss_multiclass(P: np.ndarray, y: Sequence[int]) -> np.ndarray:
    """Per-row negative log probability of the observed class."""
    P = np.asarray(P, dtype=float)
    idx = np.asarray(y, dtype=int)
    return -np.log(np.clip(P[np.arange(len(idx)), idx], EPS, 1))


def brier_multiclass(P: np.ndarray, y: Sequence[int]) -> np.ndarray:
    P = np.asarray(P, dtype=float)
    Y = np.zeros_like(P)
    Y[np.arange(len(y)), np.asarray(y, dtype=int)] = 1
    return ((P - Y) ** 2).sum(axis=1)


def log_loss_binary(p: Sequence[float], y: Sequence[int], clip: float = EPS) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), clip, 1 - clip)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier_binary(p: Sequence[float], y: Sequence[int]) -> np.ndarray:
    return (np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2


def auc(p: Sequence[float], y: Sequence[int]) -> float | None:
    """Area under the ROC curve (Mann-Whitney, ties count one half)."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=int)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    allv = np.concatenate([pos, neg])[order]
    ranks = np.empty(len(allv))
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        ranks[i : j + 1] = (i + j) / 2 + 1
        i = j + 1
    r = np.empty(len(allv))
    r[order] = ranks
    return float((r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def calibration_table(
    p: Sequence[float], y: Sequence[int], edges: Sequence[float] | None = None
) -> list[dict[str, Any]]:
    """Observed frequency against mean forecast in fixed bins."""
    edges = list(edges) if edges is not None else [i / 10 for i in range(11)]
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    out = []
    for k, (lo, hi) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        last = k == len(edges) - 2
        m = (p >= lo) & ((p <= hi) if last else (p < hi))
        n = int(m.sum())
        out.append(
            {
                "bin": f"[{lo:.2f}, {hi:.2f}{']' if last else ')'}",
                "n": n,
                "mean_forecast": round(float(p[m].mean()), 4) if n else None,
                "observed": round(float(y[m].mean()), 4) if n else None,
            }
        )
    return out


def expected_calibration_error(p: Sequence[float], y: Sequence[int]) -> float:
    tab = calibration_table(p, y)
    n = sum(r["n"] for r in tab)
    return round(
        sum(r["n"] * abs(r["mean_forecast"] - r["observed"]) for r in tab if r["n"]) / n, 4
    )


# --------------------------------------------------------------- bootstrap
def iso_week(t: datetime) -> tuple[int, int]:
    iso = t.astimezone(UTC).isocalendar()
    return (iso.year, iso.week)


def paired_bootstrap(
    diff: Sequence[float], clusters: Sequence[Any], reps: int = 2000, seed: int = SEED
) -> dict[str, float]:
    """Mean of a per-row difference with a 95% interval, resampling whole clusters
    (ISO weeks) so that fixtures played in the same week are not treated as
    independent."""
    diff = np.asarray(diff, dtype=float)
    groups: dict[Any, list[int]] = defaultdict(list)
    for i, c in enumerate(clusters):
        groups[c].append(i)
    keys = list(groups)
    sums = np.array([diff[groups[k]].sum() for k in keys])
    counts = np.array([len(groups[k]) for k in keys])
    rng = np.random.default_rng(seed)
    boots = np.empty(reps)
    for b in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        boots[b] = sums[pick].sum() / counts[pick].sum()
    lo, hi = np.quantile(boots, [0.025, 0.975])
    return {
        "mean": round(float(diff.mean()), 5),
        "ci95": [round(float(lo), 5), round(float(hi), 5)],
        "n": len(diff),
        "clusters": len(keys),
        "excludes_zero": bool(lo > 0 or hi < 0),
    }


# ------------------------------------------------------------ walk-forward
@dataclass(frozen=True)
class Fold:
    label: str
    start: datetime
    end: datetime


def monthly_folds(first: datetime, last: datetime) -> list[Fold]:
    """Calendar-month test windows from ``first`` up to and including ``last``."""
    folds = []
    y, m = first.year, first.month
    while datetime(y, m, 1, tzinfo=UTC) <= last:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        folds.append(
            Fold(f"{y}-{m:02d}", datetime(y, m, 1, tzinfo=UTC), datetime(ny, nm, 1, tzinfo=UTC))
        )
        y, m = ny, nm
    return folds


def walk_forward(
    rows: Sequence[Any],
    folds: Iterable[Fold],
    kickoff: Callable[[Any], datetime],
    fit: Callable[[list[Any]], Any],
    predict: Callable[[Any, list[Any]], np.ndarray],
    min_train: int = 200,
) -> tuple[list[Any], np.ndarray]:
    """Expanding-window evaluation. Each test row is predicted by a model fitted
    only on rows that kicked off strictly before its fold started."""
    test_rows: list[Any] = []
    preds: list[np.ndarray] = []
    for f in folds:
        train = [r for r in rows if kickoff(r) < f.start]
        test = [r for r in rows if f.start <= kickoff(r) < f.end]
        if len(train) < min_train or not test:
            continue
        model = fit(train)
        preds.append(np.asarray(predict(model, test)))
        test_rows.extend(test)
    if not preds:
        return [], np.empty((0,))
    return test_rows, np.concatenate(preds)


# ---------------------------------------------------- multinomial logistic
CLASSES = ("H", "D", "A")


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


@dataclass
class Multinomial:
    weights: np.ndarray  # (features + 1) x 2 ; home class is the reference
    mean: np.ndarray
    scale: np.ndarray
    converged: bool

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=float))
        Z = np.column_stack([np.ones(len(X)), (X - self.mean) / self.scale])
        W = np.column_stack([np.zeros(Z.shape[1]), self.weights])
        return _softmax(Z @ W)


def fit_multinomial(X: np.ndarray, y: Sequence[int], l2: float = 1e-4) -> Multinomial:
    """Multinomial logistic regression (H/D/A) with standardised features and a
    tiny ridge penalty for numerical stability. Deterministic."""
    from scipy.optimize import minimize

    X = np.atleast_2d(np.asarray(X, dtype=float))
    if X.shape[0] == 1 and len(y) != 1:
        X = X.T
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1
    Z = np.column_stack([np.ones(len(X)), (X - mean) / scale])
    Y = np.zeros((len(y), 3))
    Y[np.arange(len(y)), np.asarray(y, dtype=int)] = 1
    k = Z.shape[1]

    def nll(w):
        W = np.column_stack([np.zeros(k), w.reshape(k, 2)])
        P = _softmax(Z @ W)
        G = Z.T @ (P - Y) / len(Z)
        return (
            -(Y * np.log(np.clip(P, EPS, 1))).sum() / len(Z) + l2 * (w**2).sum(),
            G[:, 1:].ravel() + 2 * l2 * w,
        )

    res = minimize(nll, np.zeros(2 * k), jac=True, method="L-BFGS-B")
    return Multinomial(res.x.reshape(k, 2), mean, scale, bool(res.success))


@dataclass
class Logistic:
    weights: np.ndarray
    mean: np.ndarray
    scale: np.ndarray

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=float))
        Z = np.column_stack([np.ones(len(X)), (X - self.mean) / self.scale])
        return 1 / (1 + np.exp(-(Z @ self.weights)))


def fit_logistic(X: np.ndarray, y: Sequence[int], l2: float = 1e-4) -> Logistic:
    from scipy.optimize import minimize

    X = np.atleast_2d(np.asarray(X, dtype=float))
    mean, scale = X.mean(axis=0), X.std(axis=0)
    scale[scale == 0] = 1
    Z = np.column_stack([np.ones(len(X)), (X - mean) / scale])
    yv = np.asarray(y, dtype=float)

    def nll(w):
        p = np.clip(1 / (1 + np.exp(-(Z @ w))), EPS, 1 - EPS)
        return (
            -(yv * np.log(p) + (1 - yv) * np.log(1 - p)).mean() + l2 * (w[1:] ** 2).sum(),
            Z.T @ (p - yv) / len(Z) + 2 * l2 * np.concatenate([[0], w[1:]]),
        )

    res = minimize(nll, np.zeros(Z.shape[1]), jac=True, method="L-BFGS-B")
    return Logistic(res.x, mean, scale)
