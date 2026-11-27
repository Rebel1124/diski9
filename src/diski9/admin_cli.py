"""Operator presentation for Phase 6C.6 Stage E: publication readiness, one-round
investigation and the audit viewer. Every function here only formats results of
read-only services; the commands are wired in :mod:`diski9.cli` (``round
readiness``, ``round inspect``, ``round publish``) and here (``audit list``)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

ISSUE_LABELS = {
    "odds_stale": "quote older than the freshness limit",
    "odds_missing_timestamp": "no quote time",
    "odds_too_few_groups": "too few independent bookmaker groups",
    "probability_below_range": "probability below every bucket band",
    "probability_above_range": "probability above every bucket band",
    "probability_unclassified": "probability between bucket bands",
    "unsupported_market": "unsupported market",
}


def _t(dt: datetime | None) -> str:
    return "-" if dt is None else f"{dt.astimezone(UTC):%Y-%m-%d %H:%M} UTC"


def _age(now: datetime, dt: datetime | None) -> str:
    if dt is None:
        return "-"
    d = now - dt
    h = d.total_seconds() / 3600
    return f"{h:.1f} h ago" if h >= 0 else f"in {-h:.1f} h"


def readiness_dict(rd) -> dict:
    return {
        "round": rd.round.code,
        "status": rd.round.status,
        "development": rd.round.is_development,
        "stream": "development" if rd.round.is_development else rd.round.series,
        "ready": rd.ready,
        "problem": rd.problem,
        "details": rd.details,
        "evaluated_at": rd.evaluated_at,
        "snapshot_at": rd.snapshot_at,
        "max_snapshot_age_minutes": rd.max_snapshot_age / timedelta(minutes=1),
        "source": rd.source,
        "config_version": rd.config_version,
        "fingerprint": rd.fingerprint,
        "fixtures": rd.fixtures,
        "outcomes": rd.outcomes,
        "leagues": rd.leagues,
        "earliest_kickoff": rd.earliest_kickoff,
        "latest_kickoff": rd.latest_kickoff,
        "deadline_at": rd.deadline_at,
        "settle_cutoff_at": rd.settle_cutoff_at,
        "opening_report": rd.report,
        "required_by_bucket": rd.required_by_bucket,
        "ineligible_outcome_issues": rd.issues,
        "oldest_eligible_quote_at": rd.oldest_observation_at,
        "newest_eligible_quote_at": rd.newest_observation_at,
        "max_quote_age_hours": rd.max_quote_age_hours,
        "pool_diagnostics": rd.diagnostics,
    }


def pool_lines(diag: dict) -> list[str]:
    """The fixture-pool lines of ``round readiness`` (Phase 8 CP2A): fixtures with and
    without a Goal Model forecast (both can be eligible) and, separately, fixtures
    excluded because their Screener cache payload is missing."""
    lines = [
        "  fixture pool:            "
        f"{diag.get('fixtures_in_window', '-')} in the window, "
        f"{diag.get('fixtures_with_model', '-')} with a Goal Model forecast, "
        f"{diag.get('fixtures_without_model', '-')} without, "
        f"{diag.get('markets_eligible', '-')} of {diag.get('markets_checked', '-')} "
        "markets with strict consensus"
    ]
    missing = diag.get("fixtures_without_screener_payload") or 0
    if missing:
        lines.append(
            f"  WARNING: {missing} fixture{'s' if missing != 1 else ''} excluded: no Screener "
            "cache payload (refresh the cache offline with `diski9 screener-refresh`, then "
            "re-evaluate)"
        )
    return lines


def print_readiness(rd, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(readiness_dict(rd), indent=2, default=str))
        return
    r, now = rd.round, rd.evaluated_at
    stream = "development" if r.is_development else r.series
    print(f"Publication readiness: {r.code} ({stream}, status {r.status})")
    print(f"  evaluated at:            {_t(now)} (database clock)")
    print(f"  information frozen at:   {_t(rd.snapshot_at)}; source {rd.source}; "
          f"configuration {rd.config_version}")  # fmt: skip
    diag = rd.diagnostics
    if diag:
        for line in pool_lines(diag):
            print(line)
        excl = diag.get("exclusions") or {}
        if excl:
            print("  market exclusions:       "
                  + ", ".join(f"{k} {v}" for k, v in sorted(excl.items())))  # fmt: skip
    print(f"  on the sheet:            {rd.fixtures} fixtures, {rd.outcomes} outcomes, "
          f"{rd.leagues} leagues")  # fmt: skip
    rep = rd.report
    if rep:
        have = rep["eligible_outcomes_by_bucket"]
        need = rd.required_by_bucket
        print(f"  eligible:                {rep['eligible_fixtures']} fixtures in "
              f"{rep['eligible_leagues']} leagues, {rep['eligible_outcomes']} "
              "outcomes")  # fmt: skip
        print(
            "  buckets (eligible/pick): "
            + ", ".join(f"{b} {have.get(b, 0)}/{need[b]}" for b in need)
        )
        for check, ok in rep["checks"].items():
            print(f"    {'ok  ' if ok else 'FAIL'} {check.replace('_', ' ')}")
    if rd.issues:
        print("  ineligible outcomes:     "
              + ", ".join(f"{ISSUE_LABELS.get(k, k)} {v}"
                          for k, v in rd.issues.items()))  # fmt: skip
    print("  odds freshness:          eligible quotes observed "
          f"{_age(now, rd.newest_observation_at)} (newest) to "
          f"{_age(now, rd.oldest_observation_at)} (oldest); limit "
          f"{rd.max_quote_age_hours:g} h at the snapshot")  # fmt: skip
    print(f"  kickoffs:                {_t(rd.earliest_kickoff)} to {_t(rd.latest_kickoff)}")
    print(f"  entry deadline:          {_t(rd.deadline_at)}")
    print(f"  settlement cutoff:       {_t(rd.settle_cutoff_at)}")
    print(f"  fingerprint:             {rd.fingerprint}")
    if rd.ready:
        print("  verdict:                 READY to publish (every publication check passes now)")
    else:
        print(f"  verdict:                 NOT READY: {rd.problem}")
        extra = {k: v for k, v in (rd.details or {}).items() if k != "report"}
        if extra:
            print("  details: " + json.dumps(extra, default=str))


def print_inspection(ins) -> None:
    r = ins.round
    stream = "development" if r.is_development else r.series
    print(f"{r.code} ({stream}): status {r.status}; position {ins.position.replace('_', ' ')}")
    print(f"  evaluated at:            {_t(ins.evaluated_at)} (database clock)")
    print(f"  window:                  {_t(r.window_start_at)} to {_t(r.window_end_at)}")
    print(f"  published:               {_t(r.published_at)}; information frozen "
          f"{_t(r.snapshot_at)}")  # fmt: skip
    print(f"  entry deadline:          {_t(r.deadline_at)}")
    print(f"  settlement cutoff:       {_t(r.settle_cutoff_at)}")
    print(f"  versions:                config {r.config_version or '-'}, rules "
          f"{r.rules_version or '-'}, scoring {r.scoring_version or '-'}")  # fmt: skip
    print(f"  fingerprint:             {r.fingerprint or '-'}")
    ents = ", ".join(f"{k} {v}" for k, v in sorted(ins.entries.items())) or "none"
    print(f"  entries:                 {ents}; valid at lock "
          f"{'-' if r.valid_entries is None else r.valid_entries}; designation "
          f"{r.classification or '-'}")  # fmt: skip
    s = ins.settlement
    if s is not None:
        print("  settlement:")
        print(f"    result mode:           {s.result_mode or 'not chosen'}")
        print(f"    version:               {s.version or '-'} {s.version_kind or ''}")
        print(f"    round validity:        {s.validity}; pending predictions "
              f"{s.pending_predictions}")  # fmt: skip
        print("    unsettled evidence:    "
              + ("material" if s.material_unsettled else "yes" if s.unsettled_changes
                 else "none"))  # fmt: skip
        print(f"    correction window:     {s.correction_window_hours or '-'} hours")
        print(f"    earliest finalisation: {_t(s.earliest_finalisation)} (S-02)")
        print(f"    can finalise now:      {'yes' if s.eligible_to_finalise else 'no'}")
        for why in s.reasons:
            print(f"      - {why}")
    if ins.fixtures:
        fs = ins.fixture_summary
        print(f"  fixtures:                {fs['on_sheet']} on the sheet, {fs['relevant']} "
              f"relevant ({fs['resolved']} resolved, {fs['unresolved']} unresolved), "
              f"{fs['with_alerts']} with alerts")  # fmt: skip
        for f in ins.fixtures:
            if not f.relevant and not f.alerts:
                continue
            score = f"{f.score[0]}-{f.score[1]}" if f.score else "-"
            alerts = f"  alerts: {', '.join(f.alerts)}" if f.alerts else ""
            print(f"    {f.fixture_id:>9} {f.home} v {f.away}: {f.rule or 'unresolved'} "
                  f"{score}{alerts}")  # fmt: skip
    if ins.alerts:
        print(f"  open alerts:             {len(ins.alerts)}")
        for a in ins.alerts:
            kind = "blocking" if a["blocking"] else "informational"
            print(f"    #{a['id']} {a['code']} ({kind}) fixture {a['fixture_id'] or '-'}")
    elif s is not None:
        print("  open alerts:             none")
    if ins.score_set:
        ss = ins.score_set
        print(f"  weekly results:          revision {ss['revision']} ({ss['kind']}"
              f"{', final' if ss['final'] else ''}) {_t(ss['created_at'])}")  # fmt: skip
    c = ins.championship
    if c:
        slot = f" slot {c['slot']}" if c["slot"] is not None else ""
        print(f"  championship:            {c['display_name']} ({c['status'].replace('_', ' ')}, "
              f"{c['counted_rounds']} of {c['rounds_required']} rounds; version "
              f"{c['current_version'] or '-'}); this round: {c['role']}{slot}")  # fmt: skip
    elif r.status != "draft":
        print("  championship:            not assigned")
    if ins.jobs:
        print(f"  recent jobs ({len(ins.jobs)}):")
        for j in ins.jobs[:10]:
            err = f"  {j['error'][:80]}" if j.get("error") else ""
            print(f"    {_t(j['started_at'])} {j['job']:22} {j['outcome']}{err}")
    if ins.audit:
        print(f"  audit ({len(ins.audit)}):")
        for a in ins.audit[:10]:
            print(f"    {_t(a['at'])} {a['action']:22} by {a['actor_role'] or '-'}")
    for n in ins.notes:
        print(f"  note: {n}")


# ------------------------------------------------------------------ audit list
def add_parsers(sub) -> None:
    s = sub.add_parser("audit", help="audit records (read-only; needs audit.view)")
    a = s.add_subparsers(dest="action", required=True)
    p = a.add_parser("list", help="recent audit records, newest first")
    p.add_argument("--operator", metavar="EMAIL",
                   help="your own sign-in email; your password is then asked for")  # fmt: skip
    p.add_argument("--by-email", help=argparse.SUPPRESS)  # removed (S-07): guidance error
    p.add_argument("--limit", type=int, default=50, help="1-200 (default 50)")
    p.add_argument("--action-prefix", dest="prefix",
                   help="only actions starting with this, e.g. round. or role")  # fmt: skip
    p.add_argument("--round", "--code", dest="code", help="only this round's records")
    p.add_argument("--since", help="only records at or after this ISO time (UTC if no zone)")
    p.add_argument("--json", action="store_true")


def run_audit(args) -> int:
    from diski9.backend.ops.audit import audit_list
    from diski9.cli import BY_EMAIL_REMOVED
    from diski9.settlement_cli import _principal, _Usage, guarded

    if getattr(args, "by_email", None):
        print(BY_EMAIL_REMOVED, file=sys.stderr)
        return 2

    def call(engine) -> int:
        if not 1 <= args.limit <= 200:
            raise _Usage("--limit must be between 1 and 200")
        since = None
        if args.since:
            try:
                since = datetime.fromisoformat(args.since)
            except ValueError:
                raise _Usage("--since must be an ISO time, for example 2026-11-21T08:00") from None
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
        p = _principal(engine, args.operator)
        rows = audit_list(engine, p, limit=args.limit, action=args.prefix,
                          round_code=args.code, since=since)  # fmt: skip
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
            return 0
        if not rows:
            print("no audit records match")
        for r in rows:
            reason = f"  reason: {r['reason']}" if r["reason"] else ""
            job = f"  job {r['job_run_id']}" if r["job_run_id"] else ""
            print(f"{_t(r['at'])}  {r['action']:28} by {r['actor']} ({r['actor_role']}) "
                  f"on {r['target']}{job}{reason}")  # fmt: skip
        return 0

    return guarded(call)
