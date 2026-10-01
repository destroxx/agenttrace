"""Service layer: business logic, kept out of the transport layer.

Services depend on the database and the schemas. They never import FastAPI,
and they signal failure by raising the domain errors in `exceptions.py`.
"""

from app.services.api_keys import ApiKeyService, Caller
from app.services.comparisons import ComparisonService
from app.services.events import EventService
from app.services.exceptions import (
    AgentTraceError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.services.health import HealthService
from app.services.pagination import Pagination
from app.services.projects import ProjectService
from app.services.runs import RunService

__all__ = [
    "AgentTraceError",
    "ApiKeyService",
    "AuthenticationError",
    "Caller",
    "ComparisonService",
    "ConflictError",
    "EventService",
    "HealthService",
    "NotFoundError",
    "Pagination",
    "PermissionDeniedError",
    "ProjectService",
    "RunService",
    "UnprocessableError",
]
