"""
RePlannerAgent unit tests and dynamic re-planning integration tests.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.replanner_agent import RePlannerAgent
from app.core.orchestrator import OrchestratorInput, run_workflow
from app.utils.enums import InputType, RunStatus


def _make_replan_response(should_replan: bool, new_steps: list | None = None):
    from app.services.llm_service import LLMResponse
    return LLMResponse(
        content="",
        stop_reason="tool_use",
        latency_ms=200,
        usage={"input_tokens": 80, "output_tokens": 40},
        tool_calls=[{
            "name": "adjust_execution_plan",
            "input": {
                "should_replan": should_replan,
                "reason": "critical DB error found" if should_replan else "remaining plan is sufficient",
                "new_steps": new_steps or [],
            },
            "id": "t_replan",
        }],
    )


@pytest.mark.asyncio
class TestRePlannerAgent:
    async def test_returns_no_replan_when_plan_is_sufficient(self):
        agent = RePlannerAgent()

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=_make_replan_response(should_replan=False),
        ):
            result = await agent.run({
                "raw_input": "ERROR: payment timeout",
                "classification": {"task_type": "log", "route": "log_triage"},
                "trigger_step": {
                    "step_name": "analyze_logs",
                    "summary": "Found 3 errors",
                    "key_findings": ["DB timeout at 03:14"],
                    "severity": "high",
                    "next_action": "Investigate DB",
                },
                "completed_steps": [],
                "remaining_steps": [{"step_name": "synthesize", "description": "Summarize findings"}],
            })

        assert result.agent_name == "replanner_agent"
        assert result.parsed_output["should_replan"] is False
        assert result.parsed_output["new_steps"] == []

    async def test_returns_new_steps_when_replan_needed(self):
        agent = RePlannerAgent()
        new_steps = [
            {
                "step_name": "query_db_health",
                "tool_name": "database_query",
                "tool_arguments": {"query_type": "recent_errors", "table": "transactions"},
                "description": "Check DB for recent transaction failures",
            }
        ]

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=_make_replan_response(should_replan=True, new_steps=new_steps),
        ):
            result = await agent.run({
                "raw_input": "ERROR: DB connection pool exhausted",
                "classification": {"task_type": "log", "route": "log_triage"},
                "trigger_step": {
                    "step_name": "analyze_logs",
                    "summary": "Connection pool exhausted — root cause unclear",
                    "key_findings": ["Max connections reached", "Queue depth 450"],
                    "severity": "critical",
                    "next_action": "Query DB for active connections",
                },
                "completed_steps": [],
                "remaining_steps": [{"step_name": "synthesize", "description": "Summarize"}],
            })

        assert result.parsed_output["should_replan"] is True
        assert len(result.parsed_output["new_steps"]) == 1
        assert result.parsed_output["new_steps"][0]["tool_name"] == "database_query"


@pytest.mark.asyncio
async def test_orchestrator_triggers_replan_on_needs_replan():
    """
    When a step output has needs_replan=True, the orchestrator calls the
    RePlannerAgent and injects new steps into the execution queue.
    """
    from tests.test_orchestrator import (
        make_classifier_response,
        make_executor_response,
        make_planner_response,
    )

    mock_db = AsyncMock()
    mock_run = MagicMock()
    mock_run.id = "run_replan_001"
    mock_run.status = "running"

    mock_step_1 = MagicMock()
    mock_step_1.id = "step_001"
    mock_step_1.run_id = "run_replan_001"
    mock_step_1.step_name = "analyze_logs"
    mock_step_1.step_order = 1
    mock_step_1.input_data = {
        "tool_name": "log_analysis",
        "tool_arguments": {"log_content": "ERROR: DB timeout"},
        "description": "Analyze logs",
        "depends_on": [],
    }

    mock_step_2 = MagicMock()
    mock_step_2.id = "step_002"
    mock_step_2.run_id = "run_replan_001"
    mock_step_2.step_name = "summarize"
    mock_step_2.step_order = 2
    mock_step_2.input_data = {
        "tool_name": None,
        "tool_arguments": None,
        "description": "Summarize",
        "depends_on": [1],
    }

    # The injected step from re-planning
    mock_step_injected = MagicMock()
    mock_step_injected.id = "step_003"
    mock_step_injected.run_id = "run_replan_001"
    mock_step_injected.step_name = "query_db_health"
    mock_step_injected.step_order = 3
    mock_step_injected.input_data = {
        "tool_name": "database_query",
        "tool_arguments": {"query_type": "recent_errors"},
        "description": "Check DB health",
        "depends_on": [],
        "dynamic": True,
    }

    llm_call_count = 0

    async def mock_llm(request):
        nonlocal llm_call_count
        llm_call_count += 1
        if llm_call_count == 1:
            return make_classifier_response()
        elif llm_call_count == 2:
            return make_planner_response()
        elif llm_call_count == 3:
            # Executor for step 1 — sets needs_replan=True
            from app.services.llm_service import LLMResponse
            return LLMResponse(
                content="", stop_reason="tool_use", latency_ms=300,
                usage={"input_tokens": 150, "output_tokens": 80},
                tool_calls=[{
                    "name": "record_step_result",
                    "input": {
                        "step_name": "analyze_logs",
                        "summary": "DB connection pool exhausted — needs deeper investigation",
                        "key_findings": ["Max connections reached"],
                        "next_action": "Query DB for active connections",
                        "severity": "critical",
                        "needs_replan": True,
                    },
                    "id": "t_exec1",
                }],
            )
        elif llm_call_count == 4:
            # RePlannerAgent — injects one new step
            return _make_replan_response(
                should_replan=True,
                new_steps=[{
                    "step_name": "query_db_health",
                    "tool_name": "database_query",
                    "tool_arguments": {"query_type": "recent_errors"},
                    "description": "Check DB health",
                }],
            )
        else:
            # Executor for injected + remaining steps
            step_name = f"step_{llm_call_count}"
            return make_executor_response(step_name)

    with (
        patch("app.core.orchestrator._db_session.AsyncSessionFactory") as mock_sf,
        patch("app.agents.base_agent.llm_service.complete_with_tools",
              new_callable=AsyncMock, side_effect=mock_llm),
        patch("app.core.orchestrator.workflow_service.update_run_status", new_callable=AsyncMock),
        patch("app.core.orchestrator.workflow_service.get_run",
              new_callable=AsyncMock, return_value=mock_run),
        patch("app.core.orchestrator.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.planner.workflow_service.create_step", new_callable=AsyncMock,
              side_effect=[mock_step_1, mock_step_2, mock_step_injected]),
        patch("app.core.executor.workflow_service.start_step", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.complete_step", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.record_tool_call", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.executor._execute_tool_with_retries", new_callable=AsyncMock,
              return_value={"tool_name": "log_analysis", "success": True, "output": {}, "latency_ms": 50}),
        patch("app.core.state_manager.set_status", new_callable=AsyncMock),
        patch("app.core.state_manager.update_context", new_callable=AsyncMock),
        patch("app.core.state_manager.get_context", new_callable=AsyncMock, return_value={}),
        patch("app.core.state_manager.append_completed_step", new_callable=AsyncMock),
    ):
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_db_cm

        result = await run_workflow(OrchestratorInput(
            run_id="run_replan_001",
            input_type=InputType.LOG,
            raw_input="ERROR: DB connection pool exhausted",
        ))

    assert result.status == RunStatus.COMPLETED
    assert result.replan_count == 1
    assert result.steps_completed == 3  # original 2 + 1 injected


@pytest.mark.asyncio
async def test_orchestrator_no_replan_when_needs_replan_false():
    """When needs_replan is False, the RePlannerAgent is never called."""
    from tests.test_orchestrator import (
        make_classifier_response,
        make_executor_response,
        make_planner_response,
    )

    mock_db = AsyncMock()
    mock_run = MagicMock()
    mock_run.id = "run_no_replan"

    mock_step_1 = MagicMock()
    mock_step_1.id = "step_001"
    mock_step_1.run_id = "run_no_replan"
    mock_step_1.step_name = "analyze_logs"
    mock_step_1.step_order = 1
    mock_step_1.input_data = {
        "tool_name": "log_analysis",
        "tool_arguments": {"log_content": "WARN: slow query"},
        "description": "Analyze logs",
        "depends_on": [],
    }
    mock_step_2 = MagicMock()
    mock_step_2.id = "step_002"
    mock_step_2.run_id = "run_no_replan"
    mock_step_2.step_name = "summarize"
    mock_step_2.step_order = 2
    mock_step_2.input_data = {"tool_name": None, "tool_arguments": None, "description": "Summarize", "depends_on": []}

    llm_call_count = 0

    async def mock_llm(request):
        nonlocal llm_call_count
        llm_call_count += 1
        if llm_call_count == 1:
            return make_classifier_response()
        elif llm_call_count == 2:
            return make_planner_response()
        else:
            return make_executor_response(f"step_{llm_call_count}")

    replanner_mock = AsyncMock()

    with (
        patch("app.core.orchestrator._db_session.AsyncSessionFactory") as mock_sf,
        patch("app.agents.base_agent.llm_service.complete_with_tools",
              new_callable=AsyncMock, side_effect=mock_llm),
        patch("app.core.orchestrator._replanner.run", replanner_mock),
        patch("app.core.orchestrator.workflow_service.update_run_status", new_callable=AsyncMock),
        patch("app.core.orchestrator.workflow_service.get_run",
              new_callable=AsyncMock, return_value=mock_run),
        patch("app.core.orchestrator.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.planner.workflow_service.create_step", new_callable=AsyncMock,
              side_effect=[mock_step_1, mock_step_2]),
        patch("app.core.executor.workflow_service.start_step", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.complete_step", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.record_tool_call", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.executor._execute_tool_with_retries", new_callable=AsyncMock,
              return_value={"tool_name": "log_analysis", "success": True, "output": {}, "latency_ms": 50}),
        patch("app.core.state_manager.set_status", new_callable=AsyncMock),
        patch("app.core.state_manager.update_context", new_callable=AsyncMock),
        patch("app.core.state_manager.get_context", new_callable=AsyncMock, return_value={}),
        patch("app.core.state_manager.append_completed_step", new_callable=AsyncMock),
    ):
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_db_cm

        result = await run_workflow(OrchestratorInput(
            run_id="run_no_replan",
            input_type=InputType.LOG,
            raw_input="WARN: slow query detected",
        ))

    assert result.status == RunStatus.COMPLETED
    assert result.replan_count == 0
    replanner_mock.assert_not_called()
