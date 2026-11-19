"""Competition schema (Phase 6C.1): identity, rounds, snapshots, portfolios,
results, settlement, designations, championships, audit and jobs.

Revision ID: app_0001
Revises:
Create Date: 2026-11-19

Written as explicit SQL so constraints, partial indexes, deferrable keys and the
history-protection triggers are exactly as reviewed
(docs/architecture/phase6c_database_design.md). ``diski9.backend.db.schema``
mirrors these tables for queries; a test checks that the two agree.
"""

from __future__ import annotations

from alembic import op

revision = "app_0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "diski9_app"

# ---------------------------------------------------------------- functions
FUNCTIONS = r"""
CREATE SCHEMA IF NOT EXISTS app;

-- History tables: rows are appended, never changed or removed.
CREATE FUNCTION app.forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'app.%: % is not allowed on an insert-only history table',
    TG_TABLE_NAME, TG_OP USING ERRCODE = 'insufficient_privilege';
END $$;

-- Set-once columns: a non-NULL value can never change (names passed as arguments).
CREATE FUNCTION app.set_once() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE col text; old_v text; new_v text;
BEGIN
  FOREACH col IN ARRAY TG_ARGV LOOP
    EXECUTE format('SELECT ($1).%I::text, ($2).%I::text', col, col)
      INTO old_v, new_v USING OLD, NEW;
    IF old_v IS NOT NULL AND new_v IS DISTINCT FROM old_v THEN
      RAISE EXCEPTION 'app.%: column % is set once and cannot change', TG_TABLE_NAME, col
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;

-- Account deletion (D-36): the only permitted change to username history is
-- replacing the name with the tombstone; nothing else may change.
CREATE FUNCTION app.username_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND NEW.username = '[deleted]'
     AND (to_jsonb(NEW) - 'username') = (to_jsonb(OLD) - 'username') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'app.username_history: only anonymisation is allowed'
    USING ERRCODE = 'insufficient_privilege';
END $$;

-- Entitlement grants: only a single revocation is allowed after insert.
CREATE FUNCTION app.entitlement_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
     AND (to_jsonb(NEW) - 'revoked_at' - 'revoked_by' - 'revoke_reason')
       = (to_jsonb(OLD) - 'revoked_at' - 'revoked_by' - 'revoke_reason') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'app.entitlement_grants: rows are insert-only apart from one revocation'
    USING ERRCODE = 'insufficient_privilege';
END $$;

-- Run records (jobs, settlement runs): only a running row may be completed.
CREATE FUNCTION app.run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.status = 'running'
     AND (to_jsonb(NEW) - 'status' - 'finished_at' - 'api_requests' - 'error'
          - 'changed_verdicts' - 'changed_entries')
       = (to_jsonb(OLD) - 'status' - 'finished_at' - 'api_requests' - 'error'
          - 'changed_verdicts' - 'changed_entries') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'app.%: only a running record can be completed', TG_TABLE_NAME
    USING ERRCODE = 'insufficient_privilege';
END $$;

-- Deadline enforcement foundation: a submission row can only be inserted while the
-- round is open and before its deadline, by the database clock (D-06).
CREATE FUNCTION app.submission_deadline_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""

# ---------------------------------------------------------------- tables
TABLES = r"""
-- ===================================================== identity and accounts
CREATE TABLE app.users (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status      text NOT NULL DEFAULT 'active'
              CHECK (status IN ('active', 'suspended', 'deleted')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz,
  CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
);

CREATE TABLE app.user_identities (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id          uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
  provider         text NOT NULL CHECK (provider ~ '^[a-z0-9_-]{2,32}$'),
  subject          text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 255),
  created_at       timestamptz NOT NULL DEFAULT now(),
  last_sign_in_at  timestamptz,
  UNIQUE (provider, subject)
);
CREATE INDEX ix_user_identities_user ON app.user_identities (user_id);

CREATE TABLE app.user_private (
  user_id           uuid PRIMARY KEY REFERENCES app.users (id) ON DELETE CASCADE,
  email             text CHECK (email IS NULL OR char_length(email) <= 320),
  email_verified    boolean NOT NULL DEFAULT false,
  age_confirmed_at  timestamptz,
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.profiles (
  user_id              uuid PRIMARY KEY REFERENCES app.users (id) ON DELETE CASCADE,
  username             text NOT NULL
                       CHECK (char_length(username) BETWEEN 3 AND 24
                              AND username ~ '^[A-Za-z0-9][A-Za-z0-9 ._-]*[A-Za-z0-9]$'),
  username_key         text NOT NULL CHECK (username_key = lower(username)),
  username_changed_at  timestamptz NOT NULL DEFAULT now(),
  privacy_mode         text NOT NULL DEFAULT 'public'
                       CHECK (privacy_mode IN ('public', 'anonymous')),
  anonymous_alias      text NOT NULL CHECK (anonymous_alias ~ '^Anonymous [0-9]{4,8}$'),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (username_key),
  UNIQUE (anonymous_alias)
);

CREATE TABLE app.username_history (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES app.users (id),
  username    text NOT NULL,
  valid_from  timestamptz NOT NULL DEFAULT now(),
  changed_by  uuid REFERENCES app.users (id),
  reason      text
);
CREATE INDEX ix_username_history_user ON app.username_history (user_id, valid_from);

CREATE TABLE app.privacy_history (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES app.users (id),
  privacy_mode  text NOT NULL CHECK (privacy_mode IN ('public', 'anonymous')),
  retroactive   boolean NOT NULL DEFAULT false,
  effective_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT retroactive OR privacy_mode = 'anonymous')
);
CREATE INDEX ix_privacy_history_user ON app.privacy_history (user_id, effective_at);

CREATE TABLE app.user_roles (
  user_id     uuid NOT NULL REFERENCES app.users (id),
  role        text NOT NULL CHECK (role IN ('operator', 'owner')),
  granted_by  uuid REFERENCES app.users (id),
  granted_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role)
);

CREATE TABLE app.features (
  key          text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
  description  text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.entitlement_grants (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id        uuid NOT NULL REFERENCES app.users (id),
  feature_key    text NOT NULL REFERENCES app.features (key),
  source         text NOT NULL CHECK (source IN ('owner', 'manual', 'subscription')),
  granted_by     uuid REFERENCES app.users (id),
  valid_from     timestamptz NOT NULL DEFAULT now(),
  valid_to       timestamptz,
  reason         text,
  revoked_at     timestamptz,
  revoked_by     uuid REFERENCES app.users (id),
  revoke_reason  text,
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX uq_entitlement_live ON app.entitlement_grants (user_id, feature_key)
  WHERE revoked_at IS NULL;

CREATE TABLE app.terms_versions (
  version                text PRIMARY KEY,
  published_at           timestamptz NOT NULL,
  content_hash           text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  minimum_age            integer NOT NULL DEFAULT 18 CHECK (minimum_age >= 18),
  requires_reacceptance  boolean NOT NULL DEFAULT false
);

CREATE TABLE app.terms_acceptances (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id        uuid NOT NULL REFERENCES app.users (id),
  terms_version  text NOT NULL REFERENCES app.terms_versions (version),
  accepted_at    timestamptz NOT NULL DEFAULT now(),
  age_confirmed  boolean NOT NULL CHECK (age_confirmed),
  UNIQUE (user_id, terms_version)
);

CREATE TABLE app.app_sessions (
  id                   text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
  user_id              uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
  created_at           timestamptz NOT NULL DEFAULT now(),
  last_seen_at         timestamptz NOT NULL DEFAULT now(),
  authenticated_at     timestamptz NOT NULL DEFAULT now(),
  idle_expires_at      timestamptz NOT NULL,
  absolute_expires_at  timestamptz NOT NULL,
  revoked_at           timestamptz,
  rotated_from         text,
  user_agent_hash      text,
  CHECK (idle_expires_at <= absolute_expires_at)
);
CREATE INDEX ix_app_sessions_user ON app.app_sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX ix_app_sessions_expiry ON app.app_sessions (absolute_expires_at);

-- ===================================================== configuration
CREATE TABLE app.championship_series (
  id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                     text NOT NULL UNIQUE CHECK (code IN ('beta', 'official')),
  scoring_version          text NOT NULL,
  rounds_per_championship  integer NOT NULL DEFAULT 10 CHECK (rounds_per_championship > 0),
  started_at               timestamptz
);

CREATE TABLE app.round_schedules (
  id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                     text NOT NULL CHECK (code ~ '^[a-z][a-z0-9_-]*$'),
  version                  integer NOT NULL CHECK (version >= 1),
  timezone                 text NOT NULL,
  eligible_competitions    integer[] NOT NULL CHECK (cardinality(eligible_competitions) > 0),
  window_rule              jsonb NOT NULL,
  publish_rule             jsonb NOT NULL,
  deadline_buffer_minutes  integer NOT NULL CHECK (deadline_buffer_minutes >= 0),
  settle_cutoff_hours      integer NOT NULL CHECK (settle_cutoff_hours > 0),
  correction_window_hours  integer NOT NULL CHECK (correction_window_hours >= 0),
  config_version           text NOT NULL,
  rules_version            text NOT NULL,
  scoring_version          text NOT NULL,
  series_id                bigint NOT NULL REFERENCES app.championship_series (id),
  active_from              timestamptz NOT NULL,
  active_to                timestamptz,
  created_at               timestamptz NOT NULL DEFAULT now(),
  UNIQUE (code, version),
  CHECK (active_to IS NULL OR active_to > active_from)
);

-- ===================================================== rounds and snapshots
CREATE TABLE app.rounds (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code              text NOT NULL UNIQUE,
  schedule_id       bigint NOT NULL REFERENCES app.round_schedules (id),
  series_id         bigint NOT NULL REFERENCES app.championship_series (id),
  window_start_at   timestamptz NOT NULL,
  window_end_at     timestamptz NOT NULL,
  status            text NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'open', 'locked', 'settling', 'final',
                                      'postponed')),
  published_at      timestamptz,
  deadline_at       timestamptz,
  settle_cutoff_at  timestamptz,
  finalised_at      timestamptz,
  config_version    text,
  rules_version     text,
  scoring_version   text,
  model_version     text,
  valid_entries     integer CHECK (valid_entries IS NULL OR valid_entries >= 0),
  created_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (window_end_at > window_start_at),
  CHECK (deadline_at IS NULL OR settle_cutoff_at IS NULL OR deadline_at < settle_cutoff_at),
  CHECK (status IN ('draft', 'postponed')
         OR (published_at IS NOT NULL AND deadline_at IS NOT NULL
             AND settle_cutoff_at IS NOT NULL AND config_version IS NOT NULL
             AND rules_version IS NOT NULL AND scoring_version IS NOT NULL))
);
CREATE INDEX ix_rounds_status ON app.rounds (status);
CREATE INDEX ix_rounds_series_deadline ON app.rounds (series_id, deadline_at);

CREATE TABLE app.round_status_history (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id     uuid NOT NULL REFERENCES app.rounds (id),
  from_status  text,
  to_status    text NOT NULL,
  at           timestamptz NOT NULL DEFAULT now(),
  actor_user_id uuid REFERENCES app.users (id),
  job_run_id   bigint,
  reason       text
);
CREATE INDEX ix_round_status_history_round ON app.round_status_history (round_id, at);

CREATE TABLE app.round_snapshots (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id            uuid NOT NULL UNIQUE REFERENCES app.rounds (id),
  as_of               timestamptz NOT NULL,
  fingerprint         text NOT NULL CHECK (char_length(fingerprint) BETWEEN 16 AND 64),
  model_version       text NOT NULL,
  params_hash         text,
  forecast_cutoff_at  timestamptz,
  feasibility         jsonb NOT NULL,
  source_job_run_id   bigint,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, id)
);

CREATE TABLE app.snapshot_fixtures (
  snapshot_id           bigint NOT NULL REFERENCES app.round_snapshots (id),
  fixture_id            bigint NOT NULL,
  competition_id        integer NOT NULL,
  home_team             text NOT NULL,
  away_team             text NOT NULL,
  kickoff_at_publish    timestamptz NOT NULL,
  estimated_goals_home  double precision,
  estimated_goals_away  double precision,
  PRIMARY KEY (snapshot_id, fixture_id)
);

CREATE TABLE app.snapshot_offers (
  snapshot_id            bigint NOT NULL,
  fixture_id             bigint NOT NULL,
  market                 text NOT NULL CHECK (market IN ('1X2', 'BTTS', 'OU25')),
  outcome                text NOT NULL
                         CHECK (outcome IN ('HOME', 'DRAW', 'AWAY', 'BTTS_YES', 'BTTS_NO',
                                            'OVER_2_5', 'UNDER_2_5')),
  model_prob             double precision CHECK (model_prob IS NULL OR model_prob BETWEEN 0 AND 1),
  consensus_odds         numeric(8, 2) CHECK (consensus_odds IS NULL OR consensus_odds > 1),
  market_prob            double precision
                         CHECK (market_prob IS NULL OR market_prob BETWEEN 0 AND 1),
  bookmaker_groups       integer CHECK (bookmaker_groups IS NULL OR bookmaker_groups >= 0),
  latest_observation_at  timestamptz,
  provider_updated_at    timestamptz,
  eligible               boolean NOT NULL,
  bucket                 text CHECK (bucket IN ('A', 'B', 'C')),
  ineligible_reason      text,
  PRIMARY KEY (snapshot_id, fixture_id, market, outcome),
  FOREIGN KEY (snapshot_id, fixture_id) REFERENCES app.snapshot_fixtures (snapshot_id, fixture_id),
  CHECK (eligible = (bucket IS NOT NULL)),
  CHECK (NOT eligible OR (consensus_odds IS NOT NULL AND market_prob IS NOT NULL))
);

-- ===================================================== private analysis and drafts
CREATE TABLE app.your_view_adjustments (
  user_id        uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
  fixture_id     bigint NOT NULL,
  model_context  text NOT NULL,
  state          jsonb NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, fixture_id)
);

CREATE TABLE app.portfolio_drafts (
  user_id               uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
  round_id              uuid NOT NULL REFERENCES app.rounds (id),
  selections            jsonb NOT NULL,
  snapshot_fingerprint  text,
  updated_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, round_id)
);

-- ===================================================== entries and confirmed portfolios
CREATE TABLE app.entries (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  round_id              uuid NOT NULL REFERENCES app.rounds (id),
  user_id               uuid NOT NULL REFERENCES app.users (id),
  state                 text NOT NULL DEFAULT 'confirmed'
                        CHECK (state IN ('confirmed', 'withdrawn')),
  current_submission_id uuid,
  version               integer NOT NULL DEFAULT 0 CHECK (version >= 0),
  locked_at             timestamptz,
  locked_submission_id  uuid,
  public_name_at_lock   text,
  privacy_mode_at_lock  text CHECK (privacy_mode_at_lock IN ('public', 'anonymous')),
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, user_id),
  UNIQUE (id, round_id, user_id),
  CHECK (state <> 'withdrawn' OR current_submission_id IS NULL),
  CHECK ((locked_at IS NULL) = (locked_submission_id IS NULL))
);
CREATE INDEX ix_entries_locked ON app.entries (round_id) WHERE locked_submission_id IS NOT NULL;
CREATE INDEX ix_entries_user ON app.entries (user_id);

CREATE TABLE app.submissions (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id               uuid NOT NULL,
  round_id               uuid NOT NULL,
  user_id                uuid NOT NULL,
  snapshot_id            bigint NOT NULL,
  version                integer NOT NULL CHECK (version >= 1),
  idempotency_key        text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 16 AND 128),
  submitted_at           timestamptz NOT NULL DEFAULT transaction_timestamp(),
  inputs_hash            text NOT NULL CHECK (inputs_hash ~ '^[0-9a-f]{64}$'),
  p_recover_market       double precision NOT NULL CHECK (p_recover_market BETWEEN 0 AND 1),
  p_recover_model        double precision CHECK (p_recover_model BETWEEN 0 AND 1),
  expected_gross_market  double precision NOT NULL CHECK (expected_gross_market >= 0),
  expected_gross_model   double precision CHECK (expected_gross_model >= 0),
  max_gross              numeric(14, 2) NOT NULL CHECK (max_gross >= 0),
  states                 jsonb NOT NULL,
  config_version         text NOT NULL,
  calc_version           text NOT NULL,
  model_version          text NOT NULL,
  rules_version          text NOT NULL,
  -- ownership: the entry must belong to the same user and round
  FOREIGN KEY (entry_id, round_id, user_id) REFERENCES app.entries (id, round_id, user_id),
  -- the snapshot must be this round's snapshot
  FOREIGN KEY (round_id, snapshot_id) REFERENCES app.round_snapshots (round_id, id),
  UNIQUE (entry_id, version),
  UNIQUE (user_id, idempotency_key),
  UNIQUE (id, entry_id),
  UNIQUE (id, snapshot_id)
);
CREATE INDEX ix_submissions_round ON app.submissions (round_id);

ALTER TABLE app.entries
  ADD CONSTRAINT fk_entries_current_submission
    FOREIGN KEY (current_submission_id, id) REFERENCES app.submissions (id, entry_id)
    DEFERRABLE INITIALLY DEFERRED,
  ADD CONSTRAINT fk_entries_locked_submission
    FOREIGN KEY (locked_submission_id, id) REFERENCES app.submissions (id, entry_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE app.submission_selections (
  submission_id     uuid NOT NULL,
  snapshot_id       bigint NOT NULL,
  position          smallint NOT NULL CHECK (position BETWEEN 0 AND 8),
  fixture_id        bigint NOT NULL,
  market            text NOT NULL,
  outcome           text NOT NULL,
  bucket            text NOT NULL CHECK (bucket IN ('A', 'B', 'C')),
  model_prob        double precision,
  consensus_odds    numeric(8, 2) NOT NULL CHECK (consensus_odds > 1),
  market_prob       double precision NOT NULL CHECK (market_prob BETWEEN 0 AND 1),
  bookmaker_groups  integer NOT NULL CHECK (bookmaker_groups >= 0),
  PRIMARY KEY (submission_id, position),
  UNIQUE (submission_id, fixture_id),
  FOREIGN KEY (submission_id, snapshot_id) REFERENCES app.submissions (id, snapshot_id),
  FOREIGN KEY (snapshot_id, fixture_id, market, outcome)
    REFERENCES app.snapshot_offers (snapshot_id, fixture_id, market, outcome)
);
CREATE INDEX ix_selections_fixture ON app.submission_selections (fixture_id);

CREATE TABLE app.entry_events (
  id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entry_id                uuid NOT NULL REFERENCES app.entries (id),
  kind                    text NOT NULL
                          CHECK (kind IN ('confirmed', 'replaced', 'withdrawn', 'locked')),
  submission_id           uuid REFERENCES app.submissions (id),
  previous_submission_id  uuid REFERENCES app.submissions (id),
  at                      timestamptz NOT NULL DEFAULT transaction_timestamp(),
  actor_user_id           uuid REFERENCES app.users (id),
  CHECK (kind = 'withdrawn' OR submission_id IS NOT NULL)
);
CREATE INDEX ix_entry_events_entry ON app.entry_events (entry_id, at);

-- ===================================================== jobs
CREATE TABLE app.job_runs (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job           text NOT NULL,
  scope         text NOT NULL DEFAULT '',
  args          jsonb NOT NULL DEFAULT '{}'::jsonb,
  started_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
  finished_at   timestamptz,
  status        text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'succeeded', 'failed', 'skipped')),
  api_requests  integer NOT NULL DEFAULT 0 CHECK (api_requests >= 0),
  error         text,
  host          text,
  CHECK ((status = 'running') = (finished_at IS NULL))
);
CREATE INDEX ix_job_runs_job ON app.job_runs (job, scope, started_at);

ALTER TABLE app.round_status_history
  ADD FOREIGN KEY (job_run_id) REFERENCES app.job_runs (id);
ALTER TABLE app.round_snapshots
  ADD FOREIGN KEY (source_job_run_id) REFERENCES app.job_runs (id);

-- ===================================================== results and settlement
CREATE TABLE app.result_observations (
  id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fixture_id               bigint NOT NULL,
  observed_at              timestamptz NOT NULL,
  recorded_at              timestamptz NOT NULL DEFAULT clock_timestamp(),
  source                   text NOT NULL CHECK (source IN ('api-football', 'operator')),
  status_short             text,
  kickoff_at               timestamptz,
  actual_kickoff_at        timestamptz,
  ft_home                  smallint CHECK (ft_home IS NULL OR ft_home >= 0),
  ft_away                  smallint CHECK (ft_away IS NULL OR ft_away >= 0),
  raw                      jsonb,
  raw_hash                 text NOT NULL CHECK (raw_hash ~ '^[0-9a-f]{64}$'),
  job_run_id               bigint REFERENCES app.job_runs (id),
  corrects_observation_id  bigint REFERENCES app.result_observations (id),
  withdraws_correction_id  bigint REFERENCES app.result_observations (id),
  original_values          jsonb,
  actor_user_id            uuid REFERENCES app.users (id),
  reason                   text,
  CHECK (source <> 'operator'
         OR (actor_user_id IS NOT NULL AND reason IS NOT NULL AND char_length(reason) > 0
             AND (corrects_observation_id IS NOT NULL OR withdraws_correction_id IS NOT NULL))),
  CHECK (corrects_observation_id IS NULL OR original_values IS NOT NULL)
);
CREATE INDEX ix_results_fixture ON app.result_observations (fixture_id, observed_at);
CREATE UNIQUE INDEX uq_results_provider_hash ON app.result_observations (fixture_id, raw_hash)
  WHERE source = 'api-football';

CREATE TABLE app.settlement_runs (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id          uuid NOT NULL REFERENCES app.rounds (id),
  job_run_id        bigint REFERENCES app.job_runs (id),
  trigger           text NOT NULL CHECK (trigger IN ('scheduled', 'manual', 'correction',
                                                     'reopen')),
  started_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
  finished_at       timestamptz,
  status            text NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'succeeded', 'failed')),
  inputs_hash       text,
  changed_verdicts  integer NOT NULL DEFAULT 0,
  changed_entries   integer NOT NULL DEFAULT 0,
  error             text,
  CHECK ((status = 'running') = (finished_at IS NULL))
);
CREATE UNIQUE INDEX uq_settlement_running ON app.settlement_runs (round_id)
  WHERE status = 'running';

CREATE TABLE app.selection_verdicts (
  id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id                 bigint NOT NULL REFERENCES app.settlement_runs (id),
  round_id               uuid NOT NULL REFERENCES app.rounds (id),
  fixture_id             bigint NOT NULL,
  market                 text NOT NULL,
  outcome                text NOT NULL,
  verdict                text NOT NULL CHECK (verdict IN ('won', 'lost', 'void', 'pending')),
  void_code              text CHECK (void_code IN ('V1', 'V2', 'V3', 'V4')),
  result_observation_id  bigint REFERENCES app.result_observations (id),
  revision               integer NOT NULL CHECK (revision >= 1),
  created_at             timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (round_id, fixture_id, market, outcome, revision),
  CHECK ((verdict = 'void') = (void_code IS NOT NULL))
);

CREATE TABLE app.entry_settlements (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id         bigint NOT NULL REFERENCES app.settlement_runs (id),
  entry_id       uuid NOT NULL REFERENCES app.entries (id),
  submission_id  uuid NOT NULL REFERENCES app.submissions (id),
  revision       integer NOT NULL CHECK (revision >= 1),
  gross          numeric(14, 2) NOT NULL CHECK (gross >= 0),
  net            numeric(14, 2) NOT NULL,
  legs           jsonb NOT NULL,
  basis          text NOT NULL CHECK (basis IN ('settled', 'all_void')),
  complete       boolean NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (entry_id, revision),
  CHECK (net = gross - 100.00),
  CHECK (basis <> 'all_void' OR gross = 100.00)
);

CREATE TABLE app.round_evaluations (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id               bigint NOT NULL REFERENCES app.settlement_runs (id),
  round_id             uuid NOT NULL REFERENCES app.rounds (id),
  rule                 text NOT NULL CHECK (rule IN ('d32b-competitive', 'd32b-practice')),
  total_predictions    integer NOT NULL CHECK (total_predictions >= 0),
  played_predictions   integer NOT NULL CHECK (played_predictions >= 0),
  void_predictions     integer NOT NULL CHECK (void_predictions >= 0),
  pending_predictions  integer NOT NULL CHECK (pending_predictions >= 0),
  ranked_entries       integer NOT NULL CHECK (ranked_entries >= 0),
  outcome              text NOT NULL
                       CHECK (outcome IN ('not_evaluated', 'pass', 'fail_majority',
                                          'fail_ranked')),
  created_at           timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (played_predictions + void_predictions + pending_predictions = total_predictions),
  CHECK ((outcome = 'not_evaluated') = (pending_predictions > 0)),
  CHECK (outcome <> 'pass' OR 2 * played_predictions > total_predictions),
  CHECK (outcome <> 'fail_ranked' OR rule = 'd32b-competitive')
);
CREATE INDEX ix_round_evaluations_round ON app.round_evaluations (round_id, created_at);

CREATE TABLE app.designations (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id            uuid NOT NULL REFERENCES app.rounds (id),
  designation         text NOT NULL
                      CHECK (designation IN ('championship', 'practice', 'void', 'postponed')),
  basis               text NOT NULL
                      CHECK (basis IN ('opening_checks', 'deadline', 'd32b', 'operator')),
  round_evaluation_id bigint REFERENCES app.round_evaluations (id),
  actor_user_id       uuid REFERENCES app.users (id),
  reason              text,
  provisional         boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (basis <> 'operator' OR (actor_user_id IS NOT NULL AND reason IS NOT NULL)),
  CHECK (basis <> 'd32b' OR round_evaluation_id IS NOT NULL),
  CHECK (basis <> 'opening_checks' OR designation = 'postponed')
);
CREATE INDEX ix_designations_round ON app.designations (round_id, created_at, id);
-- the base designation fixed at the deadline is written once per round
CREATE UNIQUE INDEX uq_designation_deadline ON app.designations (round_id)
  WHERE basis = 'deadline';

CREATE TABLE app.score_sets (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  round_id        uuid NOT NULL REFERENCES app.rounds (id),
  revision        integer NOT NULL CHECK (revision >= 1),
  run_id          bigint NOT NULL REFERENCES app.settlement_runs (id),
  designation_id  bigint NOT NULL REFERENCES app.designations (id),
  kind            text NOT NULL CHECK (kind IN ('championship', 'practice', 'void')),
  final           boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (round_id, revision),
  UNIQUE (id, kind)
);

CREATE TABLE app.round_scores (
  score_set_id      bigint NOT NULL,
  kind              text NOT NULL,
  entry_id          uuid NOT NULL REFERENCES app.entries (id),
  user_id           uuid NOT NULL REFERENCES app.users (id),
  gross             numeric(14, 2) NOT NULL CHECK (gross >= 0),
  rank              integer CHECK (rank IS NULL OR rank >= 1),
  points            integer NOT NULL
                    CHECK (points IN (0, 75, 90, 95, 100, 105, 110, 115, 120, 125, 135, 150)),
  recovered         boolean NOT NULL,
  qualifying_top10  boolean NOT NULL,
  status            text NOT NULL CHECK (status IN ('ranked', 'void_refunded')),
  PRIMARY KEY (score_set_id, entry_id),
  FOREIGN KEY (score_set_id, kind) REFERENCES app.score_sets (id, kind),
  CHECK (kind = 'championship' OR (points = 0 AND NOT qualifying_top10)),
  CHECK (status <> 'void_refunded' OR (points = 0 AND rank IS NULL AND NOT recovered
                                       AND NOT qualifying_top10 AND gross = 100.00)),
  CHECK (NOT qualifying_top10 OR (recovered AND rank <= 10)),
  CHECK (recovered = (status = 'ranked' AND gross >= 100.00) OR kind = 'void')
);

CREATE TABLE app.championship_freezes (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  series_id         bigint NOT NULL REFERENCES app.championship_series (id),
  number            integer NOT NULL CHECK (number >= 1),
  frozen_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
  round_ids         uuid[] NOT NULL,
  standings         jsonb NOT NULL,
  champions         jsonb NOT NULL,
  content_hash      text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  reopened_from_id  bigint REFERENCES app.championship_freezes (id),
  actor_user_id     uuid REFERENCES app.users (id),
  reason            text,
  CHECK (reopened_from_id IS NULL OR (actor_user_id IS NOT NULL AND reason IS NOT NULL))
);
CREATE INDEX ix_championship_freezes ON app.championship_freezes (series_id, number, frozen_at);

-- ===================================================== audit and events
CREATE TABLE app.audit_log (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at             timestamptz NOT NULL DEFAULT clock_timestamp(),
  actor_user_id  uuid REFERENCES app.users (id),
  actor_role     text CHECK (actor_role IN ('participant', 'operator', 'owner', 'system')),
  action         text NOT NULL CHECK (action ~ '^[a-z][a-z0-9_.]*$'),
  target_type    text NOT NULL,
  target_id      text NOT NULL,
  reason         text,
  before         jsonb,
  after          jsonb,
  request_id     text,
  job_run_id     bigint REFERENCES app.job_runs (id),
  CHECK (actor_user_id IS NOT NULL OR actor_role = 'system')
);
CREATE INDEX ix_audit_target ON app.audit_log (target_type, target_id, at);
CREATE INDEX ix_audit_actor ON app.audit_log (actor_user_id, at);

CREATE TABLE app.domain_events (
  id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at        timestamptz NOT NULL DEFAULT clock_timestamp(),
  kind      text NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]*$'),
  user_id   uuid REFERENCES app.users (id),
  round_id  uuid REFERENCES app.rounds (id),
  payload   jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ix_domain_events_user ON app.domain_events (user_id, at);
CREATE INDEX ix_domain_events_kind ON app.domain_events (kind, at);
"""

HISTORY_TABLES = (
    "privacy_history",
    "terms_acceptances",
    "round_status_history",
    "round_snapshots",
    "snapshot_fixtures",
    "snapshot_offers",
    "submissions",
    "submission_selections",
    "entry_events",
    "result_observations",
    "selection_verdicts",
    "entry_settlements",
    "round_evaluations",
    "designations",
    "score_sets",
    "round_scores",
    "championship_freezes",
    "audit_log",
    "domain_events",
)
# insert-only apart from a narrow, trigger-checked change
GUARDED_TABLES = {
    "username_history": "app.username_history_guard()",
    "entitlement_grants": "app.entitlement_guard()",
    "job_runs": "app.run_guard()",
    "settlement_runs": "app.run_guard()",
}
SET_ONCE = {
    "rounds": (
        "published_at",
        "deadline_at",
        "settle_cutoff_at",
        "finalised_at",
        "config_version",
        "rules_version",
        "scoring_version",
        "model_version",
    ),
    "entries": ("locked_at", "locked_submission_id", "public_name_at_lock", "privacy_mode_at_lock"),
}
PROJECTION_TABLES = (
    "users",
    "user_identities",
    "user_private",
    "profiles",
    "user_roles",
    "features",
    "terms_versions",
    "app_sessions",
    "championship_series",
    "round_schedules",
    "rounds",
    "your_view_adjustments",
    "portfolio_drafts",
    "entries",
)


def _triggers() -> str:
    sql = []
    for t in HISTORY_TABLES:
        sql.append(
            f"CREATE TRIGGER {t}_insert_only BEFORE UPDATE OR DELETE ON app.{t} "
            "FOR EACH ROW EXECUTE FUNCTION app.forbid_change();"
        )
    for t, fn in GUARDED_TABLES.items():
        sql.append(
            f"CREATE TRIGGER {t}_guard BEFORE UPDATE OR DELETE ON app.{t} "
            f"FOR EACH ROW EXECUTE FUNCTION {fn};"
        )
    for t in (*HISTORY_TABLES, *GUARDED_TABLES):
        sql.append(
            f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON app.{t} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.forbid_change();"
        )
    for t, cols in SET_ONCE.items():
        args = ", ".join(f"'{c}'" for c in cols)
        sql.append(
            f"CREATE TRIGGER {t}_set_once BEFORE UPDATE ON app.{t} "
            f"FOR EACH ROW EXECUTE FUNCTION app.set_once({args});"
        )
    sql.append(
        "CREATE TRIGGER submissions_deadline BEFORE INSERT ON app.submissions "
        "FOR EACH ROW EXECUTE FUNCTION app.submission_deadline_guard();"
    )
    return "\n".join(sql)


def _grants() -> str:
    """Privileges for the runtime role, applied only if the role exists (roles are
    cluster-wide and created outside migrations; see docs/backend.md)."""
    history = ", ".join(f"app.{t}" for t in (*HISTORY_TABLES, *GUARDED_TABLES))
    projection = ", ".join(f"app.{t}" for t in PROJECTION_TABLES)
    guarded = ", ".join(f"app.{t}" for t in GUARDED_TABLES)
    return f"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT USAGE ON SCHEMA app TO {APP_ROLE};
    GRANT SELECT, INSERT ON {history} TO {APP_ROLE};
    GRANT UPDATE ON {guarded} TO {APP_ROLE};
    GRANT SELECT, INSERT, UPDATE, DELETE ON {projection} TO {APP_ROLE};
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO {APP_ROLE};
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO {APP_ROLE};
  END IF;
END $$;
"""


SEED = r"""
INSERT INTO app.features (key, description) VALUES
  ('lucy.research', 'Lucy qualitative research assistant (Phase 7; owner only initially)'),
  ('lucy.voice', 'Lucy voice interaction (Phase 7; owner only initially)'),
  ('lucy.presenter', 'Lucy presenter mode (Phase 7; owner only initially)');

INSERT INTO app.championship_series (code, scoring_version, rounds_per_championship) VALUES
  ('beta', 'points-150-75-v2', 10),
  ('official', 'points-150-75-v2', 10);

INSERT INTO app.round_schedules (
  code, version, timezone, eligible_competitions, window_rule, publish_rule,
  deadline_buffer_minutes, settle_cutoff_hours, correction_window_hours,
  config_version, rules_version, scoring_version, series_id, active_from)
SELECT 'weekend', 1, 'Africa/Johannesburg', ARRAY[39, 40, 288, 289, 140, 61, 78, 135],
  '{"start": {"weekday": "friday", "time": "00:00", "tz": "UTC"},
    "end": {"weekday": "tuesday", "time": "00:00", "tz": "UTC", "exclusive": true}}'::jsonb,
  '{"weekday": "thursday", "time": "08:00", "tz": "Africa/Johannesburg"}'::jsonb,
  15, 48, 24, 'broad60-432-v1', 'settle/v1', 'points-150-75-v2', s.id,
  '2026-11-19T00:00:00Z'
FROM app.championship_series s WHERE s.code = 'beta';
"""


def upgrade() -> None:
    op.execute(FUNCTIONS)
    op.execute(TABLES)
    op.execute(_triggers())
    op.execute(SEED)
    op.execute(_grants())


def downgrade() -> None:
    op.execute("DROP SCHEMA app CASCADE")
