"""Event endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.dependencies import EventServiceDep
from app.schemas.event import EventCreate, EventResponse

router = APIRouter(prefix="/runs/{run_id}/events", tags=["events"])

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "No such run."}}


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append an event to a run",
    responses={
        **NOT_FOUND,
        status.HTTP_409_CONFLICT: {
            "description": "The run already has an event at that sequence."
        },
    },
)
async def create_event(
    run_id: uuid.UUID, payload: EventCreate, service: EventServiceDep
) -> EventResponse:
    """Append one event. `sequence` must be unique within the run."""
    event = await service.create(run_id, payload)
    return EventResponse.model_validate(event)


@router.get(
    "",
    response_model=list[EventResponse],
    summary="List a run's events in sequence order",
    responses=NOT_FOUND,
)
async def list_events(
    run_id: uuid.UUID, service: EventServiceDep
) -> list[EventResponse]:
    """Return every event of the run, ordered by `sequence` ascending."""
    events = await service.list_for_run(run_id)
    return [EventResponse.model_validate(e) for e in events]
