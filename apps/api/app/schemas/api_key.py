"""API contracts for API keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    """Request body for issuing a project key."""

    name: str | None = Field(
        default=None,
        max_length=255,
        description="A label for people, such as where the key is used.",
        examples=["support-agent production"],
    )


class ApiKeyResponse(BaseModel):
    """A key as listed: everything except the key itself."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str | None
    prefix: str = Field(description="The key's first characters, to tell keys apart.")
    created_at: datetime
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyResponse):
    """A key as issued. The only response that ever contains the key."""

    key: str = Field(
        description=(
            "The key. Store it now: only its hash is kept, so it cannot be shown again."
        )
    )
