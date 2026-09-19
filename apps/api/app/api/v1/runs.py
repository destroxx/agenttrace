"""Run endpoints.

Run collections are addressed under their project; a single run is addressed
directly, because a run id is globally unique and callers holding one should
not have to remember which project it belongs to.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.dependencies import PaginationDep, RunServiceDep
from app.schemas.common import Page
from app.schemas.run import RunComplete, RunCreate, RunIngest, RunResponse

router = APIRouter(tags=["runs"])

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "No such run."}}


@router.post(
    "/projects/{project_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a run",
    responses={status.HTTP_404_NOT_FOUND: {"description": "No such project."}},
)
async def create_run(
    project_id: uuid.UUID, payload: RunCreate, service: RunServiceDep
) -> RunResponse:
    """Start a run. Its status is always `running` on creation."""
    run = await service.create(project_id, payload)
    return RunResponse.model_validate(run)


@router.post(
    "/projects/{project_id}/runs/ingest",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload one finished run with its whole trace",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "No such project."},
        status.HTTP_409_CONFLICT: {"description": "That run id is already stored."},
    },
)
async def ingest_run(
    project_id: uuid.UUID, payload: RunIngest, service: RunServiceDep
) -> RunResponse:
    """Store a finished run and all of its events in one transaction.

    This is the SDK's upload path. It records an execution in memory and sends
    it once, so the run and its trace are written together or not at all --
    a partially stored trace would look to replay like a complete recording of
    an agent that stopped early. The client supplies the run id, which makes a
    retried upload a conflict rather than a duplicate.
    """
    run = await service.ingest(project_id, payload)
    return RunResponse.model_validate(run)


@router.get(
    "/projects/{project_id}/runs",
    response_model=Page[RunResponse],
    summary="List a project's runs",
    responses={status.HTTP_404_NOT_FOUND: {"description": "No such project."}},
)
async def list_project_runs(
    project_id: uuid.UUID, service: RunServiceDep, pagination: PaginationDep
) -> Page[RunResponse]:
    """Return one page of the project's runs, newest first."""
    runs, total = await service.list_for_project(project_id, pagination)
    return Page[RunResponse](
        items=[RunResponse.model_validate(r) for r in runs],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    summary="Get a run",
    responses=NOT_FOUND,
)
async def get_run(run_id: uuid.UUID, service: RunServiceDep) -> RunResponse:
    """Return one run's metadata."""
    run = await service.get(run_id)
    return RunResponse.model_validate(run)


@router.post(
    "/runs/{run_id}/complete",
    response_model=RunResponse,
    summary="Finish a run",
    responses={
        **NOT_FOUND,
        status.HTTP_409_CONFLICT: {"description": "The run has already finished."},
    },
)
async def complete_run(
    run_id: uuid.UUID, payload: RunComplete, service: RunServiceDep
) -> RunResponse:
    """Record a run's output and final status, and stamp `completed_at`."""
    run = await service.complete(run_id, payload)
    return RunResponse.model_validate(run)
