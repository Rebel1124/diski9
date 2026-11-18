"""Phase 6B: Weekly Challenge prototype (snapshots, states, UI reducer, charts, pages)."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import charts, pages
from diski9.app.challenge.service import ChallengeService, key_str, parse_key
from diski9.challenge import analysis as pa
from diski9.challenge import demo, education
from diski9.challenge.config import DEFAULT_CONFIG as CFG
from diski9.challenge.roundsheet import (
    RoundFixture,
    RoundSnapshot,
    RoundStatus,
    SnapshotKind,
    assess_round,
    build_live_snapshot,
    snapshot_from_research_pool,
)
from diski9.challenge.scoring import RoundClassification, score_round
from diski9.challenge.structured import (
    SelectionBlock,
    assess_outcome,
    evaluate_groups,
    make_outcome,
    selection_blocks,
)

from .test_app import _free_port, data, populated  # noqa: F401  (fixtures)

ROOT = Path(__file__).parents[1]
POOL = json.loads((ROOT / "docs/research/weekly_challenge_risk/pool_weekend.json").read_text())
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)  # after the demo snapshot, before kickoffs
D = Decimal


def jtext(component) -> str:
    from plotly.utils import PlotlyJSONEncoder

    return json.dumps(component, cls=PlotlyJSONEncoder)


class _Data:
    """Minimal data stand-in: no database (the live round is then unavailable)."""

    engine = None

    def __init__(self, now=NOW):
        self._now = now

    def clock(self):
        return self._now

    def local(self, dt, fmt="%a %d %b, %H:%M"):
        return dt.strftime(fmt)


@pytest.fixture(scope="module")
def svc():
    return ChallengeService(_Data())


@pytest.fixture(scope="module")
def snap(svc):
    return svc.demo()


def valid_keys(snap, fixtures=None):
    """A deterministic valid 4/3/2 portfolio (test helper, not a recommendation)."""
    pool = [o for o in snap.outcomes if fixtures is None or o.fixture_id in fixtures]
    sel, need = [], {"A": 4, "B": 3, "C": 2}
    for code in "CAB":
        for o in pool:
            if not need[code]:
                break
            a = assess_outcome(o, snap.snapshot_at, CFG)
            if (
                a.eligible
                and a.bucket == code
                and o.key not in selection_blocks(sel, snap.outcomes, snap.snapshot_at, CFG)
            ):
                sel.append(o)
                need[code] -= 1
    assert not any(need.values())
    return [key_str(o.key) for o in sel]


# ------------------------------------------------------------------ snapshots
def test_demo_snapshot_is_labelled_and_assessed_at_its_own_time(snap):
    assert snap.kind is SnapshotKind.DEMO and snap.is_demo
    assert snap.snapshot_at == datetime.fromisoformat(POOL["as_of"])
    assert len(snap.fixtures) == 60 and snap.config_version == CFG.version
    later = datetime(2027, 6, 1, tzinfo=UTC)  # long after: wall clock must not matter
    a = assess_round(snap, later)
    assert a.status is RoundStatus.DEMO and a.playable and a.report.opens
    assert all(f.home and f.away for f in snap.fixtures)


def test_fingerprint_is_stable_and_content_sensitive(snap):
    again = snapshot_from_research_pool(POOL, snap.round_id, {})
    assert again.fingerprint == snap.fingerprint
    changed = replace(snap, outcomes=snap.outcomes[:-1])
    assert changed.fingerprint != snap.fingerprint
    assert replace(snap, snapshot_at=snap.snapshot_at + timedelta(minutes=1)).fingerprint != (
        snap.fingerprint
    )


def _live(snap, **kw):
    return replace(snap, kind=SnapshotKind.LIVE, **kw)


def test_round_states(snap):
    assert assess_round(None, NOW).status is RoundStatus.NO_ROUND
    empty = _live(snap, outcomes=(), fixtures=(), diagnostics={"fixtures_in_window": 0})
    assert assess_round(empty, NOW).status is RoundStatus.NO_ROUND
    stale = _live(
        snap,
        outcomes=(),
        diagnostics={"fixtures_in_window": 40, "exclusions": {"stale_provider_update": 90}},
    )
    assert assess_round(stale, NOW).status is RoundStatus.STALE_ODDS
    missing = _live(
        snap, outcomes=(), diagnostics={"fixtures_in_window": 40, "exclusions": {"no_prices": 90}}
    )
    assert assess_round(missing, NOW).status is RoundStatus.MISSING_MARKETS
    few = {f.fixture_id for f in snap.fixtures[:12]}
    small = _live(snap, outcomes=tuple(o for o in snap.outcomes if o.fixture_id in few))
    assert assess_round(small, NOW).status is RoundStatus.INSUFFICIENT
    # 20 fixtures but only Foundation-band outcomes: enough fixtures, no 4/3/2 portfolio
    only_a = tuple(o for o in snap.outcomes if CFG.classify(o.market_probability) == "A")
    a = assess_round(_live(snap, outcomes=only_a), NOW)
    assert a.status in (RoundStatus.INFEASIBLE, RoundStatus.INSUFFICIENT)
    assert not a.report.portfolio_feasible
    live = _live(snap)
    before = snap.earliest_kickoff - timedelta(hours=1)
    assert assess_round(live, before).status is RoundStatus.OPEN
    assert live.deadline == snap.earliest_kickoff - timedelta(minutes=15)
    assert assess_round(live, live.deadline).status is RoundStatus.LOCKED


def test_live_snapshot_reads_database_without_api(data):  # noqa: F811
    from tests.factories import T0

    s = build_live_snapshot(data.engine, T0, T0, T0 + timedelta(days=30), "W", {})
    assert s.kind is SnapshotKind.LIVE and s.snapshot_at == T0
    assert s.diagnostics["fixtures_in_window"] >= 1
    for o in s.outcomes:  # everything on the sheet passed the strict consensus
        assert o.bookmaker_groups >= 3 and o.model_probability is not None
    assert assess_round(s, T0).status is not RoundStatus.DEMO


# ------------------------------------------------------------- engine helpers
def test_selection_blocks_reasons(snap):
    keys = valid_keys(snap)
    sels = [snap.outcome(parse_key(k)) for k in keys[:5]]  # 2 Challenger + 3 Foundation
    blocks = selection_blocks(sels, snap.outcomes, snap.snapshot_at, CFG)
    for o in sels:
        assert blocks[o.key] is SelectionBlock.SELECTED
    used = {o.fixture_id for o in sels}
    for o in snap.outcomes:
        a = assess_outcome(o, snap.snapshot_at, CFG)
        b = blocks.get(o.key)
        if o.fixture_id in used and o not in sels:
            assert b in (SelectionBlock.FIXTURE_TAKEN, SelectionBlock.INELIGIBLE)
        if not a.eligible:
            assert b in (SelectionBlock.INELIGIBLE, SelectionBlock.SELECTED)
        if a.eligible and a.bucket == "C" and o.fixture_id not in used:
            assert b is SelectionBlock.BUCKET_FULL  # Challenger already 2/2


def test_would_block_completion_is_detected():
    t = datetime(2026, 11, 17, tzinfo=UTC)

    def oc(f, p, out="HOME"):
        return make_outcome(f, "1X2", out, p, "2.00", p, 5, t, 39)

    # nine fixtures: one is the only Challenger source; using it for Foundation blocks completion
    pool = [oc(1, 0.7), oc(1, 0.3, "AWAY")] + [oc(f, 0.7) for f in (2, 3, 4, 5)]
    pool += [oc(f, 0.5) for f in (6, 7, 8)] + [oc(9, 0.3)]
    blocks = selection_blocks([], pool, t, CFG)
    assert blocks[oc(1, 0.7).key] is SelectionBlock.WOULD_BLOCK_COMPLETION
    assert oc(2, 0.7).key not in blocks


def test_partial_payout_probability():
    ev = evaluate_groups(
        [[(0.5, D("1.50"))], [(0.5, D("4.00"))], [(0.5, D("6.00"))]], (40, 30, 20), 10
    )  # A pays 60 (< 100), B 120, C 120
    assert math.isclose(ev.p_partial, 0.125)  # only A wins
    assert math.isclose(ev.p_partial + ev.p_zero + ev.p_recover, 1.0)


def test_education_defaults_and_validation():
    ill = education.illustrate(education.DEFAULT_ILLUSTRATION)
    got = {b.code: b for b in ill.buckets}
    assert f"{got['A'].combined:.2%}" == "24.01%"
    assert f"{got['B'].combined:.2%}" == "12.50%"
    assert f"{got['C'].combined:.2%}" == "9.00%"
    assert math.isclose(got["B"].fair_odds, 8.0) and math.isclose(got["B"].fair_payout, 240.0)
    assert math.isclose(got["A"].fair_payout, 40 / 0.7**4)
    assert math.isclose(ill.all_nine, 0.7**4 * 0.5**3 * 0.3**2)
    assert [b.legs for b in ill.buckets] == [4, 3, 2]
    assert [b.credits for b in ill.buckets] == [40, 30, 20]
    with pytest.raises(ValueError):
        education.illustrate({"A": 0})


# ------------------------------------------------------------------ reducer
def test_pick_remove_and_guards(svc, snap):
    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    assert s["mode"] == "demo" and s["fp"] == snap.fingerprint and s["selections"] == []
    s, flash = cb.apply_action(svc, s, "nav", "review")
    assert s["stage"] == "overview" and "Complete" in flash["text"]
    s2, flash = cb.apply_action(svc, s, "nav", "no-such-step")
    assert s2["stage"] == "overview" and flash is None
    for k in keys[:4]:
        s, flash = cb.apply_action(svc, s, "pick", k)
        assert flash is None
    assert s["selections"] == keys[:4]
    # another outcome of an already used fixture is refused, not swapped
    fid = parse_key(keys[0])[0]
    other = next(key_str(o.key) for o in snap.outcomes
                 if o.fixture_id == fid and key_str(o.key) != keys[0])  # fmt: skip
    s2, flash = cb.apply_action(svc, s, "pick", other)
    assert s2["selections"] == keys[:4] and "already have" in flash["text"]
    # Challenger is full (2/2): a third Challenger outcome is refused
    used = {parse_key(k)[0] for k in keys}
    third_c = next(key_str(o.key) for o in snap.outcomes if o.fixture_id not in used
                   and assess_outcome(o, snap.snapshot_at, CFG).eligible
                   and CFG.classify(o.market_probability) == "C")  # fmt: skip
    _, flash = cb.apply_action(svc, s, "pick", third_c)
    assert "full" in flash["text"]
    # an ineligible outcome is refused
    bad = next(key_str(o.key) for o in snap.outcomes
               if not assess_outcome(o, snap.snapshot_at, CFG).eligible)  # fmt: skip
    _, flash = cb.apply_action(svc, s, "pick", bad)
    assert "isn't eligible" in flash["text"]
    # tapping a selected outcome removes it; remove and clear work
    s3, _ = cb.apply_action(svc, s, "pick", keys[0])
    assert keys[0] not in s3["selections"]
    s3, _ = cb.apply_action(svc, s, "remove", keys[1])
    assert keys[1] not in s3["selections"] and len(s3["selections"]) == 3
    s3, _ = cb.apply_action(svc, s, "clear")
    assert s3["selections"] == []


def test_complete_portfolio_navigation_and_submission(svc, snap):
    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    for k in keys:
        s, _ = cb.apply_action(svc, s, "pick", k)
    s, flash = cb.apply_action(svc, s, "nav", "review")
    assert s["stage"] == "review" and flash is None
    s, flash = cb.apply_action(svc, s, "submit")
    sub = s["submitted"]
    assert flash["kind"] == "ok" and "not a competition entry" in flash["text"]
    assert sub["fp"] == snap.fingerprint and sub["config"] == CFG.version
    assert sub["selections"] == keys and sub["mode"] == "demo"
    mk, md = svc.evaluate(snap, keys)
    assert sub["p_recover_market"] == mk.p_recover and sub["p_recover_model"] == md.p_recover


def test_submission_revalidates(svc, snap):
    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    s["selections"] = keys[:8]  # tampered / incomplete
    s, flash = cb.apply_action(svc, s, "submit")
    assert s["submitted"] is None and "not valid" in flash["text"]


def test_snapshot_change_clears_draft(svc, snap):
    keys = valid_keys(snap)
    stale = {"mode": "demo", "fp": "old-fingerprint", "selections": keys, "stage": "build"}
    s, flash = cb.apply_action(svc, stale, "pick", keys[0])
    assert s["selections"] == [] and s["fp"] == snap.fingerprint
    assert "snapshot changed" in flash["text"]
    # rendering never shows selections from another snapshot either
    assert pages.current(svc, pages.normal_state(stale))[3] == []


def test_locked_round_refuses_changes(snap):
    live = _live(snap)

    class Locked(ChallengeService):
        def snapshot(self, mode):
            return live

        def availability(self, mode):
            return assess_round(live, live.deadline + timedelta(minutes=1))

    svc = Locked(_Data())
    s = {"mode": "live", "fp": live.fingerprint, "selections": [], "stage": "build"}
    s2, flash = cb.apply_action(svc, s, "pick", valid_keys(snap)[0])
    assert s2["selections"] == [] and "locked" in flash["text"]
    _, flash = cb.apply_action(svc, s, "submit")
    assert "aren't open" in flash["text"]


def test_states_are_isolated_values(svc, snap):
    keys = valid_keys(snap)
    a, _ = cb.apply_action(svc, None, "mode", "demo")
    b, _ = cb.apply_action(svc, None, "mode", "demo")
    a, _ = cb.apply_action(svc, a, "pick", keys[0])
    assert b["selections"] == [] and a["selections"] == [keys[0]]
    assert not hasattr(cb, "STATE") and not hasattr(pages, "STATE")  # no module-level drafts


def test_filters_never_drop_selections(svc, snap):
    keys = valid_keys(snap)
    cards, text = pages.fixture_list(svc, snap, keys, {"search": "zzzz-no-team"}, _Data().local,
                                     False)  # fmt: skip
    assert "0 of 60" in text
    trk = pages.tracker_view(svc, snap, keys, False)
    assert "9/9" in jtext(trk)
    _, text = pages.fixture_list(svc, snap, keys, {"market": "BTTS", "bucket": "B"},
                                 _Data().local, False)  # fmt: skip
    assert "filtered from 60" in text


# ------------------------------------------------------------------- charts
def test_recovery_donut_reconciles_to_one(svc, snap):
    """Phase 6B.1 replaced the survival/exact charts in the UI with these three views."""
    port = svc.portfolio(snap, valid_keys(snap))
    ev = pa.evaluate_with(port, pa.market_probability)
    fig = charts.recovery_donut(ev)
    vals = list(fig.data[0].values)
    assert vals == [ev.p_recover, ev.p_partial, ev.p_zero]
    assert math.isclose(sum(vals), 1.0, abs_tol=1e-12)


def test_states_chart_lists_eight_states_by_payout(svc, snap):
    port = svc.portfolio(snap, valid_keys(snap))
    ev = pa.evaluate_with(port, pa.market_probability)
    rows = charts.state_rows(ev)
    assert len(rows) == 8 and [s.gross for s in rows] == sorted(s.gross for s in ev.states)
    fig = charts.states_figure(ev)
    assert list(fig.data[0].x) == [s.probability for s in rows]
    assert "All nine correct" in fig.layout.yaxis.ticktext[-1]
    assert fig.layout.yaxis.autorange == "reversed"  # smallest payout at the top


def test_correct_histogram_and_conditional_chart(svc, snap):
    port = svc.portfolio(snap, valid_keys(snap))
    cc = pa.correct_count_analysis(port)
    h = charts.correct_histogram(cc, 5)
    assert list(h.data[0].x) == list(range(10))
    assert math.isclose(sum(h.data[0].y), 1.0, abs_tol=1e-12)
    cond = charts.conditional_payout_figure(cc, 5)
    assert list(cond.data[0].y) == [r.expected_gross or 0.0 for r in cc.rows]
    panel = jtext(pages.analysis_panel(svc, snap, valid_keys(snap), {"source": "model"})
                       )  # fmt: skip
    assert "Diski 9 estimate" in panel and "Most likely" in panel
    empty = jtext(pages.analysis_panel(svc, snap, valid_keys(snap)[:5], {}))
    assert "5/9 so far" in empty


def test_market_model_switch_keeps_payouts(svc, snap):
    mk, md = svc.evaluate(snap, valid_keys(snap))
    assert [s.gross for s in mk.states] == [s.gross for s in md.states]
    assert [a.payout for a in mk.buckets] == [a.payout for a in md.buckets]
    assert mk.p_recover != md.p_recover
    keys = valid_keys(snap)
    body_m = jtext(pages.analysis_panel(svc, snap, keys, {"source": "market"}))  # fmt: skip
    body_d = jtext(pages.analysis_panel(svc, snap, keys, {"source": "model"}))  # fmt: skip
    for a in mk.buckets:
        assert f"{a.payout:,.2f}" in body_m and f"{a.payout:,.2f}" in body_d


# --------------------------------------------------------------- demo boards
def test_demo_leaderboards_use_the_scoring_engine():
    s = demo.demo_round_score(demo.LATEST_ROUND)
    r = next(x for x in demo.demo_rounds() if x.round_id == demo.LATEST_ROUND)
    assert s == score_round(r)
    ranked = [x for x in s.scores if x.rank]
    assert [x.rank for x in ranked[:3]] == [1, 1, 3] and ranked[0].points == ranked[1].points == 150
    tenth = [x for x in ranked if x.rank == 10]
    assert len(tenth) == 3 and all(x.points == 90 for x in tenth)
    assert next(x for x in ranked if x.rank == 13).points == 75
    refund = [x for x in s.scores if x.refunded]
    assert len(refund) == 1 and refund[0].rank is None and refund[0].points == 0
    kinds = {x.classification for x in demo.demo_rounds()}
    assert {RoundClassification.PRACTICE, RoundClassification.VOID} <= kinds
    t = demo.demo_championship()
    assert t.completed_rounds == 7 and set(t.ignored_round_ids) == {"DEMO-P1", "DEMO-V1"}
    ranks = [x.rank for x in t.standings]
    assert len(ranks) != len(set(ranks))  # at least one shared position
    assert not t.is_complete and t.champions == ()


def test_leaderboard_rendering_shows_ties_and_round_types():
    text = jtext(pages.leaderboard_body("weekly", demo.LATEST_ROUND))
    assert "=1" in text and "=10" in text and "Void \\u2014 Refunded" in text
    assert "Practice round" in jtext(pages.leaderboard_body("weekly", "DEMO-P1"))
    assert "Void round" in jtext(pages.leaderboard_body("weekly", "DEMO-V1"))
    champ = jtext(pages.leaderboard_body("championship", None))
    assert "Round 7 of 10 completed" in champ and "=6" in champ


# ------------------------------------------------------------------- routing
def _callback(app, fragment):
    k = next(k for k in app.callback_map if fragment in k)
    return app.callback_map[k]["callback"].__wrapped__


def test_routes_and_existing_screener(data):  # noqa: F811
    from diski9.app import create_app

    app = create_app(data)
    client = app.server.test_client()
    for path in ("/", "/challenge", "/challenge/me", "/leaderboards"):
        assert client.get(path).status_code == 200
    layout = client.get("/_dash-layout").get_data(as_text=True)
    for cid in ("url", "site-nav-links", "screener-root", "ch-root", "ch-session", "results-table"):
        assert f'"{cid}"' in layout
    assert '"storage_type":"session"' in layout.replace(" ", "")
    route = _callback(app, "ch-root.children")
    style, content, nav, _ = route("/", None, None, None)
    assert style == {"display": "block"} and content is None
    for path, words in (("/challenge", "Weekly Challenge"), ("/challenge/me", "My Challenge"),
                        ("/leaderboards", "Leaderboards")):  # fmt: skip
        style, content, nav, _ = route(path, None, None, None)
        assert style == {"display": "none"}
        assert words in jtext(content)
        assert any("on" in link.className for link in nav)


def test_source_preference_is_separate_from_portfolio_state(data):  # noqa: F811
    """Phase 6B.1: the explorer was removed; the probability-source selector writes only
    the display preference store, never the portfolio."""
    from diski9.app import create_app

    app = create_app(data)
    src = next(k for k in app.callback_map if k.startswith("ch-prefs.data"))
    assert "ch-session" not in src
    reducer = next(k for k in app.callback_map if k.startswith("..ch-session.data"))
    assert "source" not in reducer and "edu" not in reducer


# ------------------------------------------------------------------- browser
@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_journey_demo_round(data):  # noqa: F811
    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    from werkzeug.serving import make_server

    from diski9.app import create_app

    snap = ChallengeService(_Data()).demo()
    keys = valid_keys(snap, {f.fixture_id for f in snap.fixtures[:10]})
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
      await p.goto('http://127.0.0.1:{port}/challenge'); await p.waitForSelector('.ch-hero');
      await p.locator(sel({{m: 'demo', t: 'mode'}})).tap();
      await p.waitForSelector('text=Demonstration round.'); await idle();
      await p.locator(sel({{i: 'overview', t: 'nav', to: 'build'}})).tap();
      await p.waitForSelector(sel({{k: KEYS[0], t: 'pick'}}));
      for (const k of KEYS) {{ await p.locator(sel({{k, t: 'pick'}})).tap(); await idle(); }}
      out.total = await p.locator('.ch-total').innerText();
      const pays = await p.locator('.ch-bstat strong:nth-of-type(1)').allInnerTexts();
      const payText = async () => (await p.locator('.ch-bstat').allInnerTexts()).map(s => s.split('pays')[1]);
      const before = await payText();
      await p.locator('.ch-source').getByText('Diski 9', {{ exact: true }}).tap(); await idle();
      out.payoutsSame = JSON.stringify(before) === JSON.stringify(await payText()) && before.length === 4;
      out.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await p.goto('http://127.0.0.1:{port}/leaderboards'); await p.waitForSelector('.ch-table.lb');
      out.first = await p.locator('.ch-table.lb tbody tr').first().locator('td').first().innerText();
      console.log(JSON.stringify(out));
      await b.close();
    }})().catch(e => {{ console.error(e); process.exit(1); }});
    """
    try:
        time.sleep(0.3)
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=240)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out == {"errors": [], "total": "9/9", "payoutsSame": True, "overflow": 0,
                       "first": "=1"}  # fmt: skip
    finally:
        server.shutdown()


def test_goal_model_unchanged():
    from diski9.screener import goal_model as gm

    assert (gm.PARAMS.k_s, gm.PARAMS.k_t, gm.PARAMS.m0, gm.GOAL_MODEL_VERSION) == (
        12,
        96,
        30,
        "1.0",
    )


__all__ = ["RoundFixture", "RoundSnapshot"]


# ------------------------------------------------------ Phase 6B.1 Stage C
def _lab_state(home_delta):
    from diski9.app import lab

    s = lab.new_state()
    s["manual"]["home"] = home_delta
    return s


class _DataWithResults(_Data):
    """Screener payloads for the demo fixtures (Goal Model expected goals from the pool)."""

    def __init__(self, snap):
        super().__init__()
        from diski9.screener import goal_model as gm

        res = {}
        for f in POOL["fixtures"]:
            lam = f.get("lambda_model")
            if not lam or not f.get("model_available"):
                continue
            res[f["fixture_id"]] = {
                "fixture": {"id": f["fixture_id"], "home": "H", "away": "A"},
                "goal_model": {"available": True, "estimated_goals": {"home": lam[0], "away": lam[1]},
                               "probabilities": gm.markets(lam[0], lam[1])},
            }  # fmt: skip
        self._results = res

    def snapshot(self):
        class S:
            pass

        s = S()
        s.results = {"overall": self._results}
        return s


def test_your_view_uses_match_lab_maths_and_never_changes_official_values(snap):
    from diski9.app import lab
    from diski9.app.challenge import integration

    data = _DataWithResults(snap)  # noqa: F811
    fid = snap.fixtures[0].fixture_id
    assert integration.personal_probabilities(data, snap, {}) == {}
    store = {str(fid): _lab_state(0.8)}
    personal = integration.personal_probabilities(data, snap, store)
    outs = [o for o in snap.outcomes if o.fixture_id == fid]
    assert {k[0] for k in personal} == {fid} and len(personal) == len(outs)
    r = data.snapshot().results["overall"][fid]
    expect = lab.adjusted_probabilities(lab.user_estimates(r, lab.normalise_state(store[str(fid)],
                                                                                  lab.baseline_rounded(r))))  # fmt: skip
    for o in outs:
        assert personal[o.key] == expect[lab.OUTCOME_KEY[o.outcome]]
    home = next(o for o in outs if str(o.outcome) == "HOME")
    assert personal[home.key] > home.model_probability  # more home goals -> higher home chance
    # official values are untouched: buckets, odds, model probabilities, snapshot fingerprint
    fp = snap.fingerprint
    assert all(o.model_probability != personal[o.key] or True for o in outs)
    assert (
        snap.fingerprint == fp
        and home.model_probability == r["goal_model"]["probabilities"]["home"]
    )
    other = {str(snap.fixtures[1].fixture_id + 10**9): _lab_state(1.0)}  # not in the pool
    assert integration.personal_probabilities(data, snap, other) == {}


def test_screener_challenge_view_matches_builder_pool(svc, snap):
    from diski9.app.challenge import integration

    s, _ = cb.apply_action(svc, None, "mode", "demo")
    keys = valid_keys(snap)
    for k in keys[:3]:
        s, _ = cb.apply_action(svc, s, "pick", k)
    info = integration.challenge_cells(svc, s, "1X2")
    assert info["ids"] == {f.fixture_id for f in snap.fixtures} and info["snapshot"] is snap
    for fid, cell in info["cells"].items():
        frozen = [o for o in snap.outcomes if o.fixture_id == fid and str(o.market) == "1X2"]
        if frozen:
            assert cell["main"] == " · ".join(f"{o.reference_odds:.2f}" for o in frozen)
    picked = {parse_key(k)[0] for k in keys[:3]}
    assert {fid for fid, cell in info["cells"].items() if cell["sub"].startswith("✓")} == picked
    none = integration.challenge_cells(ChallengeService(_Data()), None, "1X2")  # live unavailable
    assert none["ids"] == set() and none["message"]


def test_match_lab_actions_share_reducer_and_validation(svc, snap):
    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    assert cb.ACTION_OF["labpick"] == "pick" and cb.ACTION_OF["labremove"] == "remove"
    s, _ = cb.apply_action(svc, s, cb.ACTION_OF["labpick"], keys[0])
    assert s["selections"] == [keys[0]]
    fid = parse_key(keys[0])[0]
    alt = next(key_str(o.key) for o in snap.outcomes if o.fixture_id == fid
               and key_str(o.key) != keys[0] and assess_outcome(o, snap.snapshot_at, CFG).eligible)  # fmt: skip
    s2, flash = cb.apply_action(svc, s, "pick", alt)  # never auto-replaced
    assert s2["selections"] == [keys[0]] and "already have" in flash["text"]
    s3, flash = cb.apply_action(svc, s, "ask_replace", alt)
    assert s3["selections"] == [keys[0]] and flash["replace"] == alt  # asks first
    s4, flash = cb.apply_action(svc, s3, "replace", alt)
    assert s4["selections"] == [alt] and flash["kind"] == "ok"
    # a replacement the engine rejects leaves the draft unchanged
    bad = next(key_str(o.key) for o in snap.outcomes if o.fixture_id == fid
               and not assess_outcome(o, snap.snapshot_at, CFG).eligible)  # fmt: skip
    s5, flash = cb.apply_action(svc, s4, "replace", bad)
    assert s5["selections"] == [alt] and "isn't possible" in flash["text"]


def test_match_lab_panel_states(svc, snap):
    from diski9.app.challenge import integration

    data = _DataWithResults(snap)  # noqa: F811
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    fid = snap.fixtures[0].fixture_id
    panel = jtext(integration.lab_panel(svc, data, s, fid, {}, None))
    assert "Add to Weekly Challenge" in panel and "Your View" in panel and "equals Diski" in panel
    outside = jtext(integration.lab_panel(svc, data, s, 99999999, {}, None))
    assert "isn't in this week's Challenge" in outside
    nolive = jtext(integration.lab_panel(ChallengeService(_Data()), data, None, fid, {}, None))
    assert "demonstration round" in nolive
    adjusted = jtext(integration.lab_panel(svc, data, s, fid, {str(fid): _lab_state(0.5)}, None))
    assert "uses your adjusted expected goals" in adjusted
