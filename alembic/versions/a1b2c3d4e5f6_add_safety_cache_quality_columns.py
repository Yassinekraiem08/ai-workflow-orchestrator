"""add safety, cache, and quality columns to workflow_runs

Revision ID: a1b2c3d4e5f6
Revises: 89631f200021
Create Date: 2026-03-22

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "89631f200021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("safety_flagged", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("workflow_runs", sa.Column("safety_reason", sa.Text(), nullable=True))
    op.add_column("workflow_runs", sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("workflow_runs", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column("workflow_runs", sa.Column("quality_breakdown", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "quality_breakdown")
    op.drop_column("workflow_runs", "quality_score")
    op.drop_column("workflow_runs", "cache_hit")
    op.drop_column("workflow_runs", "safety_reason")
    op.drop_column("workflow_runs", "safety_flagged")
