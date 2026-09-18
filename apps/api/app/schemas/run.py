"""API contracts for runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    """Request body for starting a run.

    Status is not accepted here: a run always begins as `running`. Only the
    completion endpoint may move it out of that state.
    """

    agent_name: str = Field(min_length=1, max_length=255, examples=["support-agent"])
    agent_version: str | None = Field(default=None, max_length=64, examples=["v1.2.0"])
    input: dict[str, Any] = Field(examples=[{"message": "Where is my order?"}])


class RunComplete(BaseModel):
    """Request body for finishing a run."""

    output: dict[str, Any] | None = Field(
        default=None,
        examples=[{"message": "Your order is arriving tomorrow."}],
    )
    status: Literal["completed", "failed"] = "completed"


class RunResponse(BaseModel):
    """A run as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    agent_name: str
    agent_version: str | None
    input: dict[str, Any]
    output: dict[str, Any] | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
