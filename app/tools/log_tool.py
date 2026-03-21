import re
from typing import Any, ClassVar

from pydantic import BaseModel

from app.tools.base import BaseTool, ToolResult
from app.utils.helpers import ms_since, utcnow


class LogAnalysisInput(BaseModel):
    log_content: str
    severity_filter: str | None = None  # e.g. "ERROR", "WARN"


class LogAnalysisTool(BaseTool):
    name: ClassVar[str] = "log_analysis"
    description: ClassVar[str] = (
        "Analyzes log content to extract errors, warnings, patterns, and anomalies. "
        "Returns a structured summary with error counts, top issues, and recommended actions."
    )
    input_schema: ClassVar[type[BaseModel]] = LogAnalysisInput

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        start = utcnow()
        try:
            args = LogAnalysisInput(**arguments)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output={},
                error=f"Invalid arguments: {e}",
                latency_ms=0,
            )

        lines = args.log_content.splitlines()
        errors = [l for l in lines if "ERROR" in l.upper()]
        warnings = [l for l in lines if "WARN" in l.upper()]
        exceptions = [l for l in lines if re.search(r"exception|traceback|stacktrace", l, re.IGNORECASE)]

        if args.severity_filter:
            filtered = [l for l in lines if args.severity_filter.upper() in l.upper()]
        else:
            filtered = errors + warnings

        # Extract timestamps if present (ISO or common formats)
        timestamps = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", args.log_content)

        # Determine severity
        if errors:
            severity = "critical" if len(errors) > 5 else "high"
        elif warnings:
            severity = "medium"
        else:
            severity = "low"

        # Build top issues (deduplicated)
        top_issues: list[str] = []
        seen: set[str] = set()
        for line in errors[:5]:
            key = line[:100]
            if key not in seen:
                seen.add(key)
                top_issues.append(line.strip())

        return ToolResult(
            tool_name=self.name,
            success=True,
            output={
                "total_lines": len(lines),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "exception_count": len(exceptions),
                "severity": severity,
                "top_issues": top_issues,
                "time_range": {
                    "first": timestamps[0] if timestamps else None,
                    "last": timestamps[-1] if timestamps else None,
                },
                "filtered_matches": filtered[:10],
                "recommended_action": _recommend_action(severity, errors),
            },
            latency_ms=ms_since(start),
        )


def _recommend_action(severity: str, errors: list[str]) -> str:
    if severity == "critical":
        return "Immediate escalation required. Page on-call engineer."
    if severity == "high":
        return "Create high-priority incident ticket. Investigate within 1 hour."
    if severity == "medium":
        return "Log warning for next business day review."
    return "No immediate action required. Monitor for recurrence."
