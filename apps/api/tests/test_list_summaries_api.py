"""API tests for what the list endpoints add for the dashboard.

A run list item carries its event count, duration and verdict; a project list
item carries its run count and last activity. The property worth proving is
not only that the numbers are right but that they are computed by the list
query itself: a page of fifty runs must not cost fifty more queries.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(api_client: AsyncClient, name: str = "Support") -> str:
    response = await api_client.post("/api/v1/projects", json={"name": name})
    return str(response.json()["id"])


async def _ingest(
    api_client: AsyncClient,
    project_id: str,
    *,
    events: int = 2,
    status: str = "completed",
    started: str = "2026-09-18T10:00:00+00:00",
    completed: str = "2026-09-18T10:00:04.250+00:00",
    replay_of: str | None = None,
) -> str:
    run_id = str(uuid.uuid4())
    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest",
        json={
            "id": run_id,
            "agent_name": "support-agent",
            "input": {},
            "status": status,
            "started_at": started,
            "completed_at": completed,
            "replay_of_run_id": replay_of,
            "events": [{"sequence": i, "event_type": "agent_start"} for i in range(events)],
        },
    )
    assert response.status_code == 201, response.text
    return run_id


async def _compare(api_client: AsyncClient, recording: str, replay: str, verdict: str) -> None:
    findings: list[dict[str, Any]] = (
        [{"code": "MISSING_TOOL_CALL", "severity": "error", "message": "m", "details": {}}]
        if verdict == "fail"
        else []
    )
    response = await api_client.post(
        f"/api/v1/runs/{replay}/comparison",
        json={
            "verdict": verdict,
            "recording_run_id": recording,
            "replay_run_id": replay,
            "findings": findings,
        },
    )
    assert response.status_code == 201, response.text


@contextmanager
def _counting_queries(session: AsyncSession) -> Iterator[list[str]]:
    """Record every SQL statement sent on the test session's connection."""
    statements: list[str] = []
    connection = session.bind.sync_connection  # type: ignore[union-attr]

    def _record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        # The test session nests each request in a savepoint (see conftest);
        # those statements are the harness's, not the endpoint's.
        if not statement.startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO")):
            statements.append(statement)

    event.listen(connection, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", _record)


async def test_run_items_carry_event_count_duration_and_verdict(
    api_client: AsyncClient,
) -> None:
    project_id = await _project(api_client)
    recording = await _ingest(api_client, project_id, events=5)
    passed = await _ingest(api_client, project_id, events=3, replay_of=recording)
    failed = await _ingest(api_client, project_id, events=0, replay_of=recording)
    await _compare(api_client, recording, passed, "pass")
    await _compare(api_client, recording, failed, "fail")

    response = await api_client.get(f"/api/v1/projects/{project_id}/runs")

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[recording]["event_count"] == 5
    assert items[passed]["event_count"] == 3
    assert items[failed]["event_count"] == 0
    assert items[recording]["duration_ms"] == 4250
    assert items[recording]["verdict"] is None
    assert items[passed]["verdict"] == "pass"
    assert items[failed]["verdict"] == "fail"
    assert items[passed]["replay_of_run_id"] == recording


async def test_running_run_has_no_duration(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    await api_client.post(
        f"/api/v1/projects/{project_id}/runs", json={"agent_name": "a", "input": {}}
    )

    item = (await api_client.get(f"/api/v1/projects/{project_id}/runs")).json()["items"][0]

    assert item["status"] == "running"
    assert item["duration_ms"] is None
    assert item["event_count"] == 0


async def test_the_single_run_endpoint_is_unchanged(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    run_id = await _ingest(api_client, project_id)

    body = (await api_client.get(f"/api/v1/runs/{run_id}")).json()

    assert not {"event_count", "duration_ms", "verdict"} & set(body)


async def test_runs_filter_by_status(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    completed = await _ingest(api_client, project_id)
    failed = await _ingest(api_client, project_id, status="failed")

    only_failed = await api_client.get(f"/api/v1/projects/{project_id}/runs?status=failed")
    only_completed = await api_client.get(
        f"/api/v1/projects/{project_id}/runs?status=completed"
    )
    invalid = await api_client.get(f"/api/v1/projects/{project_id}/runs?status=done")

    assert [i["id"] for i in only_failed.json()["items"]] == [failed]
    assert only_failed.json()["total"] == 1
    assert [i["id"] for i in only_completed.json()["items"]] == [completed]
    assert invalid.status_code == 422


async def test_project_items_carry_run_count_and_last_activity(
    api_client: AsyncClient,
) -> None:
    busy = await _project(api_client, "busy")
    idle = await _project(api_client, "idle")
    for _ in range(3):
        await _ingest(api_client, busy)
    newest = await api_client.get(
        f"/api/v1/projects/{busy}/runs?page=1&page_size=1"
    )

    items = {
        item["id"]: item
        for item in (await api_client.get("/api/v1/projects?page_size=100")).json()["items"]
    }

    assert items[busy]["run_count"] == 3
    assert items[busy]["last_run_at"] == newest.json()["items"][0]["created_at"]
    assert items[idle]["run_count"] == 0
    assert items[idle]["last_run_at"] is None


async def test_run_list_query_count_does_not_grow_with_the_page(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    small = await _project(api_client, "small")
    await _ingest(api_client, small, events=4)

    large = await _project(api_client, "large")
    large_recording = await _ingest(api_client, large, events=4)
    for index in range(12):
        replay = await _ingest(api_client, large, events=index, replay_of=large_recording)
        await _compare(api_client, large_recording, replay, "fail" if index % 2 else "pass")

    with _counting_queries(db_session) as one_run:
        response = await api_client.get(f"/api/v1/projects/{small}/runs?page_size=100")
        assert len(response.json()["items"]) == 1
    with _counting_queries(db_session) as many_runs:
        response = await api_client.get(f"/api/v1/projects/{large}/runs?page_size=100")
        assert len(response.json()["items"]) == 13

    assert len(one_run) == len(many_runs), (one_run, many_runs)
    # project lookup, total count, the page itself
    assert len(many_runs) == 3


async def test_project_list_query_count_does_not_grow_with_the_page(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await _project(api_client, "first")
    await _ingest(api_client, first)

    with _counting_queries(db_session) as few:
        await api_client.get("/api/v1/projects?page_size=100")
    for index in range(8):
        project_id = await _project(api_client, f"more-{index}")
        await _ingest(api_client, project_id)
    with _counting_queries(db_session) as many:
        response = await api_client.get("/api/v1/projects?page_size=100")

    assert len(response.json()["items"]) >= 9
    assert len(few) == len(many) == 2
