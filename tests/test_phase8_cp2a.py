"""Phase 8 CP2A: Weekly Challenge eligibility without the independent Goal Model,
bound ``eligible_competitions`` enforcement, missing-model safety and the OD-3
portfolio probability sources (Market / Diski 9 / Your View)."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest

from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import integration, pages
from diski9.app.challenge.service import ChallengeService, key_str
from diski9.backend.services import rounds as rounds_svc
from diski9.challenge import analysis as pa
from diski9.challenge.config import BROAD60_432_V1
from diski9.challenge.roundsheet import (
    SnapshotKind,
    build_live_snapshot,
    restrict_competitions,
)
from diski9.challenge.structured import evaluate_market_and_model, make_outcome, validate_portfolio
from diski9.screener import market_fit

from .test_app import data, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import NOW, _Data, jtext, valid_keys

CFG = BROAD60_432_V1
SHOT = os.environ.get("DISKI9_CP2A_SHOT", "/tmp/diski9_cp2a_builder.png")


# ------------------------------------------------------------------ helpers
def strip_models(snap, fixture_ids):
    """The snapshot with these fixtures' Diski 9 values removed (as Goal Model 1.1 now
    freezes them when the model is unavailable)."""
    ids = set(fixture_ids)
    return dataclasses.replace(
        snap,
        fixtures=tuple(
            dataclasses.replace(f, estimated_goals=None) if f.fixture_id in ids else f
            for f in snap.fixtures
        ),
        outcomes=tuple(
            dataclasses.replace(o, model_probability=None) if o.fixture_id in ids else o
            for o in snap.outcomes
        ),
    )


class _Svc(ChallengeService):
    """The demo round served from a given (model-stripped) snapshot."""

    def __init__(self, snap):
        super().__init__(_Data())
        self._fixed = snap

    def demo(self):
        return self._fixed


@pytest.fixture(scope="module")
def base():
    return ChallengeService(_Data()).demo()


def _keys_and_fixtures(snap):
    keys = valid_keys(snap)
    outs = [snap.outcome(tuple(_parse(k))) for k in keys]
    return keys, outs


def _parse(k):
    from diski9.app.challenge.service import parse_key

    return parse_key(k)


def _by_bucket(outs):
    return {c: [o for o in outs if CFG.classify(o.market_probability) == c] for c in "ABC"}


# ---------------------------------------------------------- OD-3: analysis layer
def oc(fid, p, odds, model):
    return make_outcome(fid, "1X2", "HOME", p, odds, model, 5, NOW - timedelta(days=2), 39)


def synthetic(model_missing=()):
    rows = [(1, 0.80, "1.20", 0.75), (2, 0.70, "1.36", 0.72), (3, 0.65, "1.47", 0.60),
            (4, 0.62, "1.55", 0.66), (5, 0.55, "1.75", 0.50), (6, 0.48, "2.00", 0.52),
            (7, 0.42, "2.30", 0.45), (8, 0.35, "2.75", 0.30), (9, 0.25, "3.80", 0.33)]  # fmt: skip
    sels = [oc(f, p, o, None if f in model_missing else m) for f, p, o, m in rows]
    return validate_portfolio(sels, NOW - timedelta(days=1), config=CFG)


def test_worked_example_partial_bucket_availability():
    """4/4 Foundation and 2/2 Challenger predictions, 2/3 Balanced: Foundation and
    Challenger Diski 9 estimates remain; Balanced and the whole nine are unavailable."""
    port = synthetic(model_missing={6})
    stats, nine = pa.bucket_stats(port.selections, pa.model_probability, CFG)
    by = {s.code: s for s in stats}
    assert by["A"].combined_probability == pytest.approx(0.75 * 0.72 * 0.60 * 0.66)
    assert by["C"].combined_probability == pytest.approx(0.30 * 0.33)
    assert by["A"].unavailable == by["C"].unavailable == 0
    assert by["B"].combined_probability is None and by["B"].unavailable == 1
    assert nine.combined_probability is None and nine.unavailable == 1
    # payouts still come from the frozen odds; never part-substituted probabilities
    assert by["B"].payout is not None and nine.payout is not None
    assert not pa.available(port, "model")
    evs = pa.evaluate_sources(port, {})
    assert evs["model"] is None and evs["market"] is not None and evs["personal"] is not None
    market, model = evaluate_market_and_model(port)
    assert model is None and market.p_recover > 0


@pytest.mark.parametrize("missing", [set(), {1}, {1, 5, 8}, set(range(1, 10))])
def test_zero_some_all_missing(missing):
    port = synthetic(model_missing=missing)
    evs = pa.evaluate_sources(port, {})
    assert (evs["model"] is None) == bool(missing)
    assert pa.missing_models(port.selections) == len(missing)
    # Market and Your View always exist; Your View never raises
    assert evs["market"].p_recover == pytest.approx(evs["market"].p_recover)
    assert 0 <= evs["personal"].p_recover <= 1
    if not missing:
        assert evs["model"].p_recover == pytest.approx(
            pa.evaluate_with(port, pa.model_probability).p_recover
        )


def test_model_probability_never_substituted():
    port = synthetic(model_missing={2})
    o = next(x for x in port.selections if x.fixture_id == 2)
    with pytest.raises(pa.ModelUnavailable):
        pa.model_probability(o)
    with pytest.raises(pa.ModelUnavailable):
        pa.evaluate_with(port, pa.model_probability)
    assert isinstance(pa.ModelUnavailable("x"), ValueError)


def test_your_view_interim_hierarchy_and_summary():
    port = synthetic(model_missing={2, 9})
    sels = {o.fixture_id: o for o in port.selections}
    personal = {sels[1].key: 0.9, sels[2].key: 0.5}  # adjusted with and without a model
    prob = pa.personal_probability(personal)
    assert prob(sels[1]) == 0.9 and pa.personal_source(sels[1], personal) == "adjusted"
    assert prob(sels[2]) == 0.5 and pa.personal_source(sels[2], personal) == "adjusted"
    assert prob(sels[3]) == sels[3].model_probability  # tier 2: Diski 9
    assert pa.personal_source(sels[3], personal) == "model"
    # without a market-implied probability (CP2B.1 tier 3) the consensus applies (tier 4)
    assert prob(sels[9]) == sels[9].market_probability
    assert pa.personal_source(sels[9], personal) == "market"
    counts = pa.personal_sources(port.selections, personal)
    assert counts == {"adjusted": 2, "model": 6, "implied": 0, "market": 1}
    assert pa.personal_summary(port.selections, personal) == (
        "Your View: 2 your adjustment · 6 Diski 9 · 1 market consensus"
    )
    assert pa.personal_summary([], personal) == ""


# --------------------------------------------------- pool construction (database)
def _cached_without_model(real):
    def cached(conn, basis):
        out = []
        for r in real(conn, basis):
            r = json.loads(json.dumps(r))
            r["goal_model"] = {"available": False, "reason": "team_matches_insufficient"}
            out.append(r)
        return out

    return cached


def test_pool_admits_model_absent_fixtures_with_null_model(data, monkeypatch):  # noqa: F811
    from diski9.screener import cache
    from tests.factories import T0

    ref = build_live_snapshot(data.engine, T0, T0, T0 + timedelta(days=30), "W", {}, config=CFG)
    assert ref.outcomes and all(o.model_probability is not None for o in ref.outcomes)
    monkeypatch.setattr(cache, "cached", _cached_without_model(cache.cached))
    s = build_live_snapshot(data.engine, T0, T0, T0 + timedelta(days=30), "W", {}, config=CFG)
    # the same market-eligible offers, now with NULL model values, never market-filled
    assert [o.key for o in s.outcomes] == [o.key for o in ref.outcomes]
    assert all(o.model_probability is None for o in s.outcomes)
    assert all(f.estimated_goals is None for f in s.fixtures)
    assert [o.market_probability for o in s.outcomes] == [
        o.market_probability for o in ref.outcomes
    ]
    assert s.diagnostics["fixtures_without_model"] >= len(s.fixtures) > 0
    assert s.diagnostics["fixtures_with_model"] == 0


def test_pool_construction_limited_to_eligible_competitions(data):  # noqa: F811
    from tests.factories import T0

    window = (T0, T0, T0 + timedelta(days=30), "W", {})
    full = build_live_snapshot(data.engine, *window, config=CFG)
    leagues = {f.league_id for f in full.fixtures}
    assert leagues
    one = sorted(leagues)[0]
    only = build_live_snapshot(data.engine, *window, config=CFG, competitions=[one])
    assert {f.league_id for f in only.fixtures} == {one}
    uefa = build_live_snapshot(data.engine, *window, config=CFG, competitions=[2, 3])
    assert not uefa.fixtures and not uefa.outcomes
    assert uefa.diagnostics["fixtures_in_window"] == 0


def test_restrict_competitions(base):
    keep = {f.league_id for f in base.fixtures}
    assert restrict_competitions(base, keep) is base  # unchanged object
    drop = sorted(keep)[0]
    r = restrict_competitions(base, keep - {drop})
    assert all(f.league_id != drop for f in r.fixtures)
    ids = {f.fixture_id for f in r.fixtures}
    assert all(o.fixture_id in ids for o in r.outcomes)
    assert r.diagnostics["excluded_competition_fixtures"] == sum(
        f.league_id == drop for f in base.fixtures
    )
    assert r.fingerprint != base.fingerprint
    assert not restrict_competitions(base, {2, 3}).fixtures


# ------------------------------------------------------------- publication guard
def _publication(snap, eligible):
    lo = min(f.kickoff for f in snap.fixtures) - timedelta(hours=1)
    hi = max(f.kickoff for f in snap.fixtures) + timedelta(hours=1)
    r = SimpleNamespace(status="draft", is_development=False, code=snap.round_id,
                        window_start_at=lo, window_end_at=hi)  # fmt: skip
    sched = SimpleNamespace(config_version=snap.config_version, eligible_competitions=eligible)
    live = dataclasses.replace(snap, kind=SnapshotKind.LIVE)
    return rounds_svc._publication_problem(
        r, sched, live, "football-db", snap.snapshot_at + timedelta(minutes=1), timedelta(hours=1)
    )


def test_publication_refuses_competitions_outside_the_schedule(base):
    leagues = sorted({f.league_id for f in base.fixtures})
    problem, details = _publication(base, leagues)
    assert problem is None
    problem, details = _publication(base, leagues[1:])
    assert "does not allow" in problem and details["competitions"] == [leagues[0]]
    # a European competition smuggled into a snapshot is refused
    f0 = base.fixtures[0]
    euro = dataclasses.replace(
        base,
        fixtures=(dataclasses.replace(f0, league_id=2), *base.fixtures[1:]),
    )
    problem, details = _publication(euro, leagues)
    assert problem is not None and 2 in details["competitions"]


# --------------------------------------------------------- builder, review, submit
@pytest.mark.parametrize("n_missing", [0, 1, 4, 9])
def test_builder_review_and_submission_with_missing_models(base, n_missing):
    keys, outs = _keys_and_fixtures(base)
    stripped = strip_models(base, [o.fixture_id for o in outs[:n_missing]])
    svc = _Svc(stripped)
    for source in ("market", "model", "personal"):
        prefs = {"source": source}
        tv = jtext(pages.tracker_view(svc, stripped, keys, False, prefs, {}))
        an = jtext(pages.analysis_panel(svc, stripped, keys, prefs, {}))
        if source == "model" and n_missing:
            assert f"unavailable for {n_missing} of 9" in tv
            assert f"{n_missing} of 9 do not have one" in an
        if source == "personal" and n_missing:
            # CP2B.1: tier 3 (frozen market-implied) where a reliable frozen fit exists,
            # tier 4 (consensus) otherwise; the summary states which
            chosen = svc.outcomes_for(stripped, keys)
            implied = market_fit.implied_probabilities(stripped, chosen)
            counts = pa.personal_sources(chosen, {}, implied)
            assert counts["model"] == 9 - n_missing
            assert counts["implied"] + counts["market"] == n_missing
            for k, n in counts.items():  # the summary names every non-zero tier
                assert (f"{n} {pa.PERSONAL_SOURCE_LABEL[k]}" in tv) == bool(n)
    avail = svc.availability("demo")
    rv = jtext(pages.review(svc, stripped, keys, avail, {}, _Data().local, {}))
    assert ("Diski 9 portfolio estimate unavailable" in rv) == bool(n_missing)
    # submission stores NULL Diski 9 aggregates when unavailable
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    for k in keys:
        s, _ = cb.apply_action(svc, s, "pick", k)
    s, flash = cb.apply_action(svc, s, "nav", "review")
    assert flash is None
    s, flash = cb.apply_action(svc, s, "submit")
    sub = s["submitted"]
    assert flash["kind"] == "ok"
    if n_missing:
        assert sub["p_recover_model"] is None and "model" not in sub["estimates"]
        assert sum(p["model"] is None for p in sub["picks"]) == n_missing
    else:
        assert sub["p_recover_model"] is not None and "model" in sub["estimates"]
    assert sub["p_recover_market"] is not None and "market" in sub["estimates"]
    mk, md = svc.evaluate(stripped, keys)
    assert (md is None) == bool(n_missing) and mk.p_recover == sub["p_recover_market"]


def test_frozen_view_without_model_shows_market_not_edge(base):
    keys, outs = _keys_and_fixtures(base)
    fid = outs[0].fixture_id
    stripped = strip_models(base, [fid])
    fx_outs = [o for o in stripped.outcomes if o.fixture_id == fid]
    market = {"MATCH_RESULT": "1X2", "BTTS": "BTTS", "OVER_UNDER_25": "OU25"}
    m = next(v for k, v in market.items() if str(fx_outs[0].market) in (k, v))
    assert integration.frozen_market_value(fx_outs, m) is None  # no fabricated edge / EV
    probs = integration.frozen_probabilities(fx_outs)
    assert probs["model"] == {} and probs["market"]
    challenge = {"values": {fid: None}, "odds": {fid: "1.50 · 3.00"}, "picked": {},
                 "snapshot": stripped}  # fmt: skip
    cell = integration.challenge_cell(challenge, m, fid, "edge", None)
    assert cell["main"] == "No model"
    challenge["odds"][fid] = "Not in this market"
    assert integration.challenge_cell(challenge, m, fid, "edge", None)["main"] == (
        "Not in this market"
    )


def test_historical_snapshot_fingerprints_unchanged(base):
    """Snapshots with full model values keep their fingerprint: the fingerprint input
    is unchanged by CP2A (repr of the stored probabilities)."""
    again = ChallengeService(_Data()).demo()
    assert again.fingerprint == base.fingerprint
    stripped = strip_models(base, [base.fixtures[0].fixture_id])
    assert stripped.fingerprint != base.fingerprint  # model values are part of the content
    k = key_str(base.outcomes[0].key)
    assert k  # keys are unchanged by stripping


# ------------------------------------------------------------------- browser
@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_builder_with_missing_models(data, monkeypatch):  # noqa: F811
    """Proportionate browser check: the existing builder journey on a round where four
    of the nine picks have no Diski 9 prediction (mobile viewport)."""
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    from diski9.app import create_app

    from .test_app import _free_port

    base = ChallengeService(_Data()).demo()
    keys = valid_keys(base, {f.fixture_id for f in base.fixtures[:10]})
    outs = [base.outcome(tuple(_parse(k))) for k in keys]
    stripped = strip_models(base, [o.fixture_id for o in outs[:4]])
    outs = [stripped.outcome(o.key) for o in outs]
    implied = market_fit.implied_probabilities(stripped, outs)
    monkeypatch.setattr(ChallengeService, "demo", lambda self: stripped)
    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    script = f"""
    const {{ chromium, devices }} = require('playwright');
    const KEYS = {json.dumps(keys)};
    const sel = (o) => `[id='${{JSON.stringify(o)}}']`;
    (async () => {{
      const b = await chromium.launch();
      const out = {{ errors: [] }};
      const p = await (await b.newContext({{ ...devices['iPhone 13'] }})).newPage();
      p.on('pageerror', e => out.errors.push(e.message));
      const idle = async () => {{ await p.waitForTimeout(400); await p.waitForLoadState('networkidle'); }};
      await p.goto('http://127.0.0.1:{port}/');  // CP3A-2: the challenge list (Research only OFF)
      await p.waitForSelector('#research-only'); if (await p.locator('#research-only input').isChecked()) {{ await p.locator('.pb-switch-label').click(); }} await p.waitForSelector('.ch-page', {{ state: 'visible' }});
      await p.locator(sel({{m: 'demo', t: 'mode'}})).tap();
      await p.waitForSelector('text=Demonstration round.'); await idle();
      for (const k of KEYS) {{ await p.locator(sel({{k, t: 'pick'}})).tap(); await idle(); }}
      out.total = await p.locator('.ch-total').innerText();
      await p.locator('.ch-source').getByText('Diski 9', {{ exact: true }}).tap(); await idle();
      await p.waitForSelector('.ch-src-note:has-text("unavailable for")', {{ timeout: 30000 }});
      out.modelNote = await p.locator('.ch-src-note').innerText();
      out.unavailBuckets = await p.locator('.ch-bstat.ch-unavail').count();
      await p.locator('.ch-source').getByText('Your View', {{ exact: true }}).tap(); await idle();
      await p.waitForSelector('.ch-src-note:has-text("Your View:")', {{ timeout: 30000 }});
      out.viewNote = await p.locator('.ch-src-note').innerText();
      await p.locator(sel({{i: 'tracker', t: 'nav', to: 'review'}})).tap(); await idle();
      // wait for the review stage itself (a fixed pause is too short on slow runners)
      await p.waitForSelector('text=Diski 9 portfolio estimate unavailable', {{ timeout: 30000 }});
      out.review = (await p.locator('.ch-unavail').allInnerTexts()).join(' ');
      out.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await p.screenshot({{ path: {json.dumps(str(SHOT))}, fullPage: false }});
      console.log(JSON.stringify(out));
      await b.close();
    }})().catch(e => {{ console.error(e); process.exit(1); }});
    """
    try:
        time.sleep(0.3)
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=240)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["errors"] == [] and out["total"] == "9/9" and out["overflow"] == 0
        assert "unavailable for 4 of 9" in out["modelNote"]
        assert out["unavailBuckets"] >= 2  # at least one bucket plus The Diski 9
        # CP2B.1: the four model-absent picks take the frozen market-implied tier where a
        # reliable frozen fit exists, otherwise the actual consensus
        assert out["viewNote"].strip() == pa.personal_summary(outs, {}, implied)
        assert "Diski 9 portfolio estimate unavailable: 4 of 9" in out["review"]
    finally:
        server.shutdown()


# ------------------------------------- CP2A closure: missing Screener payload diagnostic
def _cached_dropping(real, drop_id):
    def cached(conn, basis):
        return [r for r in real(conn, basis) if r["fixture"]["id"] != drop_id]

    return cached


def test_missing_screener_payload_is_excluded_and_recorded(data, monkeypatch):  # noqa: F811
    """A fixture with otherwise eligible market consensus but no Screener cache payload
    is excluded (unchanged rule) and now counted, separately from fixtures that have a
    payload but no independent model (which stay eligible)."""
    from diski9.admin_cli import pool_lines
    from diski9.screener import cache
    from tests.factories import T0

    window = (T0, T0, T0 + timedelta(days=30), "W", {})
    ref = build_live_snapshot(data.engine, *window, config=CFG)
    assert ref.diagnostics["fixtures_without_screener_payload"] == 0
    dropped = ref.fixtures[0].fixture_id  # has eligible market offers in the reference
    assert any(o.fixture_id == dropped for o in ref.outcomes)
    real = cache.cached
    monkeypatch.setattr(cache, "cached", _cached_dropping(real, dropped))
    s = build_live_snapshot(data.engine, *window, config=CFG)
    assert dropped not in {f.fixture_id for f in s.fixtures}
    assert not any(o.fixture_id == dropped for o in s.outcomes)
    assert s.diagnostics["fixtures_without_screener_payload"] == 1
    # every other fixture and offer is unchanged
    assert [o.key for o in s.outcomes] == [o.key for o in ref.outcomes if o.fixture_id != dropped]
    # payload present but model unavailable: still eligible, not counted as missing
    monkeypatch.setattr(cache, "cached", _cached_without_model(real))
    m = build_live_snapshot(data.engine, *window, config=CFG)
    assert [o.key for o in m.outcomes] == [o.key for o in ref.outcomes]
    assert all(o.model_probability is None for o in m.outcomes)
    assert m.diagnostics["fixtures_without_screener_payload"] == 0
    assert m.diagnostics["fixtures_without_model"] >= len(m.fixtures) > 0
    # the operator sees the exclusion in `round readiness`
    lines = pool_lines(s.diagnostics)
    assert "without" in lines[0]
    assert "WARNING: 1 fixture excluded: no Screener cache payload" in lines[1]
    assert len(pool_lines(m.diagnostics)) == 1  # no warning when nothing is missing
    # the restriction to eligible competitions keeps the counter
    assert restrict_competitions(s, set()).diagnostics["fixtures_without_screener_payload"] == 1


def test_scheduler_readiness_line_reports_missing_payload():
    from diski9.backend.jobs.prepare import decode, encode

    def rd(diag):
        return SimpleNamespace(
            ready=True, report={"eligible_outcomes_by_bucket": {}}, required_by_bucket={},
            fixtures=20, earliest_kickoff=None, deadline_at=None, problem=None,
            diagnostics=diag,
        )  # fmt: skip

    line = encode(rd({"fixtures_without_screener_payload": 2}), 1.0, "complete@x")
    assert "no_payload=2" in line
    assert decode(line, NOW).summary["no_payload"] == "2"
    assert "no_payload" not in encode(rd({"fixtures_without_screener_payload": 0}), 1.0)
    assert "no_payload" not in encode(rd({}), 1.0)
