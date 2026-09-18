"""API contracts for events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    """Request body for appending an event to a run.

    `event_type` is a free string rather than an enum: an SDK may record a kind
    of step the platform has not anticipated, and losing it would defeat the
    point of recording. `arguments` and `response` are arbitrary JSON for the
    same reason -- tool payloads have no common shape.
    """

    sequence: int = Field(ge=0, examples=[1])
    event_type: str = Field(min_length=1, max_length=64, examples=["tool_call"])
    tool_name: str | None = Field(default=None, max_length=255, examples=["get_order"])
    arguments: dict[str, Any] | None = Field(
        default=None, examples=[{"order_id": "12345"}]
    )
    response: Any | None = Field(default=None, examples=[{"status": "in_transit"}])
    duration_ms: int | None = Field(default=None, ge=0, examples=[42])


class EventResponse(BaseModel):
    """An event as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    sequence: int
    event_type: str
    tool_name: str | None
    arguments: dict[str, Any] | None
    response: Any | None
    duration_ms: int | None
    created_at: datetime
