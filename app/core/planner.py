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


async def create_replan_steps(
    db: AsyncSession,
    run_id: str,
    new_steps: list[dict[str, Any]],
    step_order_offset: int,
) -> list[WorkflowStep]:
    """
    Persists dynamically injected steps from the RePlannerAgent.
    step_order_offset ensures new steps don't collide with the original plan's orders.
    """
    created: list[WorkflowStep] = []

    for i, step_data in enumerate(new_steps):
        step = await workflow_service.create_step(
            db=db,
            run_id=run_id,
            step_name=step_data.get("step_name", f"replan_step_{i + 1}"),
            step_order=step_order_offset + i,
            input_data={
                "tool_name": step_data.get("tool_name"),
                "tool_arguments": step_data.get("tool_arguments"),
                "description": step_data.get("description", ""),
                "depends_on": [],
                "dynamic": True,  # marks this as a re-planned step
            },
        )
        created.append(step)

    return created
