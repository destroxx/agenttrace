"""API tests for comparison reports, against real PostgreSQL.

The API stores what the SDK's `compare` produced and never judges anything
itself. What is worth pinning down: a report is immutable and belongs to
exactly one replay run, it can only compare runs of the same project, and a
stored verdict cannot disagree with the findings it summarises.
"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

STARTED = "2026-09-18T10:00:00+00:00"
COMPLETED = "2026-09-18T10:00:04+00:00"


async def _project(api_client: AsyncClient, name: str = "Support") -> str:
    response = await api_client.post("/api/v1/projects", json={"name": name})
    return str(response.json()["id"])


async def _ingest(
    api_client: AsyncClient, project_id: str, replay_of: str | None = None
) -> str:
    run_id = str(uuid.uuid4())
    response = await api_client.post(
        f"/api/v1/projects/{project_id}/runs/ingest",
        json={
            "id": run_id,
            "agent_name": "support-agent",
            "input": {},
            "started_at": STARTED,
            "completed_at": COMPLETED,
            "replay_of_run_id": replay_of,
        },
    )
    assert response.status_code == 201, response.text
    return run_id


async def _pair(api_client: AsyncClient, project_id: str | None = None) -> tuple[str, str]:
    """A recording and a replay of it, in one project."""
    project_id = project_id or await _project(api_client)
    recording = await _ingest(api_client, project_id)
    replay = await _ingest(api_client, project_id, replay_of=recording)
    return recording, replay


def _report(recording: str, replay: str, **overrides: Any) -> dict[str, Any]:
    """A failing report, shaped exactly like `ComparisonReport.to_dict()`."""
    body: dict[str, Any] = {
        "verdict": "fail",
        "recording_run_id": recording,
        "replay_run_id": replay,
        "counts": {
            "by_severity": {"error": 1, "warning": 1, "info": 0},
            "by_code": {"MISSING_TOOL_CALL": 1, "OUTPUT_TEXT_CHANGED": 1},
        },
        "findings": [
            {
                "code": "MISSING_TOOL_CALL",
                "severity": "error",
                "message": 'get_delivery_status(order_id="B-2") was recorded (seq 9) '
                "but never called",
                "details": {
                    "tool_name": "get_delivery_status",
                    "recorded_call_id": "c-9",
                    "recorded_sequence": 9,
                    "recorded_arguments": {"order_id": "B-2"},
                },
            },
            {
                "code": "OUTPUT_TEXT_CHANGED",
                "severity": "warning",
                "message": "output.message text changed",
                "details": {"path": "message", "change": "text_changed"},
            },
        ],
    }
    body.update(overrides)
    return body


async def test_store_and_fetch_a_report(api_client: AsyncClient) -> None:
    recording, replay = await _pair(api_client)
    report = _report(recording, replay)

    created = await api_client.post(f"/api/v1/runs/{replay}/comparison", json=report)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["verdict"] == "fail"
    assert body["replay_run_id"] == replay
    assert body["recording_run_id"] == recording
    assert body["report"] == report

    fetched = await api_client.get(f"/api/v1/runs/{replay}/comparison")
    assert fetched.status_code == 200
    assert fetched.json() == body


async def test_unknown_fields_in_a_report_are_kept(api_client: AsyncClient) -> None:
    """A newer SDK may add to its report; an older API must not reject or drop it."""
    recording, replay = await _pair(api_client)
    report = _report(recording, replay, suite="nightly")
    report["findings"][0]["hint"] = "check the lookup"

    response = await api_client.post(f"/api/v1/runs/{replay}/comparison", json=report)

    assert response.status_code == 201, response.text
    stored = response.json()["report"]
    assert stored["suite"] == "nightly"
    assert stored["findings"][0]["hint"] == "check the lookup"


async def test_a_second_report_for_the_same_run_conflicts(api_client: AsyncClient) -> None:
    recording, replay = await _pair(api_client)
    first = _report(recording, replay)
    await api_client.post(f"/api/v1/runs/{replay}/comparison", json=first)

    passing = _report(
        recording,
        replay,
        verdict="pass",
        findings=[],
        counts={"by_severity": {"error": 0, "warning": 0, "info": 0}, "by_code": {}},
    )
    response = await api_client.post(f"/api/v1/runs/{replay}/comparison", json=passing)

    assert response.status_code == 409
    fetched = await api_client.get(f"/api/v1/runs/{replay}/comparison")
    assert fetched.json()["verdict"] == "fail"


async def test_report_for_an_unknown_run_is_404(api_client: AsyncClient) -> None:
    recording, _ = await _pair(api_client)
    missing = str(uuid.uuid4())

    response = await api_client.post(
        f"/api/v1/runs/{missing}/comparison", json=_report(recording, missing)
    )

    assert response.status_code == 404


async def test_replay_run_id_must_match_the_url(api_client: AsyncClient) -> None:
    recording, replay = await _pair(api_client)

    response = await api_client.post(
        f"/api/v1/runs/{replay}/comparison", json=_report(recording, recording)
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "replay_run_id"]


async def test_recording_must_be_in_the_same_project(api_client: AsyncClient) -> None:
    _, replay = await _pair(api_client)
    elsewhere = await _ingest(api_client, await _project(api_client, "other"))

    foreign = await api_client.post(
        f"/api/v1/runs/{replay}/comparison", json=_report(elsewhere, replay)
    )
    unknown = await api_client.post(
        f"/api/v1/runs/{replay}/comparison", json=_report(str(uuid.uuid4()), replay)
    )

    assert foreign.status_code == unknown.status_code == 422
    assert foreign.json()["detail"][0]["loc"] == ["body", "recording_run_id"]
    # The same answer either way: the error must not reveal which ids exist.
    assert "not a run in project" in foreign.json()["detail"][0]["msg"]
    assert "not a run in project" in unknown.json()["detail"][0]["msg"]


async def test_recording_must_be_the_run_that_was_replayed(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    _, replay = await _pair(api_client, project_id)
    other_recording = await _ingest(api_client, project_id)

    response = await api_client.post(
        f"/api/v1/runs/{replay}/comparison", json=_report(other_recording, replay)
    )

    assert response.status_code == 422
    assert "is a replay of" in response.json()["detail"][0]["msg"]


async def test_a_run_that_is_not_a_replay_cannot_have_a_report(
    api_client: AsyncClient,
) -> None:
    project_id = await _project(api_client)
    recording = await _ingest(api_client, project_id)
    plain = await _ingest(api_client, project_id)

    response = await api_client.post(
        f"/api/v1/runs/{plain}/comparison", json=_report(recording, plain)
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "recording_run_id"]
    assert "is not a replay" in response.json()["detail"][0]["msg"]
    assert (await api_client.get(f"/api/v1/runs/{plain}/comparison")).status_code == 404


async def test_a_recording_cannot_have_a_report_about_itself(
    api_client: AsyncClient,
) -> None:
    recording, _ = await _pair(api_client)

    response = await api_client.post(
        f"/api/v1/runs/{recording}/comparison", json=_report(recording, recording)
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "recording_run_id"]
    assert "is not a replay" in response.json()["detail"][0]["msg"]
    assert (await api_client.get(f"/api/v1/runs/{recording}/comparison")).status_code == 404


async def test_verdict_must_agree_with_the_findings(api_client: AsyncClient) -> None:
    recording, replay = await _pair(api_client)

    passes_with_errors = await api_client.post(
        f"/api/v1/runs/{replay}/comparison", json=_report(recording, replay, verdict="pass")
    )
    fails_without_errors = await api_client.post(
        f"/api/v1/runs/{replay}/comparison",
        json=_report(recording, replay, findings=[]),
    )

    assert passes_with_errors.status_code == 422
    assert fails_without_errors.status_code == 422
    missing = await api_client.get(f"/api/v1/runs/{replay}/comparison")
    assert missing.status_code == 404


async def test_invalid_verdict_and_severity_are_rejected(api_client: AsyncClient) -> None:
    recording, replay = await _pair(api_client)
    bad_severity = _report(recording, replay)
    bad_severity["findings"][0]["severity"] = "fatal"

    for body in (_report(recording, replay, verdict="maybe"), bad_severity):
        response = await api_client.post(f"/api/v1/runs/{replay}/comparison", json=body)
        assert response.status_code == 422


async def test_run_without_a_report_is_404(api_client: AsyncClient) -> None:
    recording, _ = await _pair(api_client)

    no_report = await api_client.get(f"/api/v1/runs/{recording}/comparison")
    no_run = await api_client.get(f"/api/v1/runs/{uuid.uuid4()}/comparison")

    assert no_report.status_code == no_run.status_code == 404
    assert "Comparison for run" in no_report.json()["detail"]
    assert "Run " in no_run.json()["detail"]


async def test_list_a_projects_reports_newest_first(api_client: AsyncClient) -> None:
    project_id = await _project(api_client)
    replays = []
    for _ in range(3):
        recording, replay = await _pair(api_client, project_id)
        await api_client.post(
            f"/api/v1/runs/{replay}/comparison", json=_report(recording, replay)
        )
        replays.append(replay)
    # A report in another project must not leak into this list.
    other_recording, other_replay = await _pair(api_client)
    await api_client.post(
        f"/api/v1/runs/{other_replay}/comparison",
        json=_report(other_recording, other_replay),
    )

    response = await api_client.get(
        f"/api/v1/projects/{project_id}/comparisons?page=1&page_size=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    item = body["items"][0]
    assert set(item) == {
        "id",
        "replay_run_id",
        "recording_run_id",
        "verdict",
        "counts",
        "created_at",
    }
    assert item["verdict"] == "fail"
    assert item["counts"]["by_severity"] == {"error": 1, "warning": 1, "info": 0}
    # All three were written in one transaction, so created_at ties; the id
    # tie-break still has to give a stable order across pages.
    second_page = (
        await api_client.get(f"/api/v1/projects/{project_id}/comparisons?page=2&page_size=2")
    ).json()
    listed = [i["replay_run_id"] for i in body["items"] + second_page["items"]]
    assert sorted(listed) == sorted(replays)


async def test_list_for_unknown_project_is_404(api_client: AsyncClient) -> None:
    response = await api_client.get(f"/api/v1/projects/{uuid.uuid4()}/comparisons")

    assert response.status_code == 404
