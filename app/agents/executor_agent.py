from typing import Any

from pydantic import BaseModel

from app.agents.base_agent import BaseAgent
from app.utils.exceptions import LLMResponseError


class StepExecutionOutput(BaseModel):
    step_name: str
    summary: str
    key_findings: list[str]
    next_action: str
    severity: str | None = None  # critical, high, medium, low
    raw_tool_output: dict[str, Any] | None = None
    needs_replan: bool = False  # set True if findings warrant new investigative steps


class ExecutorAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "executor_agent"

    def build_system_prompt(self) -> str:
        return (
            "You are a step executor in an AI ops triage system. "
            "You receive a workflow step and its tool output (if any) and produce a structured synthesis.\n\n"
            "Your job:\n"
            "1. Analyze the step's tool output\n"
            "2. Extract key findings relevant to the overall workflow\n"
            "3. Determine the next recommended action\n"
            "4. Assess severity if applicable\n"
            "5. Set needs_replan=true ONLY if the findings reveal something critical that "
            "the remaining planned steps cannot address — for example, a new error source "
            "was discovered, a database anomaly was found, or escalation paths are unclear.\n\n"
            "Be concise and precise. Focus on actionable insights.\n"
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
