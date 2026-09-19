"""Tests for the end-of-run upload."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from fake_api import closed_port, fake_api

from agenttrace import AgentTracer, TracerConfig

PROJECT_ID = "3f1d9c88-5b7a-4f2e-9f6c-1b2a3c4d5e6f"


def _config(url: str, **overrides: object) -> TracerConfig:
    return TracerConfig(api_url=url, project_id=PROJECT_ID, **overrides)  # type: ignore[arg-type]


def test_sync_trace_uploads_one_payload() -> None:
    with fake_api() as api:
        tracer = AgentTracer(_config(api.url))

        with tracer.trace(
            "support-agent", input={"message": "hi"}, agent_version="v1.2.0", env="test"
        ) as trace:
            tracer.record_tool_call("get_order", {"order_id": "A-1"}, response={"ok": True})
            trace.set_output({"message": "done"})

        assert len(api.requests) == 1
        request = api.requests[0]
        assert request.path == f"/api/v1/projects/{PROJECT_ID}/runs/ingest"

        body = request.body
        assert body["id"] == trace.id
        assert body["agent_name"] == "support-agent"
        assert body["agent_version"] == "v1.2.0"
        assert body["input"] == {"message": "hi"}
        assert body["output"] == {"message": "done"}
        assert body["status"] == "completed"
        assert body["metadata"] == {"env": "test"}
        assert [e["event_type"] for e in body["events"]] == [
            "agent_start",
            "tool_call",
            "tool_response",
            "agent_end",
        ]
        # The API types these as AwareDatetime, so both must carry an offset.
        assert datetime.fromisoformat(body["started_at"]).tzinfo is not None
        assert datetime.fromisoformat(body["completed_at"]).tzinfo is not None
        assert trace.uploaded is True


def test_async_trace_uploads_one_payload() -> None:
    with fake_api() as api:
        tracer = AgentTracer(_config(api.url))

        async def main() -> object:
            async with tracer.trace("async-agent", input={"q": "x"}) as trace:
                tracer.record_tool_call("lookup", {"id": 1}, response="ok")
                trace.set_output({"answer": 42})
            return trace

        trace = asyncio.run(main())

        assert len(api.requests) == 1
        body = api.requests[0].body
        assert body["id"] == trace.id
        assert body["agent_name"] == "async-agent"
        assert body["output"] == {"answer": 42}
        assert [e["event_type"] for e in body["events"]] == [
            "agent_start",
            "tool_call",
            "tool_response",
            "agent_end",
        ]
        assert trace.uploaded is True


def test_agent_exception_is_reraised_and_still_uploaded() -> None:
    boom = ValueError("agent blew up")
    with fake_api() as api:
        tracer = AgentTracer(_config(api.url))

        try:
            with tracer.trace("failing-agent") as trace:
                tracer.record_tool_call("search", {"q": "shoes"})
                raise boom
        except ValueError as exc:
            caught = exc

        assert caught is boom
        assert trace.status == "failed"
        assert trace.uploaded is True

        body = api.requests[0].body
        assert body["status"] == "failed"
        error = [e for e in body["events"] if e["event_type"] == "error"][-1]
        assert error["response"] == {"type": "ValueError", "message": "agent blew up"}


def test_conflict_counts_as_stored() -> None:
    with fake_api(status=409) as api:
        tracer = AgentTracer(_config(api.url))

        with tracer.trace("agent") as trace:
            pass

        assert len(api.requests) == 1
        assert trace.uploaded is True


def test_server_error_is_swallowed(caplog) -> None:
    with fake_api(status=500) as api, caplog.at_level(logging.WARNING, logger="agenttrace"):
        tracer = AgentTracer(_config(api.url))

        with tracer.trace("agent") as trace:
            pass

        assert trace.uploaded is False
        messages = [record.getMessage() for record in caplog.records]
        assert any("500" in message for message in messages), messages


def test_api_down_is_swallowed() -> None:
    tracer = AgentTracer(_config(f"http://127.0.0.1:{closed_port()}"))

    with tracer.trace("agent") as trace:
        pass

    assert trace.uploaded is False
    assert trace.status == "completed"


def test_upload_is_bounded_by_the_timeout() -> None:
    with fake_api(delay=5.0) as api:
        tracer = AgentTracer(_config(api.url, timeout_seconds=0.25))

        started = time.perf_counter()
        with tracer.trace("slow-agent") as trace:
            pass
        elapsed = time.perf_counter() - started

        assert trace.uploaded is False
        assert elapsed < 2.0, f"exit took {elapsed:.2f}s; the timeout should have capped it"


def test_no_project_id_makes_no_request() -> None:
    with fake_api() as api:
        tracer = AgentTracer(TracerConfig(api_url=api.url))

        with tracer.trace("agent") as trace:
            tracer.record_tool_call("search", {"q": "shoes"}, response=["a"])

        assert api.requests == []
        assert trace.uploaded is False
        assert tracer.completed_traces == (trace,)


def test_unserialisable_payloads_still_upload() -> None:
    class Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    with fake_api() as api:
        tracer = AgentTracer(_config(api.url))

        with tracer.trace("agent", input={"thing": Opaque()}) as trace:
            tracer.record_tool_call("weird", {"thing": Opaque()}, response=Opaque())
            trace.set_output({"thing": Opaque()})

        assert trace.uploaded is True
        body = api.requests[0].body
        assert body["input"] == {"thing": "<opaque>"}
        response = next(e for e in body["events"] if e["event_type"] == "tool_response")
        assert response["response"] == "<opaque>"


def test_non_dict_input_and_output_are_wrapped() -> None:
    tracer = AgentTracer(TracerConfig())

    with tracer.trace("agent", input="where is my order?") as trace:
        trace.set_output("it ships tomorrow")

    assert trace.input == {"value": "where is my order?"}
    assert trace.output == {"value": "it ships tomorrow"}


def test_completed_traces_are_capped() -> None:
    tracer = AgentTracer(TracerConfig())

    for index in range(105):
        with tracer.trace(f"agent-{index}"):
            pass

    completed = tracer.completed_traces
    assert len(completed) == 100
    # The oldest five were dropped, not the newest.
    assert completed[0].name == "agent-5"
    assert completed[-1].name == "agent-104"
