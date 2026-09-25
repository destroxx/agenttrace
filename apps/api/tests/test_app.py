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


def test_app_exposes_exactly_the_documented_surface(app: FastAPI) -> None:
    """Guards against endpoints appearing by accident."""
    documented = set(app.openapi()["paths"])

    assert documented == {
        "/health",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/comparisons",
        "/api/v1/projects/{project_id}/runs",
        "/api/v1/projects/{project_id}/runs/ingest",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/comparison",
        "/api/v1/runs/{run_id}/complete",
        "/api/v1/runs/{run_id}/events",
    }


def test_domain_errors_are_documented_on_the_endpoints(app: FastAPI) -> None:
    """404 and 409 are part of the contract, not incidental behaviour."""
    paths = app.openapi()["paths"]

    assert "404" in paths["/api/v1/projects/{project_id}"]["get"]["responses"]
    assert "409" in paths["/api/v1/runs/{run_id}/complete"]["post"]["responses"]
    assert "409" in paths["/api/v1/runs/{run_id}/events"]["post"]["responses"]
    ingest = paths["/api/v1/projects/{project_id}/runs/ingest"]["post"]["responses"]
    assert "404" in ingest
    assert "409" in ingest
    comparison = paths["/api/v1/runs/{run_id}/comparison"]
    assert {"404", "409", "422"} <= set(comparison["post"]["responses"])
    assert "404" in comparison["get"]["responses"]
    assert "404" in paths["/api/v1/projects/{project_id}/comparisons"]["get"]["responses"]


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
