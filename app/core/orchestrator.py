from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.classifier_agent import ClassifierAgent
from app.agents.planner_agent import PlannerAgent
from app.config import settings
from app.core import executor, planner, router, state_manager
from app.db.session import AsyncSessionFactory
from app.services import workflow_service
from app.services.logging_service import get_logger
from app.utils.enums import InputType, RunStatus
from app.utils.exceptions import ClassificationError, OrchestratorError, PlanningError

logger = get_logger(__name__)

_classifier = ClassifierAgent()
_planner = PlannerAgent()


class OrchestratorInput(BaseModel):
    run_id: str
    input_type: InputType
    raw_input: str
    priority: int = 5


class OrchestratorResult(BaseModel):
    run_id: str
    status: RunStatus
    final_output: str | None = None
    steps_completed: int = 0
    steps_total: int = 0
    error: str | None = None


async def run_workflow(input: OrchestratorInput) -> OrchestratorResult:
    """
    Top-level workflow coordinator. Owns the full run lifecycle:
    PENDING → RUNNING → (classify → plan → execute) → COMPLETED | FAILED
    """
    run_id = input.run_id
    log = logger.bind(run_id=run_id, input_type=input.input_type)
    log.info("workflow_started")

    async with AsyncSessionFactory() as db:
        try:
            await state_manager.set_status(run_id, RunStatus.RUNNING)
            await workflow_service.update_run_status(db, run_id, RunStatus.RUNNING)

            # --- Step A: Classification ---
            log.info("classification_started")
            try:
                classifier_result = await _classifier.run({
                    "raw_input": input.raw_input,
                    "input_type": input.input_type.value,
                })
                classification = classifier_result.parsed_output

                await workflow_service.record_llm_trace(
                    db=db,
                    run_id=run_id,
                    agent_name="classifier_agent",
                    prompt_summary=f"Classify: {input.raw_input[:100]}",
                    model_name=settings.llm_model,
                    tokens_in=classifier_result.tokens_in,
                    tokens_out=classifier_result.tokens_out,
                    latency_ms=classifier_result.latency_ms,
                )
                # Canonicalize route through the router — overrides any LLM hallucination
                canonical_route = router.get_route(
                    task_type=input.input_type,
                    classification_route=classification.get("route"),
                )
                canonical_tools = router.get_suggested_tools(canonical_route)
                classification["route"] = canonical_route
                classification["suggested_tools"] = canonical_tools

                await state_manager.update_context(run_id, {"classification": classification})
                log.info("classification_done", task_type=classification.get("task_type"), route=canonical_route)

            except ClassificationError as e:
                return await _fail_run(db, run_id, str(e), log)

            # --- Step B: Planning ---
            log.info("planning_started")
            try:
                planner_result = await _planner.run({
                    "classification": classification,
                    "raw_input": input.raw_input,
                })
                execution_plan = planner_result.parsed_output

                await workflow_service.record_llm_trace(
                    db=db,
                    run_id=run_id,
                    agent_name="planner_agent",
                    prompt_summary=f"Plan for route: {classification.get('route')}",
                    model_name=settings.llm_model,
                    tokens_in=planner_result.tokens_in,
                    tokens_out=planner_result.tokens_out,
                    latency_ms=planner_result.latency_ms,
                )
                await state_manager.update_context(run_id, {"execution_plan": execution_plan})

                # Persist step records
                steps = await planner.create_step_records(db, run_id, execution_plan)
                log.info("planning_done", total_steps=len(steps))

            except PlanningError as e:
                return await _fail_run(db, run_id, str(e), log)

            # --- Step C: Execution loop ---
            steps_completed = 0
            final_output_parts: list[str] = []

            for step in steps:
                run_context = await state_manager.get_context(run_id)
                log.info("executing_step", step_name=step.step_name, step_order=step.step_order)

                step_output = await executor.execute_step(
                    db=db,
                    step=step,
                    run_context=run_context,
                    raw_input=input.raw_input,
                )
                steps_completed += 1

                # Collect output for final summary
                summary = step_output.get("summary", "")
                if summary:
                    final_output_parts.append(f"[{step.step_name}] {summary}")

            # --- Finalization ---
            final_output = "\n\n".join(final_output_parts) if final_output_parts else "Workflow completed."

            await workflow_service.update_run_status(db, run_id, RunStatus.COMPLETED, final_output)
            await state_manager.set_status(run_id, RunStatus.COMPLETED)
            log.info("workflow_completed", steps_completed=steps_completed)

            return OrchestratorResult(
                run_id=run_id,
                status=RunStatus.COMPLETED,
                final_output=final_output,
                steps_completed=steps_completed,
                steps_total=len(steps),
            )

        except OrchestratorError as e:
            return await _fail_run(db, run_id, str(e), log)
        except Exception as e:
            log.error("unexpected_error", error=str(e), exc_info=True)
            return await _fail_run(db, run_id, f"Unexpected error: {e}", log)


async def _fail_run(db: AsyncSession, run_id: str, error: str, log: Any) -> OrchestratorResult:
    log.error("workflow_failed", error=error)
    try:
        await workflow_service.update_run_status(db, run_id, RunStatus.FAILED)
        await state_manager.set_status(run_id, RunStatus.FAILED)
    except Exception:
        pass
    return OrchestratorResult(run_id=run_id, status=RunStatus.FAILED, error=error)
