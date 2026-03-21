"""
Auth tests: token endpoint, API key validation, JWT flow, protected route enforcement.
Uses a dedicated client fixture that does NOT override require_auth.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services.auth_service import create_access_token, decode_access_token, validate_api_key

# ---------------------------------------------------------------------------
# Unit tests for auth_service helpers (no HTTP involved)
# ---------------------------------------------------------------------------

class TestValidateApiKey:
    def test_valid_key_returns_true(self):
        assert validate_api_key("dev-key-changeme") is True

    def test_invalid_key_returns_false(self):
        assert validate_api_key("wrong-key") is False

    def test_whitespace_trimmed(self):
        assert validate_api_key("  dev-key-changeme  ") is True

    def test_multiple_keys(self, monkeypatch):
        monkeypatch.setattr(settings, "api_keys", "key-a,key-b,key-c")
        assert validate_api_key("key-a") is True
        assert validate_api_key("key-b") is True
        assert validate_api_key("key-d") is False


class TestJwtHelpers:
    def test_create_and_decode_roundtrip(self):
        token = create_access_token("my-api-key")
        payload = decode_access_token(token)
        assert "sub" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_key_is_abbreviated_in_token(self):
        token = create_access_token("dev-key-changeme")
        payload = decode_access_token(token)
        assert "dev-" in payload["sub"]
        assert "changeme" not in payload["sub"]

    def test_expired_token_raises(self):
        expired_payload = {
            "sub": "dev-****",
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        }
        token = jwt.encode(expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        with pytest.raises(jwt.exceptions.ExpiredSignatureError):
            decode_access_token(token)

    def test_tampered_token_raises(self):
        token = create_access_token("dev-key-changeme")
        tampered = token[:-4] + "XXXX"
        with pytest.raises(jwt.exceptions.InvalidTokenError):
            decode_access_token(tampered)


# ---------------------------------------------------------------------------
# Integration tests: HTTP endpoints + auth middleware
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_client():
    """
    TestClient WITHOUT require_auth override — tests the real auth layer.
    raise_server_exceptions=False so post-auth failures return HTTP codes, not exceptions.
    """
    with (
        patch("app.main.engine") as mock_engine,
        patch("app.db.session.engine"),
    ):
        mock_engine.dispose = AsyncMock()
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestTokenEndpoint:
    def test_valid_key_returns_token(self, auth_client):
        response = auth_client.post("/auth/token", headers={"X-API-Key": "dev-key-changeme"})
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_invalid_key_returns_401(self, auth_client):
        response = auth_client.post("/auth/token", headers={"X-API-Key": "not-valid"})
        assert response.status_code == 401

    def test_missing_key_returns_401(self, auth_client):
        response = auth_client.post("/auth/token")
        assert response.status_code == 401

    def test_returned_token_is_valid_jwt(self, auth_client):
        response = auth_client.post("/auth/token", headers={"X-API-Key": "dev-key-changeme"})
        token = response.json()["access_token"]
        payload = decode_access_token(token)
        assert payload["sub"] is not None


class TestProtectedRoutes:
    _SUBMIT_PAYLOAD = {"input_type": "log", "raw_input": "2026-03-20 ERROR DB timeout"}

    def test_no_auth_returns_401(self, auth_client):
        response = auth_client.post("/workflows/submit", json=self._SUBMIT_PAYLOAD)
        assert response.status_code == 401

    def test_valid_api_key_passes_auth(self, auth_client):
        response = auth_client.post(
            "/workflows/submit",
            json=self._SUBMIT_PAYLOAD,
            headers={"X-API-Key": "dev-key-changeme"},
        )
        assert response.status_code != 401

    def test_valid_jwt_passes_auth(self, auth_client):
        token_resp = auth_client.post(
            "/auth/token", headers={"X-API-Key": "dev-key-changeme"}
        )
        token = token_resp.json()["access_token"]

        response = auth_client.post(
            "/workflows/submit",
            json=self._SUBMIT_PAYLOAD,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code != 401

    def test_invalid_jwt_returns_401(self, auth_client):
        response = auth_client.post(
            "/workflows/submit",
            json=self._SUBMIT_PAYLOAD,
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401

    def test_expired_jwt_returns_401(self, auth_client):
        expired_payload = {
            "sub": "dev-****",
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        }
        token = jwt.encode(
            expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        response = auth_client.post(
            "/workflows/submit",
            json=self._SUBMIT_PAYLOAD,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    def test_get_run_no_auth_returns_401(self, auth_client):
        response = auth_client.get("/workflows/run_abc123")
        assert response.status_code == 401

    def test_health_is_public(self, auth_client):
        response = auth_client.get("/health")
        assert response.status_code == 200
