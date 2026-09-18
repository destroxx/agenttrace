"""Aggregates every route module into a single router.

`/health` is deliberately unversioned: it describes the process, not the API
contract, and orchestrators probing it should not have to track a version.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health
from app.api.v1 import v1_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(v1_router)
