"""API contracts for projects."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    """Request body for creating a project."""

    name: str = Field(min_length=1, max_length=255, examples=["Customer Support Agent"])
    description: str | None = Field(
        default=None,
        examples=["Regression tests for our support agent"],
    )


class ProjectResponse(BaseModel):
    """A project as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
