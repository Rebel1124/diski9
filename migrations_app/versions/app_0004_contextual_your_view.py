"""Checkpoint refinements (Phase 6C.3): Your View per analytical context, Friday
publication schedule (D-11 revision), and development rounds kept out of the
official series.

Revision ID: app_0004
Revises: app_0003
Create Date: 2026-11-19

Your View identity becomes (user, fixture, context):

* ``live``   - the current Match Lab context (All Upcoming Fixtures), one row per
  user and fixture, ``snapshot_id`` NULL;
* ``round``  - a published round's frozen context, one row per user, fixture and
  snapshot, ``snapshot_id`` referencing the snapshot's fixture (so the fixture
  must be on that snapshot);
* ``unassigned`` - rows saved before this revision. Their stamps cannot tell a live
  context from a frozen one, so they are kept unchanged but never applied
  (documented in docs/architecture/phase6c3_implementation.md).

Only the current numbers per context are stored; this is not a history (D-41).
Additive apart from replacing the old primary key (user, fixture) by a surrogate
key plus the contextual unique constraint. Never touches Supabase schemas.
"""

from __future__ import annotations

from alembic import op

revision = "app_0004"
down_revision = "app_0003"
branch_labels = None
depends_on = None

APP_ROLE = "diski9_app"

UP = rf"""
ALTER TABLE app.your_view_adjustments
  ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY,
  ADD COLUMN context_kind text NOT NULL DEFAULT 'unassigned'
    CHECK (context_kind IN ('live', 'round', 'unassigned')),
  ADD COLUMN snapshot_id bigint;
ALTER TABLE app.your_view_adjustments ALTER COLUMN context_kind DROP DEFAULT;
ALTER TABLE app.your_view_adjustments DROP CONSTRAINT your_view_adjustments_pkey;
ALTER TABLE app.your_view_adjustments
  ADD CONSTRAINT your_view_adjustments_pkey PRIMARY KEY (id),
  ADD CONSTRAINT your_view_context_snapshot
    CHECK ((context_kind = 'round') = (snapshot_id IS NOT NULL)),
  ADD CONSTRAINT your_view_snapshot_fixture
    FOREIGN KEY (snapshot_id, fixture_id)
    REFERENCES app.snapshot_fixtures (snapshot_id, fixture_id),
  ADD CONSTRAINT uq_your_view_context
    UNIQUE NULLS NOT DISTINCT (user_id, fixture_id, context_kind, snapshot_id);
CREATE INDEX ix_your_view_user_snapshot ON app.your_view_adjustments (user_id, snapshot_id);

-- D-11 revision: standard weekend publication target Friday 08:00 SAST (schedule v2)
UPDATE app.round_schedules SET active_to = now()
 WHERE code = 'weekend' AND version = 1 AND active_to IS NULL
   AND NOT EXISTS (SELECT 1 FROM app.round_schedules WHERE code = 'weekend' AND version = 2);
INSERT INTO app.round_schedules (
  code, version, timezone, eligible_competitions, window_rule, publish_rule,
  deadline_buffer_minutes, settle_cutoff_hours, correction_window_hours,
  config_version, rules_version, scoring_version, series_id, active_from)
SELECT code, 2, timezone, eligible_competitions, window_rule,
  '{{"weekday": "friday", "time": "08:00", "tz": "Africa/Johannesburg"}}'::jsonb,
  deadline_buffer_minutes, settle_cutoff_hours, correction_window_hours,
  config_version, rules_version, scoring_version, series_id, now()
FROM app.round_schedules WHERE code = 'weekend' AND version = 1
  AND NOT EXISTS (SELECT 1 FROM app.round_schedules WHERE code = 'weekend' AND version = 2);

-- development rounds can never belong to the official series (D-38)
CREATE FUNCTION app.development_round_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.is_development AND EXISTS (
       SELECT 1 FROM app.championship_series s WHERE s.id = NEW.series_id
        AND s.code = 'official') THEN
    RAISE EXCEPTION 'app.rounds: a development round cannot belong to the official series'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rounds_development_series BEFORE INSERT OR UPDATE ON app.rounds
  FOR EACH ROW EXECUTE FUNCTION app.development_round_guard();
REVOKE EXECUTE ON FUNCTION app.development_round_guard() FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT EXECUTE ON FUNCTION app.development_round_guard() TO {APP_ROLE};
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {APP_ROLE};
  END IF;
END $$;
"""

DOWN = r"""
DROP TRIGGER rounds_development_series ON app.rounds;
DROP FUNCTION app.development_round_guard();
DELETE FROM app.round_schedules s WHERE s.code = 'weekend' AND s.version = 2
  AND NOT EXISTS (SELECT 1 FROM app.rounds r WHERE r.schedule_id = s.id);
UPDATE app.round_schedules SET active_to = NULL WHERE code = 'weekend' AND version = 1
  AND NOT EXISTS (SELECT 1 FROM app.round_schedules WHERE code = 'weekend' AND version = 2);

-- back to one row per user and fixture: frozen-context rows cannot be represented
-- there and are removed; of the rest, the most recently updated row is kept
DELETE FROM app.your_view_adjustments WHERE context_kind = 'round';
DELETE FROM app.your_view_adjustments a USING app.your_view_adjustments b
 WHERE a.user_id = b.user_id AND a.fixture_id = b.fixture_id
   AND (a.updated_at, a.id) < (b.updated_at, b.id);
DROP INDEX app.ix_your_view_user_snapshot;
ALTER TABLE app.your_view_adjustments
  DROP CONSTRAINT uq_your_view_context,
  DROP CONSTRAINT your_view_snapshot_fixture,
  DROP CONSTRAINT your_view_context_snapshot,
  DROP CONSTRAINT your_view_adjustments_pkey;
ALTER TABLE app.your_view_adjustments
  ADD CONSTRAINT your_view_adjustments_pkey PRIMARY KEY (user_id, fixture_id),
  DROP COLUMN snapshot_id,
  DROP COLUMN context_kind,
  DROP COLUMN id;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
