"""
Tool unit tests. No LLM calls needed — tools are pure functions.
"""

import pytest

from app.tools.database_tool import DatabaseQueryTool
from app.tools.email_tool import EmailDraftTool
from app.tools.log_tool import LogAnalysisTool
from app.tools.webhook_tool import WebhookTool


@pytest.mark.asyncio
class TestLogAnalysisTool:
    async def test_basic_log_analysis(self):
        tool = LogAnalysisTool()
        result = await tool.execute({
            "log_content": "2026-03-20 03:14:00 ERROR DB connection timeout\n2026-03-20 03:14:01 ERROR Retry failed",
        })
        assert result.success is True
        assert result.output["error_count"] == 2
        assert result.output["severity"] in ("high", "critical")

    async def test_empty_log(self):
        tool = LogAnalysisTool()
        result = await tool.execute({"log_content": "INFO: All systems nominal"})
        assert result.success is True
        assert result.output["error_count"] == 0
        assert result.output["severity"] == "low"

    async def test_empty_arguments(self):
        # log_content defaults to "" so the tool handles missing args gracefully
        # (prevents null planner args from crashing the execution pipeline)
        tool = LogAnalysisTool()
        result = await tool.execute({})
        assert result.success is True
        assert result.output["error_count"] == 0
        assert result.output["severity"] == "low"

    async def test_severity_filter(self):
        tool = LogAnalysisTool()
        result = await tool.execute({
            "log_content": "ERROR: fatal\nWARN: slow\nINFO: ok",
            "severity_filter": "ERROR",
        })
        assert result.success is True
        assert len(result.output["filtered_matches"]) >= 1


@pytest.mark.asyncio
class TestEmailDraftTool:
    async def test_basic_email_draft(self):
        tool = EmailDraftTool()
        result = await tool.execute({
            "to_address": "customer@example.com",
            "subject": "Re: Payment issue",
            "context": "Customer reported payment API timeout",
        })
        assert result.success is True
        assert "body" in result.output
        assert len(result.output["body"]) > 10

    async def test_urgent_tone(self):
        tool = EmailDraftTool()
        result = await tool.execute({
            "to_address": "ops@example.com",
            "subject": "Critical: DB Down",
            "context": "Database is unreachable",
            "tone": "urgent",
            "include_escalation_note": True,
        })
        assert result.success is True
        assert "escalat" in result.output["body"].lower()

    async def test_invalid_arguments(self):
        tool = EmailDraftTool()
        result = await tool.execute({})  # missing required fields
        assert result.success is False


@pytest.mark.asyncio
class TestDatabaseQueryTool:
    async def test_query_incidents(self):
        tool = DatabaseQueryTool()
        result = await tool.execute({"query_type": "incidents"})
        assert result.success is True
        assert "records" in result.output
        assert result.output["record_count"] >= 1

    async def test_query_with_filter(self):
        tool = DatabaseQueryTool()
        result = await tool.execute({
            "query_type": "incidents",
            "filters": {"status": "open"},
        })
        assert result.success is True
        for record in result.output["records"]:
            assert record["status"] == "open"

    async def test_query_recent_errors(self):
        tool = DatabaseQueryTool()
        result = await tool.execute({"query_type": "recent_errors"})
        assert result.success is True

    async def test_unknown_query_type(self):
        tool = DatabaseQueryTool()
        result = await tool.execute({"query_type": "unknown_type"})
        assert result.success is False
        assert result.error is not None


@pytest.mark.asyncio
class TestWebhookTool:
    async def test_webhook_post_success(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.tools.webhook_tool.httpx.AsyncClient", return_value=mock_client):
            tool = WebhookTool()
            result = await tool.execute({
                "url": "https://hooks.example.com/alert",
                "payload": {"severity": "high", "message": "DB timeout"},
            })

        assert result.success is True
        assert result.output["status_code"] == 200

    async def test_webhook_failure_status(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = Exception("not json")
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.tools.webhook_tool.httpx.AsyncClient", return_value=mock_client):
            tool = WebhookTool()
            result = await tool.execute({
                "url": "https://hooks.example.com/alert",
                "payload": {"test": True},
            })

        assert result.success is False
        assert "500" in result.error

    async def test_webhook_invalid_arguments(self):
        tool = WebhookTool()
        result = await tool.execute({})
        assert result.success is False


@pytest.mark.asyncio
class TestSlackNotificationTool:
    def _mock_client(self, status_code: int = 200, body: dict | None = None):
        from unittest.mock import AsyncMock, MagicMock
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = body or {"ok": True}
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        return mock_client

    async def test_send_notification_success(self):
        from unittest.mock import patch

        from app.tools.slack_tool import SlackNotificationTool

        with patch("app.tools.slack_tool.httpx.AsyncClient", return_value=self._mock_client()):
            tool = SlackNotificationTool()
            result = await tool.execute({
                "webhook_url": "https://hooks.slack.com/services/test",
                "message": "DB connection pool exhausted on payment-api",
                "title": "Critical Alert",
                "severity": "critical",
                "run_id": "run_abc123",
            })

        assert result.success is True
        assert result.output["status_code"] == 200
        assert result.output["severity"] == "critical"

    async def test_send_notification_slack_error(self):
        from unittest.mock import patch

        from app.tools.slack_tool import SlackNotificationTool

        mock_response_body = {"ok": False, "error": "invalid_payload"}
        mock_client = self._mock_client(status_code=400, body=mock_response_body)

        with patch("app.tools.slack_tool.httpx.AsyncClient", return_value=mock_client):
            tool = SlackNotificationTool()
            result = await tool.execute({
                "webhook_url": "https://hooks.slack.com/services/bad",
                "message": "test",
            })

        assert result.success is False
        assert "400" in result.error

    async def test_send_notification_timeout(self):
        from unittest.mock import AsyncMock, patch

        import httpx

        from app.tools.slack_tool import SlackNotificationTool

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("app.tools.slack_tool.httpx.AsyncClient", return_value=mock_client):
            tool = SlackNotificationTool()
            result = await tool.execute({
                "webhook_url": "https://hooks.slack.com/services/slow",
                "message": "alert",
            })

        assert result.success is False
        assert "timed out" in result.error.lower()

    async def test_invalid_arguments(self):
        from app.tools.slack_tool import SlackNotificationTool
        tool = SlackNotificationTool()
        result = await tool.execute({})  # missing required webhook_url and message
        assert result.success is False


@pytest.mark.asyncio
class TestPagerDutyIncidentTool:
    def _mock_client(self, status_code: int = 202, body: dict | None = None):
        from unittest.mock import AsyncMock, MagicMock
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = body or {
            "status": "success",
            "message": "Event processed",
            "dedup_key": "run_abc123",
        }
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        return mock_client

    async def test_trigger_incident_success(self):
        from unittest.mock import patch

        from app.tools.pagerduty_tool import PagerDutyIncidentTool

        with patch("app.tools.pagerduty_tool.httpx.AsyncClient", return_value=self._mock_client()):
            tool = PagerDutyIncidentTool()
            result = await tool.execute({
                "routing_key": "abc123routingkey",
                "summary": "payment-api DB connection pool exhausted",
                "severity": "critical",
                "action": "trigger",
                "dedup_key": "run_abc123",
                "details": {"error_count": 42, "service": "payment-api"},
            })

        assert result.success is True
        assert result.output["action"] == "trigger"
        assert result.output["severity"] == "critical"
        assert result.output["dedup_key"] == "run_abc123"

    async def test_resolve_incident_success(self):
        from unittest.mock import patch

        from app.tools.pagerduty_tool import PagerDutyIncidentTool

        resolve_body = {"status": "success", "message": "Event processed", "dedup_key": "run_abc123"}
        with patch("app.tools.pagerduty_tool.httpx.AsyncClient",
                   return_value=self._mock_client(status_code=202, body=resolve_body)):
            tool = PagerDutyIncidentTool()
            result = await tool.execute({
                "routing_key": "abc123routingkey",
                "summary": "payment-api recovered",
                "severity": "info",
                "action": "resolve",
                "dedup_key": "run_abc123",
            })

        assert result.success is True
        assert result.output["action"] == "resolve"

    async def test_pagerduty_api_error(self):
        from unittest.mock import patch

        from app.tools.pagerduty_tool import PagerDutyIncidentTool

        error_body = {"status": "invalid event", "message": "Invalid routing key"}
        mock_client = self._mock_client(status_code=400, body=error_body)

        with patch("app.tools.pagerduty_tool.httpx.AsyncClient", return_value=mock_client):
            tool = PagerDutyIncidentTool()
            result = await tool.execute({
                "routing_key": "bad_key",
                "summary": "test incident",
            })

        assert result.success is False
        assert "400" in result.error

    async def test_invalid_arguments(self):
        from app.tools.pagerduty_tool import PagerDutyIncidentTool
        tool = PagerDutyIncidentTool()
        result = await tool.execute({})  # missing required routing_key and summary
        assert result.success is False
