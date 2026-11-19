"""D-29 weekly research pool collection (Phase 6C.0): offline tests.

The fixture ``tests/fixtures/weekly_pool/2026-W47`` is a real capture made during
pre-activation validation (provider data only; no credentials)."""

from __future__ import annotations

import ast
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from diski9.research import weekly_pool as wp

FIXTURE = Path(__file__).parent / "fixtures" / "weekly_pool" / "2026-W47"
ATTEMPT = "capture-20261119T030540Z"


@pytest.fixture
def store(tmp_path) -> Path:
    s = tmp_path / "pools"
    shutil.copytree(FIXTURE, s / "2026-W47")
    return s


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


# ---------------------------------------------------------------- window and timing
def test_round_window_for_the_first_scheduled_capture():
    w = wp.round_window(_dt("2026-11-26T06:00:00+00:00"))  # Thursday 08:00 SAST
    assert w.code == "2026-W48"
    assert w.start == _dt("2026-11-27T00:00:00+00:00")
    assert w.end == _dt("2026-12-01T00:00:00+00:00")
    assert wp.timeliness(_dt("2026-11-26T06:00:00+00:00"), w) == "on_time"
    assert wp.timeliness(_dt("2026-11-26T10:30:00+00:00"), w) == "late"  # 12:30 SAST


def test_round_window_year_boundary():
    w = wp.round_window(_dt("2026-12-31T06:00:00+00:00"))
    # Friday 1 January 2027 belongs to ISO week 53 of 2026
    assert w.code == "2026-W53" and w.start.date().isoformat() == "2027-01-01"


# ---------------------------------------------------------------- isolation
@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://diski9@localhost/diski9",
        f"sqlite:///{wp.PRODUCTION_DB}",
        "mysql://x",
    ],
)
def test_collector_refuses_non_research_databases(url):
    with pytest.raises(wp.IsolationError):
        wp.guard_research_url(url)


def test_collector_accepts_its_own_sqlite_file(tmp_path):
    url = f"sqlite:///{tmp_path / 'r.sqlite'}"
    assert wp.guard_research_url(url) == url


def test_collector_never_imports_competition_persistence():
    tree = ast.parse(Path(wp.__file__).read_text())
    names = {
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not {m for m in names if m and (m.startswith("diski9.backend") or "psycopg" in m)}


def test_research_command_does_not_open_the_football_store(monkeypatch, tmp_path):
    from diski9 import cli

    def boom(*a, **k):
        raise AssertionError("football-store engine must not be created")

    monkeypatch.setattr(cli, "make_engine", boom)
    assert cli.main(["research-pool", "report", "--store-dir", str(tmp_path)]) == 0


# ---------------------------------------------------------------- reproducibility
def test_replay_reproduces_the_real_capture_offline(store):
    res = wp.replay(store / "2026-W47")
    assert res == {
        "round": "2026-W47",
        "fingerprint_matches": True,
        "pool_matches": True,
        "raw_hashes_match": True,
    }


def test_replay_detects_tampered_raw_data(store):
    adir = store / "2026-W47" / ATTEMPT
    data = wp._load_gz(adir / "odds.json.gz")
    first = next(c for c in data["competitions"].values() if c["pages"])
    first["pages"][0]["items"] = first["pages"][0]["items"][1:]
    wp._dump_gz(adir / "odds.json.gz", data)
    res = wp.replay(store / "2026-W47")
    assert not res["raw_hashes_match"]


def test_pool_uses_existing_rules_and_records_coverage(store):
    pool = json.loads((store / "2026-W47" / ATTEMPT / "pool.json").read_text())
    assert pool["config_version"] == "broad60-432-v1"
    assert pool["rules_version"] == "settle/v1"
    assert set(pool["coverage"]) == {str(c) for c in wp.COMPETITIONS}
    for o in pool["outcomes"]:
        assert o["bookmaker_groups"] >= 3  # strict consensus
        if o["eligible"]:
            assert o["bucket"] in {"A", "B", "C"}
    kick = max(_dt(f["kickoff"]) for f in pool["fixtures"])
    assert _dt(pool["settle_cutoff"]) == kick + timedelta(hours=48)
    earliest = min(_dt(f["kickoff"]) for f in pool["fixtures"])
    assert _dt(pool["deadline"]) == earliest - timedelta(minutes=15)


# ---------------------------------------------------------------- settle/v1 (research)
DEADLINE = _dt("2026-11-20T19:15:00+00:00")
CUTOFF = _dt("2026-11-25T20:00:00+00:00")
AFTER = CUTOFF + timedelta(hours=1)


def obs(
    status,
    *,
    kickoff="2026-11-22T14:00:00+00:00",
    actual=None,
    ft=(None, None),
    seen="2026-11-22T17:00:00+00:00",
):
    return {
        "fixture_id": 1,
        "observed_at": seen,
        "status": status,
        "kickoff": kickoff,
        "actual_kickoff": actual,
        "ft_home": ft[0],
        "ft_away": ft[1],
    }


@pytest.mark.parametrize(
    ("history", "now", "state", "code"),
    [
        ([obs("FT", actual="2026-11-22T14:00:00+00:00", ft=(2, 1))], AFTER, "settle", None),
        ([obs("AET", actual="2026-11-22T14:00:00+00:00", ft=(1, 1))], AFTER, "settle", None),
        ([obs("NS", kickoff="2026-11-20T18:00:00+00:00")], AFTER, "void", "V3"),
        ([obs("1H", seen="2026-11-20T19:00:00+00:00")], AFTER, "void", "V3"),
        ([obs("CANC")], AFTER, "void", "V2"),
        ([obs("AWD", ft=(3, 0))], AFTER, "void", "V2"),
        ([obs("PST")], AFTER, "void", "V1"),
        ([obs("PST")], CUTOFF - timedelta(hours=1), "pending", None),
        ([obs("ABD")], AFTER, "void", "V4"),
        ([obs("SUSP")], AFTER, "void", "V4"),
        ([obs("NS", kickoff="2026-11-26T12:00:00+00:00")], AFTER, "void", "V1"),
        # V5: postponed, then completed by the cutoff
        (
            [
                obs("PST"),
                obs(
                    "FT",
                    kickoff="2026-11-24T18:00:00+00:00",
                    actual="2026-11-24T18:00:00+00:00",
                    ft=(0, 0),
                ),
            ],
            AFTER,
            "settle",
            None,
        ),
        ([], AFTER, "void", "V1"),
        ([], CUTOFF - timedelta(hours=1), "pending", None),
    ],
)
def test_settle_v1_verdicts(history, now, state, code):
    v = wp.fixture_verdict(history, DEADLINE, CUTOFF, now)
    assert (v.state, v.code) == (state, code)


def test_cutoff_boundary_is_inclusive():
    at = CUTOFF.isoformat()
    done = [obs("FT", kickoff=at, actual=at, ft=(1, 0))]
    assert wp.fixture_verdict(done, DEADLINE, CUTOFF, AFTER).state == "settle"
    late = (CUTOFF + timedelta(seconds=1)).isoformat()
    after = [obs("FT", kickoff=late, actual=late, ft=(1, 0))]
    assert wp.fixture_verdict(after, DEADLINE, CUTOFF, AFTER).code == "V1"


def test_missing_score_alerts_instead_of_inventing_a_result():
    v = wp.fixture_verdict([obs("FT", actual="2026-11-22T14:00:00+00:00")], DEADLINE, CUTOFF, AFTER)
    assert v.state == "pending" and "score" in v.alert


def test_conflicting_statuses_latest_observation_decides():
    hist = [
        obs("FT", actual="2026-11-22T14:00:00+00:00", ft=(1, 0)),
        obs("ABD", seen="2026-11-22T18:00:00+00:00"),
    ]
    assert wp.fixture_verdict(hist, DEADLINE, CUTOFF, AFTER).code == "V4"


def test_unknown_status_stays_pending_with_alert():
    v = wp.fixture_verdict([obs("XYZ")], DEADLINE, CUTOFF, CUTOFF - timedelta(hours=1))
    assert v.state == "pending" and "unknown" in v.alert


@pytest.mark.parametrize(
    ("market", "outcome", "score", "wins"),
    [
        ("1X2", "HOME", (2, 1), True),
        ("1X2", "DRAW", (1, 1), True),
        ("1X2", "AWAY", (1, 1), False),
        ("BTTS", "BTTS_YES", (1, 1), True),
        ("BTTS", "BTTS_NO", (2, 0), True),
        ("OU25", "OVER_2_5", (2, 1), True),
        ("OU25", "UNDER_2_5", (2, 1), False),
    ],
)
def test_market_rules(market, outcome, score, wins):
    assert wp.outcome_wins(market, outcome, *score) is wins


# ---------------------------------------------------------------- results collection
class FakeResults:
    """API stand-in serving ``fixtures?ids=`` from a status table."""

    def __init__(self, table: dict[int, dict]):
        items = wp._load_gz(FIXTURE / ATTEMPT / "fixtures.json.gz")["items"]
        self.kickoffs = {i["fixture"]["id"]: i["fixture"]["timestamp"] for i in items}
        self.table = table
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params["ids"].split("-")]
        self.calls.append({"ids": ids})
        items = []
        for i in ids:
            t = self.table.get(i, {})
            items.append(
                {
                    "fixture": {
                        "id": i,
                        "timestamp": t.get("ts", self.kickoffs.get(i)),
                        "periods": {"first": t.get("first")},
                        "status": {"short": t.get("status", "NS"), "long": "x"},
                    },
                    "score": {"fulltime": {"home": t.get("h"), "away": t.get("a")}},
                }
            )
        body = {
            "get": "fixtures",
            "parameters": {},
            "errors": [],
            "results": len(items),
            "paging": {"current": 1, "total": 1},
            "response": items,
        }
        return httpx.Response(200, json=body)

    def client(self):
        return wp.ApiFootballClient(
            transport=httpx.MockTransport(self.handler), sleep=lambda s: None
        )


def _window_ids(store):
    m = json.loads((store / "2026-W47" / "manifest.json").read_text())
    return wp._window_ids(store / "2026-W47", m)


def test_results_not_collected_before_the_window(store):
    fake = FakeResults({})
    out = wp.collect_results(fake.client(), store=store, now=_dt("2026-11-19T07:15:00+00:00"))
    assert out == [{"round": "2026-W47", "status": "not_started"}]
    assert fake.calls == []


def test_repeated_deliveries_create_no_duplicates(store, monkeypatch):
    freeze_client_clock(monkeypatch, _dt("2026-11-21T07:15:00+00:00"))
    fake = FakeResults({})
    now = _dt("2026-11-21T07:15:00+00:00")
    first = wp.collect_results(fake.client(), store=store, now=now)
    again = wp.collect_results(fake.client(), store=store, now=now)
    assert first[0]["new_observations"] == len(_window_ids(store))
    assert again[0]["new_observations"] == 0
    lines = (store / "2026-W47" / "results.jsonl").read_text().splitlines()
    assert len(lines) == len(_window_ids(store))
    assert all(len(c["ids"]) <= wp.IDS_PER_REQUEST for c in fake.calls)


def freeze_client_clock(monkeypatch, at: datetime) -> None:
    """Responses are stamped with the receipt time; make it the simulated 'now'."""
    import diski9.api_football.client as client_mod

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at

    monkeypatch.setattr(client_mod, "datetime", Frozen)


def test_pool_closes_when_every_sheet_fixture_is_final(store, monkeypatch):
    freeze_client_clock(monkeypatch, CUTOFF + timedelta(hours=2))
    pool = json.loads((store / "2026-W47" / ATTEMPT / "pool.json").read_text())
    table = {}
    for f in pool["fixtures"]:
        ts = int(_dt(f["kickoff"]).timestamp())
        table[f["fixture_id"]] = {"status": "FT", "ts": ts, "first": ts, "h": 1, "a": 0}
    postponed = pool["fixtures"][0]["fixture_id"]
    table[postponed] = {"status": "PST", "ts": int(_dt(pool["fixtures"][0]["kickoff"]).timestamp())}
    fake = FakeResults(table)
    out = wp.collect_results(fake.client(), store=store, now=CUTOFF + timedelta(hours=2))
    assert out[0]["status"] == "closed"
    assert out[0]["voids"] == {"V1": 1}
    verdicts = json.loads((store / "2026-W47" / "verdicts.json").read_text())
    assert verdicts["observed"].startswith("actual provider results")
    assert {o["verdict"] for o in verdicts["outcomes"]} <= {"won", "lost", "void"}
    # closed pools are not checked again
    fake.calls.clear()
    assert wp.collect_results(fake.client(), store=store, now=CUTOFF + timedelta(days=1)) == []
    assert fake.calls == []
    rep = wp.report(store, now=CUTOFF + timedelta(days=1))
    assert rep["qualifying_pools"] == 1
    assert rep["rounds"][0]["observed_void_codes"] == {"V1": 1}


def test_unresolved_fixtures_stay_open_and_are_reported(store, monkeypatch):
    freeze_client_clock(monkeypatch, _dt("2026-11-23T07:15:00+00:00"))
    fake = FakeResults({})  # everything still "NS"
    out = wp.collect_results(fake.client(), store=store, now=_dt("2026-11-23T07:15:00+00:00"))
    assert out[0]["status"] == "open" and out[0]["pending"]
    rep = wp.report(store, now=_dt("2026-11-23T08:00:00+00:00"))
    assert rep["qualifying_pools"] == 0
    assert rep["rounds"][0]["pending_fixtures"]


# ---------------------------------------------------------------- capture orchestration
def test_complete_capture_is_never_repeated(store):
    class NoCalls(wp.RecordingClient):
        def get(self, *a, **k):  # pragma: no cover - must not be reached
            raise AssertionError("no API call expected")

    with NoCalls() as client:
        res = wp.capture(
            client, db_url="sqlite:///:memory:", store=store, now=_dt("2026-11-19T08:00:00+00:00")
        )
    assert res.status == "already_captured"


def test_capture_after_the_deadline_is_refused(store):
    m = store / "2026-W47" / "manifest.json"
    data = json.loads(m.read_text())
    data["accepted_status"] = "partial"
    m.write_text(json.dumps(data))
    with wp.RecordingClient() as client:
        res = wp.capture(
            client, db_url="sqlite:///:memory:", store=store, now=_dt("2026-11-20T19:30:00+00:00")
        )
    assert res.status == "after_deadline" and client.request_log == []


def test_missing_weeks_are_reported_not_filled(store):
    rep = wp.report(store, now=_dt("2026-12-11T08:00:00+00:00"))
    assert rep["missing_weeks"] == ["2026-W48", "2026-W49", "2026-W50"]
    assert not (store / "2026-W48").exists()


# ---------------------------------------------------------------- stopping safely
def test_target_reached_does_not_abandon_open_pools(store):
    rep = wp.report(store, now=_dt("2026-11-23T08:00:00+00:00"))
    assert rep["open_rounds"] == ["2026-W47"]
    assert rep["collection_finished"] is False  # an open pool keeps results running


def test_incomplete_pool_is_recorded_explicitly_and_never_qualifies(store):
    with pytest.raises(ValueError):
        wp.mark_incomplete(store, "2026-W47", "   ")
    wp.mark_incomplete(
        store,
        "2026-W47",
        "results unresolved at collection end",
        now=_dt("2027-04-21T08:00:00+00:00"),
    )
    rep = wp.report(store, now=_dt("2027-04-21T09:00:00+00:00"))
    assert rep["open_rounds"] == []
    assert rep["incomplete_rounds"] == [
        {"round": "2026-W47", "reason": "results unresolved at collection end"}
    ]
    assert rep["qualifying_pools"] == 0
    assert wp.open_rounds(store) == []  # results collection no longer touches it
    with pytest.raises(ValueError):
        wp.mark_incomplete(store, "2026-W47", "again")


def test_closed_pool_cannot_be_marked_incomplete(store, monkeypatch):
    m = store / "2026-W47" / "manifest.json"
    data = json.loads(m.read_text())
    data["state"] = "closed"
    m.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        wp.mark_incomplete(store, "2026-W47", "no")
