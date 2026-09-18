"""API tests for projects, against a real PostgreSQL database."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_create_project_returns_id_and_timestamps(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/projects",
        json={
            "name": "Customer Support Agent",
            "description": "Regression tests for our support agent",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["name"] == "Customer Support Agent"
    assert body["description"] == "Regression tests for our support agent"
    assert body["created_at"] is not None
    assert body["updated_at"] is not None


async def test_description_is_optional(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/projects", json={"name": "Minimal"})

    assert response.status_code == 201, response.text
    assert response.json()["description"] is None


async def test_get_project_returns_the_created_project(
    api_client: AsyncClient,
) -> None:
    created = (
        await api_client.post("/api/v1/projects", json={"name": "Lookup"})
    ).json()

    response = await api_client.get(f"/api/v1/projects/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_list_projects_returns_a_page(api_client: AsyncClient) -> None:
    for name in ("alpha", "beta", "gamma"):
        await api_client.post("/api/v1/projects", json={"name": name})

    response = await api_client.get("/api/v1/projects")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert {item["name"] for item in body["items"]} == {"alpha", "beta", "gamma"}


async def test_list_projects_paginates(api_client: AsyncClient) -> None:
    for index in range(5):
        await api_client.post("/api/v1/projects", json={"name": f"p{index}"})

    page_two = await api_client.get("/api/v1/projects?page=2&page_size=2")

    assert page_two.status_code == 200
    body = page_two.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["page"] == 2


async def test_unknown_project_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.get(f"/api/v1/projects/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


async def test_malformed_project_id_is_a_validation_error(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/api/v1/projects/not-a-uuid")

    assert response.status_code == 422


async def test_empty_name_is_rejected(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/projects", json={"name": ""})

    assert response.status_code == 422
