"""Tests for uploading comparison reports.

A report upload follows the recording rules, not the replay ones: it happens
after the verdict is already known, so a failure to store it is logged and
swallowed -- the caller still gets their report.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from fake_api import closed_port, fake_api

from agenttrace import AgentTracer, ComparisonReport, Recording, TracerConfig

PROJECT_ID = "3f1d9c88-5b7a-4f2e-9f6c-1b2a3c4d5e6f"


def _config(url: str) -> TracerConfig:
    return TracerConfig(api_url=url, project_id=PROJECT_ID)


def _agent(tracer: AgentTracer, *, skip: bool = False) -> Any:
    @tracer.tool
    async def lookup(key: str) -> str:
        return f"value-{key}"

    async def agent(agent_input: dict) -> str:
        async with tracer.trace("lookup-agent", input=agent_input) as trace:
            first = await lookup("a")
            second = "" if skip else await lookup("b")
            trace.set_output({"answer": first + second})
        return first + second

    return agent


def _record(tracer: AgentTracer) -> Recording:
    asyncio.run(_agent(tracer)({"q": "x"}))
    return Recording.from_trace(tracer.completed_traces[-1])


def test_replay_and_compare_uploads_the_report_after_the_replay_run() -> None:
    with fake_api() as api:
        tracer = AgentTracer(_config(api.url))
        recording = _record(tracer)

        result, report = asyncio.run(
            tracer.replay_and_compare(recording, _agent(tracer, skip=True))
        )

        assert result.trace is not None
        paths = [r.path for r in api.requests]
        ingest = f"/api/v1/projects/{PROJECT_ID}/runs/ingest"
        assert paths == [ingest, ingest, f"/api/v1/runs/{result.trace.id}/comparison"]
        # The replay run is stored before the report that points at it.
        assert api.requests[1].body["id"] == result.trace.id
        assert api.requests[2].body == report.to_dict()
        assert api.requests[2].body["verdict"] == "fail"
        assert api.requests[2].body["recording_run_id"] == recording.run_id


def test_upload_report_false_keeps_the_report_local() -> None:
    with fake_api() as api:
        tracer = AgentTracer(_config(api.url))
        recording = _record(tracer)

        _, report = asyncio.run(
            tracer.replay_and_compare(recording, _agent(tracer), upload_report=False)
        )

        assert report.passed
        assert not any(r.path.endswith("/comparison") for r in api.requests)


def test_nothing_is_uploaded_when_upload_is_not_configured() -> None:
    tracer = AgentTracer(TracerConfig())
    recording = _record(tracer)

    _, report = asyncio.run(
        tracer.replay_and_compare(recording, _agent(tracer), upload_report=True)
    )

    assert report.passed
    assert tracer.upload_comparison(report) is False


@pytest.mark.parametrize("status", [500, 404, 422])
def test_a_refused_report_is_logged_not_raised(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    with fake_api() as api:
        tracer = AgentTracer(_config(api.url))
        recording = _record(tracer)
        with caplog.at_level(logging.WARNING, logger="agenttrace"):
            result, report = asyncio.run(
                tracer.replay_and_compare(recording, _agent(tracer, skip=True))
            )
            # Refuse only the report, once the replay run has been accepted.
            assert result.trace is not None
            api.post_statuses[f"/api/v1/runs/{result.trace.id}/comparison"] = status
            assert tracer.upload_comparison(report) is False

    assert report.verdict == "fail"
    assert any(f"failed with status {status}" in m for m in caplog.messages)


def test_an_unreachable_api_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    tracer = AgentTracer(TracerConfig())
    recording = _record(tracer)
    _, report = asyncio.run(tracer.replay_and_compare(recording, _agent(tracer)))
    down = AgentTracer(_config(f"http://127.0.0.1:{closed_port()}"))

    with caplog.at_level(logging.WARNING, logger="agenttrace"):
        assert down.upload_comparison(report) is False

    assert any("upload of comparison" in m for m in caplog.messages)


def test_an_already_stored_report_counts_as_stored() -> None:
    """409 means a report for that run exists: a retried upload is harmless."""
    tracer = AgentTracer(TracerConfig())
    recording = _record(tracer)
    _, report = asyncio.run(tracer.replay_and_compare(recording, _agent(tracer)))

    with fake_api(status=409) as api:
        assert AgentTracer(_config(api.url)).upload_comparison(report) is True
        assert len(api.requests) == 1


def test_a_report_without_a_replay_run_is_not_sent(caplog: pytest.LogCaptureFixture) -> None:
    report = ComparisonReport(
        verdict="fail",
        findings=(),
        counts={"by_severity": {"error": 0, "warning": 0, "info": 0}, "by_code": {}},
        recording_run_id="rec-1",
        replay_run_id=None,
    )

    with fake_api() as api, caplog.at_level(logging.WARNING, logger="agenttrace"):
        assert AgentTracer(_config(api.url)).upload_comparison(report) is False
        assert api.requests == []

    assert any("no replay run id" in m for m in caplog.messages)
