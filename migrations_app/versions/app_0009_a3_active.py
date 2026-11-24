"""Scenario A3 active from day one (Checkpoint 4C, simplified: Option D).

Revision ID: app_0009
Revises: app_0008
Create Date: 2026-11-24

Makes ``a3-432-v1`` the configuration of new ``weekend`` rounds **from the moment
this migration runs**, the same pattern ``app_0004`` used for the Friday schedule:

* ``weekend`` v2 (``broad60-432-v1``) closes at this transaction's timestamp
  (``now()``);
* ``weekend`` v3 opens at that same instant with ``a3-432-v1``. Every other
  attribute is copied from v2: timezone, eligible competitions, window and
  publication rules, deadline buffer, settlement cutoff, correction window,
  settlement rules, scoring and championship series (Beta).

No future-dated activation, administrative command or cancellation: the original
4C transition proposal was superseded (owner decision, Option D). Rounds created
before the migration, published or still drafts, keep their v2 (broad60) binding.
A round's binding is fixed by its ``created_at`` (the transaction timestamp,
Checkpoint 4A).

Safety:
* the first data statement takes ``app.schedule_write_lock()``, the exclusive
  advisory lock of the app_0008 protocol (READ COMMITTED is required by it). **No
  explicit table locks**: an explicit table lock after the advisory lock deadlocks
  against direct SQL round inserts (SQLSTATE 40P01, Checkpoint 4C experiment);
* bounded waiting: ``lock_timeout`` 10 s and ``statement_timeout`` 30 s;
* strict preconditions, refused with nothing changed (never skipped or repaired):
  exactly one open-ended ``weekend`` row, which is v2 on ``broad60-432-v1`` with
  ``settle/v1`` and ``points-150-75-v2``, and no later version;
* the app_0008 safeguards then enforce integrity. The row guard refuses to close
  v2 if a v2 round was created at or after ``now()``. The exclusion constraint,
  the one-open-row index and the deferred contiguity check (at commit) apply. Any
  failure rolls the whole revision back;
* both configurations must be registered in the running code with their approved
  fingerprints.

Downgrade (never in production: ``diski9 app-db downgrade`` refuses there) removes v3
and reopens v2, atomically. It refuses if any round is bound to v3: from then on the
change is forward-only (historical bindings are immutable).
"""

from __future__ import annotations

from alembic import op

revision = "app_0009"
down_revision = "app_0008"
branch_labels = None
depends_on = None

APPROVED_FINGERPRINTS = {
    "broad60-432-v1": "b8cb7c0372e6aac15b1638e100be35955dacfd3f11c1f3654ad52c9263cbba94",
    "a3-432-v1": "91dba48a002a4fed3dc340764ef1717228f7dea61401f29621e799de401b094e",
}

SETUP = """
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '30s';
SELECT app.schedule_write_lock();
"""

COPIED = ("timezone, eligible_competitions, window_rule, publish_rule, deadline_buffer_minutes, "
          "settle_cutoff_hours, correction_window_hours, rules_version, scoring_version, "
          "series_id")  # fmt: skip

UP = rf"""
DO $$
DECLARE
  n_open int; open_v int; n_later int; v2 app.round_schedules;
BEGIN
  SELECT count(*), max(version) INTO n_open, open_v
    FROM app.round_schedules WHERE code = 'weekend' AND active_to IS NULL;
  SELECT count(*) INTO n_later FROM app.round_schedules WHERE code = 'weekend' AND version > 2;
  SELECT * INTO v2 FROM app.round_schedules WHERE code = 'weekend' AND version = 2;
  IF n_open <> 1 OR open_v <> 2 OR n_later <> 0 OR v2.id IS NULL
     OR v2.config_version <> 'broad60-432-v1' OR v2.rules_version <> 'settle/v1'
     OR v2.scoring_version <> 'points-150-75-v2' THEN
    RAISE EXCEPTION 'app_0009 refused: weekend schedule is not in the expected state (exactly '
      'one open-ended row, v2 on broad60-432-v1 / settle/v1 / points-150-75-v2, no later '
      'version): % open-ended (latest open v%), % later version(s), v2 config %. Nothing was '
      'changed.', n_open, open_v, n_later, v2.config_version;
  END IF;
  -- close v2 first: the exclusion constraint and the one-open-row index are immediate
  UPDATE app.round_schedules SET active_to = now() WHERE id = v2.id AND active_to IS NULL;
  INSERT INTO app.round_schedules (code, version, {COPIED}, config_version, active_from)
  SELECT code, 3, {COPIED}, 'a3-432-v1', now() FROM app.round_schedules WHERE id = v2.id;
END $$;
"""

DOWN = r"""
DO $$
DECLARE
  v2 app.round_schedules; v3 app.round_schedules; n int;
BEGIN
  SELECT * INTO v2 FROM app.round_schedules WHERE code = 'weekend' AND version = 2;
  SELECT * INTO v3 FROM app.round_schedules WHERE code = 'weekend' AND version = 3;
  IF v3.id IS NULL OR v3.config_version <> 'a3-432-v1' OR v3.active_to IS NOT NULL
     OR v2.id IS NULL OR v2.active_to IS DISTINCT FROM v3.active_from
     OR EXISTS (SELECT 1 FROM app.round_schedules WHERE code = 'weekend' AND version > 3) THEN
    RAISE EXCEPTION 'app_0009 downgrade refused: the weekend schedule is not the state app_0009 '
      'installed. Nothing was changed.';
  END IF;
  SELECT count(*) INTO n FROM app.rounds WHERE schedule_id = v3.id;
  IF n > 0 THEN
    RAISE EXCEPTION 'app_0009 downgrade refused: % round(s) are bound to weekend v3 '
      '(a3-432-v1); historical bindings are immutable, so the change is forward-only. Nothing '
      'was changed.', n;
  END IF;
  DELETE FROM app.round_schedules WHERE id = v3.id;
  UPDATE app.round_schedules SET active_to = NULL WHERE id = v2.id;
END $$;
"""


def _check_configurations() -> None:
    from diski9.challenge.config import ConfigError, get_config

    for version, expected in APPROVED_FINGERPRINTS.items():
        try:
            actual = get_config(version).fingerprint()
        except ConfigError as exc:
            raise RuntimeError(f"app_0009 refused: {version} is not registered") from exc
        if actual != expected:
            raise RuntimeError(f"app_0009 refused: {version} fingerprint {actual} is not the "
                               f"approved {expected}")  # fmt: skip


def upgrade() -> None:
    _check_configurations()
    op.execute(SETUP)
    op.execute(UP)


def downgrade() -> None:
    op.execute(SETUP)
    op.execute(DOWN)
