from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_auth
from app.db.schemas import WorkflowRunResponse, WorkflowSubmitRequest
from app.db.session import get_db
from app.services import workflow_service
from app.utils.enums import RunStatus
from app.utils.exceptions import WorkflowNotFoundError
from app.utils.helpers import generate_run_id
from app.workers.tasks import execute_workflow_task

router = APIRouter(prefix="/workflows", tags=["workflows"], dependencies=[Depends(require_auth)])


@router.post("/submit", response_model=WorkflowRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_workflow(
    request: WorkflowSubmitRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    run_id = generate_run_id()

    run = await workflow_service.create_run(
        db=db,
        run_id=run_id,
        input_type=request.input_type.value,
        raw_input=request.raw_input,
        priority=request.priority,
    )

    # Enqueue to Celery — status transitions to QUEUED after this
    # Celery priority is 0 (highest) → 9 (lowest); API priority is 1 (highest) → 9 (lowest)
    celery_priority = 10 - request.priority
    execute_workflow_task.apply_async(
        kwargs={
            "run_id": run_id,
            "input_type": request.input_type.value,
            "raw_input": request.raw_input,
            "priority": request.priority,
        },
        priority=celery_priority,
    )

    await workflow_service.update_run_status(db, run_id, RunStatus.QUEUED)
    await db.refresh(run)

    return WorkflowRunResponse.from_orm_run(run)


@router.post("/{run_id}/retry", response_model=WorkflowRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_workflow(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    try:
        run = await workflow_service.get_run(db, run_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found") from None

    if run.status not in (RunStatus.FAILED.value, RunStatus.DEAD_LETTER.value):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry workflow in status '{run.status}'. Only failed or dead_letter runs can be retried.",
        )

    await workflow_service.reset_run_for_retry(db, run_id)
    celery_priority = 10 - run.priority
    execute_workflow_task.apply_async(
        kwargs={
            "run_id": run_id,
            "input_type": run.input_type,
            "raw_input": run.raw_input,
            "priority": run.priority,
        },
        priority=celery_priority,
    )
    await workflow_service.update_run_status(db, run_id, RunStatus.QUEUED)
    await db.refresh(run)

    return WorkflowRunResponse.from_orm_run(run)
