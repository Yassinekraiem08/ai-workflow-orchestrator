"""
Orchestrator integration tests with fully mocked LLM and DB.
Tests the full classify → plan → execute lifecycle.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.orchestrator import OrchestratorInput, run_workflow
from app.utils.enums import InputType, RunStatus


def make_classifier_response():
    from app.services.llm_service import LLMResponse
    return LLMResponse(
        content="",
        tool_calls=[{
            "name": "classify_workflow",
            "input": {
                "task_type": "log",
                "confidence": 0.92,
                "route": "log_triage",
                "reasoning": "Log input with errors",
                "suggested_tools": ["log_analysis"],
            },
            "id": "t1",
        }],
        stop_reason="tool_use",
        usage={"input_tokens": 100, "output_tokens": 50},
        latency_ms=300,
    )


def make_planner_response():
    from app.services.llm_service import LLMResponse
    return LLMResponse(
        content="",
        tool_calls=[{
            "name": "create_execution_plan",
            "input": {
                "steps": [
                    {
                        "step_order": 1,
                        "step_name": "analyze_logs",
                        "tool_name": "log_analysis",
                        "tool_arguments": {"log_content": "ERROR: timeout"},
                        "description": "Analyze logs",
                        "depends_on": [],
                    },
                    {
                        "step_order": 2,
                        "step_name": "summarize",
                        "tool_name": None,
                        "tool_arguments": None,
                        "description": "Summarize findings",
                        "depends_on": [1],
                    },
                ],
                "context_notes": "",
            },
            "id": "t2",
        }],
        stop_reason="tool_use",
        usage={"input_tokens": 200, "output_tokens": 100},
        latency_ms=500,
    )


def make_executor_response(step_name: str):
    from app.services.llm_service import LLMResponse
    return LLMResponse(
        content="",
        tool_calls=[{
            "name": "record_step_result",
            "input": {
                "step_name": step_name,
                "summary": f"Step {step_name} completed successfully.",
                "key_findings": ["DB timeout detected"],
                "next_action": "Escalate to on-call",
                "severity": "high",
                "raw_tool_output": None,
            },
            "id": "t3",
        }],
        stop_reason="tool_use",
        usage={"input_tokens": 150, "output_tokens": 80},
        latency_ms=400,
    )


@pytest.mark.asyncio
async def test_full_workflow_run():
    """
    End-to-end orchestrator test with all LLM calls mocked.
    Verifies the full classify → plan → execute lifecycle transitions correctly.
    """

    # Mock the DB session + all service calls
    mock_db = AsyncMock()
    mock_run = MagicMock()
    mock_run.id = "run_test001"
    mock_run.status = "running"

    # Mock step objects
    mock_step_1 = MagicMock()
    mock_step_1.id = "step_001"
    mock_step_1.run_id = "run_test001"
    mock_step_1.step_name = "analyze_logs"
    mock_step_1.step_order = 1
    mock_step_1.input_data = {
        "tool_name": "log_analysis",
        "tool_arguments": {"log_content": "ERROR: timeout"},
        "description": "Analyze logs",
        "depends_on": [],
    }

    mock_step_2 = MagicMock()
    mock_step_2.id = "step_002"
    mock_step_2.run_id = "run_test001"
    mock_step_2.step_name = "summarize"
    mock_step_2.step_order = 2
    mock_step_2.input_data = {
        "tool_name": None,
        "tool_arguments": None,
        "description": "Summarize findings",
        "depends_on": [1],
    }

    llm_call_count = 0

    async def mock_llm_side_effect(request):
        nonlocal llm_call_count
        llm_call_count += 1
        if llm_call_count == 1:
            return make_classifier_response()
        elif llm_call_count == 2:
            return make_planner_response()
        else:
            # Executor calls
            step_name = f"step_{llm_call_count}"
            return make_executor_response(step_name)

    mock_tool_result = {
        "tool_name": "log_analysis", "success": True,
        "output": {"error_count": 2, "severity": "high"}, "error": None, "latency_ms": 50
    }

    with (
        patch("app.core.orchestrator._db_session.AsyncSessionFactory") as mock_session_factory,
        patch("app.agents.base_agent.llm_service.complete_with_tools", new_callable=AsyncMock,
              side_effect=mock_llm_side_effect),
        patch("app.core.orchestrator.workflow_service.update_run_status", new_callable=AsyncMock),
        patch("app.core.orchestrator.workflow_service.get_run", new_callable=AsyncMock, return_value=mock_run),
        patch("app.core.orchestrator.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.planner.workflow_service.create_step", new_callable=AsyncMock,
              side_effect=[mock_step_1, mock_step_2]),
        patch("app.core.executor.workflow_service.start_step", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.complete_step", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.record_tool_call", new_callable=AsyncMock),
        patch("app.core.executor.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.executor._execute_tool_with_retries", new_callable=AsyncMock,
              return_value=mock_tool_result),
        patch("app.core.state_manager.set_status", new_callable=AsyncMock),
        patch("app.core.state_manager.update_context", new_callable=AsyncMock),
        patch("app.core.state_manager.get_context", new_callable=AsyncMock, return_value={}),
        patch("app.core.state_manager.append_completed_step", new_callable=AsyncMock),
    ):
        # Mock the async context manager
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_db_cm

        result = await run_workflow(OrchestratorInput(
            run_id="run_test001",
            input_type=InputType.LOG,
            raw_input="ERROR: DB connection timeout at 03:14 UTC",
        ))

    assert result.run_id == "run_test001"
    assert result.status == RunStatus.COMPLETED
    assert result.steps_completed == 2
    assert result.error is None


@pytest.mark.asyncio
async def test_workflow_fails_on_classification_error():
    """If ClassifierAgent raises ClassificationError, the run transitions to FAILED."""
    from app.utils.exceptions import ClassificationError

    mock_db = AsyncMock()
    mock_run = MagicMock()
    mock_run.id = "run_chaos1"

    with (
        patch("app.core.orchestrator._db_session.AsyncSessionFactory") as mock_sf,
        patch("app.core.orchestrator._classifier.run",
              new_callable=AsyncMock,
              side_effect=ClassificationError("LLM returned invalid task_type")),
        patch("app.core.orchestrator.workflow_service.update_run_status", new_callable=AsyncMock),
        patch("app.core.orchestrator.workflow_service.get_run",
              new_callable=AsyncMock, return_value=mock_run),
        patch("app.core.orchestrator.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.state_manager.set_status", new_callable=AsyncMock),
        patch("app.core.state_manager.update_context", new_callable=AsyncMock),
        patch("app.core.state_manager.get_context", new_callable=AsyncMock, return_value={}),
    ):
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_db_cm

        result = await run_workflow(OrchestratorInput(
            run_id="run_chaos1",
            input_type=InputType.LOG,
            raw_input="ERROR: DB connection timeout",
        ))

    assert result.status == RunStatus.FAILED
    assert result.error is not None
    assert "LLM returned invalid task_type" in result.error


@pytest.mark.asyncio
async def test_workflow_fails_on_planning_error():
    """If PlannerAgent raises PlanningError, the run transitions to FAILED."""
    from app.utils.exceptions import PlanningError

    mock_db = AsyncMock()
    mock_run = MagicMock()
    mock_run.id = "run_chaos2"

    with (
        patch("app.core.orchestrator._db_session.AsyncSessionFactory") as mock_sf,
        patch("app.core.orchestrator._classifier.run",
              new_callable=AsyncMock,
              return_value=MagicMock(
                  parsed_output={
                      "task_type": "log",
                      "confidence": 0.9,
                      "route": "log_triage",
                      "reasoning": "ok",
                      "suggested_tools": ["log_analysis"],
                  },
                  tokens_in=100, tokens_out=50, latency_ms=200,
              )),
        patch("app.core.orchestrator._planner.run",
              new_callable=AsyncMock,
              side_effect=PlanningError("Could not generate execution plan")),
        patch("app.core.orchestrator.workflow_service.update_run_status", new_callable=AsyncMock),
        patch("app.core.orchestrator.workflow_service.get_run",
              new_callable=AsyncMock, return_value=mock_run),
        patch("app.core.orchestrator.workflow_service.record_llm_trace", new_callable=AsyncMock),
        patch("app.core.state_manager.set_status", new_callable=AsyncMock),
        patch("app.core.state_manager.update_context", new_callable=AsyncMock),
        patch("app.core.state_manager.get_context", new_callable=AsyncMock, return_value={}),
    ):
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_db_cm

        result = await run_workflow(OrchestratorInput(
            run_id="run_chaos2",
            input_type=InputType.LOG,
            raw_input="ERROR: DB connection timeout",
        ))

    assert result.status == RunStatus.FAILED
    assert result.error is not None
    assert "Could not generate execution plan" in result.error
