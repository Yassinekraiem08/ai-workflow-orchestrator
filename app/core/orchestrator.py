from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as _db_session
from app.agents.classifier_agent import ClassifierAgent
from app.agents.planner_agent import PlannerAgent
from app.agents.replanner_agent import RePlannerAgent
from app.config import settings
from app.core import executor, planner, router, state_manager
from app.db.models import WorkflowStep
from app.services import workflow_service
from app.services.cache_service import check_cache
from app.services.cache_service import store as cache_store
from app.services.judge_service import evaluate_output
from app.services.llm_service import estimate_cost
from app.services.logging_service import get_logger
from app.services.prometheus_service import WORKFLOW_COMPLETIONS, WORKFLOW_DURATION
from app.services.safety_service import check_safety
from app.services.telemetry_service import get_tracer
from app.utils.enums import InputType, RunStatus
from app.utils.exceptions import ClassificationError, OrchestratorError, PlanningError
from app.utils.helpers import ms_since
from app.utils.helpers import utcnow as _utcnow

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
    skip_confidence_check: bool = False  # set True when human has approved a needs_review run


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
    _start_time = _utcnow()

    async with _db_session.AsyncSessionFactory() as db:
        try:
            await state_manager.set_status(run_id, RunStatus.RUNNING)
            await workflow_service.update_run_status(db, run_id, RunStatus.RUNNING)

            # --- Safety gate (runs before any LLM processing) ---
            if settings.enable_safety_check:
                safety_result = await check_safety(input.raw_input)
                if not safety_result.safe:
                    output = (
                        f"Input blocked by safety filter.\n"
                        f"Category: {safety_result.category}\n"
                        f"Reason: {safety_result.reason}"
                    )
                    await workflow_service.update_run_safety(db, run_id, True, safety_result.reason)
                    await workflow_service.update_run_status(db, run_id, RunStatus.SAFETY_BLOCKED, output)
                    await state_manager.set_status(run_id, RunStatus.SAFETY_BLOCKED)
                    log.warning("workflow_safety_blocked", category=safety_result.category)
                    return OrchestratorResult(
                        run_id=run_id,
                        status=RunStatus.SAFETY_BLOCKED,
                        final_output=output,
                    )

            # --- Semantic cache check ---
            if settings.enable_semantic_cache and not input.skip_confidence_check:
                cache_hit = await check_cache(input.raw_input)
                if cache_hit:
                    cached_output = (
                        f"{cache_hit.final_output}\n\n"
                        f"[Served from semantic cache — similarity {cache_hit.similarity:.1%} "
                        f"with run {cache_hit.run_id}]"
                    )
                    await workflow_service.update_run_cache_hit(db, run_id, True)
                    await workflow_service.update_run_status(db, run_id, RunStatus.COMPLETED, cached_output)
                    await state_manager.set_status(run_id, RunStatus.COMPLETED)
                    WORKFLOW_COMPLETIONS.labels(input_type=input.input_type.value, status="completed").inc()
                    log.info("workflow_cache_hit", source_run_id=cache_hit.run_id, similarity=cache_hit.similarity)
                    return OrchestratorResult(
                        run_id=run_id,
                        status=RunStatus.COMPLETED,
                        final_output=cached_output,
                    )

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
                    model_name=classifier_result.model_name,
                    tokens_in=classifier_result.tokens_in,
                    tokens_out=classifier_result.tokens_out,
                    latency_ms=classifier_result.latency_ms,
                    estimated_cost_usd=estimate_cost(
                        classifier_result.model_name,
                        classifier_result.tokens_in,
                        classifier_result.tokens_out,
                    ),
                )

                # Confidence gate: low-confidence classifications go to human review
                confidence = classification.get("confidence", 1.0)
                if confidence < settings.confidence_threshold and not input.skip_confidence_check:
                    await workflow_service.update_run_status(db, run_id, RunStatus.NEEDS_REVIEW)
                    await state_manager.set_status(run_id, RunStatus.NEEDS_REVIEW)
                    log.info("workflow_needs_review", confidence=confidence, threshold=settings.confidence_threshold)
                    return OrchestratorResult(
                        run_id=run_id,
                        status=RunStatus.NEEDS_REVIEW,
                        final_output=f"Low classification confidence ({confidence:.0%}). Awaiting human review.",
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
                return await _fail_run(db, run_id, str(e), log, input.input_type.value)

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
                    model_name=planner_result.model_name,
                    tokens_in=planner_result.tokens_in,
                    tokens_out=planner_result.tokens_out,
                    latency_ms=planner_result.latency_ms,
                    estimated_cost_usd=estimate_cost(
                        planner_result.model_name,
                        planner_result.tokens_in,
                        planner_result.tokens_out,
                    ),
                )
                await state_manager.update_context(run_id, {"execution_plan": execution_plan})

                initial_steps = await planner.create_step_records(db, run_id, execution_plan)
                log.info("planning_done", total_steps=len(initial_steps))

            except PlanningError as e:
                return await _fail_run(db, run_id, str(e), log, input.input_type.value)

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
            duration_s = ms_since(_start_time) / 1000
            WORKFLOW_COMPLETIONS.labels(input_type=input.input_type.value, status="completed").inc()
            WORKFLOW_DURATION.labels(input_type=input.input_type.value).observe(duration_s)

            # --- LLM-as-judge quality evaluation ---
            quality_score: float | None = None
            if settings.enable_judge:
                judge_result = await evaluate_output(
                    input_type=input.input_type.value,
                    raw_input=input.raw_input,
                    final_output=final_output,
                )
                if judge_result:
                    quality_score = judge_result.overall_score
                    await workflow_service.update_run_quality(
                        db, run_id, judge_result.overall_score, judge_result.dimensions
                    )
                    log.info("judge_score", overall=judge_result.overall_score)

            # --- Store in semantic cache for future deduplication ---
            await cache_store(
                run_id=run_id,
                raw_input=input.raw_input,
                final_output=final_output,
                quality_score=quality_score,
            )

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
            return await _fail_run(db, run_id, str(e), log, input.input_type.value)
        except Exception as e:
            log.error("unexpected_error", error=str(e), exc_info=True)
            return await _fail_run(db, run_id, f"Unexpected error: {e}", log, input.input_type.value)


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
            model_name=replan_result.model_name,
            tokens_in=replan_result.tokens_in,
            tokens_out=replan_result.tokens_out,
            latency_ms=replan_result.latency_ms,
            estimated_cost_usd=estimate_cost(
                replan_result.model_name,
                replan_result.tokens_in,
                replan_result.tokens_out,
            ),
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


async def _fail_run(db: AsyncSession, run_id: str, error: str, log: Any, input_type: str = "unknown") -> OrchestratorResult:
    log.error("workflow_failed", error=error)
    try:
        await workflow_service.update_run_status(db, run_id, RunStatus.FAILED)
        await state_manager.set_status(run_id, RunStatus.FAILED)
        WORKFLOW_COMPLETIONS.labels(input_type=input_type, status="failed").inc()
    except Exception:
        pass
    return OrchestratorResult(run_id=run_id, status=RunStatus.FAILED, error=error)
