"""Official weekly results and championship storage (Phase 6C.5).

Revision ID: app_0007
Revises: app_0006
Create Date: 2026-11-20

Approved in the Phase 6C.5 Stage A specification (§7, decisions CH-01 to CH-12).
Only schema ``app``; never Supabase schemas. Additive, except for dropping the
never-written placeholder ``championship_freezes``.

* ``score_sets`` (insert-only): one per **published final settlement version**
  (``settlement_version_id`` UNIQUE, which makes publication idempotent), with the
  scoring version, the publication time and the acting user. A guard checks that
  the settlement version is a ``final`` version of the same round.
* ``round_scores`` (insert-only): ``display_order`` (deterministic order inside a
  score set; competitive rank is never altered by it) and the status
  ``round_void`` (every entry of an invalidated round: refunded 100.00, no rank,
  recovery, top ten or points).
* New ``championships`` and ``championship_rounds`` (guarded projections: identity,
  name, start date and round membership can never change or be deleted) and
  insert-only ``championship_versions`` and ``championship_standings``. They are
  written from Phase 6C.5 Stage C onwards.
* ``championship_freezes`` is superseded by ``championship_versions`` and dropped.
  The upgrade refuses (changes nothing) if it, ``score_sets`` or ``round_scores``
  unexpectedly hold rows.

Downgrade refuses (and changes nothing) once any official result or championship
exists: published competition history is never discarded. With none, it restores
``app_0006`` exactly.
"""

from __future__ import annotations

from alembic import op

revision = "app_0007"
down_revision = "app_0006"
branch_labels = None
depends_on = None

APP_ROLE = "diski9_app"

NEW_HISTORY = ("championship_versions", "championship_standings")
NEW_GUARDED = {
    "championships": "app.championship_guard()",
    "championship_rounds": "app.championship_round_guard()",
}
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# "Championship Nov-26", with " (2)", " (3)", ... for a same-month collision (CH-03)
NAME_PATTERN = rf"^Championship ({MONTHS})-[0-9]{{2}}( \(([2-9]|[1-9][0-9]+)\))?$"


def _history(t: str) -> str:
    return (
        f"CREATE TRIGGER {t}_insert_only BEFORE UPDATE OR DELETE ON app.{t} "
        "FOR EACH ROW EXECUTE FUNCTION app.forbid_change();\n"
        f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON app.{t} "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.forbid_change();\n"
        f"ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;\n"
    )


def _guarded(t: str, fn: str) -> str:
    return (
        f"CREATE TRIGGER {t}_guard BEFORE UPDATE OR DELETE ON app.{t} "
        f"FOR EACH ROW EXECUTE FUNCTION {fn};\n"
        f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON app.{t} "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.forbid_change();\n"
        f"ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;\n"
    )


UP = rf"""
-- ============================================================== safety checks
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.championship_freezes)
     OR EXISTS (SELECT 1 FROM app.score_sets)
     OR EXISTS (SELECT 1 FROM app.round_scores) THEN
    RAISE EXCEPTION 'app_0007 upgrade refused: the placeholder tables championship_freezes, '
      'score_sets or round_scores unexpectedly hold rows (nothing was changed)'
      USING ERRCODE = 'object_in_use';
  END IF;
END $$;

-- ============================================================== weekly results
ALTER TABLE app.score_sets
  ADD COLUMN settlement_version_id bigint NOT NULL
    REFERENCES app.settlement_versions (id),
  ADD COLUMN scoring_version text NOT NULL,
  ADD COLUMN published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ADD COLUMN actor_user_id uuid REFERENCES app.users (id),
  ALTER COLUMN final SET DEFAULT true,
  ADD CONSTRAINT score_sets_settlement_version_key UNIQUE (settlement_version_id),
  ADD CONSTRAINT score_sets_final_only CHECK (final);

-- a score set publishes a final settlement version of its own round, and only that
CREATE FUNCTION app.score_set_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM app.settlement_versions v
     WHERE v.id = NEW.settlement_version_id AND v.round_id = NEW.round_id
       AND v.kind = 'final' AND v.run_id = NEW.run_id) THEN
    RAISE EXCEPTION 'app.score_sets: a score set must publish a final settlement version '
      'of the same round and run'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER score_sets_publishes_final BEFORE INSERT ON app.score_sets
  FOR EACH ROW EXECUTE FUNCTION app.score_set_guard();

ALTER TABLE app.round_scores
  ADD COLUMN display_order integer NOT NULL CHECK (display_order >= 1),
  DROP CONSTRAINT round_scores_status_check,
  ADD CONSTRAINT round_scores_status_check
    CHECK (status IN ('ranked', 'void_refunded', 'round_void')),
  ADD CONSTRAINT round_scores_round_void_kind CHECK ((status = 'round_void') = (kind = 'void')),
  ADD CONSTRAINT round_scores_round_void_refund
    CHECK (status <> 'round_void' OR (points = 0 AND rank IS NULL AND NOT recovered
                                      AND NOT qualifying_top10 AND gross = 100.00)),
  ADD CONSTRAINT round_scores_display_order_key UNIQUE (score_set_id, display_order);
CREATE INDEX ix_round_scores_user ON app.round_scores (user_id, score_set_id);
CREATE INDEX ix_score_sets_round ON app.score_sets (round_id, revision DESC);

-- ============================================================== championships
DROP TABLE app.championship_freezes;

CREATE TABLE app.championships (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stream                      text NOT NULL CHECK (stream IN ('development', 'beta', 'official')),
  series_id                   bigint NOT NULL REFERENCES app.championship_series (id),
  ordinal                     integer NOT NULL CHECK (ordinal >= 1),
  start_date                  date NOT NULL,
  display_name                text NOT NULL CHECK (display_name ~ '{NAME_PATTERN}'),
  status                      text NOT NULL DEFAULT 'upcoming'
                              CHECK (status IN ('upcoming', 'in_progress', 'completed')),
  rounds_required             smallint NOT NULL DEFAULT 10 CHECK (rounds_required > 0),
  counted_rounds              smallint NOT NULL DEFAULT 0,
  boundary_fixed_at           timestamptz,
  completed_at                timestamptz,
  corrected_after_completion  boolean NOT NULL DEFAULT false,
  current_version             integer CHECK (current_version IS NULL OR current_version >= 1),
  created_at                  timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (stream, ordinal),
  UNIQUE (stream, display_name),
  CHECK (counted_rounds >= 0 AND counted_rounds <= rounds_required),
  CHECK (status <> 'completed' OR completed_at IS NOT NULL),
  CHECK (status <> 'upcoming' OR counted_rounds = 0)
);

CREATE TABLE app.championship_rounds (
  round_id         uuid PRIMARY KEY REFERENCES app.rounds (id),
  championship_id  uuid NOT NULL REFERENCES app.championships (id),
  role             text NOT NULL
                   CHECK (role IN ('pending', 'counted', 'practice', 'void', 'not_counted')),
  slot             smallint CHECK (slot IS NULL OR slot >= 1),
  assigned_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((slot IS NOT NULL) = (role = 'counted'))
);
CREATE INDEX ix_championship_rounds ON app.championship_rounds (championship_id, role);

CREATE TABLE app.championship_versions (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  championship_id     uuid NOT NULL REFERENCES app.championships (id),
  version             integer NOT NULL CHECK (version >= 1),
  cause               text NOT NULL
                      CHECK (cause IN ('round_assigned', 'round_published', 'round_republished',
                                       'round_invalidated', 'round_restored', 'backfill',
                                       'repair')),
  cause_round_id      uuid REFERENCES app.rounds (id),
  cause_score_set_id  bigint REFERENCES app.score_sets (id),
  status              text NOT NULL CHECK (status IN ('upcoming', 'in_progress', 'completed')),
  counted_rounds      smallint NOT NULL CHECK (counted_rounds >= 0),
  round_ids           uuid[] NOT NULL,
  champion_count      integer NOT NULL CHECK (champion_count >= 0),
  scoring_version     text NOT NULL,
  content_hash        text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{{64}}$'),
  actor_user_id       uuid REFERENCES app.users (id),
  reason              text,
  created_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (championship_id, version)
);

CREATE TABLE app.championship_standings (
  version_id        bigint NOT NULL REFERENCES app.championship_versions (id),
  user_id           uuid NOT NULL REFERENCES app.users (id),
  rank              integer NOT NULL CHECK (rank >= 1),
  points            integer NOT NULL CHECK (points >= 0),
  rounds_played     smallint NOT NULL CHECK (rounds_played >= 1),
  recoveries        smallint NOT NULL,
  qualifying_top10  smallint NOT NULL,
  display_order     integer NOT NULL CHECK (display_order >= 1),
  name_entry_id     uuid NOT NULL REFERENCES app.entries (id),
  PRIMARY KEY (version_id, user_id),
  UNIQUE (version_id, display_order),
  CHECK (recoveries >= 0 AND recoveries <= rounds_played),
  CHECK (qualifying_top10 >= 0 AND qualifying_top10 <= recoveries),
  CHECK (points <= 150 * rounds_played)
);
CREATE INDEX ix_championship_standings_user ON app.championship_standings (user_id, version_id);

-- identity, name, start date and membership never change; rows are never deleted
CREATE FUNCTION app.championship_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'app.championships: championships are never deleted'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.id <> OLD.id OR NEW.stream <> OLD.stream OR NEW.series_id <> OLD.series_id
     OR NEW.ordinal <> OLD.ordinal OR NEW.start_date <> OLD.start_date
     OR NEW.display_name <> OLD.display_name OR NEW.rounds_required <> OLD.rounds_required
     OR NEW.created_at <> OLD.created_at
     OR (OLD.boundary_fixed_at IS NOT NULL
         AND NEW.boundary_fixed_at IS DISTINCT FROM OLD.boundary_fixed_at)
     OR (OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at)
  THEN
    RAISE EXCEPTION 'app.championships: identity, name, start date and fixed boundaries '
      'cannot change' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION app.championship_round_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'app.championship_rounds: championship membership is never deleted'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.round_id <> OLD.round_id OR NEW.championship_id <> OLD.championship_id
     OR NEW.assigned_at <> OLD.assigned_at THEN
    RAISE EXCEPTION 'app.championship_rounds: a round never moves to another championship'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

{"".join(_history(t) for t in NEW_HISTORY)}
{"".join(_guarded(t, fn) for t, fn in NEW_GUARDED.items())}

REVOKE ALL ON app.championships, app.championship_rounds, app.championship_versions,
  app.championship_standings FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.score_set_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.championship_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.championship_round_guard() FROM PUBLIC;
DO $$
DECLARE t text;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    FOREACH t IN ARRAY ARRAY{list(NEW_HISTORY)!r}::text[] LOOP
      EXECUTE format('GRANT SELECT, INSERT ON app.%I TO {APP_ROLE}', t);
      EXECUTE format(
        'CREATE POLICY runtime_access ON app.%I TO {APP_ROLE} USING (true) WITH CHECK (true)', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY{list(NEW_GUARDED)!r}::text[] LOOP
      EXECUTE format('GRANT SELECT, INSERT, UPDATE ON app.%I TO {APP_ROLE}', t);
      EXECUTE format(
        'CREATE POLICY runtime_access ON app.%I TO {APP_ROLE} USING (true) WITH CHECK (true)', t);
    END LOOP;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.score_set_guard() TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.championship_guard() TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.championship_round_guard() TO {APP_ROLE};
  END IF;
END $$;
"""

DOWN = rf"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.score_sets)
     OR EXISTS (SELECT 1 FROM app.round_scores)
     OR EXISTS (SELECT 1 FROM app.championships)
     OR EXISTS (SELECT 1 FROM app.championship_rounds)
     OR EXISTS (SELECT 1 FROM app.championship_versions) THEN
    RAISE EXCEPTION 'app_0007 downgrade refused: official competition results exist '
      'and the earlier schema cannot hold them (nothing was changed)'
      USING ERRCODE = 'object_in_use';
  END IF;
END $$;

DROP TABLE app.championship_standings;
DROP TABLE app.championship_versions;
DROP TABLE app.championship_rounds;
DROP TABLE app.championships;
DROP FUNCTION app.championship_round_guard();
DROP FUNCTION app.championship_guard();

CREATE TABLE app.championship_freezes (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  series_id         bigint NOT NULL REFERENCES app.championship_series (id),
  number            integer NOT NULL CHECK (number >= 1),
  frozen_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
  round_ids         uuid[] NOT NULL,
  standings         jsonb NOT NULL,
  champions         jsonb NOT NULL,
  content_hash      text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{{64}}$'),
  reopened_from_id  bigint REFERENCES app.championship_freezes (id),
  actor_user_id     uuid REFERENCES app.users (id),
  reason            text,
  CHECK (reopened_from_id IS NULL OR (actor_user_id IS NOT NULL AND reason IS NOT NULL))
);
CREATE INDEX ix_championship_freezes ON app.championship_freezes (series_id, number, frozen_at);
{_history("championship_freezes")}
REVOKE ALL ON app.championship_freezes FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT SELECT, INSERT ON app.championship_freezes TO {APP_ROLE};
    CREATE POLICY runtime_access ON app.championship_freezes TO {APP_ROLE}
      USING (true) WITH CHECK (true);
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {APP_ROLE};
  END IF;
END $$;

DROP INDEX app.ix_score_sets_round;
DROP INDEX app.ix_round_scores_user;
ALTER TABLE app.round_scores
  DROP CONSTRAINT round_scores_display_order_key,
  DROP CONSTRAINT round_scores_round_void_refund,
  DROP CONSTRAINT round_scores_round_void_kind,
  DROP CONSTRAINT round_scores_status_check,
  DROP COLUMN display_order;
ALTER TABLE app.round_scores
  ADD CONSTRAINT round_scores_status_check CHECK (status IN ('ranked', 'void_refunded'));

DROP TRIGGER score_sets_publishes_final ON app.score_sets;
DROP FUNCTION app.score_set_guard();
ALTER TABLE app.score_sets
  ALTER COLUMN final SET DEFAULT false,
  DROP CONSTRAINT score_sets_final_only,
  DROP CONSTRAINT score_sets_settlement_version_key,
  DROP COLUMN actor_user_id,
  DROP COLUMN published_at,
  DROP COLUMN scoring_version,
  DROP COLUMN settlement_version_id;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
