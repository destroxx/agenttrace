"""Project endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.dependencies import PaginationDep, ProjectServiceDep
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectSummary

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
async def create_project(
    payload: ProjectCreate, service: ProjectServiceDep
) -> ProjectResponse:
    """Create a project and return it with its generated id and timestamps."""
    project = await service.create(payload)
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    response_model=Page[ProjectSummary],
    summary="List projects",
)
async def list_projects(
    service: ProjectServiceDep, pagination: PaginationDep
) -> Page[ProjectSummary]:
    """Return one page of projects, newest first, with run counts."""
    rows, total = await service.list(pagination)
    return Page[ProjectSummary](
        items=[
            ProjectSummary(
                **ProjectResponse.model_validate(project).model_dump(),
                run_count=run_count,
                last_run_at=last_run_at,
            )
            for project, run_count, last_run_at in rows
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project",
    responses={status.HTTP_404_NOT_FOUND: {"description": "No such project."}},
)
async def get_project(
    project_id: uuid.UUID, service: ProjectServiceDep
) -> ProjectResponse:
    """Return one project."""
    project = await service.get(project_id)
    return ProjectResponse.model_validate(project)
