"""screener cache, approved home grounds, venue classification rename

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approved_home_grounds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False, comment="API team id"),
        sa.Column("venue_id", sa.Integer(), nullable=False, comment="API venue id"),
        sa.Column("valid_from", sa.String(length=10), nullable=False, comment="YYYY-MM-DD inclusive"),
        sa.Column("valid_to", sa.String(length=10), nullable=True, comment="YYYY-MM-DD inclusive; NULL = open"),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approved_home_grounds")),
        sa.UniqueConstraint("team_id", "venue_id", "valid_from", name="uq_approved_home_grounds_key"),
    )
    op.create_table(
        "screener_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fixture_id", sa.Integer(), nullable=False),
        sa.Column("basis", sa.String(length=10), nullable=False, comment="venue | overall"),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("as_of", sa.String(length=32), nullable=False, comment="Reference time requested"),
        sa.Column("cutoff", sa.String(length=32), nullable=False,
                  comment="Only matches kicking off before this were used (min(as_of, kickoff))"),
        sa.Column("calculated_at", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.String(length=32), nullable=False, comment="Last refresh confirming the result"),
        sa.Column("superseded_at", sa.String(length=32), nullable=True, comment="NULL = current cached result"),
        sa.Column("inputs_hash", sa.String(length=64), nullable=False),
        sa.Column("home_form", sa.Float(), nullable=True),
        sa.Column("away_form", sa.Float(), nullable=True),
        sa.Column("raw_difference", sa.Float(), nullable=True),
        sa.Column("venue_adjusted_difference", sa.Float(), nullable=True),
        sa.Column("benchmark_season", sa.Integer(), nullable=True),
        sa.Column("benchmark_source", sa.String(length=20), nullable=True),
        sa.Column("benchmark_matches", sa.Integer(), nullable=True),
        sa.Column("btts_yes_indicator", sa.Float(), nullable=True),
        sa.Column("over25_indicator", sa.Float(), nullable=True),
        sa.Column("limited_data", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, comment="Full calculation breakdown (JSON)"),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"], name=op.f("fk_screener_results_fixture_id_fixtures")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screener_results")),
    )
    with op.batch_alter_table("screener_results", schema=None) as batch_op:
        batch_op.create_index(
            "uq_screener_results_active",
            ["fixture_id", "basis", "engine_version"],
            unique=True,
            sqlite_where=sa.text("superseded_at IS NULL"),
        )
    op.execute(
        "UPDATE fixtures SET venue_classification = 'unverified_venue' "
        "WHERE venue_classification = 'potential_neutral'"
    )
    with op.batch_alter_table("fixtures", schema=None) as batch_op:
        batch_op.alter_column(
            "venue_classification",
            existing_type=sa.String(length=20),
            comment="home_ground | unverified_venue | neutral | unknown",
            existing_nullable=False,
            existing_server_default=sa.text("'unknown'"),
        )


def downgrade() -> None:
    with op.batch_alter_table("fixtures", schema=None) as batch_op:
        batch_op.alter_column(
            "venue_classification",
            existing_type=sa.String(length=20),
            comment="home_ground | potential_neutral | neutral | unknown",
            existing_nullable=False,
            existing_server_default=sa.text("'unknown'"),
        )
    op.execute(
        "UPDATE fixtures SET venue_classification = 'potential_neutral' "
        "WHERE venue_classification = 'unverified_venue'"
    )
    with op.batch_alter_table("screener_results", schema=None) as batch_op:
        batch_op.drop_index("uq_screener_results_active", sqlite_where=sa.text("superseded_at IS NULL"))
    op.drop_table("screener_results")
    op.drop_table("approved_home_grounds")
