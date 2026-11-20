"""Settlement evidence, development result modes and settlement versions (Phase 6C.4).

Revision ID: app_0006
Revises: app_0005
Create Date: 2026-11-19

Additive, approved as S-10 (register). Only schema ``app``; never Supabase schemas.

* ``result_observations``: every distinct provider state is kept (the unique
  ``(fixture_id, raw_hash)`` index is replaced by an ordinary index, so a return to
  an earlier state, A -> B -> A, can be recorded; idempotency moves to the
  recorder, which compares with the preceding observation under an advisory lock).
  New source ``synthetic``, scoped to one development round in synthetic mode;
  operator rows may assert a result without a provider row (actor, reason and
  evidence required); verified event times only on operator rows; the provider's
  first-half start kept separately as supporting evidence; our receipt time can
  never be later than the database's recording time.
* ``rounds``: frozen ``correction_window_hours`` (copied at publish; back-filled
  for published rounds) and an explicit ``result_mode`` (``real`` for every real
  round; development rounds must choose ``real`` or ``synthetic`` before they can
  be settled). Both set once.
* ``selection_verdicts``: the deciding rule, the evidence used and whether the
  revision was material.
* ``settlement_runs``: evaluation time and phase, development time override flag,
  actor, evidence manifest, and whether the run changed anything material.
* New insert-only ``settlement_versions`` (authoritative settlement versions and the
  provisional -> final -> reopened lifecycle), ``settlement_alerts`` and
  ``settlement_alert_resolutions``.

Downgrade refuses (and changes nothing) once any 6C.4 settlement data exists,
because the earlier schema cannot represent it; discarding settlement history
silently is never acceptable. With no such data it restores ``app_0005`` exactly.
"""

from __future__ import annotations

from alembic import op

revision = "app_0006"
down_revision = "app_0005"
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
    "is_development",
)

NEW_HISTORY = ("settlement_versions", "settlement_alerts", "settlement_alert_resolutions")

VOID_RULES = "'V1', 'V1-catch-all', 'V2', 'V3-started', 'V3-rescheduled', 'V4'"
ALERT_CODES = (
    "'unknown_status', 'missing_score', 'score_conflict', 'status_regression', "
    "'schedule_conflict', 'early_start_unverified', 'late_notification', "
    "'catch_all_void', 'score_corrected', 'post_final_change'"
)


def _round_set_once(cols: tuple[str, ...]) -> str:
    args = ", ".join(f"'{c}'" for c in cols)
    return (
        "DROP TRIGGER rounds_set_once ON app.rounds;\n"
        "CREATE TRIGGER rounds_set_once BEFORE UPDATE ON app.rounds "
        f"FOR EACH ROW EXECUTE FUNCTION app.set_once({args});"
    )


def _history(t: str) -> str:
    return (
        f"CREATE TRIGGER {t}_insert_only BEFORE UPDATE OR DELETE ON app.{t} "
        "FOR EACH ROW EXECUTE FUNCTION app.forbid_change();\n"
        f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON app.{t} "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.forbid_change();\n"
        f"ALTER TABLE app.{t} ENABLE ROW LEVEL SECURITY;\n"
    )


UP = rf"""
-- ============================================================== rounds
ALTER TABLE app.rounds
  ADD COLUMN correction_window_hours integer
    CHECK (correction_window_hours IS NULL OR correction_window_hours >= 0),
  ADD COLUMN result_mode text CHECK (result_mode IS NULL OR result_mode IN ('real', 'synthetic'));
UPDATE app.rounds r SET correction_window_hours = s.correction_window_hours
  FROM app.round_schedules s
 WHERE s.id = r.schedule_id AND r.published_at IS NOT NULL;
-- every real round settles on real results; development rounds choose explicitly
UPDATE app.rounds SET result_mode = 'real' WHERE NOT is_development;
ALTER TABLE app.rounds
  ADD CONSTRAINT rounds_synthetic_only_development
    CHECK (is_development OR result_mode IS NULL OR result_mode = 'real'),
  ADD CONSTRAINT rounds_published_window
    CHECK (published_at IS NULL OR correction_window_hours IS NOT NULL),
  ADD CONSTRAINT rounds_published_real_mode
    CHECK (is_development OR published_at IS NULL OR result_mode = 'real');
{_round_set_once((*ROUND_SET_ONCE, "correction_window_hours", "result_mode"))}
-- publication freezes the schedule's correction window on the round, and a real
-- round's result mode, whichever code path publishes it
CREATE FUNCTION app.round_publish_defaults() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.published_at IS NOT NULL AND NEW.correction_window_hours IS NULL THEN
    SELECT correction_window_hours INTO NEW.correction_window_hours
      FROM app.round_schedules WHERE id = NEW.schedule_id;
  END IF;
  IF NOT NEW.is_development AND NEW.result_mode IS NULL THEN
    NEW.result_mode := 'real';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rounds_publish_defaults BEFORE INSERT OR UPDATE ON app.rounds
  FOR EACH ROW EXECUTE FUNCTION app.round_publish_defaults();

-- ============================================================== observations
DROP INDEX app.uq_results_provider_hash;
CREATE INDEX ix_results_fixture_hash ON app.result_observations (fixture_id, raw_hash);
CREATE INDEX ix_results_fixture_source ON app.result_observations
  (fixture_id, source, observed_at, id);
ALTER TABLE app.result_observations
  DROP CONSTRAINT result_observations_source_check,
  DROP CONSTRAINT result_observations_check,
  ADD COLUMN scope_round_id uuid REFERENCES app.rounds (id),
  ADD COLUMN provider_first_half_at timestamptz,
  ADD COLUMN completed_at timestamptz,
  ADD COLUMN evidence text;
ALTER TABLE app.result_observations
  ADD CONSTRAINT result_observations_source_check
    CHECK (source IN ('api-football', 'operator', 'synthetic')),
  ADD CONSTRAINT result_observations_operator
    CHECK (source <> 'operator'
           OR (actor_user_id IS NOT NULL AND reason IS NOT NULL AND char_length(reason) > 0
               AND (withdraws_correction_id IS NOT NULL
                    OR (evidence IS NOT NULL AND char_length(evidence) > 0)))),
  ADD CONSTRAINT result_observations_provider_unscoped
    CHECK (source <> 'api-football' OR scope_round_id IS NULL),
  ADD CONSTRAINT result_observations_synthetic_scoped
    CHECK (source <> 'synthetic' OR scope_round_id IS NOT NULL),
  ADD CONSTRAINT result_observations_verified_times_operator_only
    CHECK (source = 'operator' OR (actual_kickoff_at IS NULL AND completed_at IS NULL)),
  ADD CONSTRAINT result_observations_receipt_not_after_recording
    CHECK (source = 'synthetic' OR observed_at <= recorded_at);
CREATE INDEX ix_results_scope ON app.result_observations (scope_round_id)
  WHERE scope_round_id IS NOT NULL;

-- scoped evidence belongs only to a development round in synthetic mode, and an
-- operator row may only correct or withdraw evidence of the same fixture and scope
CREATE FUNCTION app.result_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record; o record;
BEGIN
  IF NEW.scope_round_id IS NOT NULL THEN
    SELECT is_development, result_mode INTO r FROM app.rounds WHERE id = NEW.scope_round_id;
    IF NOT coalesce(r.is_development, false) OR r.result_mode IS DISTINCT FROM 'synthetic' THEN
      RAISE EXCEPTION 'app.result_observations: scoped evidence is only for a '
        'development round in synthetic result mode'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  FOR o IN SELECT fixture_id, scope_round_id, source FROM app.result_observations
            WHERE id IN (NEW.corrects_observation_id, NEW.withdraws_correction_id) LOOP
    IF o.fixture_id <> NEW.fixture_id OR o.scope_round_id IS DISTINCT FROM NEW.scope_round_id THEN
      RAISE EXCEPTION 'app.result_observations: a correction must concern the '
        'same fixture and scope'
        USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;
  IF NEW.withdraws_correction_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM app.result_observations
        WHERE id = NEW.withdraws_correction_id AND source = 'operator') THEN
    RAISE EXCEPTION 'app.result_observations: only an operator correction can be withdrawn'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER result_observations_scope BEFORE INSERT ON app.result_observations
  FOR EACH ROW EXECUTE FUNCTION app.result_scope_guard();

-- ============================================================== verdicts
ALTER TABLE app.selection_verdicts
  ADD COLUMN rule text
    CHECK (rule IS NULL OR rule IN ('settle', 'settle-v5', 'pending', {VOID_RULES})),
  ADD COLUMN evidence jsonb,
  ADD COLUMN material boolean NOT NULL DEFAULT true,
  ADD CONSTRAINT selection_verdicts_rule_matches
    CHECK (rule IS NULL
           OR ((verdict = 'pending') = (rule = 'pending')
               AND (verdict = 'void') = (rule IN ({VOID_RULES}))
               AND (verdict <> 'void' OR left(rule, 2) = void_code)));

-- ============================================================== settlement runs
ALTER TABLE app.settlement_runs
  DROP CONSTRAINT settlement_runs_trigger_check,
  ADD CONSTRAINT settlement_runs_trigger_check
    CHECK (trigger IN ('scheduled', 'manual', 'correction', 'reopen', 'invalidation', 'finalise')),
  ADD COLUMN evaluated_at timestamptz,
  ADD COLUMN phase text CHECK (phase IS NULL OR phase IN ('before_cutoff', 'after_cutoff')),
  ADD COLUMN time_override boolean NOT NULL DEFAULT false,
  ADD COLUMN actor_user_id uuid REFERENCES app.users (id),
  ADD COLUMN manifest jsonb,
  ADD COLUMN evidence_through_id bigint,
  ADD COLUMN material boolean NOT NULL DEFAULT false,
  ADD CONSTRAINT settlement_runs_evaluated
    CHECK ((evaluated_at IS NULL) = (phase IS NULL));

-- a development time override is refused for every real round
CREATE FUNCTION app.settlement_override_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.time_override AND NOT EXISTS (
       SELECT 1 FROM app.rounds WHERE id = NEW.round_id AND is_development) THEN
    RAISE EXCEPTION 'app.settlement_runs: time overrides are only for development rounds'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER settlement_runs_override BEFORE INSERT ON app.settlement_runs
  FOR EACH ROW EXECUTE FUNCTION app.settlement_override_guard();

-- ============================================================== settlement versions
CREATE TABLE app.settlement_versions (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id       uuid NOT NULL REFERENCES app.rounds (id),
  version        integer NOT NULL CHECK (version >= 1),
  run_id         bigint REFERENCES app.settlement_runs (id),
  kind           text NOT NULL CHECK (kind IN ('provisional', 'final', 'reopened')),
  material       boolean NOT NULL,
  effective_at   timestamptz NOT NULL,
  actor_user_id  uuid REFERENCES app.users (id),
  reason         text,
  evidence       text,
  created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (round_id, version),
  CHECK (kind <> 'provisional' OR run_id IS NOT NULL),
  CHECK (kind <> 'reopened' OR (actor_user_id IS NOT NULL AND char_length(coalesce(reason, '')) > 0
                                AND char_length(coalesce(evidence, '')) > 0))
);
CREATE INDEX ix_settlement_versions_round ON app.settlement_versions (round_id, version DESC);

-- versions are consecutive; "final" is followed only by "reopened", and
-- "reopened" only follows "final"
CREATE FUNCTION app.settlement_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE last record;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('diski9:settlement_version:' || NEW.round_id, 0));
  SELECT version, kind INTO last FROM app.settlement_versions
   WHERE round_id = NEW.round_id ORDER BY version DESC LIMIT 1;
  IF NEW.version <> coalesce(last.version, 0) + 1 THEN
    RAISE EXCEPTION 'app.settlement_versions: version % does not follow %',
      NEW.version, last.version
      USING ERRCODE = 'check_violation';
  END IF;
  IF (last.kind = 'final') <> (NEW.kind = 'reopened') THEN
    RAISE EXCEPTION 'app.settlement_versions: % cannot follow %',
      NEW.kind, coalesce(last.kind, 'nothing')
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER settlement_versions_lifecycle BEFORE INSERT ON app.settlement_versions
  FOR EACH ROW EXECUTE FUNCTION app.settlement_version_guard();

-- ============================================================== alerts
CREATE TABLE app.settlement_alerts (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id     uuid NOT NULL REFERENCES app.rounds (id),
  fixture_id   bigint,
  run_id       bigint REFERENCES app.settlement_runs (id),
  code         text NOT NULL CHECK (code IN ({ALERT_CODES})),
  blocking     boolean NOT NULL,
  fingerprint  text NOT NULL,
  detail       jsonb NOT NULL DEFAULT '{{}}'::jsonb,
  created_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (round_id, fingerprint)
);
CREATE INDEX ix_settlement_alerts_round ON app.settlement_alerts (round_id, id);

CREATE TABLE app.settlement_alert_resolutions (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  alert_id        bigint NOT NULL UNIQUE REFERENCES app.settlement_alerts (id),
  resolution      text NOT NULL
                  CHECK (resolution IN ('confirmed', 'corrected', 'superseded', 'acknowledged')),
  actor_user_id   uuid REFERENCES app.users (id),
  reason          text NOT NULL CHECK (char_length(reason) > 0),
  observation_id  bigint REFERENCES app.result_observations (id),
  created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (resolution = 'superseded' OR actor_user_id IS NOT NULL),
  CHECK (resolution <> 'corrected' OR observation_id IS NOT NULL)
);

{"".join(_history(t) for t in NEW_HISTORY)}

REVOKE ALL ON app.settlement_versions, app.settlement_alerts,
  app.settlement_alert_resolutions FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.result_scope_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.round_publish_defaults() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.settlement_override_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION app.settlement_version_guard() FROM PUBLIC;
DO $$
DECLARE t text;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    FOREACH t IN ARRAY ARRAY{list(NEW_HISTORY)!r}::text[] LOOP
      EXECUTE format('GRANT SELECT, INSERT ON app.%I TO {APP_ROLE}', t);
      EXECUTE format(
        'CREATE POLICY runtime_access ON app.%I TO {APP_ROLE} USING (true) WITH CHECK (true)', t);
    END LOOP;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.result_scope_guard() TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.round_publish_defaults() TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.settlement_override_guard() TO {APP_ROLE};
    GRANT EXECUTE ON FUNCTION app.settlement_version_guard() TO {APP_ROLE};
  END IF;
END $$;
"""

DOWN = rf"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM app.settlement_versions)
     OR EXISTS (SELECT 1 FROM app.settlement_alerts)
     OR EXISTS (SELECT 1 FROM app.settlement_runs WHERE evaluated_at IS NOT NULL)
     OR EXISTS (SELECT 1 FROM app.selection_verdicts WHERE rule IS NOT NULL)
     OR EXISTS (SELECT 1 FROM app.result_observations
                 WHERE source = 'synthetic' OR scope_round_id IS NOT NULL
                    OR provider_first_half_at IS NOT NULL OR completed_at IS NOT NULL
                    OR (source = 'operator' AND corrects_observation_id IS NULL
                        AND withdraws_correction_id IS NULL))
     OR EXISTS (SELECT 1 FROM app.result_observations WHERE source = 'api-football'
                 GROUP BY fixture_id, raw_hash HAVING count(*) > 1)
     OR EXISTS (SELECT 1 FROM app.rounds WHERE result_mode = 'synthetic') THEN
    RAISE EXCEPTION 'app_0006 downgrade refused: Phase 6C.4 settlement data exists '
      'and the earlier schema cannot hold it (nothing was changed)'
      USING ERRCODE = 'object_in_use';
  END IF;
END $$;

DROP TABLE app.settlement_alert_resolutions;
DROP TABLE app.settlement_alerts;
DROP TABLE app.settlement_versions;
DROP FUNCTION app.settlement_version_guard();

DROP TRIGGER settlement_runs_override ON app.settlement_runs;
DROP FUNCTION app.settlement_override_guard();
ALTER TABLE app.settlement_runs
  DROP CONSTRAINT settlement_runs_evaluated,
  DROP COLUMN material,
  DROP COLUMN evidence_through_id,
  DROP COLUMN manifest,
  DROP COLUMN actor_user_id,
  DROP COLUMN time_override,
  DROP COLUMN phase,
  DROP COLUMN evaluated_at,
  DROP CONSTRAINT settlement_runs_trigger_check,
  ADD CONSTRAINT settlement_runs_trigger_check
    CHECK (trigger IN ('scheduled', 'manual', 'correction', 'reopen'));

ALTER TABLE app.selection_verdicts
  DROP CONSTRAINT selection_verdicts_rule_matches,
  DROP COLUMN material,
  DROP COLUMN evidence,
  DROP COLUMN rule;

DROP TRIGGER result_observations_scope ON app.result_observations;
DROP FUNCTION app.result_scope_guard();
DROP INDEX app.ix_results_scope;
ALTER TABLE app.result_observations
  DROP CONSTRAINT result_observations_receipt_not_after_recording,
  DROP CONSTRAINT result_observations_verified_times_operator_only,
  DROP CONSTRAINT result_observations_synthetic_scoped,
  DROP CONSTRAINT result_observations_provider_unscoped,
  DROP CONSTRAINT result_observations_operator,
  DROP CONSTRAINT result_observations_source_check,
  DROP COLUMN evidence,
  DROP COLUMN completed_at,
  DROP COLUMN provider_first_half_at,
  DROP COLUMN scope_round_id;
ALTER TABLE app.result_observations
  ADD CONSTRAINT result_observations_source_check CHECK (source IN ('api-football', 'operator')),
  ADD CONSTRAINT result_observations_check
    CHECK (source <> 'operator'
           OR (actor_user_id IS NOT NULL AND reason IS NOT NULL AND char_length(reason) > 0
               AND (corrects_observation_id IS NOT NULL OR withdraws_correction_id IS NOT NULL)));
DROP INDEX app.ix_results_fixture_source;
DROP INDEX app.ix_results_fixture_hash;
CREATE UNIQUE INDEX uq_results_provider_hash ON app.result_observations (fixture_id, raw_hash)
  WHERE source = 'api-football';

DROP TRIGGER rounds_publish_defaults ON app.rounds;
DROP FUNCTION app.round_publish_defaults();
{_round_set_once(ROUND_SET_ONCE)}
ALTER TABLE app.rounds
  DROP CONSTRAINT rounds_published_real_mode,
  DROP CONSTRAINT rounds_published_window,
  DROP CONSTRAINT rounds_synthetic_only_development,
  DROP COLUMN result_mode,
  DROP COLUMN correction_window_hours;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
