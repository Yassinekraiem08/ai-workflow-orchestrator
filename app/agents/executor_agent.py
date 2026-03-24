from typing import Any

from pydantic import BaseModel

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.utils.exceptions import LLMResponseError


class StepExecutionOutput(BaseModel):
    step_name: str = ""
    summary: str = ""
    key_findings: list[str] = []
    next_action: str = ""
    severity: str | None = None  # critical, high, medium, low
    raw_tool_output: dict[str, Any] | None = None
    needs_replan: bool = False  # set True if findings warrant new investigative steps


class ExecutorAgent(BaseAgent):
    @property
    def model(self) -> str:
        return settings.llm_model_strong  # executor needs the strongest model

    @property
    def agent_name(self) -> str:
        return "executor_agent"

    def build_system_prompt(self) -> str:
        return (
            "You are a step executor in an AI ops triage system. "
            "You receive a workflow step and its tool output (if any) and produce a structured synthesis.\n\n"
            "Your job:\n"
            "1. Analyze the step's tool output\n"
            "2. Extract key findings — be specific: name the exact services, error codes, and components involved\n"
            "3. For the next_action field: give CONCRETE, IMMEDIATE actions an on-call engineer can take right now "
            "(e.g. 'Restart fraud-check-svc in EU-WEST-1 and monitor circuit breaker status' not 'investigate the issue')\n"
            "4. Assess severity if applicable\n"
            "5. For summary steps: state the most likely root cause hypothesis explicitly, "
            "name the specific failing component, and list 2-3 immediate remediation steps\n"
            "6. Set needs_replan=true ONLY if the findings reveal something critical that "
            "the remaining planned steps cannot address.\n\n"
            "Be specific and decisive. An engineer reading this at 2am should know exactly what to do.\n"
            "You MUST call the 'record_step_result' tool with your synthesis."
        )

    def build_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        step = context.get("step", {})
        tool_result = context.get("tool_result", {})
        run_context = context.get("run_context", {})

        tool_section = ""
        if tool_result:
            tool_section = f"\nTool execution result:\n{tool_result}"

        prior_steps = run_context.get("completed_steps", [])
        prior_section = ""
        if prior_steps:
            prior_section = f"\nContext from prior steps:\n{prior_steps[-3:]}"  # last 3 steps

        return [
            {
                "role": "user",
                "content": (
                    f"Execute and synthesize workflow step: {step.get('step_name')}\n\n"
                    f"Step description: {step.get('description')}\n"
                    f"Step order: {step.get('step_order')}"
                    f"{tool_section}"
                    f"{prior_section}"
                ),
            }
        ]

    def get_output_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "record_step_result",
                "description": "Record the synthesis and findings from executing this workflow step.",
                "parameters": StepExecutionOutput.model_json_schema(),
            },
        }

    def parse_tool_call(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            output = StepExecutionOutput(**tool_input)
            return output.model_dump()
        except Exception as e:
            raise LLMResponseError(f"Invalid step execution output: {e}") from e
