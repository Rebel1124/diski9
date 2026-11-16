# ruff: noqa: F811  (pytest fixtures imported from test_app are used as arguments)
"""Engine 3.0: The Match Lab, cross-league support, UEFA exclusion, forecast
snapshots and calibration monitoring."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text, update

from diski9.app import ScreenerData, create_app
from diski9.app.app import _parse_goals, lab_update
from diski9.app.data import LEAGUE_SHORT
from diski9.app.lab import lab_outputs, pp, render_detail, slider_max
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
    base = r["goal_model"]["estimated_goals"]
    a = lab_update(r, "lab-home-slider", {"home_slider": 2.05}, None)
    assert a == {"home": 2.05, "away": round(base["away"], 2)}
    b = lab_update(r, "lab-away-input", {"away_input": "0.8"}, a)
    assert b == {"home": 2.05, "away": 0.8}
    for bad in ("x", -1, 11, float("nan"), None):
        assert lab_update(r, "lab-away-input", {"away_input": bad}, b) == b  # ignored
    assert lab_update(r, "lab-reset", {}, b) is None
    back = lab_update(r, "lab-home-input", {"home_input": round(base["home"], 2)}, a)
    assert back is None  # back at the baseline: no adjustment remains
    assert _parse_goals("1.234") == 1.23 and _parse_goals("10.5") is None


def test_adjustment_recalculates_all_seven_and_never_touches_baseline(data):
    r = _result(data)
    before = copy.deepcopy(r)
    adj = {"home": 1.55, "away": 1.10}
    out, compare = lab_outputs(r, "1X2", data.detail(EPL_FIX)[1], adj)
    mine = gm.markets(1.55, 1.10)
    t = _text(out)
    for key in ("home", "draw", "away", "btts_yes", "btts_no", "over", "under"):
        assert f"{mine[key] * 100:.1f}%" in t  # selected market + "All markets"
    b = r["goal_model"]["probabilities"]
    assert pp(mine["home"] - b["home"]) in t
    assert "Your estimate" in t and "Yours" in _text(compare)
    assert r == before  # the cached baseline is never modified
    d = render_detail(r, *data.detail(EPL_FIX)[1:], "1X2", data, adj)
    base_section = _text(d.children[1].children[1])
    assert f"{b['home'] * 100:.1f}%" in base_section  # baseline stays the model's
    assert "Adjusted by you" in _text(d.children[0])


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
    other = {"123": {"home": 9.0, "away": 9.0}}
    _trigger("lab-home-input.value", 2.4)
    out = func(None, 2.4, None, None, 0, EPL_FIX, "BTTS", other)
    store = out[0]
    assert store["123"] == other["123"]  # other fixtures untouched
    assert store[str(EPL_FIX)]["home"] == 2.4 and out[1] == out[2] == 2.4
    assert other == {"123": {"home": 9.0, "away": 9.0}}  # input store not mutated
    # a second user's (empty) store is unaffected: state lives in each browser only
    _trigger("lab-reset.n_clicks")
    out2 = func(None, None, None, None, 1, EPL_FIX, "BTTS", {})
    assert out2[0] == {}
    layout = create_app(data).server.test_client().get("/_dash-layout").get_data(as_text=True)
    assert '"id":"lab-store"' in layout and '"storage_type":"memory"' in layout


def test_market_switch_keeps_adjustment(data):
    app = create_app(data)
    detail = next(v for k, v in app.callback_map.items() if k.startswith("detail.children"))
    func = detail["callback"].__wrapped__
    lab = {str(EPL_FIX): {"home": 2.5, "away": 0.9}}
    for market in ("1X2", "BTTS", "OU25"):
        d = func(EPL_FIX, market, lab)
        sliders = _find(d, lambda c: getattr(c, "id", None) == "lab-home-slider")
        assert sliders[0].value == 2.5
        assert "Adjusted by you" in _text(d)


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
    d = render_detail(r, None, {}, "1X2", data, {"home": 3.0, "away": 1.0})
    t = _text(d)
    assert gm.UEFA_MESSAGE in t and "estimated goals" not in t.replace("Estimated goals are", "")
    assert not _find(d, lambda c: getattr(c, "id", None) == "lab-home-slider")
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
