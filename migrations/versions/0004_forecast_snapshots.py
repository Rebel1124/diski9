"""Engine 3.0: insert-only pre-kickoff forecast snapshots

Revision ID: 0004
Revises: 0003

Rollback (``alembic downgrade 0003``) drops the table and its triggers; the
snapshots are lost, so export them first if they matter (they cannot be
recomputed honestly afterwards, because a recomputation would not be a forecast
made before kickoff).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecast_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("kickoff_utc", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("data_cutoff", sa.String(length=32), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("goal_model_version", sa.String(length=20), nullable=False),
        sa.Column("params_hash", sa.String(length=32), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("lambda_home", sa.Float(), nullable=False),
        sa.Column("lambda_away", sa.Float(), nullable=False),
        sa.Column("p_home", sa.Float(), nullable=False),
        sa.Column("p_draw", sa.Float(), nullable=False),
        sa.Column("p_away", sa.Float(), nullable=False),
        sa.Column("p_btts_yes", sa.Float(), nullable=False),
        sa.Column("p_over", sa.Float(), nullable=False),
        sa.Column("baseline_json", sa.Text(), nullable=True),
        sa.Column("forecast_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pre_kickoff'"), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"], name=op.f("fk_forecast_snapshots_fixture_id_fixtures")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_snapshots")),
    )
    op.create_index(
        "ix_forecast_snapshots_fixture",
        "forecast_snapshots",
        ["fixture_id", "goal_model_version", "created_at"],
    )
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER forecast_snapshots_no_{event.lower()} BEFORE {event} "
            "ON forecast_snapshots BEGIN "
            "SELECT RAISE(ABORT, 'forecast snapshots are immutable'); END"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS forecast_snapshots_no_update")
    op.execute("DROP TRIGGER IF EXISTS forecast_snapshots_no_delete")
    op.drop_index("ix_forecast_snapshots_fixture", table_name="forecast_snapshots")
    op.drop_table("forecast_snapshots")
