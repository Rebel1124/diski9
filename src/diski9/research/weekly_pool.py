"""D-29 weekly research pool collection (Phase 6C.0).

Research only. Each Friday morning (D-11 revision) a complete fixture and odds
snapshot of the coming weekend is captured for all eight leagues; results are
collected daily until every fixture is final under ``settle/v1``. Everything is
written as files under ``research/weekly_pools/<round_code>/`` (committed to the
``research/weekly-pools`` branch by the scheduled job), never to a competition
database.

Reproducibility: a capture stores the raw API data it used (window fixtures, odds
pages trimmed to the three Diski 9 markets, rate-limit headers) and the frozen Goal
Model 1.0 payloads. The normalised pool is *always* built from those files by
:func:`build_pool_from_raw`, using the production round-sheet code
(``challenge.roundsheet.build_live_snapshot``: strict consensus, freshness,
margin removal) in a scratch SQLite file, so ``replay`` reproduces the same
fingerprint offline.

Isolation: the working database is a separate SQLite file; any other URL (the
production football store, PostgreSQL, ...) is refused.

Nothing is invented: missing odds stay missing, unresolved fixtures stay pending,
and the provider's receipt time is recorded as such (the provider gives no match
completion time).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, create_engine

from diski9.api_football import ApiFootballClient
from diski9.api_football.client import ApiResponse
from diski9.api_football.errors import ApiFootballError
from diski9.leagues import COMPETITIONS, CURRENT_SEASON, odds_competitions

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STORE_DIR = PROJECT_ROOT / "research" / "weekly_pools"
DEFAULT_DB_URL = f"sqlite:///{PROJECT_ROOT / 'data' / 'research_weekly.sqlite'}"
PRODUCTION_DB = (PROJECT_ROOT / "data" / "diski9.sqlite").resolve()

COLLECTOR_VERSION = "weekly-pool/1"
RULES_VERSION = "settle/v1"
SAST = ZoneInfo("Africa/Johannesburg")
DEADLINE_BUFFER = timedelta(minutes=15)  # D-06
SETTLE_CUTOFF = timedelta(hours=48)  # D-08
ON_TIME_BEFORE = time(12, 0)  # capture counts as on time before 12:00 SAST Friday
IDS_PER_REQUEST = 20  # API-Football ``fixtures?ids=`` limit
TARGET_QUALIFYING = 8  # capture stops here (D-29 needs six to eight qualifying pools)

Log = Callable[[str], None]


# ------------------------------------------------------------------ helpers
class IsolationError(RuntimeError):
    """The collector was pointed at a database it must not touch."""


def guard_research_url(url: str) -> str:
    """Accept only a SQLite research file (or an in-memory database for tests)."""
    if not url.startswith("sqlite:///"):
        raise IsolationError(f"research collection only uses a SQLite research file, not {url!r}")
    path = url.removeprefix("sqlite:///")
    if path not in ("", ":memory:") and Path(path).resolve() == PRODUCTION_DB:
        raise IsolationError("research collection must not use the production football store")
    return url


def _dump_gz(path: Path, obj: Any) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"), sort_keys=True)


def _load_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", "utf-8")


def _read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def sha256_file(path: Path) -> str:
    """Hash of the decoded content (gzip headers carry a timestamp)."""
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return hashlib.sha256(data).hexdigest()


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts).astimezone(UTC) if ts else None


# ------------------------------------------------------------------ round window
@dataclass(frozen=True)
class RoundWindow:
    code: str  # ISO week of the Friday, e.g. "2026-W48"
    start: datetime  # Friday 00:00 UTC
    end: datetime  # Tuesday 00:00 UTC (exclusive): the weekend window of FR-R1
    capture_day: date  # scheduled capture day: the Friday itself (D-11 revision)


def round_window(at: datetime) -> RoundWindow:
    """The weekend round a capture at ``at`` belongs to (the coming Friday to Monday)."""
    d = at.astimezone(UTC).date()
    friday = d + timedelta(days=(4 - d.weekday()) % 7)
    iso = friday.isocalendar()
    start = datetime.combine(friday, time(0), UTC)
    return RoundWindow(f"{iso.year}-W{iso.week:02d}", start, start + timedelta(days=4), friday)


def timeliness(at: datetime, window: RoundWindow) -> str:
    local = at.astimezone(SAST)
    on_time = local.date() < window.capture_day or (
        local.date() == window.capture_day and local.time() < ON_TIME_BEFORE
    )
    return "on_time" if on_time else "late"


# ------------------------------------------------------------------ recording client
@dataclass
class RecordingClient(ApiFootballClient):
    """API client that keeps every successful response page for the raw record."""

    records: list[ApiResponse] = field(default_factory=list)

    def get(self, endpoint, params=None):  # type: ignore[override]
        resp = super().get(endpoint, params)
        self.records.append(resp)
        return resp


def _slim_fixture(item: dict[str, Any]) -> dict[str, Any]:
    """The fixture fields the pool and settlement need (nothing personal exists)."""
    fx = item.get("fixture") or {}
    return {
        "fixture": {
            k: fx.get(k) for k in ("id", "date", "timestamp", "timezone", "periods", "status")
        }
        | {"venue": fx.get("venue")},
        "league": {k: (item.get("league") or {}).get(k) for k in ("id", "season", "round")},
        "teams": item.get("teams"),
        "goals": item.get("goals"),
        "score": item.get("score"),
    }


# ------------------------------------------------------------------ capture
@dataclass
class CaptureResult:
    round_code: str
    status: str  # complete | partial | already_captured | after_deadline
    attempt: str | None = None
    requests: int = 0
    daily_remaining: int | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        s = self.summary
        return (
            f"{self.round_code} capture {self.status}: fixtures {s.get('window_fixtures', 0)}, "
            f"eligible fixtures {s.get('eligible_fixtures', 0)} in "
            f"{s.get('eligible_leagues', 0)} leagues, outcomes {s.get('eligible_outcomes', 0)}, "
            f"opens {s.get('opens')}, requests {self.requests}, "
            f"remaining {self.daily_remaining}, errors {s.get('errors') or 'none'}"
        )


def _ensure_history(engine: Engine, client: ApiFootballClient, log: Log) -> str:
    """Bring the research database up to date (setup once per fresh file, then refresh)."""
    from diski9 import workflow
    from diski9.db import upgrade

    upgrade(str(engine.url.render_as_string(hide_password=False)))
    if workflow.missing_requirements(engine):
        workflow.setup(engine, client, with_odds=False, days=7, log=log, migrate=False)
        return "setup"
    workflow.refresh(engine, client, with_odds=False, days=7, log=log)
    return "refresh"


def capture(
    client: RecordingClient,
    *,
    db_url: str = DEFAULT_DB_URL,
    store: Path = STORE_DIR,
    now: datetime | None = None,
    log: Log = print,
) -> CaptureResult:
    """Capture the coming weekend's pool. Idempotent per round: a complete capture is
    never repeated, and a later attempt cannot replace it."""
    from diski9.db import make_engine
    from diski9.screener import cache

    now = (now or datetime.now(UTC)).astimezone(UTC)
    window = round_window(now)
    round_dir = store / window.code
    manifest = _read_json(round_dir / "manifest.json", {})
    if manifest.get("accepted_status") == "complete":
        return CaptureResult(window.code, "already_captured", manifest.get("accepted_attempt"))
    deadline = _parse(manifest.get("deadline"))
    if deadline and now >= deadline:
        return CaptureResult(window.code, "after_deadline")

    guard_research_url(db_url)
    engine = make_engine(db_url)
    errors: dict[str, str] = {}
    try:
        history = _ensure_history(engine, client, log)
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for the run report
        errors["history"] = repr(exc)[:300]
        _append_run(
            store,
            {
                "run_at": _iso(now),
                "round": window.code,
                "step": "capture",
                "status": "failed",
                "errors": errors,
                "requests": client.quota_requests_made,
            },
        )
        raise

    # window fixtures from the recorded season responses (one per league)
    fixture_items: list[dict] = []
    leagues_fetched: set[int] = set()
    for resp in client.records:
        if resp.endpoint == "fixtures" and int(resp.params.get("season", 0)) == CURRENT_SEASON:
            leagues_fetched.add(int(resp.params["league"]))
            for item in resp.items:
                kick = datetime.fromtimestamp(item["fixture"]["timestamp"], UTC)
                if window.start <= kick < window.end:
                    fixture_items.append(_slim_fixture(item))
    for cid in COMPETITIONS:
        if cid not in leagues_fetched:
            errors[f"fixtures:{cid}"] = "no current-season fixture response"

    # odds pages for every odds-enabled league (not stored in the research database)
    from diski9.odds.collect import FATAL_ERRORS
    from diski9.odds.monitor import _slim

    odds: dict[str, Any] = {}
    for cid in odds_competitions():
        entry: dict[str, Any] = {"pages": [], "error": None}
        try:
            for page in client.paginate("odds", {"league": cid, "season": CURRENT_SEASON}):
                entry["pages"].append(
                    {
                        "retrieved_at": page.retrieved_at.isoformat(),
                        "paging": [page.paging_current, page.paging_total],
                        "rate_limit": page.rate_limit.__dict__,
                        "items": [_slim(i) for i in page.items],
                    }
                )
        except FATAL_ERRORS as exc:
            entry["error"] = repr(exc)[:300]
            errors[f"odds:{cid}"] = entry["error"]
            odds[str(cid)] = entry
            break
        except ApiFootballError as exc:
            entry["error"] = repr(exc)[:300]
            errors[f"odds:{cid}"] = entry["error"]
        odds[str(cid)] = entry
    for cid in odds_competitions():
        if str(cid) not in odds:
            errors[f"odds:{cid}"] = "skipped after a fatal error"

    ids = {i["fixture"]["id"] for i in fixture_items}
    from diski9.screener.engine import ENGINE_VERSION

    with engine.connect() as conn:
        model = [p for p in cache.cached(conn, "overall") if p["fixture"]["id"] in ids]
    engine.dispose()

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    attempt = f"capture-{stamp}"
    adir = round_dir / attempt
    adir.mkdir(parents=True, exist_ok=False)
    _dump_gz(
        adir / "fixtures.json.gz",
        {"window": [_iso(window.start), _iso(window.end)], "items": fixture_items},
    )
    _dump_gz(adir / "odds.json.gz", {"season": CURRENT_SEASON, "competitions": odds})
    _dump_gz(adir / "model.json.gz", {"engine_version": ENGINE_VERSION, "payloads": model})
    requests = [
        {
            "endpoint": r.endpoint,
            "params": r.params,
            "status": r.status_code,
            "results": r.results,
            "daily_remaining": r.daily_remaining,
            "attempt": r.attempt,
        }
        for r in client.request_log
    ]
    _write_json(adir / "requests.json", {"history_step": history, "requests": requests})

    pool = build_pool_from_raw(adir, window.code)
    status = "partial" if errors else "complete"
    pool["capture"] = {
        "captured_at": _iso(now),
        "timeliness": timeliness(now, window),
        "status": status,
        "errors": errors,
        "collector_version": COLLECTOR_VERSION,
    }
    _write_json(adir / "pool.json", pool)

    late_after_deadline = pool["deadline"] and now >= _parse(pool["deadline"])
    files = {p.name: sha256_file(p) for p in sorted(adir.iterdir())}
    attempts = manifest.get("attempts", []) + [
        {
            "attempt": attempt,
            "status": status,
            "captured_at": _iso(now),
            "timeliness": timeliness(now, window),
            "files": files,
            "requests": client.quota_requests_made,
            "after_deadline": bool(late_after_deadline),
        }
    ]
    manifest.update(
        {
            "round": window.code,
            "window": [_iso(window.start), _iso(window.end)],
            "attempts": attempts,
            "collector_version": COLLECTOR_VERSION,
            "rules_version": RULES_VERSION,
            "config_version": pool["config_version"],
            "model": pool["model"],
        }
    )
    if late_after_deadline:
        final_status = "after_deadline"
    elif manifest.get("accepted_status") != "complete":
        manifest.update(
            {
                "accepted_attempt": attempt,
                "accepted_status": status,
                "deadline": pool["deadline"],
                "settle_cutoff": pool["settle_cutoff"],
                "fingerprint": pool["fingerprint"],
                "state": "open",
            }
        )
        final_status = status
    else:  # pragma: no cover - excluded by the early return
        final_status = "already_captured"
    _write_json(round_dir / "manifest.json", manifest)

    result = CaptureResult(
        window.code,
        final_status,
        attempt,
        client.quota_requests_made,
        client.last_rate_limit.daily_remaining,
        {
            "window_fixtures": len(fixture_items),
            "eligible_fixtures": pool["opening"]["eligible_fixtures"],
            "eligible_leagues": pool["opening"]["eligible_leagues"],
            "eligible_outcomes": pool["opening"]["eligible_outcomes"],
            "opens": pool["opening"]["opens"],
            "errors": errors,
        },
    )
    _append_run(
        store,
        {
            "run_at": _iso(now),
            "round": window.code,
            "step": "capture",
            "status": final_status,
            "attempt": attempt,
            "requests": result.requests,
            "daily_remaining": result.daily_remaining,
            "errors": errors,
            "summary": result.summary,
        },
    )
    return result


def _append_run(store: Path, row: dict[str, Any]) -> None:
    store.mkdir(parents=True, exist_ok=True)
    with (store / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


# ------------------------------------------------------------------ pool builder
def build_pool_from_raw(attempt_dir: Path, round_code: str) -> dict[str, Any]:
    """Normalised pool from the raw files only (capture and replay share this)."""
    from diski9.challenge.config import DEFAULT_CONFIG
    from diski9.challenge.roundsheet import build_live_snapshot
    from diski9.challenge.structured import assess_outcome
    from diski9.db import upgrade
    from diski9.db.schema import screener_results
    from diski9.ingestion.fixtures import store_fixtures
    from diski9.ingestion.reference import sync_bookmakers
    from diski9.odds.collect import OddsPage, reconcile_pages
    from diski9.screener.engine import ENGINE_VERSION

    fx = _load_gz(attempt_dir / "fixtures.json.gz")
    odds = _load_gz(attempt_dir / "odds.json.gz")
    model = _load_gz(attempt_dir / "model.json.gz")
    if model["engine_version"] != ENGINE_VERSION:
        raise RuntimeError(
            f"captured with engine {model['engine_version']}, running {ENGINE_VERSION}: "
            "replay with the commit recorded in the manifest"
        )
    start, end = (_parse(t) for t in fx["window"])
    retrieved = [
        _parse(p["retrieved_at"]) for c in odds["competitions"].values() for p in c["pages"]
    ]
    as_of = max(retrieved) if retrieved else start
    names = {cid: c.name for cid, c in COMPETITIONS.items()}

    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp) / 'replay.sqlite'}"
        upgrade(url)
        scratch = create_engine(url)  # no foreign-key pragma: reference rows are not needed
        with scratch.begin() as conn:
            store_fixtures(conn, fx["items"], clock=lambda: as_of)
            for cid, entry in odds["competitions"].items():
                pages = [
                    OddsPage(_parse(p["retrieved_at"]), p["items"], p["paging"][0], p["paging"][1])
                    for p in entry["pages"]
                ]
                if pages:
                    reconcile_pages(
                        conn, int(cid), int(odds["season"]), pages, clock=lambda t=as_of: t
                    )
            sync_bookmakers(conn, None, clock=lambda: as_of)
            for p in model["payloads"]:
                conn.execute(
                    screener_results.insert().values(
                        fixture_id=p["fixture"]["id"],
                        basis="overall",
                        engine_version=ENGINE_VERSION,
                        as_of=as_of,
                        cutoff=as_of,
                        calculated_at=as_of,
                        verified_at=as_of,
                        inputs_hash="replay",
                        limited_data=False,
                        payload=json.dumps(p),
                    )
                )
        snap = build_live_snapshot(scratch, as_of, start, end, round_code, names)
        scratch.dispose()

    report = snap.opening_report(DEFAULT_CONFIG)
    assessed = {o.key: assess_outcome(o, snap.snapshot_at, DEFAULT_CONFIG) for o in snap.outcomes}
    model_ids = {
        p["fixture"]["id"]
        for p in model["payloads"]
        if (p.get("goal_model") or {}).get("available")
    }
    odds_ids: dict[int, set[int]] = {}
    for cid, entry in odds["competitions"].items():
        odds_ids[int(cid)] = {i["fixture"]["id"] for p in entry["pages"] for i in p["items"]}
    coverage = {}
    for cid in COMPETITIONS:
        in_window = [i for i in fx["items"] if i["league"]["id"] == cid]
        ids = {i["fixture"]["id"] for i in in_window}
        coverage[str(cid)] = {
            "league": names[cid],
            "window_fixtures": len(ids),
            "with_model": len(ids & model_ids),
            "with_odds": len(ids & odds_ids.get(cid, set())),
            "eligible_fixtures": len(
                {f.fixture_id for f in snap.fixtures if f.league_id == cid}
                & {a.outcome.fixture_id for a in assessed.values() if a.eligible}
            ),
            "odds_error": (odds["competitions"].get(str(cid)) or {}).get("error"),
            "odds_fetched": str(cid) in odds["competitions"],
        }
    sheet_kickoffs = [f.kickoff for f in snap.fixtures]
    return {
        "round": round_code,
        "kind": "research_pool",
        "as_of": _iso(snap.snapshot_at),
        "window": [_iso(start), _iso(end)],
        "config_version": snap.config_version,
        "rules_version": RULES_VERSION,
        "model": {"engine_version": model["engine_version"], "goal_model": "1.0"},
        "fingerprint": snap.fingerprint,
        "deadline": _iso(snap.deadline),
        "settle_cutoff": _iso(max(sheet_kickoffs) + SETTLE_CUTOFF) if sheet_kickoffs else None,
        "opening": {
            "eligible_outcomes": report.eligible_outcomes,
            "eligible_outcomes_by_bucket": report.eligible_outcomes_by_bucket,
            "eligible_fixtures": report.eligible_fixtures,
            "eligible_leagues": report.eligible_leagues,
            "portfolio_feasible": report.portfolio_feasible,
            "checks": report.checks,
            "opens": report.opens,
        },
        "coverage": coverage,
        "diagnostics": snap.diagnostics,
        "fixtures": [
            {
                "fixture_id": f.fixture_id,
                "league_id": f.league_id,
                "home": f.home,
                "away": f.away,
                "kickoff": _iso(f.kickoff),
                "estimated_goals": list(f.estimated_goals) if f.estimated_goals else None,
            }
            for f in snap.fixtures
        ],
        "outcomes": [
            {
                "fixture_id": o.fixture_id,
                "market": str(o.market),
                "outcome": str(o.outcome),
                "market_probability": o.market_probability,
                "odds": str(o.reference_odds),
                "model_probability": o.model_probability,
                "bookmaker_groups": o.bookmaker_groups,
                "latest_observation_at": _iso(o.latest_observation_at),
                "bucket": assessed[o.key].bucket,
                "eligible": assessed[o.key].eligible,
            }
            for o in snap.outcomes
        ],
    }


def replay(round_dir: Path) -> dict[str, Any]:
    """Rebuild the accepted pool from its raw files and compare it with the stored one."""
    manifest = _read_json(round_dir / "manifest.json")
    if not manifest or not manifest.get("accepted_attempt"):
        raise FileNotFoundError(f"no accepted capture in {round_dir}")
    adir = round_dir / manifest["accepted_attempt"]
    stored = _read_json(adir / "pool.json")
    rebuilt = json.loads(json.dumps(build_pool_from_raw(adir, manifest["round"]), default=str))
    accepted = next(a for a in manifest["attempts"] if a["attempt"] == manifest["accepted_attempt"])
    hashes = {
        n: sha256_file(adir / n) == h for n, h in accepted["files"].items() if n != "pool.json"
    }
    stored_core = {k: v for k, v in stored.items() if k != "capture"}
    return {
        "round": manifest["round"],
        "fingerprint_matches": rebuilt["fingerprint"] == stored["fingerprint"],
        "pool_matches": rebuilt == stored_core,
        "raw_hashes_match": all(hashes.values()) and bool(hashes),
    }


# ------------------------------------------------------------------ settle/v1 (research)
FINAL_PLAYED = frozenset({"FT", "AET", "PEN"})
VOID_FINAL = frozenset({"CANC", "AWD", "WO"})
INTERRUPTED = frozenset({"ABD", "SUSP", "INT"})
IN_PLAY = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE"})
NOT_STARTED = frozenset({"TBD", "NS"})
KNOWN = FINAL_PLAYED | VOID_FINAL | INTERRUPTED | IN_PLAY | NOT_STARTED | {"PST"}


@dataclass(frozen=True)
class FixtureVerdict:
    state: str  # settle | void | pending
    code: str | None = None  # V1..V4 for voids
    score: tuple[int, int] | None = None
    alert: str | None = None


def fixture_verdict(
    observations: list[dict[str, Any]], deadline: datetime, cutoff: datetime, now: datetime
) -> FixtureVerdict:
    """``settle/v1`` (docs/product/weekly_challenge_settle_v1.md), research version.

    Observations are slim result records ordered by ``observed_at``; the latest one
    decides, except that any evidence of a start before the deadline voids (V3)."""
    if not observations:
        return (
            FixtureVerdict("void", "V1", alert="no result observation")
            if now > cutoff
            else FixtureVerdict("pending")
        )
    for o in observations:
        sched = _parse(o.get("kickoff"))
        actual = _parse(o.get("actual_kickoff"))
        seen = _parse(o["observed_at"])
        if (
            (sched and sched < deadline)
            or (actual and actual < deadline)
            or (seen < deadline and o["status"] in IN_PLAY | FINAL_PLAYED)
        ):
            return FixtureVerdict("void", "V3")
    last = observations[-1]
    status = last["status"]
    if status in VOID_FINAL:
        return FixtureVerdict("void", "V2")
    kickoff = _parse(last.get("actual_kickoff")) or _parse(last.get("kickoff"))
    if status in FINAL_PLAYED:
        if last.get("ft_home") is None or last.get("ft_away") is None:
            return FixtureVerdict("pending", alert="final status without a 90-minute score")
        if kickoff and kickoff <= cutoff:
            return FixtureVerdict("settle", score=(int(last["ft_home"]), int(last["ft_away"])))
    if now > cutoff:
        if status == "PST" or (kickoff and kickoff > cutoff):
            return FixtureVerdict("void", "V1")
        if status in INTERRUPTED:
            return FixtureVerdict("void", "V4")
        return FixtureVerdict("void", "V1", alert=f"unresolved status {status} after the cutoff")
    alert = None if status in KNOWN else f"unknown status {status}"
    return FixtureVerdict("pending", alert=alert)


def outcome_wins(market: str, outcome: str, home: int, away: int) -> bool:
    if market == "1X2":
        return {"HOME": home > away, "DRAW": home == away, "AWAY": home < away}[outcome]
    if market == "BTTS":
        both = home >= 1 and away >= 1
        return both if outcome == "BTTS_YES" else not both
    if market == "OU25":
        over = home + away >= 3
        return over if outcome == "OVER_2_5" else not over
    raise ValueError(f"unknown market {market}")


def slim_result(item: dict[str, Any], observed_at: datetime) -> dict[str, Any]:
    fx = item.get("fixture") or {}
    periods = fx.get("periods") or {}
    ft = (item.get("score") or {}).get("fulltime") or {}
    first = periods.get("first")
    return {
        "fixture_id": fx.get("id"),
        "observed_at": _iso(observed_at),  # provider result-receipt time, not completion
        "status": (fx.get("status") or {}).get("short"),
        "status_long": (fx.get("status") or {}).get("long"),
        "kickoff": _iso(datetime.fromtimestamp(fx["timestamp"], UTC))
        if fx.get("timestamp")
        else None,
        "actual_kickoff": _iso(datetime.fromtimestamp(first, UTC)) if first else None,
        "ft_home": ft.get("home"),
        "ft_away": ft.get("away"),
    }


def _content_key(obs: dict[str, Any]) -> str:
    core = {k: v for k, v in obs.items() if k != "observed_at"}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def _load_results(path: Path) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                out.setdefault(int(o["fixture_id"]), []).append(o)
    return out


def _window_ids(round_dir: Path, manifest: dict[str, Any]) -> list[int]:
    fx = _load_gz(round_dir / manifest["accepted_attempt"] / "fixtures.json.gz")
    return sorted({int(i["fixture"]["id"]) for i in fx["items"]})


def open_rounds(store: Path) -> list[Path]:
    if not store.exists():
        return []
    return sorted(
        d
        for d in store.iterdir()
        if d.is_dir() and (_read_json(d / "manifest.json", {}) or {}).get("state") == "open"
    )


def collect_results(
    client: ApiFootballClient,
    *,
    store: Path = STORE_DIR,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch results for every open pool whose window has started; append only changed
    observations; recompute verdicts; close pools whose fixtures are all final."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    reports = []
    for round_dir in open_rounds(store):
        manifest = _read_json(round_dir / "manifest.json")
        start = _parse(manifest["window"][0])
        if now < start:
            reports.append({"round": manifest["round"], "status": "not_started"})
            continue
        ids = _window_ids(round_dir, manifest)
        results_path = round_dir / "results.jsonl"
        history = _load_results(results_path)
        cutoff = _parse(manifest["settle_cutoff"]) if manifest.get("settle_cutoff") else None
        deadline = _parse(manifest["deadline"]) if manifest.get("deadline") else None
        before = client.quota_requests_made
        new_rows, errors = [], []
        unresolved = [
            i
            for i in ids
            if not history.get(i)
            or not (cutoff and deadline)
            or fixture_verdict(history[i], deadline, cutoff, now).state == "pending"
        ]
        for k in range(0, len(unresolved), IDS_PER_REQUEST):
            chunk = unresolved[k : k + IDS_PER_REQUEST]
            try:
                resp = client.get("fixtures", {"ids": "-".join(str(i) for i in chunk)})
            except ApiFootballError as exc:
                errors.append(repr(exc)[:300])
                continue
            for item in resp.items:
                obs = slim_result(item, resp.retrieved_at)
                prev = history.get(int(obs["fixture_id"]))
                if prev and _content_key(prev[-1]) == _content_key(obs):
                    continue  # repeated delivery: nothing new
                history.setdefault(int(obs["fixture_id"]), []).append(obs)
                new_rows.append(obs)
        if new_rows:
            with results_path.open("a", encoding="utf-8") as fh:
                for row in new_rows:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
        verdicts = compute_verdicts(round_dir, manifest, history, now)
        _write_json(round_dir / "verdicts.json", verdicts)
        if verdicts["closed"]:
            manifest["state"] = "closed"
            manifest["closed_at"] = _iso(now)
            _write_json(round_dir / "manifest.json", manifest)
        rep = {
            "round": manifest["round"],
            "status": "closed" if verdicts["closed"] else "open",
            "requests": client.quota_requests_made - before,
            "new_observations": len(new_rows),
            "pending": verdicts["pending_fixtures"],
            "voids": verdicts["void_codes"],
            "alerts": verdicts["alerts"],
            "errors": errors,
        }
        _append_run(store, {"run_at": _iso(now), "step": "results", **rep})
        reports.append(rep)
    return reports


def compute_verdicts(
    round_dir: Path, manifest: dict[str, Any], history: dict[int, list[dict]], now: datetime
) -> dict[str, Any]:
    pool = _read_json(round_dir / manifest["accepted_attempt"] / "pool.json")
    deadline, cutoff = _parse(pool["deadline"]), _parse(pool["settle_cutoff"])
    fixtures, alerts = {}, []
    sheet = {f["fixture_id"] for f in pool["fixtures"]}
    for fid in _window_ids(round_dir, manifest):
        if deadline is None or cutoff is None:
            v = FixtureVerdict("pending", alert="pool has no eligible fixtures")
        else:
            v = fixture_verdict(history.get(fid, []), deadline, cutoff, now)
        fixtures[str(fid)] = {
            "state": v.state,
            "code": v.code,
            "score": list(v.score) if v.score else None,
            "on_round_sheet": fid in sheet,
        }
        if v.alert:
            alerts.append({"fixture_id": fid, "alert": v.alert})
    outcomes = []
    for o in pool["outcomes"]:
        f = fixtures[str(o["fixture_id"])]
        verdict = (
            ("won" if outcome_wins(o["market"], o["outcome"], *f["score"]) else "lost")
            if f["state"] == "settle"
            else f["state"]
        )
        outcomes.append(
            {
                "fixture_id": o["fixture_id"],
                "market": o["market"],
                "outcome": o["outcome"],
                "verdict": verdict,
                "void_code": f["code"],
            }
        )
    sheet_states = [fixtures[str(fid)] for fid in sheet]
    pending = sorted(
        int(k) for k, f in fixtures.items() if f["on_round_sheet"] and f["state"] == "pending"
    )
    return {
        "round": manifest["round"],
        "rules_version": RULES_VERSION,
        "evaluated_at": _iso(now),
        "observed": "actual provider results (not simulated)",
        "fixtures": fixtures,
        "outcomes": outcomes,
        "pending_fixtures": pending,
        "void_codes": dict(Counter(f["code"] for f in sheet_states if f["state"] == "void")),
        "alerts": alerts,
        "closed": bool(sheet) and not pending,
    }


# ------------------------------------------------------------------ report
def qualifies(manifest: dict[str, Any], pool: dict[str, Any] | None) -> bool:
    if not pool or manifest.get("accepted_status") != "complete":
        return False
    return manifest.get("state") == "closed" and bool(pool["opening"]["opens"])


def report(store: Path = STORE_DIR, now: datetime | None = None) -> dict[str, Any]:
    """Status of the collection: qualifying and non-qualifying pools, observed voids,
    coverage gaps and API use. Missing weeks are listed as gaps, never filled in."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    rounds = []
    dirs = sorted(d for d in store.iterdir() if d.is_dir()) if store.exists() else []
    for d in dirs:
        m = _read_json(d / "manifest.json", {})
        if not m.get("accepted_attempt"):
            rounds.append({"round": d.name, "status": "no accepted capture"})
            continue
        pool = _read_json(d / m["accepted_attempt"] / "pool.json")
        verdicts = _read_json(d / "verdicts.json", {})
        attempt = next(a for a in m["attempts"] if a["attempt"] == m["accepted_attempt"])
        rounds.append(
            {
                "round": m["round"],
                "capture_status": m["accepted_status"],
                "timeliness": attempt["timeliness"],
                "state": m.get("state"),
                "qualifying": qualifies(m, pool),
                "opens": pool["opening"]["opens"],
                "eligible_fixtures": pool["opening"]["eligible_fixtures"],
                "eligible_leagues": pool["opening"]["eligible_leagues"],
                "eligible_by_bucket": pool["opening"]["eligible_outcomes_by_bucket"],
                "leagues_without_eligible_fixtures": [
                    c["league"] for c in pool["coverage"].values() if not c["eligible_fixtures"]
                ],
                "observed_void_codes": verdicts.get("void_codes", {}),
                "pending_fixtures": verdicts.get("pending_fixtures", []),
                "capture_errors": pool["capture"]["errors"],
                "incomplete_reason": m.get("incomplete_reason"),
            }
        )
    captured = {r["round"] for r in rounds}
    gaps = []
    if rounds:
        first = min(datetime.strptime(r["round"] + "-5", "%G-W%V-%u") for r in rounds)
        week = first.replace(tzinfo=UTC)
        while week < now:  # a week counts as missing once its capture day has begun
            code = round_window(week).code
            if code not in captured:
                gaps.append(code)
            week += timedelta(days=7)
    requests = (
        sum(
            json.loads(line).get("requests") or 0
            for line in (store / "runs.jsonl").read_text("utf-8").splitlines()
            if line.strip()
        )
        if (store / "runs.jsonl").exists()
        else 0
    )
    qualifying = sum(r.get("qualifying", False) for r in rounds)
    still_open = [r["round"] for r in rounds if r.get("state") == "open"]
    return {
        "generated_at": _iso(now),
        "qualifying_pools": qualifying,
        "target": "6 to 8 qualifying pools",
        # capture stops at the target; results continue until no pool is open, so the
        # final qualifying pool is always fully evaluated (or marked incomplete)
        "capture_target_reached": qualifying >= TARGET_QUALIFYING,
        "open_rounds": still_open,
        "incomplete_rounds": [
            {"round": r["round"], "reason": r.get("incomplete_reason")}
            for r in rounds
            if r.get("state") == "incomplete"
        ],
        "collection_finished": qualifying >= TARGET_QUALIFYING and not still_open,
        "rounds": rounds,
        "missing_weeks": gaps,
        "api_requests_recorded": requests,
        "observed_vs_simulated": (
            "All void counts above are observed provider results. Simulated cancellation "
            "scenarios are produced separately by the D-29 validation report and are "
            "never mixed into these figures."
        ),
    }


def mark_incomplete(
    store: Path, round_code: str, reason: str, now: datetime | None = None
) -> dict[str, Any]:
    """Record that an open pool's results could not be completed (used only when the
    collection reaches its hard end date). All data is kept; pending fixtures stay
    listed as pending; the pool never counts as qualifying."""
    if not reason.strip():
        raise ValueError("a reason is required")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    path = store / round_code / "manifest.json"
    manifest = _read_json(path)
    if not manifest or manifest.get("state") != "open":
        raise ValueError(f"{round_code} is not an open pool")
    manifest.update(
        {"state": "incomplete", "incomplete_reason": reason, "incomplete_at": _iso(now)}
    )
    _write_json(path, manifest)
    row = {"run_at": _iso(now), "step": "mark_incomplete", "round": round_code, "reason": reason}
    _append_run(store, row)
    return row


def summarise(results: Iterable[dict[str, Any]]) -> str:
    return (
        "; ".join(
            f"{r['round']} {r['status']}"
            + (
                f" (requests {r.get('requests', 0)}, new {r.get('new_observations', 0)}, "
                f"pending {len(r.get('pending', []))}, voids {r.get('voids') or {}})"
                if r["status"] != "not_started"
                else ""
            )
            for r in results
        )
        or "no open pools; nothing collected"
    )
