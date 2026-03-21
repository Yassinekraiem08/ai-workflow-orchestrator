"""initial_schema

Revision ID: 89631f200021
Revises:
Create Date: 2026-03-20

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "89631f200021"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("input_type", sa.String(20), nullable=False),
        sa.Column("raw_input", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("final_output", sa.Text, nullable=True),
    )
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"])

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("step_name", sa.String(100), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("input_data", sa.JSON, nullable=True),
        sa.Column("output_data", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_steps_run_order", "workflow_steps", ["run_id", "step_order"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("step_id", sa.String(32), sa.ForeignKey("workflow_steps.id"), nullable=True),
        sa.Column("tool_name", sa.String(50), nullable=False),
        sa.Column("arguments", sa.JSON, nullable=True),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_tool_calls_run_success", "tool_calls", ["run_id", "success"])

    op.create_table(
        "llm_traces",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("agent_name", sa.String(50), nullable=False),
        sa.Column("prompt_summary", sa.Text, nullable=True),
        sa.Column("model_name", sa.String(50), nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_llm_traces_run_id", "llm_traces", ["run_id"])


def downgrade() -> None:
    op.drop_table("llm_traces")
    op.drop_table("tool_calls")
    op.drop_table("workflow_steps")
    op.drop_table("workflow_runs")
