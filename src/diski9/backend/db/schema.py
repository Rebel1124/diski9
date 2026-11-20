"""SQLAlchemy Core mirror of the competition schema (``app``) for queries.

The migration ``migrations_app/versions/app_0001_competition_schema.py`` is the
source of truth for constraints, indexes and triggers; this module declares the
tables and columns used to build statements. ``tests/backend/test_schema.py``
checks that the two agree column by column.

Table kinds: ``HISTORY`` tables are insert-only (enforced by triggers and
privileges); ``GUARDED`` tables allow one narrow, trigger-checked change; all
others are mutable current-state projections.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Double,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

SCHEMA = "app"
metadata = MetaData(schema=SCHEMA)


app_sessions = Table(
    "app_sessions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("authenticated_at", DateTime(timezone=True), nullable=False),
    Column("idle_expires_at", DateTime(timezone=True), nullable=False),
    Column("absolute_expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("rotated_from", Text, nullable=True),
    Column("user_agent_hash", Text, nullable=True),
    Column("provider_session_id", UUID(as_uuid=True), nullable=True),
    Column("provider_refresh_token_enc", Text, nullable=True),
    Column("provider_access_token_enc", Text, nullable=True),
    Column("provider_access_expires_at", DateTime(timezone=True), nullable=True),
    Column("provider_checked_at", DateTime(timezone=True), nullable=True),
    Column("reauthenticated_at", DateTime(timezone=True), nullable=True),
    Column("revoked_reason", Text, nullable=True),
)

auth_rate_events = Table(
    "auth_rate_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("bucket", Text, nullable=False),
    Column("key_hash", Text, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("actor_role", Text, nullable=True),
    Column("action", Text, nullable=False),
    Column("target_type", Text, nullable=False),
    Column("target_id", Text, nullable=False),
    Column("reason", Text, nullable=True),
    Column("before", JSONB, nullable=True),
    Column("after", JSONB, nullable=True),
    Column("request_id", Text, nullable=True),
    Column("job_run_id", BigInteger, nullable=True),
)

championships = Table(
    "championships",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("stream", Text, nullable=False),
    Column("series_id", BigInteger, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("rounds_required", SmallInteger, nullable=False),
    Column("counted_rounds", SmallInteger, nullable=False),
    Column("boundary_fixed_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("corrected_after_completion", Boolean, nullable=False),
    Column("current_version", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

championship_rounds = Table(
    "championship_rounds",
    metadata,
    Column("round_id", UUID(as_uuid=True), primary_key=True),
    Column("championship_id", UUID(as_uuid=True), nullable=False),
    Column("role", Text, nullable=False),
    Column("slot", SmallInteger, nullable=True),
    Column("assigned_at", DateTime(timezone=True), nullable=False),
)

championship_versions = Table(
    "championship_versions",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("championship_id", UUID(as_uuid=True), nullable=False),
    Column("version", Integer, nullable=False),
    Column("cause", Text, nullable=False),
    Column("cause_round_id", UUID(as_uuid=True), nullable=True),
    Column("cause_score_set_id", BigInteger, nullable=True),
    Column("status", Text, nullable=False),
    Column("counted_rounds", SmallInteger, nullable=False),
    Column("round_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
    Column("champion_count", Integer, nullable=False),
    Column("scoring_version", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

championship_standings = Table(
    "championship_standings",
    metadata,
    Column("version_id", BigInteger, primary_key=True),
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("rank", Integer, nullable=False),
    Column("points", Integer, nullable=False),
    Column("rounds_played", SmallInteger, nullable=False),
    Column("recoveries", SmallInteger, nullable=False),
    Column("qualifying_top10", SmallInteger, nullable=False),
    Column("display_order", Integer, nullable=False),
    Column("name_entry_id", UUID(as_uuid=True), nullable=False),
)

championship_series = Table(
    "championship_series",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("code", Text, nullable=False),
    Column("scoring_version", Text, nullable=False),
    Column("rounds_per_championship", Integer, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
)

designations = Table(
    "designations",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("designation", Text, nullable=False),
    Column("basis", Text, nullable=False),
    Column("round_evaluation_id", BigInteger, nullable=True),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("reason", Text, nullable=True),
    Column("provisional", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

domain_events = Table(
    "domain_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("kind", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=True),
    Column("round_id", UUID(as_uuid=True), nullable=True),
    Column("payload", JSONB, nullable=False),
)

entitlement_grants = Table(
    "entitlement_grants",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("feature_key", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("granted_by", UUID(as_uuid=True), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_to", DateTime(timezone=True), nullable=True),
    Column("reason", Text, nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("revoked_by", UUID(as_uuid=True), nullable=True),
    Column("revoke_reason", Text, nullable=True),
)

entries = Table(
    "entries",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("state", Text, nullable=False),
    Column("current_submission_id", UUID(as_uuid=True), nullable=True),
    Column("version", Integer, nullable=False),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_submission_id", UUID(as_uuid=True), nullable=True),
    Column("public_name_at_lock", Text, nullable=True),
    Column("privacy_mode_at_lock", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

entry_events = Table(
    "entry_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("entry_id", UUID(as_uuid=True), nullable=False),
    Column("kind", Text, nullable=False),
    Column("submission_id", UUID(as_uuid=True), nullable=True),
    Column("previous_submission_id", UUID(as_uuid=True), nullable=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
)

entry_settlements = Table(
    "entry_settlements",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, nullable=False),
    Column("entry_id", UUID(as_uuid=True), nullable=False),
    Column("submission_id", UUID(as_uuid=True), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("gross", Numeric(14, 2, asdecimal=True), nullable=False),
    Column("net", Numeric(14, 2, asdecimal=True), nullable=False),
    Column("legs", JSONB, nullable=False),
    Column("basis", Text, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

features = Table(
    "features",
    metadata,
    Column("key", Text, primary_key=True),
    Column("description", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

job_runs = Table(
    "job_runs",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("job", Text, nullable=False),
    Column("scope", Text, nullable=False),
    Column("args", JSONB, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("status", Text, nullable=False),
    Column("api_requests", Integer, nullable=False),
    Column("error", Text, nullable=True),
    Column("host", Text, nullable=True),
)

portfolio_drafts = Table(
    "portfolio_drafts",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("round_id", UUID(as_uuid=True), primary_key=True),
    Column("selections", JSONB, nullable=False),
    Column("snapshot_fingerprint", Text, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("version", Integer, nullable=False, server_default=text("0")),
    Column("writer_tab", Text, nullable=True),
    Column("writer_seq", BigInteger, nullable=True),
)

privacy_history = Table(
    "privacy_history",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("privacy_mode", Text, nullable=False),
    Column("retroactive", Boolean, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
)

profiles = Table(
    "profiles",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("username", Text, nullable=False),
    Column("username_key", Text, nullable=False),
    Column("username_changed_at", DateTime(timezone=True), nullable=False),
    Column("privacy_mode", Text, nullable=False),
    Column("anonymous_alias", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

result_observations = Table(
    "result_observations",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("fixture_id", BigInteger, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("source", Text, nullable=False),
    Column("status_short", Text, nullable=True),
    Column("kickoff_at", DateTime(timezone=True), nullable=True),
    Column("actual_kickoff_at", DateTime(timezone=True), nullable=True),
    Column("ft_home", SmallInteger, nullable=True),
    Column("ft_away", SmallInteger, nullable=True),
    Column("raw", JSONB, nullable=True),
    Column("raw_hash", Text, nullable=False),
    Column("job_run_id", BigInteger, nullable=True),
    Column("corrects_observation_id", BigInteger, nullable=True),
    Column("withdraws_correction_id", BigInteger, nullable=True),
    Column("original_values", JSONB, nullable=True),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("reason", Text, nullable=True),
    Column("scope_round_id", UUID(as_uuid=True), nullable=True),
    Column("provider_first_half_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("evidence", Text, nullable=True),
)

round_evaluations = Table(
    "round_evaluations",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, nullable=False),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("rule", Text, nullable=False),
    Column("total_predictions", Integer, nullable=False),
    Column("played_predictions", Integer, nullable=False),
    Column("void_predictions", Integer, nullable=False),
    Column("pending_predictions", Integer, nullable=False),
    Column("ranked_entries", Integer, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

round_schedules = Table(
    "round_schedules",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("code", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("eligible_competitions", ARRAY(Integer), nullable=False),
    Column("window_rule", JSONB, nullable=False),
    Column("publish_rule", JSONB, nullable=False),
    Column("deadline_buffer_minutes", Integer, nullable=False),
    Column("settle_cutoff_hours", Integer, nullable=False),
    Column("correction_window_hours", Integer, nullable=False),
    Column("config_version", Text, nullable=False),
    Column("rules_version", Text, nullable=False),
    Column("scoring_version", Text, nullable=False),
    Column("series_id", BigInteger, nullable=False),
    Column("active_from", DateTime(timezone=True), nullable=False),
    Column("active_to", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

round_scores = Table(
    "round_scores",
    metadata,
    Column("score_set_id", BigInteger, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("entry_id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("gross", Numeric(14, 2, asdecimal=True), nullable=False),
    Column("rank", Integer, nullable=True),
    Column("points", Integer, nullable=False),
    Column("recovered", Boolean, nullable=False),
    Column("qualifying_top10", Boolean, nullable=False),
    Column("status", Text, nullable=False),
    Column("display_order", Integer, nullable=False),
)

round_snapshots = Table(
    "round_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("fingerprint", Text, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("params_hash", Text, nullable=True),
    Column("forecast_cutoff_at", DateTime(timezone=True), nullable=True),
    Column("feasibility", JSONB, nullable=False),
    Column("source_job_run_id", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

round_status_history = Table(
    "round_status_history",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("from_status", Text, nullable=True),
    Column("to_status", Text, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("job_run_id", BigInteger, nullable=True),
    Column("reason", Text, nullable=True),
)

rounds = Table(
    "rounds",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("code", Text, nullable=False),
    Column("schedule_id", BigInteger, nullable=False),
    Column("series_id", BigInteger, nullable=False),
    Column("window_start_at", DateTime(timezone=True), nullable=False),
    Column("window_end_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("deadline_at", DateTime(timezone=True), nullable=True),
    Column("settle_cutoff_at", DateTime(timezone=True), nullable=True),
    Column("finalised_at", DateTime(timezone=True), nullable=True),
    Column("config_version", Text, nullable=True),
    Column("rules_version", Text, nullable=True),
    Column("scoring_version", Text, nullable=True),
    Column("model_version", Text, nullable=True),
    Column("valid_entries", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("is_development", Boolean, nullable=False, server_default=text("false")),
    Column("correction_window_hours", Integer, nullable=True),
    Column("result_mode", Text, nullable=True),
)

score_sets = Table(
    "score_sets",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("run_id", BigInteger, nullable=False),
    Column("designation_id", BigInteger, nullable=False),
    Column("kind", Text, nullable=False),
    Column("final", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("settlement_version_id", BigInteger, nullable=False),
    Column("scoring_version", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
)

selection_verdicts = Table(
    "selection_verdicts",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, nullable=False),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("fixture_id", BigInteger, nullable=False),
    Column("market", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("verdict", Text, nullable=False),
    Column("void_code", Text, nullable=True),
    Column("result_observation_id", BigInteger, nullable=True),
    Column("revision", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("rule", Text, nullable=True),
    Column("evidence", JSONB, nullable=True),
    Column("material", Boolean, nullable=False, server_default=text("true")),
)

settlement_runs = Table(
    "settlement_runs",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("job_run_id", BigInteger, nullable=True),
    Column("trigger", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("status", Text, nullable=False),
    Column("inputs_hash", Text, nullable=True),
    Column("changed_verdicts", Integer, nullable=False),
    Column("changed_entries", Integer, nullable=False),
    Column("error", Text, nullable=True),
    Column("evaluated_at", DateTime(timezone=True), nullable=True),
    Column("phase", Text, nullable=True),
    Column("time_override", Boolean, nullable=False, server_default=text("false")),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("manifest", JSONB, nullable=True),
    Column("evidence_through_id", BigInteger, nullable=True),
    Column("material", Boolean, nullable=False, server_default=text("false")),
)

settlement_versions = Table(
    "settlement_versions",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("version", Integer, nullable=False),
    Column("run_id", BigInteger, nullable=True),
    Column("kind", Text, nullable=False),
    Column("material", Boolean, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("reason", Text, nullable=True),
    Column("evidence", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

settlement_alerts = Table(
    "settlement_alerts",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("fixture_id", BigInteger, nullable=True),
    Column("run_id", BigInteger, nullable=True),
    Column("code", Text, nullable=False),
    Column("blocking", Boolean, nullable=False),
    Column("fingerprint", Text, nullable=False),
    Column("detail", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

settlement_alert_resolutions = Table(
    "settlement_alert_resolutions",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("alert_id", BigInteger, nullable=False),
    Column("resolution", Text, nullable=False),
    Column("actor_user_id", UUID(as_uuid=True), nullable=True),
    Column("reason", Text, nullable=False),
    Column("observation_id", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

snapshot_fixtures = Table(
    "snapshot_fixtures",
    metadata,
    Column("snapshot_id", BigInteger, primary_key=True),
    Column("fixture_id", BigInteger, primary_key=True),
    Column("competition_id", Integer, nullable=False),
    Column("home_team", Text, nullable=False),
    Column("away_team", Text, nullable=False),
    Column("kickoff_at_publish", DateTime(timezone=True), nullable=False),
    Column("estimated_goals_home", Double, nullable=True),
    Column("estimated_goals_away", Double, nullable=True),
)

snapshot_offers = Table(
    "snapshot_offers",
    metadata,
    Column("snapshot_id", BigInteger, primary_key=True),
    Column("fixture_id", BigInteger, primary_key=True),
    Column("market", Text, primary_key=True),
    Column("outcome", Text, primary_key=True),
    Column("model_prob", Double, nullable=True),
    Column("consensus_odds", Numeric(8, 2, asdecimal=True), nullable=True),
    Column("market_prob", Double, nullable=True),
    Column("bookmaker_groups", Integer, nullable=True),
    Column("latest_observation_at", DateTime(timezone=True), nullable=True),
    Column("provider_updated_at", DateTime(timezone=True), nullable=True),
    Column("eligible", Boolean, nullable=False),
    Column("bucket", Text, nullable=True),
    Column("ineligible_reason", Text, nullable=True),
)

submission_selections = Table(
    "submission_selections",
    metadata,
    Column("submission_id", UUID(as_uuid=True), primary_key=True),
    Column("snapshot_id", BigInteger, nullable=False),
    Column("position", SmallInteger, primary_key=True),
    Column("fixture_id", BigInteger, nullable=False),
    Column("market", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("bucket", Text, nullable=False),
    Column("model_prob", Double, nullable=True),
    Column("consensus_odds", Numeric(8, 2, asdecimal=True), nullable=False),
    Column("market_prob", Double, nullable=False),
    Column("bookmaker_groups", Integer, nullable=False),
)

submissions = Table(
    "submissions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("entry_id", UUID(as_uuid=True), nullable=False),
    Column("round_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("snapshot_id", BigInteger, nullable=False),
    Column("version", Integer, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=False),
    Column("inputs_hash", Text, nullable=False),
    Column("p_recover_market", Double, nullable=False),
    Column("p_recover_model", Double, nullable=True),
    Column("expected_gross_market", Double, nullable=False),
    Column("expected_gross_model", Double, nullable=True),
    Column("max_gross", Numeric(14, 2, asdecimal=True), nullable=False),
    Column("states", JSONB, nullable=False),
    Column("config_version", Text, nullable=False),
    Column("calc_version", Text, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("rules_version", Text, nullable=False),
)

terms_acceptances = Table(
    "terms_acceptances",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("terms_version", Text, nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("age_confirmed", Boolean, nullable=False),
)

terms_versions = Table(
    "terms_versions",
    metadata,
    Column("version", Text, primary_key=True),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("minimum_age", Integer, nullable=False),
    Column("requires_reacceptance", Boolean, nullable=False),
)

user_identities = Table(
    "user_identities",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("provider", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_sign_in_at", DateTime(timezone=True), nullable=True),
)

user_private = Table(
    "user_private",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("email", Text, nullable=True),
    Column("email_verified", Boolean, nullable=False),
    Column("age_confirmed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("role", Text, primary_key=True),
    Column("granted_by", UUID(as_uuid=True), nullable=True),
    Column("granted_at", DateTime(timezone=True), nullable=False),
)

username_history = Table(
    "username_history",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("username", Text, nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("changed_by", UUID(as_uuid=True), nullable=True),
    Column("reason", Text, nullable=True),
)

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
)

your_view_adjustments = Table(
    "your_view_adjustments",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("fixture_id", BigInteger, nullable=False),
    Column("context_kind", Text, nullable=False),
    Column("snapshot_id", BigInteger, nullable=True),
    Column("model_context", Text, nullable=False),
    Column("state", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("version", Integer, nullable=False, server_default=text("0")),
    Column("writer_tab", Text, nullable=True),
    Column("writer_seq", BigInteger, nullable=True),
)

HISTORY = frozenset(
    [
        "audit_log",
        "championship_standings",
        "championship_versions",
        "designations",
        "domain_events",
        "entry_events",
        "entry_settlements",
        "privacy_history",
        "result_observations",
        "round_evaluations",
        "round_scores",
        "round_snapshots",
        "round_status_history",
        "score_sets",
        "selection_verdicts",
        "settlement_alert_resolutions",
        "settlement_alerts",
        "settlement_versions",
        "snapshot_fixtures",
        "snapshot_offers",
        "submission_selections",
        "submissions",
        "terms_acceptances",
    ]
)
GUARDED = frozenset(
    [
        "championship_rounds",
        "championships",
        "entitlement_grants",
        "job_runs",
        "settlement_runs",
        "username_history",
    ]
)
# appended and purged (never updated): authentication rate-limit events
APPEND_PURGE = frozenset({"auth_rate_events"})
PROJECTION = frozenset(t.name for t in metadata.sorted_tables) - HISTORY - GUARDED - APPEND_PURGE
