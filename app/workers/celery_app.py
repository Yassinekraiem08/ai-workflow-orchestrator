from celery import Celery
from celery.signals import worker_process_init

from app.config import settings

celery_app = Celery(
    "workflow_orchestrator",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # one task at a time per worker (for long-running workflows)
    task_routes={
        "app.workers.tasks.execute_workflow_task": {"queue": "workflows"},
        "app.workers.tasks.retry_step_task": {"queue": "retries"},
        "app.workers.tasks.dead_letter_task": {"queue": "dead_letter"},
    },
    task_default_queue="workflows",
)


@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """
    Runs once in each Celery Prefork worker process after forking.

    1. Register tools — FastAPI lifespan never runs in workers, so tool_registry
       would otherwise be empty, causing "Tool not registered" errors.

    2. Initialise OpenTelemetry — setup_telemetry() is normally called in the
       FastAPI lifespan, which never runs in worker processes. Without this, the
       global tracer provider stays as the no-op default and no spans reach Jaeger.

    3. Replace the SQLAlchemy engine with NullPool — the default pool holds open
       asyncpg connections that are bound to the event loop that created them.
       Prefork workers call asyncio.run() once per task (new loop each time), so
       pooled connections from a previous run would reference the old loop and raise
       "Future attached to a different loop". NullPool opens and closes a connection
       per session, keeping max concurrent connections to 1 per worker process.
    """
    # --- 1. Tool registration ---
    from app.tools.base import tool_registry
    from app.tools.database_tool import DatabaseQueryTool
    from app.tools.email_tool import EmailDraftTool
    from app.tools.log_tool import LogAnalysisTool
    from app.tools.pagerduty_tool import PagerDutyIncidentTool
    from app.tools.slack_tool import SlackNotificationTool
    from app.tools.webhook_tool import WebhookTool

    tool_registry.register(LogAnalysisTool())
    tool_registry.register(EmailDraftTool())
    tool_registry.register(WebhookTool())
    tool_registry.register(DatabaseQueryTool())
    tool_registry.register(SlackNotificationTool())
    tool_registry.register(PagerDutyIncidentTool())

    # --- 2. OpenTelemetry ---
    from app.services.telemetry_service import setup_telemetry
    setup_telemetry()

    # --- 3. NullPool engine ---
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.db.session as db_session

    db_session.engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
    )
    db_session.AsyncSessionFactory = async_sessionmaker(
        bind=db_session.engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
