"""add_cost_tracking_and_user_isolation

Revision ID: a1b2c3d4e5f6
Revises: 89631f200021
Create Date: 2026-03-21

Adds:
  - llm_traces.estimated_cost_usd  — per-call USD cost for LLM observability
  - workflow_runs.user_id          — per-user run isolation
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "89631f200021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_traces",
        sa.Column("estimated_cost_usd", sa.Float, nullable=False, server_default="0.0"),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("user_id", sa.String(128), nullable=True),
    )
    op.create_index("ix_workflow_runs_user_id", "workflow_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_user_id", "workflow_runs")
    op.drop_column("workflow_runs", "user_id")
    op.drop_column("llm_traces", "estimated_cost_usd")
