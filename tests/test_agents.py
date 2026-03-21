"""
Agent unit tests with mocked LLM service.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.classifier_agent import ClassifierAgent
from app.agents.planner_agent import PlannerAgent
from app.utils.exceptions import ClassificationError, LLMResponseError


def make_mock_llm_response(tool_input: dict) -> object:
    from app.services.llm_service import LLMResponse
    return LLMResponse(
        content="",
        tool_calls=[{"name": "classify_workflow", "input": tool_input, "id": "tool_123"}],
        stop_reason="tool_use",
        usage={"input_tokens": 150, "output_tokens": 80},
        latency_ms=450,
    )


@pytest.mark.asyncio
class TestClassifierAgent:
    async def test_classify_log_input(self):
        agent = ClassifierAgent()
        mock_output = {
            "task_type": "log",
            "confidence": 0.95,
            "route": "log_triage",
            "reasoning": "Input contains ERROR log lines",
            "suggested_tools": ["log_analysis", "database_query"],
        }

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=make_mock_llm_response(mock_output),
        ):
            result = await agent.run({
                "raw_input": "ERROR: DB connection timeout",
                "input_type": "log",
            })

        assert result.agent_name == "classifier_agent"
        assert result.parsed_output["task_type"] == "log"
        assert result.parsed_output["confidence"] == 0.95
        assert result.tokens_in == 150

    async def test_classify_email_input(self):
        agent = ClassifierAgent()
        mock_output = {
            "task_type": "email",
            "confidence": 0.88,
            "route": "email_response",
            "reasoning": "Input is formatted like an email",
            "suggested_tools": ["email_draft"],
        }

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=make_mock_llm_response(mock_output),
        ):
            result = await agent.run({
                "raw_input": "Subject: Billing issue\n\nHi, I was charged twice.",
                "input_type": "email",
            })

        assert result.parsed_output["task_type"] == "email"

    async def test_raises_on_no_tool_call(self):
        agent = ClassifierAgent()
        from app.services.llm_service import LLMResponse
        empty_response = LLMResponse(
            content="I can't classify this",
            tool_calls=None,
            stop_reason="end_turn",
            usage={"input_tokens": 50, "output_tokens": 20},
            latency_ms=200,
        )

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=empty_response,
        ):
            with pytest.raises(LLMResponseError):
                await agent.run({"raw_input": "test", "input_type": "log"})

    async def test_raises_on_invalid_output_schema(self):
        agent = ClassifierAgent()
        bad_output = {"task_type": "INVALID_TYPE", "confidence": 2.0}  # bad values

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=make_mock_llm_response(bad_output),
        ):
            with pytest.raises((ClassificationError, LLMResponseError)):
                await agent.run({"raw_input": "test", "input_type": "log"})


@pytest.mark.asyncio
class TestPlannerAgent:
    def _make_plan_response(self) -> object:
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
                            "description": "Analyze the log content for errors",
                            "depends_on": [],
                        },
                        {
                            "step_order": 2,
                            "step_name": "synthesize_findings",
                            "tool_name": None,
                            "tool_arguments": None,
                            "description": "Summarize findings and recommend action",
                            "depends_on": [1],
                        },
                    ],
                    "context_notes": "Log triage workflow",
                },
                "id": "tool_456",
            }],
            stop_reason="tool_use",
            usage={"input_tokens": 300, "output_tokens": 150},
            latency_ms=600,
        )

    async def test_generates_valid_plan(self):
        agent = PlannerAgent()

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=self._make_plan_response(),
        ):
            result = await agent.run({
                "classification": {
                    "task_type": "log",
                    "route": "log_triage",
                    "suggested_tools": ["log_analysis"],
                    "reasoning": "Log input",
                },
                "raw_input": "ERROR: timeout",
            })

        assert result.agent_name == "planner_agent"
        steps = result.parsed_output["steps"]
        assert len(steps) == 2
        assert steps[0]["step_order"] == 1
        assert steps[0]["tool_name"] == "log_analysis"
        assert steps[1]["tool_name"] is None  # synthesis step


@pytest.mark.asyncio
class TestAgentFailures:
    def _empty_response(self):
        from app.services.llm_service import LLMResponse
        return LLMResponse(
            content="sorry, cannot help",
            tool_calls=None,
            stop_reason="end_turn",
            usage={"input_tokens": 20, "output_tokens": 10},
            latency_ms=100,
        )

    async def test_llm_no_tool_call_retries_3_times_then_raises(self):
        """BaseAgent retries max_retries=2 times, so 3 total attempts before raising."""
        agent = ClassifierAgent()

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=self._empty_response(),
        ) as mock_llm:
            with pytest.raises(LLMResponseError):
                await agent.run({"raw_input": "test", "input_type": "log"})

        assert mock_llm.call_count == 3

    async def test_llm_retry_succeeds_on_second_attempt(self):
        """If the first LLM call returns no tool_call but the second succeeds, the result is valid."""
        agent = ClassifierAgent()
        good_response = make_mock_llm_response({
            "task_type": "log",
            "confidence": 0.9,
            "route": "log_triage",
            "reasoning": "retry succeeded",
            "suggested_tools": ["log_analysis"],
        })

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            side_effect=[self._empty_response(), good_response],
        ) as mock_llm:
            result = await agent.run({"raw_input": "test", "input_type": "log"})

        assert mock_llm.call_count == 2
        assert result.parsed_output["task_type"] == "log"

    async def test_fallback_agent_returns_safe_response(self):
        from app.agents.fallback_agent import FallbackAgent
        from app.services.llm_service import LLMResponse

        agent = FallbackAgent()
        fallback_response = LLMResponse(
            content="",
            stop_reason="tool_use",
            latency_ms=150,
            usage={"input_tokens": 50, "output_tokens": 30},
            tool_calls=[{
                "name": "handle_fallback",
                "input": {
                    "step_name": "analyze_logs",
                    "failure_reason": "LLM timeout after 3 attempts",
                    "safe_response": "Could not analyze logs. Manual review required.",
                    "should_escalate": True,
                    "recommended_next_steps": ["Review logs manually", "Page on-call"],
                },
                "id": "t_fallback",
            }],
        )

        with patch(
            "app.agents.base_agent.llm_service.complete_with_tools",
            new_callable=AsyncMock,
            return_value=fallback_response,
        ):
            result = await agent.run({
                "step_name": "analyze_logs",
                "failure_reason": "LLM timeout after 3 attempts",
                "original_input": "ERROR: DB timeout",
            })

        assert result.agent_name == "fallback_agent"
        assert result.parsed_output["should_escalate"] is True
        assert len(result.parsed_output["recommended_next_steps"]) == 2
