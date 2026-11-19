"""Authentication foundations (Phase 6C.2): provider-linked server-side sessions,
authentication rate-limit events, the beta terms version, and defence in depth
for Supabase-hosted PostgreSQL (row-level security on every ``app`` table with
access only for the runtime role; nothing granted to Supabase's browser-facing
roles).

Revision ID: app_0002
Revises: app_0001
Create Date: 2026-11-19

This migration never touches Supabase-managed schemas (``auth``, ``storage``,
...). It only changes schema ``app``.
"""

from __future__ import annotations

from alembic import op

revision = "app_0002"
down_revision = "app_0001"
branch_labels = None
depends_on = None

APP_ROLE = "diski9_app"
# Supabase roles that serve the Data API, GraphQL and Realtime to browsers.
BROWSER_ROLES = ("anon", "authenticated")
TERMS_VERSION = "beta-2026-11"
TERMS_SHA256 = "d15eb61224a6dba72461cb06ef610e2a91d4a7e4860a85b051d69ce0731876f2"

UP = rf"""
ALTER TABLE app.app_sessions
  ADD COLUMN provider_session_id uuid,
  ADD COLUMN provider_refresh_token_enc text,
  ADD COLUMN provider_access_token_enc text,
  ADD COLUMN provider_access_expires_at timestamptz,
  ADD COLUMN provider_checked_at timestamptz,
  ADD COLUMN reauthenticated_at timestamptz,
  ADD COLUMN revoked_reason text
    CHECK (revoked_reason IN ('sign_out', 'sign_out_everywhere', 'rotated', 'expired_idle',
                              'expired_absolute', 'account_suspended', 'provider_session_ended',
                              'password_changed', 'operator'));
CREATE INDEX ix_app_sessions_provider_session ON app.app_sessions (provider_session_id);

CREATE TABLE app.auth_rate_events (
  id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  bucket    text NOT NULL CHECK (bucket ~ '^[a-z][a-z0-9_.:-]*$'),
  key_hash  text NOT NULL CHECK (key_hash ~ '^[0-9a-f]{{64}}$'),
  at        timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ix_auth_rate_events ON app.auth_rate_events (bucket, key_hash, at);

INSERT INTO app.terms_versions (version, published_at, content_hash, minimum_age,
                                requires_reacceptance)
VALUES ('{TERMS_VERSION}', '2026-11-19T00:00:00Z', '{TERMS_SHA256}', 18, false);
"""


def _rls_and_grants() -> str:
    return rf"""
DO $$
DECLARE t record; r text;
BEGIN
  -- nothing in schema app is for PUBLIC or the browser-facing Supabase roles
  REVOKE ALL ON SCHEMA app FROM PUBLIC;
  REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC;
  REVOKE ALL ON ALL SEQUENCES IN SCHEMA app FROM PUBLIC;
  REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC;
  FOREACH r IN ARRAY ARRAY{list(BROWSER_ROLES)!r}::text[] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA app FROM %I', r);
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA app FROM %I', r);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA app FROM %I', r);
      EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA app FROM %I', r);
    END IF;
  END LOOP;

  -- row-level security everywhere; the owner (migrations) bypasses it, the runtime
  -- role gets an explicit policy, every other role sees nothing
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'app' LOOP
    EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
      EXECUTE format(
        'CREATE POLICY runtime_access ON app.%I TO {APP_ROLE} USING (true) WITH CHECK (true)',
        t.tablename);
    END IF;
  END LOOP;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT SELECT, INSERT, DELETE ON app.auth_rate_events TO {APP_ROLE};
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {APP_ROLE};
  END IF;
END $$;
"""


DOWN = rf"""
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'app' LOOP
    EXECUTE format('DROP POLICY IF EXISTS runtime_access ON app.%I', t.tablename);
    EXECUTE format('ALTER TABLE app.%I DISABLE ROW LEVEL SECURITY', t.tablename);
  END LOOP;
END $$;
DROP TABLE app.auth_rate_events;
-- acceptances are insert-only history: keep the version if anyone accepted it
DELETE FROM app.terms_versions WHERE version = '{TERMS_VERSION}'
  AND NOT EXISTS (SELECT 1 FROM app.terms_acceptances WHERE terms_version = '{TERMS_VERSION}');
DROP INDEX app.ix_app_sessions_provider_session;
ALTER TABLE app.app_sessions
  DROP COLUMN provider_session_id,
  DROP COLUMN provider_refresh_token_enc,
  DROP COLUMN provider_access_token_enc,
  DROP COLUMN provider_access_expires_at,
  DROP COLUMN provider_checked_at,
  DROP COLUMN reauthenticated_at,
  DROP COLUMN revoked_reason;
"""


def upgrade() -> None:
    op.execute(UP)
    op.execute(_rls_and_grants())


def downgrade() -> None:
    op.execute(DOWN)
