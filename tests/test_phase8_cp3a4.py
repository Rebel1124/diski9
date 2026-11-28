"""Phase 8 CP3A-4: the Match Lab's frozen/latest analytical context.

A match opened from a valid published Weekly Challenge snapshot shows "Use latest
available data" (OFF: the frozen analysis). ON shows the same match with the latest
data - its own context, store key and Your View - for research only: no competitive
controls, and stale selection actions are refused. Research matches never show the
toggle. Each context states its own source and times. The research list's frozen
line reads one published round."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest
from dash import no_update

from diski9.app import app as appmod
from diski9.app import lab, lab_context
from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import integration

from .test_app import EPL_FIX, PSL_FIX, data, populated  # noqa: F401  (fixtures)
from .test_challenge_ui import jtext
from .test_phase8_cp3a1 import _app, _named
from .test_phase8_cp3a3 import _changing, _live, _slider, _two_rounds, challenge

ON = [appmod.LATEST_VALUE]
SHOWN = None  # the toggle wrapper's style when shown


def _detail(app):
    return _named(app, "update_detail")


def _service(app):
    return app.server.config["DISKI9_CHALLENGE"]


def _store(frozen, live, home_frozen=0.3, home_live=-0.2):
    """A browser store with a different Your View in each context of one match."""
    store = lab.store_adjustment({}, frozen.key, frozen.r,
                                 lab.normalise_state({"manual": {"home": home_frozen}}))  # fmt: skip
    return lab.store_adjustment(store, live.key, live.r,
                                lab.normalise_state({"manual": {"home": home_live}}))  # fmt: skip


def _delta(update, target, market, store):
    """The home Your View adjustment shown (shown value minus the context's baseline)."""
    body = update(None, market, "/lab", [], target, store)[0]
    plain = update(None, market, "/lab", [], target, {})[0]
    return round(_slider(body, "lab-home-slider") - _slider(plain, "lab-home-slider"), 2)


# ------------------------------------------------------------------ the toggle's target
def test_new_opening_starts_frozen_and_the_toggle_sets_the_mode():
    t = {"fixture": 1, "ctx": "challenge", "round": "R", "fp": "F"}
    on = {**t, "latest": True}
    assert appmod.lab_want(t, on, ON, "lab-request") == t  # a new opening: frozen
    assert appmod.lab_want(t, t, ON, "lab-latest") == on
    assert appmod.lab_want(t, on, [], "lab-latest") == t
    # a market change, the address or the tab keep the remembered mode of the same match
    for trig in ("lab-market", "url", None):
        assert appmod.lab_want(t, on, ON, trig) == on
        assert appmod.lab_want(None, on, ON, trig) == on
    # another match in the address wins (and starts frozen)
    other = {**t, "fixture": 2}
    assert appmod.lab_want(other, on, ON, "lab-market") == other
    # research targets never take the latest flag (they are latest data already)
    r = {"fixture": 1, "ctx": "research"}
    assert appmod.lab_want(r, r, ON, "lab-latest") == r


# ------------------------------------------ CP3A-4 closure: overlapping toggle and market
# A market change sent while the toggle's response is still in flight carries the
# pre-toggle lab-target but the switched checkbox (reproduced in the browser with the
# toggle's response delayed). The mode must follow the checkbox, not the stored target.
def test_market_change_during_toggle_keeps_the_users_choice(data, monkeypatch):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    frozen = challenge(snap)  # lab-target as the market request saw it
    monkeypatch.setattr(appmod, "_triggered", lambda: "lab-market")
    body, _, _, _, active, toggle, _ = _detail(app)(frozen, "BTTS", "/lab", ON, frozen, {})
    assert toggle == ON and active.get("latest"), (toggle, active)
    assert "Model calculated" in jtext(body)


def test_latest_to_frozen_during_a_market_change_also_follows_the_checkbox(data, monkeypatch):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    on = {**challenge(snap), "latest": True}  # stored target still latest
    monkeypatch.setattr(appmod, "_triggered", lambda: "lab-market")
    body, _, _, _, active, toggle, _ = _detail(app)(challenge(snap), "OU25", "/lab", [], on, {})
    assert toggle == [] and active == challenge(snap) and "Frozen:" in jtext(body)


def test_mode_rules_for_openings_restores_and_switches():
    t = {"fixture": 1, "ctx": "challenge", "round": "R", "fp": "F"}
    on = {**t, "latest": True}
    other = {**t, "fixture": 2}
    # a new opening is frozen, even with the previous match's toggle still on - whether
    # Dash reports the address or the request first
    for trig in ("lab-request", {"url", "lab-request"}):
        assert appmod.lab_want(other, on, ON, trig) == other
        assert appmod.lab_want(t, on, ON, trig) == t  # reopening the same match too
    # another match in the address is never given the old match's mode
    assert appmod.lab_want(other, on, ON, "lab-market") == other
    # the initial call after a page load (no event) keeps the remembered mode
    assert appmod.lab_want(None, on, [], None) == on
    assert appmod.lab_want(None, on, [], set()) == on
    # the tab itself (same match, a real event): the checkbox, which shows that match
    assert appmod.lab_want(None, on, ON, "url") == on
    assert appmod.lab_want(None, on, [], "url") == t
    # rapid switching: whatever the checkbox shows when the last request is sent
    for value, expected in ((ON, on), ([], t), (ON, on)):
        assert appmod.lab_want(t, t, value, "lab-latest") == expected
    # research targets never take the flag
    r = {"fixture": 1, "ctx": "research"}
    assert appmod.lab_want(r, r, ON, "lab-market") == r


# ---------------------------------------------------------------- frozen, latest, back
def test_challenge_match_defaults_to_frozen_with_the_toggle(data):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    body, _, _, saved, active, toggle, style = _detail(app)(
        challenge(snap), "1X2", "/lab", [], None, {})  # fmt: skip
    text = jtext(body)
    assert toggle == [] and style is SHOWN and saved == active == challenge(snap)
    assert "Weekly Challenge snapshot" in text and "may differ from these frozen values" in text
    assert "Latest available data" not in text


def test_latest_mode_is_research_only_and_back_restores_frozen(data, monkeypatch):  # noqa: F811
    app = _app(data)
    update = _detail(app)
    _, snap = _live(data)
    frozen = challenge(snap)
    monkeypatch.setattr(appmod, "_triggered", lambda: "lab-latest")
    body, _, _, saved, active, toggle, style = update(frozen, "BTTS", "/lab", ON, frozen, {})
    text = jtext(body)
    assert toggle == ON and style is SHOWN and active == {**frozen, "latest": True} == saved
    assert "Latest available data" in text and "Research only" in text
    assert "Model calculated" in text and "Weekly Challenge snapshot" not in text
    # no competitive controls while the latest data is shown
    assert _named(app, "match_lab_panel")(active, {}, {}, None, "/lab") is None
    assert _named(app, "screener_strip")({}, "/lab", active) is None
    # back to frozen: the same match and context, the panel again
    body, _, _, saved, active, toggle, _ = update(frozen, "BTTS", "/lab", [], saved, {})
    assert toggle == [] and active == frozen and saved == frozen
    assert "Weekly Challenge snapshot" in jtext(body)
    assert cb.competitive(active) and not cb.competitive({**frozen, "latest": True})


def test_research_origin_never_shows_the_toggle(data, monkeypatch):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    assert EPL_FIX in {f.fixture_id for f in snap.fixtures}  # also a challenge match
    research = {"fixture": EPL_FIX, "ctx": "research"}
    monkeypatch.setattr(appmod, "_triggered", lambda: "lab-latest")
    body, _, _, _, active, toggle, style = _detail(app)(research, "1X2", "/lab", ON, research,
                                                        {})  # fmt: skip
    assert style == appmod.HIDDEN_STYLE and toggle == [] and active == research
    assert "Latest available data" in jtext(body)


def test_your_view_is_kept_separately_per_context(data, monkeypatch):  # noqa: F811
    app = _app(data)
    update = _detail(app)
    svc, snap = _live(data)
    frozen = challenge(snap)
    latest = {**frozen, "latest": True}
    lc_frozen, _ = lab_context.resolve_target(svc, data, frozen)
    lc_live, _ = lab_context.resolve_target(svc, data, latest)
    assert lc_frozen.key != lc_live.key == str(EPL_FIX)  # separate browser storage
    store = _store(lc_frozen, lc_live)
    for market in ("1X2", "OU25"):  # the market is independent of the context
        assert _delta(update, frozen, market, store) == 0.3
        assert _delta(update, latest, market, store) == -0.2
        assert _delta(update, frozen, market, store) == 0.3  # frozen restored, untouched
    # account storage: different contexts (round row versus live row)
    from diski9.backend.services.your_view import LiveContext, RoundContext

    assert isinstance(lab_context.service_context(lc_live), LiveContext)
    assert lab_context.service_context(lc_frozen) is None  # prototype: no account rows
    a, b = _two_rounds(data)
    svc_db, _ = _changing(data, a)
    lc_db, _ = lab_context.resolve_target(svc_db, data, challenge(a[1]))
    assert lab_context.service_context(lc_db) == RoundContext("uuid-A", EPL_FIX)


def test_latest_view_is_the_research_view_of_the_same_match(data):  # noqa: F811
    """State A/B/C behaviour comes from the existing live path unchanged: the latest
    view of a challenge match is exactly its research view (model or market-implied
    starting point, edge/EV rules)."""
    svc, snap = _live(data)
    for fid in (EPL_FIX,):
        latest, _ = lab_context.resolve_target(svc, data, {**challenge(snap, fid=fid),
                                                           "latest": True})  # fmt: skip
        research, _ = lab_context.resolve_target(svc, data, {"fixture": fid, "ctx": "research"})
        assert latest.kind == research.kind == "live" and latest.key == research.key
        assert lab.starting_point(latest.r) == lab.starting_point(research.r)


def test_toggle_does_not_depend_on_an_independent_model(data, monkeypatch):  # noqa: F811
    app = _app(data)
    svc = _service(app)
    snap = svc.snapshot("live")
    bare = dataclasses.replace(
        snap, fixtures=tuple(dataclasses.replace(f, estimated_goals=None) for f in snap.fixtures)
    )
    monkeypatch.setattr(svc, "live", lambda: bare)  # frozen without Goal Model estimates
    frozen, _ = lab_context.resolve_target(svc, data, challenge(bare))
    assert frozen.kind == "round" and frozen.r["goal_model"]["available"] is False  # B or C
    _, _, _, _, active, toggle, style = _detail(app)(challenge(bare), "1X2", "/lab", [], None, {})
    assert style is SHOWN and toggle == [] and active == challenge(bare)


# ---------------------------------------------------------------- failures and safety
def test_missing_latest_data_never_falls_back_to_frozen(data, monkeypatch):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    latest = {**challenge(snap), "latest": True}
    real = data.detail
    calls = {"n": 0}

    def gone(fid, basis="overall"):  # the latest data for this match is unavailable
        calls["n"] += 1
        return (None, None, None) if fid == EPL_FIX else real(fid, basis)

    monkeypatch.setattr(data, "detail", gone)
    body, _, _, saved, active, toggle, style = _detail(app)(None, "1X2", "/lab", ON, latest, {})
    text = jtext(body)
    assert "Latest data is not available for this match" in text and calls["n"]
    assert "Weekly Challenge snapshot" not in text and active is None
    assert toggle == ON and style is SHOWN and saved is no_update  # can be turned off
    svc = _service(app)
    assert lab_context.resolve_target(svc, data, latest) == (None, lab_context.LATEST_MISSING)


def test_expired_challenge_context_fails_safely_in_both_modes(data):  # noqa: F811
    app = _app(data)
    _, snap = _live(data)
    for t in (challenge(snap, round="old-round"), {**challenge(snap, round="old"), "latest": True},
              challenge(snap, fp="changed")):  # fmt: skip
        body, _, _, _, active, toggle, style = _detail(app)(t, "1X2", "/lab", [], None, {})
        assert "no longer available" in jtext(body) and active is None
        assert style == appmod.HIDDEN_STYLE  # no toggle for an invalid challenge context


def test_stale_selection_controls_are_refused_in_latest_mode(data):  # noqa: F811
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    app = _app(data)
    reduce = _named(app, "reduce")
    _, snap = _live(data)
    key = "|".join(map(str, snap.outcomes[0].key))
    state = {"mode": "live", "selections": []}
    inputs = [None] * 18
    for t in sorted(cb.LAB_ACTIONS):
        trig = {"prop_id": json.dumps({"k": key, "t": t}) + ".n_clicks", "value": 1}
        context_value.set(AttributeDict(triggered_inputs=[trig]))
        for active in ({**challenge(snap), "latest": True}, {"fixture": EPL_FIX,
                                                             "ctx": "research"}, None):  # fmt: skip
            new, flash = reduce(*inputs, state, {}, active)
            assert new is no_update and flash["text"] == cb.LATEST_REFUSED, (t, active)
    # with the frozen analysis the action reaches the reducer as before
    trig = {"prop_id": json.dumps({"k": key, "t": "labpick"}) + ".n_clicks", "value": 1}
    context_value.set(AttributeDict(triggered_inputs=[trig]))
    _, flash = reduce(*inputs, state, {}, challenge(snap))
    assert flash is no_update or flash.get("text") != cb.LATEST_REFUSED
    # builder actions are not Match Lab actions and are unaffected by the Match Lab mode
    assert "pick" not in cb.LAB_ACTIONS and "remove" not in cb.LAB_ACTIONS


# ------------------------------------------------------------------ source transparency
def test_each_context_states_its_own_times(data):  # noqa: F811
    svc, snap = _live(data)
    frozen, _ = lab_context.resolve_target(svc, data, challenge(snap))
    latest, _ = lab_context.resolve_target(svc, data, {**challenge(snap), "latest": True})
    ftext = jtext(lab.context_line(frozen.r, data))
    assert f"Round {snap.round_id}" in ftext and "Frozen:" in ftext
    assert "Model calculated" not in ftext
    note = lab.statistics_note(frozen.r, data)
    assert "frozen Weekly Challenge values" in note and "Goal Model 1" not in note
    _, ov, _ = data.detail(EPL_FIX)
    ltext = jtext(lab.context_line(latest.r, data, ov, "1X2"))
    assert "Model calculated" in ltext and "Research only" in ltext
    assert "Odds observed" in ltext or "No current bookmaker prices" in ltext
    assert "Frozen:" not in ltext and "Goal Model" in lab.statistics_note(latest.r, data)
    none = SimpleNamespace(markets={})
    assert "No current bookmaker prices" in jtext(lab.context_line(latest.r, data, none, "1X2"))


def test_no_outdated_list_name_or_page_level_calculation_time(data):  # noqa: F811
    from pathlib import Path

    src = Path(appmod.__file__).parent
    for f in ("lab.py", "app.py", "lab_context.py", "challenge/callbacks.py",
              "challenge/integration.py", "challenge/adopt_ui.py"):  # fmt: skip
        assert "All Upcoming Fixtures" not in (src / f).read_text(), f
    layout = _app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert "statistics calculated" not in layout and appmod.LATEST_LABEL in layout


# ------------------------------------------------- research-list line: one published read
def test_research_list_frozen_line_reads_one_published_round(data):  # noqa: F811
    a, b = _two_rounds(data)
    va, sa = a
    va.snapshot_at, va.deadline_at = sa.snapshot_at, sa.deadline
    vb, sb = b
    vb.snapshot_at = sa.snapshot_at.replace(year=sa.snapshot_at.year - 1)
    vb.deadline_at = sa.deadline.replace(year=sa.deadline.year - 1)
    svc, backend = _changing(data, a, b)  # a second read would see round B
    text = jtext(integration.data_context(svc, data, "challenge"))
    assert backend.reads == 1
    assert data.local(va.snapshot_at) in text and data.local(va.deadline_at) in text
    assert data.local(vb.deadline_at) not in text


@pytest.mark.parametrize("fid", [PSL_FIX])
def test_research_match_outside_the_snapshot_stays_research(data, fid):  # noqa: F811
    svc, snap = _live(data)
    lc, problem = lab_context.resolve_target(svc, data, {"fixture": fid, "ctx": "research"})
    assert problem is None and lc.kind == "live"
    assert lab_context.resolve_target(svc, data, {**challenge(snap, fid=fid), "latest": True}) == (
        None, lab_context.CHALLENGE_GONE)  # fmt: skip


# ------------------------------------------- CP3A-4 closure: the context's bookmaker reference
FROZEN_1X2 = {"HOME": "1.60", "DRAW": "3.60", "AWAY": "5.20"}  # differ from the latest prices
FROZEN_GOALS = (1.40, 1.10)  # differ from the latest estimate (1.97 - 0.51)


def _distinct(snap, drop_btts=False):
    """The prototype snapshot with this match frozen at other prices and estimates, so the
    two contexts can be told apart (optionally without its BTTS market)."""
    from decimal import Decimal

    inv = {k: 1 / float(v) for k, v in FROZEN_1X2.items()}
    total = sum(inv.values())
    outcomes = []
    for o in snap.outcomes:
        if o.fixture_id == EPL_FIX and str(o.market) == "1X2":
            k = o.outcome.name
            o = dataclasses.replace(o, reference_odds=Decimal(FROZEN_1X2[k]),
                                    market_probability=inv[k] / total)  # fmt: skip
        elif o.fixture_id == EPL_FIX and drop_btts and str(o.market) == "BTTS":
            continue
        outcomes.append(o)
    fixtures = tuple(dataclasses.replace(f, estimated_goals=FROZEN_GOALS)
                     if f.fixture_id == EPL_FIX else f for f in snap.fixtures)  # fmt: skip
    return dataclasses.replace(snap, outcomes=tuple(outcomes), fixtures=fixtures)


def _texts(component, cls):
    """Texts of the nodes with this class (e.g. the reference card's price cells)."""
    found = []

    def text(node):
        if isinstance(node, dict):
            kids = node.get("props", {}).get("children")
            return text(kids)
        if isinstance(node, list):
            return "".join(text(n) for n in node)
        return "" if node is None else str(node)

    def walk(node):
        if isinstance(node, dict):
            props = node.get("props", {})
            if cls in (props.get("className") or "").split():
                found.append(text(node))
            for v in props.values():
                walk(v)
        elif isinstance(node, list):
            for n in node:
                walk(n)

    walk(json.loads(jtext(component)))
    return found


def _frozen_app(data, monkeypatch, **kw):  # noqa: F811
    app = _app(data)
    svc = _service(app)
    snap = _distinct(svc.snapshot("live"), **kw)
    monkeypatch.setattr(svc, "live", lambda: snap)
    return app, snap


def test_frozen_reference_card_shows_only_snapshot_prices(data, monkeypatch):  # noqa: F811
    app, snap = _frozen_app(data, monkeypatch)
    body, ref, *_ = _detail(app)(challenge(snap), "1X2", "/lab", [], None, {})
    text = jtext(ref)
    assert "Frozen Bookmaker Market Reference" in text and "Weekly Challenge snapshot" in text
    assert _texts(ref, "price") == ["1.60", "3.60", "5.20"]  # never the latest 1.45/3.40/3.80
    assert "Individual bookmaker prices" not in text.split("not stored")[-1]  # no ranges
    assert "latest collected" not in text and "3 independent bookmaker groups" in text
    # Your View's value check uses the frozen prices too (no latest substitution)
    assert "1.45" not in jtext(body) and "1.60" in jtext(body)
    # the frozen estimate is the snapshot's
    assert "1.40" in jtext(body) and "1.10" in jtext(body)


def test_missing_frozen_market_is_unavailable_never_latest(data, monkeypatch):  # noqa: F811
    app, snap = _frozen_app(data, monkeypatch, drop_btts=True)
    _, ref, *_ = _detail(app)(challenge(snap), "BTTS", "/lab", [], None, {})
    text = jtext(ref)
    assert lab_context.FROZEN_MARKET_MISSING in text
    assert _texts(ref, "price") == [] and "1.80" not in text and "2.00" not in text


def test_latest_and_research_keep_the_latest_reference(data, monkeypatch):  # noqa: F811
    app, snap = _frozen_app(data, monkeypatch)
    update = _detail(app)
    latest = {**challenge(snap), "latest": True}
    for t in (latest, {"fixture": EPL_FIX, "ctx": "research"}):
        body, ref, *_ = update(t, "1X2", "/lab", [], t, {})
        text = jtext(ref)
        assert (
            "Frozen Bookmaker Market Reference" not in text and "Bookmaker Market Reference" in text
        )
        assert _texts(ref, "price") == ["1.45", "3.40", "3.80"], t  # the latest consensus
        assert "1.97" in jtext(body)  # the latest estimate, not the frozen 1.40


def test_frozen_odds_view_holds_only_snapshot_values(data):  # noqa: F811
    _, snap = _live(data)
    snap = _distinct(snap, drop_btts=True)
    ov = lab_context.frozen_odds(snap, EPL_FIX)
    from diski9.api_football.markets import Market

    dm = ov.markets[Market.MATCH_RESULT]
    assert {k.name: str(v.consensus_odds) for k, v in dm.consensus.outcomes.items()} == FROZEN_1X2
    assert all(v.min_odds is None and v.max_odds is None for v in dm.consensus.outcomes.values())
    assert abs(sum(float(x) for x in dm.implied.margin_adjusted.values()) - 1) < 1e-9
    assert (
        ov.markets[Market.BTTS].status == "unavailable"
        and ov.markets[Market.BTTS].consensus is None
    )


def test_supplementary_statistics_note_and_frozen_integrity(data, monkeypatch):  # noqa: F811
    app, snap = _frozen_app(data, monkeypatch)
    update = _detail(app)
    frozen_body = jtext(update(challenge(snap), "1X2", "/lab", [], None, {})[0])
    assert lab.FROZEN_CONTEXT_NOTE in frozen_body
    latest = {**challenge(snap), "latest": True}
    for t in (latest, {"fixture": EPL_FIX, "ctx": "research"}):
        assert lab.FROZEN_CONTEXT_NOTE not in jtext(update(t, "1X2", "/lab", [], t, {})[0])
    lc, _ = lab_context.resolve_target(_service(app), data, challenge(snap))
    g = lc.r["goal_model"]["estimated_goals"]
    assert (g["home"], g["away"]) == FROZEN_GOALS  # the latest statistics change nothing
    assert lc.r["_model_context"].endswith("|1.40|1.10")


# ------------------------------------------------------------------------- browser
BROWSER = r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = { errors: [], widths: {} };
  for (const w of [390, 768, 1280]) {
    const ctx = await b.newContext({ viewport: { width: w, height: 900 } });
    const p = await ctx.newPage();
    p.on('pageerror', e => out.errors.push(w + ': ' + e.message));
    const r = {};
    const shot = async (n) => { if (SHOTS) await p.screenshot({ path: `${SHOTS}/cp3a4_${n}_${w}.png` }); };
    const overflow = () => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const detail = () => p.locator('#detail').innerText().then(t => t.toLowerCase());
    const until = (text) => p.waitForFunction((t) => ((document.querySelector('#detail') || {})
      .innerText || '').toLowerCase().includes(t), text, { timeout: 20000 });
    const ctxHome = async () => {
      const acc = p.locator('.ctx-acc').first();
      if (!(await acc.evaluate(e => e.open))) await acc.locator('summary').click();
      return p.locator('#ctx-home').inputValue();
    };
    const toggle = p.locator('#lab-latest input');
    const prices = () => p.evaluate(() => [...document.querySelectorAll('#detail-reference .card.market .price')].map(e => e.innerText.trim()));
    const goals = () => p.evaluate(() => [...document.querySelectorAll('#detail .lab-baseline .num, #detail .lab-baseline .big')].map(e => e.innerText.trim()).join(' '));
    const leftAligned = () => p.evaluate(() => {
      const h = document.querySelector('.detail-header h2').getBoundingClientRect().left;
      return [...document.querySelectorAll('.lab-context .lab-context-line > *, .lab-context-note')]
        .every(e => Math.abs(e.getBoundingClientRect().left - h) < 2 || e.previousElementSibling);
    });
    const scrollShot = async (sel, n) => { await p.locator(sel).first().scrollIntoViewIfNeeded(); await p.evaluate(() => window.scrollBy(0, -80)); await shot(n); };
    // a challenge-origin match: frozen by default, the toggle shown and off
    await p.goto(BASE + `lab?fixture=${FID}&ctx=challenge&round=${ROUND}`);
    await until('frozen:');
    r.toggleShown = await p.locator('#lab-latest-wrap').isVisible();
    r.offAtStart = !(await toggle.isChecked());
    r.overflowFrozen = await overflow(); await shot('frozen');
    // the frozen context's own reference, estimate and disclosure
    await p.waitForFunction(() => document.querySelectorAll('#detail-reference .card.market .price').length > 0);
    r.frozenPrices = await prices();
    r.frozenCard = (await p.locator('#detail-reference .card.market').innerText()).toLowerCase().includes('frozen bookmaker market reference');
    r.frozenGoals = (await p.locator('#detail .lab-baseline').innerText()).includes('1.40');
    r.note = (await detail()).includes('supplementary latest data');
    r.frozenLeft = await leftAligned();
    await scrollShot('#detail-reference .card.market', 'frozen_reference');
    await scrollShot('.frozen-context-note', 'frozen_context_note');
    await ctxHome(); await p.locator('#ctx-home').fill('0.25'); await p.locator('#ctx-home').press('Tab');
    await p.waitForFunction(() => document.querySelector('#ctx-home').value === '+0.25');
    // latest data: research only, its own (empty) Your View, no selection panel
    await toggle.click(); await until('model calculated');
    const t = await detail();
    r.latestText = t.includes('research only') && t.includes('model calculated') && !t.includes('weekly challenge snapshot');
    r.latestHome = await ctxHome();
    await p.waitForFunction(() => document.querySelector('#lab-challenge').innerText.trim() === ''
      && document.querySelector('#ch-strip').innerText.trim() === '', null, { timeout: 10000 }).catch(() => {});
    r.latestPanel = (await p.locator('#lab-challenge').innerText()).trim();
    r.latestStrip = (await p.locator('#ch-strip').innerText()).trim();
    await p.evaluate(() => window.scrollTo(0, 0));
    r.overflowLatest = await overflow(); await shot('latest');
    await p.waitForFunction(() => !document.querySelector('#detail-reference').innerText.toLowerCase().includes('frozen bookmaker'));
    r.latestPrices = await prices();
    r.latestGoals = (await p.locator('#detail .lab-baseline').innerText()).includes('1.97');
    r.latestNote = (await detail()).includes('supplementary latest data');
    r.latestLeft = await leftAligned();
    await scrollShot('#detail-reference .card.market', 'latest_reference');
    await p.evaluate(() => window.scrollTo(0, 0));
    // the market is independent of the context
    await p.locator('#lab-market label', { hasText: 'Both Teams' }).click();
    await p.waitForFunction(() => document.querySelector('#lab-market input:checked').value === 'BTTS');
    await until('model calculated');
    r.stillLatest = await toggle.isChecked();
    // back to frozen: the frozen Your View again, the same market
    await toggle.click(); await until('frozen:');
    r.frozenHome = await ctxHome();
    r.marketKept = await p.evaluate(() => document.querySelector('#lab-market input:checked').value);
    // a research-origin match: latest data, never the toggle
    await p.goto(BASE); await p.waitForSelector(w < 720 ? '#screener-root .fx-card' : '#screener-root tr.row', { state: 'visible', timeout: 20000 });
    await p.locator(w < 720 ? '#screener-root .fx-card' : '#screener-root tr.row').first().click();
    await p.waitForURL(/ctx=research/); await until('model calculated');
    r.researchToggle = await p.locator('#lab-latest-wrap').isVisible();
    r.researchLeft = await leftAligned();
    r.overflowResearch = await overflow(); await shot('research_origin');
    out.widths[w] = r;
    await ctx.close();
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_browser_frozen_latest_and_research_origin_at_three_widths(data, monkeypatch):  # noqa: F811
    import os
    import shutil
    import subprocess
    import threading

    if (
        shutil.which("node") is None
        or subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode
    ):
        pytest.skip("node with playwright not available")
    from werkzeug.serving import make_server

    from .test_app import _free_port

    app, snap = _frozen_app(data, monkeypatch)  # frozen values differ from the latest ones
    port = _free_port()
    server = make_server("127.0.0.1", port, app.server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    head = (f"const BASE = 'http://127.0.0.1:{port}/'; const FID = {EPL_FIX}; "
            f"const ROUND = {json.dumps(snap.round_id)}; "
            f"const SHOTS = {json.dumps(os.environ.get('DISKI9_SHOTS', ''))};\n")  # fmt: skip
    try:
        res = subprocess.run(["node", "-e", head + BROWSER], capture_output=True, text=True,
                             timeout=400)  # fmt: skip
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
    assert out["errors"] == []
    for w, r in out["widths"].items():
        assert r["toggleShown"] and r["offAtStart"], (w, r)
        assert r["latestText"] and r["latestHome"] == "0.00", (w, r)  # not the frozen view
        assert r["latestPanel"] == "" and r["latestStrip"] == "", (w, r)
        assert r["stillLatest"] and r["frozenHome"] == "+0.25" and r["marketKept"] == "BTTS", w
        assert not r["researchToggle"], w
        assert r["frozenCard"] and r["frozenPrices"] == ["1.60", "3.60", "5.20"], (w, r)
        assert r["latestPrices"] == ["1.45", "3.40", "3.80"], (w, r)
        assert r["frozenGoals"] and r["latestGoals"], (w, r)  # the switch is visible
        assert r["note"] and not r["latestNote"], (w, r)
        assert r["frozenLeft"] and r["latestLeft"] and r["researchLeft"], (w, r)
        assert r["overflowFrozen"] == r["overflowLatest"] == r["overflowResearch"] == 0, (w, r)
