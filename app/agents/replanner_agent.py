from typing import Any

from pydantic import BaseModel

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.utils.exceptions import LLMResponseError


class ReplanStep(BaseModel):
    step_name: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    description: str


class RePlanningDecision(BaseModel):
    should_replan: bool
    reason: str
    new_steps: list[ReplanStep] = []


class RePlannerAgent(BaseAgent):
    @property
    def model(self) -> str:
        return settings.llm_model_fast

    """
    Invoked after a high-severity step completes. Evaluates findings and
    decides whether to inject new investigative steps before continuing.
    Returns at most 3 new steps to avoid plan explosion.
    """

    @property
    def agent_name(self) -> str:
        return "replanner_agent"

    def build_system_prompt(self) -> str:
        return (
            "You are a dynamic re-planner in an AI ops triage system. "
            "A workflow step has just completed and revealed important findings. "
            "Your job is to decide whether the remaining plan needs new steps "
            "to properly investigate or resolve what was discovered.\n\n"
            "Rules:\n"
            "1. Only add steps if the findings reveal something the remaining plan cannot address.\n"
            "2. Add at most 3 new steps. Keep them targeted and non-redundant.\n"
            "3. If the remaining plan already covers the findings, set should_replan=false.\n"
            "4. New steps must use tools from: log_analysis, email_draft, webhook, database_query.\n"
            "   A step with tool_name=null is an LLM synthesis step.\n"
            "5. Be conservative — unnecessary steps waste time and money.\n\n"
            "You MUST call the 'adjust_execution_plan' tool with your decision."
        )

    def build_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        trigger = context.get("trigger_step", {})
        remaining = context.get("remaining_steps", [])
        completed = context.get("completed_steps", [])
        classification = context.get("classification", {})

        remaining_names = [s.get("step_name") for s in remaining]

        return [
            {
                "role": "user",
                "content": (
                    f"Original workflow input: {context.get('raw_input', '')[:300]}\n"
                    f"Task type: {classification.get('task_type')} | "
                    f"Route: {classification.get('route')}\n\n"
                    f"Step just completed: {trigger.get('step_name')}\n"
                    f"Summary: {trigger.get('summary')}\n"
                    f"Key findings: {trigger.get('key_findings')}\n"
                    f"Severity: {trigger.get('severity')}\n"
                    f"Recommended next action: {trigger.get('next_action')}\n\n"
                    f"Steps already done: {[s.get('step_name') for s in completed]}\n"
                    f"Steps still planned: {remaining_names}\n\n"
                    "Should new investigative steps be inserted before the remaining plan? "
                    "Call 'adjust_execution_plan' with your decision."
                ),
            }
        ]

    def get_output_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "adjust_execution_plan",
                "description": "Decide whether to inject new steps into the workflow plan.",
                "parameters": RePlanningDecision.model_json_schema(),
            },
        }

    def parse_tool_call(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            decision = RePlanningDecision(**tool_input)
            return decision.model_dump()
        except Exception as e:
            raise LLMResponseError(f"Invalid re-planning decision: {e}") from e
