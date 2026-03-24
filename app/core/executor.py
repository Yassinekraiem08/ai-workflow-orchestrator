import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.executor_agent import ExecutorAgent
from app.agents.fallback_agent import FallbackAgent
from app.config import settings
from app.core import state_manager
from app.db.models import WorkflowStep
from app.services import workflow_service
from app.services.llm_service import estimate_cost
from app.services.logging_service import get_logger
from app.tools.base import tool_registry
from app.utils.enums import StepStatus
from app.utils.exceptions import ToolExecutionError

logger = get_logger(__name__)

_executor_agent = ExecutorAgent()
_fallback_agent = FallbackAgent()


async def execute_step(
    db: AsyncSession,
    step: WorkflowStep,
    run_context: dict[str, Any],
    raw_input: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Executes a single workflow step with tool call + executor agent synthesis.
    Returns the step's output dict. On repeated failure, invokes FallbackAgent.
    """
    run_id = step.run_id
    step_id = step.id
    step_input = step.input_data or {}
    tool_name = step_input.get("tool_name")
    tool_arguments = step_input.get("tool_arguments") or {}

    await workflow_service.start_step(db, step_id)
    log = logger.bind(run_id=run_id, step_id=step_id, step_name=step.step_name)
    log.info("step_started", tool_name=tool_name)

    tool_result: dict[str, Any] | None = None

    # --- Tool execution with retries ---
    if tool_name:
        tool_result = await _execute_tool_with_retries(
            db=db,
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            log=log,
        )

    # --- Executor agent synthesis ---
    try:
        agent_result = await _executor_agent.run({
            "step": {
                "step_name": step.step_name,
                "step_order": step.step_order,
                "description": step_input.get("description", ""),
            },
            "tool_result": tool_result,
            "run_context": run_context,
            "raw_input": raw_input,
        }, api_key=api_key)

        await workflow_service.record_llm_trace(
            db=db,
            run_id=run_id,
            agent_name="executor_agent",
            prompt_summary=f"Execute step: {step.step_name}",
            model_name=agent_result.model_name,
            tokens_in=agent_result.tokens_in,
            tokens_out=agent_result.tokens_out,
            latency_ms=agent_result.latency_ms,
            estimated_cost_usd=estimate_cost(
                agent_result.model_name,
                agent_result.tokens_in,
                agent_result.tokens_out,
            ),
        )

        output = agent_result.parsed_output
        output["tool_result"] = tool_result

        await workflow_service.complete_step(db, step_id, output)
        await state_manager.append_completed_step(run_id, {
            "step_name": step.step_name,
            "summary": output.get("summary", ""),
            "severity": output.get("severity"),
        })

        log.info("step_completed", summary=output.get("summary", "")[:100])
        return output

    except Exception as e:
        log.warning("executor_agent_failed", error=str(e), step_name=step.step_name)
        return await _run_fallback(
            db=db,
            step=step,
            failure_reason=str(e),
            raw_input=raw_input,
            run_id=run_id,
            log=log,
        )


async def _execute_tool_with_retries(
    db: AsyncSession,
    run_id: str,
    step_id: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
    log: Any,
) -> dict[str, Any] | None:
    max_retries = settings.max_tool_retries
    delay = 1.0

    for attempt in range(max_retries):
        try:
            tool = tool_registry.get(tool_name)
            tool_result = await tool.execute(tool_arguments)

            await workflow_service.record_tool_call(
                db=db,
                run_id=run_id,
                step_id=step_id,
                tool_name=tool_name,
                arguments=tool_arguments,
                result=tool_result.output,
                success=tool_result.success,
                latency_ms=tool_result.latency_ms,
            )

            if not tool_result.success:
                log.warning("tool_returned_failure", tool=tool_name, error=tool_result.error)

            return tool_result.model_dump()

        except KeyError as e:
            # Tool not registered — no point retrying
            log.error("tool_not_found", tool_name=tool_name, error=str(e))
            raise ToolExecutionError(tool_name, f"Tool not registered: {e}") from e

        except Exception as e:
            log.warning("tool_attempt_failed", tool=tool_name, attempt=attempt + 1, error=str(e))
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise ToolExecutionError(tool_name, str(e)) from e

    return None


async def _run_fallback(
    db: AsyncSession,
    step: WorkflowStep,
    failure_reason: str,
    raw_input: str,
    run_id: str,
    log: Any,
    api_key: str | None = None,
) -> dict[str, Any]:
    log.warning("invoking_fallback_agent", step_name=step.step_name)
    try:
        fallback_result = await _fallback_agent.run({
            "step_name": step.step_name,
            "failure_reason": failure_reason,
            "original_input": raw_input,
        }, api_key=api_key)
        output = fallback_result.parsed_output
        output["_fallback_used"] = True

        await workflow_service.complete_step(db, step.id, output, status=StepStatus.SKIPPED)
        log.info("fallback_step_skipped", step_name=step.step_name)
        return output

    except Exception as fallback_error:
        log.error("fallback_agent_failed", error=str(fallback_error))
        error_output = {
            "summary": f"Step '{step.step_name}' failed and fallback also failed.",
            "key_findings": [],
            "next_action": "Manual review required",
            "_fallback_used": True,
            "_error": str(fallback_error),
        }
        await workflow_service.complete_step(db, step.id, error_output, status=StepStatus.SKIPPED)
        return error_output
