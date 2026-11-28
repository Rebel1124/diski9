"""Price editions, freshness evidence and rolling-entry integrity (Phase 8 CP3A-R, R2).

Revision ID: app_0010
Revises: app_0009
Create Date: 2026-11-28

The single consolidated migration agreed in CP3A-R.1 (refinement §14.8). Additive
and backward compatible; it changes no historical row and activates nothing (no
schedule row is written: rolling entry stays dormant until a separately authorised
activation).

1. **Editions.** ``round_snapshots.edition`` (existing snapshots become edition 1);
   ``UNIQUE (round_id)`` is replaced by ``UNIQUE (round_id, edition)``. Snapshot ids
   and every reference to them are unchanged.
2. **Edition guard** (BEFORE INSERT on ``round_snapshots``): edition 1 only for a
   draft round with no snapshot yet (publication, unchanged); a later edition only
   with the next consecutive number, for an open ``rolling/v1`` round, before its
   entry close by ``clock_timestamp()``.
3. **Row guard** (replaces ``snapshot_rows_guard``): edition 1 rows only while the
   round is a draft (unchanged); rows of a later edition only in the transaction that
   created that edition (never added to an existing edition), while the round is
   open and before its close. A later edition's fixtures must belong to edition 1
   (the published universe).
4. **Freshness evidence.** ``snapshot_offers.oldest_observation_at`` (new) and the
   existing ``provider_updated_at``: for editions written by R2, the oldest
   contributing observation and provider timestamps. Historical rows keep NULL
   (nothing is invented); their methodology is unchanged.
5. **Rolling submissions** (replaces ``submission_deadline_guard``): for a
   ``rolling/v1`` round, ``submitted_at := clock_timestamp()`` at insert (after the
   locks), which must be before the entry close, and the submission must use the
   round's current (latest) edition. Other rounds: unchanged (transaction timestamp,
   common deadline).
6. **Rolling selections** (new BEFORE INSERT trigger on ``submission_selections``):
   for a ``rolling/v1`` round, the fixture's kickoff **in the submission's own
   edition** must be later than ``submitted_at`` plus the schedule's buffer, and
   every copied value (odds, market and model probability, bucket, groups) must equal
   the edition's eligible offer.
7. **``submission_views``** (insert-only): the submission-time analytical record
   structure for R3 (P8-YV). Created empty; nothing is reconstructed for history.

Downgrade refuses (nothing changed) if any rolling-entry data exists: a later
edition, a ``rolling/v1`` round or a ``submission_views`` row. Otherwise it restores
the app_0009 structures exactly. Freshness evidence on other rounds' offers is
dropped with its column: their methodology never uses it and it is not part of any
snapshot fingerprint, so their stored snapshots still verify.
"""

from __future__ import annotations

from alembic import op

revision = "app_0010"
down_revision = "app_0009"
branch_labels = None
depends_on = None

APP_ROLE = "diski9_app"
ROLLING = "rolling/v1"

SETUP = """
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
"""

UP = rf"""
-- ================================================================ editions
ALTER TABLE app.round_snapshots
  ADD COLUMN edition integer NOT NULL DEFAULT 1 CHECK (edition >= 1);
ALTER TABLE app.round_snapshots DROP CONSTRAINT round_snapshots_round_id_key;
ALTER TABLE app.round_snapshots
  ADD CONSTRAINT uq_round_snapshots_edition UNIQUE (round_id, edition);

ALTER TABLE app.snapshot_offers ADD COLUMN oldest_observation_at timestamptz;
COMMENT ON COLUMN app.snapshot_offers.oldest_observation_at IS
  'Oldest genuine observation of the contributing quotes (R2; NULL for historical offers)';
COMMENT ON COLUMN app.snapshot_offers.provider_updated_at IS
  'Oldest provider update of the contributing quotes (R2; NULL for historical offers)';

CREATE FUNCTION app.round_snapshot_edition_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record; last_edition int;
BEGIN
  SELECT status, rules_version, deadline_at INTO r FROM app.rounds WHERE id = NEW.round_id;
  SELECT max(edition) INTO last_edition FROM app.round_snapshots WHERE round_id = NEW.round_id;
  IF NEW.edition = 1 THEN
    IF last_edition IS NOT NULL OR r.status IS DISTINCT FROM 'draft' THEN
      RAISE EXCEPTION 'app.round_snapshots: edition 1 is written once, while the round is a draft'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSE
    IF last_edition IS NULL OR NEW.edition <> last_edition + 1 THEN
      RAISE EXCEPTION 'app.round_snapshots: edition % does not follow edition %',
        NEW.edition, last_edition USING ERRCODE = 'check_violation';
    END IF;
    IF r.rules_version IS DISTINCT FROM '{ROLLING}' OR r.status IS DISTINCT FROM 'open'
       OR r.deadline_at IS NULL OR clock_timestamp() >= r.deadline_at THEN
      RAISE EXCEPTION 'app.round_snapshots: only an open rolling-entry round before its entry '
        'close takes new editions' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER round_snapshots_edition BEFORE INSERT ON app.round_snapshots
  FOR EACH ROW EXECUTE FUNCTION app.round_snapshot_edition_guard();

CREATE OR REPLACE FUNCTION app.snapshot_rows_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  SELECT rd.status, rd.rules_version, rd.deadline_at, s.edition, s.round_id,
         (s.xmin = pg_current_xact_id()::xid) AS mine
    INTO r FROM app.round_snapshots s JOIN app.rounds rd ON rd.id = s.round_id
   WHERE s.id = NEW.snapshot_id;
  IF r.edition IS NULL OR r.edition = 1 THEN
    IF r.status IS DISTINCT FROM 'draft' THEN
      RAISE EXCEPTION 'app.%: the snapshot of a published round cannot change', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
  END IF;
  IF NOT r.mine OR r.rules_version IS DISTINCT FROM '{ROLLING}'
     OR r.status IS DISTINCT FROM 'open' OR clock_timestamp() >= r.deadline_at THEN
    RAISE EXCEPTION 'app.%: an edition is written once, atomically, while its round is open',
      TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF TG_TABLE_NAME = 'snapshot_fixtures' AND NOT EXISTS (
       SELECT 1 FROM app.snapshot_fixtures f JOIN app.round_snapshots s1 ON s1.id = f.snapshot_id
        WHERE s1.round_id = r.round_id AND s1.edition = 1 AND f.fixture_id = NEW.fixture_id) THEN
    RAISE EXCEPTION 'app.snapshot_fixtures: fixture % is outside the published universe',
      NEW.fixture_id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

-- ================================================================ rolling submissions
CREATE OR REPLACE FUNCTION app.submission_deadline_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record; current_id bigint;
BEGIN
  SELECT status, deadline_at, rules_version INTO r FROM app.rounds WHERE id = NEW.round_id;
  IF r.rules_version = '{ROLLING}' THEN
    -- the authoritative submission time: the actual clock at insert, after every lock
    NEW.submitted_at := clock_timestamp();
    IF r.status IS DISTINCT FROM 'open' OR r.deadline_at IS NULL
       OR NEW.submitted_at >= r.deadline_at THEN
      RAISE EXCEPTION 'app.submissions: round % is not open for submissions (status %, entry '
        'close %)', NEW.round_id, r.status, r.deadline_at USING ERRCODE = 'check_violation';
    END IF;
    SELECT id INTO current_id FROM app.round_snapshots WHERE round_id = NEW.round_id
     ORDER BY edition DESC LIMIT 1;
    IF NEW.snapshot_id IS DISTINCT FROM current_id THEN
      RAISE EXCEPTION 'app.submissions: a rolling-entry submission must use the current edition'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF r.status IS DISTINCT FROM 'open' OR r.deadline_at IS NULL
     OR transaction_timestamp() >= r.deadline_at THEN
    RAISE EXCEPTION 'app.submissions: round % is not open for submissions (status %, deadline %)',
      NEW.round_id, r.status, r.deadline_at USING ERRCODE = 'check_violation';
  END IF;
  NEW.submitted_at := transaction_timestamp();
  RETURN NEW;
END $$;

CREATE FUNCTION app.rolling_selection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s record; ko timestamptz; o record;
BEGIN
  SELECT sub.submitted_at, rd.rules_version, sch.deadline_buffer_minutes AS buffer INTO s
    FROM app.submissions sub JOIN app.rounds rd ON rd.id = sub.round_id
    JOIN app.round_schedules sch ON sch.id = rd.schedule_id
   WHERE sub.id = NEW.submission_id;
  IF s.rules_version IS DISTINCT FROM '{ROLLING}' THEN
    RETURN NEW;
  END IF;
  SELECT kickoff_at_publish INTO ko FROM app.snapshot_fixtures
   WHERE snapshot_id = NEW.snapshot_id AND fixture_id = NEW.fixture_id;
  IF ko IS NULL OR ko <= s.submitted_at + make_interval(mins => s.buffer) THEN
    RAISE EXCEPTION 'app.submission_selections: fixture % kicks off within % minutes of the '
      'submission', NEW.fixture_id, s.buffer USING ERRCODE = 'check_violation';
  END IF;
  SELECT * INTO o FROM app.snapshot_offers
   WHERE snapshot_id = NEW.snapshot_id AND fixture_id = NEW.fixture_id
     AND market = NEW.market AND outcome = NEW.outcome;
  IF o IS NULL OR NOT o.eligible OR o.bucket IS DISTINCT FROM NEW.bucket
     OR o.consensus_odds IS DISTINCT FROM NEW.consensus_odds
     OR o.market_prob IS DISTINCT FROM NEW.market_prob
     OR o.model_prob IS DISTINCT FROM NEW.model_prob
     OR o.bookmaker_groups IS DISTINCT FROM NEW.bookmaker_groups THEN
    RAISE EXCEPTION 'app.submission_selections: the copied values of position % differ from '
      'the edition', NEW.position USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER submission_selections_rolling BEFORE INSERT ON app.submission_selections
  FOR EACH ROW EXECUTE FUNCTION app.rolling_selection_guard();

-- ================================================================ R3 foundation
CREATE TABLE app.submission_views (
  submission_id               uuid NOT NULL,
  position                    smallint NOT NULL,
  view_kind                   text NOT NULL CHECK (view_kind IN ('personal', 'fallback')),
  baseline_source             text NOT NULL
                              CHECK (baseline_source IN ('goal_model', 'market_implied', 'none')),
  methodology                 text,
  original_baseline_home      double precision,
  original_baseline_away      double precision,
  original_baseline_identity  jsonb,
  saved_goals_home            double precision,
  saved_goals_away            double precision,
  latest_baseline_home        double precision,
  latest_baseline_away        double precision,
  latest_baseline_identity    jsonb,
  personal_prob               double precision CHECK (personal_prob BETWEEN 0 AND 1),
  fallback_prob               double precision CHECK (fallback_prob BETWEEN 0 AND 1),
  fallback_source             text,
  created_at                  timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (submission_id, position),
  FOREIGN KEY (submission_id, position)
    REFERENCES app.submission_selections (submission_id, position),
  CHECK (view_kind <> 'personal' OR (saved_goals_home IS NOT NULL
         AND saved_goals_away IS NOT NULL AND personal_prob IS NOT NULL)),
  CHECK (view_kind <> 'fallback' OR (saved_goals_home IS NULL AND saved_goals_away IS NULL
         AND personal_prob IS NULL))
);
CREATE TRIGGER submission_views_insert_only BEFORE UPDATE OR DELETE ON app.submission_views
  FOR EACH ROW EXECUTE FUNCTION app.forbid_change();
CREATE TRIGGER submission_views_no_truncate BEFORE TRUNCATE ON app.submission_views
  FOR EACH STATEMENT EXECUTE FUNCTION app.forbid_change();
ALTER TABLE app.submission_views ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON app.submission_views FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.round_snapshot_edition_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.rolling_selection_guard() FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT SELECT, INSERT ON app.submission_views TO {APP_ROLE};
    CREATE POLICY runtime_access ON app.submission_views TO {APP_ROLE}
      USING (true) WITH CHECK (true);
    GRANT EXECUTE ON FUNCTION app.round_snapshot_edition_guard() TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.rolling_selection_guard() TO {APP_ROLE};
  END IF;
END $$;
"""

DOWN = rf"""
DO $$
DECLARE n_editions int; n_rolling int; n_views int;
BEGIN
  SELECT count(*) INTO n_editions FROM app.round_snapshots WHERE edition > 1;
  SELECT count(*) INTO n_rolling FROM app.rounds WHERE rules_version = '{ROLLING}';
  SELECT count(*) INTO n_views FROM app.submission_views;
  IF n_editions + n_rolling + n_views > 0 THEN
    RAISE EXCEPTION 'app_0010 downgrade refused: rolling-entry data exists (% later editions, % '
      'rolling rounds, % submission views); removing the structures would destroy it. '
      'Nothing was changed.', n_editions, n_rolling, n_views;
  END IF;
END $$;

DROP TABLE app.submission_views;
DROP TRIGGER submission_selections_rolling ON app.submission_selections;
DROP FUNCTION app.rolling_selection_guard();

CREATE OR REPLACE FUNCTION app.submission_deadline_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  SELECT status, deadline_at INTO r FROM app.rounds WHERE id = NEW.round_id;
  IF r.status IS DISTINCT FROM 'open' OR r.deadline_at IS NULL
     OR transaction_timestamp() >= r.deadline_at THEN
    RAISE EXCEPTION 'app.submissions: round % is not open for submissions (status %, deadline %)',
      NEW.round_id, r.status, r.deadline_at USING ERRCODE = 'check_violation';
  END IF;
  NEW.submitted_at := transaction_timestamp();
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION app.snapshot_rows_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE st text;
BEGIN
  SELECT r.status INTO st FROM app.round_snapshots s JOIN app.rounds r ON r.id = s.round_id
   WHERE s.id = NEW.snapshot_id;
  IF st IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'app.%: the snapshot of a published round cannot change', TG_TABLE_NAME
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER round_snapshots_edition ON app.round_snapshots;
DROP FUNCTION app.round_snapshot_edition_guard();
COMMENT ON COLUMN app.snapshot_offers.provider_updated_at IS NULL;
ALTER TABLE app.snapshot_offers DROP COLUMN oldest_observation_at;
ALTER TABLE app.round_snapshots DROP CONSTRAINT uq_round_snapshots_edition;
ALTER TABLE app.round_snapshots ADD CONSTRAINT round_snapshots_round_id_key UNIQUE (round_id);
ALTER TABLE app.round_snapshots DROP COLUMN edition;
"""


def upgrade() -> None:
    op.execute(SETUP)
    op.execute(UP)


def downgrade() -> None:
    op.execute(SETUP)
    op.execute(DOWN)
