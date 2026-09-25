"""Pydantic schemas describing the API's public request/response contracts.

These are deliberately separate types from the ORM models in `app/models`: the
models describe how rows are stored, these describe what the API accepts and
returns. A route never serialises a SQLAlchemy object directly.
"""

from app.schemas.common import ErrorResponse, Page
from app.schemas.comparison import (
    ComparisonCreate,
    ComparisonResponse,
    ComparisonSummary,
)
from app.schemas.event import EventCreate, EventResponse
from app.schemas.health import ComponentHealth, HealthReport
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectSummary
from app.schemas.run import RunComplete, RunCreate, RunResponse, RunSummary

__all__ = [
    "ComparisonCreate",
    "ComparisonResponse",
    "ComparisonSummary",
    "ComponentHealth",
    "ErrorResponse",
    "EventCreate",
    "EventResponse",
    "HealthReport",
    "Page",
    "ProjectCreate",
    "ProjectResponse",
    "ProjectSummary",
    "RunComplete",
    "RunCreate",
    "RunResponse",
    "RunSummary",
]
