"""Operator commands for results, settlement, corrections, finalisation and owner
reopening (Phase 6C.4, Stage E), plus development-only result scenarios.

Every command that reads or changes settlement data asks for the acting person's
password (hidden, from a real terminal) and verifies it with Supabase Auth
(:mod:`diski9.backend.auth.operator_cli`). Roles come from the competition
database. Handlers only parse arguments, call the settlement services and print;
no settlement rule lives here.

Material changes (corrections, invalidation, reopening) always show an impact
preview first. They run only after an explicit confirmation: typing the round code
interactively, or ``--token`` with the token a preview printed. A token from a
preview made before the round changed is refused, and nothing is changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from diski9.backend.auth.operator_cli import (
    OperatorAuthFailed,
    authenticate_operator,
    refresh_clock,
)
from diski9.backend.auth.permissions import (
    AuthorizationError,
    Forbidden,
    NotAuthenticated,
    RecentAuthenticationRequired,
)

# ------------------------------------------------------------------ parsing helpers


def _when(value: str) -> datetime:
    """An ISO 8601 date-time with a time zone (for example 2026-11-28T17:05:00+00:00)."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 date-time: {value!r}") from None
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(f"add a time zone, for example {value}+00:00")
    return moment


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S UTC") if v.utcoffset() is not None else str(v)
    return str(v)


def _print_earliest(moment) -> None:
    """The earliest finalisation time, plus (development rounds) the ``--as-of``
    value to use: rounded up to the next whole second, so it is never early."""
    print(f"  earliest finalisation:  {_fmt(moment)}")
    if moment is not None:
        up = moment.replace(microsecond=0)
        if up < moment:
            up += timedelta(seconds=1)
        print(f"    (development rounds: --as-of {up.astimezone(UTC).isoformat()})")


def _operator_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--operator",
        metavar="EMAIL",
        help="your sign-in email; your password is then asked for (never pass it here)",
    )


def _round_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--round", "--code", dest="code", required=True, help="round code")


def _correction_args(p: argparse.ArgumentParser, *, required: bool) -> None:
    p.add_argument("--fixture", type=int, required=required, help="fixture ID")
    p.add_argument(
        "--status",
        help="corrected provider status code, for example FT, AET, PEN, PST, CANC, ABD",
    )
    p.add_argument("--home", type=int, help="corrected 90-minute home goals")
    p.add_argument("--away", type=int, help="corrected 90-minute away goals")
    p.add_argument(
        "--completed-at",
        type=_when,
        help="verified completion time from the cited evidence (needed for a full-time "
        "correction when no provider final was recorded by the cutoff)",
    )
    p.add_argument("--actual-kickoff-at", type=_when, help="verified actual kickoff time")
    p.add_argument("--kickoff-at", type=_when, help="verified (revised) scheduled kickoff")


def _confirm_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--preview-only", action="store_true", help="show the impact and stop")
    g.add_argument("--token", help="confirm a preview made earlier with its token")


def add_parsers(sub) -> None:
    """Register ``results``, ``settle`` and ``dev-results`` on the main parser."""
    s = sub.add_parser("results", help="result evidence and corrections (competition DB)")
    rs = s.add_subparsers(dest="action", required=True)
    p = rs.add_parser("import", help="fetch provider results for a real round's relevant fixtures")
    _round_arg(p)
    _operator_args(p)
    p.add_argument(
        "--full",
        action="store_true",
        help="re-check every relevant fixture, including those stable for six hours",
    )
    p.add_argument(
        "--update-football-store",
        action="store_true",
        help="also hand the same items to the existing football store upsert",
    )
    p = rs.add_parser("show", help="evidence and current resolution per fixture")
    _round_arg(p)
    _operator_args(p)
    p.add_argument("--fixture", type=int, help="one fixture, with every observation")
    p.add_argument("--all", action="store_true", help="include fixtures nobody selected")
    p = rs.add_parser("correct", help="audited result correction (preview, then confirm)")
    _round_arg(p)
    _operator_args(p)
    _correction_args(p, required=True)
    p.add_argument("--reason", required=True, help="why (recorded in the audit log)")
    p.add_argument("--evidence", required=True, help="the source you relied on")
    _confirm_args(p)
    p = rs.add_parser("withdraw-correction", help="withdraw an operator correction (audited)")
    _round_arg(p)
    _operator_args(p)
    p.add_argument("--observation", type=int, required=True, help="the correction's ID")
    p.add_argument("--reason", required=True)

    s = sub.add_parser("settle", help="settlement: preview, run, alerts, status")
    ss = s.add_subparsers(dest="action", required=True)
    for name, text in (
        ("preview", "what a settlement run would change now (writes nothing)"),
        ("run", "settle the round on the evidence recorded so far"),
        ("status", "settlement version, alerts and finalisation eligibility"),
    ):
        p = ss.add_parser(name, help=text)
        _round_arg(p)
        _operator_args(p)
        p.add_argument(
            "--as-of",
            type=_when,
            help="development rounds only: evaluate at this time instead of now",
        )
    p = ss.add_parser("alerts", help="settlement alerts (open by default)")
    _round_arg(p)
    _operator_args(p)
    p.add_argument("--all", action="store_true", help="include resolved alerts")
    p = ss.add_parser("resolve-alert", help="audited confirmation of an alert")
    _round_arg(p)
    _operator_args(p)
    p.add_argument("--alert", type=int, required=True)
    p.add_argument("--reason", required=True)

    s = sub.add_parser(
        "dev-results", help="development rounds only: result mode, scenarios, test entries"
    )
    ds = s.add_subparsers(dest="action", required=True)
    ds.add_parser("scenarios", help="list the deterministic scenarios")
    p = ds.add_parser("set-mode", help="choose a development round's result mode (once)")
    _round_arg(p)
    _operator_args(p)
    p.add_argument("--mode", choices=["synthetic", "real"], required=True)
    p = ds.add_parser("scenario", help="record a scenario's synthetic observations")
    _round_arg(p)
    _operator_args(p)
    p.add_argument("--name", required=True)
    p.add_argument(
        "--timeline",
        choices=["prompt", "standard"],
        default="prompt",
        help="prompt (default): evidence minutes after the deadline; standard: spread "
        "between the deadline and the cutoff",
    )
    p = ds.add_parser(
        "test-entry",
        help="confirm a deterministic portfolio for a test participant (their password)",
    )
    _round_arg(p)
    p.add_argument("--participant", metavar="EMAIL", help="the test participant's email")
    p.add_argument("--variant", type=int, default=0, help="portfolio variant (0, 1, 2 ...)")

    s = sub.add_parser(
        "competition",
        help="championships: status, integrity check, historical backfill, audited repair",
    )
    cs = s.add_subparsers(dest="action", required=True)
    p = cs.add_parser("status", help="each stream's current championship and waiting rounds")
    _operator_args(p)
    p = cs.add_parser("verify", help="read-only integrity check of every championship")
    _operator_args(p)
    p = cs.add_parser(
        "backfill",
        help="publish official results of rounds finalised before app_0007 (preview first)",
    )
    _operator_args(p)
    _confirm_args(p)
    p = cs.add_parser(
        "repair",
        help="rebuild derived championship records from authoritative results (preview first)",
    )
    _operator_args(p)
    p.add_argument("--stream", choices=("development", "beta", "official"),
                   help="limit the repair to one stream (default: every stream)")  # fmt: skip
    p.add_argument("--reason", help="why the repair is needed (required to apply; audited)")
    _confirm_args(p)


def add_round_arguments(p: argparse.ArgumentParser) -> None:
    """Extra ``round`` options for invalidate / finalise / finalise-check / reopen."""
    _operator_args(p)
    p.add_argument("--reason", help="invalidate / reopen: why (audited)")
    p.add_argument("--evidence", help="reopen: the source you relied on")
    p.add_argument("--as-of", type=_when, help="finalise: development rounds only")
    _confirm_args(p)
    g = p.add_argument_group("reopen with a correction (optional)")
    g.add_argument("--fixture", type=int)
    g.add_argument("--status")
    g.add_argument("--home", type=int)
    g.add_argument("--away", type=int)
    g.add_argument("--completed-at", type=_when)
    g.add_argument("--actual-kickoff-at", type=_when)
    g.add_argument("--kickoff-at", type=_when)


ROUND_ACTIONS = ("invalidate", "finalise", "finalise-check", "reopen")


# ------------------------------------------------------------------ runtime helpers
class _Usage(Exception):
    pass


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(prompt: str) -> str:
    if not _interactive():
        raise _Usage("this step needs an interactive terminal")
    return input(prompt)


def _principal(engine, email: str | None, who: str = "Operator"):
    email = email or _ask(f"{who} email: ")
    return authenticate_operator(engine, email, out=sys.stdout)


def _correction(args, *, required: bool):
    from diski9.backend.services.corrections import CorrectionInput

    if args.fixture is None:
        if required:
            raise _Usage("--fixture is required")
        return None
    if not args.status:
        raise _Usage("--status is required with --fixture")
    if (args.home is None) != (args.away is None):
        raise _Usage("give both --home and --away, or neither")
    return CorrectionInput(
        fixture_id=args.fixture,
        status=args.status.upper(),
        ft_home=args.home,
        ft_away=args.away,
        completed_at=args.completed_at,
        actual_kickoff_at=args.actual_kickoff_at,
        kickoff_at=args.kickoff_at,
    )


def _print_impact(imp) -> None:
    print(f"Preview: {imp.action}")
    print(f"  material change:        {'yes' if imp.material else 'no'}")
    print(f"  prediction verdicts:    {len(imp.verdict_changes)} change(s)")
    for c in imp.verdict_changes:
        flag = "" if c["material"] else " (score only, not material)"
        print(
            f"    fixture {c['fixture_id']} {c['market']} {c['outcome']}: "
            f"{c['verdict']} [{c['rule']}]{flag}"
        )
    print(f"  entries recalculated:   {imp.entry_changes}")
    print(f"  round designation:      {imp.designation_after}")
    print(f"  round validity:         {imp.outcome}")
    print(f"  confirmation token:     {imp.token}")


def _confirm(args, imp, code: str) -> str | None:
    """The token to execute with, or ``None`` when not confirmed."""
    if args.preview_only:
        print("Preview only; nothing changed. Confirm later with --token " + imp.token)
        return None
    if args.token:
        return args.token
    if not _interactive():
        raise _Usage("confirm with --token TOKEN (from a preview) or run interactively")
    answer = input(f"Type the round code ({code}) to apply this change, or press Enter to stop: ")
    if answer.strip() != code:
        print("Not confirmed; nothing changed.")
        return None
    return imp.token


def _print_settlement(res) -> None:
    print(
        f"Settlement run {res.run_id or '-'}: version {res.version or '-'} "
        f"({'material' if res.material else 'no material change'})"
    )
    print(f"  verdicts changed:       {res.changed_verdicts}")
    print(f"  entries changed:        {res.changed_entries}")
    print(f"  phase:                  {res.phase.replace('_', ' ')}")
    print(f"  round validity:         {res.outcome}")
    print(f"  designation:            {res.designation}")
    print(f"  new alerts:             {len(res.new_alerts)}")
    print(f"  open blocking alerts:   {res.open_blocking_alerts}")
    _print_earliest(res.earliest_finalisation)
    if res.post_final_change:
        print("  The round is final: a material difference raised a post_final_change alert.")


def _round_id(engine, code: str):
    from diski9.backend.services import rounds as rounds_svc

    return rounds_svc.round_id_for_code(engine, code)


# ------------------------------------------------------------------ handlers
def _results(args, engine) -> int:
    from diski9.backend.services import corrections as co
    from diski9.backend.services import results as rs
    from diski9.backend.services import settlement_ops as ops

    rid = _round_id(engine, args.code)
    p = _principal(engine, args.operator)
    if args.action == "import":
        from diski9.api_football import ApiFootballClient
        from diski9.ingestion.results_fetch import fetch_fixtures_by_ids

        client = ApiFootballClient.from_settings()
        store = None
        if args.update_football_store:
            from diski9.db import make_engine
            from diski9.ingestion.fixtures import store_fixtures

            football = make_engine(args.database_url)

            def store(items):
                with football.begin() as conn:
                    return store_fixtures(conn, items)

        res = rs.import_results(
            engine,
            p,
            rid,
            lambda ids: fetch_fixtures_by_ids(client, ids),
            full=args.full,
            football_store=store,
        )
        print(
            f"Polled {len(res.polled)} fixture(s), skipped {len(res.skipped)}; "
            f"received {res.received}, recorded {res.recorded} new observation(s), "
            f"{res.unchanged} unchanged; provider requests {res.requests}."
        )
        remaining = [r.daily_remaining for r in client.request_log if r.daily_remaining is not None]
        if remaining:
            print(f"Provider daily requests remaining: {remaining[-1]}")
        return 0
    if args.action == "show":
        reports = ops.fixture_report(engine, p, rid, args.fixture)
        for f in reports:
            if not (args.all or args.fixture or f.relevant):
                continue
            verdicts = ", ".join(f"{v['outcome']}={v['verdict']}" for v in f.verdicts) or "-"
            score = "-" if f.score is None else f"{f.score[0]}-{f.score[1]}"
            print(
                f"{f.fixture_id}  {f.home} v {f.away}  kickoff {_fmt(f.kickoff_at_publish)}  "
                f"rule {f.rule or '-'}  score {score}  {verdicts}"
                + (f"  alerts: {', '.join(f.alerts)}" if f.alerts else "")
            )
            if args.fixture:
                for n in f.notes:
                    print(f"    note: {n}")
                for o in f.observations:
                    extra = "".join(
                        f"  {k} {_fmt(o[k])}"
                        for k in ("completed_at", "actual_kickoff_at", "first_half_at",
                                  "corrects", "withdraws")
                        if o[k] is not None
                    )  # fmt: skip
                    print(
                        f"    #{o['id']} {o['source']:12} received {_fmt(o['observed_at'])}  "
                        f"{o['status'] or '-':5} score {o['score'] or '-':5} "
                        f"scheduled {_fmt(o['kickoff_at'])}{extra}"
                    )
        if not reports:
            print("No fixtures.")
        return 0
    if args.action == "correct":
        c = _correction(args, required=True)
        imp = co.preview_correction(engine, p, rid, c)
        _print_impact(imp)
        token = _confirm(args, imp, args.code)
        if token is None:
            return 0 if args.preview_only else 1
        res = co.correct_result(
            engine,
            refresh_clock(engine, p),
            rid,
            c,
            reason=args.reason,
            evidence=args.evidence,
            confirmation=token,
        )
        print("Correction recorded (audited).")
        _print_settlement(res)
        return 0
    if args.action == "withdraw-correction":
        res = co.withdraw_correction(engine, p, rid, args.observation, reason=args.reason)
        print("Correction withdrawn (audited).")
        _print_settlement(res)
        return 0
    return 2


def _settle(args, engine) -> int:
    from diski9.backend.services import corrections as co
    from diski9.backend.services import settlement as st
    from diski9.backend.services import settlement_ops as ops

    rid = _round_id(engine, args.code)
    p = _principal(engine, args.operator)
    if args.action == "preview":
        plan = st.preview_settlement(engine, p, rid, as_of=args.as_of)
        material = sum(1 for w in plan.verdict_writes if w["material"])
        pending = sum(
            1 for _, es in plan.entry_results.values() for _, v in es.legs if v == "pending"
        )
        print(f"Preview at {_fmt(plan.evaluated_at)} ({plan.phase.replace('_', ' ')})")
        print(f"  would change:           {'yes' if plan.changed else 'nothing'}")
        print(f"  verdict revisions:      {len(plan.verdict_writes)} ({material} material)")
        print(f"  entry revisions:        {len(plan.entry_writes)}")
        print(
            "  designation change:     "
            + ((plan.designation_write or {}).get("designation") or "none")
        )
        print(f"  round validity:         {plan.validity.outcome}")
        print(f"  pending predictions:    {pending}")
        print(f"  alerts it would raise:  {len(plan.alerts)}")
        for a in plan.alerts:
            kind = " (blocking)" if a.blocking else ""
            print(f"    {a.code} fixture {a.fixture_id or '-'}{kind}")
        return 0
    if args.action == "run":
        _print_settlement(st.settle_round(engine, p, rid, as_of=args.as_of))
        return 0
    if args.action == "status":
        r = ops.round_report(engine, p, rid, as_of=args.as_of)
        print(f"{r.code}: status {r.status}, result mode {r.result_mode or 'not chosen'}")
        print(f"  deadline:               {_fmt(r.deadline_at)}")
        print(f"  settlement cutoff:      {_fmt(r.settle_cutoff_at)}")
        print(f"  correction window:      {r.correction_window_hours or '-'} hours")
        print(f"  evaluated at:           {_fmt(r.evaluated_at)} ({r.phase.replace('_', ' ')})")
        print(f"  settlement version:     {r.version or '-'} {r.version_kind or ''}")
        print(f"  designation:            {r.designation or '-'}")
        print(f"  round validity:         {r.validity}")
        print(f"  pending predictions:    {r.pending_predictions}")
        print(
            f"  open alerts:            {r.open_blocking_alerts} blocking, "
            f"{r.open_informational_alerts} informational"
        )
        print(
            "  unsettled evidence:     "
            + ("material" if r.material_unsettled else "yes" if r.unsettled_changes else "none")
        )
        _print_earliest(r.earliest_finalisation)
        print(f"  can finalise now:       {'yes' if r.eligible_to_finalise else 'no'}")
        for why in r.reasons:
            print(f"    - {why}")
        return 0
    if args.action == "alerts":
        rows = ops.alerts_report(engine, p, rid, include_resolved=args.all)
        for a in rows:
            state = (
                f"{a['resolution']} {_fmt(a['resolved_at'])}: {a['resolution_reason']}"
                if a["resolution"]
                else "open"
            )
            print(
                f"#{a['id']} {a['code']} {'blocking' if a['blocking'] else 'informational'} "
                f"fixture {a['fixture_id'] or '-'} raised {_fmt(a['created_at'])} - {state}"
            )
            if a["detail"]:
                print(f"    {json.dumps(a['detail'], default=str, sort_keys=True)}")
        if not rows:
            print("No alerts." if args.all else "No open alerts.")
        return 0
    if args.action == "resolve-alert":
        outcome = co.resolve_alert(engine, p, rid, args.alert, reason=args.reason)
        print(f"Alert {args.alert} {outcome} (audited).")
        return 0
    return 2


def _dev(args, engine) -> int:
    from diski9.backend import settlement_scenarios as sc
    from diski9.backend.services import results as rs

    if args.action == "scenarios":
        for name in sc.SCENARIOS:
            print(f"{name:24} {sc.DESCRIPTIONS[name]}")
        return 0
    rid = _round_id(engine, args.code)
    if args.action == "test-entry":
        participant = _principal(engine, args.participant, who="Participant")
        view = sc.submit_test_entry(engine, participant, rid, args.variant)
        print(f"Confirmed test portfolio (variant {args.variant}); entry version {view.version}.")
        return 0
    p = _principal(engine, args.operator)
    if args.action == "set-mode":
        print(f"Result mode: {rs.set_result_mode(engine, p, rid, args.mode)} (frozen, audited)")
        return 0
    if args.action == "scenario":
        if args.name not in sc.SCENARIOS:
            raise _Usage(f"unknown scenario; choose one of: {', '.join(sc.SCENARIOS)}")
        horizon = sc.PROMPT_HORIZON if args.timeline == "prompt" else None
        n = sc.apply_scenario(engine, p, rid, args.name, horizon=horizon)
        print(f"Recorded {n} synthetic observation(s) for {args.name} ({args.timeline} timeline).")
        return 0
    return 2


def _competition(args, engine) -> int:
    from diski9.backend.services import competition_ops as cops

    p = _principal(engine, args.operator)
    if args.action in ("status", "verify"):
        problems = 0
        for st in cops.stream_status(engine, p):
            if not st.open:
                print(f"{st.stream}: not started (official series, D-38)")
                continue
            if args.action == "status":
                cur = (
                    f"{st.current} ({st.status.replace('_', ' ')}, {st.counted_rounds} of "
                    f"{st.rounds_required} rounds)"
                    if st.current
                    else "no championship yet"
                )
                print(f"{st.stream}: {cur}; {st.championships} championship(s)")
                if st.waiting_rounds:
                    print(f"  championship assignment pending: {', '.join(st.waiting_rounds)}")
                if st.unpublished_final:
                    print(
                        f"  final without official results (backfill): "
                        f"{', '.join(st.unpublished_final)}"
                    )
            for note in st.notes:
                print(f"  note: {note}")
            for prob in st.repairable:
                print(f"  repairable: {prob}")
            for prob in st.material:
                print(f"  needs investigation: {prob}")
            problems += len(st.problems)
            if args.action == "verify" and not st.problems:
                print(f"{st.stream}: consistent")
        return 1 if problems else 0
    if args.action == "repair":
        return _repair(args, engine, p, cops)
    plan = cops.preview_backfill(engine, p)
    print("Backfill preview (nothing has changed yet)")
    for i in plan.items:
        extra = f" [{i.kind}]" if i.kind else (f": {i.reason}" if i.reason else "")
        print(f"  {i.stream:12} {i.round_code:24} {i.action.replace('_', ' ')}{extra}")
    print(f"  rounds to publish:        {plan.to_publish}")
    print(f"  championships created:    {', '.join(plan.championships_created) or 'none'}")
    print(f"  rounds assigned:          {plan.rounds_assigned}")
    print(f"  assignment still pending: {plan.waiting}")
    print(f"  confirmation token:       {plan.token}")
    if args.preview_only:
        print("Preview only; nothing changed. Confirm later with --token " + plan.token)
        return 0
    token = args.token
    if not token:
        if not _interactive():
            raise _Usage("confirm with --token TOKEN (from a preview) or run interactively")
        if input("Type backfill to apply it, or press Enter to stop: ").strip() != "backfill":
            print("Not confirmed; nothing changed.")
            return 0
        token = plan.token
    done = cops.run_backfill(engine, p, confirmation=token)
    print(f"Backfill complete: {done.to_publish} round(s) published (audited).")
    return 0


def _repair(args, engine, p, cops) -> int:
    plan = cops.preview_repair(engine, p, stream=args.stream)
    print("Repair preview (nothing has changed yet)")
    for f in plan.repairable:
        print(f"  found:              {f}")
    for code in plan.republish:
        print(f"  publish results:    round {code} (latest final settlement version)")
    for c in plan.changes:
        before = (
            "new"
            if c.before is None
            else (f"{c.before[0].replace('_', ' ')}, {c.before[1]} rounds, v{c.before[2]}")
        )
        after = f"{c.after[0].replace('_', ' ')}, {c.after[1]} rounds, v{c.after[2]}"
        flags = []
        if c.standings_changed:
            flags.append("standings change")
        if c.winners_changed:
            flags.append("leaders or champions change")
        if c.note:
            flags.append(c.note)
        print(f"  {c.stream:12} {c.name}: {before} -> {after}"
              + (f" ({'; '.join(flags)})" if flags else ""))  # fmt: skip
    for f in plan.unrepairable:
        print(f"  not repaired (investigate separately): {f}")
    for f in plan.remaining:
        print(f"  would remain:       {f}")
    if not plan.material_change:
        print("Nothing to repair.")
        return 1 if plan.unrepairable else 0
    print(f"  confirmation token: {plan.token}")
    if args.preview_only:
        print("Preview only; nothing changed. Confirm later with --token " + plan.token)
        return 0
    if not args.reason:
        raise _Usage("--reason is required to apply a repair")
    token = args.token
    if not token:
        if not _interactive():
            raise _Usage("confirm with --token TOKEN (from a preview) or run interactively")
        if input("Type repair to apply it, or press Enter to stop: ").strip() != "repair":
            print("Not confirmed; nothing changed.")
            return 0
        token = plan.token
    done = cops.run_repair(engine, refresh_clock(engine, p), confirmation=token, reason=args.reason,
                           stream=args.stream)  # fmt: skip
    print(f"Repair complete: {len(done.changes)} championship(s), {len(done.republish)} "
          "round(s) republished (audited).")  # fmt: skip
    return 0


def _round(args, engine) -> int:
    from diski9.backend.services import corrections as co
    from diski9.backend.services import settlement_ops as ops

    rid = _round_id(engine, args.code)
    p = _principal(engine, args.operator)
    if args.action == "finalise-check":
        r = ops.round_report(engine, p, rid, as_of=args.as_of)
        print(f"{r.code}: can finalise {'now' if r.eligible_to_finalise else 'not yet'}")
        _print_earliest(r.earliest_finalisation)
        for why in r.reasons:
            print(f"    - {why}")
        return 0
    if args.action == "finalise":
        res = co.finalise_round(engine, p, rid, as_of=args.as_of)
        if res.finalised:
            print(f"Finalised: settlement version {res.version} (final).")
            return 0
        print(f"Not finalised: {res.reason}")
        _print_earliest(res.earliest_finalisation)
        return 1
    if args.action == "invalidate":
        if not args.reason:
            raise _Usage("--reason is required")
        imp = co.preview_invalidation(engine, p, rid, reason=args.reason)
        _print_impact(imp)
        token = _confirm(args, imp, args.code)
        if token is None:
            return 0 if args.preview_only else 1
        res = co.invalidate_round(
            engine, refresh_clock(engine, p), rid, reason=args.reason, confirmation=token
        )
        print("Round invalidated (audited); every entry is refunded.")
        _print_settlement(res)
        return 0
    if args.action == "reopen":
        if not (args.reason and args.evidence):
            raise _Usage("--reason and --evidence are required")
        c = _correction(args, required=False)
        imp = co.preview_reopen(engine, p, rid, correction=c)
        _print_impact(imp)
        token = _confirm(args, imp, args.code)
        if token is None:
            return 0 if args.preview_only else 1
        res = co.reopen_round(
            engine,
            refresh_clock(engine, p),
            rid,
            reason=args.reason,
            evidence=args.evidence,
            confirmation=token,
            correction=c,
        )
        print("Round reopened (audited); the final version is kept in history.")
        _print_settlement(res)
        return 0
    return 2


HANDLERS = {
    "results": _results,
    "settle": _settle,
    "dev-results": _dev,
    "round": _round,
    "competition": _competition,
}

AUTH_MESSAGES = {
    RecentAuthenticationRequired: "Your password check is too old for this change. "
    "Run the command again and confirm promptly. Nothing was changed.",
    NotAuthenticated: "You are not signed in. Nothing was changed.",
}


def run(args) -> int:
    """Run one settlement command; returns the process exit code."""
    from diski9.backend.db import make_app_engine
    from diski9.backend.services.common import ServiceError

    engine = make_app_engine()
    try:
        return HANDLERS[args.command](args, engine)
    except OperatorAuthFailed as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 3
    except Forbidden as exc:
        if exc.reason == "onboarding_incomplete":
            msg = "Finish setting up your account in the web app first."
        else:
            msg = "Your account does not have permission for this operation."
        print(f"error: {msg} Nothing was changed.", file=sys.stderr)
        return 3
    except AuthorizationError as exc:
        msg = AUTH_MESSAGES.get(type(exc), "Not permitted. Nothing was changed.")
        print(f"error: {msg}", file=sys.stderr)
        return 3
    except ServiceError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2
    except (_Usage, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nStopped; nothing changed.", file=sys.stderr)
        return 130
    finally:
        engine.dispose()
