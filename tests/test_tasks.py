"""
Celery task unit tests — exercise retry logic and dead-letter dispatch
without a live broker by calling the task function directly.

Uses Celery's push_request()/pop_request() pattern to set up the task
context (request.retries, request.id) for testing.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.utils.enums import RunStatus


def test_celery_task_retries_on_failure():
    """When the orchestrator fails and retries remain, self.retry() is called."""
    from celery.exceptions import Retry as CeleryRetry

    from app.workers.tasks import execute_workflow_task

    mock_retry = MagicMock(side_effect=CeleryRetry())

    execute_workflow_task.push_request(retries=0, id="test_task_001")
    try:
        with (
            patch.object(execute_workflow_task, "retry", mock_retry),
            patch("app.workers.tasks.asyncio.run", side_effect=RuntimeError("orchestrator crashed")),
            pytest.raises(CeleryRetry),
        ):
            execute_workflow_task.run(run_id="run_retry_1", input_type="log", raw_input="ERROR: crash")
    finally:
        execute_workflow_task.pop_request()

    mock_retry.assert_called_once()


def test_celery_task_does_not_retry_at_max():
    """When retries are exhausted, self.retry() is NOT called — dead-letter runs instead."""
    from app.workers.tasks import execute_workflow_task

    # Set retries == max_retries so the retry branch is skipped
    execute_workflow_task.push_request(retries=execute_workflow_task.max_retries, id="test_task_002")
    try:
        with (
            patch("app.workers.tasks.asyncio.run", side_effect=RuntimeError("persistent failure")),
            patch("app.workers.tasks.dead_letter_task") as mock_dead_letter,
        ):
            result = execute_workflow_task.run(
                run_id="run_dead_001", input_type="log", raw_input="ERROR: persistent"
            )
    finally:
        execute_workflow_task.pop_request()

    mock_dead_letter.delay.assert_called_once_with("run_dead_001", "persistent failure")
    assert result["status"] == RunStatus.DEAD_LETTER
    assert result["run_id"] == "run_dead_001"


def test_celery_task_succeeds_on_valid_orchestrator_result():
    """When the orchestrator completes successfully, the task returns the serialized result."""
    from app.core.orchestrator import OrchestratorResult
    from app.workers.tasks import execute_workflow_task

    mock_result = OrchestratorResult(
        run_id="run_ok_001",
        status=RunStatus.COMPLETED,
        final_output="All steps completed.",
        steps_completed=2,
        steps_total=2,
    )

    execute_workflow_task.push_request(retries=0, id="test_task_003")
    try:
        with patch("app.workers.tasks.asyncio.run", return_value=mock_result):
            result = execute_workflow_task.run(
                run_id="run_ok_001", input_type="log", raw_input="ERROR: timeout"
            )
    finally:
        execute_workflow_task.pop_request()

    assert result["status"] == RunStatus.COMPLETED
    assert result["run_id"] == "run_ok_001"
