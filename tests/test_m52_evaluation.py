"""Milestone 5.2 research: evaluation utilities, goals dataset and the
result-validation pipeline (research only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from diski9.ingestion.fixtures import store_fixtures
from diski9.odds.collect import OddsPage, reconcile_pages
from diski9.research.evaluation import (
    auc,
    brier_binary,
    brier_multiclass,
    calibration_table,
    fit_multinomial,
    log_loss_binary,
    log_loss_multiclass,
    monthly_folds,
    paired_bootstrap,
    walk_forward,
)
from diski9.research.goal_models import Spec, probabilities
from diski9.research.historical_goals import build_rows, fit_rho, league_prior
from diski9.research.result_validation import Record, collect_records, evaluate
from diski9.screener.engine import Match, MatchStore

from .factories import T0, fixture_item, full_book, odds_item, seed_competition

T = datetime(2025, 8, 1, 15, tzinfo=UTC)


# ---------------------------------------------------------------- metrics
def test_scoring_rules_known_values():
    P = np.array([[0.5, 0.3, 0.2], [0.2, 0.3, 0.5]])
    assert log_loss_multiclass(P, [0, 2]).tolist() == pytest.approx([-np.log(0.5)] * 2)
    assert brier_multiclass(P, [0, 2]).tolist() == pytest.approx([0.25 + 0.09 + 0.04] * 2)
    assert brier_binary([0.7], [1])[0] == pytest.approx(0.09)
    assert log_loss_binary([0.7], [0])[0] == pytest.approx(-np.log(0.3))
    assert auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert auc([0.5, 0.5], [0, 1]) == 0.5
    assert auc([0.1, 0.2], [0, 0]) is None
    tab = calibration_table([0.05, 0.15, 0.95, 1.0], [0, 1, 1, 1])
    assert tab[0]["n"] == 1 and tab[-1]["n"] == 2 and tab[-1]["observed"] == 1


def test_paired_bootstrap_is_deterministic_and_clustered():
    d = [0.01] * 50 + [-0.01] * 50
    weeks = [i // 10 for i in range(100)]
    a, b = paired_bootstrap(d, weeks), paired_bootstrap(d, weeks)
    assert a == b and a["clusters"] == 10 and a["mean"] == 0
    assert not a["excludes_zero"]
    assert paired_bootstrap([0.02] * 40, [i // 4 for i in range(40)])["excludes_zero"]


def test_walk_forward_trains_only_on_earlier_fixtures():
    rows = [{"t": T + timedelta(days=d), "y": d % 3} for d in range(0, 400, 2)]
    folds = monthly_folds(T + timedelta(days=200), T + timedelta(days=398))
    seen = []

    def fit(train):
        seen.append(max(r["t"] for r in train))
        return len(train)

    def predict(model, test):
        assert all(seen[-1] < r["t"] for r in test)
        return np.zeros((len(test), 3))

    test_rows, P = walk_forward(rows, folds, lambda r: r["t"], fit, predict, min_train=10)
    assert len(test_rows) == len(P) and test_rows
    starts = {f.label: f.start for f in folds}
    for r in test_rows:
        fold = f"{r['t'].year}-{r['t'].month:02d}"
        assert r["t"] >= starts[fold]
    assert len({id(r) for r in test_rows}) == len(test_rows)  # no duplicates


def test_multinomial_learns_a_monotone_relationship():
    rng = np.random.default_rng(0)
    x = rng.normal(size=3000)
    p_home = 1 / (1 + np.exp(-x))
    y = np.where(rng.random(3000) < p_home, 0, 2)
    m = fit_multinomial(x[:, None], y)
    P = m.predict(np.array([[-2.0], [2.0]]))
    assert P[1, 0] > P[0, 0] and m.converged
    assert P.sum(axis=1) == pytest.approx([1, 1])


# ------------------------------------------------------------- goals dataset
def mm(fid, days, comp, season, h, a, hg, ag, eligible=True):
    return Match(
        fid,
        T + timedelta(days=days),
        comp,
        season,
        h,
        a,
        hg,
        ag,
        "verified",
        eligible,
        None,
        None,
        "FT",
        str(fid),
    )


def goal_store():
    ms = []
    fid = 1
    # previous season of the league (prior) and of the second tier
    for d in range(40):
        ms.append(mm(fid, -300 + d, 39, 2024, 20 + d % 6, 30 + d % 6, d % 3, d % 2))
        fid += 1
    ms.append(mm(fid, -250, 40, 2024, 1, 50, 5, 5))
    fid += 1  # team 1 in tier 2 last season
    ms += [
        mm(500, 0, 39, 2025, 1, 2, 2, 1),
        mm(501, 7, 39, 2025, 2, 1, 0, 0),
        mm(502, 14, 39, 2025, 1, 3, 1, 1),
        mm(503, 14, 39, 2025, 2, 4, 3, 3),  # same kickoff as 502
        mm(504, 21, 39, 2025, 1, 2, 4, 0, eligible=False),  # awarded
        mm(505, 28, 39, 2025, 1, 2, 1, 2),
    ]
    return MatchStore.from_matches(ms, {}, {39: "EPL", 40: "Ch"})


def test_goals_windows_current_season_and_competition_only():
    rows = {(r.fixture_id, r.basis): r for r in build_rows(goal_store(), (39,), (2025,))}
    r = rows[(505, "overall")]
    # team 1: 500, 501, 502 (504 awarded excluded); last season's tier-2 match never used
    assert r.n_home == 3 and r.btts_home == pytest.approx(2 / 3)
    # team 2: 500, 501, 503 (504 excluded)
    assert r.n_away == 3 and r.btts_away == pytest.approx(2 / 3)
    assert r.btts_indicator == pytest.approx(2 / 3)
    # same-kickoff fixture 503 never enters 502's window
    r502 = rows[(502, "overall")]
    assert r502.n_away == 0 and r502.btts_indicator is None
    assert 504 not in {k[0] for k in rows}
    assert len(rows) == len(set(rows))


def test_league_prior_provenance():
    store = goal_store()
    lg = league_prior(store, 39, 2025, T + timedelta(days=28))
    assert lg.source == "blended_previous" and lg.current_matches == 4
    assert league_prior(store, 39, 2025, T).source == "previous_only"
    assert league_prior(store, 39, 2024, T - timedelta(days=300)) is None  # nothing stored


def test_rho_estimate_recovers_simulated_dependence():
    from types import SimpleNamespace

    rng = np.random.default_rng(1)
    rows = []
    for _ in range(6000):
        lh, la = rng.uniform(0.8, 2.0), rng.uniform(0.6, 1.6)
        M = __import__("diski9.research.goal_models", fromlist=["score_matrix"]).score_matrix(
            lh, la, -0.12
        )[0]
        k = rng.choice(M.size, p=M.ravel())
        h, a = divmod(k, M.shape[1])
        rows.append(SimpleNamespace(lambda_home=lh, lambda_away=la, home_goals=h, away_goals=a))
    assert fit_rho(rows) == pytest.approx(-0.12, abs=0.05)


# ------------------------------------------------------ result validation
KICK = T0 + timedelta(days=3)


def books(home="1.80"):
    return {b: full_book(home=home) for b in (8, 11, 4)}


def collect(conn, at, homes: dict[int, str]):
    """One capture (one page) of all listed fixtures at ``at``."""
    items = [
        odds_item(fid, books(h), kickoff=KICK, update=(at - timedelta(hours=1)).isoformat())
        for fid, h in homes.items()
    ]
    reconcile_pages(conn, 39, 2026, [OddsPage(at, items)], clock=lambda: at)


def test_validation_uses_latest_fresh_pre_kickoff_snapshot_once(conn):
    seed_competition(conn)
    store_fixtures(
        conn,
        [
            fixture_item(1, 10, 20, status="NS", kickoff=KICK),
            fixture_item(2, 30, 40, status="NS", kickoff=KICK),
            fixture_item(4, 70, 80, status="NS", kickoff=KICK),
        ],
        lambda: T0,
    )
    collect(conn, T0, {1: "1.80", 2: "1.80", 4: "1.80"})
    collect(conn, T0 + timedelta(days=1), {1: "1.70", 2: "1.80", 4: "1.80"})  # latest pre-kickoff
    collect(conn, KICK + timedelta(minutes=30), {1: "3.00"})  # in-play prices: never used
    # results arrive: fixture 1 played, fixture 2 postponed, fixture 4 awarded
    store_fixtures(
        conn,
        [
            fixture_item(1, 10, 20, status="FT", kickoff=KICK, ft=(2, 1)),
            fixture_item(2, 30, 40, status="PST", kickoff=KICK),
            fixture_item(4, 70, 80, status="AWD", kickoff=KICK, ft=(3, 0)),
        ],
        lambda: KICK + timedelta(hours=3),
    )
    recs = collect_records(conn)
    assert [r.fixture_id for r in recs] == [1]
    r = recs[0]
    assert r.snapshot_at == T0 + timedelta(days=1) and r.snapshot_at < r.kickoff
    assert (r.home_goals, r.away_goals, r.outcome) == (2, 1, 0)
    assert set(r.market) == {"1x2", "btts", "ou25"}
    # implied home probability reflects the 1.70 snapshot, not the earlier 1.80
    raw = [1 / 1.70, 1 / 3.40, 1 / 3.80]
    assert r.market["1x2"][0] == pytest.approx(raw[0] / sum(raw), abs=1e-4)
    assert r.metadata["1X2"]["status"] == "fresh"


def test_evaluate_handles_empty_and_missing_markets():
    empty = evaluate([], (Spec(),))
    assert empty["fixtures"] == 0 and not empty["sufficient_for_comparison"] and empty["note"]
    p = probabilities(1.5, 1.1)
    full = {k: p[k] for k in ("1x2", "btts", "ou25")}
    recs = [
        Record(1, 39, 2026, KICK, T0, 2, 1, dict(full)),
        Record(2, 39, 2026, KICK, T0, 0, 0, {"1x2": full["1x2"]}),  # no goals markets
    ]
    out = evaluate(recs, (Spec(),))
    assert out["results"]["1x2"]["fixtures"] == 2
    assert out["results"]["1x2+btts+ou25"]["fixtures"] == 1
    r = out["results"]["1x2+btts+ou25"]["poisson/kl"]
    assert r["usable_fits"] == 1
    assert r["log_loss_1x2"] == pytest.approx(r["market_log_loss_1x2_same_fixtures"], abs=1e-3)
    assert sum(r["total_goals_distribution"]["predicted"]) == pytest.approx(1, abs=1e-3)
    assert not out["sufficient_for_calibration"]
