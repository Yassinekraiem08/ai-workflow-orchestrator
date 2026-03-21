from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.tools.base import BaseTool, ToolResult
from app.utils.helpers import ms_since, utcnow

_SEVERITY_COLORS = {
    "critical": "#FF0000",
    "high": "#FF6600",
    "medium": "#FFCC00",
    "low": "#36A64F",
    "info": "#36A64F",
}


class SlackNotificationInput(BaseModel):
    webhook_url: str
    message: str
    title: str = ""
    severity: str = "info"  # critical, high, medium, low, info
    run_id: str = ""
    timeout_seconds: int = 10


class SlackNotificationTool(BaseTool):
    name: ClassVar[str] = "slack_notification"
    description: ClassVar[str] = (
        "Sends a formatted notification to a Slack channel via an Incoming Webhook URL. "
        "Supports severity-coded message blocks with optional run ID for traceability."
    )
    input_schema: ClassVar[type[BaseModel]] = SlackNotificationInput

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        start = utcnow()
        try:
            args = SlackNotificationInput(**arguments)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Invalid arguments: {e}",
                latency_ms=0,
            )

        color = _SEVERITY_COLORS.get(args.severity.lower(), "#36A64F")
        title = args.title or f"AI Ops Alert — {args.severity.upper()}"
        footer = f"run_id: {args.run_id}" if args.run_id else "AI Workflow Orchestrator"

        payload: dict[str, Any] = {
            "attachments": [
                {
                    "color": color,
                    "title": title,
                    "text": args.message,
                    "footer": footer,
                    "ts": int(utcnow().timestamp()),
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
                response = await client.post(args.webhook_url, json=payload)

            success = 200 <= response.status_code < 300
            try:
                response_body = response.json()
            except Exception:
                response_body = {"text": response.text[:200]}

            if not success:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    output={"status_code": response.status_code, "response": response_body},
                    error=f"Slack returned {response.status_code}",
                    latency_ms=ms_since(start),
                )

            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "status_code": response.status_code,
                    "channel_response": response_body,
                    "title": title,
                    "severity": args.severity,
                },
                latency_ms=ms_since(start),
            )

        except httpx.TimeoutException:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Slack webhook timed out after {args.timeout_seconds}s",
                latency_ms=ms_since(start),
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Slack notification failed: {e}",
                latency_ms=ms_since(start),
            )
