import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_auth
from app.core import state_manager
from app.db.schemas import WorkflowRunResponse, WorkflowStepResponse, WorkflowStepsResponse
from app.db.session import get_db
from app.services import workflow_service
from app.utils.enums import RunStatus
from app.utils.exceptions import WorkflowNotFoundError

router = APIRouter(prefix="/workflows", tags=["runs"], dependencies=[Depends(require_auth)])

_TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.DEAD_LETTER, RunStatus.NEEDS_REVIEW}


@router.get("/review-queue", response_model=list[WorkflowRunResponse])
async def get_review_queue(
    db: AsyncSession = Depends(get_db),
) -> list[WorkflowRunResponse]:
    """
    Returns all workflow runs awaiting human review (needs_review status),
    ordered by priority then submission time.
    """
    runs = await workflow_service.get_review_queue(db)
    return [WorkflowRunResponse.from_orm_run(r) for r in runs]


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


@router.get("/{run_id}/stream")
async def stream_workflow(run_id: str) -> StreamingResponse:
    """
    Server-Sent Events stream for live workflow progress.

    Events emitted:
      - connected      — immediately on connect, confirms the run exists in Redis
      - step_completed — each time a new step finishes (includes step summary)
      - status_changed — when run status transitions (running → completed, etc.)
      - done           — terminal event; stream closes after this

    Usage:
      curl -N -H "Authorization: Bearer <token>" \\
           http://localhost:8000/workflows/{run_id}/stream
    """
    async def event_generator():
        yield _sse("connected", {"run_id": run_id})

        last_step_count = 0
        last_status: RunStatus | None = None
        timeout_seconds = 300  # 5-minute max stream
        elapsed = 0

        while elapsed < timeout_seconds:
            await asyncio.sleep(1)
            elapsed += 1

            status = await state_manager.get_status(run_id)
            context = await state_manager.get_context(run_id)

            # Push any newly completed steps
            completed_steps = context.get("completed_steps", [])
            if len(completed_steps) > last_step_count:
                for step in completed_steps[last_step_count:]:
                    yield _sse("step_completed", step)
                last_step_count = len(completed_steps)

            # Push status change
            if status and status != last_status:
                yield _sse("status_changed", {"status": status.value})
                last_status = status

                if status in _TERMINAL:
                    yield _sse("done", {"status": status.value})
                    return

        # Timed out
        yield _sse("done", {"status": "timeout", "message": "Stream exceeded 5-minute limit"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
