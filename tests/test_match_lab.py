# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Engine 3.0: The Match Lab, cross-league support, UEFA exclusion, forecast
snapshots and calibration monitoring."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from dash import html
from sqlalchemy import delete, select, text, update

from diski9.app import ScreenerData, create_app
from diski9.app.app import _parse_goals, lab_update
from diski9.app.data import LEAGUE_SHORT
from diski9.app.lab import breakdown, has_adjustment, lab_outputs, pp, render_detail, slider_max
from diski9.app.methodology import methodology_section
from diski9.db.schema import fixtures, forecast_snapshots, odds_quotes
from diski9.leagues import COMPETITIONS, screener_competitions, seasons_for
from diski9.screener import cache, forecasts
from diski9.screener import goal_model as gm
from diski9.screener.engine import MatchStore, compute_fixture

from .test_app import (  # noqa: F401
    EPL_FIX,
    EXTRA,
    PSL_FIX,
    T0,
    _find,
    _text,
    data,
    payload,
    populated,
)


# ---------------------------------------------------------------- leagues
def test_eight_domestic_leagues_with_shared_parameters():
    comps = screener_competitions()
    assert sorted(comps) == [39, 40, 61, 78, 135, 140, 288, 289]
    assert all(c in LEAGUE_SHORT for c in comps)
    for c in (140, 61, 78, 135):
        assert seasons_for(c) == (2025, 2026)  # previous-season prior + current season
        assert COMPETITIONS[c].odds_enabled is False  # odds trial scope unchanged
    assert 2 not in COMPETITIONS and 3 not in COMPETITIONS  # UEFA never in the Screener
    # one frozen parameter set: nothing league-specific exists in the model
    assert not any(isinstance(v, dict) for v in vars(gm.PARAMS).values())


# ------------------------------------------------------------ Match Lab logic
def _result(data):
    return data.detail(EPL_FIX)[0]


def test_baseline_payload_and_markets_consistent(data):
    g = _result(data)["goal_model"]
    assert g["available"] and g["model"]["goal_model_version"] == "1.0"
    assert g["probabilities"] == pytest.approx(
        gm.markets(g["estimated_goals"]["home"], g["estimated_goals"]["away"])
    )


def test_lab_update_slider_input_reset_and_validation(data):
    r = _result(data)
    base = {s: round(v, 2) for s, v in r["goal_model"]["estimated_goals"].items()}
    a, msg = lab_update(r, "lab-home-slider", 2.05, None)
    assert msg == [] and breakdown(base, a)["home"]["final"] == 2.05
    assert a["manual"]["home"] == pytest.approx(2.05 - base["home"])
    b, _ = lab_update(r, "lab-away-input", "0.8", a)
    assert breakdown(base, b)["away"]["final"] == 0.8
    for bad in ("x", -1, 11, float("nan"), None):
        c, msg = lab_update(r, "lab-away-input", bad, b)
        assert c == b and msg and "not changed" in msg[0]  # explained, never silent
    d, _ = lab_update(r, "lab-reset", 1, b)
    assert not has_adjustment(d)
    assert _parse_goals("1.234") == 1.23 and _parse_goals("10.5") is None


def test_adjustment_recalculates_all_seven_and_never_touches_baseline(data):
    r = _result(data)
    before = copy.deepcopy(r)
    base = {s: round(v, 2) for s, v in r["goal_model"]["estimated_goals"].items()}
    st, _ = lab_update(r, "lab-home-input", 1.55, None)
    st, _ = lab_update(r, "lab-away-input", 1.10, st)
    out, compare = lab_outputs(r, "1X2", data.detail(EPL_FIX)[1], st)
    mine = gm.markets(1.55, 1.10)
    t = _text(out)
    for key in ("home", "draw", "away", "btts_yes", "btts_no", "over", "under"):
        assert f"{mine[key] * 100:.1f}%" in t  # selected market + "All markets"
    b = r["goal_model"]["probabilities"]
    assert pp(mine["home"] - b["home"]) in t
    for label in (
        "Model baseline",
        "Your research (Section C)",
        "Additional manual adjustment",
        "Your estimate",
    ):
        assert label in t
    assert "Your estimate" in t and "Yours" in _text(compare)
    assert r == before  # the cached baseline is never modified
    d = render_detail(r, *data.detail(EPL_FIX)[1:], "1X2", data, st)
    base_section = _text(d.children[1].children[1])
    assert f"{b['home'] * 100:.1f}%" in base_section  # baseline stays the model's
    assert "Adjusted by you" in _text(d.children[0])
    assert base == {s: round(v, 2) for s, v in r["goal_model"]["estimated_goals"].items()}


def test_pp_and_slider_range():
    assert pp(0.06) == "+6.0 pp" and pp(-0.123) == "-12.3 pp" and pp(0.0) == "0.0 pp"
    assert slider_max(1.4) == 5.0 and slider_max(4.6) == 6.0  # never caps the baseline
    assert slider_max(1.4, 7.2) == 9.0


def _adjust_callback(data):
    app = create_app(data)
    return next(v for k, v in app.callback_map.items() if "lab-store.data" in k)[
        "callback"
    ].__wrapped__


def _trigger(prop_id: str, value=1):
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    context_value.set(AttributeDict(triggered_inputs=[{"prop_id": prop_id, "value": value}]))


def test_adjust_callback_keyed_by_fixture_and_isolated(data):
    func = _adjust_callback(data)
    other = {"123": {"cats": {}, "manual": {"home": 9.0, "away": 9.0}}}
    snapshot = copy.deepcopy(other)
    _trigger("lab-home-input.value", 2.4)
    out = _call(func, data, other, value=2.4)
    store = out[0]
    assert store["123"] == other["123"]  # other fixtures untouched
    b = breakdown(
        {s: round(v, 2) for s, v in _result(data)["goal_model"]["estimated_goals"].items()},
        store[str(EPL_FIX)],
    )
    assert b["home"]["final"] == 2.4 and out[1] == out[2] == 2.4
    assert other == snapshot  # input store not mutated
    # a second user's (empty) store is unaffected: state lives in each browser only
    _trigger("lab-reset.n_clicks", 1)
    out2 = _call(func, data, {}, value=1)
    assert out2[0] == {}
    layout = create_app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert '"id":"lab-store"' in layout and '"storage_type":"memory"' in layout


def test_market_switch_keeps_adjustment(data):
    app = create_app(data)
    detail = next(v for k, v in app.callback_map.items() if k.startswith("detail.children"))
    func = detail["callback"].__wrapped__
    r = _result(data)
    st, _ = lab_update(r, {"type": "cat-adj", "cat": "squad", "side": "home"}, -0.15, None)
    st, _ = lab_update(r, {"type": "cat-note", "cat": "squad"}, "Striker out", st)
    st, _ = lab_update(r, "lab-home-input", 2.5, st)
    lab = {str(EPL_FIX): st}
    for market in ("1X2", "BTTS", "OU25"):
        d = func(EPL_FIX, market, lab)
        sliders = _find(d, lambda c: getattr(c, "id", None) == "lab-home-slider")
        assert sliders[0].value == 2.5
        cat = _find(
            d,
            lambda c: getattr(c, "id", None) == {"type": "cat-adj", "cat": "squad", "side": "home"},
        )
        note = _find(d, lambda c: getattr(c, "id", None) == {"type": "cat-note", "cat": "squad"})
        assert cat[0].value == -0.15 and note[0].value == "Striker out"
        assert "Adjusted by you" in _text(d)
    # another fixture has its own (empty) state
    d = func(PSL_FIX, "1X2", lab)
    assert "Adjusted by you" not in _text(d)


def test_context_never_changes_estimated_goals(populated):
    with populated.connect() as conn:
        store = MatchStore(conn)
        fx = conn.execute(select(fixtures).where(fixtures.c.id == EPL_FIX)).one()
    a = compute_fixture(store, fx, T0, "overall")["goal_model"]
    # add head-to-head meetings in another competition and an extra cup-style match:
    # Form Score / H2H context changes, the model does not
    from diski9.screener.engine import Match

    extra = [
        Match(
            90000 + i,
            T0 - timedelta(days=400 + i),
            40,
            2024,
            1,
            2,
            5,
            0,
            "verified",
            True,
            None,
            None,
            "FT",
            "x",
        )
        for i in range(3)
    ]
    store2 = MatchStore.from_matches(
        store.matches + extra, store.team_names, store.competition_names
    )
    r2 = compute_fixture(store2, fx, T0, "overall")
    assert len(r2["head_to_head"]) > 0
    assert r2["goal_model"] == a


def test_odds_are_never_model_inputs(populated):
    d = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0)
    before = d.detail(EPL_FIX)[0]["goal_model"]
    with populated.begin() as conn:
        conn.execute(delete(odds_quotes))
        cache.invalidate(conn, T0)
        cache.refresh(conn, [EPL_FIX], T0, T0)
    after = ScreenerData(populated, ttl_seconds=0, clock=lambda: T0).detail(EPL_FIX)[0]
    assert after["goal_model"] == before


# ------------------------------------------------------------------ UEFA
def test_uefa_fixtures_show_no_probabilities(data):
    r = copy.deepcopy(_result(data))
    r["fixture"]["competition_id"] = 2
    r["goal_model"] = {
        "available": False,
        "reason": "european_competition",
        "message": gm.UEFA_MESSAGE,
    }
    row = data.row("1X2", r)
    assert not row["available"] and row["p_home"] == "—" and row["estimated_goals"] == "—"
    st, _ = lab_update(_result(data), "lab-home-input", 3.0, None)
    d = render_detail(r, None, {}, "1X2", data, st)
    t = _text(d)
    assert gm.UEFA_MESSAGE in t
    assert not _find(d, lambda c: "eg-tile" in str(getattr(c, "className", "")))
    assert not _find(d, lambda c: getattr(c, "id", None) == "lab-home-slider")
    assert not _find(
        d, lambda c: isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "cat-adj"
    )
    assert "Adjusted by you" not in t


# -------------------------------------------------------------- methodology
def test_methodology_section_content():
    t = _text(methodology_section())
    for phrase in (
        "How Diski 9 Calculates Probabilities",
        "Poisson goal distribution",
        "rely more on league averages",
        "Strength smoothing",
        "Goal tempo smoothing",
        "League-average prior",
        "Premier League, Championship, South African Premiership and First Division",
        "La Liga, Ligue 1, the Bundesliga and Serie A",
        "Not every competition was used to choose the settings",
        "Model settings stay fixed",
        "Draws have historically been slightly underestimated",
        "not validated for UEFA",
        "at least 0.005",
        "Goal Model 1.0",
        "not shot-based xG",
    ):
        assert phrase in t, phrase
    assert "12" in t and "96" in t and "30" in t


# --------------------------------------------------------------- snapshots
def _fx(conn, fid=EPL_FIX):
    return conn.execute(select(fixtures).where(fixtures.c.id == fid)).one()


def _snapshots(conn, fid=EPL_FIX):
    return conn.execute(
        select(forecast_snapshots)
        .where(forecast_snapshots.c.fixture_id == fid)
        .order_by(forecast_snapshots.c.id)
    ).all()


def test_live_refresh_records_one_snapshot_with_model_version(populated):
    with populated.connect() as conn:
        rows = _snapshots(conn)
    assert len(rows) == 1  # recorded by the fixture's live refresh at T0
    s = rows[0]
    assert s.goal_model_version == "1.0" and s.engine_version == "3.0.0"
    assert json.loads(s.params_json) == {"k_s": 12.0, "k_t": 96.0, "m0": 30.0}
    assert s.created_at == T0 < s.kickoff_utc and s.data_cutoff == T0
    assert s.p_home + s.p_draw + s.p_away == pytest.approx(1)
    assert json.loads(s.baseline_json)["home"] > 0
    # repeated refreshes do not duplicate an unchanged forecast
    with populated.begin() as conn:
        cache.refresh(conn, [EPL_FIX], T0 + timedelta(hours=1), T0 + timedelta(hours=1))
        assert len(_snapshots(conn)) == 1


def test_snapshot_rules(populated):
    with populated.begin() as conn:
        fx = _fx(conn)
        r = compute_fixture(MatchStore(conn), fx, T0, "overall")
        later = T0 + timedelta(hours=2)
        assert (
            forecasts.record(conn, fx, r, later, live=False, engine_version="3.0.0") == "not_live"
        )
        after = fx.kickoff_utc + timedelta(minutes=1)
        assert forecasts.record(conn, fx, r, after, True, "3.0.0") == "kicked_off"
        assert forecasts.record(conn, fx, r, later, True, "3.0.0") == "unchanged"
        changed = copy.deepcopy(r)
        changed["goal_model"]["lambda_home"] += 0.1
        assert forecasts.record(conn, fx, changed, later, True, "3.0.0") == "recorded"
        unavailable = {**r, "goal_model": {"available": False}}
        assert forecasts.record(conn, fx, unavailable, later, True, "3.0.0") == "unavailable"
        assert len(_snapshots(conn)) == 2


def test_historical_replay_never_records(populated):
    with populated.begin() as conn:
        n = conn.execute(text("select count(*) from forecast_snapshots")).scalar()
        cache.invalidate(conn, T0)
        cache.refresh(conn, [EPL_FIX, PSL_FIX], T0 - timedelta(days=1), T0)  # as_of != now
        assert conn.execute(text("select count(*) from forecast_snapshots")).scalar() == n


def test_snapshots_are_immutable(populated):
    from sqlalchemy.exc import IntegrityError

    for stmt in (update(forecast_snapshots).values(p_home=0.99), delete(forecast_snapshots)):
        with pytest.raises(IntegrityError, match="immutable"), populated.begin() as conn:
            conn.execute(stmt)


def _settle(conn, fid, hg, ag, kickoff=None):
    vals = {
        "is_final": True,
        "status_short": "FT",
        "ft_home": hg,
        "ft_away": ag,
        "stats_exclusion_reason": None,
    }
    if kickoff is not None:
        vals["kickoff_utc"] = kickoff
    conn.execute(update(fixtures).where(fixtures.c.id == fid).values(**vals))


def test_official_forecast_and_monitoring_without_lookahead(populated):
    with populated.begin() as conn:
        fx = _fx(conn)
        r = compute_fixture(MatchStore(conn), fx, T0, "overall")
        # a later (still pre-kickoff) forecast becomes the official one
        later = copy.deepcopy(r)
        later["goal_model"]["lambda_home"] = 2.0
        forecasts.record(conn, fx, later, T0 + timedelta(days=1), True, "3.0.0")
        _settle(conn, EPL_FIX, 2, 1)
        # PSL fixture: postponed and then cancelled -> never evaluated
        conn.execute(
            update(fixtures)
            .where(fixtures.c.id == PSL_FIX)
            .values(status_short="CANC", stats_exclusion_reason="cancelled", is_final=False)
        )
        off = forecasts.official_forecasts(conn)
        assert [o["fixture_id"] for o in off] == [EPL_FIX]
        assert off[0]["lambda_home"] == 2.0 and off[0]["created_at"] < off[0]["actual_kickoff"]
        rep = forecasts.report(conn, T0 + timedelta(days=10))
    assert rep["official_forecasts"] == 1
    allg = {g["market"]: g for g in rep["groups"] if g["competition_id"] == "all"}
    assert set(allg) == {"1X2", "BTTS", "OU25"}
    g = allg["1X2"]
    assert g["settled_fixtures"] == 1 and g["preliminary"] is True
    import math

    assert g["log_loss"] == pytest.approx(-math.log(off[0]["p_home"]), abs=1e-4)
    assert g["baseline_log_loss"] is not None and "log_loss_vs_baseline" in g
    assert g["goal_model_version"] == "1.0"


def test_forecasts_after_kickoff_are_never_official(populated):
    with populated.begin() as conn:
        fx = _fx(conn)
        # the match was brought forward: it kicked off before the only snapshot
        _settle(conn, EPL_FIX, 0, 0, kickoff=T0 - timedelta(hours=1))
        assert forecasts.official_forecasts(conn) == []
        rep = forecasts.report(conn, T0)
    assert rep["official_forecasts"] == 0 and rep["groups"] == []
    assert fx.id == EPL_FIX


def test_migration_rollback_removes_table(tmp_path):
    from alembic import command
    from alembic.config import Config

    from diski9.db import make_engine, upgrade

    url = f"sqlite:///{tmp_path / 'm.sqlite'}"
    upgrade(url)
    eng = make_engine(url)
    with eng.connect() as conn:
        assert (
            conn.execute(
                text("select count(*) from sqlite_master where name='forecast_snapshots'")
            ).scalar()
            == 1
        )
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "0003")
    with eng.connect() as conn:
        assert (
            conn.execute(
                text("select count(*) from sqlite_master where name like 'forecast_snapshots%'")
            ).scalar()
            == 0
        )
    command.upgrade(cfg, "head")


def test_model_report_cli(populated, tmp_path, monkeypatch):
    from diski9 import cli

    args = SimpleNamespace(out_dir=str(tmp_path))
    cli.cmd_model_report(args, populated)
    files = list(tmp_path.glob("model_report_*.json"))
    assert len(files) == 1
    rep = json.loads(files[0].read_text())
    assert "official = latest snapshot recorded before the actual kickoff" in rep["policy"]


def test_early_season_extra_fixtures_flagged(data):
    r = data.detail(EXTRA[0])[0]
    g = r["goal_model"]
    assert g["available"] and g["league_average_only"] == ["home", "away"] and g["early_season"]
    assert g["estimated_goals"]["home"] == pytest.approx(g["league"]["home"])


def test_section_c_categories_aggregate_into_section_d(data):
    r = _result(data)
    base = {s: round(v, 2) for s, v in r["goal_model"]["estimated_goals"].items()}
    st = None
    for cat, v in (("squad", -0.15), ("fitness", -0.10), ("tactics", 0.05), ("conditions", 0)):
        st, msg = lab_update(r, {"type": "cat-adj", "cat": cat, "side": "home"}, v, st)
        assert msg == []
    st, _ = lab_update(r, {"type": "cat-adj", "cat": "squad", "side": "away"}, 0.10, st)
    b = breakdown(base, st)
    assert b["home"]["cats"] == -0.20 and b["home"]["manual"] == 0
    assert b["home"]["final"] == round(base["home"] - 0.20, 2)
    assert b["away"]["final"] == round(base["away"] + 0.10, 2)
    # direct final edit: the manual adjustment is derived, never added on top
    st2, _ = lab_update(r, "lab-home-input", round(base["home"] - 0.30, 2), st)
    b2 = breakdown(base, st2)
    assert b2["home"]["final"] == round(base["home"] - 0.30, 2)
    assert b2["home"]["manual"] == pytest.approx(-0.10)
    # a later category change keeps the manual adjustment and moves the final estimate
    st3, _ = lab_update(r, {"type": "cat-adj", "cat": "conditions", "side": "home"}, 0.05, st2)
    assert breakdown(base, st3)["home"]["final"] == round(base["home"] - 0.25, 2)
    # notes are stored per category; invalid category values are explained and ignored
    st4, _ = lab_update(r, {"type": "cat-note", "cat": "squad"}, "  Striker out  ", st3)
    assert st4["cats"]["squad"]["note"] == "Striker out"
    st5, msg = lab_update(r, {"type": "cat-adj", "cat": "squad", "side": "home"}, 9, st4)
    assert st5 == st4 and "between -2 and +2" in msg[0]
    cleared, _ = lab_update(r, {"type": "cat-adj", "cat": "squad", "side": "home"}, None, st4)
    assert cleared["cats"]["squad"]["home"] == 0.0  # an emptied box means 0
    # reset: every adjustment cleared, research notes kept
    reset, _ = lab_update(r, "lab-reset", 1, st4)
    assert not has_adjustment(reset) and reset["cats"]["squad"]["note"] == "Striker out"


def test_final_estimate_never_negative_and_explained(data):
    r = _result(data)
    st = None
    for cat in ("squad", "fitness", "tactics", "conditions"):
        st, _ = lab_update(r, {"type": "cat-adj", "cat": cat, "side": "away"}, -2, st)
    base = {s: round(v, 2) for s, v in r["goal_model"]["estimated_goals"].items()}
    b = breakdown(base, st)
    assert b["away"]["final"] == 0 and b["away"]["clipped"]
    out, _ = lab_outputs(r, "1X2", None, st)
    assert "held at 0.00" in _text(out)
    p = gm.markets(b["home"]["final"], 0.0)
    assert p["away"] == pytest.approx(0, abs=1e-12)
    assert p["home"] + p["draw"] == pytest.approx(1)


def _call(func, data, lab, value):
    """Invoke the Match Lab callback outside Dash, with pattern-matching output lists."""
    from dash._callback_context import context_value

    from diski9.app.lab import CATEGORY_KEYS

    ctxv = context_value.get()
    ctxv["outputs_list"] = [None] * 7 + [
        [
            {"id": {"type": "cat-adj", "cat": k, "side": s}}
            for k in CATEGORY_KEYS
            for s in ("home", "away")
        ],
        [{"id": {"type": "cat-sum", "cat": k}} for k in CATEGORY_KEYS],
    ]
    ctxv["triggered_inputs"][0]["value"] = value
    return func(None, None, None, None, 0, [], [], EPL_FIX, "BTTS", lab)


def test_section_c_structure_and_education(data):
    r, ov, off = data.detail(EPL_FIX)
    d = render_detail(r, ov, off, "1X2", data)
    sec = [
        c for c in d.children[1].children if "factors-section" in str(getattr(c, "className", ""))
    ][0]
    t = _text(sec)
    for phrase in (
        "Squad & Availability",
        "Fitness & Scheduling",
        "Tactics & Management",
        "Match Conditions & Motivation",
        "Injuries",
        "Travel demands",
        "Relevant tactical matchups",
        "Title or relegation circumstances",
        "not automatically included in the statistical model",
        "Avoid counting the same information twice",
        "never assigns a value",
    ):
        assert phrase in t, phrase
    accs = _find(sec, lambda c: isinstance(c, html.Details) and "cat-acc" in c.className)
    assert len(accs) == 4 and not any(getattr(a, "open", False) for a in accs)
    inputs = _find(
        sec, lambda c: isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "cat-adj"
    )
    assert len(inputs) == 8 and all(i.value == 0.0 and i.step == 0.05 for i in inputs)
    for label in ("Model estimate", "Context", "Your research", "Your assumptions", "Market"):
        assert label in _text(d)


def test_bookmaker_cards_consistent_across_markets(data):
    from diski9.app.data import MARKET_OF, MARKET_OUTCOME_ORDER, OUTCOME_LABEL

    r, ov, off = data.detail(EPL_FIX)
    for market, n in (("1X2", 3), ("BTTS", 2), ("OU25", 2)):
        card = render_detail(r, ov, off, market, data).children[2]
        grids = _find(card, lambda c: str(getattr(c, "className", "")).startswith("prices"))
        assert len(grids) == 1 and grids[0].className == f"prices cols-{n}"
        cells = grids[0].children
        assert len(cells) == n and all(c.className == "price-cell" for c in cells)
        dm = ov.markets[MARKET_OF[market]]
        for cell, o in zip(cells, MARKET_OUTCOME_ORDER[MARKET_OF[market]], strict=True):
            label, price, raw = cell.children
            assert _text(label) == OUTCOME_LABEL[o]
            assert _text(price) == str(dm.consensus.outcomes[o].consensus_odds)
            assert _text(raw) == f"raw {float(dm.implied.raw[o]) * 100:.1f}%"
    from pathlib import Path

    css = Path("src/diski9/app/assets/style.css").read_text()
    rule = css[css.index(".price-cell { display: flex") :]
    rule = rule[: rule.index("}")]
    assert "align-items: center" in rule and "text-align: center" in rule
    # missing odds: no grid, honest message
    r, ov, off = data.detail(PSL_FIX)
    card = render_detail(r, ov, off, "1X2", data).children[2]
    assert not _find(card, lambda c: str(getattr(c, "className", "")).startswith("prices"))
    assert "No bookmaker odds are available" in _text(card)


def test_form_score_two_levels(data):
    r, ov, off = data.detail(EPL_FIX)
    d = render_detail(r, ov, off, "1X2", data)
    form = [
        a
        for a in _find(d, lambda c: isinstance(c, html.Details) and c.className == "acc")
        if _text(a.children[0]).startswith("Recent form")
    ][0]
    body = form.children[1].children
    primary = [c for c in body if not isinstance(c, html.Details)]
    t = _text(primary)
    assert "out of 5" in t and "League Form Score average" in t and "Recent results" in t
    assert "Points part" not in t and "Venue context" not in t  # formulas one level down
    detail = [c for c in body if isinstance(c, html.Details)][0]
    assert _text(detail.children[0]) == "Calculation and detail"
    assert not getattr(detail, "open", False)
    dt = _text(detail)
    assert "Points part = 2.5 × points ÷ 3N" in dt and "Venue context" in dt
    assert "Matches used" in dt


def test_market_dropdown_and_league_multiselect(data):
    from diski9.app.app import MARKETS, league_labels

    layout = create_app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert '"id":"market"' in layout and '"Match Result (1X2)"' in layout
    assert '"Both Teams to Score (BTTS)"' in layout and "Over\\u002fUnder 2.5 Goals" in layout
    assert '"type":"Tabs"' not in layout  # the tab row is gone
    assert '"id":"leagues"' in layout and '"multi":true' in layout
    assert [m for m, _ in MARKETS] == ["1X2", "BTTS", "OU25"]
    assert league_labels(8, 8)["selected_count"] == "All 8 leagues"
    assert league_labels(5, 8)["selected_count"] == "{num_selected} leagues selected"
    assert league_labels(1, 8)["selected_count"] == "1 league selected"
    assert league_labels(3, 8)["select_all"] == "Select all"
    assert league_labels(3, 8)["deselect_all"] == "Clear all"
    app = create_app(data)
    summary = next(v for k, v in app.callback_map.items() if k.startswith("leagues.labels"))
    f = summary["callback"].__wrapped__
    assert f([39], [{"value": 39}, {"value": 288}])["selected_count"] == "1 league selected"


BROWSER_FLOW = """
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = {};
  const views = [['desktop', { viewport: { width: 1400, height: 1000 } }],
                 ['tablet', { viewport: { width: 900, height: 1100 } }],
                 ['phone', devices['iPhone 13']]];
  for (const [name, opts] of views) {
    const p = await (await b.newContext(opts)).newPage();
    const errors = []; p.on('pageerror', e => errors.push(String(e)));
    await p.goto(BASE);
    const sel = name === 'phone' ? '.fx-card' : 'tr.row';
    await p.waitForSelector(sel, { timeout: 20000, state: 'visible' });
    const r = {};
    r.filterOverflow = await p.evaluate(() => {
      const f = document.querySelector('.filters'); return f.scrollWidth - f.clientWidth; });
    if (name === 'desktop') {
      await p.locator('#leagues').click();
      await p.getByText('Clear all').click();
      await p.waitForFunction(() => document.querySelector('#empty').innerText.includes('Select at least one league'));
      r.cleared = true;
      await p.getByText('Select all').click();
      await p.waitForFunction(() => document.querySelectorAll('tr.row').length > 0);
      await p.keyboard.press('Escape');
      r.restored = await p.locator('tr.row').count();
    }
    await p.locator(sel, { hasText: 'Team 1' }).first().click();
    await p.waitForSelector('#lab-home-input');
    const base = parseFloat(await p.locator('#lab-home-input').inputValue());
    const cats = p.locator('.cat-acc');
    for (const [i, v] of [[0, '-0.15'], [1, '-0.10']]) {
      await cats.nth(i).locator('summary').click();
      const inp = cats.nth(i).locator('input[type=number]').first();
      await inp.fill(v); await inp.press('Tab'); await p.waitForTimeout(700);
    }
    r.afterC = Math.round((parseFloat(await p.locator('#lab-home-input').inputValue()) - base) * 100) / 100;
    await p.locator('#lab-home-input').fill((base - 0.5).toFixed(2));
    await p.locator('#lab-home-input').press('Enter');
    await p.waitForFunction(() => document.querySelectorAll('.breakdown tr')[3].innerText.includes('-0.25'), null, { timeout: 10000 }).catch(() => {});
    r.manualRow = (await p.locator('.breakdown tr').nth(3).innerText()).includes('-0.25');
    await p.locator('#market').click();
    await p.locator('[role=option]', { hasText: 'Over/Under' }).click();
    await p.waitForFunction(() => document.querySelector('#lab-output') && document.querySelector('#lab-output').innerText.includes('Over 2.5'));
    r.persisted = Math.round((parseFloat(await p.locator('#lab-home-input').inputValue()) - base) * 100) / 100;
    r.cards = await p.locator('.prices .price-cell').count();
    await p.locator('#lab-reset').click();
    await p.waitForFunction(() => document.querySelector('#lab-output').innerText.includes('Showing the model baseline'));
    r.reset = parseFloat(await p.locator('#lab-home-input').inputValue()) === base;
    r.overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    r.errors = errors.length;
    out[name] = r;
  }
  console.log(JSON.stringify(out));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node not available")
def test_browser_filters_and_section_c_d_flow(data):
    import subprocess
    import threading
    import time

    from werkzeug.serving import make_server

    from .test_app import _free_port

    if subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
        pytest.skip("playwright for node not available")
    port = _free_port()
    server = make_server("127.0.0.1", port, create_app(data).server, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        time.sleep(0.5)
        script = f"const BASE = 'http://127.0.0.1:{port}/';\n" + BROWSER_FLOW
        res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=240)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["desktop"]["cleared"] and out["desktop"]["restored"] > 0
        for name in ("desktop", "tablet", "phone"):
            r = out[name]
            assert r["afterC"] == -0.25, (name, r)  # -0.15 + -0.10 from Section C
            assert r["manualRow"], name  # a direct final edit derives the manual adjustment
            assert r["persisted"] == -0.5, name  # kept across a market switch
            assert r["cards"] == 2, name  # Over/Under: two bookmaker cards
            assert r["reset"], name
            assert r["overflow"] <= 0 and r["filterOverflow"] <= 0, name
            assert r["errors"] == 0, name
    finally:
        server.shutdown()
