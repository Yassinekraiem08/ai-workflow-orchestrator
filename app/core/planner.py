from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkflowStep
from app.services import workflow_service


async def create_step_records(
    db: AsyncSession,
    run_id: str,
    execution_plan: dict[str, Any],
) -> list[WorkflowStep]:
    """
    Converts a PlannerAgent's ExecutionPlan output into persisted WorkflowStep records.
    Returns the created steps in order.
    """
    steps_data = execution_plan.get("steps", [])
    created: list[WorkflowStep] = []

    for step_data in sorted(steps_data, key=lambda s: s["step_order"]):
        step = await workflow_service.create_step(
            db=db,
            run_id=run_id,
            step_name=step_data["step_name"],
            step_order=step_data["step_order"],
            input_data={
                "tool_name": step_data.get("tool_name"),
                "tool_arguments": step_data.get("tool_arguments"),
                "description": step_data.get("description"),
                "depends_on": step_data.get("depends_on", []),
            },
        )
        created.append(step)

    return created
