from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.schemas import FailureBreakdown, HealthResponse, MetricsResponse
from app.db.session import get_db
from app.services import metrics_service
from app.services.prometheus_service import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(db: AsyncSession = Depends(get_db)) -> MetricsResponse:
    """DB-backed aggregate metrics — accurate across all worker processes."""
    data = await metrics_service.get_metrics(db)
    data["failure_breakdown"] = FailureBreakdown(**data["failure_breakdown"])
    return MetricsResponse(**data)


@router.get("/metrics/prometheus", include_in_schema=False)
async def prometheus_metrics() -> PlainTextResponse:
    """
    Prometheus text-format scrape endpoint.
    Tracks API-layer metrics (submissions, HTTP layer).
    Mount Prometheus to scrape this at /metrics/prometheus.
    """
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
