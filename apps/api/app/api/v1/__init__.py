"""Version 1 of the AgentTrace REST API."""

from fastapi import APIRouter

from app.api.v1 import events, projects, runs

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(projects.router)
v1_router.include_router(runs.router)
v1_router.include_router(events.router)

__all__ = ["v1_router"]
