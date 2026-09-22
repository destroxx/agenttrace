"""Application entrypoint and factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api import api_router
from app.config import get_settings
from app.db.session import dispose_engine
from app.services.exceptions import ConflictError, NotFoundError, UnprocessableError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release pooled database connections on shutdown."""
    yield
    await dispose_engine()


async def _not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
    """Answer a missing entity with 404."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": exc.detail}
    )


async def _conflict_handler(_: Request, exc: ConflictError) -> JSONResponse:
    """Answer a state conflict with 409."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": exc.detail}
    )


async def _unprocessable_handler(_: Request, exc: UnprocessableError) -> JSONResponse:
    """Answer a body that fails a database-backed rule with 422.

    Shaped like FastAPI's own validation errors, so a client handles one 422
    format whether the rule was checked by pydantic or by a service.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": [
                {"type": "value_error", "loc": ["body", exc.field], "msg": exc.detail}
            ]
        },
    )


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
    # Services raise domain errors; the mapping onto HTTP lives here, so no
    # route handler has to translate one into the other.
    app.add_exception_handler(NotFoundError, _not_found_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ConflictError, _conflict_handler)  # type: ignore[arg-type]
    app.add_exception_handler(UnprocessableError, _unprocessable_handler)  # type: ignore[arg-type]

    app.include_router(api_router)
    return app


app = create_app()
