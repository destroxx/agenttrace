"""Tests for recording as an immutable snapshot, and for closing a trace safely."""

from __future__ import annotations

import asyncio
import json

import pytest
from fake_api import fake_api

from agenttrace import AgentTracer, TracerConfig
from agenttrace.transport import build_payload

PROJECT_ID = "3f1d9c88-5b7a-4f2e-9f6c-1b2a3c4d5e6f"


def _events(trace, event_type: str) -> list:
    return [event for event in trace.events if event.event_type == event_type]


def test_mutating_a_returned_value_does_not_rewrite_the_recording() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    async def get_order(order_id: str) -> dict:
        return {"status": "in_transit", "items": ["shoes"]}

    async def main():
        async with tracer.trace("agent") as trace:
            order = await get_order("A-1")
            order["status"] = "MUTATED"
            order["items"].append("socks")
        return trace, order

    trace, order = asyncio.run(main())

    recorded = _events(trace, "tool_response")[0].response
    assert recorded == {"status": "in_transit", "items": ["shoes"]}
    # The agent's own object is untouched by the recording, and vice versa.
    assert order == {"status": "MUTATED", "items": ["shoes", "socks"]}


def test_mutating_arguments_does_not_rewrite_the_recording() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def fetch(payload: dict) -> str:
        return "ok"

    payload = {"order_id": "A-1", "opts": {"deep": 1}}
    with tracer.trace("agent") as trace:
        fetch(payload)
        payload["order_id"] = "MUTATED"
        payload["opts"]["deep"] = 999

    recorded = _events(trace, "tool_call")[0].arguments
    assert recorded == {"payload": {"order_id": "A-1", "opts": {"deep": 1}}}


def test_mutating_input_after_the_trace_starts_does_not_change_the_upload() -> None:
    question = {"message": "where is my order?", "ctx": {"attempt": 1}}
    context = {"tenant": {"id": "t-1"}}

    with fake_api() as api:
        tracer = AgentTracer(TracerConfig(api_url=api.url, project_id=PROJECT_ID))

        with tracer.trace("agent", input=question, **context) as trace:
            question["ctx"]["attempt"] = 999
            context["tenant"]["id"] = "MUTATED"
            trace.set_output({"done": True})

        body = api.requests[0].body
        assert body["input"] == {"message": "where is my order?", "ctx": {"attempt": 1}}
        assert body["metadata"] == {"tenant": {"id": "t-1"}}


def test_mutating_output_after_set_output_does_not_change_the_upload() -> None:
    answer = {"message": "shipped", "lines": ["a"]}

    with fake_api() as api:
        tracer = AgentTracer(TracerConfig(api_url=api.url, project_id=PROJECT_ID))

        with tracer.trace("agent") as trace:
            trace.set_output(answer)
            answer["message"] = "MUTATED"
            answer["lines"].append("b")

        assert api.requests[0].body["output"] == {"message": "shipped", "lines": ["a"]}


def test_nan_still_produces_a_payload_the_api_would_accept() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    def measure() -> dict:
        return {"score": float("nan"), "ok": True}

    with tracer.trace("agent") as trace:
        measure()

    # Python would happily emit bare NaN, which is not valid JSON; the API
    # rejects it. allow_nan=False is the check that proves it never gets out.
    json.dumps(build_payload(trace), allow_nan=False)

    recorded = _events(trace, "tool_response")[0].response
    assert isinstance(recorded, str)
    assert "nan" in recorded.lower()


def test_circular_response_does_not_break_recording_or_upload() -> None:
    circular: dict = {"name": "loop"}
    circular["self"] = circular

    with fake_api() as api:
        tracer = AgentTracer(TracerConfig(api_url=api.url, project_id=PROJECT_ID))

        @tracer.tool
        def loopy() -> dict:
            return circular

        with tracer.trace("agent") as trace:
            assert loopy() is circular

        assert trace.uploaded is True
        response = next(
            e for e in api.requests[0].body["events"] if e["event_type"] == "tool_response"
        )
        assert isinstance(response["response"], str)


def test_cancelled_tool_is_recorded_and_the_error_reaches_the_caller() -> None:
    tracer = AgentTracer(TracerConfig())

    @tracer.tool
    async def slow_lookup(order_id: str) -> str:
        await asyncio.sleep(5)
        return "never"

    async def main():
        async with tracer.trace("agent") as trace:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(slow_lookup("A-1"), timeout=0.05)
        return trace

    trace = asyncio.run(main())

    call = _events(trace, "tool_call")[0]
    error = _events(trace, "error")[0]
    assert error.call_id == call.call_id
    assert error.tool_name == "slow_lookup"
    assert error.response["type"] == "CancelledError"
    assert error.duration_ms is not None
    # The run itself finished normally: the agent handled the timeout.
    assert trace.status == "completed"


def test_closed_trace_rejects_events_and_keeps_its_list() -> None:
    tracer = AgentTracer(TracerConfig())

    with tracer.trace("agent") as trace:
        tracer.record_tool_call("search", {"q": "shoes"}, response=["a"])

    before = list(trace.events)

    with pytest.raises(RuntimeError, match="already closed"):
        trace.record_event("tool_call", tool_name="late")

    assert trace.events == before
