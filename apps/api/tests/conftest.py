"""Shared test fixtures.

Configuration is pinned via environment variables here so the suite never
depends on a developer's local `.env` (environment variables take precedence
over the dotenv file in pydantic-settings).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

TEST_ENV = {
    "ENVIRONMENT": "ci",
    "DEBUG": "false",
    "POSTGRES_HOST": os.environ.get("POSTGRES_HOST", "localhost"),
    "POSTGRES_PORT": os.environ.get("POSTGRES_PORT", "5432"),
    "POSTGRES_DB": os.environ.get("POSTGRES_DB", "agenttrace"),
    "POSTGRES_USER": os.environ.get("POSTGRES_USER", "agenttrace"),
    "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD", "test-password"),
}


@pytest.fixture(autouse=True)
def _pinned_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin settings-relevant environment variables for every test."""
    from app.config import get_settings

    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app() -> FastAPI:
    """A freshly built application instance."""
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound directly to the ASGI app (no network involved)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip database-backed tests unless explicitly enabled."""
    if os.environ.get("RUN_INTEGRATION_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set RUN_INTEGRATION_TESTS=1 with Postgres running")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
