from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.classifier_agent import ClassifierAgent
from app.agents.planner_agent import PlannerAgent
from app.agents.replanner_agent import RePlannerAgent
from app.config import settings
from app.core import executor, planner, router, state_manager
from app.db.models import WorkflowStep
from app.db.session import AsyncSessionFactory
from app.services import workflow_service
from app.services.logging_service import get_logger
from app.services.telemetry_service import get_tracer
from app.utils.enums import InputType, RunStatus
from app.utils.exceptions import ClassificationError, OrchestratorError, PlanningError

logger = get_logger(__name__)
_tracer = get_tracer(__name__)

_classifier = ClassifierAgent()
_planner = PlannerAgent()
_replanner = RePlannerAgent()


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
    replan_count: int = 0
    error: str | None = None


async def run_workflow(input: OrchestratorInput) -> OrchestratorResult:
    """
    Top-level workflow coordinator. Owns the full run lifecycle:
    PENDING → RUNNING → (classify → plan → execute [→ replan]*) → COMPLETED | FAILED
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
                with _tracer.start_as_current_span(
                    "workflow.classify",
                    attributes={"run_id": run_id, "input_type": input.input_type.value},
                ):
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
                with _tracer.start_as_current_span(
                    "workflow.plan",
                    attributes={"run_id": run_id, "route": str(classification.get("route"))},
                ):
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

                initial_steps = await planner.create_step_records(db, run_id, execution_plan)
                log.info("planning_done", total_steps=len(initial_steps))

            except PlanningError as e:
                return await _fail_run(db, run_id, str(e), log)

            # --- Step C: Dynamic execution loop ---
            remaining_steps: list[WorkflowStep] = list(initial_steps)
            steps_completed = 0
            replan_count = 0
            # next_order starts after all initially planned steps
            next_order = len(initial_steps) + 1
            final_output_parts: list[str] = []

            while remaining_steps:
                step = remaining_steps.pop(0)
                run_context = await state_manager.get_context(run_id)
                log.info("executing_step", step_name=step.step_name, step_order=step.step_order)

                with _tracer.start_as_current_span(
                    "workflow.step",
                    attributes={
                        "run_id": run_id,
                        "step_name": step.step_name,
                        "step_order": str(step.step_order),
                    },
                ):
                    step_output = await executor.execute_step(
                        db=db,
                        step=step,
                        run_context=run_context,
                        raw_input=input.raw_input,
                    )
                steps_completed += 1

                summary = step_output.get("summary", "")
                if summary:
                    final_output_parts.append(f"[{step.step_name}] {summary}")

                # --- Re-planning hook ---
                if (
                    step_output.get("needs_replan")
                    and remaining_steps
                    and replan_count < settings.max_replan_depth
                ):
                    injected = await _maybe_replan(
                        db=db,
                        run_id=run_id,
                        step_output=step_output,
                        remaining_steps=remaining_steps,
                        run_context=run_context,
                        input=input,
                        next_order=next_order,
                        log=log,
                    )
                    if injected:
                        # Insert new steps before the remaining plan
                        remaining_steps = injected + remaining_steps
                        next_order += len(injected)
                        replan_count += 1
                        log.info("replan_applied", injected=len(injected), replan_count=replan_count)

            # --- Finalization ---
            final_output = "\n\n".join(final_output_parts) if final_output_parts else "Workflow completed."

            await workflow_service.update_run_status(db, run_id, RunStatus.COMPLETED, final_output)
            await state_manager.set_status(run_id, RunStatus.COMPLETED)
            log.info("workflow_completed", steps_completed=steps_completed, replan_count=replan_count)

            return OrchestratorResult(
                run_id=run_id,
                status=RunStatus.COMPLETED,
                final_output=final_output,
                steps_completed=steps_completed,
                steps_total=steps_completed,  # reflects actual steps run including dynamic ones
                replan_count=replan_count,
            )

        except OrchestratorError as e:
            return await _fail_run(db, run_id, str(e), log)
        except Exception as e:
            log.error("unexpected_error", error=str(e), exc_info=True)
            return await _fail_run(db, run_id, f"Unexpected error: {e}", log)


async def _maybe_replan(
    db: AsyncSession,
    run_id: str,
    step_output: dict[str, Any],
    remaining_steps: list[WorkflowStep],
    run_context: dict[str, Any],
    input: OrchestratorInput,
    next_order: int,
    log: Any,
) -> list[WorkflowStep]:
    """
    Calls the RePlannerAgent to decide if new steps should be injected.
    Returns the list of newly created WorkflowStep records (may be empty).
    """
    try:
        replan_result = await _replanner.run({
            "raw_input": input.raw_input,
            "classification": run_context.get("classification", {}),
            "trigger_step": {
                "step_name": step_output.get("step_name"),
                "summary": step_output.get("summary"),
                "key_findings": step_output.get("key_findings"),
                "severity": step_output.get("severity"),
                "next_action": step_output.get("next_action"),
            },
            "completed_steps": run_context.get("completed_steps", []),
            "remaining_steps": [
                {
                    "step_name": s.step_name,
                    "description": (s.input_data or {}).get("description", ""),
                }
                for s in remaining_steps
            ],
        })

        await workflow_service.record_llm_trace(
            db=db,
            run_id=run_id,
            agent_name="replanner_agent",
            prompt_summary=f"Replan after: {step_output.get('step_name')}",
            model_name=settings.llm_model,
            tokens_in=replan_result.tokens_in,
            tokens_out=replan_result.tokens_out,
            latency_ms=replan_result.latency_ms,
        )

        decision = replan_result.parsed_output
        if not decision.get("should_replan") or not decision.get("new_steps"):
            log.info("replan_declined", reason=decision.get("reason", ""))
            return []

        new_steps = await planner.create_replan_steps(
            db=db,
            run_id=run_id,
            new_steps=decision["new_steps"],
            step_order_offset=next_order,
        )
        return new_steps

    except Exception as e:
        # Re-planning failure is non-fatal — continue with the original remaining steps
        log.warning("replan_failed", error=str(e))
        return []


async def _fail_run(db: AsyncSession, run_id: str, error: str, log: Any) -> OrchestratorResult:
    log.error("workflow_failed", error=error)
    try:
        await workflow_service.update_run_status(db, run_id, RunStatus.FAILED)
        await state_manager.set_status(run_id, RunStatus.FAILED)
    except Exception:
        pass
    return OrchestratorResult(run_id=run_id, status=RunStatus.FAILED, error=error)
