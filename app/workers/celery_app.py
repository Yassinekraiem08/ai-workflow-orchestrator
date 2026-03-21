from celery import Celery

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
