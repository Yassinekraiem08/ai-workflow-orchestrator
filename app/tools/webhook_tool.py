from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.tools.base import BaseTool, ToolResult
from app.utils.helpers import ms_since, utcnow


class WebhookInput(BaseModel):
    url: str
    payload: dict[str, Any]
    method: str = "POST"  # POST or GET
    timeout_seconds: int = 10


class WebhookTool(BaseTool):
    name: ClassVar[str] = "webhook"
    description: ClassVar[str] = (
        "Sends an HTTP request to an external webhook URL with a structured payload. "
        "Used for triggering external actions like PagerDuty alerts, Slack messages, or API calls."
    )
    input_schema: ClassVar[type[BaseModel]] = WebhookInput

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        start = utcnow()
        try:
            args = WebhookInput(**arguments)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Invalid arguments: {e}",
                latency_ms=0,
            )

        try:
            async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
                if args.method.upper() == "POST":
                    response = await client.post(args.url, json=args.payload)
                else:
                    response = await client.get(args.url, params=args.payload)

            success = 200 <= response.status_code < 300
            try:
                response_body = response.json()
            except Exception:
                response_body = {"text": response.text[:500]}

            return ToolResult(
                tool_name=self.name,
                success=success,
                output={
                    "status_code": response.status_code,
                    "response_body": response_body,
                    "url": args.url,
                },
                error=None if success else f"HTTP {response.status_code}",
                latency_ms=ms_since(start),
            )

        except httpx.TimeoutException:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={"url": args.url},
                error=f"Request timed out after {args.timeout_seconds}s",
                latency_ms=ms_since(start),
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={"url": args.url},
                error=str(e),
                latency_ms=ms_since(start),
            )
