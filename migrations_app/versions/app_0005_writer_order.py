"""Save ordering within one browser tab (Phase 6C.3, Stage F).

Revision ID: app_0005
Revises: app_0004
Create Date: 2026-11-19

The Dash front end may send a newer save from the same tab before an older one
has finished (the older response is then discarded by the browser, but the
server still runs it). Each draft and Your View row therefore records which tab
wrote it last (``writer_tab``: a random per-tab token, not linked to any identity)
and that tab's request sequence (``writer_seq``). A tab's newer save may replace
its own older one; an older save arriving late is ignored. Saves from another
tab or device still need the current version (optimistic concurrency unchanged).

Additive only; never touches Supabase schemas.
"""

from __future__ import annotations

from alembic import op

revision = "app_0005"
down_revision = "app_0004"
branch_labels = None
depends_on = None

UP = r"""
ALTER TABLE app.portfolio_drafts
  ADD COLUMN writer_tab text CHECK (writer_tab ~ '^[A-Za-z0-9_-]{16,64}$'),
  ADD COLUMN writer_seq bigint CHECK (writer_seq >= 0);
ALTER TABLE app.your_view_adjustments
  ADD COLUMN writer_tab text CHECK (writer_tab ~ '^[A-Za-z0-9_-]{16,64}$'),
  ADD COLUMN writer_seq bigint CHECK (writer_seq >= 0);
"""

DOWN = r"""
ALTER TABLE app.your_view_adjustments DROP COLUMN writer_seq, DROP COLUMN writer_tab;
ALTER TABLE app.portfolio_drafts DROP COLUMN writer_seq, DROP COLUMN writer_tab;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
