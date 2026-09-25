"""Reusable FastAPI dependencies.

Wiring lives here so that route modules declare *what* they need rather than
how it is constructed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.comparisons import ComparisonService
from app.services.events import EventService
from app.services.health import HealthService
from app.services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Pagination
from app.services.projects import ProjectService
from app.services.runs import RunService

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_health_service(session: SessionDep, settings: SettingsDep) -> HealthService:
    """Construct the health service for a request."""
    return HealthService(session=session, settings=settings)


def get_project_service(session: SessionDep) -> ProjectService:
    """Construct the project service for a request."""
    return ProjectService(session=session)


def get_run_service(session: SessionDep) -> RunService:
    """Construct the run service for a request."""
    return RunService(session=session)


def get_event_service(session: SessionDep) -> EventService:
    """Construct the event service for a request."""
    return EventService(session=session)


def get_comparison_service(session: SessionDep) -> ComparisonService:
    """Construct the comparison service for a request."""
    return ComparisonService(session=session)


def get_pagination(
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page.")
    ] = DEFAULT_PAGE_SIZE,
) -> Pagination:
    """Translate query parameters into framework-free pagination."""
    return Pagination(page=page, page_size=page_size)


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
EventServiceDep = Annotated[EventService, Depends(get_event_service)]
ComparisonServiceDep = Annotated[ComparisonService, Depends(get_comparison_service)]
PaginationDep = Annotated[Pagination, Depends(get_pagination)]
