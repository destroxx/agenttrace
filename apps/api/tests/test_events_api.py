"""API tests for events, against a real PostgreSQL database.

Event ordering is the load-bearing property here: replay will reconstruct an
execution from `sequence`, so the API must return a run's events in that order
regardless of the order they were written in.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def _run(api_client: AsyncClient) -> str:
    project = (
        await api_client.post("/api/v1/projects", json={"name": "Support"})
    ).json()
    run = (
        await api_client.post(
            f"/api/v1/projects/{project['id']}/runs",
            json={"agent_name": "support-agent", "input": {"message": "hi"}},
        )
    ).json()
    return str(run["id"])


async def test_create_event(api_client: AsyncClient) -> None:
    run_id = await _run(api_client)

    response = await api_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={
            "sequence": 1,
            "event_type": "tool_call",
            "tool_name": "get_order",
            "arguments": {"order_id": "12345"},
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["run_id"] == run_id
    assert body["sequence"] == 1
    assert body["event_type"] == "tool_call"
    assert body["tool_name"] == "get_order"
    assert body["arguments"] == {"order_id": "12345"}
    assert body["response"] is None
    assert body["duration_ms"] is None


async def test_events_are_returned_in_sequence_order(api_client: AsyncClient) -> None:
    """Insert 3, 1, 2 -- read back 1, 2, 3."""
    run_id = await _run(api_client)
    for sequence in (3, 1, 2):
        await api_client.post(
            f"/api/v1/runs/{run_id}/events",
            json={"sequence": sequence, "event_type": "tool_call"},
        )

    response = await api_client.get(f"/api/v1/runs/{run_id}/events")

    assert response.status_code == 200
    assert [event["sequence"] for event in response.json()] == [1, 2, 3]


async def test_a_full_trace_reads_back_in_order(api_client: AsyncClient) -> None:
    run_id = await _run(api_client)
    trace = [
        {"sequence": 1, "event_type": "agent_start"},
        {
            "sequence": 2,
            "event_type": "tool_call",
            "tool_name": "get_order",
            "arguments": {"order_id": "12345"},
        },
        {
            "sequence": 3,
            "event_type": "tool_response",
            "tool_name": "get_order",
            "response": {"status": "in_transit", "eta": "tomorrow"},
            "duration_ms": 42,
        },
        {"sequence": 4, "event_type": "agent_end"},
    ]
    for event in reversed(trace):
        await api_client.post(f"/api/v1/runs/{run_id}/events", json=event)

    events = (await api_client.get(f"/api/v1/runs/{run_id}/events")).json()

    assert [e["event_type"] for e in events] == [
        "agent_start",
        "tool_call",
        "tool_response",
        "agent_end",
    ]
    assert events[2]["response"] == {"status": "in_transit", "eta": "tomorrow"}
    assert events[2]["duration_ms"] == 42


async def test_duplicate_sequence_within_a_run_is_a_conflict(
    api_client: AsyncClient,
) -> None:
    """Two events cannot claim the same position in one trace."""
    run_id = await _run(api_client)
    body = {"sequence": 1, "event_type": "tool_call"}
    assert (
        await api_client.post(f"/api/v1/runs/{run_id}/events", json=body)
    ).status_code == 201

    response = await api_client.post(f"/api/v1/runs/{run_id}/events", json=body)

    assert response.status_code == 409
    assert "sequence" in response.json()["detail"]


async def test_the_same_sequence_is_fine_in_a_different_run(
    api_client: AsyncClient,
) -> None:
    first, second = await _run(api_client), await _run(api_client)
    body = {"sequence": 1, "event_type": "agent_start"}

    assert (
        await api_client.post(f"/api/v1/runs/{first}/events", json=body)
    ).status_code == 201
    assert (
        await api_client.post(f"/api/v1/runs/{second}/events", json=body)
    ).status_code == 201


async def test_a_completed_run_rejects_new_events(api_client: AsyncClient) -> None:
    """A finished run is a frozen recording."""
    run_id = await _run(api_client)
    await api_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"sequence": 1, "event_type": "agent_start"},
    )
    await api_client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"output": {"message": "done"}, "status": "completed"},
    )

    response = await api_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"sequence": 2, "event_type": "tool_call"},
    )

    assert response.status_code == 409
    assert "frozen" in response.json()["detail"]

    events = (await api_client.get(f"/api/v1/runs/{run_id}/events")).json()
    assert [event["sequence"] for event in events] == [1]


async def test_a_failed_run_rejects_new_events(api_client: AsyncClient) -> None:
    """Failure freezes the trace too -- that is what makes it worth keeping."""
    run_id = await _run(api_client)
    await api_client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"output": {"error": "tool timeout"}, "status": "failed"},
    )

    response = await api_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"sequence": 1, "event_type": "error"},
    )

    assert response.status_code == 409
    assert "failed" in response.json()["detail"]
    assert (await api_client.get(f"/api/v1/runs/{run_id}/events")).json() == []


async def test_a_running_run_still_accepts_events(api_client: AsyncClient) -> None:
    """Regression guard: the freeze must not catch runs that are still open."""
    run_id = await _run(api_client)

    response = await api_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"sequence": 1, "event_type": "agent_start"},
    )

    assert response.status_code == 201
    assert response.json()["sequence"] == 1


async def test_response_may_be_a_non_object(api_client: AsyncClient) -> None:
    """Rule 3: a tool can return a list or a scalar, not only an object."""
    run_id = await _run(api_client)

    response = await api_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={
            "sequence": 1,
            "event_type": "tool_response",
            "response": ["first", "second"],
        },
    )

    assert response.status_code == 201
    assert response.json()["response"] == ["first", "second"]


async def test_events_are_scoped_to_their_run(api_client: AsyncClient) -> None:
    first, second = await _run(api_client), await _run(api_client)
    await api_client.post(
        f"/api/v1/runs/{first}/events",
        json={"sequence": 1, "event_type": "agent_start"},
    )

    assert (await api_client.get(f"/api/v1/runs/{second}/events")).json() == []


async def test_event_on_unknown_run_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.post(
        f"/api/v1/runs/{uuid.uuid4()}/events",
        json={"sequence": 1, "event_type": "agent_start"},
    )

    assert response.status_code == 404


async def test_listing_events_of_unknown_run_returns_404(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get(f"/api/v1/runs/{uuid.uuid4()}/events")

    assert response.status_code == 404


async def test_negative_sequence_is_rejected(api_client: AsyncClient) -> None:
    run_id = await _run(api_client)

    response = await api_client.post(
        f"/api/v1/runs/{run_id}/events",
        json={"sequence": -1, "event_type": "agent_start"},
    )

    assert response.status_code == 422
