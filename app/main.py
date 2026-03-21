from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import routes_auth, routes_health, routes_runs, routes_workflows
from app.db.session import engine
from app.services.logging_service import configure_logging
from app.services.telemetry_service import setup_telemetry
from app.tools.base import tool_registry
from app.tools.database_tool import DatabaseQueryTool
from app.tools.email_tool import EmailDraftTool
from app.tools.log_tool import LogAnalysisTool
from app.tools.pagerduty_tool import PagerDutyIncidentTool
from app.tools.slack_tool import SlackNotificationTool
from app.tools.webhook_tool import WebhookTool


def register_tools() -> None:
    tool_registry.register(LogAnalysisTool())
    tool_registry.register(EmailDraftTool())
    tool_registry.register(WebhookTool())
    tool_registry.register(DatabaseQueryTool())
    tool_registry.register(SlackNotificationTool())
    tool_registry.register(PagerDutyIncidentTool())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    setup_telemetry(app)
    register_tools()

    yield

    await engine.dispose()


app = FastAPI(
    title="AI Workflow Orchestrator",
    description=(
        "Production-grade LLM orchestration system for multi-step, fault-tolerant workflows "
        "with tool execution and state tracking. Use case: AI Ops triage for tickets, emails, and logs."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(routes_health.router)
app.include_router(routes_auth.router)
app.include_router(routes_workflows.router)
app.include_router(routes_runs.router)
