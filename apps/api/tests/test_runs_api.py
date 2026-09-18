"""API tests for runs, against a real PostgreSQL database."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

RUN_BODY = {
    "agent_name": "support-agent",
    "agent_version": "v1.2.0",
    "input": {"message": "Where is my order?"},
}


async def _project(api_client: AsyncClient, name: str = "Support") -> str:
    response = await api_client.post("/api/v1/projects", json={"name": name})
    return str(response.json()["id"])


async def test_create_run_starts_in_running_status(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs", json=RUN_BODY
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["project_id"] == project_id
    assert body["agent_name"] == "support-agent"
    assert body["agent_version"] == "v1.2.0"
    assert body["input"] == {"message": "Where is my order?"}
    assert body["output"] is None
    assert body["completed_at"] is None
    assert body["started_at"] is not None


async def test_run_input_accepts_arbitrary_json(api_client: AsyncClient) -> None:
    """Rule 3: agent payloads have no fixed shape."""
    project_id = await _project(api_client)
    nested = {
        "messages": [{"role": "user", "content": "hi"}],
        "config": {"temperature": 0.2, "tools": ["a", "b"]},
        "flag": True,
    }

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"agent_name": "a", "input": nested},
    )

    assert response.status_code == 201
    assert response.json()["input"] == nested


async def test_get_run(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    created = (
        await api_client.post(f"/api/v1/projects/{project_id}/runs", json=RUN_BODY)
    ).json()

    response = await api_client.get(f"/api/v1/runs/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_list_project_runs_paginates(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    for index in range(3):
        await api_client.post(
            f"/api/v1/projects/{project_id}/runs",
            json={"agent_name": f"agent-{index}", "input": {}},
        )

    response = await api_client.get(
        f"/api/v1/projects/{project_id}/runs?page=1&page_size=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_runs_are_scoped_to_their_project(api_client: AsyncClient) -> None:
    first = await _project(api_client, "first")
    second = await _project(api_client, "second")
    await api_client.post(
        f"/api/v1/projects/{first}/runs", json={"agent_name": "a", "input": {}}
    )

    response = await api_client.get(f"/api/v1/projects/{second}/runs")

    assert response.json()["total"] == 0


async def test_run_on_unknown_project_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.post(
        f"/api/v1/projects/{uuid.uuid4()}/runs", json=RUN_BODY
    )

    assert response.status_code == 404


async def test_unknown_run_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.get(f"/api/v1/runs/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_complete_run_records_output_status_and_timestamp(
    api_client: AsyncClient,
) -> None:
    project_id = await _project(api_client)
    run = (
        await api_client.post(f"/api/v1/projects/{project_id}/runs", json=RUN_BODY)
    ).json()
    assert run["completed_at"] is None

    response = await api_client.post(
        f"/api/v1/runs/{run['id']}/complete",
        json={
            "output": {"message": "Your order is arriving tomorrow."},
            "status": "completed",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["output"] == {"message": "Your order is arriving tomorrow."}
    assert body["completed_at"] is not None

    # and it is persisted, not just echoed
    fetched = (await api_client.get(f"/api/v1/runs/{run['id']}")).json()
    assert fetched["status"] == "completed"
    assert fetched["output"] == {"message": "Your order is arriving tomorrow."}
    assert fetched["completed_at"] == body["completed_at"]


async def test_run_can_be_completed_as_failed(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    run = (
        await api_client.post(f"/api/v1/projects/{project_id}/runs", json=RUN_BODY)
    ).json()

    response = await api_client.post(
        f"/api/v1/runs/{run['id']}/complete",
        json={"status": "failed", "output": {"error": "tool timeout"}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["completed_at"] is not None


async def test_completing_a_finished_run_is_a_conflict(
    api_client: AsyncClient,
) -> None:
    """A recorded trace must not be silently overwritten."""
    project_id = await _project(api_client)
    run = (
        await api_client.post(f"/api/v1/projects/{project_id}/runs", json=RUN_BODY)
    ).json()
    await api_client.post(
        f"/api/v1/runs/{run['id']}/complete", json={"output": {"first": True}}
    )

    response = await api_client.post(
        f"/api/v1/runs/{run['id']}/complete", json={"output": {"second": True}}
    )

    assert response.status_code == 409
    fetched = (await api_client.get(f"/api/v1/runs/{run['id']}")).json()
    assert fetched["output"] == {"first": True}


async def test_completing_an_unknown_run_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.post(
        f"/api/v1/runs/{uuid.uuid4()}/complete", json={"status": "completed"}
    )

    assert response.status_code == 404


async def test_invalid_completion_status_is_rejected(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    run = (
        await api_client.post(f"/api/v1/projects/{project_id}/runs", json=RUN_BODY)
    ).json()

    response = await api_client.post(
        f"/api/v1/runs/{run['id']}/complete", json={"status": "running"}
    )

    assert response.status_code == 422
