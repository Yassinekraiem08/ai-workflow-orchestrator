from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, ClassVar, Generator

from pydantic import BaseModel


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    output: dict[str, Any]
    error: str | None = None
    latency_ms: int


class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ...

    def to_openai_tool_definition(self) -> dict[str, Any]:
        """Returns the OpenAI function tool definition dict for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema.model_json_schema(),
            },
        }


class ToolRegistry:
    _instance: "ToolRegistry | None" = None
    _tools: dict[str, BaseTool]

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(self._tools.keys())}")
        return self._tools[name]

    def list_available(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool_definition() for tool in self._tools.values()]

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    @contextmanager
    def override(self, name: str, mock_tool: BaseTool) -> Generator[None, None, None]:
        """Context manager for test overrides."""
        original = self._tools.get(name)
        self._tools[name] = mock_tool
        try:
            yield
        finally:
            if original is None:
                self._tools.pop(name, None)
            else:
                self._tools[name] = original


tool_registry = ToolRegistry()
