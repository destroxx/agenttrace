"""Tests for application assembly.

Assertions go through the OpenAPI schema rather than `app.routes`: FastAPI
wraps included routers in a private lazy-resolution object, so the schema is
the stable public view of what the app exposes.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__


def test_openapi_documents_the_health_endpoint(app: FastAPI) -> None:
    schema = app.openapi()

    assert schema["info"]["title"] == "AgentTrace API"
    assert schema["info"]["version"] == __version__
    assert "/health" in schema["paths"]

    responses = schema["paths"]["/health"]["get"]["responses"]
    assert "200" in responses
    assert "503" in responses


def test_app_exposes_only_the_health_endpoint(app: FastAPI) -> None:
    """This milestone ships one endpoint; guards against accidental surface."""
    documented = set(app.openapi()["paths"])

    assert documented == {"/health"}


async def test_cors_allows_the_web_app_origin(app: FastAPI) -> None:
    """The Next.js dev server must be able to call the API from the browser."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"] == "http://localhost:3000"
    )
