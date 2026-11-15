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
from diski9.leagues import BACKFILL_SEASONS, COMPETITIONS, CURRENT_SEASON
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
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            ingestion_runs.insert().values(
                job=job, started_at=now, finished_at=now, status="failed", error=repr(exc)[:2000]
            )
        )


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
    targets = args.competitions or [c.id for c in COMPETITIONS.values() if c.odds_enabled]
    with ApiFootballClient.from_settings() as client:
        for cid in targets:
            with engine.begin() as conn:
                stats = collect_odds(conn, client, cid, args.season)
            print(f"{cid}/{args.season}: {_json(summarise_fetch(stats))}")
        print(f"API requests: {client.quota_requests_made}")


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

    targets = args.competitions or [c.id for c in COMPETITIONS.values() if c.odds_enabled]
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
    s = sub.add_parser("monitor-odds", help="odds trial: capture one raw odds snapshot")
    s.add_argument("--competitions", type=int, nargs="+", default=None)
    s.add_argument("--season", type=int, default=CURRENT_SEASON)
    s.add_argument("--until", default=None, help="ISO time after which capture is refused")
    s.add_argument("--out-dir", default=None)
    s.set_defaults(func=cmd_monitor_odds)

    s = sub.add_parser("analyse-odds-trial", help="replay and analyse captured odds")
    s.add_argument("--out-dir", default=None)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_analyse_odds_trial)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    engine = make_engine(args.database_url)
    try:
        args.func(args, engine)
    except Exception as exc:
        if args.command != "init-db":
            _record_failure(engine, args.command, exc)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
