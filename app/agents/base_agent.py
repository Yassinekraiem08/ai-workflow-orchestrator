from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from app.config import settings
from app.services import llm_service
from app.services.llm_service import LLMRequest, LLMResponse
from app.utils.exceptions import LLMResponseError


class AgentResult(BaseModel):
    agent_name: str
    raw_response: str
    parsed_output: dict[str, Any]
    tokens_in: int
    tokens_out: int
    latency_ms: int


class BaseAgent(ABC):
    model: str = settings.llm_model
    max_retries: int = 2

    @property
    @abstractmethod
    def agent_name(self) -> str:
        ...

    @abstractmethod
    def build_system_prompt(self) -> str:
        ...

    @abstractmethod
    def build_messages(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_output_tool_definition(self) -> dict[str, Any]:
        """Returns the OpenAI function tool definition that forces structured output."""
        ...

    @abstractmethod
    def parse_tool_call(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Validate and return the parsed tool call input."""
        ...

    async def run(self, context: dict[str, Any]) -> AgentResult:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                request = LLMRequest(
                    messages=self.build_messages(context),
                    system=self.build_system_prompt(),
                    tools=[self.get_output_tool_definition()],
                    max_tokens=4096,
                    temperature=0.1,
                )

                response: LLMResponse = await llm_service.complete_with_tools(request)

                if not response.tool_calls:
                    raise LLMResponseError(
                        f"{self.agent_name}: expected tool_use response, got none. "
                        f"stop_reason={response.stop_reason}"
                    )

                tool_call = response.tool_calls[0]
                parsed = self.parse_tool_call(tool_call["input"])

                return AgentResult(
                    agent_name=self.agent_name,
                    raw_response=str(tool_call["input"]),
                    parsed_output=parsed,
                    tokens_in=response.usage.get("input_tokens", 0),
                    tokens_out=response.usage.get("output_tokens", 0),
                    latency_ms=response.latency_ms,
                )

            except LLMResponseError as e:
                last_error = e
                if attempt < self.max_retries:
                    continue
                raise

            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    continue
                raise LLMResponseError(
                    f"{self.agent_name}: failed after {self.max_retries + 1} attempts: {e}"
                ) from e

        raise LLMResponseError(f"{self.agent_name}: exhausted retries") from last_error
