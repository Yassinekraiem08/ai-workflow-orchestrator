import json
from datetime import datetime
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.utils.helpers import ms_since, utcnow


class LLMRequest(BaseModel):
    messages: list[dict[str, Any]]
    system: str | None = None
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 4096
    temperature: float = 0.1
    model: str | None = None  # overrides settings.llm_model when set


# Pricing per 1K tokens (input, output) as of 2026
_COST_PER_1K: dict[str, dict[str, float]] = {
    "gpt-4o":      {"input": 0.0025,  "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Returns estimated USD cost for an LLM call."""
    prices = _COST_PER_1K.get(model, _COST_PER_1K["gpt-4o"])
    return round(
        (tokens_in / 1000) * prices["input"] + (tokens_out / 1000) * prices["output"],
        6,
    )


class LLMResponse(BaseModel):
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    stop_reason: str
    usage: dict[str, int]
    latency_ms: int


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _build_messages(request: LLMRequest) -> list[dict[str, Any]]:
    """Prepend system message into the messages list (OpenAI style)."""
    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.extend(request.messages)
    return messages


async def complete(request: LLMRequest) -> LLMResponse:
    client = get_client()
    start: datetime = utcnow()

    response = await client.chat.completions.create(
        model=request.model or settings.llm_model,
        messages=_build_messages(request),
        max_tokens=request.max_tokens,
        temperature=request.temperature,
    )

    choice = response.choices[0]
    content = choice.message.content or ""

    return LLMResponse(
        content=content,
        tool_calls=None,
        stop_reason=choice.finish_reason or "stop",
        usage={
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        },
        latency_ms=ms_since(start),
    )


async def complete_with_tools(request: LLMRequest) -> LLMResponse:
    """
    Call the model with function/tool calling.
    Forces the model to call the first tool defined (structured output pattern).
    """
    client = get_client()
    start: datetime = utcnow()

    tools = request.tools or []
    tool_choice = (
        {"type": "function", "function": {"name": tools[0]["function"]["name"]}}
        if tools else "none"
    )

    response = await client.chat.completions.create(
        model=request.model or settings.llm_model,
        messages=_build_messages(request),
        tools=tools,
        tool_choice=tool_choice,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
    )

    choice = response.choices[0]
    content = choice.message.content or ""

    tool_calls: list[dict[str, Any]] = []
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            tool_calls.append({
                "name": tc.function.name,
                "input": json.loads(tc.function.arguments),  # OpenAI returns JSON string
                "id": tc.id,
            })

    return LLMResponse(
        content=content,
        tool_calls=tool_calls if tool_calls else None,
        stop_reason=choice.finish_reason or "tool_calls",
        usage={
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        },
        latency_ms=ms_since(start),
    )
