"""Tests for the health endpoint and the service behind it."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_session


class _StubSession:
    """Minimal stand-in for AsyncSession that records or raises on execute()."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))
        if self.error is not None:
            raise self.error


def _override_session(app: FastAPI, session: _StubSession) -> None:
    async def _dependency() -> Any:
        yield session

    app.dependency_overrides[get_session] = _dependency


async def test_health_reports_ok_when_database_answers(
    app: FastAPI, client: AsyncClient
) -> None:
    session = _StubSession()
    _override_session(app, session)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "ci"
    assert body["version"]
    assert body["checks"]["database"]["status"] == "up"
    assert body["checks"]["database"]["latency_ms"] >= 0
    assert session.statements == ["SELECT 1"]


async def test_health_degrades_to_503_when_database_is_unreachable(
    app: FastAPI, client: AsyncClient
) -> None:
    _override_session(
        app,
        _StubSession(error=OperationalError("SELECT 1", {}, Exception("refused"))),
    )

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "down"
    assert "OperationalError" in body["checks"]["database"]["error"]


async def test_health_error_does_not_leak_credentials(
    app: FastAPI, client: AsyncClient
) -> None:
    _override_session(
        app,
        _StubSession(error=OperationalError("SELECT 1", {}, Exception("test-password"))),
    )

    response = await client.get("/health")

    assert response.status_code == 503
    assert "postgresql+asyncpg://" not in response.text


async def test_health_against_real_database(api_client: AsyncClient) -> None:
    """End-to-end probe against the live test database."""
    response = await api_client.get("/health")

    assert response.status_code == 200, response.text
    report = response.json()["checks"]["database"]
    assert report["status"] == "up"
    assert report["latency_ms"] >= 0
