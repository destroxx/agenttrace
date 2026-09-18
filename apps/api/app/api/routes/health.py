"""Health endpoint.

The handler contains no business logic: it delegates to `HealthService` and
maps the resulting report onto an HTTP status code.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.dependencies import HealthServiceDep
from app.schemas.health import HealthReport

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthReport,
    summary="Report API and dependency health",
    responses={
        status.HTTP_200_OK: {"description": "API and all dependencies are healthy."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "A dependency is unreachable.",
            "model": HealthReport,
        },
    },
)
async def read_health(service: HealthServiceDep, response: Response) -> HealthReport:
    """Return the health report, degrading to 503 when a dependency is down."""
    report = await service.check()
    if report.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
