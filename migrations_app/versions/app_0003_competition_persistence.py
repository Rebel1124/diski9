"""Competition persistence (Phase 6C.3): optimistic versions for drafts and Your
View, a development-round flag, and database-clock guards for snapshot
immutability and draft deadlines.

Revision ID: app_0003
Revises: app_0002
Create Date: 2026-11-19

Additive only. Never touches Supabase-managed schemas; only schema ``app``.
"""

from __future__ import annotations

from alembic import op

revision = "app_0003"
down_revision = "app_0002"
branch_labels = None
depends_on = None

APP_ROLE = "diski9_app"

ROUND_SET_ONCE = (
    "published_at",
    "deadline_at",
    "settle_cutoff_at",
    "finalised_at",
    "config_version",
    "rules_version",
    "scoring_version",
    "model_version",
)


def _round_set_once(extra: tuple[str, ...] = ()) -> str:
    args = ", ".join(f"'{c}'" for c in (*ROUND_SET_ONCE, *extra))
    return (
        "DROP TRIGGER rounds_set_once ON app.rounds;\n"
        "CREATE TRIGGER rounds_set_once BEFORE UPDATE ON app.rounds "
        f"FOR EACH ROW EXECUTE FUNCTION app.set_once({args});"
    )


UP = rf"""
-- optimistic concurrency: a save names the version it was based on
ALTER TABLE app.portfolio_drafts
  ADD COLUMN version integer NOT NULL DEFAULT 0 CHECK (version >= 0);
ALTER TABLE app.your_view_adjustments
  ADD COLUMN version integer NOT NULL DEFAULT 0 CHECK (version >= 0);

-- development rounds are distinguishable from real competition rounds
ALTER TABLE app.rounds ADD COLUMN is_development boolean NOT NULL DEFAULT false;
{_round_set_once(("is_development",))}

-- a published snapshot cannot gain fixtures or offers
CREATE FUNCTION app.snapshot_rows_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER snapshot_fixtures_draft_only BEFORE INSERT ON app.snapshot_fixtures
  FOR EACH ROW EXECUTE FUNCTION app.snapshot_rows_guard();
CREATE TRIGGER snapshot_offers_draft_only BEFORE INSERT ON app.snapshot_offers
  FOR EACH ROW EXECUTE FUNCTION app.snapshot_rows_guard();

-- drafts change only while the round is open and before its deadline (database clock)
CREATE FUNCTION app.draft_deadline_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  SELECT status, deadline_at INTO r FROM app.rounds WHERE id = NEW.round_id;
  IF r.status IS DISTINCT FROM 'open' OR r.deadline_at IS NULL
     OR transaction_timestamp() >= r.deadline_at THEN
    RAISE EXCEPTION 'app.portfolio_drafts: round % is not open for changes', NEW.round_id
      USING ERRCODE = 'check_violation';
  END IF;
  NEW.updated_at := transaction_timestamp();
  RETURN NEW;
END $$;
CREATE TRIGGER portfolio_drafts_deadline BEFORE INSERT OR UPDATE ON app.portfolio_drafts
  FOR EACH ROW EXECUTE FUNCTION app.draft_deadline_guard();

REVOKE EXECUTE ON FUNCTION app.snapshot_rows_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.draft_deadline_guard() FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT EXECUTE ON FUNCTION app.snapshot_rows_guard() TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.draft_deadline_guard() TO {APP_ROLE};
  END IF;
END $$;
"""

DOWN = rf"""
DROP TRIGGER portfolio_drafts_deadline ON app.portfolio_drafts;
DROP FUNCTION app.draft_deadline_guard();
DROP TRIGGER snapshot_offers_draft_only ON app.snapshot_offers;
DROP TRIGGER snapshot_fixtures_draft_only ON app.snapshot_fixtures;
DROP FUNCTION app.snapshot_rows_guard();
{_round_set_once()}
ALTER TABLE app.rounds DROP COLUMN is_development;
ALTER TABLE app.your_view_adjustments DROP COLUMN version;
ALTER TABLE app.portfolio_drafts DROP COLUMN version;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
