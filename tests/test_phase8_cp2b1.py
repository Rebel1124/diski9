"""Phase 8 CP2B.1: the production market-implied model (State B), its reliability rules,
on-demand reuse, live/frozen separation, source-aware Your View identity and the
complete OD-3 Your View hierarchy (adjusted -> Diski 9 -> market-implied -> consensus)."""

from __future__ import annotations

import csv
import dataclasses
import json
import re
import shutil
import subprocess
import threading
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from diski9.api_football.markets import Market, Outcome
from diski9.app import lab, lab_context
from diski9.app.challenge import integration, pages
from diski9.app.challenge.service import ChallengeService
from diski9.backend.services import your_view as yv
from diski9.challenge import analysis as pa
from diski9.challenge.structured import evaluate_market_and_model, make_outcome
from diski9.odds.collect import OddsPage, reconcile_pages
from diski9.odds.display import DisplayedMarket
from diski9.odds.value import MARKET_ORDER
from diski9.research import market_implied_xg as proto
from diski9.screener import goal_model as gm
from diski9.screener import market_fit as mf

from .factories import T0, odds_item
from .test_app import EPL_FIX, EXTRA, data, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import _Data, valid_keys
from .test_phase8_cp2a import _keys_and_fixtures, _Svc, strip_models

ROOT = Path(__file__).resolve().parents[1]
CP1_FITS = ROOT / "docs/research/phase8_cp1/market_fits.csv"
STATE_B, STATE_C = EXTRA[0], EXTRA[1]  # no Goal Model (teams without history)
# Tolerances (see the Phase 8 record §14): the production fit calls the accepted
# prototype's optimiser unchanged, so the rates are expected to be bit-identical
# (observed difference 0); 1e-9 goals only absorbs floating-point differences between
# CPUs and is far below the 0.005 display rounding. Production probabilities come from
# goal_model.markets, whose grid omits less than 1e-12 of mass, against the
# prototype's own grid (observed difference <= 7.4e-13).
LAMBDA_TOL = 1e-9
PROB_TOL = 1e-9


@pytest.fixture(autouse=True)
def _fresh_cache():
    mf.clear()
    yield
    mf.clear()


def model_inputs(lh: float, la: float) -> proto.MarketInputs:
    p = gm.markets(lh, la)
    return proto.MarketInputs(
        (p["home"], p["draw"], p["away"]),
        (p["btts_yes"], p["btts_no"]),
        (p["over"], p["under"]),
    )


# ------------------------------------------------------------ numerical correctness
def _cp1_rows():
    return [r for r in csv.DictReader(CP1_FITS.open()) if r["rule_ok"] == "True"]


def _tup(r, m, n):
    v = [r.get(f"market_{m}_{i}") for i in range(n)]
    return tuple(float(x) for x in v) if all(v) else None


def test_reconciles_with_the_accepted_cp1_fits():
    """All 131 qualifying CP1 snapshots: same rates, same quality, the one
    non-converged fit rejected as CP1 recommended (report §7)."""
    rows = _cp1_rows()
    assert len(rows) == 131
    statuses = {}
    worst_l = worst_p = 0.0
    keys = (("1x2", ("home", "draw", "away")), ("btts", ("btts_yes", "btts_no")),
            ("ou25", ("over", "under")))  # fmt: skip
    for i, r in enumerate(rows):
        inp = proto.MarketInputs(_tup(r, "1x2", 3), _tup(r, "btts", 2), _tup(r, "ou25", 2))
        f = mf.fit_inputs(mf.FROZEN, f"cp1-{i}", inp)
        statuses[(r["status"], r["converged"], f.status, f.reason)] = (
            statuses.get((r["status"], r["converged"], f.status, f.reason), 0) + 1
        )
        if f.reliable:
            worst_l = max(worst_l, abs(f.lambda_home - float(r["lambda_home"])),
                          abs(f.lambda_away - float(r["lambda_away"])))  # fmt: skip
            assert f.max_abs_residual == pytest.approx(float(r["max_abs_residual"]), abs=1e-12)
            for m, ks in keys:
                for j, k in enumerate(ks):
                    v = r.get(f"fitted_{m}_{j}")
                    if v:
                        worst_p = max(worst_p, abs(f.probabilities[k] - float(v)))
    assert statuses == {
        ("good_fit", "True", "good", None): 101,
        ("approximate_fit", "True", "approximate", None): 29,
        ("approximate_fit", "False", "rejected", "not_converged"): 1,
    }
    assert worst_l <= LAMBDA_TOL
    assert worst_p <= PROB_TOL


def test_identical_to_the_prototype_on_synthetic_inputs():
    for lh, la in ((1.0, 1.0), (1.6, 1.1), (2.4, 0.7), (0.7, 2.2), (3.1, 1.8)):
        inp = model_inputs(lh, la)
        res = proto.fit(inp)
        f = mf.fit_inputs(mf.LIVE, f"syn-{lh}-{la}", inp)
        assert f.status == "good"
        assert abs(f.lambda_home - res.lambda_home) <= LAMBDA_TOL
        assert abs(f.lambda_away - res.lambda_away) <= LAMBDA_TOL
        assert f.lambda_home == pytest.approx(lh, abs=1e-4)
        assert f.lambda_away == pytest.approx(la, abs=1e-4)
        # fitted probabilities: the production Poisson function, finite and valid
        assert f.probabilities == gm.markets(f.lambda_home, f.lambda_away)
        assert all(0 < p < 1 for p in f.probabilities.values())
        p = f.probabilities
        assert p["home"] + p["draw"] + p["away"] == pytest.approx(1, abs=1e-12)
        assert p["btts_yes"] + p["btts_no"] == pytest.approx(1, abs=1e-12)
        assert p["over"] + p["under"] == pytest.approx(1, abs=1e-12)
        for k, v in res.model.items():  # prototype's grid vs production's
            ours = {"1x2": (p["home"], p["draw"], p["away"]), "btts": (p["btts_yes"],
                    p["btts_no"]), "ou25": (p["over"], p["under"])}[k]  # fmt: skip
            assert max(abs(x - y) for x, y in zip(ours, v, strict=True)) <= PROB_TOL


def test_methodology_constants_are_the_accepted_ones():
    assert proto.LAMBDA_BOUNDS == (0.05, 6.0)
    assert proto.GOOD_FIT_MAX_RESIDUAL == 0.02 and proto.APPROX_FIT_MAX_RESIDUAL == 0.04
    assert proto.MARKETS == ("1x2", "btts", "ou25") and len(proto.INITIAL_POINTS) == 7
    assert mf.MIN_GROUPS == 3 and timedelta(hours=24) == mf.MAX_INPUT_AGE
    assert mf.FIT_VERSION == "1.0" and mf.SOURCE_LABEL == "Market-implied Model"


def test_goal_model_unchanged():
    assert gm.GOAL_MODEL_VERSION == "1.1"
    assert gm.PARAMS.k_s == 12 and gm.PARAMS.k_t == 96
    assert gm.PARAMS.team_min == 2 and gm.PARAMS.competition_min == 20


# ------------------------------------------------------------- reliability rules
def test_quality_bands_at_their_boundaries():
    assert mf.quality(0.0) == mf.quality(0.02) == "good"
    assert mf.quality(0.02 + 1e-9) == "approximate"
    assert mf.quality(0.04) == "approximate"
    assert mf.quality(0.04 + 1e-9) == "poor"


def _fake(**kw):
    base = dict(status="good_fit", markets_used=("1x2", "ou25"), lambda_home=1.5,
                lambda_away=1.1, max_abs_residual=0.01, converged=True, at_boundary=False,
                identified=True)  # fmt: skip
    base.update(kw)
    return proto.FitResult(**base)


@pytest.mark.parametrize(
    ("fake", "status", "reason"),
    [
        (dict(max_abs_residual=0.02), "good", None),
        (dict(status="approximate_fit", max_abs_residual=0.020001), "approximate", None),
        (dict(status="approximate_fit", max_abs_residual=0.04), "approximate", None),
        (dict(status="poor_fit", max_abs_residual=0.0401), "rejected", "poor_fit"),
        (dict(converged=False), "rejected", "not_converged"),  # even with a small residual
        (dict(status="insufficient_market_data", identified=False), "rejected", "not_identified"),
        (dict(status="poor_fit", at_boundary=True), "rejected", "at_boundary"),
        (dict(status="optimization_failure"), "rejected", "optimisation_failure"),
        (dict(status="invalid_input", lambda_home=None, lambda_away=None), "rejected",
         "invalid_input"),
        (dict(lambda_home=None, lambda_away=None, identified=None), "rejected",
         "optimisation_failure"),
    ],
)  # fmt: skip
def test_gating_of_every_prototype_outcome(monkeypatch, fake, status, reason):
    monkeypatch.setattr(proto, "fit", lambda inputs: _fake(**fake))
    f = mf.fit_inputs(mf.LIVE, 1, model_inputs(1.5, 1.1))
    assert (f.status, f.reason) == (status, reason)
    assert f.reliable == (status != "rejected")
    if not f.reliable:
        assert f.estimated_goals is None and f.stamp() is None and f.message


def test_failed_fit_never_raises(monkeypatch):
    def boom(inputs):
        raise RuntimeError("optimiser exploded")

    monkeypatch.setattr(proto, "fit", boom)
    f = mf.fit_inputs(mf.LIVE, 7, model_inputs(1.5, 1.1))
    assert f.status == "rejected" and f.reason == "error"


def test_invalid_and_inconsistent_inputs_are_rejected():
    bad = proto.MarketInputs((0.5, 0.3, 0.3), None, (0.5, 0.5))  # 1X2 sums to 1.1
    assert mf.fit_inputs(mf.LIVE, 1, bad).reason == "invalid_input"
    # strong favourite priced with almost no goals: not jointly consistent
    odd = proto.MarketInputs((0.80, 0.15, 0.05), (0.05, 0.95), (0.05, 0.95))
    f = mf.fit_inputs(mf.LIVE, 2, odd)
    assert f.status == "rejected" and f.reason in ("poor_fit", "at_boundary")


# -------------------------------------------------------------- live input rule
def _dm(market, probs, status="fresh", groups=5):
    cons = SimpleNamespace(sources=groups, challenge_eligible=groups >= 3)
    imp = SimpleNamespace(
        margin_adjusted={
            o: Decimal(repr(p)) for o, p in zip(MARKET_ORDER[market], probs, strict=True)
        }  # fmt: skip
    )
    return DisplayedMarket(market, status, cons, imp, T0, 1.0)


def _ov(lh=1.6, la=1.1, **over):
    p = gm.markets(lh, la)
    ms = {
        Market.MATCH_RESULT: _dm(Market.MATCH_RESULT, (p["home"], p["draw"], p["away"])),
        Market.BTTS: _dm(Market.BTTS, (p["btts_yes"], p["btts_no"])),
        Market.OVER_UNDER_25: _dm(Market.OVER_UNDER_25, (p["over"], p["under"])),
    }
    for m, v in over.items():
        ms[Market[m]] = v if v is not None else DisplayedMarket(Market[m], "unavailable", None,
                                                               None, None, None)  # fmt: skip
    return SimpleNamespace(markets=ms, league_has_odds=True)


def _unavail(m):
    return DisplayedMarket(m, "unavailable", None, None, None, None)


def test_live_input_rule():
    assert mf.live_fit(1, _ov()).status == "good"
    assert mf.live_fit(1, None).reason == "no_odds"
    assert mf.live_fit(1, SimpleNamespace(markets=None, league_has_odds=False)).reason == "no_odds"
    p = gm.markets(1.6, 1.1)
    one_x_two = (p["home"], p["draw"], p["away"])
    # 1X2 plus a single goals market is enough
    ok = _ov(BTTS=None)
    assert mf.live_fit(1, ok).reliable and mf.live_fit(1, ok).markets_used == ("1x2", "ou25")
    # 1X2 stale / too few groups / missing
    stale = _ov(MATCH_RESULT=_dm(Market.MATCH_RESULT, one_x_two, status="stale"))
    assert mf.live_fit(1, stale).reason == "stale"
    thin = _ov(MATCH_RESULT=_dm(Market.MATCH_RESULT, one_x_two, groups=2))
    assert mf.live_fit(1, thin).reason == "insufficient_groups"
    assert mf.live_fit(1, _ov(MATCH_RESULT=None)).reason == "missing_1x2"
    # no usable goals market
    assert mf.live_fit(1, _ov(BTTS=None, OVER_UNDER_25=None)).reason == "missing_goals_market"
    stale_goals = _ov(
        BTTS=_dm(Market.BTTS, (p["btts_yes"], p["btts_no"]), status="stale"),
        OVER_UNDER_25=None,
    )
    assert mf.live_fit(1, stale_goals).reason == "stale"
    thin_goals = _ov(
        BTTS=None, OVER_UNDER_25=_dm(Market.OVER_UNDER_25, (p["over"], p["under"]), groups=2)
    )
    assert mf.live_fit(1, thin_goals).reason == "insufficient_groups"
    # two distinct input sets were fitted (all three markets; 1X2 + O/U); every rule
    # rejection was decided before the optimiser
    assert mf.stats()["fits"] == 2


# ------------------------------------------------------------ frozen input rule
def _frozen(fid=11, lh=1.7, la=1.0, groups=5, seen=None, drop=(), snapshot_at=None):
    at = snapshot_at or T0
    seen = seen if seen is not None else at - timedelta(hours=2)
    p = gm.markets(lh, la)
    outs = []
    for market, keys in (("1X2", (("HOME", "home"), ("DRAW", "draw"), ("AWAY", "away"))),
                         ("BTTS", (("BTTS_YES", "btts_yes"), ("BTTS_NO", "btts_no"))),
                         ("OU25", (("OVER_2_5", "over"), ("UNDER_2_5", "under")))):  # fmt: skip
        for outcome, key in keys:
            if (market, outcome) in drop or market in drop:
                continue
            q = p[key]
            odds = Decimal(f"{1 / (q * 1.05):.2f}")
            outs.append(make_outcome(fid, market, outcome, q, odds, None, groups, seen, 39))
    fixture = SimpleNamespace(fixture_id=fid, estimated_goals=None)
    return SimpleNamespace(snapshot_at=at, outcomes=tuple(outs),
                           fixture=lambda f: fixture if f == fid else (_ for _ in ()).throw(
                               KeyError(f)))  # fmt: skip


def test_frozen_input_rule_judged_at_snapshot_time():
    assert mf.frozen_fit(_frozen(), 11).status == "good"
    assert mf.frozen_fit(_frozen(groups=2), 11).reason == "insufficient_groups"
    old = _frozen(seen=T0 - timedelta(hours=25))
    assert mf.frozen_fit(old, 11).reason == "stale"
    future = _frozen(seen=T0 + timedelta(minutes=1))  # observed after the snapshot
    assert mf.frozen_fit(future, 11).reason == "stale"
    assert mf.frozen_fit(_frozen(drop=("1X2",)), 11).reason == "missing_1x2"
    assert mf.frozen_fit(_frozen(drop=("BTTS", "OU25")), 11).reason == "missing_goals_market"
    # an incomplete market is not a distribution: ignored, the other goals market used
    part = _frozen(drop=(("BTTS", "BTTS_NO"),))
    assert mf.frozen_fit(part, 11).markets_used == ("1x2", "ou25")
    assert mf.frozen_fit(_frozen(drop=(("1X2", "DRAW"),)), 11).reason == "missing_1x2"


def test_historical_frozen_inputs_are_not_rejected_for_their_present_age():
    """Nothing in the frozen rule depends on the current time: a snapshot taken long
    ago still fits exactly as it did then."""
    long_ago = T0 - timedelta(days=900)
    snap = _frozen(snapshot_at=long_ago)
    a = mf.frozen_fit(snap, 11)
    mf.clear()
    b = mf.frozen_fit(snap, 11)
    assert a.status == "good" and a == b


def test_frozen_fit_uses_frozen_inputs_only_and_never_changes_the_snapshot(base):
    keys, outs = _keys_and_fixtures(base)
    fid = outs[0].fixture_id
    stripped = strip_models(base, [fid])
    before = stripped.fingerprint
    f1 = mf.frozen_fit(stripped, fid)
    assert f1.reliable and f1.context == "frozen"
    # different live odds for the same fixture: the frozen fit is untouched
    live = mf.live_fit(fid, _ov(2.6, 0.6))
    assert live.reliable and live.input_id != f1.input_id
    assert mf.frozen_fit(stripped, fid) == f1
    assert stripped.fingerprint == before
    assert all(o.model_probability is None for o in stripped.outcomes if o.fixture_id == fid)
    assert stripped.fixture(fid).estimated_goals is None
    # the consensus kept for display is exactly the frozen probabilities
    frozen = {o.outcome: o.market_probability for o in stripped.outcomes if o.fixture_id == fid}
    assert f1.consensus["home"] == frozen[Outcome.HOME]


# --------------------------------------------------------- reuse and identity
def test_identical_inputs_reuse_and_changes_invalidate(monkeypatch):
    inp = model_inputs(1.5, 1.2)
    a = mf.fit_inputs(mf.LIVE, 5, inp)
    b = mf.fit_inputs(mf.LIVE, 5, inp)
    assert a is b and mf.stats()["fits"] == 1 and mf.stats()["hits"] == 1
    # a changed input probability is a different identity (full precision, not rounded)
    nudged = proto.MarketInputs((inp.p1x2[0] + 1e-9, inp.p1x2[1] - 1e-9, inp.p1x2[2]),
                                inp.btts, inp.ou25)  # fmt: skip
    assert mf.input_id(mf.LIVE, 5, nudged) != a.input_id
    # live and frozen never share a result, nor do different fixtures
    assert mf.input_id(mf.FROZEN, 5, inp) != a.input_id
    assert mf.input_id(mf.LIVE, 6, inp) != a.input_id
    # a methodology change is a different identity
    monkeypatch.setattr(mf, "MIN_GROUPS", 4)
    assert mf.input_id(mf.LIVE, 5, inp) != a.input_id
    monkeypatch.undo()
    monkeypatch.setattr(proto, "GOOD_FIT_MAX_RESIDUAL", 0.025)
    assert mf.input_id(mf.LIVE, 5, inp) != a.input_id


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(mf, "CACHE_SIZE", 3)
    for i in range(6):
        mf.fit_inputs(mf.LIVE, i, model_inputs(1.2 + i / 10, 1.0))
    assert mf.stats()["entries"] == 3 and mf.stats()["fits"] == 6


def test_no_fitting_from_listing_fixtures_or_building_pools(data, base):  # noqa: F811
    _add_state_b_odds(data.engine)
    mf.clear()
    from .test_app import payload

    payload(data)  # the Screener list (All Upcoming Fixtures), every page row
    snap = data.snapshot()
    assert snap.results["overall"]
    stripped = strip_models(base, [f.fixture_id for f in base.fixtures])  # no model anywhere
    svc = _Svc(stripped)
    pages.tracker_view(svc, stripped, [], False, {"source": "market"}, {})
    pages.tracker_view(svc, stripped, [], False, {"source": "personal"}, {})
    assert mf.stats()["fits"] == 0


def test_weekly_challenge_eligibility_does_not_depend_on_a_fit(monkeypatch):
    plain = ChallengeService(_Data()).demo()

    def refuse(*a, **k):
        raise AssertionError("pool construction must not fit")

    monkeypatch.setattr(mf, "fit_inputs", refuse)
    again = ChallengeService(_Data()).demo()
    assert again.fingerprint == plain.fingerprint


# ----------------------------------------------------- Match Lab (live data)
def _book(lh, la, margin=1.05):
    p = gm.markets(lh, la)

    def o(q):
        return f"{1 / (q * margin):.2f}"

    return {
        "1": [("Home", o(p["home"])), ("Draw", o(p["draw"])), ("Away", o(p["away"]))],
        "8": [("Yes", o(p["btts_yes"])), ("No", o(p["btts_no"]))],
        "5": [("Over 2.5", o(p["over"])), ("Under 2.5", o(p["under"]))],
    }


def _add_state_b_odds(engine, lh=1.55, la=1.15):
    kickoff = T0 + 5 * timedelta(days=1)
    books = {b: _book(lh, la, m) for b, m in ((8, 1.05), (11, 1.06), (4, 1.04))}
    page = OddsPage(T0 - timedelta(hours=1), [odds_item(STATE_B, books, kickoff=kickoff)])
    with engine.begin() as conn:
        reconcile_pages(conn, 39, 2026, [page], clock=lambda: T0 - timedelta(hours=1))


def _text(c) -> str:
    if c is None:
        return ""
    if isinstance(c, str | int | float):
        return str(c)
    if isinstance(c, list | tuple):
        return " ".join(_text(x) for x in c)
    return _text(getattr(c, "children", None))


def _ids(c, out=None):
    out = [] if out is None else out
    if isinstance(c, list | tuple):
        for x in c:
            _ids(x, out)
    elif c is not None and not isinstance(c, str | int | float):
        if getattr(c, "id", None) is not None:
            out.append(c.id)
        _ids(getattr(c, "children", None), out)
    return out


def _detail(data, fid, adj=None, notice=None):  # noqa: F811
    lc = lab_context.resolve(None, data, fid, "all")
    r, ov, official = data.detail(fid)
    return lc, lab.render_detail(lc.r, ov, official, "1X2", data, adj, notice)


def test_state_a_takes_precedence_without_fitting(data):  # noqa: F811
    lc, page = _detail(data, EPL_FIX)
    sp = lab.starting_point(lc.r)
    assert sp["source"] == "model" and sp["label"] == "Diski 9 Goal Model"
    text = _text(page)
    assert "Starting point:" in text and "Diski 9 Goal Model" in text
    assert "Market-implied Model" not in text
    assert "_starting_point" not in lc.r
    assert mf.stats()["fits"] == 0  # State A never fits
    assert lab.model_context(lc.r).startswith(f"{gm.GOAL_MODEL_VERSION}|{EPL_FIX}|")


def test_state_b_live_starting_point_and_no_edge(data):  # noqa: F811
    _add_state_b_odds(data.engine)
    r, ov, _ = data.detail(STATE_B)
    assert not r["goal_model"]["available"]
    lc, page = _detail(data, STATE_B)
    sp = lab.starting_point(lc.r)
    assert sp["source"] == "market" and sp["quality"] in ("good", "approximate")
    assert sp["context"] == "live"
    assert sp["estimated_goals"]["home"] == pytest.approx(1.55, abs=0.15)
    assert "goal_model" in lc.r and not lc.r["goal_model"]["available"]  # never a model field
    text = _text(page)
    for s in ("Market-implied Model", "Market-implied probabilities (fitted)",
              "Bookmaker consensus (actual)", "Market-implied Model (fitted)", lab.NO_EDGE_NOTE,
              "Reset to starting point", lab.FIT_CAVEAT):  # fmt: skip
        assert s in text, s
    assert "Your value check" not in text
    assert _text(lab.source_line(lc.r)).split() == ["Starting", "point:", "Market-implied",
                                                    "Model"]  # fmt: skip
    assert "lab-reset" in _ids(page)  # Your View adjustments available from this start
    # the starting point's own probabilities are the production Poisson function
    eg = sp["estimated_goals"]
    assert sp["probabilities"] == gm.markets(eg["home"], eg["away"])
    out, compare = lab.lab_outputs(lc.r, "1X2", ov, lab.new_state())
    assert lab.NO_EDGE_NOTE in _text(out) and "fitted" in _text(compare)
    # repeated navigation: one fit, then reuse; the same stamp
    stamp = lab.model_context(lc.r)
    for _ in range(3):
        assert lab.model_context(_detail(data, STATE_B)[0].r) == stamp
    assert mf.stats()["fits"] == 1 and mf.stats()["hits"] >= 3
    assert re.match(rf"^mi1\.0:[0-9a-f]{{12}}\|{STATE_B}\|\d\.\d\d\|\d\.\d\d$", stamp)
    yv._check_context(STATE_B, stamp)  # the server accepts the stamp format


def test_state_c_without_inputs(data):  # noqa: F811
    lc, page = _detail(data, STATE_C)
    assert lab.starting_point(lc.r) is None
    text = _text(page)
    assert "Market-implied estimate unavailable: No bookmaker prices" in text
    assert "Adjustments need a model baseline." in text
    assert "lab-reset" not in _ids(page) and "Starting point:" not in text
    assert lab.stored_adjustment({str(STATE_C): {"manual": {"home": 1}}}, STATE_C, lc.r)


def test_failed_fit_shows_state_c(data, monkeypatch):  # noqa: F811
    _add_state_b_odds(data.engine)
    monkeypatch.setattr(proto, "fit", lambda i: (_ for _ in ()).throw(RuntimeError("x")))
    lc, page = _detail(data, STATE_B)
    assert lab.starting_point(lc.r) is None
    assert "could not be calculated" in _text(page)


# ----------------------------------------------------- source-aware adjustments
def _payloads(data):  # noqa: F811
    _add_state_b_odds(data.engine)
    rb = lab_context.resolve(None, data, STATE_B, "all").r
    ra = dict(rb)
    ra.pop("_starting_point")
    ra["goal_model"] = {"available": True, "estimated_goals": {"home": 1.4, "away": 1.2},
                        "probabilities": gm.markets(1.4, 1.2)}  # fmt: skip
    return ra, rb


STATE = {"manual": {"home": 0.3, "away": -0.1}}


def test_adjustments_never_transfer_between_starting_points(data, monkeypatch):  # noqa: F811
    ra, rb = _payloads(data)
    # model -> market-implied
    store = lab.store_adjustment({}, STATE_B, ra, lab.normalise_state(STATE))
    assert lab.stored_adjustment(store, STATE_B, ra) is not None
    assert lab.adjustment_notice(store, STATE_B, ra) is None  # unchanged: kept, no notice
    assert lab.stored_adjustment(store, STATE_B, rb) is None
    assert "no prediction for this match now" in lab.adjustment_notice(store, STATE_B, rb)
    # market-implied -> model
    store = lab.store_adjustment({}, STATE_B, rb, lab.normalise_state(STATE))
    assert lab.stored_adjustment(store, STATE_B, rb) is not None
    assert lab.stored_adjustment(store, STATE_B, ra) is None
    assert "now has an independent prediction" in lab.adjustment_notice(store, STATE_B, ra)
    # changed market-implied inputs (even with the same rounded estimated goals)
    rb2 = dict(rb)
    rb2["_starting_point"] = dict(rb["_starting_point"])
    rb2["_starting_point"]["stamp"] = (
        "mi1.0:0123456789ab|" + rb["_starting_point"]["stamp"].split("|", 1)[1]
    )
    assert lab.stored_adjustment(store, STATE_B, rb2) is None
    assert "bookmaker prices" in lab.adjustment_notice(store, STATE_B, rb2)
    # no starting point any more
    rc = dict(rb)
    rc.pop("_starting_point")
    assert "no quantitative starting point" in lab.adjustment_notice(store, STATE_B, rc)
    # changed Goal Model version or parameters
    store = lab.store_adjustment({}, STATE_B, ra, lab.normalise_state(STATE))
    monkeypatch.setattr(gm, "GOAL_MODEL_VERSION", "1.2")
    assert lab.stored_adjustment(store, STATE_B, ra) is None
    assert "version has changed" in lab.adjustment_notice(store, STATE_B, ra)
    monkeypatch.undo()
    ra2 = dict(ra)
    ra2["goal_model"] = dict(ra["goal_model"], estimated_goals={"home": 1.5, "away": 1.2})
    assert "estimated goals for this match have changed" in lab.adjustment_notice(
        store, STATE_B, ra2
    )
    # an empty stored state needs no explanation
    empty = lab.store_adjustment({}, STATE_B, ra, lab.new_state())
    assert lab.adjustment_notice(empty, STATE_B, rb) is None
    # adjusting again replaces the earlier numbers and clears the explanation
    store = lab.store_adjustment({}, STATE_B, ra, lab.normalise_state(STATE))
    store[lab.WAS_KEY] = {str(STATE_B): "1.0|1|1.00|1.00"}
    store = lab.store_adjustment(store, STATE_B, rb, lab.normalise_state(STATE))
    assert lab.WAS_KEY not in store and lab.adjustment_notice(store, STATE_B, rb) is None


def test_notice_is_rendered_visibly(data):  # noqa: F811
    _, page = _detail(data, EPL_FIX, notice="Your earlier adjustments ... changed.")
    assert "Your earlier adjustments ... changed." in _text(page.children[0])  # header


def test_live_and_frozen_contexts_never_mix(base):
    keys, outs = _keys_and_fixtures(base)
    fid = outs[0].fixture_id
    stripped = strip_models(base, [fid])
    frozen = mf.frozen_fit(stripped, fid)
    # the same probabilities seen live give a different identity and stamp
    probs = {o.outcome: o.market_probability for o in stripped.outcomes if o.fixture_id == fid}
    ov = SimpleNamespace(
        league_has_odds=True,
        markets={
            Market.MATCH_RESULT: _dm(Market.MATCH_RESULT, [probs[o] for o in MARKET_ORDER[
                Market.MATCH_RESULT]]),
            Market.BTTS: _dm(Market.BTTS, [probs[o] for o in MARKET_ORDER[Market.BTTS]]),
            Market.OVER_UNDER_25: _dm(Market.OVER_UNDER_25, [probs[o] for o in MARKET_ORDER[
                Market.OVER_UNDER_25]]),
        },
    )  # fmt: skip
    live = mf.live_fit(fid, ov)
    assert live.lambda_home == frozen.lambda_home  # same maths ...
    assert live.stamp() != frozen.stamp()  # ... never the same Your View identity
    assert lab_context.frozen_key(stripped.round_id, fid) != str(fid)  # separate store keys
    # the backend's frozen stamp is the frozen fit's
    assert yv.frozen_context(stripped, fid, "goal-model-1.1") == frozen.stamp()


def test_frozen_market_payload_and_personal_probabilities(base):
    keys, outs = _keys_and_fixtures(base)
    fid = outs[0].fixture_id
    stripped = strip_models(base, [fid])
    live_r = {"fixture": {"id": fid}, "goal_model": {"available": True,
              "estimated_goals": {"home": 2.0, "away": 0.5}, "probabilities":
              gm.markets(2.0, 0.5)}}  # fmt: skip
    fr = lab_context.frozen_market_payload(live_r, stripped, fid)
    assert not fr["goal_model"]["available"]  # the live model is never shown frozen
    sp = lab.starting_point(fr)
    assert sp["source"] == "market" and sp["context"] == "frozen"
    key = lab_context.frozen_key(stripped.round_id, fid)
    store = lab.store_adjustment({}, key, fr, lab.normalise_state(STATE))
    personal = integration.personal_probabilities(None, stripped, store)
    f = mf.frozen_fit(stripped, fid)
    base_r = {"home": round(f.lambda_home, 2), "away": round(f.lambda_away, 2)}
    b = lab.breakdown(base_r, lab.normalise_state(STATE))
    expect = gm.markets(b["home"]["final"], b["away"]["final"])
    fx_outs = [o for o in stripped.outcomes if o.fixture_id == fid]
    assert {k for k in personal} == {o.key for o in fx_outs}
    for o in fx_outs:
        assert personal[o.key] == pytest.approx(expect[lab.OUTCOME_KEY[Outcome(str(o.outcome))]])
    # a live-context stamp for the same fixture is never applied to the frozen context
    store[lab.CONTEXT_KEY][key] = f"mi1.0:{'0' * 12}|{fid}|{base_r['home']:.2f}|" \
                                   f"{base_r['away']:.2f}"  # fmt: skip
    assert integration.personal_probabilities(None, stripped, store) == {}


# ------------------------------------------------------------ OD-3 portfolios
def test_complete_your_view_hierarchy_and_sources(base):
    keys, outs = _keys_and_fixtures(base)
    model_absent = [o.fixture_id for o in outs[:4]]
    stripped = strip_models(base, model_absent)
    svc = _Svc(stripped)
    port = svc.portfolio(stripped, keys)
    sels = port.selections
    implied = pages.implied_for(stripped, sels)
    absent = [o for o in sels if o.model_probability is None]
    assert len(absent) == 4
    # fitted only for these selections' fixtures, never the pool
    assert mf.stats()["fits"] == len({o.fixture_id for o in absent})
    assert set(implied) <= {o.key for o in absent}
    modelled = next(o for o in reversed(sels) if o.model_probability is not None)
    adjusted = {absent[0].key: 0.42, modelled.key: 0.33}  # one model-absent, one modelled
    prob = pa.personal_probability(adjusted, implied)
    for o in sels:
        if o.key in adjusted:
            assert prob(o) == adjusted[o.key]
            assert pa.personal_source(o, adjusted, implied) == "adjusted"
        elif o.model_probability is not None:
            assert prob(o) == o.model_probability
            assert pa.personal_source(o, adjusted, implied) == "model"
        elif o.key in implied:
            assert prob(o) == implied[o.key] != o.market_probability
            assert pa.personal_source(o, adjusted, implied) == "implied"
        else:
            assert prob(o) == o.market_probability
            assert pa.personal_source(o, adjusted, implied) == "market"
    counts = pa.personal_sources(sels, adjusted, implied)
    assert sum(counts.values()) == 9 and counts["adjusted"] == 2
    assert counts["implied"] == len([o for o in absent[1:] if o.key in implied])
    summary = pa.personal_summary(sels, adjusted, implied)
    assert summary.startswith("Your View: 2 your adjustment")
    if counts["implied"]:
        assert f"{counts['implied']} market-implied" in summary
    # Market stays the actual consensus; Diski 9 stays independent-only (unavailable)
    evs = pa.evaluate_sources(port, adjusted, implied)
    market, model = evaluate_market_and_model(port)
    assert model is None and evs["model"] is None
    assert evs["market"].p_recover == market.p_recover
    assert evs["personal"].p_recover == pa.evaluate_with(port, prob).p_recover
    no_tier3 = pa.evaluate_sources(port, adjusted)["personal"]
    if counts["implied"]:
        assert no_tier3.p_recover != evs["personal"].p_recover  # tier 3 is really used
    # frozen market-value view: still no edge or EV for market-only fixtures
    fid = absent[0].fixture_id
    assert (
        integration.frozen_market_value(
            [o for o in stripped.outcomes if o.fixture_id == fid], "1X2"
        )
        is None
    )


def test_review_and_tracker_state_the_market_implied_tier(base):
    keys, outs = _keys_and_fixtures(base)
    stripped = strip_models(base, [o.fixture_id for o in outs[:4]])
    svc = _Svc(stripped)
    sels = svc.portfolio(stripped, keys).selections
    implied = pages.implied_for(stripped, sels)
    n = len({k[0] for k in implied})
    avail = svc.availability("demo")
    rv = _text(pages.review(svc, stripped, keys, avail, {}, _Data().local, {}))
    tv = _text(pages.tracker_view(svc, stripped, keys, False, {"source": "personal"}, {}))
    if n:
        assert f"{n} market-implied" in tv and f"{n} market-implied" in rv
        assert "the market-implied estimate where Diski 9 has no prediction" in rv


# -------------------------------------------------------------------- browser
@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_match_lab_states_and_adjustments(data):  # noqa: F811
    """Proportionate browser check (mobile): States A, B and C in the Match Lab, the
    source label, an adjustment from the market-implied starting point that survives
    navigation, and no edge/EV for State B."""
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    from diski9.app import create_app

    from .test_app import _free_port

    _add_state_b_odds(data.engine)
    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    script = f"""
    const {{ chromium }} = require('playwright');
    (async () => {{
      const b = await chromium.launch();
      const out = {{ errors: [] }};
      const p = await (await b.newContext({{ viewport: {{ width: 1280, height: 900 }} }})).newPage();
      p.on('pageerror', e => out.errors.push(e.message));
      const pick = async (fid, expect) => {{
        await p.locator(`[id='${{JSON.stringify({{index: fid, type: 'row'}})}}']`).click();
        await p.waitForFunction((t) => document.querySelector('.detail h2') &&
          document.querySelector('.detail h2').innerText.includes(t), expect, {{ timeout: 30000 }});
      }};
      await p.goto('http://127.0.0.1:{port}/'); await p.waitForSelector('tr.row');
      // State B
      await pick({STATE_B}, 'Team 400 v');
      await p.waitForSelector('.lab-source.market', {{ timeout: 30000 }});
      out.bSource = await p.locator('.lab-source-line').first().innerText();
      out.bCompare = await p.locator('#lab-compare').innerText();
      out.bNoEdge = await p.locator('.no-edge').count();
      out.bValue = await p.getByText('Your value check').count();
      await p.locator('#lab-home-input').fill('2.50'); await p.locator('#lab-home-input').press('Enter');
      await p.waitForFunction(() => document.querySelector('#lab-output') &&
        document.querySelector('#lab-output').innerText.includes('Your estimate'), null, {{ timeout: 30000 }});
      out.bOutput = await p.locator('#lab-output').innerText();
      // State A, then back to B: the adjustment is kept (same starting point)
      await pick({EPL_FIX}, 'Team 1 v');
      await p.waitForSelector('.lab-source.model', {{ timeout: 30000 }});
      out.aSource = await p.locator('.lab-source-line').first().innerText();
      await pick({STATE_B}, 'Team 400 v');
      await p.waitForFunction(() => document.querySelector('#lab-home-input') &&
        document.querySelector('#lab-home-input').value === '2.50', null, {{ timeout: 30000 }});
      out.bAgain = await p.locator('#lab-home-input').inputValue();
      // State C
      await pick({STATE_C}, 'Team 401 v');
      await p.waitForSelector('.mi-why', {{ timeout: 30000 }});
      out.cWhy = await p.locator('.mi-why').innerText();
      out.cSource = await p.locator('.lab-source-line').count();
      out.cReset = await p.locator('#lab-reset').count();
      out.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      console.log(JSON.stringify(out));
      await b.close();
    }})().catch(e => {{ console.error(e); process.exit(1); }});
    """
    try:
        time.sleep(0.3)
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=300)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["errors"] == [] and out["overflow"] == 0
        assert "Market-implied Model" in out["bSource"]
        assert "Bookmaker consensus (actual)" in out["bCompare"]
        assert "Market-implied Model (fitted)" in out["bCompare"]
        assert out["bNoEdge"] >= 1 and out["bValue"] == 0
        assert "Your estimate" in out["bOutput"] and "market-implied" in out["bOutput"]
        assert "Diski 9 Goal Model" in out["aSource"]
        assert out["bAgain"] == "2.50"
        assert "No bookmaker prices" in out["cWhy"]
        assert out["cSource"] == 0 and out["cReset"] == 0
    finally:
        server.shutdown()


def test_snapshot_dataclasses_are_frozen():
    snap = ChallengeService(_Data()).demo()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.fixtures[0].estimated_goals = (1.0, 1.0)
    assert valid_keys(snap)


@pytest.fixture(scope="module")
def base():
    return ChallengeService(_Data()).demo()
