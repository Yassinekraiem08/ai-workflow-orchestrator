from typing import Any

from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent
from app.utils.exceptions import PlanningError


class PlanStep(BaseModel):
    step_order: int = Field(..., ge=1)
    step_name: str
    tool_name: str | None = None  # None = LLM-only step
    tool_arguments: dict[str, Any] | None = None
    description: str
    depends_on: list[int] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    steps: list[PlanStep] = Field(..., min_length=1)
    context_notes: str = ""


class PlannerAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "planner_agent"

    def build_system_prompt(self) -> str:
        return (
            "You are a workflow planner for an AI ops triage system. "
            "Given a classified task, generate a step-by-step execution plan.\n\n"
            "Available tools:\n"
            "- log_analysis: Analyze log content for errors, patterns, and recommended actions\n"
            "- email_draft: Generate a draft email response\n"
            "- webhook: Send an HTTP notification to an arbitrary external endpoint\n"
            "- database_query: Query the incident/service database\n"
            "- slack_notification: Send a formatted alert to a Slack channel via webhook URL. "
            "Args: webhook_url, message, title (optional), severity (critical/high/medium/low/info), "
            "run_id (optional)\n"
            "- pagerduty_incident: Create, acknowledge, or resolve a PagerDuty incident. "
            "Args: routing_key, summary, severity (critical/error/warning/info), "
            "action (trigger/acknowledge/resolve), dedup_key (optional), details (optional)\n\n"
            "Rules:\n"
            "1. Keep plans to 3-6 steps\n"
            "2. The last step should always be a summary/synthesis step with no tool (tool_name=null)\n"
            "3. Tool arguments must match the tool's expected inputs exactly\n"
            "4. For log inputs: always start with log_analysis\n"
            "5. For ticket inputs: start with database_query to check existing incidents\n"
            "6. For email inputs: start with email_draft\n\n"
            "You MUST call the 'create_execution_plan' tool with your plan."
        )

    def build_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        classification = context.get("classification", {})
        raw_input = context.get("raw_input", "")
        return [
            {
                "role": "user",
                "content": (
                    f"Create an execution plan for this classified workflow.\n\n"
                    f"Classification:\n"
                    f"- Task type: {classification.get('task_type')}\n"
                    f"- Route: {classification.get('route')}\n"
                    f"- Suggested tools: {classification.get('suggested_tools', [])}\n"
                    f"- Reasoning: {classification.get('reasoning')}\n\n"
                    f"Original input:\n{raw_input}"
                ),
            }
        ]

    def get_output_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "create_execution_plan",
                "description": "Create an ordered execution plan for the classified workflow.",
                "parameters": ExecutionPlan.model_json_schema(),
            },
        }

    def parse_tool_call(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            plan = ExecutionPlan(**tool_input)
            return plan.model_dump()
        except Exception as e:
            raise PlanningError(f"Invalid execution plan: {e}") from e
