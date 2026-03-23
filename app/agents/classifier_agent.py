from typing import Any

from pydantic import BaseModel, Field

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.services.config_loader import get_config
from app.utils.exceptions import ClassificationError


class ClassificationOutput(BaseModel):
    task_type: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    route: str
    reasoning: str
    suggested_tools: list[str]


class ClassifierAgent(BaseAgent):
    @property
    def model(self) -> str:
        return settings.llm_model_fast

    @property
    def agent_name(self) -> str:
        return "classifier_agent"

    def build_system_prompt(self) -> str:
        config = get_config()
        type_lines = "\n".join(
            f"- {name}: {cfg.description}"
            for name, cfg in config.input_types.items()
        )
        valid_types = ", ".join(config.input_types.keys())
        return (
            "You are a workflow classifier for an AI ops system. "
            "Analyze the incoming request and classify it into one of the configured input types.\n\n"
            f"Configured input types:\n{type_lines}\n\n"
            f"task_type must be one of: {valid_types}\n\n"
            "You MUST call the 'classify_workflow' tool with your classification."
        )

    def build_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        raw_input = context.get("raw_input", "")
        input_type_hint = context.get("input_type", "")
        return [
            {
                "role": "user",
                "content": (
                    f"Classify this workflow input.\n\n"
                    f"Declared input type (may be a hint or may be wrong): {input_type_hint}\n\n"
                    f"Input content:\n{raw_input}"
                ),
            }
        ]

    def get_output_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "classify_workflow",
                "description": "Classify the incoming workflow request and determine the execution route.",
                "parameters": ClassificationOutput.model_json_schema(),
            },
        }

    def parse_tool_call(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        try:
            output = ClassificationOutput(**tool_input)
            return output.model_dump()
        except Exception as e:
            raise ClassificationError(f"Invalid classification output: {e}") from e
