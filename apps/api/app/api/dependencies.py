"""Reusable FastAPI dependencies.

Wiring lives here so that route modules declare *what* they need rather than
how it is constructed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.health import HealthService

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_health_service(session: SessionDep, settings: SettingsDep) -> HealthService:
    """Construct the health service for a request."""
    return HealthService(session=session, settings=settings)


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
