"""
Auth helpers: API key validation and JWT issuance/verification.
"""

from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings


def validate_api_key(key: str) -> bool:
    """Returns True if the provided key is in the configured API key list."""
    valid_keys = {k.strip() for k in settings.api_keys.split(",") if k.strip()}
    return key.strip() in valid_keys


def create_access_token(api_key: str) -> str:
    """Issues a signed JWT for the given API key. The key itself is not stored in the token."""
    payload = {
        "sub": api_key[:4] + "****",  # abbreviated identifier — never store the raw key
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """
    Decodes and validates a JWT. Raises jwt.exceptions.InvalidTokenError
    (including ExpiredSignatureError) on any failure.
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
