"""Schedule integrity safeguards (Scenario A3, Checkpoint 4B).

Revision ID: app_0008
Revises: app_0007
Create Date: 2026-11-24

Safeguards only: no schedule, round or configuration data is changed, and nothing
is activated. Only schema ``app`` (plus the shared ``btree_gist`` extension).

Schedule rows (``app.round_schedules``) are valid on ``[active_from, active_to)``.

1. **Audit first.** The upgrade refuses, installing nothing, if existing data
   already violates a rule below:
   * overlapping intervals within a code;
   * a gap, wrong order or several open-ended rows within a code;
   * a round bound to a schedule row that was not valid at its ``created_at``.
   It never repairs rows, changes timestamps, rebinds rounds or makes exemptions.
2. **No overlaps:** ``EXCLUDE USING gist (code WITH =, tstzrange(active_from,
   active_to, '[)') WITH &&)`` (``btree_gist``, created if absent; never dropped).
3. **One open-ended row per code:** a partial unique index.
4. **Contiguous and chronological:** a deferred constraint trigger checks the
   affected code at commit. Ordered by version, each row's ``active_to`` must equal
   the next row's ``active_from``, and only the highest version may be open-ended.
5. **Referenced rows are protected:**
   * a row used by any round can never be deleted, and no column may change except
     ``active_to``;
   * ``active_to`` may be set **once** from NULL, and only to an instant strictly
     after the latest ``created_at`` of its rounds (half-open: equality is refused);
   * it may be reopened (back to NULL) only when no later version of the code
     remains (the undo of an unused activation).
6. **Validity at round insertion:** a BEFORE INSERT trigger on ``app.rounds``
   refuses a ``schedule_id`` that is not valid at the new row's ``created_at``.
   ``app.rounds.schedule_id`` and ``created_at`` become immutable (``app.set_once``;
   both are NOT NULL).
7. **One locking protocol** (transaction-level advisory lock, key
   ``hashtextextended('diski9.round_schedules', 0)``):
   * every statement that writes ``round_schedules`` (any role, any path) takes the
     **exclusive** form through a statement trigger;
   * every round insertion takes the **shared** form in its trigger, and the
     application takes it before resolving the schedule.

   Writers and creators therefore never interleave, while creators run in parallel.
   Both checks require READ COMMITTED: their queries take a fresh snapshot after the
   lock is granted, so they see every change committed before (the transaction
   timestamp, and so ``created_at``, stays fixed, but the data read does not).
   Writers should call ``app.schedule_write_lock()`` as their first statement.
8. **Privileges:** the runtime role keeps SELECT on ``round_schedules`` but loses
   INSERT, UPDATE and DELETE (schedules change only through migrations).

**Migration-time locking (Checkpoint 4B refinement).** The audit and the
installation run under table locks taken as the revision's first statements and held
until it commits:
* ``ACCESS EXCLUSIVE`` on ``round_schedules``: no reads or writes for the few
  milliseconds the migration runs; the exclusion constraint needs this lock anyway;
* ``SHARE ROW EXCLUSIVE`` on ``rounds``: readers continue, every INSERT, UPDATE and
  DELETE waits; ``CREATE TRIGGER`` needs this lock anyway.

So no write can land between the audit and the safeguards becoming effective. That
covers older application versions and direct SQL writers that do not use the
advisory protocol, and privileged roles too: table locks bind everyone. The locks
also wait for every in-flight writer to finish first, so the audit sees all committed
data.

Order and limits:
* the locks are taken schedules-then-rounds, and nothing else is taken first;
* ``lock_timeout`` is 10 s: if long-running transactions hold conflicting locks, the
  revision fails with nothing changed instead of queueing application writers
  behind it;
* READ COMMITTED is required, so the audit's snapshot is taken after the locks are
  granted.

Run it in a maintenance window with application writers (web and scheduler)
quiesced; see the implementation record.

Downgrade removes exactly these safeguards and restores the runtime role's previous
INSERT, UPDATE and DELETE privileges. It changes no data, never drops the shared
extension, and uses no CASCADE.
"""

from __future__ import annotations

from alembic import op

revision = "app_0008"
down_revision = "app_0007"
branch_labels = None
depends_on = None

APP_ROLE = "diski9_app"
LOCK_KEY = "hashtextextended('diski9.round_schedules', 0)"

# First statements of the revision: freeze schedule and round writes for the audit and
# the installation (held until the revision commits; see the module docstring).
LOCKS = r"""
DO $$
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'app_0008 must run at READ COMMITTED (this transaction is %)',
      current_setting('transaction_isolation');
  END IF;
END $$;
SET LOCAL lock_timeout = '10s';
LOCK TABLE app.round_schedules IN ACCESS EXCLUSIVE MODE;
LOCK TABLE app.rounds IN SHARE ROW EXCLUSIVE MODE;
"""

AUDIT = r"""
DO $$
DECLARE
  problems text := '';
  n int;
  ex text;
BEGIN
  -- overlapping intervals within a code
  SELECT count(*), string_agg(format('%s v%s/v%s', a.code, a.version, b.version), '; ')
    INTO n, ex
    FROM (SELECT * FROM app.round_schedules) a
    JOIN app.round_schedules b ON a.code = b.code AND a.version < b.version
   WHERE tstzrange(a.active_from, a.active_to, '[)')
         && tstzrange(b.active_from, b.active_to, '[)');
  IF n > 0 THEN
    problems := problems || format(' overlapping versions (%s): %s.', n, left(ex, 300));
  END IF;

  -- gaps, wrong order, closed last version or open earlier versions within a code
  WITH o AS (
    SELECT code, version, active_from, active_to,
           lead(active_from) OVER w AS next_from,
           lead(version) OVER w AS next_version
      FROM app.round_schedules WINDOW w AS (PARTITION BY code ORDER BY version))
  SELECT count(*), string_agg(format('%s v%s', code, version), '; ')
    INTO n, ex
    FROM o
   WHERE (next_version IS NULL AND active_to IS NOT NULL)
      OR (next_version IS NOT NULL AND (active_to IS NULL OR active_to <> next_from));
  IF n > 0 THEN
    problems := problems || format(' non-contiguous versions (%s): %s.', n, left(ex, 300));
  END IF;

  -- rounds bound to a schedule row that was not valid at their creation
  SELECT count(*),
         string_agg(format('%s (%s v%s at %s)', r.code, s.code, s.version, r.created_at), '; ')
    INTO n, ex
    FROM app.rounds r JOIN app.round_schedules s ON s.id = r.schedule_id
   WHERE NOT (s.active_from <= r.created_at
              AND (s.active_to IS NULL OR r.created_at < s.active_to));
  IF n > 0 THEN
    problems := problems
      || format(' rounds outside their schedule validity (%s): %s.', n, left(ex, 300));
  END IF;

  IF problems <> '' THEN
    RAISE EXCEPTION 'app_0008 upgrade refused: existing data violates the schedule rules;%'
      '  Nothing was changed. Resolve with an owner decision (no automatic repair).',
      problems;
  END IF;
END $$;
"""

UP = rf"""
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ------------------------------------------------------------ locking protocol
CREATE FUNCTION app.require_read_committed(what text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION '% must run at READ COMMITTED (this transaction is %): its checks need '
      'a fresh snapshot after the schedule lock is granted',
      what, current_setting('transaction_isolation')
      USING ERRCODE = 'object_not_in_prerequisite_state';
  END IF;
END $$;

CREATE FUNCTION app.schedule_write_lock() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  PERFORM app.require_read_committed('A schedule change');
  PERFORM pg_advisory_xact_lock({LOCK_KEY});
END $$;

CREATE FUNCTION app.schedule_read_lock() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  PERFORM app.require_read_committed('Round creation');
  PERFORM pg_advisory_xact_lock_shared({LOCK_KEY});
END $$;

-- every write to round_schedules, whatever the role or path, takes the exclusive lock
CREATE FUNCTION app.round_schedules_write_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM app.schedule_write_lock();
  RETURN NULL;
END $$;

-- ------------------------------------------------------------ contiguity (deferred)
CREATE FUNCTION app.check_schedule_contiguity(c text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE prev app.round_schedules; cur app.round_schedules;
BEGIN
  FOR cur IN SELECT * FROM app.round_schedules WHERE code = c ORDER BY version LOOP
    IF prev.id IS NOT NULL THEN
      IF prev.active_to IS NULL THEN
        RAISE EXCEPTION 'app.round_schedules: %: only the highest version may be '
          'open-ended (v% is open, v% follows)', c, prev.version, cur.version
          USING ERRCODE = 'integrity_constraint_violation';
      END IF;
      IF prev.active_to <> cur.active_from THEN
        RAISE EXCEPTION 'app.round_schedules: %: v% must start exactly when v% ends '
          '(% vs %): no gaps, no overlaps, chronological order',
          c, cur.version, prev.version, cur.active_from, prev.active_to
          USING ERRCODE = 'integrity_constraint_violation';
      END IF;
    END IF;
    prev := cur;
  END LOOP;
  IF prev.id IS NOT NULL AND prev.active_to IS NOT NULL THEN
    RAISE EXCEPTION 'app.round_schedules: %: the highest version (v%) must be open-ended '
      '(exactly one open-ended row per code)', c, prev.version
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
END $$;

CREATE FUNCTION app.round_schedules_contiguity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM app.require_read_committed('A schedule change');
  IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM app.check_schedule_contiguity(OLD.code); END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM app.check_schedule_contiguity(NEW.code); END IF;
  RETURN NULL;
END $$;

-- ------------------------------------------------------------ referenced rows
CREATE FUNCTION app.round_schedules_row_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE latest timestamptz; probe app.round_schedules;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM app.rounds WHERE schedule_id = OLD.id) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'app.round_schedules: % v% is used by rounds and can never be deleted',
      OLD.code, OLD.version
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  probe := NEW;
  probe.active_to := OLD.active_to;
  IF probe IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'app.round_schedules: % v% is used by rounds; only its closing time '
      '(active_to) may be set', OLD.code, OLD.version
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF OLD.active_to IS NULL AND NEW.active_to IS NOT NULL THEN
    SELECT max(created_at) INTO latest FROM app.rounds WHERE schedule_id = OLD.id;
    IF NEW.active_to <= latest THEN
      RAISE EXCEPTION 'app.round_schedules: % v% cannot close at % : a round bound to it '
        'was created at % (the closing time must be strictly later)',
        OLD.code, OLD.version, NEW.active_to, latest
        USING ERRCODE = 'integrity_constraint_violation';
    END IF;
  ELSIF OLD.active_to IS NOT NULL AND NEW.active_to IS NULL THEN
    IF EXISTS (SELECT 1 FROM app.round_schedules
                WHERE code = OLD.code AND id <> OLD.id AND active_from >= OLD.active_to) THEN
      RAISE EXCEPTION 'app.round_schedules: % v% may be reopened only after every later '
        'version is removed', OLD.code, OLD.version
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  ELSIF OLD.active_to IS DISTINCT FROM NEW.active_to THEN
    RAISE EXCEPTION 'app.round_schedules: % v% is used by rounds; its closing time is set '
      'once and cannot change', OLD.code, OLD.version
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

-- ------------------------------------------------------------ rounds: validity at insertion
CREATE FUNCTION app.round_schedule_valid() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM app.schedule_read_lock();
  IF NOT EXISTS (
    SELECT 1 FROM app.round_schedules s
     WHERE s.id = NEW.schedule_id AND s.active_from <= NEW.created_at
       AND (s.active_to IS NULL OR NEW.created_at < s.active_to)) THEN
    RAISE EXCEPTION 'app.rounds: schedule % is not valid at the round''s creation time %',
      NEW.schedule_id, NEW.created_at
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $$;

-- ------------------------------------------------------------ constraints and triggers
ALTER TABLE app.round_schedules ADD CONSTRAINT round_schedules_no_overlap
  EXCLUDE USING gist (code WITH =, tstzrange(active_from, active_to, '[)') WITH &&);
CREATE UNIQUE INDEX round_schedules_one_open ON app.round_schedules (code) WHERE active_to IS NULL;

CREATE TRIGGER round_schedules_write_lock BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
  ON app.round_schedules FOR EACH STATEMENT EXECUTE FUNCTION app.round_schedules_write_lock();
CREATE TRIGGER round_schedules_row_guard BEFORE UPDATE OR DELETE ON app.round_schedules
  FOR EACH ROW EXECUTE FUNCTION app.round_schedules_row_guard();
CREATE CONSTRAINT TRIGGER round_schedules_contiguous AFTER INSERT OR UPDATE OR DELETE
  ON app.round_schedules DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION app.round_schedules_contiguity();
CREATE TRIGGER rounds_schedule_valid BEFORE INSERT ON app.rounds
  FOR EACH ROW EXECUTE FUNCTION app.round_schedule_valid();
CREATE TRIGGER rounds_identity_immutable BEFORE UPDATE ON app.rounds
  FOR EACH ROW EXECUTE FUNCTION app.set_once('schedule_id', 'created_at');

REVOKE EXECUTE ON FUNCTION app.schedule_write_lock() FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    REVOKE INSERT, UPDATE, DELETE ON app.round_schedules FROM {APP_ROLE};
    GRANT SELECT ON app.round_schedules TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.schedule_read_lock(), app.require_read_committed(text),
      app.round_schedule_valid() TO {APP_ROLE};
  END IF;
END $$;
"""

DOWN = rf"""
DROP TRIGGER rounds_identity_immutable ON app.rounds;
DROP TRIGGER rounds_schedule_valid ON app.rounds;
DROP TRIGGER round_schedules_contiguous ON app.round_schedules;
DROP TRIGGER round_schedules_row_guard ON app.round_schedules;
DROP TRIGGER round_schedules_write_lock ON app.round_schedules;
DROP INDEX app.round_schedules_one_open;
ALTER TABLE app.round_schedules DROP CONSTRAINT round_schedules_no_overlap;
DROP FUNCTION app.round_schedule_valid();
DROP FUNCTION app.round_schedules_row_guard();
DROP FUNCTION app.round_schedules_contiguity();
DROP FUNCTION app.check_schedule_contiguity(text);
DROP FUNCTION app.round_schedules_write_lock();
DROP FUNCTION app.schedule_read_lock();
DROP FUNCTION app.schedule_write_lock();
DROP FUNCTION app.require_read_committed(text);
-- the shared btree_gist extension is deliberately kept
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.round_schedules TO {APP_ROLE};
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(LOCKS)  # before the audit; held through installation until commit
    op.execute(AUDIT)
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
