from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import state_manager
from app.db.schemas import WorkflowRunResponse, WorkflowStepResponse, WorkflowStepsResponse
from app.db.session import get_db
from app.services import workflow_service
from app.utils.exceptions import WorkflowNotFoundError

router = APIRouter(prefix="/workflows", tags=["runs"])


@router.get("/{run_id}", response_model=WorkflowRunResponse)
async def get_workflow(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    try:
        run = await workflow_service.get_run(db, run_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found") from None

    # Check Redis for a fresher status (worker may have updated it)
    live_status = await state_manager.get_status(run_id)
    if live_status and live_status.value != run.status:
        # Sync the DB record if Redis has a newer status
        await workflow_service.update_run_status(db, run_id, live_status)
        await db.refresh(run)

    return WorkflowRunResponse.from_orm_run(run)


@router.get("/{run_id}/steps", response_model=WorkflowStepsResponse)
async def get_workflow_steps(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowStepsResponse:
    try:
        await workflow_service.get_run(db, run_id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found") from None

    steps = await workflow_service.get_steps(db, run_id)
    return WorkflowStepsResponse(
        run_id=run_id,
        steps=[WorkflowStepResponse.from_orm_step(s) for s in steps],
    )
