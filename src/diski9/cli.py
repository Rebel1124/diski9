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
from diski9.settlement_cli import ROUND_ACTIONS, add_round_arguments
from diski9.settlement_cli import add_parsers as add_settlement_parsers

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
    from diski9.app.factory import build_app

    built = build_app(engine, ttl_seconds=args.ttl, tz=args.tz)
    if built.accounts_enabled:
        print("Accounts enabled (Supabase Auth)")
    else:
        print("Accounts disabled: DISKI9_SUPABASE_AUTH_URL / _PUBLISHABLE_KEY not set (guest mode)")
    built.app.run(host=args.host, port=args.port, debug=args.debug)


BY_EMAIL_REMOVED = (
    "error: --by-email was removed (S-07, Phase 6C.6): an e-mail address alone no longer "
    "identifies the acting operator or owner. Use --operator EMAIL (your own sign-in "
    "address); your password is then asked for in a terminal and verified with Supabase "
    "Auth. Nothing was changed."
)

# The capability each privileged account command needs. All three are SENSITIVE, so
# the password must have been entered within the T-14 window (15 minutes) at the
# moment of the write, on top of the T-12 operator recency.
ACCOUNT_CAPABILITY = {
    "grant-role": "roles.manage",
    "revoke-role": "roles.manage",
    "grant-feature": "entitlements.manage",
    "revoke-feature": "entitlements.manage",
    "suspend": "user.suspend",
    "reinstate": "user.suspend",
}


def cmd_account(args) -> int:
    """Server-side account administration. There is no web equivalent. Every change
    is made by a person whose identity is verified with their password through
    Supabase Auth (S-07): the acting owner or operator for roles, entitlements and
    suspension; the target account itself for the one-time owner bootstrap. Roles
    come from the database and every change is audited."""
    if args.action == "generate-keys":
        import secrets as _s

        from diski9.backend.auth.crypto import generate_fernet_key

        print(f"DISKI9_APP_SECRET_KEY={_s.token_urlsafe(48)}")
        print(f"DISKI9_APP_TOKEN_ENCRYPTION_KEY={generate_fernet_key()}")
        print("# put these in your untracked .env (or the host's secret store); never commit them")
        return 0
    if getattr(args, "by_email", None):
        print(BY_EMAIL_REMOVED, file=sys.stderr)
        return 2
    from diski9.backend.auth import privileged as pv
    from diski9.backend.auth.operator_cli import authenticate_operator, refresh_clock
    from diski9.backend.auth.permissions import Capability, authorize
    from diski9.backend.auth.sessions import revoke_all_sessions
    from diski9.backend.db import transaction
    from diski9.settlement_cli import _principal, _Usage, guarded

    def list_privileged(engine) -> int:
        from sqlalchemy import select

        from diski9.backend.db.schema import profiles, user_roles

        with transaction(engine) as conn:
            rows = conn.execute(
                select(user_roles.c.role, profiles.c.username, user_roles.c.granted_at)
                .join(profiles, profiles.c.user_id == user_roles.c.user_id)
                .order_by(user_roles.c.role, profiles.c.username)
            ).all()
        for r in rows:
            print(f"{r.role:8} {r.username} (since {r.granted_at:%Y-%m-%d})")
        if not rows:
            print("no operators or owners")
        return 0

    def bootstrap(engine) -> int:
        if not args.confirm:
            raise _Usage("add --confirm to grant the first owner role")
        if not args.email:
            raise _Usage("--email is required (the account that becomes the first owner)")
        with transaction(engine) as conn:
            if pv.owner_count(conn) > 0:  # fail before asking for a password
                raise pv.PrivilegeError("an owner already exists; use grant-role as that owner.")
            target = pv.find_user_by_email(conn, args.email)
        print("Owner bootstrap: sign in as the account that will become the first owner.")
        who = authenticate_operator(engine, args.email, out=sys.stdout)
        if who.user_id != target:  # the verified sign-in must be the named account
            raise pv.PrivilegeError("the verified sign-in is not the account named by --email.")
        with transaction(engine) as conn:
            pv.bootstrap_owner(conn, target, args.reason or "initial owner bootstrap",
                               actor=who.user_id)  # fmt: skip
        print("owner role granted (first owner); lucy.* entitlements granted")
        return 0

    def change(engine) -> int:
        # every argument is checked before the password is asked for (nothing written)
        if not args.email:
            raise _Usage("--email is required (the account to change)")
        if not (args.reason and args.reason.strip()):
            raise _Usage("--reason is required (recorded in the audit log)")
        role_action = args.action in ("grant-role", "revoke-role")
        feature_action = args.action in ("grant-feature", "revoke-feature")
        if role_action and not args.role:
            raise _Usage(f"--role is required for {args.action} (operator or owner)")
        if feature_action and not (args.feature and args.feature.strip()):
            raise _Usage(f"--feature is required for {args.action}, for example lucy.research")
        if args.role and not role_action:
            raise _Usage(f"--role does not apply to {args.action}; nothing was changed")
        if args.feature and not feature_action:
            raise _Usage(f"--feature does not apply to {args.action}; nothing was changed")
        actor = _principal(engine, args.operator)
        # authorise against the current database time, before any write (T-12/T-14)
        actor = refresh_clock(engine, actor)
        authorize(actor, Capability(ACCOUNT_CAPABILITY[args.action]))
        with transaction(engine) as conn:
            target = pv.find_user_by_email(conn, args.email)
            if args.action == "grant-role":
                pv.grant_role(conn, actor.user_id, target, args.role, args.reason)
            elif args.action == "revoke-role":
                pv.revoke_role(conn, actor.user_id, target, args.role, args.reason)
            elif args.action == "grant-feature":
                pv.grant_feature(conn, actor.user_id, target, args.feature, args.reason)
            elif args.action == "revoke-feature":
                pv.revoke_feature(conn, actor.user_id, target, args.feature, args.reason)
            else:
                pv.set_status(
                    conn,
                    actor.user_id,
                    target,
                    "suspended" if args.action == "suspend" else "active",
                    args.reason,
                    revoke_all_sessions,
                    actor_role="owner" if "owner" in actor.roles else "operator",
                )
        print(f"{args.action}: done (audited)")
        return 0

    if args.action == "list-privileged":
        return guarded(list_privileged)
    if args.action == "bootstrap-owner":
        return guarded(bootstrap)
    return guarded(change)


def cmd_round(args) -> int:
    """Weekly round administration through the server CLI (Phase 6C.3). Publication
    and lock run the same services and checks as any other caller; nothing here can
    change a published snapshot or deadline. Every write is made by an operator whose
    password is verified through Supabase Auth (S-07); unattended locking belongs to
    the scheduler (``SYSTEM``), not to this command."""
    from datetime import timedelta

    if getattr(args, "by_email", None):
        print(BY_EMAIL_REMOVED, file=sys.stderr)
        return 2
    from diski9.backend.db import BackendDatabaseSettings, db_now, transaction
    from diski9.backend.services import rounds as svc
    from diski9.backend.services.common import ServiceError
    from diski9.settlement_cli import _principal, guarded

    def show(v) -> None:
        print(
            f"{v.code}  status={v.status}  development={v.is_development}  "
            f"deadline={v.deadline_at:%Y-%m-%d %H:%M UTC}  "
            if v.deadline_at
            else f"{v.code}  status={v.status}  development={v.is_development}  ",
            end="",
        )
        print(
            f"designation={v.designation or '-'}  valid_entries="
            f"{'-' if v.valid_entries is None else v.valid_entries}  "
            f"fingerprint={v.fingerprint or '-'}"
        )

    def build_snapshot(engine, r):
        """The live snapshot exactly as publication builds it (football store, read-only)."""
        from diski9.app.data import LEAGUE_SHORT
        from diski9.challenge.roundsheet import build_live_snapshot

        football = make_engine(args.database_url)
        with transaction(engine) as conn:
            now = db_now(conn)
            config = svc.round_config(conn, r.id)  # the round's own schedule, never the default
        return build_live_snapshot(
            football, now, r.window_start_at, r.window_end_at, r.code, LEAGUE_SHORT, config
        )

    def call(engine) -> int:
        from diski9.admin_cli import print_inspection, print_readiness

        if args.action == "list":
            for v in svc.list_rounds(engine):
                show(v)
            return 0
        if args.action in ("show", "lock", "publish", "readiness", "inspect") and not args.code:
            raise ServiceError("--code is required, for example 2026-W48-weekend", code="usage")
        if args.action == "show":
            show(svc.get_round(engine, svc.round_id_for_code(engine, args.code)))
            return 0
        if args.action == "readiness":
            # read-only: the same checks as publication, nothing written, no password
            rid = svc.round_id_for_code(engine, args.code)
            r = svc.get_round(engine, rid)
            if r.status != "draft":
                raise ServiceError(
                    f"{r.code} is already {r.status}; readiness applies to draft rounds "
                    "(use round inspect for published rounds).",
                    code="usage",
                )
            if r.is_development:
                raise ServiceError(
                    "Development rounds are opened with round dev-open (synthetic data); "
                    "readiness applies to real rounds.",
                    code="usage",
                )
            rd = svc.publication_readiness(engine, rid, build_snapshot(engine, r),
                                           source="football-db")  # fmt: skip
            print_readiness(rd, as_json=args.json)
            if not args.json:
                # display only (E.1b, D-3): which automated data sweep the store reflects
                from diski9.backend.jobs.refresh import readiness_line

                try:
                    print(f"  data refresh:            {readiness_line(engine, r.code)}")
                except Exception as exc:  # noqa: BLE001 - never affects the verdict
                    print(f"  data refresh:            unavailable ({type(exc).__name__})")
            return 0 if rd.ready else 1
        if args.action == "inspect":
            from diski9.backend.ops.inspect import inspect_round

            rid = svc.round_id_for_code(engine, args.code)
            p = _principal(engine, args.operator)
            print_inspection(inspect_round(engine, p, rid))
            return 0
        if args.action == "create":
            if not args.week or "-W" not in args.week:
                raise ServiceError("--week is required, for example 2026-W48", code="usage")
            year, week = (int(x) for x in args.week.split("-W"))
            start, end = svc.schedule_window(engine, year, week)
            p = _principal(engine, args.operator)
            v = svc.create_round(
                engine,
                p,
                code=f"{year}-W{week:02d}-weekend",
                window_start=start,
                window_end=end,
            )
            show(v)
            return 0
        if args.action == "publish":
            from diski9.settlement_cli import _ask

            rid = svc.round_id_for_code(engine, args.code)
            p = _principal(engine, args.operator)
            r = svc.get_round(engine, rid)
            snap = build_snapshot(engine, r)  # built once; the same immutable object is
            approved = None  # validated, shown, confirmed and published (no rebuild)
            if r.status == "draft" and not r.is_development:
                # show the operator exactly what would be frozen, then ask (Stage E)
                rd = svc.publication_readiness(engine, rid, snap, source="football-db")
                print_readiness(rd)
                if rd.ready:
                    answer = _ask(f"Type {r.code} to publish this snapshot, or press Enter to "
                                  "stop: ").strip()  # fmt: skip
                    if answer != r.code:
                        print("Not confirmed; nothing changed.")
                        return 0
                    approved = rd.fingerprint
            # the service repeats every check under the round lock (and records a refusal)
            show(svc.publish_round(engine, p, rid, snap, source="football-db",
                                   expected_fingerprint=approved))  # fmt: skip
            return 0
        if args.action == "dev-open":
            from diski9.backend.devdata import dev_snapshot

            if BackendDatabaseSettings().environment == "production":
                raise ServiceError("development rounds are refused in production", code="usage")
            if args.fixtures < 0:
                raise ServiceError("--fixtures must be 0 (no cap) or more", code="usage")
            if not args.mirror_upcoming and args.spacing_minutes < 1:
                raise ServiceError("--spacing-minutes must be 1 or more", code="usage")
            p = _principal(engine, args.operator)
            with transaction(engine) as conn:
                now = db_now(conn)
                config = svc.schedule_config(conn)  # what create_round below binds the round to
            first = now + timedelta(minutes=args.deadline_minutes + 15)
            code = args.code or f"dev-{now:%Y%m%d-%H%M%S}"
            if args.mirror_upcoming:
                from diski9.app.data import LEAGUE_SHORT
                from diski9.backend.devdata import mirror_snapshot

                snap = mirror_snapshot(
                    code,
                    now,
                    make_engine(args.database_url),
                    earliest_kickoff=first,
                    fixtures=args.fixtures,
                    seed=args.seed,
                    league_names=LEAGUE_SHORT,
                    config=config,
                )
            else:
                snap = dev_snapshot(
                    code,
                    now,
                    first,
                    seed=args.seed,
                    spacing=timedelta(minutes=args.spacing_minutes),
                    fixtures=args.fixtures or 20,
                    config=config,
                )
            v = svc.create_round(
                engine,
                p,
                code=code,
                window_start=snap.window[0],
                window_end=snap.window[1],
                development=True,
            )
            show(svc.publish_round(engine, p, v.id, snap, source="development"))
            print(
                "Development round: synthetic odds"
                + (" on real upcoming fixtures." if args.mirror_upcoming else " and fixtures.")
            )
            return 0
        if args.action == "lock":
            rid = svc.round_id_for_code(engine, args.code)
            p = _principal(engine, args.operator)  # a person; never SYSTEM here (Q-02)
            res = svc.lock_round(engine, p, rid)
            show(res.round)
            print(
                "already locked; nothing changed"
                if res.already_locked
                else f"locked {res.locked_entries} entries"
            )
            return 0
        return 2

    return guarded(call)


def cmd_app_db(args) -> int:
    """Competition database (PostgreSQL) commands. Never touches the SQLite store."""
    from diski9.backend.db import BackendDatabaseSettings, check_health, make_app_engine, migrate

    settings = BackendDatabaseSettings()
    url = settings.url()
    if args.action == "upgrade":
        migrate.upgrade(url, args.revision or "head")
        print(f"competition schema at {migrate.current(url)} ({settings.safe_url()})")
    elif args.action == "downgrade":
        if not args.revision:
            print("error: downgrade needs --revision (for example: base)", file=sys.stderr)
            return 2
        if settings.environment == "production":
            print("error: downgrade is disabled in production", file=sys.stderr)
            return 2
        migrate.downgrade(url, args.revision)
        print(f"competition schema at {migrate.current(url)} ({settings.safe_url()})")
    elif args.action == "current":
        print(f"current {migrate.current(url)}; head {migrate.head()}")
    elif args.action == "check":
        engine = make_app_engine(settings)
        try:
            health = check_health(engine)
        finally:
            engine.dispose()
        health["head"] = migrate.head()
        health["up_to_date"] = health["schema_revision"] == health["head"]
        print(_json(health))
        return 0 if health["up_to_date"] else 1
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

    s = sub.add_parser("analyse-odds-trial", help="replay and analyse captured odds")
    s.add_argument("--out-dir", default=None)
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_analyse_odds_trial)

    s = sub.add_parser(
        "account", help="server-side account administration (owner bootstrap, roles)"
    )
    s.add_argument(
        "action",
        choices=[
            "generate-keys",
            "list-privileged",
            "bootstrap-owner",
            "grant-role",
            "revoke-role",
            "grant-feature",
            "revoke-feature",
            "suspend",
            "reinstate",
        ],
    )
    s.add_argument("--email", help="the account to change (its verified email address)")
    s.add_argument(
        "--operator",
        metavar="EMAIL",
        help="your own sign-in email (owner or operator); your password is then asked for",
    )
    s.add_argument("--by-email", help=argparse.SUPPRESS)  # removed (S-07): guidance error
    s.add_argument("--role", choices=["operator", "owner"])
    s.add_argument("--feature", help="for example lucy.research")
    s.add_argument("--reason", help="recorded in the audit log")
    s.add_argument("--confirm", action="store_true", help="required for bootstrap-owner")

    s = sub.add_parser(
        "round",
        help="weekly rounds: list, show, readiness, inspect, create, publish, lock; "
        "invalidate, finalise, reopen (competition DB)",
    )
    s.add_argument(
        "action",
        choices=[
            "list",
            "show",
            "readiness",
            "inspect",
            "create",
            "publish",
            "lock",
            "dev-open",
            *ROUND_ACTIONS,
        ],
    )
    s.add_argument("--code", help="round code, for example 2026-W48-weekend")
    s.add_argument("--week", help="ISO week for create, for example 2026-W48")
    s.add_argument("--json", action="store_true", help="readiness: machine-readable output")
    s.add_argument("--by-email", help=argparse.SUPPRESS)  # removed (S-07): guidance error
    s.add_argument("--seed", type=int, default=2026, help="dev-open: fixture seed")
    s.add_argument(
        "--deadline-minutes",
        type=int,
        default=120,
        help="dev-open: minutes from now until the submission deadline (at the earliest)",
    )
    s.add_argument(
        "--mirror-upcoming",
        action="store_true",
        help="dev-open: real upcoming fixtures from the football store, synthetic odds",
    )
    s.add_argument(
        "--fixtures",
        type=int,
        default=20,
        help="dev-open: number of fixtures (synthetic default 20); with --mirror-upcoming the "
        "earliest kickoffs first (0 = every upcoming fixture within seven days of the first "
        "allowed kickoff)",
    )
    s.add_argument(
        "--spacing-minutes",
        type=int,
        default=120,
        help="dev-open (synthetic fixtures): minutes between kickoffs; use 1 for a "
        "compressed round whose matches all start within minutes of each other",
    )
    add_round_arguments(s)
    add_settlement_parsers(sub)
    from diski9.jobs_cli import add_parsers as add_jobs_parsers

    add_jobs_parsers(sub)
    from diski9.ops_cli import add_parsers as add_ops_parsers

    add_ops_parsers(sub)
    from diski9.admin_cli import add_parsers as add_admin_parsers

    add_admin_parsers(sub)
    from diski9.backup_cli import add_parsers as add_backup_parsers

    add_backup_parsers(sub)

    s = sub.add_parser("app-db", help="competition database (PostgreSQL): migrations, health")
    s.add_argument("action", choices=["upgrade", "downgrade", "current", "check"])
    s.add_argument("--revision", default=None, help="target revision (default head)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    if args.command == "app-db":
        return cmd_app_db(args)
    if args.command == "account":
        return cmd_account(args)
    if args.command == "jobs":
        from diski9.jobs_cli import run as run_jobs

        return run_jobs(args)
    if args.command == "ops":
        from diski9.ops_cli import run as run_ops

        return run_ops(args)
    if args.command in ("backup", "restore"):
        from diski9.backup_cli import run as run_backup

        return run_backup(args)
    if args.command == "audit":
        from diski9.admin_cli import run_audit

        return run_audit(args)
    if args.command in ("results", "settle", "dev-results", "competition", "dev-championship") or (
        args.command == "round" and args.action in ROUND_ACTIONS
    ):
        from diski9.settlement_cli import run as run_settlement

        return run_settlement(args)
    if args.command == "round":
        return cmd_round(args)
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
