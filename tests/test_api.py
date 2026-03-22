"""
API tests using FastAPI TestClient with mocked DB and Celery.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_mock_run(run_id: str = "run_abc123", status: str = "queued"):
    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.status = status
    mock_run.input_type = "log"
    mock_run.priority = 5
    mock_run.user_id = None
    mock_run.created_at = datetime.now(UTC)
    mock_run.updated_at = datetime.now(UTC)
    mock_run.final_output = None
    mock_run.quality_score = None
    mock_run.quality_breakdown = None
    mock_run.cache_hit = False
    mock_run.safety_flagged = False
    return mock_run


@pytest.fixture
def client():
    """
    Creates a TestClient with the FastAPI app, mocking out the DB engine
    so no real PostgreSQL connection is needed.
    Auth is bypassed via dependency_overrides so existing route tests stay clean.
    """
    with (
        patch("app.main.engine") as mock_engine,
        patch("app.db.session.engine"),
    ):
        mock_engine.dispose = AsyncMock()
        from app.api.deps import require_auth
        from app.main import app
        app.dependency_overrides[require_auth] = lambda: "test-user"
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
        app.dependency_overrides.pop(require_auth, None)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@patch("app.api.routes_workflows.execute_workflow_task")
@patch("app.api.routes_workflows.workflow_service.update_run_status", new_callable=AsyncMock)
@patch("app.api.routes_workflows.workflow_service.create_run", new_callable=AsyncMock)
@patch("app.db.session.AsyncSessionFactory")
def test_submit_workflow_valid(mock_session_factory, mock_create, mock_update, mock_task, client):
    mock_run = _make_mock_run()
    mock_create.return_value = mock_run

    mock_db = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_session_factory.return_value = mock_cm

    mock_task.apply_async.return_value = MagicMock()

    response = client.post("/workflows/submit", json={
        "input_type": "log",
        "raw_input": "ERROR: DB connection timeout at 03:14 UTC",
        "priority": 3,
    })

    assert response.status_code == 202
    assert "run_id" in response.json()


def test_submit_workflow_missing_input(client):
    response = client.post("/workflows/submit", json={"input_type": "log"})
    assert response.status_code == 422


def test_submit_workflow_invalid_input_type(client):
    response = client.post("/workflows/submit", json={
        "input_type": "invalid_type",
        "raw_input": "some content",
    })
    assert response.status_code == 422


def test_submit_workflow_priority_out_of_range(client):
    response = client.post("/workflows/submit", json={
        "input_type": "ticket",
        "raw_input": "some content",
        "priority": 11,
    })
    assert response.status_code == 422


@patch("app.api.routes_runs.workflow_service.get_run", new_callable=AsyncMock)
@patch("app.api.routes_runs.state_manager.get_status", new_callable=AsyncMock, return_value=None)
def test_get_workflow_not_found(mock_status, mock_get, client):
    from app.utils.exceptions import WorkflowNotFoundError
    mock_get.side_effect = WorkflowNotFoundError("run_notexist")
    response = client.get("/workflows/run_notexist")
    assert response.status_code == 404


@patch("app.api.routes_runs.workflow_service.get_run", new_callable=AsyncMock)
def test_get_workflow_steps_not_found(mock_get, client):
    from app.utils.exceptions import WorkflowNotFoundError
    mock_get.side_effect = WorkflowNotFoundError("run_notexist")
    response = client.get("/workflows/run_notexist/steps")
    assert response.status_code == 404


# --- Metrics endpoint tests ---

@patch("app.api.routes_health.metrics_service.get_metrics", new_callable=AsyncMock)
@patch("app.db.session.AsyncSessionFactory")
def test_get_metrics_empty_db(mock_session_factory, mock_get_metrics, client):
    mock_get_metrics.return_value = {
        "total_runs": 0,
        "completed_runs": 0,
        "failed_runs": 0,
        "success_rate": 0.0,
        "avg_latency_ms": 0.0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "failure_breakdown": {"by_status": {}, "by_tool": {}},
    }
    mock_db = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_session_factory.return_value = mock_cm

    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 0
    assert data["success_rate"] == 0.0
    assert data["failure_breakdown"]["by_status"] == {}
    assert data["failure_breakdown"]["by_tool"] == {}


@patch("app.api.routes_health.metrics_service.get_metrics", new_callable=AsyncMock)
@patch("app.db.session.AsyncSessionFactory")
def test_get_metrics_populated(mock_session_factory, mock_get_metrics, client):
    mock_get_metrics.return_value = {
        "total_runs": 50,
        "completed_runs": 45,
        "failed_runs": 4,
        "success_rate": 0.9,
        "avg_latency_ms": 1200.5,
        "total_tokens_in": 50000,
        "total_tokens_out": 25000,
        "failure_breakdown": {
            "by_status": {"failed": 3, "dead_letter": 1},
            "by_tool": {"webhook": 2, "database_query": 1},
        },
    }
    mock_db = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_session_factory.return_value = mock_cm

    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 50
    assert data["success_rate"] == 0.9
    assert data["failure_breakdown"]["by_tool"]["webhook"] == 2


@patch("app.api.routes_health.metrics_service.get_metrics", new_callable=AsyncMock)
@patch("app.db.session.AsyncSessionFactory")
def test_get_metrics_schema_validation(mock_session_factory, mock_get_metrics, client):
    from app.db.schemas import MetricsResponse
    mock_get_metrics.return_value = {
        "total_runs": 10,
        "completed_runs": 8,
        "failed_runs": 2,
        "success_rate": 0.8,
        "avg_latency_ms": 800.0,
        "total_tokens_in": 10000,
        "total_tokens_out": 5000,
        "failure_breakdown": {
            "by_status": {"failed": 2},
            "by_tool": {"log_analysis": 1},
        },
    }
    mock_db = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_session_factory.return_value = mock_cm

    response = client.get("/metrics")
    assert response.status_code == 200
    # Validate full schema conformance
    validated = MetricsResponse.model_validate(response.json())
    assert validated.total_runs == 10
    assert validated.failure_breakdown.by_tool["log_analysis"] == 1


# --- Retry dead-letter endpoint test ---

@patch("app.api.routes_workflows.execute_workflow_task")
@patch("app.api.routes_workflows.workflow_service.update_run_status", new_callable=AsyncMock)
@patch("app.api.routes_workflows.workflow_service.reset_run_for_retry", new_callable=AsyncMock)
@patch("app.api.routes_workflows.workflow_service.get_run", new_callable=AsyncMock)
@patch("app.db.session.AsyncSessionFactory")
def test_retry_dead_letter_run_requeues(mock_sf, mock_get, mock_reset, mock_update, mock_task, client):
    mock_run = _make_mock_run(run_id="run_dead_001", status="dead_letter")
    mock_run.input_type = "log"
    mock_run.raw_input = "ERROR: crash"
    mock_get.return_value = mock_run

    mock_db = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_sf.return_value = mock_cm
    mock_task.apply_async.return_value = MagicMock()

    response = client.post("/workflows/run_dead_001/retry")
    assert response.status_code == 202
    mock_task.apply_async.assert_called_once()
