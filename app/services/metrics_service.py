"""
Phase 3: Metrics aggregation service.
Queries workflow_runs, tool_calls, and llm_traces to produce system-wide metrics.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMTrace, ToolCall, WorkflowRun
from app.utils.enums import RunStatus


async def get_metrics(db: AsyncSession) -> dict[str, Any]:
    # Total runs by status
    status_counts_result = await db.execute(
        select(WorkflowRun.status, func.count(WorkflowRun.id).label("count"))
        .group_by(WorkflowRun.status)
    )
    status_counts = {row.status: row.count for row in status_counts_result}

    total_runs = sum(status_counts.values())
    completed = status_counts.get(RunStatus.COMPLETED.value, 0)
    failed = status_counts.get(RunStatus.FAILED.value, 0)
    dead_letter = status_counts.get(RunStatus.DEAD_LETTER.value, 0)

    success_rate = (completed / total_runs) if total_runs > 0 else 0.0

    # Token usage and cost
    token_result = await db.execute(
        select(
            func.sum(LLMTrace.tokens_in).label("total_in"),
            func.sum(LLMTrace.tokens_out).label("total_out"),
            func.avg(LLMTrace.latency_ms).label("avg_latency"),
            func.sum(LLMTrace.estimated_cost_usd).label("total_cost"),
        )
    )
    token_row = token_result.one()

    # Tool failure breakdown
    tool_failures_result = await db.execute(
        select(ToolCall.tool_name, func.count(ToolCall.id).label("count"))
        .where(ToolCall.success == False)  # noqa: E712
        .group_by(ToolCall.tool_name)
    )
    tool_failures = {row.tool_name: row.count for row in tool_failures_result}

    return {
        "total_runs": total_runs,
        "completed_runs": completed,
        "failed_runs": failed + dead_letter,
        "success_rate": round(success_rate, 4),
        "avg_latency_ms": round(float(token_row.avg_latency or 0), 2),
        "total_tokens_in": int(token_row.total_in or 0),
        "total_tokens_out": int(token_row.total_out or 0),
        "total_cost_usd": round(float(token_row.total_cost or 0.0), 6),
        "failure_breakdown": {
            "by_status": status_counts,
            "by_tool": tool_failures,
        },
    }
