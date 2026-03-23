from typing import Any

from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent
from app.config import settings
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
    def model(self) -> str:
        return settings.llm_model_fast

    @property
    def agent_name(self) -> str:
        return "planner_agent"

    def build_system_prompt(self) -> str:
        from app.services.config_loader import get_config
        config = get_config()

        tool_lines = []
        for name, tool in config.tools.items():
            line = f"- {name}: {tool.description}"
            if tool.args:
                line += f". Args: {tool.args}"
            tool_lines.append(line)

        rules_lines = "\n".join(
            f"{i + 1}. {rule}"
            for i, rule in enumerate(config.planner.rules)
        )

        tools_block = "\n".join(tool_lines)
        return (
            "You are a workflow planner for an AI ops triage system. "
            "Given a classified task, generate a step-by-step execution plan.\n\n"
            f"Available tools:\n{tools_block}\n\n"
            f"Rules:\n{rules_lines}\n\n"
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
