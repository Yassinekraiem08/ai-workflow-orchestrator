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
            "You receive a workflow step, its tool output (if any), and the original input. "
            "Produce a structured synthesis.\n\n"
            "Your job:\n"
            "1. Analyze the step's tool output and original input\n"
            "2. Extract key findings — name ONLY services, error codes, and components that appear "
            "in the tool output or original input. NEVER invent service names, error codes, or root causes "
            "that are not present in the data you were given.\n"
            "3. For the next_action field: give CONCRETE, IMMEDIATE actions based on actual findings "
            "(e.g. 'Restart fraud-check-svc in EU-WEST-1 and monitor circuit breaker status'). "
            "If evidence is limited, say what's known and recommend manual review.\n"
            "4. Assess severity based on actual signals, not assumptions\n"
            "5. For summary steps: state the most likely root cause hypothesis based ONLY on evidence "
            "from prior steps and the original input. If prior steps were skipped or produced no data, "
            "derive what you can from the original input text alone and explicitly note the limitation.\n"
            "6. Set needs_replan=true ONLY if the findings reveal something critical that "
            "the remaining planned steps cannot address.\n\n"
            "CRITICAL: Ground every conclusion in actual data. Do not hallucinate.\n"
            "You MUST call the 'record_step_result' tool with your synthesis."
        )

    def build_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        step = context.get("step", {})
        tool_result = context.get("tool_result", {})
        run_context = context.get("run_context", {})
        raw_input = context.get("raw_input", "")

        tool_section = ""
        if tool_result:
            tool_section = f"\nTool execution result:\n{tool_result}"

        prior_steps = run_context.get("completed_steps", [])
        prior_section = ""
        if prior_steps:
            prior_section = f"\nContext from prior steps:\n{prior_steps[-3:]}"  # last 3 steps
        else:
            prior_section = "\nContext from prior steps: none (earlier steps were skipped or this is the first step)"

        input_section = f"\nOriginal input:\n{raw_input}" if raw_input else ""

        return [
            {
                "role": "user",
                "content": (
                    f"Execute and synthesize workflow step: {step.get('step_name')}\n\n"
                    f"Step description: {step.get('description')}\n"
                    f"Step order: {step.get('step_order')}"
                    f"{tool_section}"
                    f"{prior_section}"
                    f"{input_section}"
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
        # Manually coerce each field so no LLM output shape can cause a failure.
        raw_findings = tool_input.get("key_findings", [])
        if isinstance(raw_findings, str):
            key_findings = [raw_findings] if raw_findings else []
        elif isinstance(raw_findings, list):
            key_findings = [str(f) for f in raw_findings if f]
        else:
            key_findings = []

        raw_tool_output = tool_input.get("raw_tool_output")
        if not isinstance(raw_tool_output, dict):
            raw_tool_output = None

        return StepExecutionOutput(
            step_name=str(tool_input.get("step_name") or ""),
            summary=str(tool_input.get("summary") or ""),
            key_findings=key_findings,
            next_action=str(tool_input.get("next_action") or ""),
            severity=tool_input.get("severity"),
            raw_tool_output=raw_tool_output,
            needs_replan=bool(tool_input.get("needs_replan", False)),
        ).model_dump()
