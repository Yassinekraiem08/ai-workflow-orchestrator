from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.schemas import FailureBreakdown, HealthResponse, MetricsResponse
from app.db.session import get_db
from app.services import metrics_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(db: AsyncSession = Depends(get_db)) -> MetricsResponse:
    data = await metrics_service.get_metrics(db)
    data["failure_breakdown"] = FailureBreakdown(**data["failure_breakdown"])
    return MetricsResponse(**data)
