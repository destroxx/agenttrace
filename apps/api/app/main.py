"""Application entrypoint and factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.config import get_settings
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release pooled database connections on shutdown."""
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Build the FastAPI application.

    A factory (rather than a module-level singleton built at import time) keeps
    tests able to construct isolated instances.
    """
    settings = get_settings()
    app = FastAPI(
        title="AgentTrace API",
        version=__version__,
        summary="Record-and-replay regression testing for AI agents.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
