"""Command-line entry point: ``uv run diski9 <command>``.

All jobs are on-demand; nothing here schedules recurring collection.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from diski9.api_football import ApiFootballClient
from diski9.db import make_engine, upgrade
from diski9.db.schema import fixtures, ingestion_runs
from diski9.ingestion import reference
from diski9.ingestion.fixtures import ingest_fixtures, refresh_venue_classification
from diski9.ingestion.quality import full_report
from diski9.leagues import (
    BACKFILL_SEASONS,
    COMPETITIONS,
    CURRENT_SEASON,
    ODDS_TRIAL_COMPETITIONS,
    odds_competitions,
    screener_competitions,
)
from diski9.odds.collect import collect_odds, summarise_fetch
from diski9.odds.consensus import fixture_consensus, load_bookmakers

log = logging.getLogger("diski9")


def _json(obj) -> str:
    def default(o):
        if isinstance(o, Decimal | datetime):
            return str(o)
        return o.__dict__ if hasattr(o, "__dict__") else str(o)

    return json.dumps(obj, indent=2, default=default)


def _record_failure(engine, job: str, exc: Exception) -> None:
    """Best effort: the database may not be migrated yet."""
    now = datetime.now(UTC)
    try:
        with engine.begin() as conn:
            conn.execute(
                ingestion_runs.insert().values(
                    job=job,
                    started_at=now,
                    finished_at=now,
                    status="failed",
                    error=repr(exc)[:2000],
                )
            )
    except Exception:  # noqa: BLE001 - never mask the original error
        log.debug("could not record failure", exc_info=True)


def cmd_init_db(args, engine) -> None:
    upgrade(str(engine.url))
    print(f"Database at {engine.url} migrated to head")


def cmd_sync_reference(args, engine) -> None:
    with ApiFootballClient.from_settings() as client, engine.begin() as conn:
        reference.sync_competitions(conn, client, args.competitions)
        reference.sync_bookmakers(conn, client)
        n = reference.load_neutral_overrides(conn)
        for cid in args.competitions:
            for season in args.seasons:
                reference.sync_teams(conn, client, cid, season)
        print(f"Reference data synced ({client.quota_requests_made} requests, {n} venue overrides)")


def cmd_ingest_fixtures(args, engine) -> None:
    with ApiFootballClient.from_settings() as client:
        for cid in args.competitions:
            for season in args.seasons:
                with engine.begin() as conn:
                    reference.load_neutral_overrides(conn)
                    reference.load_approved_home_grounds(conn)
                    s = ingest_fixtures(conn, client, cid, season)
                print(
                    f"{cid}/{season}: +{s.inserted} ~{s.updated} ={s.unchanged} "
                    f"venues={s.extra.get('venue_classification')}"
                )
        # Second pass: grounds from every competition-season are now known.
        with engine.begin() as conn:
            for cid in args.competitions:
                for season in args.seasons:
                    refresh_venue_classification(conn, cid, season)
        print(f"API requests: {client.quota_requests_made}")


def cmd_collect_odds(args, engine) -> None:
    """Collect odds league by league (all eight by default). A failure in one league
    is rolled back and reported without stopping the others; quota and
    authentication errors stop the run (later requests would fail the same way)."""
    from diski9.odds.collect import FATAL_ERRORS

    targets = args.competitions or odds_competitions()
    failed: list[int] = []
    with ApiFootballClient.from_settings() as client:
        for cid in targets:
            try:
                with engine.begin() as conn:
                    stats = collect_odds(conn, client, cid, args.season)
            except FATAL_ERRORS as exc:
                print(f"{cid}/{args.season}: STOPPED ({exc!r:.300}); remaining leagues skipped")
                failed.append(cid)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"{cid}/{args.season}: FAILED and rolled back ({exc!r:.300})")
                failed.append(cid)
                continue
            print(f"{cid}/{args.season}: {_json(summarise_fetch(stats))}")
        print(f"API requests: {client.quota_requests_made}")
    if failed:
        raise SystemExit(f"odds collection failed for: {failed}")


def cmd_odds_coverage(args, engine) -> None:
    """Coverage diagnostics from the local database (no API requests)."""
    from diski9.odds.coverage import coverage_report, format_table

    with engine.connect() as conn:
        report = coverage_report(
            conn, datetime.now(UTC), args.competitions, horizon_days=args.horizon_days
        )
    text = _json(report) if args.json else format_table(report)
    if args.out:
        Path(args.out).write_text(_json(report) + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    print(text)


def cmd_quality_report(args, engine) -> None:
    with engine.connect() as conn:
        report = full_report(conn, args.seasons, datetime.now(UTC))
    text = _json(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"Wrote {args.out}")
    else:
        print(text)


def cmd_consensus(args, engine) -> None:
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    with engine.connect() as conn:
        books = load_bookmakers(conn)
        ids = args.fixtures or [
            r.id
            for r in conn.execute(
                select(fixtures.c.id)
                .where(
                    fixtures.c.kickoff_utc > as_of, fixtures.c.competition_id == args.competition
                )
                .order_by(fixtures.c.kickoff_utc)
                .limit(args.limit)
            )
        ]
        for fid in ids:
            result = fixture_consensus(conn, fid, as_of, books=books)
            print(f"fixture {fid}")
            for market, mc in result.items():
                prices = ", ".join(
                    f"{o.value}={oc.consensus_odds}" for o, oc in mc.outcomes.items()
                )
                print(
                    f"  {market.value:5s} sources={mc.sources} eligible={mc.challenge_eligible} "
                    f"{prices} excluded={mc.exclusions}"
                )


def cmd_monitor_odds(args, engine) -> None:
    from diski9.odds.monitor import DEFAULT_DIR, run_monitor

    # The trial keeps its approved scope (EPL + PSL) unless competitions are given.
    targets = args.competitions or list(ODDS_TRIAL_COMPETITIONS)
    until = datetime.fromisoformat(args.until) if args.until else None
    with ApiFootballClient.from_settings() as client:
        summary = run_monitor(
            client, targets, args.season, Path(args.out_dir) if args.out_dir else DEFAULT_DIR, until
        )
    print(_json(summary))


def cmd_analyse_odds_trial(args, engine) -> None:
    """Replay saved monitoring runs into a scratch copy of the database."""
    import shutil
    import tempfile

    from diski9.db.schema import odds_fetches, odds_fixture_observations, odds_quotes
    from diski9.odds.monitor import DEFAULT_DIR, analyse, load_runs, replay

    runs = load_runs(Path(args.out_dir) if args.out_dir else DEFAULT_DIR)
    src = engine.url.database
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "replay.sqlite"
        shutil.copy(src, copy)
        scratch = make_engine(f"sqlite:///{copy}")
        with scratch.begin() as conn:
            for t in (odds_quotes, odds_fixture_observations, odds_fetches):
                conn.execute(t.delete())
            result = replay(conn, runs)
            report = analyse(conn, runs)
        scratch.dispose()
    report["replay_errors"] = result.errors
    text = _json(report)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)


def cmd_screener_refresh(args, engine) -> None:
    from datetime import timedelta

    from diski9.screener import cache

    now = datetime.now(UTC)
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else now
    comps = args.competitions or screener_competitions()
    with engine.begin() as conn:
        ids = args.fixtures or cache.upcoming_fixture_ids(
            conn, comps, as_of, as_of + timedelta(days=args.days)
        )
        counts = cache.refresh(conn, ids, as_of, now)
    print(f"{len(ids)} fixtures: {counts}")


def cmd_screener_show(args, engine) -> None:
    from diski9.api_football.markets import Market, Outcome
    from diski9.screener import cache
    from diski9.screener.rank import rank

    market_of = {
        "kickoff_earliest": (Market.MATCH_RESULT, Outcome.HOME),
        "kickoff_latest": (Market.MATCH_RESULT, Outcome.HOME),
        "home_win": (Market.MATCH_RESULT, Outcome.HOME),
        "draw": (Market.MATCH_RESULT, Outcome.DRAW),
        "away_win": (Market.MATCH_RESULT, Outcome.AWAY),
        "btts_yes": (Market.BTTS, Outcome.BTTS_YES),
        "btts_no": (Market.BTTS, Outcome.BTTS_NO),
        "over": (Market.OVER_UNDER_25, Outcome.OVER_25),
        "under": (Market.OVER_UNDER_25, Outcome.UNDER_25),
    }
    now = datetime.now(UTC)
    with engine.connect() as conn:
        results = cache.cached(conn, "overall")
        if args.competition:
            results = [r for r in results if r["fixture"]["competition_id"] == args.competition]
        ranked = rank(results, args.direction, args.threshold)[: args.limit]
        books = load_bookmakers(conn)
        market, outcome = market_of[args.direction]
        for r in ranked:
            f, g = r["fixture"], r["goal_model"]
            odds = fixture_consensus(conn, f["id"], now, books=books)[market]
            oc = odds.outcomes[outcome]
            price = f"{oc.consensus_odds} ({odds.sources} src)" if oc.consensus_odds else "-"
            if g.get("available"):
                eg, p = g["estimated_goals"], g["probabilities"]
                model = (
                    f"estimated goals {eg['home']:.2f}-{eg['away']:.2f} | "
                    f"H/D/A {p['home']:.1%}/{p['draw']:.1%}/{p['away']:.1%} | "
                    f"BTTS {p['btts_yes']:.1%} | O2.5 {p['over']:.1%}"
                    + (" [Early season]" if g.get("early_season") else "")
                )
            else:
                model = g.get("message", "model unavailable")
            print(
                f"{f['kickoff'][:16]} {f['home']} v {f['away']}: {model} | "
                f"consensus {outcome.value} {price}"
            )


def cmd_model_report(args, engine) -> None:
    """Monthly Goal Model monitoring from official pre-kickoff forecasts (no API)."""
    from diski9.screener.forecasts import report

    now = datetime.now(UTC)
    with engine.connect() as conn:
        rep = report(conn, now)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"model_report_{now:%Y%m%d}.json"
    path.write_text(_json(rep))
    print(f"{rep['official_forecasts']} official forecasts evaluated; report: {path}")
    for g in rep["groups"]:
        if g["competition_id"] == "all":
            flag = " (preliminary)" if g["preliminary"] else ""
            vs = g.get("log_loss_vs_baseline")
            print(
                f"  {g['market']:5} n={g['settled_fixtures']:4} log loss {g['log_loss']:.4f}"
                f" brier {g['brier']:.4f}"
                + (f" vs baseline {vs:+.4f}" if vs is not None else "")
                + flag
            )


def cmd_sync_standings(args, engine) -> None:
    comps = args.competitions or [c.id for c in COMPETITIONS.values() if c.tier == 1]
    with ApiFootballClient.from_settings() as client, engine.begin() as conn:
        for cid in comps:
            s = reference.sync_standings(conn, client, cid, args.season)
            print(f"{cid}/{args.season}: {'new snapshot' if s.inserted else 'unchanged'}")


def cmd_setup(args, engine) -> None:
    """First-time setup on a new computer (safe to re-run)."""
    from diski9 import workflow

    with ApiFootballClient.from_settings() as client:
        res = workflow.setup(
            engine, client, force=args.force, with_odds=args.with_odds, days=args.days
        )
    print(
        f"Setup complete: {len(res.seasons_fetched)} seasons fetched, "
        f"{len(res.seasons_skipped)} already loaded, fixtures +{res.fixtures_inserted} "
        f"~{res.fixtures_updated} ={res.fixtures_unchanged}; API requests {res.requests}. "
        "Start the app with: uv run diski9 serve"
    )


def cmd_refresh_data(args, engine) -> None:
    """Routine incremental refresh after setup: current season, standings, cache."""
    from diski9 import workflow

    with ApiFootballClient.from_settings() as client:
        res = workflow.refresh(
            engine,
            client,
            with_odds=args.with_odds,
            skip_standings=args.skip_standings,
            days=args.days,
        )
    print(f"Refresh complete; API requests {res.requests}")


def cmd_serve(args, engine) -> None:
    from diski9.app import ScreenerData, create_app

    app = create_app(ScreenerData(engine, ttl_seconds=args.ttl, tz=args.tz))
    app.run(host=args.host, port=args.port, debug=args.debug)


def cmd_research_pool(args) -> int:
    """D-29 weekly research collection. Runs without the football-store engine, so a
    failure can never be recorded in (or otherwise touch) the production database."""
    from diski9.research import weekly_pool as wp

    store = Path(args.store_dir) if args.store_dir else wp.STORE_DIR
    now = datetime.fromisoformat(args.now) if args.now else None
    if args.action == "capture":
        url = wp.guard_research_url(args.research_db_url or wp.DEFAULT_DB_URL)
        with wp.RecordingClient.from_settings() as client:
            print(wp.capture(client, db_url=url, store=store, now=now).line())
    elif args.action == "results":
        with ApiFootballClient.from_settings() as client:
            print(wp.summarise(wp.collect_results(client, store=store, now=now)))
    elif args.action == "replay":
        rounds = (
            [store / args.round] if args.round else sorted(d for d in store.iterdir() if d.is_dir())
        )
        bad = 0
        for d in rounds:
            res = wp.replay(d)
            bad += not (
                res["fingerprint_matches"] and res["pool_matches"] and res["raw_hashes_match"]
            )
            print(_json(res))
        return 1 if bad else 0
    elif args.action == "report":
        rep = wp.report(store, now=now)
        text = _json(rep)
        (store / "report.json").write_text(text + "\n", encoding="utf-8")
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="diski9")
    p.add_argument("--database-url", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="apply Alembic migrations").set_defaults(func=cmd_init_db)

    comps = list(COMPETITIONS)
    s = sub.add_parser("sync-reference", help="competitions, seasons, teams, bookmakers")
    s.add_argument("--competitions", type=int, nargs="+", default=comps)
    s.add_argument("--seasons", type=int, nargs="+", default=list(BACKFILL_SEASONS))
    s.set_defaults(func=cmd_sync_reference)

    s = sub.add_parser("ingest-fixtures", help="backfill / update fixtures and results")
    s.add_argument("--competitions", type=int, nargs="+", default=comps)
    s.add_argument("--seasons", type=int, nargs="+", default=[CURRENT_SEASON])
    s.set_defaults(func=cmd_ingest_fixtures)

    s = sub.add_parser("collect-odds", help="one on-demand pre-match odds collection")
    s.add_argument("--competitions", type=int, nargs="+", default=None)
    s.add_argument("--season", type=int, default=CURRENT_SEASON)
    s.set_defaults(func=cmd_collect_odds)

    s = sub.add_parser(
        "odds-coverage", help="odds availability per league from the local database (no API)"
    )
    s.add_argument("--competitions", type=int, nargs="+", default=None)
    s.add_argument("--horizon-days", type=int, default=14)
    s.add_argument("--json", action="store_true", help="print the full JSON report")
    s.add_argument("--out", default=None, help="also write the JSON report to this file")
    s.set_defaults(func=cmd_odds_coverage)

    s = sub.add_parser("quality-report", help="data-quality and exclusion report")
    s.add_argument("--seasons", type=int, nargs="+", default=list(BACKFILL_SEASONS))
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_quality_report)

    s = sub.add_parser("consensus", help="show consensus reference odds")
    s.add_argument("--fixtures", type=int, nargs="*", default=None)
    s.add_argument("--competition", type=int, default=39)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--as-of", default=None)
    s.set_defaults(func=cmd_consensus)
    s = sub.add_parser("screener-refresh", help="compute and cache screener results")
    s.add_argument("--competitions", type=int, nargs="+", default=None)
    s.add_argument("--fixtures", type=int, nargs="*", default=None)
    s.add_argument("--days", type=int, default=14)
    s.add_argument("--as-of", default=None)
    s.set_defaults(func=cmd_screener_refresh)

    s = sub.add_parser("model-report", help="Goal Model monitoring from official forecasts")
    s.add_argument("--out-dir", default="monitoring/model")
    s.set_defaults(func=cmd_model_report)

    s = sub.add_parser("screener-show", help="ranked screener view from the cache")
    s.add_argument(
        "--direction",
        default="kickoff_earliest",
        choices=[
            "kickoff_earliest",
            "kickoff_latest",
            "home_win",
            "draw",
            "away_win",
            "btts_yes",
            "btts_no",
            "over",
            "under",
        ],
    )
    s.add_argument("--competition", type=int, default=None)
    s.add_argument("--threshold", type=float, default=None)
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_screener_show)

    s = sub.add_parser("sync-standings", help="official standings snapshot (1 request/league)")
    s.add_argument("--competitions", type=int, nargs="+", default=None)
    s.add_argument("--season", type=int, default=CURRENT_SEASON)
    s.set_defaults(func=cmd_sync_standings)

    s = sub.add_parser("setup", help="first-time setup: reference data, 2023-2026 backfill, cache")
    s.add_argument("--force", action="store_true", help="re-fetch completed historical seasons")
    s.add_argument(
        "--with-odds", action="store_true", help="also collect current odds (~4 requests)"
    )
    s.add_argument("--days", type=int, default=21)
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser(
        "refresh-data", help="incremental: current season, standings, screener cache"
    )
    s.add_argument("--days", type=int, default=21)
    s.add_argument("--skip-standings", action="store_true")
    s.add_argument(
        "--with-odds", action="store_true", help="also collect current odds (~4 requests)"
    )
    s.set_defaults(func=cmd_refresh_data)

    s = sub.add_parser("serve", help="run the Dash Statistical Screener")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8050)
    s.add_argument("--ttl", type=float, default=300, help="seconds to keep loaded data in memory")
    s.add_argument("--tz", default="Africa/Johannesburg", help="display time zone")
    s.add_argument("--debug", action="store_true")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("monitor-odds", help="odds trial: capture one raw odds snapshot")
    s.add_argument("--competitions", type=int, nargs="+", default=None)
    s.add_argument("--season", type=int, default=CURRENT_SEASON)
    s.add_argument("--until", default=None, help="ISO time after which capture is refused")
    s.add_argument("--out-dir", default=None)
    s.set_defaults(func=cmd_monitor_odds)

    s = sub.add_parser("research-pool", help="D-29 weekly research pool collection")
    s.add_argument("action", choices=["capture", "results", "replay", "report"])
    s.add_argument("--store-dir", default=None)
    s.add_argument("--research-db-url", default=None, help="SQLite research file only")
    s.add_argument("--round", default=None, help="round code for replay, e.g. 2026-W48")
    s.add_argument("--now", default=None, help=argparse.SUPPRESS)

    s = sub.add_parser("analyse-odds-trial", help="replay and analyse captured odds")
    s.add_argument("--out-dir", default=None)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_analyse_odds_trial)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    if args.command == "research-pool":
        return cmd_research_pool(args)
    engine = make_engine(args.database_url)
    from diski9.ingestion.common import MissingReferenceData
    from diski9.workflow import SetupIncomplete

    try:
        args.func(args, engine)
    except (SetupIncomplete, MissingReferenceData) as exc:
        _record_failure(engine, args.command, exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if args.command != "init-db":
            _record_failure(engine, args.command, exc)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
