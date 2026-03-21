"""
FastAPI dependency for authentication.

Accepts either:
  - X-API-Key header (raw API key)
  - Authorization: Bearer <jwt> header (JWT issued by POST /auth/token)

Public routes (health, metrics) skip this dependency entirely.
Protected routers declare it at the router level via dependencies=[Depends(require_auth)].
"""

import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.services import auth_service

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(
    api_key: str | None = Security(_api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> str:
    """
    Returns the authenticated identity (abbreviated key ID or JWT sub claim).
    Raises HTTP 401 if neither a valid API key nor a valid Bearer token is present.
    """
    if api_key and auth_service.validate_api_key(api_key):
        return api_key

    if credentials:
        try:
            payload = auth_service.decode_access_token(credentials.credentials)
            return payload["sub"]
        except jwt.exceptions.InvalidTokenError:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
