import asyncio

from celery import Task

from app.config import settings
from app.core.orchestrator import OrchestratorInput, run_workflow
from app.services.logging_service import get_logger
from app.utils.enums import InputType, RunStatus
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.execute_workflow_task",
    max_retries=settings.max_celery_retries,
    default_retry_delay=settings.celery_retry_delay_seconds,
    queue="workflows",
)
def execute_workflow_task(self: Task, run_id: str, input_type: str, raw_input: str, priority: int = 5) -> dict:
    """
    Celery task that drives a full workflow run.
    Uses asyncio.run() to bridge sync Celery and async orchestrator.
    """
    log = logger.bind(run_id=run_id, task_id=self.request.id)
    log.info("celery_task_started", attempt=self.request.retries + 1)

    try:
        orchestrator_input = OrchestratorInput(
            run_id=run_id,
            input_type=InputType(input_type),
            raw_input=raw_input,
            priority=priority,
        )
        result = asyncio.run(run_workflow(orchestrator_input))
        log.info("celery_task_completed", status=result.status)
        return result.model_dump()

    except Exception as exc:
        log.error("celery_task_failed", error=str(exc), exc_info=True)

        if self.request.retries < self.max_retries:
            log.info("celery_task_retrying", retry=self.request.retries + 1)
            raise self.retry(exc=exc) from exc

        # All retries exhausted → send to dead-letter queue
        dead_letter_task.delay(run_id, str(exc))
        return {"run_id": run_id, "status": RunStatus.DEAD_LETTER, "error": str(exc)}


@celery_app.task(
    name="app.workers.tasks.dead_letter_task",
    queue="dead_letter",
)
def dead_letter_task(run_id: str, reason: str) -> None:
    """
    Handles workflows that have exhausted all retries.
    Updates the run status to dead_letter and logs for operator review.
    """
    log = logger.bind(run_id=run_id)
    log.error("workflow_dead_lettered", reason=reason)

    async def _mark_dead_letter() -> None:
        from app.core import state_manager
        from app.db.session import AsyncSessionFactory
        from app.services import workflow_service

        async with AsyncSessionFactory() as db:
            await workflow_service.update_run_status(db, run_id, RunStatus.DEAD_LETTER)
            await state_manager.set_status(run_id, RunStatus.DEAD_LETTER)

    asyncio.run(_mark_dead_letter())
