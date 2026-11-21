"""Phase 6C.5 Stage F4: final data-integrity and audit verification of competition
databases (local development only). Strictly read-only: one READ ONLY, REPEATABLE
READ transaction per database (a consistent snapshot); nothing is written.

    uv run python tools/phase6c5_f4_integrity.py URL [URL ...]

Per database, every check prints its count of violations (0 = pass):

* duplicates: weekly score sets per (round, kind, revision); championship
  memberships per round; championship versions per (championship, version);
* every championship's ``current_version`` is its latest stored version;
* ``inspect_stream`` for development, beta and official (roles, counters, slots,
  status, boundaries, isolation; a recomputation of each current version's standings
  against its stored ``content_hash``);
* stored standing rows against their version's ``content_hash``, for **every**
  version (``inspect_stream`` compares the recomputation with the hash and counts the
  rows, but does not read the stored rows; together the two prove the stored rows
  equal the recomputation);
* shared ranks (weekly and championship): display order 1..n without gaps, ranked
  rows first, standard competition ranking (a new rank equals its position among the
  ranked rows), equal rank means equal points, and points never increase down the
  table (championship standings);
* refunds and voids: refunded or voided rows carry no rank and no points; a void
  score set contains only void rows; a void round is never a counted round;
* Under Review: a round being corrected (status settling after an earlier final
  score set) keeps its championship's last published version readable, and no
  version references a score set that is not final;
* audit: every finalisation, reopening, correction and publication has an actor; the
  only actor-less records are system jobs (``actor_role = 'system'``); every final
  competitive score set has a finalisation audit record for its round;
* streams: development championships contain only development rounds and the reverse;
  the official series has not started and no official championship exists.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import sqlalchemy as sa

from diski9.backend.db import BackendDatabaseSettings, make_app_engine
from diski9.backend.services import championships as ch

CHECKS: dict[str, str] = {
    "dup_score_sets": "SELECT count(*) FROM (SELECT 1 FROM app.score_sets GROUP BY round_id, "
    "kind, revision HAVING count(*) > 1) d",
    "dup_memberships": "SELECT count(*) FROM (SELECT 1 FROM app.championship_rounds GROUP BY "
    "round_id HAVING count(*) > 1) d",
    "dup_versions": "SELECT count(*) FROM (SELECT 1 FROM app.championship_versions GROUP BY "
    "championship_id, version HAVING count(*) > 1) d",
    "current_version_not_latest": "SELECT count(*) FROM app.championships c WHERE "
    "c.current_version IS DISTINCT FROM (SELECT max(v.version) FROM app.championship_versions v "
    "WHERE v.championship_id = c.id)",
    # weekly tables
    "weekly_display_order_gaps": "SELECT count(*) FROM (SELECT score_set_id FROM app.round_scores "
    "GROUP BY 1 HAVING min(display_order) <> 1 OR max(display_order) <> count(*) "
    "OR count(DISTINCT display_order) <> count(*)) d",
    "weekly_unranked_before_ranked": "SELECT count(*) FROM app.round_scores a JOIN "
    "app.round_scores b ON b.score_set_id = a.score_set_id AND b.display_order > a.display_order "
    "WHERE a.rank IS NULL AND b.rank IS NOT NULL",
    "weekly_competition_ranking": "SELECT count(*) FROM (SELECT rank, lag(rank) OVER w AS prev, "
    "row_number() OVER w AS pos FROM app.round_scores WHERE rank IS NOT NULL WINDOW w AS "
    "(PARTITION BY score_set_id ORDER BY display_order)) d WHERE (prev IS NULL AND rank <> 1) "
    "OR (prev IS NOT NULL AND rank <> prev AND rank <> pos) OR rank < prev",
    "weekly_equal_rank_unequal_points": "SELECT count(*) FROM (SELECT 1 FROM app.round_scores "
    "WHERE rank IS NOT NULL GROUP BY score_set_id, rank HAVING count(DISTINCT points) > 1) d",
    # championship tables
    "champ_display_order_gaps": "SELECT count(*) FROM (SELECT version_id FROM "
    "app.championship_standings GROUP BY 1 HAVING min(display_order) <> 1 OR "
    "max(display_order) <> count(*) OR count(DISTINCT display_order) <> count(*)) d",
    "champ_competition_ranking": "SELECT count(*) FROM (SELECT rank, lag(rank) OVER w AS prev, "
    "row_number() OVER w AS pos FROM app.championship_standings WHERE rank IS NOT NULL WINDOW w "
    "AS (PARTITION BY version_id ORDER BY display_order)) d WHERE (prev IS NULL AND rank <> 1) "
    "OR (prev IS NOT NULL AND rank <> prev AND rank <> pos) OR rank < prev",
    "champ_equal_rank_unequal_points": "SELECT count(*) FROM (SELECT 1 FROM "
    "app.championship_standings WHERE rank IS NOT NULL GROUP BY version_id, rank HAVING "
    "count(DISTINCT points) > 1) d",
    "champ_points_increase_down_table": "SELECT count(*) FROM (SELECT points, lag(points) OVER "
    "(PARTITION BY version_id ORDER BY display_order) AS prev FROM app.championship_standings) d "
    "WHERE points > prev",
    # refunds and voids
    "refund_or_void_with_rank_or_points": "SELECT count(*) FROM app.round_scores WHERE status "
    "<> 'ranked' AND (rank IS NOT NULL OR coalesce(points, 0) <> 0)",
    "void_set_with_non_void_rows": "SELECT count(*) FROM app.round_scores rs JOIN app.score_sets "
    "s ON s.id = rs.score_set_id WHERE s.kind = 'void' AND rs.status <> 'round_void'",
    "void_round_counted": "SELECT count(*) FROM app.championship_rounds cr JOIN app.score_sets s "
    "ON s.round_id = cr.round_id AND s.final AND s.kind = 'void' WHERE cr.role = 'counted' AND "
    "s.revision = (SELECT max(x.revision) FROM app.score_sets x WHERE x.round_id = s.round_id)",
    # Under Review and versions
    "version_cites_missing_score_set": "SELECT count(*) FROM app.championship_versions v WHERE "
    "v.cause_score_set_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM app.score_sets s WHERE "
    "s.id = v.cause_score_set_id AND s.final)",
    "version_without_standings": "SELECT count(*) FROM app.championship_versions v WHERE "
    "v.status IN ('in_progress', 'completed') AND v.counted_rounds > 0 AND NOT EXISTS "
    "(SELECT 1 FROM app.championship_standings s WHERE s.version_id = v.id)",
    # audit
    "unattributed_operator_actions": "SELECT count(*) FROM app.audit_log WHERE actor_user_id IS "
    "NULL AND coalesce(actor_role, '') <> 'system'",
    "operator_actions_without_actor": "SELECT count(*) FROM app.audit_log WHERE action IN "
    "('round.finalise', 'round.reopen', 'result.correct', 'round.publish', 'round.create', "
    "'competition.publish') AND actor_user_id IS NULL",
    "final_score_set_without_finalise_audit": "SELECT count(*) FROM (SELECT DISTINCT round_id "
    "FROM app.score_sets WHERE final) s WHERE NOT EXISTS (SELECT 1 FROM app.audit_log a WHERE "
    "a.action = 'round.finalise' AND a.target_id = s.round_id::text)",
    # streams
    "development_mix": "SELECT count(*) FROM app.championship_rounds cr JOIN app.championships c "
    "ON c.id = cr.championship_id JOIN app.rounds r ON r.id = cr.round_id WHERE "
    "(c.stream = 'development') <> r.is_development",
    "official_series_started": "SELECT count(*) FROM app.championship_series WHERE code = "
    "'official' AND started_at IS NOT NULL",
    "official_championships": "SELECT count(*) FROM app.championships WHERE stream = 'official'",
}

FACTS = {
    "rounds": "SELECT count(*) FROM app.rounds",
    "rounds_settling_after_final": "SELECT count(*) FROM app.rounds r WHERE r.status = "
    "'settling' AND EXISTS (SELECT 1 FROM app.score_sets s WHERE s.round_id = r.id AND s.final)",
    "score_sets": "SELECT count(*) FROM app.score_sets",
    "round_scores": "SELECT count(*) FROM app.round_scores",
    "refunded_or_void_rows": "SELECT count(*) FROM app.round_scores WHERE status <> 'ranked'",
    "shared_weekly_ranks": "SELECT count(*) FROM (SELECT 1 FROM app.round_scores WHERE rank IS "
    "NOT NULL GROUP BY score_set_id, rank HAVING count(*) > 1) d",
    "championships": "SELECT count(*) FROM app.championships",
    "championship_versions": "SELECT count(*) FROM app.championship_versions",
    "standing_rows": "SELECT count(*) FROM app.championship_standings",
    "audit_records": "SELECT count(*) FROM app.audit_log",
    "streams": "SELECT coalesce(string_agg(DISTINCT stream, ','), '') FROM app.championships",
}


def stored_rows_vs_hash(conn) -> int:
    """Versions whose stored standing rows do not reproduce their content hash."""
    bad = 0
    for v in conn.execute(sa.text("SELECT id, status, round_ids, scoring_version, content_hash "
                                  "FROM app.championship_versions")).all():  # fmt: skip
        rows = conn.execute(sa.text(
            "SELECT user_id AS participant_id, rank, points, rounds_played AS rounds_entered, "
            "recoveries, qualifying_top10, display_order FROM app.championship_standings "
            "WHERE version_id = :v ORDER BY display_order"), {"v": v.id}).all()  # fmt: skip
        rows = [
            SimpleNamespace(**{**r._asdict(), "participant_id": str(r.participant_id)})
            for r in rows
        ]
        if ch.content_hash(v.status, list(v.round_ids or []), v.scoring_version,
                           rows) != v.content_hash:  # fmt: skip
            bad += 1
    return bad


def verify(url: str) -> dict:
    eng = make_app_engine(BackendDatabaseSettings(environment="development"), url=url)
    out: dict = {"database": url.rsplit("/", 1)[-1], "violations": {}, "facts": {}}
    try:
        with eng.connect() as conn:
            conn.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            for name, sql in CHECKS.items():
                out["violations"][name] = conn.execute(sa.text(sql)).scalar()
            for name, sql in FACTS.items():
                out["facts"][name] = conn.execute(sa.text(sql)).scalar()
            out["violations"]["stored_standings_differ_from_hash"] = stored_rows_vs_hash(conn)
            for stream in ("development", "beta", "official"):
                out["violations"][f"inspect_stream_{stream}"] = ch.verify_stream(conn, stream)
            conn.rollback()
    finally:
        eng.dispose()
    bad = {k: v for k, v in out["violations"].items() if v not in (0, [])}
    out["result"] = "consistent" if not bad else {"problems": bad}
    return out


def main(urls: list[str]) -> int:
    results = [verify(u) for u in urls]
    print(json.dumps(results, indent=1, default=str))
    return 0 if all(r["result"] == "consistent" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
