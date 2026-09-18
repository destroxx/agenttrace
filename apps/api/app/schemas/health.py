"""Response contract for the health endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ComponentStatus = Literal["up", "down"]
OverallStatus = Literal["ok", "degraded"]


class ComponentHealth(BaseModel):
    """Health of a single dependency the API relies on."""

    status: ComponentStatus
    latency_ms: float | None = Field(
        default=None,
        description="Round-trip time of the probe, in milliseconds.",
    )
    error: str | None = Field(
        default=None,
        description="Failure detail when status is 'down'.",
    )


class HealthReport(BaseModel):
    """Aggregate health of the API and its dependencies."""

    status: OverallStatus
    version: str
    environment: str
    checks: dict[str, ComponentHealth]
