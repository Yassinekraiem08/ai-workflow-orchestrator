"""add safety, cache, and quality columns to workflow_runs

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-03-22

Adds:
  - workflow_runs.safety_flagged   — whether input was blocked by safety filter
  - workflow_runs.safety_reason    — reason text for safety violations
  - workflow_runs.cache_hit        — whether output was served from semantic cache
  - workflow_runs.quality_score    — LLM-as-judge overall score (0-1)
  - workflow_runs.quality_breakdown — per-dimension judge scores (JSON)
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a1"
down_revision: str | None = "a1b2c3d4e5f6"
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
