"""Comparison report endpoints.

A report is addressed through its replay run, which it belongs to one-to-one;
the project-wide list is addressed under the project, like runs.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.dependencies import ComparisonServiceDep, PaginationDep
from app.schemas.common import Page
from app.schemas.comparison import ComparisonCreate, ComparisonResponse, ComparisonSummary

router = APIRouter(tags=["comparisons"])


@router.post(
    "/runs/{run_id}/comparison",
    response_model=ComparisonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store the comparison report for a replay run",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "No such run."},
        status.HTTP_409_CONFLICT: {"description": "The run already has a report."},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "Invalid body; replay_run_id differs from the URL; the run is not a "
                "replay; or recording_run_id is not a run in the replay's project, or "
                "not the run it replayed."
            )
        },
    },
)
async def create_comparison(
    run_id: uuid.UUID, payload: ComparisonCreate, service: ComparisonServiceDep
) -> ComparisonResponse:
    """Store a report produced by the SDK's `compare` for replay run `run_id`.

    Reports are immutable. The path parameter shares its name with the GET on
    the same URL, so the two are one path in the OpenAPI document.
    """
    comparison = await service.create(run_id, payload)
    return ComparisonResponse.model_validate(comparison)


@router.get(
    "/runs/{run_id}/comparison",
    response_model=ComparisonResponse,
    summary="Get the comparison report for a replay run",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "No such run, or it has no report."}
    },
)
async def get_comparison(
    run_id: uuid.UUID, service: ComparisonServiceDep
) -> ComparisonResponse:
    """Return the report stored for the run."""
    comparison = await service.get_for_run(run_id)
    return ComparisonResponse.model_validate(comparison)


@router.get(
    "/projects/{project_id}/comparisons",
    response_model=Page[ComparisonSummary],
    summary="List a project's comparison reports",
    responses={status.HTTP_404_NOT_FOUND: {"description": "No such project."}},
)
async def list_project_comparisons(
    project_id: uuid.UUID, service: ComparisonServiceDep, pagination: PaginationDep
) -> Page[ComparisonSummary]:
    """Return one page of the project's reports, newest first, without findings."""
    rows, total = await service.list_for_project(project_id, pagination)
    return Page[ComparisonSummary](
        items=[ComparisonSummary.model_validate(row) for row in rows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
