from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMTrace, ToolCall, WorkflowRun, WorkflowStep
from app.utils.enums import RunStatus, StepStatus
from app.utils.exceptions import WorkflowNotFoundError
from app.utils.helpers import generate_step_id, generate_trace_id, utcnow


async def create_run(
    db: AsyncSession,
    run_id: str,
    input_type: str,
    raw_input: str,
    priority: int,
) -> WorkflowRun:
    now = utcnow()
    run = WorkflowRun(
        id=run_id,
        input_type=input_type,
        raw_input=raw_input,
        status=RunStatus.PENDING,
        priority=priority,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, run_id: str) -> WorkflowRun:
    result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise WorkflowNotFoundError(run_id)
    return run


async def update_run_status(
    db: AsyncSession, run_id: str, status: RunStatus, final_output: str | None = None
) -> None:
    run = await get_run(db, run_id)
    run.status = status
    run.updated_at = utcnow()
    if final_output is not None:
        run.final_output = final_output
    await db.commit()


async def create_step(
    db: AsyncSession,
    run_id: str,
    step_name: str,
    step_order: int,
    input_data: dict[str, Any] | None = None,
) -> WorkflowStep:
    step = WorkflowStep(
        id=generate_step_id(),
        run_id=run_id,
        step_name=step_name,
        step_order=step_order,
        status=StepStatus.PENDING,
        input_data=input_data,
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return step


async def start_step(db: AsyncSession, step_id: str) -> None:
    result = await db.execute(select(WorkflowStep).where(WorkflowStep.id == step_id))
    step = result.scalar_one_or_none()
    if step:
        step.status = StepStatus.RUNNING
        step.started_at = utcnow()
        await db.commit()


async def complete_step(
    db: AsyncSession,
    step_id: str,
    output_data: dict[str, Any],
    status: StepStatus = StepStatus.COMPLETED,
) -> None:
    result = await db.execute(select(WorkflowStep).where(WorkflowStep.id == step_id))
    step = result.scalar_one_or_none()
    if step:
        step.status = status
        step.output_data = output_data
        step.completed_at = utcnow()
        await db.commit()


async def fail_step(db: AsyncSession, step_id: str, error_message: str) -> None:
    result = await db.execute(select(WorkflowStep).where(WorkflowStep.id == step_id))
    step = result.scalar_one_or_none()
    if step:
        step.status = StepStatus.FAILED
        step.error_message = error_message
        step.completed_at = utcnow()
        await db.commit()


async def get_steps(db: AsyncSession, run_id: str) -> list[WorkflowStep]:
    result = await db.execute(
        select(WorkflowStep)
        .where(WorkflowStep.run_id == run_id)
        .order_by(WorkflowStep.step_order)
    )
    return list(result.scalars().all())


async def record_tool_call(
    db: AsyncSession,
    run_id: str,
    step_id: str | None,
    tool_name: str,
    arguments: dict[str, Any] | None,
    result: dict[str, Any] | None,
    success: bool,
    latency_ms: int,
) -> None:
    tool_call = ToolCall(
        id=generate_trace_id(),
        run_id=run_id,
        step_id=step_id,
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        success=success,
        latency_ms=latency_ms,
    )
    db.add(tool_call)
    await db.commit()


async def record_llm_trace(
    db: AsyncSession,
    run_id: str,
    agent_name: str,
    prompt_summary: str,
    model_name: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
) -> None:
    trace = LLMTrace(
        id=generate_trace_id(),
        run_id=run_id,
        agent_name=agent_name,
        prompt_summary=prompt_summary,
        model_name=model_name,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    )
    db.add(trace)
    await db.commit()


async def reset_run_for_retry(db: AsyncSession, run_id: str) -> None:
    run = await get_run(db, run_id)
    run.status = RunStatus.PENDING
    run.updated_at = utcnow()
    run.final_output = None
    await db.commit()
