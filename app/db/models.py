from datetime import datetime
from typing import Any

from sqlalchemy import (
    String, Text, Integer, Boolean, DateTime, JSON,
    ForeignKey, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    input_type: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    final_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps: Mapped[list["WorkflowStep"]] = relationship(
        "WorkflowStep", back_populates="run", cascade="all, delete-orphan"
    )
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        "ToolCall", back_populates="run", cascade="all, delete-orphan"
    )
    llm_traces: Mapped[list["LLMTrace"]] = relationship(
        "LLMTrace", back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_created_at", "created_at"),
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("workflow_runs.id"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(100), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="steps")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        "ToolCall", back_populates="step", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_workflow_steps_run_order", "run_id", "step_order"),
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("workflow_runs.id"), nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("workflow_steps.id"), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="tool_calls")
    step: Mapped["WorkflowStep | None"] = relationship("WorkflowStep", back_populates="tool_calls")

    __table_args__ = (
        Index("ix_tool_calls_run_success", "run_id", "success"),
    )


class LLMTrace(Base):
    __tablename__ = "llm_traces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("workflow_runs.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="llm_traces")

    __table_args__ = (
        Index("ix_llm_traces_run_id", "run_id"),
    )
