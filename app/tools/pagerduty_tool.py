from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.tools.base import BaseTool, ToolResult
from app.utils.helpers import ms_since, utcnow

_PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

_VALID_SEVERITIES = {"critical", "error", "warning", "info"}
_VALID_ACTIONS = {"trigger", "acknowledge", "resolve"}


class PagerDutyIncidentInput(BaseModel):
    routing_key: str
    summary: str
    severity: str = "error"  # critical, error, warning, info
    source: str = "ai-workflow-orchestrator"
    action: str = "trigger"  # trigger, acknowledge, resolve
    dedup_key: str = ""  # use run_id to dedup/resolve incidents
    details: dict[str, Any] = {}
    timeout_seconds: int = 10


class PagerDutyIncidentTool(BaseTool):
    name: ClassVar[str] = "pagerduty_incident"
    description: ClassVar[str] = (
        "Creates, acknowledges, or resolves a PagerDuty incident via the Events API v2. "
        "Use action=trigger to open an incident, action=resolve to close it. "
        "Provide a dedup_key (e.g. run_id) to link trigger and resolve events."
    )
    input_schema: ClassVar[type[BaseModel]] = PagerDutyIncidentInput

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        start = utcnow()
        try:
            args = PagerDutyIncidentInput(**arguments)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Invalid arguments: {e}",
                latency_ms=0,
            )

        severity = args.severity.lower()
        if severity not in _VALID_SEVERITIES:
            severity = "error"

        action = args.action.lower()
        if action not in _VALID_ACTIONS:
            action = "trigger"

        payload: dict[str, Any] = {
            "routing_key": args.routing_key,
            "event_action": action,
            "payload": {
                "summary": args.summary,
                "source": args.source,
                "severity": severity,
                "custom_details": args.details or {},
            },
        }
        if args.dedup_key:
            payload["dedup_key"] = args.dedup_key

        try:
            async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
                response = await client.post(
                    _PAGERDUTY_EVENTS_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

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
                    error=f"PagerDuty returned {response.status_code}: {response_body.get('message', '')}",
                    latency_ms=ms_since(start),
                )

            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "status_code": response.status_code,
                    "dedup_key": response_body.get("dedup_key", args.dedup_key),
                    "incident_key": response_body.get("incident_key", ""),
                    "action": action,
                    "severity": severity,
                    "message": response_body.get("message", "Event processed"),
                },
                latency_ms=ms_since(start),
            )

        except httpx.TimeoutException:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"PagerDuty request timed out after {args.timeout_seconds}s",
                latency_ms=ms_since(start),
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"PagerDuty incident failed: {e}",
                latency_ms=ms_since(start),
            )
