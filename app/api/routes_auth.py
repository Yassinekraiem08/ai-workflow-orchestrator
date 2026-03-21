from fastapi import APIRouter, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
async def get_token(
    api_key: str | None = Security(_api_key_header),
) -> TokenResponse:
    """
    Exchange a valid API key for a short-lived JWT Bearer token.

    Pass the key in the X-API-Key header. The returned token can be used
    in subsequent requests as Authorization: Bearer <token>.
    """
    if not api_key or not auth_service.validate_api_key(api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return TokenResponse(access_token=auth_service.create_access_token(api_key))
