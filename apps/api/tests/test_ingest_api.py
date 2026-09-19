"""API tests for the single-request ingest path, against real PostgreSQL.

Ingest is how the SDK uploads a finished run: one payload, one transaction.
The properties worth pinning down are that nothing is stored when the payload
is rejected, that a retried upload conflicts instead of duplicating, and that
`call_id` survives the round trip so parallel tool calls stay paired.
"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

STARTED = "2026-09-18T10:00:00+00:00"
COMPLETED = "2026-09-18T10:00:04+00:00"


async def _project(api_client: AsyncClient, name: str = "Support") -> str:
    response = await api_client.post("/api/v1/projects", json={"name": name})
    return str(response.json()["id"])


def _payload(**overrides: Any) -> dict[str, Any]:
    """A realistic finished run: start, one tool call answered, end."""
    body: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "agent_name": "support-agent",
        "agent_version": "v1.2.0",
        "input": {"message": "Where is my order?"},
        "output": {"message": "Your order is arriving tomorrow."},
        "status": "completed",
        "started_at": STARTED,
        "completed_at": COMPLETED,
        "metadata": {"user_id": "u-1", "environment": "staging"},
        "events": [
            {"sequence": 1, "event_type": "agent_start"},
            {
                "sequence": 2,
                "event_type": "tool_call",
                "call_id": "call_abc123",
                "tool_name": "get_order",
                "arguments": {"order_id": "12345"},
            },
            {
                "sequence": 3,
                "event_type": "tool_response",
                "call_id": "call_abc123",
                "tool_name": "get_order",
                "response": {"status": "in_transit"},
                "duration_ms": 42,
            },
            {"sequence": 4, "event_type": "agent_end"},
        ],
    }
    body.update(overrides)
    return body


async def test_ingest_stores_the_run_and_its_whole_trace(
    api_client: AsyncClient,
) -> None:
    project_id = await _project(api_client)
    payload = _payload()

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == payload["id"]
    assert body["project_id"] == project_id
    assert body["status"] == "completed"
    assert body["output"] == {"message": "Your order is arriving tomorrow."}
    assert body["started_at"].startswith("2026-09-18T10:00:00")
    assert body["completed_at"].startswith("2026-09-18T10:00:04")

    # and it is persisted, not just echoed
    fetched = (await api_client.get(f"/api/v1/runs/{payload['id']}")).json()
    assert fetched["status"] == "completed"
    assert fetched["agent_version"] == "v1.2.0"


async def test_ingested_events_read_back_in_sequence_order_with_call_id(
    api_client: AsyncClient,
) -> None:
    project_id = await _project(api_client)
    payload = _payload()
    # upload the trace shuffled; ordering is the API's job, not the client's
    payload["events"] = list(reversed(payload["events"]))
    await api_client.post(f"/api/v1/projects/{project_id}/runs/ingest", json=payload)

    events = (await api_client.get(f"/api/v1/runs/{payload['id']}/events")).json()

    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert [event["call_id"] for event in events] == [
        None,
        "call_abc123",
        "call_abc123",
        None,
    ]
    assert events[2]["response"] == {"status": "in_transit"}
    assert events[2]["duration_ms"] == 42


async def test_metadata_round_trips(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    payload = _payload(metadata={"user_id": "u-9", "git_sha": "abc123", "retries": 2})

    created = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert created.json()["metadata"] == {
        "user_id": "u-9",
        "git_sha": "abc123",
        "retries": 2,
    }
    fetched = (await api_client.get(f"/api/v1/runs/{payload['id']}")).json()
    assert fetched["metadata"] == {
        "user_id": "u-9",
        "git_sha": "abc123",
        "retries": 2,
    }


async def test_metadata_is_the_stored_dict_not_sqlalchemy_metadata(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`Run.metadata` is SQLAlchemy's MetaData; the API must never serialise it."""
    from sqlalchemy import MetaData

    from app.models import Run
    from app.schemas.run import RunResponse

    project_id = await _project(api_client)
    payload = _payload(metadata={"environment": "staging"})
    await api_client.post(f"/api/v1/projects/{project_id}/runs/ingest", json=payload)

    run = await db_session.get(Run, uuid.UUID(payload["id"]))
    assert run is not None
    # the trap this guards against
    assert isinstance(run.metadata, MetaData)
    assert run.run_metadata == {"environment": "staging"}

    rendered = RunResponse.model_validate(run)
    assert isinstance(rendered.metadata, dict)
    assert rendered.metadata == {"environment": "staging"}
    assert "metadata" in rendered.model_dump()


async def test_metadata_may_be_omitted(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    payload = _payload()
    del payload["metadata"]

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 201
    assert response.json()["metadata"] is None


async def test_parallel_tool_calls_are_paired_by_call_id(
    api_client: AsyncClient,
) -> None:
    """Two tools called at once: call_id is what tells the pairs apart."""
    project_id = await _project(api_client)
    payload = _payload(
        events=[
            {"sequence": 1, "event_type": "agent_start"},
            {
                "sequence": 2,
                "event_type": "tool_call",
                "call_id": "call_order",
                "tool_name": "get_order",
                "arguments": {"order_id": "12345"},
            },
            {
                "sequence": 3,
                "event_type": "tool_call",
                "call_id": "call_weather",
                "tool_name": "get_weather",
                "arguments": {"city": "Berlin"},
            },
            # answers arrive in the opposite order to the calls
            {
                "sequence": 4,
                "event_type": "tool_response",
                "call_id": "call_weather",
                "tool_name": "get_weather",
                "response": {"forecast": "rain"},
            },
            {
                "sequence": 5,
                "event_type": "tool_response",
                "call_id": "call_order",
                "tool_name": "get_order",
                "response": {"status": "in_transit"},
            },
            {"sequence": 6, "event_type": "agent_end"},
        ]
    )
    await api_client.post(f"/api/v1/projects/{project_id}/runs/ingest", json=payload)

    events = (await api_client.get(f"/api/v1/runs/{payload['id']}/events")).json()

    pairs: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["call_id"] is not None:
            pairs.setdefault(event["call_id"], {})[event["event_type"]] = event

    assert set(pairs) == {"call_order", "call_weather"}
    assert pairs["call_order"]["tool_call"]["arguments"] == {"order_id": "12345"}
    assert pairs["call_order"]["tool_response"]["response"] == {
        "status": "in_transit"
    }
    assert pairs["call_weather"]["tool_call"]["arguments"] == {"city": "Berlin"}
    assert pairs["call_weather"]["tool_response"]["response"] == {"forecast": "rain"}
    # each pair names one tool consistently
    for pair in pairs.values():
        assert pair["tool_call"]["tool_name"] == pair["tool_response"]["tool_name"]


async def test_a_run_may_be_ingested_without_events(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    payload = _payload(events=[])

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 201
    assert (await api_client.get(f"/api/v1/runs/{payload['id']}/events")).json() == []


async def test_ingesting_a_running_status_is_rejected(api_client: AsyncClient) -> None:
    """An ingested run is finished by definition."""
    project_id = await _project(api_client)
    payload = _payload(status="running")

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 422
    assert (await api_client.get(f"/api/v1/runs/{payload['id']}")).status_code == 404


async def test_a_failed_run_may_be_ingested(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    payload = _payload(status="failed", output={"error": "tool timeout"})

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"


async def test_duplicate_sequence_in_the_payload_stores_nothing(
    api_client: AsyncClient,
) -> None:
    """Rejected at the door -- and the run must not exist afterwards."""
    project_id = await _project(api_client)
    payload = _payload(
        events=[
            {"sequence": 1, "event_type": "agent_start"},
            {"sequence": 1, "event_type": "agent_end"},
        ]
    )

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 422
    assert "Duplicate sequence 1" in response.text
    assert (await api_client.get(f"/api/v1/runs/{payload['id']}")).status_code == 404
    assert (await api_client.get(f"/api/v1/projects/{project_id}/runs")).json()[
        "total"
    ] == 0


async def test_completed_before_started_is_rejected(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    payload = _payload(started_at=COMPLETED, completed_at=STARTED)

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 422
    assert "completed_at" in response.text


async def test_identical_start_and_completion_is_allowed(
    api_client: AsyncClient,
) -> None:
    """A run can be fast enough that the clock does not move."""
    project_id = await _project(api_client)
    payload = _payload(started_at=STARTED, completed_at=STARTED)

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 201


async def test_naive_timestamps_are_rejected(api_client: AsyncClient) -> None:
    """Without an offset there is no way to order runs from different hosts."""
    project_id = await _project(api_client)
    payload = _payload(started_at="2026-09-18T10:00:00", completed_at=COMPLETED)

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert response.status_code == 422


async def test_ingest_on_unknown_project_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.post(
        f"/api/v1/projects/{uuid.uuid4()}/runs/ingest", json=_payload()
    )

    assert response.status_code == 404


async def test_re_uploading_the_same_run_is_a_conflict(
    api_client: AsyncClient,
) -> None:
    """A retried upload must not duplicate or extend the stored trace."""
    project_id = await _project(api_client)
    payload = _payload()
    first = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )
    assert first.status_code == 201

    second = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest", json=payload
    )

    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]

    runs = (await api_client.get(f"/api/v1/projects/{project_id}/runs")).json()
    assert runs["total"] == 1
    events = (await api_client.get(f"/api/v1/runs/{payload['id']}/events")).json()
    assert len(events) == 4
