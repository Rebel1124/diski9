-- Runs once, when the local volume is first created (docker compose up).
-- Creates the separate test database and the runtime role that receives the
-- restricted privileges granted by the competition migrations.
CREATE DATABASE diski9_test;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'diski9_app') THEN
    -- NOLOGIN: local development connects as the owner; deployments create a
    -- login user and GRANT diski9_app to it (docs/backend.md).
    CREATE ROLE diski9_app NOLOGIN;
  END IF;
END $$;
