from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.utils.enums import InputType, RunStatus, StepStatus


# --- Requests ---

class WorkflowSubmitRequest(BaseModel):
    input_type: InputType
    raw_input: str = Field(..., min_length=1, max_length=10_000)
    priority: int = Field(default=5, ge=1, le=10)


class WorkflowRetryRequest(BaseModel):
    pass  # No body needed; run_id comes from path


# --- Responses ---

class WorkflowRunResponse(BaseModel):
    model_config = {"from_attributes": True}

    run_id: str
    status: RunStatus
    input_type: InputType
    priority: int
    created_at: datetime
    updated_at: datetime
    final_output: str | None = None

    @classmethod
    def from_orm_run(cls, run: Any) -> "WorkflowRunResponse":
        return cls(
            run_id=run.id,
            status=run.status,
            input_type=run.input_type,
            priority=run.priority,
            created_at=run.created_at,
            updated_at=run.updated_at,
            final_output=run.final_output,
        )


class WorkflowStepResponse(BaseModel):
    model_config = {"from_attributes": True}

    step_id: str
    step_name: str
    step_order: int
    status: StepStatus
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_orm_step(cls, step: Any) -> "WorkflowStepResponse":
        return cls(
            step_id=step.id,
            step_name=step.step_name,
            step_order=step.step_order,
            status=step.status,
            input_data=step.input_data,
            output_data=step.output_data,
            error_message=step.error_message,
            started_at=step.started_at,
            completed_at=step.completed_at,
        )


class WorkflowStepsResponse(BaseModel):
    run_id: str
    steps: list[WorkflowStepResponse]


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"


class FailureBreakdown(BaseModel):
    by_status: dict[str, int]
    by_tool: dict[str, int]


class MetricsResponse(BaseModel):
    total_runs: int
    completed_runs: int
    failed_runs: int
    success_rate: float
    avg_latency_ms: float
    total_tokens_in: int
    total_tokens_out: int
    failure_breakdown: FailureBreakdown
