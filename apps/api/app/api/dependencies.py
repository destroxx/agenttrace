"""Reusable FastAPI dependencies.

Wiring lives here so that route modules declare *what* they need rather than
how it is constructed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.api_keys import ApiKeyService, Caller
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


def get_api_key_service(session: SessionDep, settings: SettingsDep) -> ApiKeyService:
    """Construct the API key service for a request."""
    return ApiKeyService(session=session, admin_key_sha256=settings.admin_key_sha256)


# auto_error=False: a missing or non-Bearer header reaches the service as None
# and gets the API's own 401, not FastAPI's 403. Declaring the scheme also puts
# the padlock and "Authorize" button in /docs.
_bearer = HTTPBearer(auto_error=False, description="An AgentTrace API key.")


async def get_caller(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
) -> Caller:
    """Authenticate the request's bearer key.

    Only write routes depend on this, so reads stay open. It runs before the
    body is validated: an unauthenticated caller gets 401, never a 422 that
    describes what a valid body would look like.
    """
    return await service.authenticate(credentials.credentials if credentials else None)


def get_pagination(
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page.")
    ] = DEFAULT_PAGE_SIZE,
) -> Pagination:
    """Translate query parameters into framework-free pagination."""
    return Pagination(page=page, page_size=page_size)


ApiKeyServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]
CallerDep = Annotated[Caller, Depends(get_caller)]
HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
EventServiceDep = Annotated[EventService, Depends(get_event_service)]
ComparisonServiceDep = Annotated[ComparisonService, Depends(get_comparison_service)]
PaginationDep = Annotated[Pagination, Depends(get_pagination)]

# Documented on every write route. 403 only where a project key can be
# pointed at the wrong project, or at an admin-only route.
WRITE_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "No API key, or an unknown or revoked one."},
    403: {"description": "The key is valid, but not for this project."},
}
ADMIN_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "No API key, or an unknown or revoked one."},
    403: {"description": "A project key was used; this needs the admin key."},
}
