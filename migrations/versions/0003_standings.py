"""official standings snapshots

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "standings_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("played", sa.Integer(), nullable=False),
        sa.Column("won", sa.Integer(), nullable=False),
        sa.Column("drawn", sa.Integer(), nullable=False),
        sa.Column("lost", sa.Integer(), nullable=False),
        sa.Column("goals_for", sa.Integer(), nullable=False),
        sa.Column("goals_against", sa.Integer(), nullable=False),
        sa.Column("goal_difference", sa.Integer(), nullable=False),
        sa.Column("form", sa.String(length=10), nullable=True),
        sa.Column("description", sa.String(length=120), nullable=True),
        sa.Column("group_name", sa.String(length=120), nullable=True),
        sa.Column("provider_updated_at", sa.String(length=32), nullable=True, comment="API 'update' for the row"),
        sa.Column("retrieved_at", sa.String(length=32), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["competition_id", "season"], ["seasons.competition_id", "seasons.year"],
                                name="fk_standings_snapshots_season_seasons"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name=op.f("fk_standings_snapshots_team_id_teams")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standings_snapshots")),
    )
    with op.batch_alter_table("standings_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            "ix_standings_comp_season_retrieved", ["competition_id", "season", "retrieved_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("standings_snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_standings_comp_season_retrieved")
    op.drop_table("standings_snapshots")
