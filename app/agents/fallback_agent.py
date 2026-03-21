from typing import Any

from pydantic import BaseModel

from app.agents.base_agent import BaseAgent
from app.utils.exceptions import LLMResponseError


class FallbackOutput(BaseModel):
    step_name: str
    failure_reason: str
    safe_response: str
    should_escalate: bool
    recommended_next_steps: list[str]


class FallbackAgent(BaseAgent):
    """
    Triggered when a step fails after tool retries, or when the ExecutorAgent
    output fails Pydantic validation twice. Produces a safe default response
    so the workflow can complete rather than dying.
    """

    @property
    def agent_name(self) -> str:
        return "fallback_agent"

    def build_system_prompt(self) -> str:
        return (
            "You are a fallback handler in an AI ops triage system. "
            "A workflow step has failed. Your job is to:\n"
            "1. Acknowledge the failure clearly\n"
            "2. Produce a safe, helpful default response\n"
            "3. Decide whether human escalation is needed\n"
            "4. Suggest recovery steps\n\n"
            "Be conservative: when in doubt, recommend escalation.\n"
            "You MUST call the 'handle_fallback' tool with your response."
        )

    def build_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        step_name = context.get("step_name", "unknown")
        failure_reason = context.get("failure_reason", "unknown error")
        original_input = context.get("original_input", "")

        return [
            {
                "role": "user",
                "content": (
                    f"A workflow step has failed and needs a fallback response.\n\n"
                    f"Failed step: {step_name}\n"
                    f"Failure reason: {failure_reason}\n"
                    f"Original workflow input: {original_input}"
                ),
            }
        ]

    def get_output_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "handle_fallback",
                "description": "Provide a safe fallback response for a failed workflow step.",
                "parameters": FallbackOutput.model_json_schema(),
            },
        }

    def parse_tool_call(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            output = FallbackOutput(**tool_input)
            return output.model_dump()
        except Exception as e:
            # Fallback of the fallback: return a hardcoded safe response
            return {
                "step_name": tool_input.get("step_name", "unknown"),
                "failure_reason": "Fallback agent also encountered an error",
                "safe_response": "This workflow step could not be completed. Manual review required.",
                "should_escalate": True,
                "recommended_next_steps": ["Review workflow logs", "Contact on-call engineer"],
            }
