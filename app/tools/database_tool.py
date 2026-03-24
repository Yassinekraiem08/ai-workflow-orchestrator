from typing import Any, ClassVar

from pydantic import BaseModel

from app.tools.base import BaseTool, ToolResult
from app.utils.helpers import ms_since, utcnow

# Simulated in-memory "database" for the tool — in production this would
# connect to a real data source via SQLAlchemy or another client.
_MOCK_INCIDENT_DB: list[dict[str, Any]] = [
    {"id": "INC-001", "service": "payment-api", "status": "open", "severity": "high", "created_at": "2026-03-19"},
    {"id": "INC-002", "service": "auth-service", "status": "resolved", "severity": "medium", "created_at": "2026-03-18"},
    {"id": "INC-003", "service": "database", "status": "open", "severity": "critical", "created_at": "2026-03-20"},
]


class DatabaseQueryInput(BaseModel):
    query_type: str = "incidents"  # "incidents", "services", "recent_errors"
    filters: dict[str, Any] | None = None
    limit: int = 10


class DatabaseQueryTool(BaseTool):
    name: ClassVar[str] = "database_query"
    description: ClassVar[str] = (
        "Queries the internal incident and service database for relevant records. "
        "Supports filtering by service name, severity, status, and date range."
    )
    input_schema: ClassVar[type[BaseModel]] = DatabaseQueryInput

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        start = utcnow()
        try:
            args = DatabaseQueryInput(**arguments)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Invalid arguments: {e}",
                latency_ms=0,
            )

        if args.query_type == "incidents":
            records = _MOCK_INCIDENT_DB.copy()
            if args.filters:
                for key, value in args.filters.items():
                    records = [r for r in records if r.get(key) == value]
            records = records[:args.limit]

            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "query_type": args.query_type,
                    "record_count": len(records),
                    "records": records,
                },
                latency_ms=ms_since(start),
            )

        if args.query_type == "recent_errors":
            open_incidents = [r for r in _MOCK_INCIDENT_DB if r["status"] == "open"]
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "query_type": args.query_type,
                    "record_count": len(open_incidents),
                    "records": open_incidents[:args.limit],
                },
                latency_ms=ms_since(start),
            )

        return ToolResult(
            tool_name=self.name,
            success=False,
            output={},
            error=f"Unknown query_type: '{args.query_type}'. Supported: incidents, recent_errors",
            latency_ms=ms_since(start),
        )
